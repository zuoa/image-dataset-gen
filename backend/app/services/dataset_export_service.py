from __future__ import annotations

import csv
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


IMAGE_SIZE = (512, 512)


def build_dataset_export_archive(
    dataset: Dataset,
    export_job: DatasetExport,
    export_format: str,
    image_format: str,
    include_readme: bool,
    storage_root: str,
) -> dict[str, Any]:
    export_root = Path(storage_root) / "exports"
    export_root.mkdir(parents=True, exist_ok=True)
    archive_path = export_root / f"{export_job.id}.zip"
    dataset_name = _slugify(dataset.name or "dataset")

    selected_images = [image for image in dataset.images if image.selected]
    split_assignments = _build_splits(selected_images)
    categories = dataset.categories or ["default"]
    image_format_summary = _resolved_image_format_summary(dataset, selected_images, image_format, storage_root)

    with tempfile.TemporaryDirectory(prefix="dataset-export-") as temp_dir:
        temp_root = Path(temp_dir) / dataset_name
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
            _write_data_yaml(temp_root, categories)

        if archive_path.exists():
            archive_path.unlink()
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for file_path in temp_root.rglob("*"):
                if file_path.is_file():
                    archive.write(file_path, file_path.relative_to(temp_root.parent))

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
    total = len(ordered)
    if total <= 1:
        return {"train": ordered, "val": [], "test": []}
    if total == 2:
        return {"train": ordered[:1], "val": ordered[1:], "test": []}

    train_cutoff = math.floor(total * 0.7)
    val_cutoff = math.floor(total * 0.9)
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


def _primary_detection(storage_root: str, dataset: Dataset, dataset_image: DatasetImage) -> dict[str, Any] | None:
    stored = load_annotation_result(
        storage_root,
        dataset.id,
        dataset_image.id,
        default_bbox_semantics=infer_default_bbox_semantics(dataset.annotation_json or {}),
    )
    if stored is not None:
        detections = stored.get("detections", [])
        return detections[0] if detections else None

    return None


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
    detection = _primary_detection(storage_root, dataset, dataset_image)
    if detection:
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


def _write_yolo_label(label_path: Path, class_id: int, bbox: tuple[float, float, float, float] | None) -> None:
    label_path.parent.mkdir(parents=True, exist_ok=True)
    if not bbox:
        label_path.write_text("", encoding="utf-8")
        return
    x_center, y_center, width, height = bbox
    label_path.write_text(
        f"{class_id} {x_center:.6f} {y_center:.6f} {width:.6f} {height:.6f}\n",
        encoding="utf-8",
    )


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
            detection = _primary_detection(storage_root, dataset, dataset_image)
            category = str(detection["category"]) if detection and detection.get("category") in category_to_id else categories[0]
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
                category_to_id[category],
                tuple(detection["bbox"]) if detection else None,
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

    for split_name in ("train", "val"):
        split_images = split_assignments.get(split_name, [])
        images_payload: list[dict[str, Any]] = []
        annotations_payload: list[dict[str, Any]] = []

        for image_id, dataset_image in enumerate(split_images, start=1):
            detection = _primary_detection(storage_root, dataset, dataset_image)
            category = str(detection["category"]) if detection and detection.get("category") in category_to_id else categories[0]
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
                    "width": IMAGE_SIZE[0],
                    "height": IMAGE_SIZE[1],
                }
            )
            if detection:
                x_center, y_center, width, height = detection["bbox"]
                bbox = [
                    round((x_center - width / 2) * IMAGE_SIZE[0], 2),
                    round((y_center - height / 2) * IMAGE_SIZE[1], 2),
                    round(width * IMAGE_SIZE[0], 2),
                    round(height * IMAGE_SIZE[1], 2),
                ]
                annotations_payload.append(
                    {
                        "id": len(annotations_payload) + 1,
                        "image_id": image_id,
                        "category_id": category_to_id[category],
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
            detection = _primary_detection(storage_root, dataset, dataset_image)
            category = (
                str(detection["category"])
                if detection and detection.get("category")
                else (dataset.categories[0] if dataset.categories else "default")
            )
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
            SubElement(size, "width").text = str(IMAGE_SIZE[0])
            SubElement(size, "height").text = str(IMAGE_SIZE[1])
            SubElement(size, "depth").text = "3"

            if detection:
                x_center, y_center, width, height = detection["bbox"]
                x1 = max(1, int((x_center - width / 2) * IMAGE_SIZE[0]))
                y1 = max(1, int((y_center - height / 2) * IMAGE_SIZE[1]))
                x2 = min(IMAGE_SIZE[0], int((x_center + width / 2) * IMAGE_SIZE[0]))
                y2 = min(IMAGE_SIZE[1], int((y_center + height / 2) * IMAGE_SIZE[1]))
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
        detection = _primary_detection(storage_root, dataset, dataset_image)
        category = str(detection["category"]) if detection and detection.get("category") in categories else categories[0]
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
        rows.append(
            {
                "image_name": image_name,
                "category": category,
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


def _write_data_yaml(temp_root: Path, categories: list[str]) -> None:
    lines = [
        "path: .",
        "train: images/train",
        "val: images/val",
        "test: images/test",
        f"names: {json.dumps(categories, ensure_ascii=False)}",
    ]
    (temp_root / "data.yaml").write_text("\n".join(lines), encoding="utf-8")
