from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
import tempfile
from typing import Any
import zipfile

from flask import current_app
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

from app.extensions import db
from app.models import Dataset, DatasetImage, DatasetTask
from app.services.annotation_storage import save_annotation_result
from app.services.dataset_service import (
    now_utc,
    reserve_dataset_ordinals,
    sync_dataset_category_rows,
    sync_dataset_stats_from_db,
    sync_dataset_task_stats_from_db,
)
from app.services.image_storage import normalize_uploaded_image, preview_data_url, save_generated_image
from app.services.storage_backend import local_backend, register_local_asset
from app.services.supervision_adapter import records_from_detections


IMAGE_SUFFIXES = {".bmp", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"}


class DatasetArchiveImportError(RuntimeError):
    pass


@dataclass
class PreparedArchiveImage:
    path: Path
    image_bytes: bytes
    mime_type: str
    width: int
    height: int
    detections: list[dict[str, Any]]
    split: str


def save_zip_import_source(storage_root: str, task_id: str, upload: FileStorage) -> str:
    """Persist the uploaded ZIP to storage and return the storage key."""
    safe_name = secure_filename(upload.filename or "archive.zip") or "archive.zip"
    if not safe_name.lower().endswith(".zip"):
        safe_name = f"{safe_name}.zip"
    key = f"import_sources/{task_id}/{safe_name}"
    local_backend(storage_root).put_stream(key, upload.stream)
    return key


def resolve_zip_import_source(storage_root: str, relative_path: str) -> Path:
    if not relative_path:
        raise DatasetArchiveImportError("missing zip source path")
    storage_path = Path(storage_root).resolve()
    source_path = (storage_path / relative_path).resolve()
    import_sources_dir = (storage_path / "import_sources").resolve()
    if not source_path.is_relative_to(import_sources_dir):
        raise DatasetArchiveImportError("zip source path is outside storage root")
    return source_path


def cleanup_zip_import_source(storage_root: str, relative_path: str) -> None:
    try:
        source_path = resolve_zip_import_source(storage_root, relative_path)
    except DatasetArchiveImportError:
        return
    source_dir = source_path.parent
    import_sources_dir = (Path(storage_root).resolve() / "import_sources").resolve()
    if source_dir.exists() and source_dir.parent == import_sources_dir:
        shutil.rmtree(source_dir, ignore_errors=True)


def run_archive_import_task(task_id: str) -> dict[str, Any]:
    """Extract and persist a previously saved ZIP archive in the background.

    This function is idempotent: if the task is retried after a soft limit,
    images already linked to the task are skipped.
    """
    task = db.session.get(DatasetTask, task_id)
    if task is None or task.task_type != "import" or (task.config_json or {}).get("source") != "zip":
        raise DatasetArchiveImportError("导入任务不存在或类型不正确。")
    if task.status != "running":
        raise DatasetArchiveImportError("导入任务未处于运行状态。")

    dataset = db.session.get(Dataset, task.dataset_id)
    if dataset is None:
        raise DatasetArchiveImportError("数据集不存在。")

    config = task.config_json or {}
    source_path_value = str(config.get("sourcePath") or "")
    storage_root = current_app.config["STORAGE_ROOT"]
    source_path = resolve_zip_import_source(storage_root, source_path_value)
    if not source_path.exists():
        raise DatasetArchiveImportError("ZIP 源文件不存在，请重新上传。")

    with tempfile.TemporaryDirectory(prefix="dataset-archive-") as temp_dir:
        root = Path(temp_dir) / "archive"
        _extract_zip_safely(source_path, root)
        prepared, imported_categories, detected_format, skipped = _prepare_archive(root)
        if not prepared:
            raise DatasetArchiveImportError("压缩包中没有可导入的图片文件。")

        max_images = max(1, int(current_app.config.get("MAX_IMPORTED_IMAGES", 2000)))
        prepared = prepared[:max_images]
        categories = _merge_categories(dataset.categories or [], imported_categories)

        total_count = len(prepared)
        annotated_count = sum(
            1 for item in prepared if item.detections and detected_format != "images"
        )

        # Idempotency: skip images already imported by a previous attempt.
        existing_count = len(task.images)
        if existing_count >= total_count:
            return _finalize_archive_import_task(
                task=task,
                dataset=dataset,
                total_count=total_count,
                annotated_count=annotated_count,
                skipped=skipped,
                detected_format=detected_format,
                storage_root=storage_root,
                source_path_value=source_path_value,
            )

        remaining = prepared[existing_count:]
        return _persist_prepared_archive_images(
            task=task,
            dataset=dataset,
            prepared=remaining,
            categories=categories,
            detected_format=detected_format,
            skipped=skipped,
            total_count=total_count,
            annotated_count=annotated_count,
            existing_count=existing_count,
            storage_root=storage_root,
            source_path_value=source_path_value,
        )


def _extract_zip_safely(archive_path: Path, root: Path) -> None:
    try:
        archive = zipfile.ZipFile(archive_path)
    except zipfile.BadZipFile as exc:
        raise DatasetArchiveImportError("无法解析 ZIP 压缩包。") from exc
    root.mkdir(parents=True, exist_ok=True)
    with archive:
        for member in archive.infolist():
            target = (root / member.filename).resolve()
            if not target.is_relative_to(root.resolve()):
                raise DatasetArchiveImportError("ZIP 压缩包包含不安全的文件路径。")
        archive.extractall(root)


def _prepare_archive(
    root: Path,
) -> tuple[list[PreparedArchiveImage], list[str], str, list[str]]:
    import supervision as sv

    data_yaml_candidates = sorted(root.rglob("data.yaml"))
    if data_yaml_candidates:
        data_yaml = data_yaml_candidates[0]
        dataset_root = data_yaml.parent
        loaded: list[tuple[str, Any]] = []
        for split in ("train", "valid", "val", "test"):
            split_directories = _find_yolo_split_directories(dataset_root, split)
            if split_directories is not None:
                images_dir, labels_dir = split_directories
                try:
                    loaded.append(
                        (
                            "val" if split == "valid" else split,
                            sv.DetectionDataset.from_yolo(
                                str(images_dir), str(labels_dir), str(data_yaml)
                            ),
                        )
                    )
                except Exception as exc:
                    raise DatasetArchiveImportError(
                        "无法解析 YOLO 标注，请检查 data.yaml 和标签文件。"
                    ) from exc
        if loaded:
            try:
                return _prepare_supervision_datasets(loaded, "yolo")
            except Exception as exc:
                raise DatasetArchiveImportError(
                    "无法解析 YOLO 标注，请检查 data.yaml 和标签文件。"
                ) from exc

    coco_annotations = sorted(root.rglob("instances_*.json"))
    if coco_annotations:
        loaded = []
        for annotation_path in coco_annotations:
            split = annotation_path.stem.removeprefix("instances_")
            dataset_root = annotation_path.parent.parent
            images_dir = dataset_root / split
            if not images_dir.is_dir():
                images_dir = dataset_root / "images" / split
            if images_dir.is_dir():
                try:
                    loaded.append(
                        (
                            split,
                            sv.DetectionDataset.from_coco(
                                str(images_dir), str(annotation_path)
                            ),
                        )
                    )
                except Exception as exc:
                    raise DatasetArchiveImportError(
                        "无法解析 COCO 标注，请检查 JSON 标注文件。"
                    ) from exc
        if loaded:
            try:
                return _prepare_supervision_datasets(loaded, "coco")
            except Exception as exc:
                raise DatasetArchiveImportError(
                    "无法解析 COCO 标注，请检查 JSON 标注文件。"
                ) from exc

    voc_annotations = next((path for path in root.rglob("Annotations") if path.is_dir()), None)
    if voc_annotations is not None:
        dataset_root = voc_annotations.parent
        images_dir = dataset_root / "JPEGImages"
        if images_dir.is_dir():
            try:
                loaded = [
                    (
                        "",
                        sv.DetectionDataset.from_pascal_voc(
                            str(images_dir), str(voc_annotations)
                        ),
                    )
                ]
                return _prepare_supervision_datasets(loaded, "voc")
            except Exception as exc:
                raise DatasetArchiveImportError(
                    "无法解析 Pascal VOC 标注，请检查 XML 标注文件。"
                ) from exc

    return _prepare_plain_images(root)


def _find_yolo_split_directories(dataset_root: Path, split: str) -> tuple[Path, Path] | None:
    candidates = (
        (dataset_root / split / "images", dataset_root / split / "labels"),
        (dataset_root / "images" / split, dataset_root / "labels" / split),
    )
    return next(
        (
            (images_dir, labels_dir)
            for images_dir, labels_dir in candidates
            if images_dir.is_dir() and labels_dir.is_dir()
        ),
        None,
    )


def _prepare_supervision_datasets(
    loaded: list[tuple[str, Any]], detected_format: str
) -> tuple[list[PreparedArchiveImage], list[str], str, list[str]]:
    prepared: list[PreparedArchiveImage] = []
    categories: list[str] = []
    skipped: list[str] = []
    for split, supervision_dataset in loaded:
        categories = _merge_categories(categories, list(supervision_dataset.classes))
        for image_value, _image_data, detections in supervision_dataset:
            image_path = Path(str(image_value))
            normalized = normalize_uploaded_image(image_path.read_bytes())
            if normalized is None:
                skipped.append(image_path.name)
                continue
            prepared.append(
                PreparedArchiveImage(
                    path=image_path,
                    image_bytes=bytes(normalized["image_bytes"]),
                    mime_type=str(normalized["mime_type"]),
                    width=int(normalized["width"]),
                    height=int(normalized["height"]),
                    detections=records_from_detections(
                        detections,
                        list(supervision_dataset.classes),
                        (int(normalized["width"]), int(normalized["height"])),
                    ),
                    split=split,
                )
            )
    return prepared, categories, detected_format, skipped


def _prepare_plain_images(
    root: Path,
) -> tuple[list[PreparedArchiveImage], list[str], str, list[str]]:
    prepared: list[PreparedArchiveImage] = []
    skipped: list[str] = []
    for image_path in sorted(
        path for path in root.rglob("*") if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
    ):
        normalized = normalize_uploaded_image(image_path.read_bytes())
        if normalized is None:
            skipped.append(image_path.name)
            continue
        prepared.append(
            PreparedArchiveImage(
                path=image_path,
                image_bytes=bytes(normalized["image_bytes"]),
                mime_type=str(normalized["mime_type"]),
                width=int(normalized["width"]),
                height=int(normalized["height"]),
                detections=[],
                split="",
            )
        )
    return prepared, [], "images", skipped


def _persist_prepared_archive_images(
    *,
    task: DatasetTask,
    dataset: Dataset,
    prepared: list[PreparedArchiveImage],
    categories: list[str],
    detected_format: str,
    skipped: list[str],
    total_count: int,
    annotated_count: int,
    existing_count: int,
    storage_root: str,
    source_path_value: str,
) -> dict[str, Any]:
    user_id = task.user_id
    next_ordinal = reserve_dataset_ordinals(dataset, len(prepared))

    task.image_count = total_count
    task.categories = categories
    task.progress_percent = 0
    task.status = "running"
    dataset.categories = categories
    sync_dataset_category_rows(dataset)
    db.session.flush()

    for offset, item in enumerate(prepared, start=1):
        source_ordinal = existing_count + offset
        image_key = f"image-{next_ordinal:06d}"
        saved_path = save_generated_image(
            storage_root,
            dataset.id,
            image_key,
            item.image_bytes,
            item.mime_type,
        )
        image = DatasetImage(
            dataset_id=dataset.id,
            source_task_id=task.id,
            source_type="import",
            source_ordinal=source_ordinal,
            ordinal=next_ordinal,
            status="uploaded",
            seed=700000 + next_ordinal,
            prompt_text=f"uploaded image: {item.path.name}",
            diversity_vars={"composition": "uploaded asset", "importSplit": item.split},
            latency_ms=0,
            preview_svg=preview_data_url(item.image_bytes, item.mime_type),
            selected=True,
            annotation_status=("annotated" if item.detections else "empty")
            if detected_format != "images"
            else "pending",
            confidence_score=max(
                (float(record["confidence"]) for record in item.detections), default=None
            ),
            detection_categories=sorted({str(record["category"]) for record in item.detections}),
            asset=register_local_asset(
                storage_root,
                saved_path,
                user_id=user_id,
                dataset_id=dataset.id,
                kind="dataset_image",
                mime_type=item.mime_type,
                original_filename=item.path.name,
                width=item.width,
                height=item.height,
            ),
        )
        db.session.add(image)
        db.session.flush()
        if detected_format != "images":
            save_annotation_result(
                storage_root,
                dataset.id,
                image.id,
                item.detections,
                source="import",
                provider="supervision",
                model=detected_format,
            )

        task.images_generated = source_ordinal
        task.selected_count = source_ordinal
        task.progress_percent = min(100, round(source_ordinal / max(total_count, 1) * 100))
        sync_dataset_task_stats_from_db(task)
        sync_dataset_stats_from_db(dataset, commit=False)
        db.session.commit()
        next_ordinal += 1

    return _finalize_archive_import_task(
        task=task,
        dataset=dataset,
        total_count=total_count,
        annotated_count=annotated_count,
        skipped=skipped,
        detected_format=detected_format,
        storage_root=storage_root,
        source_path_value=source_path_value,
    )


def _finalize_archive_import_task(
    *,
    task: DatasetTask,
    dataset: Dataset,
    total_count: int,
    annotated_count: int,
    skipped: list[str],
    detected_format: str,
    storage_root: str,
    source_path_value: str,
) -> dict[str, Any]:
    summary = {
        "importedCount": total_count,
        "annotatedCount": annotated_count,
        "emptyAnnotationCount": total_count - annotated_count if detected_format != "images" else 0,
        "skippedCount": len(skipped),
        "skippedFiles": skipped[:10],
        "detectedFormat": detected_format,
    }

    task.images_generated = total_count
    task.selected_count = total_count
    task.image_count = total_count
    task.progress_percent = 100
    task.status = "completed"
    task.completed_at = now_utc()
    config = {**(task.config_json or {})}
    runtime = {**(config.get("runtime") or {})}
    runtime.update(
        {
            "importedCount": summary["importedCount"],
            "annotatedCount": summary["annotatedCount"],
            "emptyAnnotationCount": summary["emptyAnnotationCount"],
            "skippedCount": summary["skippedCount"],
            "skippedFiles": summary["skippedFiles"],
            "detectedFormat": summary["detectedFormat"],
            "completedAt": now_utc().isoformat(),
        }
    )
    config["runtime"] = runtime
    task.config_json = config
    sync_dataset_task_stats_from_db(task)
    sync_dataset_stats_from_db(dataset, commit=False)
    db.session.commit()

    if task.source_asset is not None:
        task.source_asset.status = "deleted"
        task.source_asset.deleted_at = now_utc()
        db.session.commit()
    cleanup_zip_import_source(storage_root, source_path_value)

    return summary


def _merge_categories(existing: list[str], imported: list[str]) -> list[str]:
    merged: list[str] = []
    for value in [*existing, *imported]:
        name = str(value).strip()
        if name and name not in merged:
            merged.append(name)
    return merged or ["object"]
