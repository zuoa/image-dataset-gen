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

from app.models import Task, TaskExport, TaskImage
from app.services.image_storage import existing_generated_image, export_image_to_format
from app.services.annotation_storage import load_annotation_result


IMAGE_SIZE = (512, 512)


def build_export_archive(
    task: Task,
    export_job: TaskExport,
    export_format: str,
    image_format: str,
    include_readme: bool,
    storage_root: str,
) -> dict[str, Any]:
    export_root = Path(storage_root) / "exports"
    export_root.mkdir(parents=True, exist_ok=True)
    archive_path = export_root / f"{export_job.id}.zip"
    dataset_name = _slugify(task.subject or task.task_name or "dataset")

    selected_images = [image for image in task.images if image.selected]

    actual_image_format = _resolve_image_format(image_format, task.config_json.get("format", "jpg"))
    image_ext = "jpg" if actual_image_format == "jpg" else "png"
    split_assignments = _build_splits(selected_images)

    with tempfile.TemporaryDirectory(prefix="dataset-export-") as temp_dir:
        temp_root = Path(temp_dir) / dataset_name
        temp_root.mkdir(parents=True, exist_ok=True)

        categories = task.categories or ["default"]

        if export_format == "yolo":
            _write_yolo_dataset(
                temp_root, selected_images, split_assignments, categories, image_ext, storage_root
            )
        elif export_format == "coco":
            _write_coco_dataset(
                temp_root, selected_images, split_assignments, categories, image_ext, storage_root
            )
        elif export_format == "voc":
            _write_voc_dataset(temp_root, selected_images, split_assignments, image_ext, storage_root)
        else:
            _write_csv_dataset(temp_root, selected_images, categories, image_ext, storage_root)

        if include_readme:
            _write_readme(temp_root, task, export_format, len(selected_images), image_ext)

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
        "imageFormat": image_ext,
        "structure": "yolov8" if export_format == "yolo" else export_format,
        "splits": {key: len(value) for key, value in split_assignments.items()},
    }


def get_archive_path(storage_root: str, export_job: TaskExport) -> Path:
    return Path(storage_root) / "exports" / f"{export_job.id}.zip"


def _slugify(value: str) -> str:
    sanitized = "".join(char.lower() if char.isalnum() else "-" for char in value)
    return "-".join(filter(None, sanitized.split("-"))) or "dataset"


def _resolve_image_format(image_format: str, original_format: str) -> str:
    if image_format in {"jpg", "png"}:
        return image_format
    return "jpg" if original_format == "jpg" else "png"


def _build_splits(images: list[TaskImage]) -> dict[str, list[TaskImage]]:
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


def _image_name(task_image: TaskImage, category: str, image_ext: str) -> str:
    normalized_category = _slugify(category)
    return f"{normalized_category}_{task_image.ordinal:06d}.{image_ext}"


def _category_for_image(task: Task, task_image: TaskImage) -> str:
    categories = task.categories or ["default"]
    return categories[(task_image.ordinal - 1) % len(categories)]


def _bbox_for_image(task_image: TaskImage) -> tuple[float, float, float, float] | None:
    if task_image.ordinal % 7 == 0:
        return None
    seed = task_image.seed
    x_center = 0.28 + ((seed % 31) / 100)
    y_center = 0.30 + (((seed // 10) % 29) / 100)
    width = 0.18 + (((seed // 100) % 16) / 100)
    height = 0.20 + (((seed // 1000) % 16) / 100)
    return (
        min(x_center, 0.85),
        min(y_center, 0.85),
        min(width, 0.38),
        min(height, 0.42),
    )


def _primary_detection(storage_root: str, task_image: TaskImage) -> dict[str, Any] | None:
    stored = load_annotation_result(storage_root, task_image.task_id, task_image.id)
    if stored is not None:
        detections = stored.get("detections", [])
        return detections[0] if detections else None

    bbox = _bbox_for_image(task_image)
    if not bbox:
        return None
    return {
        "category": _category_for_image(task_image.task, task_image),
        "confidence": task_image.confidence_score or 0.75,
        "bbox": list(bbox),
    }


def _save_preview_image(
    task: Task, task_image: TaskImage, output_path: Path, image_format: str, storage_root: str
) -> None:
    generated_path = existing_generated_image(storage_root, task.id, f"ordinal-{task_image.ordinal:06d}")
    if generated_path is not None:
        export_image_to_format(generated_path, output_path, image_format)
        return

    width, height = IMAGE_SIZE
    seed = task_image.seed
    background_value = 12 + (seed % 40)
    image = Image.new("RGB", (width, height), color=(background_value, background_value, background_value))
    draw = ImageDraw.Draw(image)

    border_color = 180 + (seed % 40)
    draw.rounded_rectangle((18, 18, width - 18, height - 18), radius=32, outline=(border_color,) * 3, width=2)
    detection = _primary_detection(storage_root, task_image)
    if detection:
        x_center, y_center, box_width, box_height = detection["bbox"]
        x1 = int((x_center - box_width / 2) * width)
        y1 = int((y_center - box_height / 2) * height)
        x2 = int((x_center + box_width / 2) * width)
        y2 = int((y_center + box_height / 2) * height)
        draw.rectangle((x1, y1, x2, y2), outline=(245, 245, 245), width=3)

    category = _category_for_image(task, task_image).upper()
    draw.text((36, 36), category, fill=(240, 240, 240))
    draw.text((36, 68), f"#{task_image.ordinal:03d}", fill=(190, 190, 190))
    draw.text((36, height - 54), task.subject[:28], fill=(210, 210, 210))

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
    images: list[TaskImage],
    split_assignments: dict[str, list[TaskImage]],
    categories: list[str],
    image_ext: str,
    storage_root: str,
) -> None:
    category_to_id = {name: index for index, name in enumerate(categories)}

    for split_name, split_images in split_assignments.items():
        for task_image in split_images:
            detection = _primary_detection(storage_root, task_image)
            category = (
                str(detection["category"])
                if detection and detection.get("category") in category_to_id
                else _category_for_image(task_image.task, task_image)
            )
            image_name = _image_name(task_image, category, image_ext)
            _save_preview_image(
                task_image.task,
                task_image,
                temp_root / "images" / split_name / image_name,
                image_ext,
                storage_root,
            )
            _write_yolo_label(
                temp_root / "labels" / split_name / f"{Path(image_name).stem}.txt",
                category_to_id[category],
                tuple(detection["bbox"]) if detection else None,
            )


def _write_coco_dataset(
    temp_root: Path,
    images: list[TaskImage],
    split_assignments: dict[str, list[TaskImage]],
    categories: list[str],
    image_ext: str,
    storage_root: str,
) -> None:
    category_to_id = {name: index + 1 for index, name in enumerate(categories)}
    categories_payload = [{"id": category_id, "name": name} for name, category_id in category_to_id.items()]

    for split_name in ("train", "val"):
        split_images = split_assignments.get(split_name, [])
        images_payload: list[dict[str, Any]] = []
        annotations_payload: list[dict[str, Any]] = []

        for image_id, task_image in enumerate(split_images, start=1):
            detection = _primary_detection(storage_root, task_image)
            category = (
                str(detection["category"])
                if detection and detection.get("category") in category_to_id
                else _category_for_image(task_image.task, task_image)
            )
            image_name = _image_name(task_image, category, image_ext)
            _save_preview_image(
                task_image.task,
                task_image,
                temp_root / "images" / f"{split_name}2024" / image_name,
                image_ext,
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
                abs_width = width * IMAGE_SIZE[0]
                abs_height = height * IMAGE_SIZE[1]
                abs_x = (x_center - width / 2) * IMAGE_SIZE[0]
                abs_y = (y_center - height / 2) * IMAGE_SIZE[1]
                annotations_payload.append(
                    {
                        "id": len(annotations_payload) + 1,
                        "image_id": image_id,
                        "category_id": category_to_id[category],
                        "bbox": [round(abs_x, 2), round(abs_y, 2), round(abs_width, 2), round(abs_height, 2)],
                        "area": round(abs_width * abs_height, 2),
                        "iscrowd": 0,
                    }
                )

        annotation_root = temp_root / "annotations"
        annotation_root.mkdir(parents=True, exist_ok=True)
        (annotation_root / f"instances_{split_name}2024.json").write_text(
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
    images: list[TaskImage],
    split_assignments: dict[str, list[TaskImage]],
    image_ext: str,
    storage_root: str,
) -> None:
    image_sets_root = temp_root / "ImageSets" / "Main"
    jpeg_root = temp_root / "JPEGImages"
    annotation_root = temp_root / "Annotations"
    image_sets_root.mkdir(parents=True, exist_ok=True)
    jpeg_root.mkdir(parents=True, exist_ok=True)
    annotation_root.mkdir(parents=True, exist_ok=True)

    for split_name, split_images in split_assignments.items():
        stems: list[str] = []
        for task_image in split_images:
            category = _category_for_image(task_image.task, task_image)
            image_name = _image_name(task_image, category, image_ext)
            stem = Path(image_name).stem
            stems.append(stem)
            _save_preview_image(task_image.task, task_image, jpeg_root / image_name, image_ext, storage_root)

            detection = _primary_detection(storage_root, task_image)
            annotation = Element("annotation")
            SubElement(annotation, "filename").text = image_name
            size = SubElement(annotation, "size")
            SubElement(size, "width").text = str(IMAGE_SIZE[0])
            SubElement(size, "height").text = str(IMAGE_SIZE[1])
            SubElement(size, "depth").text = "3"
            if detection:
                category = str(detection["category"])
                x_center, y_center, width, height = detection["bbox"]
                x1 = int((x_center - width / 2) * IMAGE_SIZE[0])
                y1 = int((y_center - height / 2) * IMAGE_SIZE[1])
                x2 = int((x_center + width / 2) * IMAGE_SIZE[0])
                y2 = int((y_center + height / 2) * IMAGE_SIZE[1])
                obj = SubElement(annotation, "object")
                SubElement(obj, "name").text = category
                bbox_node = SubElement(obj, "bndbox")
                SubElement(bbox_node, "xmin").text = str(max(x1, 0))
                SubElement(bbox_node, "ymin").text = str(max(y1, 0))
                SubElement(bbox_node, "xmax").text = str(min(x2, IMAGE_SIZE[0]))
                SubElement(bbox_node, "ymax").text = str(min(y2, IMAGE_SIZE[1]))
            (annotation_root / f"{stem}.xml").write_text(
                tostring(annotation, encoding="unicode"),
                encoding="utf-8",
            )
        (image_sets_root / f"{split_name}.txt").write_text("\n".join(stems), encoding="utf-8")


def _write_csv_dataset(
    temp_root: Path,
    images: list[TaskImage],
    categories: list[str],
    image_ext: str,
    storage_root: str,
) -> None:
    images_root = temp_root / "images"
    images_root.mkdir(parents=True, exist_ok=True)
    csv_path = temp_root / "annotations.csv"

    with csv_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(["filename", "class", "x_min", "y_min", "x_max", "y_max"])
        for task_image in images:
            category = categories[(task_image.ordinal - 1) % len(categories)]
            image_name = _image_name(task_image, category, image_ext)
            detection = _primary_detection(storage_root, task_image)
            if detection:
                category = str(detection["category"])
            _save_preview_image(task_image.task, task_image, images_root / image_name, image_ext, storage_root)
            if detection:
                x_center, y_center, width, height = detection["bbox"]
                x1 = int((x_center - width / 2) * IMAGE_SIZE[0])
                y1 = int((y_center - height / 2) * IMAGE_SIZE[1])
                x2 = int((x_center + width / 2) * IMAGE_SIZE[0])
                y2 = int((y_center + height / 2) * IMAGE_SIZE[1])
                writer.writerow([image_name, category, x1, y1, x2, y2])
            else:
                writer.writerow([image_name, category, "", "", "", ""])


def _write_readme(
    temp_root: Path,
    task: Task,
    export_format: str,
    image_count: int,
    image_ext: str,
) -> None:
    readme = f"""# {task.subject}

Export format: {export_format}
Images: {image_count}
Categories: {", ".join(task.categories or [])}
Image format: {image_ext}

This archive was generated by Dataset Forge. The images are deterministic placeholders derived from the task metadata so the export flow can be validated end-to-end before wiring a real generation backend.
"""
    (temp_root / "README.md").write_text(readme, encoding="utf-8")


def _write_data_yaml(temp_root: Path, categories: list[str]) -> None:
    yaml_content = "\n".join(
        [
            "path: .",
            "train: images/train",
            "val: images/val",
            "test: images/test",
            "",
            f"nc: {len(categories)}",
            f"names: {json.dumps(categories, ensure_ascii=False)}",
        ]
    )
    (temp_root / "data.yaml").write_text(yaml_content, encoding="utf-8")
