from __future__ import annotations

import base64
import copy
from io import BytesIO
import math
import os
import random
import shutil
from pathlib import Path
from typing import Any

os.environ.setdefault("NO_ALBUMENTATIONS_UPDATE", "1")

import albumentations as A
import cv2
import numpy as np
from PIL import Image

from app.services.storage_backend import local_backend

MAX_ROTATION_ANGLE_DEGREES = 8.0
MIN_BBOX_AREA_PIXELS = 1.0
MIN_BBOX_VISIBILITY = 0.25
GENERATED_IMAGE_EXTENSIONS = ("png", "jpg", "jpeg")
DEFAULT_AUGMENTATION_SETTINGS = {
    "flip": {"mode": "random"},
    "rotate": {"max_angle": MAX_ROTATION_ANGLE_DEGREES},
    "crop": {"min_scale": 0.82, "max_scale": 0.94},
    "color_jitter": {"strength": 0.18},
    "blur": {"max_radius": 2.4},
    "noise": {"max_sigma": 28.0},
    "occlusion": {"min_ratio": 0.14, "max_ratio": 0.28},
    "perspective": {"max_warp": 0.08},
}


def image_dir(storage_root: str, task_id: str) -> Path:
    path = Path(storage_root) / "images" / task_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def image_path(storage_root: str, task_id: str, image_key: str, extension: str) -> Path:
    normalized = extension.replace(".", "").lower()
    return image_dir(storage_root, task_id) / f"{image_key}.{normalized}"


def save_generated_image(
    storage_root: str,
    task_id: str,
    image_key: str,
    image_bytes: bytes,
    mime_type: str,
) -> Path:
    extension = "png" if mime_type == "image/png" else "jpg"
    remove_generated_image_variants(storage_root, task_id, image_key)
    stored = local_backend(storage_root).put_bytes(
        f"images/{task_id}/{image_key}.{extension}", image_bytes
    )
    return stored.path


def existing_generated_image(storage_root: str, task_id: str, image_key: str) -> Path | None:
    candidates = [
        path
        for path in (image_path(storage_root, task_id, image_key, extension) for extension in GENERATED_IMAGE_EXTENSIONS)
        if path.exists()
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime_ns)


def remove_generated_image_variants(storage_root: str, task_id: str, image_key: str) -> list[Path]:
    removed_paths: list[Path] = []
    for extension in GENERATED_IMAGE_EXTENSIONS:
        path = image_path(storage_root, task_id, image_key, extension)
        if path.exists():
            path.unlink()
            removed_paths.append(path)
    return removed_paths


def copy_generated_image(storage_root: str, task_id: str, source_image_key: str, target_image_key: str) -> Path | None:
    source_path = existing_generated_image(storage_root, task_id, source_image_key)
    if source_path is None:
        return None
    target_path = image_path(storage_root, task_id, target_image_key, source_path.suffix)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_path, target_path)
    return target_path


def augment_generated_image(
    storage_root: str,
    task_id: str,
    source_image_key: str,
    target_image_key: str,
    methods: list[str],
    seed: int,
    settings: dict[str, object] | None = None,
    detections: list[dict[str, Any]] | None = None,
) -> dict[str, object] | None:
    source_path = existing_generated_image(storage_root, task_id, source_image_key)
    if source_path is None:
        return None

    rng = random.Random(seed)
    applied_methods = _pick_augmentation_methods(methods, rng)
    mime_type = "image/png" if source_path.suffix.lower() == ".png" else "image/jpeg"
    source_format = "PNG" if mime_type == "image/png" else "JPEG"

    with Image.open(source_path) as source_image:
        preserve_alpha = source_image.mode in {"RGBA", "LA"} or "transparency" in source_image.info
        source_rgb = np.asarray(source_image.convert("RGB"))
        source_alpha = np.asarray(source_image.convert("RGBA").getchannel("A")) if preserve_alpha else None
        height, width = source_rgb.shape[:2]
        transforms: list[A.BasicTransform] = []
        augmentation_ops: list[dict[str, Any]] = []
        for method in applied_methods:
            transform, op = _build_augmentation_transform(method, rng, settings, width, height)
            transforms.append(transform)
            augmentation_ops.append(op)

        source_detections, bboxes, detection_indices = _prepare_detections(detections)
        pipeline = A.ReplayCompose(
            transforms,
            bbox_params=A.BboxParams(
                format="yolo",
                label_fields=["detection_indices"],
                min_area=MIN_BBOX_AREA_PIXELS,
                min_visibility=MIN_BBOX_VISIBILITY,
                clip=True,
                filter_invalid_bboxes=True,
            ),
        )
        pipeline.set_random_seed(seed)
        transform_inputs: dict[str, Any] = {
            "image": source_rgb,
            "bboxes": bboxes,
            "detection_indices": detection_indices,
        }
        if "occlusion" in applied_methods:
            transform_inputs["mask"] = np.ones((height, width), dtype=np.uint8)
        transformed = pipeline(**transform_inputs)
        transformed_image = np.asarray(transformed["image"], dtype=np.uint8)
        transformed_detections = (
            _restore_detections(
                source_detections,
                transformed.get("bboxes", []),
                transformed.get("detection_indices", []),
            )
            if detections is not None
            else None
        )
        if transformed_detections is not None and "occlusion" in applied_methods:
            transformed_detections = _filter_occluded_detections(
                transformed_detections,
                np.asarray(transformed["mask"]),
            )

        if source_alpha is not None:
            alpha_replay = _replay_without_occlusion(transformed["replay"])
            alpha_result = A.ReplayCompose.replay(
                alpha_replay,
                image=source_rgb,
                mask=source_alpha,
                bboxes=[],
                detection_indices=[],
            )
            transformed_alpha = np.asarray(alpha_result["mask"], dtype=np.uint8)
            working = Image.fromarray(np.dstack((transformed_image, transformed_alpha)))
        else:
            working = Image.fromarray(transformed_image)

        output = BytesIO()
        if source_format == "PNG":
            working.save(output, format="PNG")
        else:
            working.convert("RGB").save(output, format="JPEG", quality=90)
        image_bytes = output.getvalue()

    saved_path = save_generated_image(storage_root, task_id, target_image_key, image_bytes, mime_type)
    return {
        "image_bytes": image_bytes,
        "mime_type": mime_type,
        "path": saved_path,
        "applied_methods": applied_methods,
        "augmentation_ops": augmentation_ops,
        "augmentation_replay": _json_safe(transformed["replay"]),
        "transformed_detections": transformed_detections,
    }


def normalize_uploaded_image(image_bytes: bytes) -> dict[str, object] | None:
    try:
        with Image.open(BytesIO(image_bytes)) as image:
            image.load()
            preserve_alpha = image.mode in {"RGBA", "LA"} or "transparency" in image.info
            working = image.convert("RGBA" if preserve_alpha else "RGB")
            output = BytesIO()
            if preserve_alpha:
                working.save(output, format="PNG")
                mime_type = "image/png"
            else:
                working.save(output, format="JPEG", quality=90)
                mime_type = "image/jpeg"
            normalized_bytes = output.getvalue()
    except OSError:
        return None

    return {
        "image_bytes": normalized_bytes,
        "mime_type": mime_type,
        "width": working.size[0],
        "height": working.size[1],
    }


def preview_data_url(image_bytes: bytes, mime_type: str) -> str:
    encoded = base64.b64encode(image_bytes).decode("utf-8")
    return f"data:{mime_type};base64,{encoded}"


def export_image_to_format(source_path: Path, destination_path: Path, image_format: str) -> None:
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    if image_format == "png":
        with Image.open(source_path) as image:
            preserve_alpha = image.mode in {"RGBA", "LA"} or "transparency" in image.info
            image.convert("RGBA" if preserve_alpha else "RGB").save(destination_path, format="PNG")
        return
    with Image.open(source_path) as image:
        image.convert("RGB").save(destination_path, format="JPEG", quality=90)


def _pick_augmentation_methods(methods: list[str], rng: random.Random) -> list[str]:
    unique_methods = [method for index, method in enumerate(methods) if method and method not in methods[:index]]
    if not unique_methods:
        return ["flip"]
    sample_size = min(len(unique_methods), 1 + rng.randrange(min(3, len(unique_methods))))
    return rng.sample(unique_methods, k=sample_size)


def _method_settings(settings: dict[str, object] | None, method: str) -> dict[str, object]:
    resolved = dict(DEFAULT_AUGMENTATION_SETTINGS.get(method, {}))
    if not isinstance(settings, dict):
        return resolved

    custom = settings.get(method)
    if isinstance(custom, dict):
        resolved.update(custom)
    return resolved


def _build_augmentation_transform(
    method: str,
    rng: random.Random,
    settings: dict[str, object] | None = None,
    width: int = 1,
    height: int = 1,
) -> tuple[A.BasicTransform, dict[str, Any]]:
    method_settings = _method_settings(settings, method)
    op: dict[str, Any] = {"method": method, "size": [width, height]}
    if method == "flip":
        flip_mode = str(method_settings.get("mode", "random"))
        resolved_mode = flip_mode if flip_mode in {"horizontal", "vertical"} else (
            "horizontal" if rng.random() < 0.7 else "vertical"
        )
        op["mode"] = resolved_mode
        transform = A.HorizontalFlip(p=1.0) if resolved_mode == "horizontal" else A.VerticalFlip(p=1.0)
        op["transform"] = type(transform).__name__
        return transform, op
    if method == "rotate":
        max_angle = max(0.0, float(method_settings.get("max_angle", MAX_ROTATION_ANGLE_DEGREES)))
        transform = A.Rotate(
            limit=(-max_angle, max_angle),
            interpolation=cv2.INTER_CUBIC,
            border_mode=cv2.BORDER_CONSTANT,
            fill=(245, 245, 245),
            fill_mask=0,
            p=1.0,
        ) if max_angle > 0 else A.NoOp(p=1.0)
        op.update({"max_angle": max_angle, "transform": type(transform).__name__})
        return transform, op
    if method == "crop":
        min_scale = max(0.01, float(method_settings.get("min_scale", 0.82)))
        max_scale = max(0.01, float(method_settings.get("max_scale", 0.94)))
        low, high = sorted((min_scale, max_scale))
        aspect_ratio = width / max(height, 1)
        transform = A.RandomResizedCrop(
            size=(height, width),
            scale=(low * low, high * high),
            ratio=(aspect_ratio, aspect_ratio),
            interpolation=cv2.INTER_LANCZOS4,
            p=1.0,
        )
        op.update({"min_scale": low, "max_scale": high, "transform": type(transform).__name__})
        return transform, op
    if method == "color_jitter":
        strength = max(0.0, float(method_settings.get("strength", 0.18)))
        transform = A.ColorJitter(
            brightness=strength,
            contrast=strength,
            saturation=strength,
            hue=0.0,
            p=1.0,
        ) if strength > 0 else A.NoOp(p=1.0)
        op.update({"strength": strength, "transform": type(transform).__name__})
        return transform, op
    if method == "blur":
        max_radius = max(0.0, float(method_settings.get("max_radius", 2.4)))
        transform = A.GaussianBlur(
            blur_limit=0,
            sigma_limit=(min(0.8, max_radius), max_radius),
            p=1.0,
        ) if max_radius > 0 else A.NoOp(p=1.0)
        op.update({"max_radius": max_radius, "transform": type(transform).__name__})
        return transform, op
    if method == "noise":
        max_sigma = max(0.0, float(method_settings.get("max_sigma", 28.0)))
        min_sigma = min(max_sigma, min(12.0, max(4.0, max_sigma * 0.45)))
        transform = A.GaussNoise(
            std_range=(min_sigma / 255.0, max_sigma / 255.0),
            mean_range=(0.0, 0.0),
            per_channel=False,
            p=1.0,
        ) if max_sigma > 0 else A.NoOp(p=1.0)
        op.update({"max_sigma": max_sigma, "transform": type(transform).__name__})
        return transform, op
    if method == "occlusion":
        min_ratio = float(method_settings.get("min_ratio", 0.14))
        max_ratio = float(method_settings.get("max_ratio", 0.28))
        low, high = sorted((max(0.01, min_ratio), max(0.01, max_ratio)))
        transform = A.CoarseDropout(
            num_holes_range=(1, 1),
            hole_height_range=(low, high),
            hole_width_range=(low, high),
            fill=(40, 40, 40),
            fill_mask=0,
            p=1.0,
        )
        op.update({"min_ratio": low, "max_ratio": high, "transform": type(transform).__name__})
        return transform, op
    if method == "perspective":
        max_warp = max(0.0, float(method_settings.get("max_warp", 0.08)))
        transform = A.Perspective(
            scale=(min(0.03, max_warp), max_warp),
            keep_size=True,
            fit_output=False,
            interpolation=cv2.INTER_CUBIC,
            border_mode=cv2.BORDER_CONSTANT,
            fill=(245, 245, 245),
            fill_mask=0,
            p=1.0,
        ) if max_warp > 0 else A.NoOp(p=1.0)
        op.update({"max_warp": max_warp, "transform": type(transform).__name__})
        return transform, op
    transform = A.NoOp(p=1.0)
    op["transform"] = type(transform).__name__
    return transform, op


def _prepare_detections(
    detections: list[dict[str, Any]] | None,
) -> tuple[dict[int, dict[str, Any]], list[list[float]], list[int]]:
    source_detections: dict[int, dict[str, Any]] = {}
    bboxes: list[list[float]] = []
    detection_indices: list[int] = []
    for index, detection in enumerate(detections or []):
        bbox = detection.get("bbox")
        if not isinstance(bbox, list) or len(bbox) != 4:
            continue
        try:
            normalized_bbox = [float(value) for value in bbox]
        except (TypeError, ValueError):
            continue
        if not all(math.isfinite(value) for value in normalized_bbox):
            continue
        if normalized_bbox[2] <= 0 or normalized_bbox[3] <= 0:
            continue
        source_detections[index] = detection
        bboxes.append(normalized_bbox)
        detection_indices.append(index)
    return source_detections, bboxes, detection_indices


def _restore_detections(
    source_detections: dict[int, dict[str, Any]],
    bboxes: list[list[float]],
    detection_indices: list[float],
) -> list[dict[str, Any]]:
    restored: list[dict[str, Any]] = []
    for bbox, raw_index in zip(bboxes, detection_indices):
        try:
            source = source_detections[int(raw_index)]
            normalized_bbox = [round(float(value), 4) for value in bbox]
        except (KeyError, TypeError, ValueError):
            continue
        restored.append({**source, "bbox": normalized_bbox})
    return restored


def _filter_occluded_detections(
    detections: list[dict[str, Any]],
    visibility_mask: np.ndarray,
) -> list[dict[str, Any]]:
    height, width = visibility_mask.shape[:2]
    filtered: list[dict[str, Any]] = []
    for detection in detections:
        x_center, y_center, box_width, box_height = detection["bbox"]
        left = max(0, int(math.floor((x_center - box_width / 2) * width)))
        top = max(0, int(math.floor((y_center - box_height / 2) * height)))
        right = min(width, int(math.ceil((x_center + box_width / 2) * width)))
        bottom = min(height, int(math.ceil((y_center + box_height / 2) * height)))
        region = visibility_mask[top:bottom, left:right]
        if region.size and float(np.count_nonzero(region)) / float(region.size) >= MIN_BBOX_VISIBILITY:
            filtered.append(detection)
    return filtered


def _replay_without_occlusion(replay: dict[str, Any]) -> dict[str, Any]:
    alpha_replay = copy.deepcopy(replay)
    for transform in alpha_replay.get("transforms", []):
        if str(transform.get("__class_fullname__", "")).endswith("CoarseDropout"):
            transform["applied"] = False
            transform["params"] = None
    return alpha_replay


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    return value
