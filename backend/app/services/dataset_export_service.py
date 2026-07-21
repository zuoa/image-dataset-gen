from __future__ import annotations

import csv
from datetime import UTC
import json
import math
import tempfile
import zipfile
from pathlib import Path
from typing import Any
from xml.etree.ElementTree import Element, SubElement, tostring

from PIL import Image, ImageDraw

from app.models import Dataset, DatasetExport, DatasetImage
from app.services.annotation_storage import infer_default_bbox_semantics, load_annotation_result
from app.services.image_storage import existing_generated_image, export_image_to_format
from app.services.storage_backend import local_backend


IMAGE_SIZE = (512, 512)
EXPORT_FILENAME_DATASET_SLUG_MAX_LENGTH = 40


def build_dataset_export_archive(
    dataset: Dataset,
    export_job: DatasetExport,
    export_format: str,
    image_format: str,
    include_readme: bool,
    storage_root: str,
) -> dict[str, Any]:
    dataset_name = _slugify(dataset.name or "dataset")

    selected_images = [image for image in dataset.images if image.selected]
    split_assignments = _build_splits(selected_images)
    categories = dataset.categories or ["default"]
    image_format_summary = _resolved_image_format_summary(dataset, selected_images, image_format, storage_root)

    with tempfile.TemporaryDirectory(prefix="dataset-export-") as temp_dir:
        temp_root = Path(temp_dir) / dataset_name
        temporary_archive = Path(temp_dir) / f"{export_job.id}.zip"
        temp_root.mkdir(parents=True, exist_ok=True)

        if export_format == "yolo":
            _write_yolo_dataset(temp_root, dataset, selected_images, split_assignments, categories, image_format, storage_root)
        elif export_format == "coco":
            _write_coco_dataset(temp_root, dataset, split_assignments, categories, image_format, storage_root)
        elif export_format == "voc":
            _write_voc_dataset(temp_root, dataset, split_assignments, image_format, storage_root)
        else:
            _write_csv_dataset(temp_root, dataset, selected_images, categories, image_format, storage_root)

        if include_readme:
            _write_readme(temp_root, dataset, export_format, len(selected_images), image_format_summary)

        if export_format == "yolo":
            _write_data_yaml(temp_root, categories, split_assignments)
        _write_manifest(
            temp_root,
            dataset,
            selected_images,
            split_assignments,
            categories,
            export_format,
            image_format,
            storage_root,
        )

        with zipfile.ZipFile(temporary_archive, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for file_path in temp_root.rglob("*"):
                if file_path.is_file():
                    archive.write(file_path, file_path.relative_to(temp_root.parent))
        with temporary_archive.open("rb") as handle:
            archive_path = local_backend(storage_root).put_stream(
                f"exports/{export_job.id}.zip", handle
            ).path

    return {
        "archivePath": str(archive_path),
        "estimatedSizeMb": round(archive_path.stat().st_size / (1024 * 1024), 2),
        "imageCount": len(selected_images),
        "categoryCount": len(categories),
        "imageFormat": image_format_summary,
        "structure": "yolov8" if export_format == "yolo" else export_format,
        "splits": {key: len(value) for key, value in split_assignments.items()},
    }


def get_dataset_archive_path(storage_root: str, export_job: DatasetExport) -> Path:
    return Path(storage_root) / "exports" / f"{export_job.id}.zip"


def dataset_export_download_name(
    dataset_name: str,
    export_job: DatasetExport,
    *,
    fallback_image_count: int = 0,
) -> str:
    dataset_slug = _slugify(dataset_name or "dataset")
    dataset_slug = dataset_slug[:EXPORT_FILENAME_DATASET_SLUG_MAX_LENGTH].rstrip("-") or "dataset"
    format_slug = _slugify(export_job.export_format or "dataset")

    created_at = export_job.created_at
    if created_at is None:
        created_stamp = "undated"
    else:
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        else:
            created_at = created_at.astimezone(UTC)
        created_stamp = created_at.strftime("%Y%m%dT%H%MZ")

    image_count_value = (export_job.summary_json or {}).get(
        "imageCount", fallback_image_count
    )
    try:
        image_count = max(0, int(image_count_value))
    except (TypeError, ValueError):
        image_count = max(0, int(fallback_image_count or 0))

    version = max(1, int(export_job.version or 1))
    return (
        f"{dataset_slug}-{format_slug}-{created_stamp}"
        f"-n{image_count}-v{version:03d}.zip"
    )


def _slugify(value: str) -> str:
    sanitized = "".join(char.lower() if char.isalnum() else "-" for char in value)
    return "-".join(filter(None, sanitized.split("-"))) or "dataset"


def _resolve_image_format(image_format: str, original_format: str) -> str:
    if image_format in {"jpg", "png"}:
        return image_format
    return "jpg" if original_format == "jpg" else "png"


def _resolved_image_format_for_dataset_image(
    dataset: Dataset,
    dataset_image: DatasetImage,
    image_format: str,
    storage_root: str,
) -> tuple[str, str]:
    if image_format in {"jpg", "png"}:
        return image_format, image_format

    generated_path = existing_generated_image(storage_root, dataset.id, f"image-{dataset_image.ordinal:06d}")
    if generated_path is not None and generated_path.suffix.lower() == ".png":
        return "png", "png"

    if generated_path is not None:
        return "jpg", "jpg"

    if dataset_image.preview_svg.startswith("data:image/png"):
        return "png", "png"

    return "jpg", "jpg"


def _resolved_image_format_summary(
    dataset: Dataset,
    images: list[DatasetImage],
    image_format: str,
    storage_root: str,
) -> str:
    if image_format in {"jpg", "png"}:
        return image_format

    actual_formats = {
        _resolved_image_format_for_dataset_image(dataset, dataset_image, image_format, storage_root)[1]
        for dataset_image in images
    }
    if not actual_formats:
        return "keep"
    if len(actual_formats) == 1:
        return next(iter(actual_formats))
    return "mixed"


def _build_splits(images: list[DatasetImage]) -> dict[str, list[DatasetImage]]:
    ordered = sorted(images, key=lambda image: image.ordinal)
    imported_splits = {
        image.id: str((image.diversity_vars or {}).get("importSplit") or "")
        for image in ordered
    }
    if any(value in {"train", "val", "test"} for value in imported_splits.values()):
        result: dict[str, list[DatasetImage]] = {"train": [], "val": [], "test": []}
        unassigned: list[DatasetImage] = []
        for image in ordered:
            split = imported_splits.get(image.id, "")
            if split in result:
                result[split].append(image)
            else:
                unassigned.append(image)
        fallback = _build_splits_without_imports(unassigned)
        for split, split_images in fallback.items():
            result[split].extend(split_images)
        return result
    return _build_splits_without_imports(ordered)


def _build_splits_without_imports(images: list[DatasetImage]) -> dict[str, list[DatasetImage]]:
    ordered = sorted(images, key=lambda image: image.ordinal)
    total = len(ordered)
    if total <= 1:
        return {"train": ordered, "val": [], "test": []}
    if total <= 3:
        return {"train": ordered[:-1], "val": ordered[-1:], "test": []}

    train_cutoff = max(1, math.floor(total * 0.7))
    val_cutoff = min(total, max(train_cutoff + 1, math.floor(total * 0.9)))
    return {
        "train": ordered[:train_cutoff],
        "val": ordered[train_cutoff:val_cutoff],
        "test": ordered[val_cutoff:],
    }


def _image_name(dataset_image: DatasetImage, category: str, image_ext: str) -> str:
    output_filename = (dataset_image.diversity_vars or {}).get("outputFilename")
    if dataset_image.source_type == "video" and isinstance(output_filename, str) and output_filename.strip():
        return f"{_safe_filename_stem(Path(output_filename).stem)}_{dataset_image.ordinal:06d}.{image_ext}"
    normalized_category = _slugify(category)
    return f"{normalized_category}_{dataset_image.ordinal:06d}.{image_ext}"


def _safe_filename_stem(value: str) -> str:
    sanitized = "".join(char if char.isalnum() or char in {"_", "-"} else "-" for char in value.strip())
    return "-".join(filter(None, sanitized.split("-"))) or "frame"


def _detections(
    storage_root: str,
    dataset: Dataset,
    dataset_image: DatasetImage,
) -> list[dict[str, Any]]:
    stored = load_annotation_result(
        storage_root,
        dataset.id,
        dataset_image.id,
        default_bbox_semantics=infer_default_bbox_semantics(dataset.annotation_json or {}),
    )
    if stored is not None:
        return list(stored.get("detections", []))
    return []


def _image_dimensions(
    storage_root: str,
    dataset: Dataset,
    dataset_image: DatasetImage,
) -> tuple[int, int]:
    if dataset_image.asset and dataset_image.asset.width and dataset_image.asset.height:
        return int(dataset_image.asset.width), int(dataset_image.asset.height)
    generated_path = existing_generated_image(
        storage_root, dataset.id, f"image-{dataset_image.ordinal:06d}"
    )
    if generated_path is not None:
        with Image.open(generated_path) as image:
            return image.size
    return IMAGE_SIZE


def _save_preview_image(
    dataset: Dataset,
    dataset_image: DatasetImage,
    output_path: Path,
    image_format: str,
    storage_root: str,
) -> None:
    generated_path = existing_generated_image(storage_root, dataset.id, f"image-{dataset_image.ordinal:06d}")
    if generated_path is not None:
        export_image_to_format(generated_path, output_path, image_format)
        return

    width, height = IMAGE_SIZE
    seed = dataset_image.seed
    background_value = 12 + (seed % 40)
    image = Image.new("RGB", (width, height), color=(background_value, background_value, background_value))
    draw = ImageDraw.Draw(image)

    border_color = 180 + (seed % 40)
    draw.rounded_rectangle((18, 18, width - 18, height - 18), radius=32, outline=(border_color,) * 3, width=2)
    for detection in _detections(storage_root, dataset, dataset_image):
        x_center, y_center, box_width, box_height = detection["bbox"]
        x1 = int((x_center - box_width / 2) * width)
        y1 = int((y_center - box_height / 2) * height)
        x2 = int((x_center + box_width / 2) * width)
        y2 = int((y_center + box_height / 2) * height)
        draw.rectangle((x1, y1, x2, y2), outline=(245, 245, 245), width=3)

    category = dataset.categories[0].upper() if dataset.categories else "OBJECT"
    draw.text((36, 36), category, fill=(240, 240, 240))
    draw.text((36, 68), f"#{dataset_image.ordinal:03d}", fill=(190, 190, 190))
    draw.text((36, height - 54), dataset.name[:28], fill=(210, 210, 210))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if image_format == "jpg":
        image.save(output_path, format="JPEG", quality=90)
    else:
        image.save(output_path, format="PNG")


def _write_yolo_label(
    label_path: Path,
    detections: list[dict[str, Any]],
    category_to_id: dict[str, int],
) -> None:
    label_path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    for detection in detections:
        category = str(detection.get("category") or "")
        if category not in category_to_id:
            continue
        x_center, y_center, width, height = detection["bbox"]
        lines.append(
            f"{category_to_id[category]} {x_center:.6f} {y_center:.6f} "
            f"{width:.6f} {height:.6f}"
        )
    label_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def _write_yolo_dataset(
    temp_root: Path,
    dataset: Dataset,
    images: list[DatasetImage],
    split_assignments: dict[str, list[DatasetImage]],
    categories: list[str],
    image_format: str,
    storage_root: str,
) -> None:
    category_to_id = {name: index for index, name in enumerate(categories)}

    for split_name, split_images in split_assignments.items():
        for dataset_image in split_images:
            detections = _detections(storage_root, dataset, dataset_image)
            category = _filename_category(detections, categories)
            actual_image_format, image_ext = _resolved_image_format_for_dataset_image(
                dataset, dataset_image, image_format, storage_root
            )
            image_name = _image_name(dataset_image, category, image_ext)
            _save_preview_image(
                dataset,
                dataset_image,
                temp_root / "images" / split_name / image_name,
                actual_image_format,
                storage_root,
            )
            _write_yolo_label(
                temp_root / "labels" / split_name / f"{Path(image_name).stem}.txt",
                detections,
                category_to_id,
            )


def _write_coco_dataset(
    temp_root: Path,
    dataset: Dataset,
    split_assignments: dict[str, list[DatasetImage]],
    categories: list[str],
    image_format: str,
    storage_root: str,
) -> None:
    category_to_id = {name: index + 1 for index, name in enumerate(categories)}
    categories_payload = [{"id": category_id, "name": name} for name, category_id in category_to_id.items()]

    for split_name in ("train", "val", "test"):
        split_images = split_assignments.get(split_name, [])
        images_payload: list[dict[str, Any]] = []
        annotations_payload: list[dict[str, Any]] = []

        for image_id, dataset_image in enumerate(split_images, start=1):
            detections = _detections(storage_root, dataset, dataset_image)
            category = _filename_category(detections, categories)
            image_width, image_height = _image_dimensions(storage_root, dataset, dataset_image)
            actual_image_format, image_ext = _resolved_image_format_for_dataset_image(
                dataset, dataset_image, image_format, storage_root
            )
            image_name = _image_name(dataset_image, category, image_ext)
            _save_preview_image(
                dataset,
                dataset_image,
                temp_root / split_name / image_name,
                actual_image_format,
                storage_root,
            )
            images_payload.append(
                {
                    "id": image_id,
                    "file_name": image_name,
                    "width": image_width,
                    "height": image_height,
                }
            )
            for detection in detections:
                detection_category = str(detection.get("category") or "")
                if detection_category not in category_to_id:
                    continue
                x_center, y_center, width, height = detection["bbox"]
                bbox = [
                    round((x_center - width / 2) * image_width, 2),
                    round((y_center - height / 2) * image_height, 2),
                    round(width * image_width, 2),
                    round(height * image_height, 2),
                ]
                annotations_payload.append(
                    {
                        "id": len(annotations_payload) + 1,
                        "image_id": image_id,
                        "category_id": category_to_id[detection_category],
                        "bbox": bbox,
                        "area": round(bbox[2] * bbox[3], 2),
                        "iscrowd": 0,
                    }
                )

        annotations_dir = temp_root / "annotations"
        annotations_dir.mkdir(parents=True, exist_ok=True)
        (annotations_dir / f"instances_{split_name}.json").write_text(
            json.dumps(
                {
                    "images": images_payload,
                    "annotations": annotations_payload,
                    "categories": categories_payload,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )


def _write_voc_dataset(
    temp_root: Path,
    dataset: Dataset,
    split_assignments: dict[str, list[DatasetImage]],
    image_format: str,
    storage_root: str,
) -> None:
    jpeg_images = temp_root / "JPEGImages"
    annotations_dir = temp_root / "Annotations"
    image_sets_main = temp_root / "ImageSets" / "Main"
    jpeg_images.mkdir(parents=True, exist_ok=True)
    annotations_dir.mkdir(parents=True, exist_ok=True)
    image_sets_main.mkdir(parents=True, exist_ok=True)

    for split_name, split_images in split_assignments.items():
        ids: list[str] = []
        for dataset_image in split_images:
            detections = _detections(storage_root, dataset, dataset_image)
            category = _filename_category(detections, dataset.categories or ["default"])
            image_width, image_height = _image_dimensions(storage_root, dataset, dataset_image)
            actual_image_format, image_ext = _resolved_image_format_for_dataset_image(
                dataset, dataset_image, image_format, storage_root
            )
            image_stem = Path(_image_name(dataset_image, category, image_ext)).stem
            ids.append(image_stem)
            _save_preview_image(
                dataset,
                dataset_image,
                jpeg_images / f"{image_stem}.{image_ext}",
                actual_image_format,
                storage_root,
            )

            annotation = Element("annotation")
            SubElement(annotation, "folder").text = "JPEGImages"
            SubElement(annotation, "filename").text = f"{image_stem}.{image_ext}"
            size = SubElement(annotation, "size")
            SubElement(size, "width").text = str(image_width)
            SubElement(size, "height").text = str(image_height)
            SubElement(size, "depth").text = "3"

            for detection in detections:
                x_center, y_center, width, height = detection["bbox"]
                x1 = max(1, int((x_center - width / 2) * image_width))
                y1 = max(1, int((y_center - height / 2) * image_height))
                x2 = min(image_width, int((x_center + width / 2) * image_width))
                y2 = min(image_height, int((y_center + height / 2) * image_height))
                obj = SubElement(annotation, "object")
                SubElement(obj, "name").text = str(detection["category"])
                bbox = SubElement(obj, "bndbox")
                SubElement(bbox, "xmin").text = str(x1)
                SubElement(bbox, "ymin").text = str(y1)
                SubElement(bbox, "xmax").text = str(x2)
                SubElement(bbox, "ymax").text = str(y2)

            (annotations_dir / f"{image_stem}.xml").write_bytes(tostring(annotation, encoding="utf-8"))

        (image_sets_main / f"{split_name}.txt").write_text("\n".join(ids), encoding="utf-8")


def _write_csv_dataset(
    temp_root: Path,
    dataset: Dataset,
    images: list[DatasetImage],
    categories: list[str],
    image_format: str,
    storage_root: str,
) -> None:
    images_dir = temp_root / "images"
    rows: list[dict[str, Any]] = []
    for dataset_image in images:
        detections = _detections(storage_root, dataset, dataset_image)
        category = _filename_category(detections, categories)
        actual_image_format, image_ext = _resolved_image_format_for_dataset_image(
            dataset, dataset_image, image_format, storage_root
        )
        image_name = _image_name(dataset_image, category, image_ext)
        _save_preview_image(
            dataset,
            dataset_image,
            images_dir / image_name,
            actual_image_format,
            storage_root,
        )
        row_detections = detections or [None]
        for detection in row_detections:
            rows.append(
                {
                    "image_name": image_name,
                    "category": detection.get("category", "") if detection else "",
                    "selected": dataset_image.selected,
                    "annotation_status": dataset_image.annotation_status,
                    "bbox": json.dumps(detection["bbox"]) if detection else "",
                    "confidence": detection["confidence"] if detection else "",
                }
            )

    with (temp_root / "labels.csv").open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(
            csv_file,
            fieldnames=["image_name", "category", "selected", "annotation_status", "bbox", "confidence"],
        )
        writer.writeheader()
        writer.writerows(rows)


def _write_readme(
    temp_root: Path,
    dataset: Dataset,
    export_format: str,
    image_count: int,
    image_ext: str,
) -> None:
    readme = "\n".join(
        [
            f"# {dataset.name}",
            "",
            f"- Export format: {export_format}",
            f"- Images: {image_count}",
            f"- Categories: {', '.join(dataset.categories or ['default'])}",
            f"- Image extension: {image_ext}",
            "",
            "Generated by Dataset Forge.",
        ]
    )
    (temp_root / "README.md").write_text(readme, encoding="utf-8")


def _write_data_yaml(
    temp_root: Path,
    categories: list[str],
    split_assignments: dict[str, list[DatasetImage]],
) -> None:
    val_path = "images/val" if split_assignments.get("val") else "images/train"
    lines = [
        "train: images/train",
        f"val: {val_path}",
        f"names: {json.dumps(categories, ensure_ascii=False)}",
    ]
    if split_assignments.get("test"):
        lines.insert(2, "test: images/test")
    (temp_root / "data.yaml").write_text("\n".join(lines), encoding="utf-8")


def _filename_category(
    detections: list[dict[str, Any]], categories: list[str]
) -> str:
    category_set = set(categories)
    for detection in detections:
        category = str(detection.get("category") or "")
        if category in category_set:
            return category
    return categories[0] if categories else "default"


def _write_manifest(
    temp_root: Path,
    dataset: Dataset,
    images: list[DatasetImage],
    split_assignments: dict[str, list[DatasetImage]],
    categories: list[str],
    export_format: str,
    image_format: str,
    storage_root: str,
) -> None:
    split_by_id = {
        image.id: split_name
        for split_name, split_images in split_assignments.items()
        for image in split_images
    }
    entries: list[dict[str, Any]] = []
    for dataset_image in images:
        detections = _detections(storage_root, dataset, dataset_image)
        category = _filename_category(detections, categories)
        _, image_ext = _resolved_image_format_for_dataset_image(
            dataset, dataset_image, image_format, storage_root
        )
        image_name = _image_name(dataset_image, category, image_ext)
        split_name = split_by_id.get(dataset_image.id, "train")
        if export_format == "yolo":
            image_path = f"images/{split_name}/{image_name}"
        elif export_format == "coco":
            image_path = f"{split_name}/{image_name}"
        elif export_format == "voc":
            image_path = f"JPEGImages/{image_name}"
        else:
            image_path = f"images/{image_name}"
        current_revision = next(
            (revision for revision in dataset_image.annotation_revisions if revision.is_current),
            None,
        )
        entries.append(
            {
                "imageId": dataset_image.id,
                "ordinal": dataset_image.ordinal,
                "imagePath": image_path,
                "split": split_name,
                "annotationRevision": current_revision.revision if current_revision else None,
                "detectionCount": len(detections),
            }
        )
    (temp_root / "dataset-manifest.json").write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "datasetId": dataset.id,
                "categories": categories,
                "images": entries,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
