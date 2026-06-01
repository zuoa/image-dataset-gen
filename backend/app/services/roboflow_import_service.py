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
    next_dataset_ordinal,
    now_utc,
    sync_dataset_stats_inplace,
    sync_dataset_task_inplace,
)
from app.services.image_storage import normalize_uploaded_image, preview_data_url, save_generated_image


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


def import_roboflow_dataset(
    *,
    dataset: Dataset,
    user_id: str,
    api_key: str,
    workspace: str,
    project: str,
    version: str,
    model_format: str = ROBOFLOW_IMPORT_FORMAT,
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
        current_app.logger.exception("Roboflow dataset download failed")
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

        prepared_images.append(
            PreparedRoboflowImage(
                source_path=image_path,
                image_bytes=bytes(normalized["image_bytes"]),
                mime_type=str(normalized["mime_type"]),
                detections=_load_yolo_detections(image_path, dataset_root, label_categories),
            )
        )

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
) -> dict[str, Any]:
    task = DatasetTask(
        dataset_id=dataset.id,
        user_id=user_id,
        task_type="import",
        task_name=f"Roboflow 导入批次 {len(dataset.tasks) + 1}",
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
    dataset.tasks.append(task)
    dataset.categories = categories
    db.session.flush()

    next_ordinal = next_dataset_ordinal(dataset)
    annotated_count = 0
    empty_annotation_count = 0

    for index, prepared in enumerate(prepared_images, start=1):
        image_key = f"image-{next_ordinal:06d}"
        save_generated_image(
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
        )
        db.session.add(image)
        dataset.images.append(image)
        task.images.append(image)
        db.session.flush()

        save_annotation_result(current_app.config["STORAGE_ROOT"], dataset.id, image.id, prepared.detections)
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
    sync_dataset_task_inplace(task)
    sync_dataset_stats_inplace(dataset)
    dataset.annotation_json = {
        **(dataset.annotation_json or {}),
        "provider": "roboflow",
        "format": model_format,
        "status": "completed",
        "detectedImages": annotated_count,
        "emptyLabels": empty_annotation_count,
        "updatedAt": now_utc().isoformat(),
    }
    db.session.commit()

    return {
        "importedCount": len(prepared_images),
        "annotatedCount": annotated_count,
        "emptyAnnotationCount": empty_annotation_count,
        "skippedCount": len(skipped_files),
        "skippedFiles": skipped_files[:10],
    }


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


def _load_yolo_detections(image_path: Path, dataset_root: Path, categories: list[str]) -> list[dict[str, Any]]:
    label_path = _label_path_for_image(image_path, dataset_root)
    if label_path is None:
        return []

    detections: list[dict[str, Any]] = []
    for line in label_path.read_text(encoding="utf-8").splitlines():
        parts = line.strip().split()
        if len(parts) < 5:
            continue
        try:
            class_id = int(float(parts[0]))
            x_center, y_center, width, height = (float(value) for value in parts[1:5])
        except ValueError:
            continue
        if width <= 0 or height <= 0:
            continue
        category = categories[class_id] if 0 <= class_id < len(categories) else f"class_{class_id}"
        detections.append(
            {
                "category": category,
                "confidence": 1.0,
                "bbox": _clip_bbox(x_center, y_center, width, height),
            }
        )
    return detections


def _label_path_for_image(image_path: Path, dataset_root: Path) -> Path | None:
    relative_path = image_path.relative_to(dataset_root)
    parts = relative_path.parts
    candidates: list[Path] = []

    if "images" in parts:
        images_index = parts.index("images")
        label_relative = Path(*parts[:images_index], "labels", *parts[images_index + 1 :]).with_suffix(".txt")
        candidates.append(dataset_root / label_relative)

    candidates.extend(
        [
            image_path.with_suffix(".txt"),
            dataset_root / "labels" / image_path.with_suffix(".txt").name,
        ]
    )

    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def _clip_bbox(x_center: float, y_center: float, width: float, height: float) -> list[float]:
    width = min(max(width, 0.001), 1.0)
    height = min(max(height, 0.001), 1.0)
    x_center = min(max(x_center, width / 2), 1.0 - width / 2)
    y_center = min(max(y_center, height / 2), 1.0 - height / 2)
    return [round(x_center, 6), round(y_center, 6), round(width, 6), round(height, 6)]
