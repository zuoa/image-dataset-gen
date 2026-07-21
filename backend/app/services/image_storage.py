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
    "flip": {"mode": "random", "probability": 0.5},
    "rotate": {"max_angle": MAX_ROTATION_ANGLE_DEGREES},
    "crop": {"min_scale": 0.82, "max_scale": 0.94},
    "color_jitter": {"strength": 0.18},
    "blur": {"max_radius": 2.4},
    "noise": {"max_sigma": 28.0},
    "occlusion": {"min_ratio": 0.14, "max_ratio": 0.28},
    "perspective": {"max_warp": 0.08},
    "affine": {
        "min_scale": 0.85,
        "max_scale": 1.15,
        "max_translate": 0.04,
        "max_rotate": MAX_ROTATION_ANGLE_DEGREES,
        "max_shear": 3.0,
        "probability": 0.55,
    },
    "safe_crop": {
        "erosion_rate": 0.0,
        "min_scale": 0.75,
        "max_scale": 0.95,
        "probability": 0.3,
    },
    "target_occlusion": {
        "min_holes": 1,
        "max_holes": 2,
        "min_ratio": 0.18,
        "max_ratio": 0.38,
        "probability": 0.3,
    },
    "lighting": {"strength": 0.18, "probability": 0.55},
    "degradation": {"strength": 0.5, "probability": 0.35},
}

POLICY_GEOMETRY_METHODS = ("affine", "safe_crop", "rotate", "crop", "perspective")
POLICY_OCCLUSION_METHODS = ("target_occlusion", "occlusion")
POLICY_LIGHTING_METHODS = ("lighting", "color_jitter")
POLICY_DEGRADATION_METHODS = ("degradation", "blur", "noise")
APPLIED_METHOD_BY_TRANSFORM = {
    "HorizontalFlip": "flip",
    "VerticalFlip": "flip",
    "Rotate": "rotate",
    "RandomResizedCrop": "crop",
    "RandomSizedBBoxSafeCrop": "safe_crop",
    "ColorJitter": "color_jitter",
    "GaussianBlur": "blur",
    "GaussNoise": "noise",
    "CoarseDropout": "occlusion",
    "Perspective": "perspective",
    "Affine": "affine",
    "ConstrainedCoarseDropout": "target_occlusion",
    "RandomBrightnessContrast": "brightness_contrast",
    "RandomGamma": "gamma",
    "PlanckianJitter": "color_temperature",
    "ImageCompression": "image_compression",
    "Downscale": "downscale",
    "MotionBlur": "motion_blur",
    "Defocus": "defocus",
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
    policy_version: int = 1,
) -> dict[str, object] | None:
    source_path = existing_generated_image(storage_root, task_id, source_image_key)
    if source_path is None:
        return None

    rng = random.Random(seed)
    mime_type = "image/png" if source_path.suffix.lower() == ".png" else "image/jpeg"
    source_format = "PNG" if mime_type == "image/png" else "JPEG"

    with Image.open(source_path) as source_image:
        preserve_alpha = source_image.mode in {"RGBA", "LA"} or "transparency" in source_image.info
        source_rgb = np.asarray(source_image.convert("RGB"))
        source_alpha = np.asarray(source_image.convert("RGBA").getchannel("A")) if preserve_alpha else None
        height, width = source_rgb.shape[:2]
        source_detections, bboxes, detection_indices = _prepare_detections(detections)
        if policy_version >= 2:
            transforms, augmentation_ops = _build_policy_transforms(
                methods,
                rng,
                settings,
                width,
                height,
                detection_indices,
            )
            applied_methods: list[str] = []
        else:
            applied_methods = _pick_augmentation_methods(methods, rng)
            transforms = []
            augmentation_ops = []
            for method in applied_methods:
                transform, op = _build_augmentation_transform(method, rng, settings, width, height)
                transforms.append(transform)
                augmentation_ops.append(op)

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
        transform_inputs: dict[str, Any] = {
            "image": source_rgb,
            "bboxes": bboxes,
            "detection_indices": detection_indices,
        }
        if any(method in {"occlusion", "target_occlusion"} for method in methods):
            transform_inputs["mask"] = np.ones((height, width), dtype=np.uint8)
        max_attempts = 3 if policy_version >= 2 else 1
        for attempt in range(max_attempts):
            pipeline.set_random_seed(seed + attempt)
            transformed = pipeline(**transform_inputs)
            if policy_version < 2:
                break
            applied_methods = _applied_methods_from_replay(transformed["replay"])
            if applied_methods:
                break
        transformed_image = np.asarray(transformed["image"], dtype=np.uint8)
        dropout_applied = _replay_has_applied_dropout(transformed["replay"])
        bbox_result = transformed
        replay_without_occlusion: dict[str, Any] | None = None
        if detections is not None and dropout_applied:
            replay_without_occlusion = _replay_without_occlusion(transformed["replay"])
            bbox_result = A.ReplayCompose.replay(
                replay_without_occlusion,
                image=source_rgb,
                bboxes=bboxes,
                detection_indices=detection_indices,
            )
        transformed_detections = (
            _restore_detections(
                source_detections,
                bbox_result.get("bboxes", []),
                bbox_result.get("detection_indices", []),
            )
            if detections is not None
            else None
        )
        if (
            transformed_detections is not None
            and "mask" in transformed
            and dropout_applied
        ):
            transformed_detections = _filter_occluded_detections(
                transformed_detections,
                np.asarray(transformed["mask"]),
            )

        if source_alpha is not None:
            alpha_replay = replay_without_occlusion or _replay_without_occlusion(transformed["replay"])
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


def _setting_probability(
    settings: dict[str, object] | None,
    method: str,
    default: float,
) -> float:
    method_settings = _method_settings(settings, method)
    try:
        probability = float(method_settings.get("probability", default))
    except (TypeError, ValueError):
        return default
    return min(max(probability, 0.0), 1.0)


def _combined_probability(probabilities: list[float]) -> float:
    return min(sum(min(max(probability, 0.0), 1.0) for probability in probabilities), 1.0)


def _build_policy_stage(
    candidates: list[tuple[A.BasicTransform, dict[str, Any], float]],
    stage: str,
) -> tuple[A.BasicTransform, dict[str, Any]] | None:
    active = [(transform, op, probability) for transform, op, probability in candidates if probability > 0]
    if not active:
        return None

    probabilities = [probability for _, _, probability in active]
    stage_probability = _combined_probability(probabilities)
    if len(active) == 1:
        transform, op, _ = active[0]
        transform.p = stage_probability
        return transform, {**op, "stage": stage, "probability": stage_probability}

    for transform, _, probability in active:
        transform.p = probability
    return (
        A.OneOf([transform for transform, _, _ in active], p=stage_probability),
        {
            "method": stage,
            "stage": stage,
            "probability": stage_probability,
            "candidates": [op for _, op, _ in active],
            "transform": "OneOf",
        },
    )


def _build_policy_transforms(
    methods: list[str],
    rng: random.Random,
    settings: dict[str, object] | None,
    width: int,
    height: int,
    detection_indices: list[int],
) -> tuple[list[A.BasicTransform], list[dict[str, Any]]]:
    selected = set(dict.fromkeys(method for method in methods if method))
    transforms: list[A.BasicTransform] = []
    augmentation_ops: list[dict[str, Any]] = []

    if "flip" in selected:
        transform, op = _build_augmentation_transform("flip", rng, settings, width, height)
        probability = _setting_probability(settings, "flip", 0.5)
        transform.p = probability
        transforms.append(transform)
        augmentation_ops.append({**op, "stage": "flip", "probability": probability})

    geometry_candidates: list[tuple[A.BasicTransform, dict[str, Any], float]] = []
    for method in POLICY_GEOMETRY_METHODS:
        if method not in selected:
            continue
        if method == "affine":
            transform, op = _build_affine_transform(settings, width, height)
            probability = _setting_probability(settings, method, 0.55)
        elif method == "safe_crop":
            transform, op = _build_safe_crop_transform(
                settings,
                width,
                height,
                has_detections=bool(detection_indices),
            )
            probability = _setting_probability(settings, method, 0.3)
        else:
            transform, op = _build_augmentation_transform(method, rng, settings, width, height)
            probability = _setting_probability(settings, method, 0.25)
        geometry_candidates.append((transform, op, probability))
    geometry_stage = _build_policy_stage(geometry_candidates, "geometry")
    if geometry_stage is not None:
        transform, op = geometry_stage
        transforms.append(transform)
        augmentation_ops.append(op)

    occlusion_candidates: list[tuple[A.BasicTransform, dict[str, Any], float]] = []
    for method in POLICY_OCCLUSION_METHODS:
        if method not in selected:
            continue
        if method == "target_occlusion":
            transform, op = _build_target_occlusion_transform(
                settings,
                width,
                height,
                detection_indices,
            )
            probability = _setting_probability(settings, method, 0.3)
        else:
            transform, op = _build_augmentation_transform(method, rng, settings, width, height)
            probability = _setting_probability(settings, method, 0.25)
        occlusion_candidates.append((transform, op, probability))
    occlusion_stage = _build_policy_stage(occlusion_candidates, "occlusion")
    if occlusion_stage is not None:
        transform, op = occlusion_stage
        transforms.append(transform)
        augmentation_ops.append(op)

    lighting_candidates: list[tuple[A.BasicTransform, dict[str, Any], float]] = []
    for method in POLICY_LIGHTING_METHODS:
        if method not in selected:
            continue
        if method == "lighting":
            transform, op = _build_lighting_transform(settings, width, height)
            probability = _setting_probability(settings, method, 0.55)
        else:
            transform, op = _build_augmentation_transform(method, rng, settings, width, height)
            probability = _setting_probability(settings, method, 0.45)
        lighting_candidates.append((transform, op, probability))
    lighting_stage = _build_policy_stage(lighting_candidates, "lighting")
    if lighting_stage is not None:
        transform, op = lighting_stage
        transforms.append(transform)
        augmentation_ops.append(op)

    degradation_candidates: list[tuple[A.BasicTransform, dict[str, Any], float]] = []
    for method in POLICY_DEGRADATION_METHODS:
        if method not in selected:
            continue
        if method == "degradation":
            transform, op = _build_degradation_transform(settings, width, height)
            probability = _setting_probability(settings, method, 0.35)
        else:
            transform, op = _build_augmentation_transform(method, rng, settings, width, height)
            probability = _setting_probability(settings, method, 0.25)
        degradation_candidates.append((transform, op, probability))
    degradation_stage = _build_policy_stage(degradation_candidates, "degradation")
    if degradation_stage is not None:
        transform, op = degradation_stage
        transforms.append(transform)
        augmentation_ops.append(op)

    if not transforms:
        transforms.append(A.NoOp(p=1.0))
        augmentation_ops.append({"method": "noop", "transform": "NoOp", "size": [width, height]})
    return transforms, augmentation_ops


def _build_affine_transform(
    settings: dict[str, object] | None,
    width: int,
    height: int,
) -> tuple[A.BasicTransform, dict[str, Any]]:
    method_settings = _method_settings(settings, "affine")
    min_scale = max(0.1, float(method_settings.get("min_scale", 0.85)))
    max_scale = max(0.1, float(method_settings.get("max_scale", 1.15)))
    low_scale, high_scale = sorted((min_scale, max_scale))
    max_translate = min(max(float(method_settings.get("max_translate", 0.04)), 0.0), 1.0)
    max_rotate = max(float(method_settings.get("max_rotate", MAX_ROTATION_ANGLE_DEGREES)), 0.0)
    max_shear = max(float(method_settings.get("max_shear", 3.0)), 0.0)
    transform = A.Affine(
        scale=(low_scale, high_scale),
        translate_percent=(-max_translate, max_translate),
        rotate=(-max_rotate, max_rotate),
        shear=(-max_shear, max_shear),
        interpolation=cv2.INTER_CUBIC,
        mask_interpolation=cv2.INTER_NEAREST,
        balanced_scale=low_scale < 1.0 < high_scale,
        border_mode=cv2.BORDER_CONSTANT,
        fill=(245, 245, 245),
        fill_mask=0,
        p=1.0,
    )
    return transform, {
        "method": "affine",
        "size": [width, height],
        "min_scale": low_scale,
        "max_scale": high_scale,
        "max_translate": max_translate,
        "max_rotate": max_rotate,
        "max_shear": max_shear,
        "transform": "Affine",
    }


def _build_safe_crop_transform(
    settings: dict[str, object] | None,
    width: int,
    height: int,
    *,
    has_detections: bool,
) -> tuple[A.BasicTransform, dict[str, Any]]:
    method_settings = _method_settings(settings, "safe_crop")
    erosion_rate = min(max(float(method_settings.get("erosion_rate", 0.0)), 0.0), 1.0)
    if has_detections:
        transform: A.BasicTransform = A.RandomSizedBBoxSafeCrop(
            height=height,
            width=width,
            erosion_rate=erosion_rate,
            interpolation=cv2.INTER_LANCZOS4,
            mask_interpolation=cv2.INTER_NEAREST,
            p=1.0,
        )
    else:
        min_scale = min(max(float(method_settings.get("min_scale", 0.75)), 0.05), 1.0)
        max_scale = min(max(float(method_settings.get("max_scale", 0.95)), 0.05), 1.0)
        low_scale, high_scale = sorted((min_scale, max_scale))
        aspect_ratio = width / max(height, 1)
        transform = A.RandomResizedCrop(
            size=(height, width),
            scale=(low_scale, high_scale),
            ratio=(max(0.05, aspect_ratio * 0.9), aspect_ratio * 1.1),
            interpolation=cv2.INTER_LANCZOS4,
            mask_interpolation=cv2.INTER_NEAREST,
            p=1.0,
        )
    return transform, {
        "method": "safe_crop",
        "size": [width, height],
        "erosion_rate": erosion_rate,
        "bbox_safe": has_detections,
        "transform": type(transform).__name__,
    }


def _build_target_occlusion_transform(
    settings: dict[str, object] | None,
    width: int,
    height: int,
    detection_indices: list[int],
) -> tuple[A.BasicTransform, dict[str, Any]]:
    method_settings = _method_settings(settings, "target_occlusion")
    min_holes = max(1, int(method_settings.get("min_holes", 1)))
    max_holes = max(1, int(method_settings.get("max_holes", 2)))
    low_holes, high_holes = sorted((min_holes, max_holes))
    min_ratio = min(max(float(method_settings.get("min_ratio", 0.18)), 0.01), 1.0)
    max_ratio = min(max(float(method_settings.get("max_ratio", 0.38)), 0.01), 1.0)
    low_ratio, high_ratio = sorted((min_ratio, max_ratio))
    if detection_indices:
        transform: A.BasicTransform = A.ConstrainedCoarseDropout(
            num_holes_range=(low_holes, high_holes),
            hole_height_range=(low_ratio, high_ratio),
            hole_width_range=(low_ratio, high_ratio),
            fill="random_uniform",
            fill_mask=0,
            bbox_labels=detection_indices,
            p=1.0,
        )
    else:
        transform = A.CoarseDropout(
            num_holes_range=(low_holes, high_holes),
            hole_height_range=(min(low_ratio, 0.08), min(high_ratio, 0.18)),
            hole_width_range=(min(low_ratio, 0.08), min(high_ratio, 0.18)),
            fill="random_uniform",
            fill_mask=0,
            p=1.0,
        )
    return transform, {
        "method": "target_occlusion",
        "size": [width, height],
        "min_holes": low_holes,
        "max_holes": high_holes,
        "min_ratio": low_ratio,
        "max_ratio": high_ratio,
        "bbox_constrained": bool(detection_indices),
        "transform": type(transform).__name__,
    }


def _build_lighting_transform(
    settings: dict[str, object] | None,
    width: int,
    height: int,
) -> tuple[A.BasicTransform, dict[str, Any]]:
    method_settings = _method_settings(settings, "lighting")
    strength = min(max(float(method_settings.get("strength", 0.18)), 0.0), 0.5)
    gamma_delta = max(1, int(round(strength * 100)))
    temperature_delta = max(250, int(round(strength * 10_000)))
    transform = A.OneOf(
        [
            A.RandomBrightnessContrast(
                brightness_limit=strength,
                contrast_limit=strength,
                p=0.35,
            ),
            A.RandomGamma(
                gamma_limit=(max(1, 100 - gamma_delta), 100 + gamma_delta),
                p=0.25,
            ),
            A.PlanckianJitter(
                mode="blackbody",
                temperature_limit=(
                    max(3000, 6500 - temperature_delta),
                    min(15000, 6500 + temperature_delta),
                ),
                sampling_method="gaussian",
                p=0.25,
            ),
            A.ColorJitter(
                brightness=0.0,
                contrast=0.0,
                saturation=strength,
                hue=min(0.05, strength / 4),
                p=0.15,
            ),
        ],
        p=1.0,
    )
    return transform, {
        "method": "lighting",
        "size": [width, height],
        "strength": strength,
        "transform": "OneOf",
    }


def _build_degradation_transform(
    settings: dict[str, object] | None,
    width: int,
    height: int,
) -> tuple[A.BasicTransform, dict[str, Any]]:
    method_settings = _method_settings(settings, "degradation")
    strength = min(max(float(method_settings.get("strength", 0.5)), 0.0), 1.0)
    min_quality = max(25, int(round(90 - 50 * strength)))
    min_downscale = max(0.25, 1.0 - 0.7 * strength)
    max_downscale = max(min_downscale, 1.0 - 0.2 * strength)
    max_blur_kernel = 3 + 2 * max(1, int(round(strength * 3)))
    max_defocus_radius = max(2, 2 + int(round(strength * 6)))
    transform = A.OneOf(
        [
            A.ImageCompression(
                compression_type="jpeg",
                quality_range=(min_quality, 95),
                p=0.3,
            ),
            A.Downscale(
                scale_range=(min_downscale, max_downscale),
                interpolation_pair={
                    "downscale": cv2.INTER_AREA,
                    "upscale": cv2.INTER_LINEAR,
                },
                p=0.25,
            ),
            A.MotionBlur(blur_limit=(3, max_blur_kernel), p=0.2),
            A.Defocus(radius=(2, max_defocus_radius), alias_blur=(0.1, 0.4), p=0.1),
            A.GaussNoise(
                std_range=(0.01, 0.02 + 0.08 * strength),
                mean_range=(0.0, 0.0),
                per_channel=True,
                p=0.15,
            ),
        ],
        p=1.0,
    )
    return transform, {
        "method": "degradation",
        "size": [width, height],
        "strength": strength,
        "transform": "OneOf",
    }


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


def _applied_methods_from_replay(replay: dict[str, Any]) -> list[str]:
    applied_methods: list[str] = []

    def collect(transform: dict[str, Any]) -> None:
        nested = transform.get("transforms")
        if isinstance(nested, list):
            for child in nested:
                if isinstance(child, dict):
                    collect(child)
            return
        if not transform.get("applied"):
            return
        class_name = str(transform.get("__class_fullname__", "")).rsplit(".", 1)[-1]
        method = APPLIED_METHOD_BY_TRANSFORM.get(class_name)
        if method and method not in applied_methods:
            applied_methods.append(method)

    for transform in replay.get("transforms", []):
        if isinstance(transform, dict):
            collect(transform)
    return applied_methods


def _replay_has_applied_dropout(replay: dict[str, Any]) -> bool:
    def contains(transform: dict[str, Any]) -> bool:
        class_name = str(transform.get("__class_fullname__", "")).rsplit(".", 1)[-1]
        if transform.get("applied") and class_name.endswith("CoarseDropout"):
            return True
        nested = transform.get("transforms")
        return isinstance(nested, list) and any(
            contains(child) for child in nested if isinstance(child, dict)
        )

    return any(
        contains(transform)
        for transform in replay.get("transforms", [])
        if isinstance(transform, dict)
    )


def _replay_without_occlusion(replay: dict[str, Any]) -> dict[str, Any]:
    alpha_replay = copy.deepcopy(replay)

    def remove_dropout(transform: dict[str, Any]) -> bool:
        if str(transform.get("__class_fullname__", "")).endswith("CoarseDropout"):
            transform["applied"] = False
            transform["params"] = None
            return False
        nested = transform.get("transforms")
        if isinstance(nested, list):
            nested_states = [
                remove_dropout(child) for child in nested if isinstance(child, dict)
            ]
            nested_applied = any(nested_states)
            if transform.get("applied") and not nested_applied:
                transform["applied"] = False
                transform["params"] = None
            return bool(transform.get("applied"))
        return bool(transform.get("applied"))

    for transform in alpha_replay.get("transforms", []):
        if isinstance(transform, dict):
            remove_dropout(transform)
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
