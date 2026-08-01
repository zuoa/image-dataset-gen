from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
import tempfile
from typing import Any
import zipfile

from flask import current_app

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
from app.services.storage_backend import register_local_asset


ROBOFLOW_IMPORT_FORMAT = "yolov8"
SUPPORTED_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


class RoboflowImportError(RuntimeError):
    pass


@dataclass
class PreparedRoboflowImage:
    source_path: Path
    image_bytes: bytes
    mime_type: str
    detections: list[dict[str, Any]]
    label_path: Path | None = None


@dataclass(frozen=True)
class YoloLabelIndex:
    paths: tuple[Path, ...]
    by_relative_path: dict[str, Path]
    by_stem: dict[str, tuple[Path, ...]]


def import_roboflow_dataset(
    *,
    dataset: Dataset,
    user_id: str,
    api_key: str,
    workspace: str,
    project: str,
    version: str,
    model_format: str = ROBOFLOW_IMPORT_FORMAT,
    task: DatasetTask | None = None,
) -> dict[str, Any]:
    if model_format != ROBOFLOW_IMPORT_FORMAT:
        raise RoboflowImportError("当前只支持导入 Roboflow YOLOv8 格式。")

    with tempfile.TemporaryDirectory(prefix="roboflow-import-") as temp_dir:
        export_root = _download_roboflow_version(
            api_key=api_key,
            workspace=workspace,
            project=project,
            version=version,
            model_format=model_format,
            target_dir=Path(temp_dir),
        )
        prepared_images, categories, skipped_files = _prepare_roboflow_export(export_root, dataset.categories)

        if not prepared_images:
            raise RoboflowImportError(_empty_export_message(export_root, skipped_files))

        return _persist_prepared_images(
            dataset=dataset,
            user_id=user_id,
            prepared_images=prepared_images,
            categories=categories,
            skipped_files=skipped_files,
            workspace=workspace,
            project=project,
            version=version,
            model_format=model_format,
            task=task,
        )


def _download_roboflow_version(
    *,
    api_key: str,
    workspace: str,
    project: str,
    version: str,
    model_format: str,
    target_dir: Path,
) -> Path:
    try:
        rf = _make_roboflow_client(api_key)
        download_dir = target_dir / "download"
        downloaded = (
            rf.workspace(workspace)
            .project(project)
            .version(version)
            .download(model_format=model_format, location=str(download_dir), overwrite=True)
        )
    except Exception as exc:
        current_app.logger.warning(
            "Roboflow dataset download failed for %s/%s version %s",
            workspace,
            project,
            version,
        )
        raise RoboflowImportError("Roboflow 数据集下载失败，请检查 workspace、project、version 和 API Key。") from exc

    location = getattr(downloaded, "location", None)
    export_root = Path(location) if location else target_dir
    if not export_root.exists():
        raise RoboflowImportError("Roboflow 下载完成，但未找到导出目录。")
    return _resolve_download_root(export_root)


def _make_roboflow_client(api_key: str):
    try:
        from roboflow import Roboflow
    except ImportError as exc:
        raise RoboflowImportError("后端尚未安装 Roboflow SDK。") from exc
    return Roboflow(api_key=api_key)


def _prepare_roboflow_export(
    export_root: Path,
    existing_categories: list[str],
) -> tuple[list[PreparedRoboflowImage], list[str], list[str]]:
    dataset_root = _find_dataset_root(export_root)
    imported_categories = _load_yolo_categories(dataset_root)
    categories = _merge_categories(existing_categories, imported_categories)
    label_categories = imported_categories or categories
    image_paths = _find_image_paths(dataset_root)
    label_index = _build_yolo_label_index(dataset_root)
    skipped_files: list[str] = []
    prepared_images: list[PreparedRoboflowImage] = []
    max_imported_images = max(1, int(current_app.config.get("MAX_IMPORTED_IMAGES", 2000)))

    for image_path in image_paths:
        if len(prepared_images) >= max_imported_images:
            break
        normalized = normalize_uploaded_image(image_path.read_bytes())
        if normalized is None:
            skipped_files.append(image_path.name)
            continue

        label_path = _label_path_for_image(
            image_path,
            dataset_root,
            label_index=label_index,
        )
        prepared_images.append(
            PreparedRoboflowImage(
                source_path=image_path,
                image_bytes=bytes(normalized["image_bytes"]),
                mime_type=str(normalized["mime_type"]),
                detections=_load_yolo_detections(
                    image_path,
                    dataset_root,
                    label_categories,
                    label_path=label_path,
                ),
                label_path=label_path,
            )
        )

    _reject_silently_dropped_annotations(dataset_root, prepared_images, label_index)
    return prepared_images, categories, skipped_files


def _resolve_download_root(export_root: Path) -> Path:
    if export_root.is_file():
        if export_root.suffix.lower() != ".zip":
            return export_root
        extract_root = export_root.parent / f"{export_root.stem}-extracted"
        _extract_zip_safely(export_root, extract_root)
        return extract_root

    if (export_root / "data.yaml").exists() or _find_image_paths(export_root):
        return export_root

    zip_candidates = sorted(path for path in export_root.rglob("*.zip") if path.is_file())
    if not zip_candidates:
        return export_root

    extract_root = export_root / "__extracted__"
    _extract_zip_safely(zip_candidates[0], extract_root)
    return extract_root


def _extract_zip_safely(archive_path: Path, extract_root: Path) -> None:
    extract_root.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path) as archive:
        for member in archive.infolist():
            target = (extract_root / member.filename).resolve()
            if not target.is_relative_to(extract_root.resolve()):
                raise RoboflowImportError("Roboflow 下载包包含不安全的文件路径。")
        archive.extractall(extract_root)


def _persist_prepared_images(
    *,
    dataset: Dataset,
    user_id: str,
    prepared_images: list[PreparedRoboflowImage],
    categories: list[str],
    skipped_files: list[str],
    workspace: str,
    project: str,
    version: str,
    model_format: str,
    task: DatasetTask | None = None,
) -> dict[str, Any]:
    next_ordinal = reserve_dataset_ordinals(dataset, len(prepared_images))
    if task is None:
        task = DatasetTask(
            dataset_id=dataset.id,
            user_id=user_id,
            task_type="import",
            task_name=f"Roboflow 导入批次 {int(dataset.task_count or 0) + 1}",
            subject=dataset.name,
            image_count=0,
            categories=categories,
            config_json={
                "source": "roboflow",
                "workspace": workspace,
                "project": project,
                "version": version,
                "format": model_format,
            },
            prompt_json={},
            status="running",
            progress_percent=0,
            api_provider="roboflow",
            started_at=now_utc(),
        )
        db.session.add(task)
    else:
        task.categories = categories
        task.status = "running"
    dataset.categories = categories
    sync_dataset_category_rows(dataset)
    db.session.flush()
    annotated_count = 0
    empty_annotation_count = 0

    for index, prepared in enumerate(prepared_images, start=1):
        image_key = f"image-{next_ordinal:06d}"
        saved_path = save_generated_image(
            current_app.config["STORAGE_ROOT"],
            dataset.id,
            image_key,
            prepared.image_bytes,
            prepared.mime_type,
        )
        image = DatasetImage(
            dataset_id=dataset.id,
            source_task_id=task.id,
            source_type="roboflow",
            source_ordinal=index,
            ordinal=next_ordinal,
            status="uploaded",
            seed=800000 + next_ordinal,
            prompt_text=f"roboflow image: {prepared.source_path.name}",
            diversity_vars={"composition": "roboflow dataset"},
            latency_ms=0,
            preview_svg=preview_data_url(prepared.image_bytes, prepared.mime_type),
            selected=True,
            annotation_status="annotated" if prepared.detections else "empty",
            confidence_score=max((float(item["confidence"]) for item in prepared.detections), default=None),
            detection_categories=sorted({str(item["category"]) for item in prepared.detections if item.get("category")}),
            asset=register_local_asset(
                current_app.config["STORAGE_ROOT"],
                saved_path,
                user_id=user_id,
                dataset_id=dataset.id,
                kind="dataset_image",
                mime_type=prepared.mime_type,
                original_filename=prepared.source_path.name,
            ),
        )
        db.session.add(image)
        db.session.flush()

        save_annotation_result(
            current_app.config["STORAGE_ROOT"],
            dataset.id,
            image.id,
            prepared.detections,
            source="import",
            provider="roboflow",
            model=model_format,
        )
        if prepared.detections:
            annotated_count += 1
        else:
            empty_annotation_count += 1
        next_ordinal += 1

    task.image_count = len(prepared_images)
    task.images_generated = len(prepared_images)
    task.selected_count = len(prepared_images)
    task.progress_percent = 100
    task.status = "completed"
    task.completed_at = now_utc()
    task.categories = categories
    sync_dataset_task_stats_from_db(task)
    sync_dataset_stats_from_db(dataset, commit=False)
    dataset.annotation_json = {
        **(dataset.annotation_json or {}),
        "provider": "roboflow",
        "format": model_format,
        "status": "completed",
        "detectedImages": annotated_count,
        "emptyLabels": empty_annotation_count,
        "updatedAt": now_utc().isoformat(),
    }
    result_summary = {
        "importedCount": len(prepared_images),
        "annotatedCount": annotated_count,
        "emptyAnnotationCount": empty_annotation_count,
        "skippedCount": len(skipped_files),
        "skippedFiles": skipped_files[:10],
    }
    task.config_json = {**(task.config_json or {}), "resultSummary": result_summary}
    db.session.commit()
    return result_summary


def _find_dataset_root(export_root: Path) -> Path:
    if (export_root / "data.yaml").exists():
        return export_root

    candidates = sorted(export_root.rglob("data.yaml"))
    if candidates:
        return candidates[0].parent

    return export_root


def _find_image_paths(dataset_root: Path) -> list[Path]:
    paths = [
        path
        for path in dataset_root.rglob("*")
        if path.is_file() and path.suffix.lower() in SUPPORTED_IMAGE_SUFFIXES
    ]
    return sorted(paths, key=lambda path: path.relative_to(dataset_root).as_posix())


def _empty_export_message(export_root: Path, skipped_files: list[str]) -> str:
    suffix_counts: dict[str, int] = {}
    sample_files: list[str] = []
    if export_root.exists():
        for path in export_root.rglob("*") if export_root.is_dir() else [export_root]:
            if not path.is_file():
                continue
            suffix = path.suffix.lower() or "<no extension>"
            suffix_counts[suffix] = suffix_counts.get(suffix, 0) + 1
            if len(sample_files) < 8:
                try:
                    sample_files.append(path.relative_to(export_root).as_posix())
                except ValueError:
                    sample_files.append(path.name)

    details: list[str] = []
    if suffix_counts:
        details.append(
            "扫描到的文件类型：" + ", ".join(f"{suffix}={count}" for suffix, count in sorted(suffix_counts.items()))
        )
    if sample_files:
        details.append("示例文件：" + ", ".join(sample_files))
    if skipped_files:
        details.append("图片解码失败：" + ", ".join(skipped_files[:5]))

    if not details:
        return "Roboflow 数据集中没有可导入的图片文件。请确认该版本已生成并包含 train/valid/test 图片。"
    return "Roboflow 数据集中没有可导入的图片文件。" + " ".join(details)


def _load_yolo_categories(dataset_root: Path) -> list[str]:
    data_yaml = dataset_root / "data.yaml"
    if not data_yaml.exists():
        return []

    text = data_yaml.read_text(encoding="utf-8")
    try:
        import yaml

        payload = yaml.safe_load(text) or {}
        names = payload.get("names") if isinstance(payload, dict) else None
        return _normalize_category_names(names)
    except Exception:
        return _parse_category_names_without_yaml(text)


def _normalize_category_names(names: Any) -> list[str]:
    if isinstance(names, dict):
        items = sorted(names.items(), key=lambda item: int(item[0]) if str(item[0]).isdigit() else str(item[0]))
        return [str(value).strip() for _, value in items if str(value).strip()]
    if isinstance(names, list):
        return [str(value).strip() for value in names if str(value).strip()]
    return []


def _parse_category_names_without_yaml(text: str) -> list[str]:
    lines = text.splitlines()
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped.startswith("names:"):
            continue

        inline_value = stripped.removeprefix("names:").strip()
        if inline_value:
            try:
                return _normalize_category_names(ast.literal_eval(inline_value))
            except (SyntaxError, ValueError):
                return [item.strip().strip("'\"") for item in inline_value.strip("[]").split(",") if item.strip()]

        names: list[str] = []
        for nested in lines[index + 1 :]:
            if nested and not nested.startswith((" ", "\t", "-")):
                break
            nested_value = nested.strip()
            if nested_value.startswith("-"):
                value = nested_value.removeprefix("-").strip().strip("'\"")
                if value:
                    names.append(value)
            elif ":" in nested_value:
                _, value = nested_value.split(":", 1)
                value = value.strip().strip("'\"")
                if value:
                    names.append(value)
        return names
    return []


def _merge_categories(existing_categories: list[str], imported_categories: list[str]) -> list[str]:
    merged: list[str] = []
    for category in [*existing_categories, *imported_categories]:
        normalized = str(category).strip()
        if normalized and normalized not in merged:
            merged.append(normalized)
    return merged or ["object"]


def _load_yolo_detections(
    image_path: Path,
    dataset_root: Path,
    categories: list[str],
    *,
    label_path: Path | None = None,
) -> list[dict[str, Any]]:
    if label_path is None:
        label_path = _label_path_for_image(image_path, dataset_root)
    if label_path is None:
        return []

    detections: list[dict[str, Any]] = []
    for line in label_path.read_text(encoding="utf-8-sig").splitlines():
        parts = line.strip().split()
        if len(parts) < 5:
            continue
        try:
            class_id = int(float(parts[0]))
            coordinates = [float(value) for value in parts[1:]]
        except ValueError:
            continue
        parsed = _parse_yolo_coordinates(coordinates)
        if parsed is None:
            continue
        bbox, metadata = parsed
        category = categories[class_id] if 0 <= class_id < len(categories) else f"class_{class_id}"
        detections.append(
            {
                "category": category,
                "confidence": 1.0,
                "bbox": bbox,
                **metadata,
            }
        )
    return detections


def _build_yolo_label_index(dataset_root: Path) -> YoloLabelIndex:
    paths = tuple(
        sorted(
            (
                path
                for path in dataset_root.rglob("*")
                if path.is_file() and path.suffix.casefold() == ".txt"
            ),
            key=lambda path: path.relative_to(dataset_root).as_posix().casefold(),
        )
    )
    by_relative_path = {
        path.relative_to(dataset_root).as_posix().casefold(): path
        for path in paths
    }
    paths_by_stem: dict[str, list[Path]] = {}
    for path in paths:
        if not _is_label_directory_path(path, dataset_root):
            continue
        paths_by_stem.setdefault(path.stem.casefold(), []).append(path)
    return YoloLabelIndex(
        paths=paths,
        by_relative_path=by_relative_path,
        by_stem={key: tuple(value) for key, value in paths_by_stem.items()},
    )


def _label_path_for_image(
    image_path: Path,
    dataset_root: Path,
    *,
    label_index: YoloLabelIndex | None = None,
) -> Path | None:
    label_index = label_index or _build_yolo_label_index(dataset_root)
    relative_path = image_path.relative_to(dataset_root)
    parts = relative_path.parts
    candidate_relative_paths: list[Path] = []

    for images_index, part in enumerate(parts):
        if part.casefold() != "images":
            continue
        candidate_relative_paths.append(
            Path(
                *parts[:images_index],
                "labels",
                *parts[images_index + 1 :],
            ).with_suffix(".txt")
        )

    candidate_relative_paths.extend(
        [
            relative_path.with_suffix(".txt"),
            relative_path.parent / "labels" / relative_path.with_suffix(".txt").name,
            Path("labels") / relative_path.with_suffix(".txt").name,
        ]
    )
    if len(parts) > 1:
        candidate_relative_paths.append(
            Path(*parts[:-1], "labels", relative_path.with_suffix(".txt").name)
        )

    for candidate in candidate_relative_paths:
        matched = label_index.by_relative_path.get(candidate.as_posix().casefold())
        if matched is not None:
            return matched

    same_stem_paths = label_index.by_stem.get(image_path.stem.casefold(), ())
    if len(same_stem_paths) == 1:
        return same_stem_paths[0]
    if len(same_stem_paths) > 1:
        image_parent_parts = {
            part.casefold()
            for part in relative_path.parent.parts
            if part.casefold() != "images"
        }
        scored = [
            (
                len(
                    image_parent_parts
                    & {
                        part.casefold()
                        for part in path.relative_to(dataset_root).parent.parts
                        if part.casefold() != "labels"
                    }
                ),
                path,
            )
            for path in same_stem_paths
        ]
        best_score = max(score for score, _ in scored)
        best_paths = [path for score, path in scored if score == best_score]
        if len(best_paths) == 1:
            return best_paths[0]
    return None


def _is_label_directory_path(path: Path, dataset_root: Path) -> bool:
    return any(
        part.casefold() == "labels"
        for part in path.relative_to(dataset_root).parent.parts
    )


def _reject_silently_dropped_annotations(
    dataset_root: Path,
    prepared_images: list[PreparedRoboflowImage],
    label_index: YoloLabelIndex,
) -> None:
    non_empty_label_paths = [
        path
        for path in label_index.paths
        if _is_label_directory_path(path, dataset_root)
        and path.read_text(encoding="utf-8-sig").strip()
    ]
    unparsed_matched_labels = [
        item.label_path
        for item in prepared_images
        if item.label_path in non_empty_label_paths and not item.detections
    ]
    all_annotations_missing = bool(non_empty_label_paths) and not any(
        item.detections for item in prepared_images
    )
    if not unparsed_matched_labels and not all_annotations_missing:
        return

    failed_paths = unparsed_matched_labels or non_empty_label_paths
    samples = ", ".join(
        path.relative_to(dataset_root).as_posix()
        for path in failed_paths[:5]
    )
    raise RoboflowImportError(
        "Roboflow 导出包包含非空标签文件，但部分或全部标注未能解析，已停止导入以避免标注丢失。"
        f"请检查数据集类型和 YOLOv8 标签格式。示例标签：{samples}"
    )


def _parse_yolo_coordinates(
    coordinates: list[float],
) -> tuple[list[float], dict[str, Any]] | None:
    if len(coordinates) == 4:
        x_center, y_center, width, height = coordinates
        if width <= 0 or height <= 0:
            return None
        return _clip_bbox(x_center, y_center, width, height), {}

    if len(coordinates) < 6 or len(coordinates) % 2 != 0:
        return None
    points = list(zip(coordinates[0::2], coordinates[1::2], strict=True))
    x_values = [point[0] for point in points]
    y_values = [point[1] for point in points]
    left = min(x_values)
    right = max(x_values)
    top = min(y_values)
    bottom = max(y_values)
    width = right - left
    height = bottom - top
    if width <= 0 or height <= 0:
        return None
    return (
        _clip_bbox(
            left + width / 2,
            top + height / 2,
            width,
            height,
        ),
        {"sourceYoloCoordinates": coordinates},
    )


def _clip_bbox(x_center: float, y_center: float, width: float, height: float) -> list[float]:
    width = min(max(width, 0.001), 1.0)
    height = min(max(height, 0.001), 1.0)
    x_center = min(max(x_center, width / 2), 1.0 - width / 2)
    y_center = min(max(y_center, height / 2), 1.0 - height / 2)
    return [round(x_center, 6), round(y_center, 6), round(width, 6), round(height, 6)]
