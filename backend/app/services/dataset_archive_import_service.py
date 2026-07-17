from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
import tempfile
from typing import Any
import zipfile

from flask import current_app

from app.extensions import db
from app.models import Dataset, DatasetImage, DatasetTask
from app.services.annotation_storage import save_annotation_result
from app.services.dataset_service import (
    next_dataset_ordinal,
    now_utc,
    sync_dataset_category_rows,
    sync_dataset_stats_from_db,
    sync_dataset_task_stats_from_db,
)
from app.services.image_storage import normalize_uploaded_image, preview_data_url, save_generated_image
from app.services.storage_backend import register_local_asset
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


def import_dataset_archive(
    *,
    dataset: Dataset,
    user_id: str,
    archive_bytes: bytes,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="dataset-archive-") as temp_dir:
        root = Path(temp_dir) / "archive"
        _extract_zip_safely(archive_bytes, root)
        prepared, imported_categories, detected_format, skipped = _prepare_archive(root)
        if not prepared:
            raise DatasetArchiveImportError("压缩包中没有可导入的图片文件。")
        max_images = max(1, int(current_app.config.get("MAX_IMPORTED_IMAGES", 2000)))
        prepared = prepared[:max_images]
        categories = _merge_categories(dataset.categories or [], imported_categories)
        return _persist_archive_images(
            dataset=dataset,
            user_id=user_id,
            prepared=prepared,
            categories=categories,
            detected_format=detected_format,
            skipped=skipped,
        )


def _extract_zip_safely(archive_bytes: bytes, root: Path) -> None:
    try:
        archive = zipfile.ZipFile(BytesIO(archive_bytes))
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
                loaded.append(
                    (
                        "val" if split == "valid" else split,
                        sv.DetectionDataset.from_yolo(
                            str(images_dir), str(labels_dir), str(data_yaml)
                        ),
                    )
                )
        if loaded:
            return _prepare_supervision_datasets(loaded, "yolo")

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
                loaded.append(
                    (
                        split,
                        sv.DetectionDataset.from_coco(
                            str(images_dir), str(annotation_path)
                        ),
                    )
                )
        if loaded:
            return _prepare_supervision_datasets(loaded, "coco")

    voc_annotations = next((path for path in root.rglob("Annotations") if path.is_dir()), None)
    if voc_annotations is not None:
        dataset_root = voc_annotations.parent
        images_dir = dataset_root / "JPEGImages"
        if images_dir.is_dir():
            loaded = [
                (
                    "",
                    sv.DetectionDataset.from_pascal_voc(
                        str(images_dir), str(voc_annotations)
                    ),
                )
            ]
            return _prepare_supervision_datasets(loaded, "voc")

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


def _persist_archive_images(
    *,
    dataset: Dataset,
    user_id: str,
    prepared: list[PreparedArchiveImage],
    categories: list[str],
    detected_format: str,
    skipped: list[str],
) -> dict[str, Any]:
    task = DatasetTask(
        dataset_id=dataset.id,
        user_id=user_id,
        task_type="import",
        task_name=f"导入批次 {int(dataset.task_count or 0) + 1}",
        subject=dataset.name,
        image_count=len(prepared),
        categories=categories,
        config_json={"source": "zip", "detectedFormat": detected_format},
        prompt_json={},
        status="running",
        progress_percent=0,
        api_provider="local",
        started_at=now_utc(),
    )
    db.session.add(task)
    dataset.categories = categories
    sync_dataset_category_rows(dataset)
    db.session.flush()
    next_ordinal = next_dataset_ordinal(dataset)
    annotated_count = 0
    for source_ordinal, item in enumerate(prepared, start=1):
        image_key = f"image-{next_ordinal:06d}"
        saved_path = save_generated_image(
            current_app.config["STORAGE_ROOT"],
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
            annotation_status=("annotated" if item.detections else "empty") if detected_format != "images" else "pending",
            confidence_score=max((float(record["confidence"]) for record in item.detections), default=None),
            detection_categories=sorted({str(record["category"]) for record in item.detections}),
            asset=register_local_asset(
                current_app.config["STORAGE_ROOT"],
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
                current_app.config["STORAGE_ROOT"],
                dataset.id,
                image.id,
                item.detections,
                source="import",
                provider="supervision",
                model=detected_format,
            )
        if item.detections:
            annotated_count += 1
        next_ordinal += 1

    task.images_generated = len(prepared)
    task.selected_count = len(prepared)
    task.progress_percent = 100
    task.status = "completed"
    task.completed_at = now_utc()
    sync_dataset_task_stats_from_db(task)
    sync_dataset_stats_from_db(dataset, commit=False)
    db.session.commit()
    return {
        "importedCount": len(prepared),
        "annotatedCount": annotated_count,
        "emptyAnnotationCount": len(prepared) - annotated_count if detected_format != "images" else 0,
        "skippedCount": len(skipped),
        "skippedFiles": skipped[:10],
        "detectedFormat": detected_format,
    }


def _merge_categories(existing: list[str], imported: list[str]) -> list[str]:
    merged: list[str] = []
    for value in [*existing, *imported]:
        name = str(value).strip()
        if name and name not in merged:
            merged.append(name)
    return merged or ["object"]
