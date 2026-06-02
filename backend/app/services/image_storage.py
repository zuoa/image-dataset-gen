from __future__ import annotations

import base64
from io import BytesIO
import random
import shutil
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageOps

MAX_ROTATION_ANGLE_DEGREES = 8.0
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
    path = image_path(storage_root, task_id, image_key, extension)
    path.write_bytes(image_bytes)
    return path


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
        working = source_image.convert("RGBA" if preserve_alpha else "RGB")
        for method in applied_methods:
            working = _apply_augmentation(working, method, rng, settings)

        output = BytesIO()
        if source_format == "PNG":
            working.save(output, format="PNG")
        else:
            working.convert("RGB").save(output, format="JPEG", quality=90)
        image_bytes = output.getvalue()

    save_generated_image(storage_root, task_id, target_image_key, image_bytes, mime_type)
    return {
        "image_bytes": image_bytes,
        "mime_type": mime_type,
        "applied_methods": applied_methods,
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


def _apply_augmentation(
    image: Image.Image,
    method: str,
    rng: random.Random,
    settings: dict[str, object] | None = None,
) -> Image.Image:
    method_settings = _method_settings(settings, method)
    if method == "flip":
        flip_mode = str(method_settings.get("mode", "random"))
        if flip_mode == "horizontal":
            return ImageOps.mirror(image)
        if flip_mode == "vertical":
            return ImageOps.flip(image)
        return ImageOps.mirror(image) if rng.random() < 0.7 else ImageOps.flip(image)
    if method == "rotate":
        max_angle = max(0.0, float(method_settings.get("max_angle", MAX_ROTATION_ANGLE_DEGREES)))
        angle = rng.uniform(-max_angle, max_angle)
        fill = (245, 245, 245, 255) if image.mode == "RGBA" else (245, 245, 245)
        return image.rotate(angle, resample=Image.Resampling.BICUBIC, expand=False, fillcolor=fill)
    if method == "crop":
        width, height = image.size
        min_scale = float(method_settings.get("min_scale", 0.82))
        max_scale = float(method_settings.get("max_scale", 0.94))
        crop_ratio = rng.uniform(min(min_scale, max_scale), max(min_scale, max_scale))
        crop_w = max(8, int(width * crop_ratio))
        crop_h = max(8, int(height * crop_ratio))
        left = rng.randint(0, max(0, width - crop_w))
        top = rng.randint(0, max(0, height - crop_h))
        cropped = image.crop((left, top, left + crop_w, top + crop_h))
        return cropped.resize((width, height), Image.Resampling.LANCZOS)
    if method == "color_jitter":
        strength = max(0.0, float(method_settings.get("strength", 0.18)))
        if strength <= 0:
            return image
        working = image
        brightness = ImageEnhance.Brightness(working)
        working = brightness.enhance(rng.uniform(max(0.1, 1 - strength), 1 + strength))
        contrast = ImageEnhance.Contrast(working)
        working = contrast.enhance(rng.uniform(max(0.1, 1 - strength), 1 + strength))
        if working.mode in {"RGB", "RGBA"}:
            color = ImageEnhance.Color(working)
            working = color.enhance(rng.uniform(max(0.1, 1 - strength), 1 + strength))
        return working
    if method == "blur":
        max_radius = max(0.0, float(method_settings.get("max_radius", 2.4)))
        if max_radius <= 0:
            return image
        radius = rng.uniform(min(0.8, max_radius), max_radius)
        return image.filter(ImageFilter.GaussianBlur(radius=radius))
    if method == "noise":
        max_sigma = max(0.0, float(method_settings.get("max_sigma", 28.0)))
        if max_sigma <= 0:
            return image
        min_sigma = min(12.0, max(4.0, max_sigma * 0.45))
        noise = Image.effect_noise(image.size, rng.uniform(min_sigma, max_sigma)).convert("L")
        if image.mode == "RGBA":
            alpha = image.getchannel("A")
            rgb = image.convert("RGB")
            merged = ImageChops.add(rgb, Image.merge("RGB", (noise, noise, noise)), scale=1.0, offset=-18)
            return Image.merge("RGBA", (*merged.split(), alpha))
        return ImageChops.add(image.convert("RGB"), Image.merge("RGB", (noise, noise, noise)), scale=1.0, offset=-18)
    if method == "occlusion":
        working = image.copy()
        draw = ImageDraw.Draw(working)
        width, height = working.size
        min_ratio = float(method_settings.get("min_ratio", 0.14))
        max_ratio = float(method_settings.get("max_ratio", 0.28))
        occ_ratio = rng.uniform(min(min_ratio, max_ratio), max(min_ratio, max_ratio))
        occ_w = max(12, int(width * occ_ratio))
        occ_h = max(12, int(height * occ_ratio))
        left = rng.randint(0, max(0, width - occ_w))
        top = rng.randint(0, max(0, height - occ_h))
        fill = (rng.randint(18, 70), rng.randint(18, 70), rng.randint(18, 70), 235) if working.mode == "RGBA" else (
            rng.randint(18, 70),
            rng.randint(18, 70),
            rng.randint(18, 70),
        )
        draw.rounded_rectangle((left, top, left + occ_w, top + occ_h), radius=6, fill=fill)
        return working
    if method == "perspective":
        width, height = image.size
        max_warp = max(0.0, float(method_settings.get("max_warp", 0.08)))
        if max_warp <= 0:
            return image
        dx = width * rng.uniform(min(0.03, max_warp), max_warp)
        dy = height * rng.uniform(min(0.03, max_warp), max_warp)
        quad = (
            rng.uniform(0, dx),
            rng.uniform(0, dy),
            width - rng.uniform(0, dx),
            rng.uniform(0, dy),
            width - rng.uniform(0, dx),
            height - rng.uniform(0, dy),
            rng.uniform(0, dx),
            height - rng.uniform(0, dy),
        )
        return image.transform(image.size, Image.Transform.QUAD, quad, resample=Image.Resampling.BICUBIC)
    return image
