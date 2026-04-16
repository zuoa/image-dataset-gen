from __future__ import annotations

import base64
import io
import json
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from urllib import error, request

from PIL import Image, ImageDraw

from app.models import Dataset
from app.services.image_storage import existing_generated_image


def annotate_dataset_images(
    dataset: Dataset,
    confidence_threshold: float,
    annotator_url: str,
    storage_root: str,
    vl_config: dict[str, str] | None = None,
    images: list | None = None,
) -> list[dict[str, Any]]:
    target_images = images if images is not None else dataset.images
    payload = {
        "taskId": dataset.id,
        "subject": dataset.name,
        "categories": dataset.categories,
        "confidenceThreshold": confidence_threshold,
        "images": [
            {
                "imageId": image.id,
                "ordinal": image.ordinal,
                "seed": image.seed,
                "categoryHint": dataset.categories[0] if dataset.categories else "default",
                "promptText": image.prompt_text,
            }
            for image in target_images
        ],
    }

    vl_config = vl_config or {}
    if vl_config.get("api_key"):
        return _vl_annotate_dataset(dataset, confidence_threshold, storage_root, vl_config, target_images)

    if annotator_url:
        return _remote_annotate(payload, annotator_url)

    return _local_annotate(payload)


def _remote_annotate(payload: dict[str, Any], annotator_url: str) -> list[dict[str, Any]]:
    http_request = request.Request(
        f"{annotator_url.rstrip('/')}/annotate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(http_request, timeout=15) as response:
            body = json.loads(response.read().decode("utf-8"))
            return body["results"]
    except (error.URLError, TimeoutError, KeyError, json.JSONDecodeError):
        return _local_annotate(payload)


def _vl_annotate_dataset(
    dataset: Dataset,
    confidence_threshold: float,
    storage_root: str,
    vl_config: dict[str, str],
    images: list | None = None,
) -> list[dict[str, Any]]:
    provider = vl_config.get("provider", "gemini")
    model = vl_config.get("model", "gemini-2.0-flash")
    api_key = vl_config.get("api_key", "")
    base_url = vl_config.get("base_url", "")

    if not api_key:
        target_images = images if images is not None else dataset.images
        return _local_annotate(
            {
                "taskId": dataset.id,
                "subject": dataset.name,
                "categories": dataset.categories,
                "confidenceThreshold": confidence_threshold,
                "images": [
                    {
                        "imageId": image.id,
                        "ordinal": image.ordinal,
                        "seed": image.seed,
                        "categoryHint": dataset.categories[0] if dataset.categories else "default",
                        "promptText": image.prompt_text,
                    }
                    for image in target_images
                ],
            }
        )

    target_images = images if images is not None else dataset.images
    categories = dataset.categories or ["default"]
    allowed = set(categories)

    def annotate_single(image: Any) -> dict[str, Any]:
        path = existing_generated_image(storage_root, dataset.id, f"image-{image.ordinal:06d}")
        if not path:
            return {"imageId": image.id, "detections": [], "status": "empty"}

        try:
            with Image.open(path) as pil_img:
                img_w, img_h = pil_img.size
        except Exception:
            return {"imageId": image.id, "detections": [], "status": "empty"}

        image_bytes = path.read_bytes()
        mime_type = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
        b64 = base64.b64encode(image_bytes).decode("utf-8")
        prompt = _build_vl_prompt(dataset.name, categories, getattr(image, "prompt_text", ""), img_w=img_w, img_h=img_h, provider=provider)

        try:
            if provider == "gemini":
                raw = _call_gemini_vl(api_key, model, prompt, mime_type, b64)
            else:
                raw = _call_openai_compat_vl(base_url, api_key, model, prompt, mime_type, b64)
            detections = _parse_vl_response(raw, confidence_threshold, allowed, img_w, img_h)

            # Self-check: draw predictions and ask model to refine
            if provider != "gemini" and detections:
                try:
                    with Image.open(path) as refine_img:
                        detections = _refine_detections(
                            provider, model, api_key, base_url, refine_img,
                            detections, categories, img_w, img_h,
                        )
                except Exception:
                    pass

            return {"imageId": image.id, "detections": detections, "status": "annotated" if detections else "empty"}
        except Exception:
            return {"imageId": image.id, "detections": [], "status": "empty"}

    with ThreadPoolExecutor(max_workers=3) as executor:
        results = list(executor.map(annotate_single, target_images))

    return results


def _build_vl_prompt(subject: str, categories: list[str], prompt_text: str = "", *, img_w: int = 0, img_h: int = 0, provider: str = "gemini") -> str:
    categories_str = ", ".join(categories)

    if provider != "gemini" and img_w > 0 and img_h > 0:
        # Qwen2.5-VL native bbox_2d grounding format
        parts = [
            f"Detect all visible instances of these categories in the image: {categories_str}.",
            f"Image dimensions: {img_w} x {img_h} pixels.",
            "",
            "Return a JSON array where each element contains:",
            '  "bbox_2d": [x1, y1, x2, y2] in pixel coordinates matching the image dimensions,',
            '  "label": the detected category,',
            '  "confidence": float between 0 and 1.',
            "",
            "Rules:",
            "- [x1, y1] = top-left corner, [x2, y2] = bottom-right corner.",
            "- The box must TIGHTLY hug the object's visible outline with minimal margin.",
            "- Do NOT pad the box with extra background.",
            "- A typical object occupies only a fraction of the image — avoid oversized boxes.",
        ]
        if prompt_text:
            parts.append(f'- Generation context: "{prompt_text}".')
        parts.extend([
            "",
            'Output strictly as JSON with no markdown: [{"bbox_2d": [x1, y1, x2, y2], "label": "...", "confidence": 0.95}]',
            "If nothing is found, return [].",
        ])
        return "\n".join(parts)

    # Gemini / generic format
    parts = [
        "You are a professional bounding-box annotator. Your ONLY task is to output precise, tight bounding boxes.",
        f"Dataset subject: '{subject}'.",
        f"Target categories: {categories_str}.",
    ]
    if prompt_text:
        parts.append(f'Image was generated from prompt: "{prompt_text}".')
    parts.extend([
        "",
        "CRITICAL RULES FOR BOUNDING BOXES:",
        "- Format: normalized [x_center, y_center, width, height], all values between 0 and 1.",
        "- The box must tightly contour the object's actual visible boundary — no extra margin.",
        "- Do NOT add any padding or safety margin around the object.",
        "- If the object occupies a small region, return a small box. A typical object in these images is often only 10-25% of the image dimension.",
        "- WRONG: a loose box covering the whole object with lots of background — this is the most common mistake.",
        "- RIGHT: a box that closely hugs the exact outline of the object.",
        "- Before finalizing each box, ask yourself: can I shrink this box by 30% and still contain the object? If yes, your box is too large.",
        "",
        "Steps:",
        "1. Identify each clearly visible object matching a target category.",
        "2. For each object, carefully trace its visual outline and place the box right at that boundary.",
        "3. Return category, confidence (0-1), and bounding box.",
        "",
        'Return strictly as JSON with no markdown: {"detections": [{"category": "...", "confidence": 0.95, "bbox": [0.5, 0.5, 0.15, 0.2]}]}. '
        'If nothing is found, return {"detections": []}.',
    ])
    return "\n".join(parts)


def _call_gemini_vl(api_key: str, model: str, prompt: str, mime_type: str, b64_data: str) -> str:
    body = {
        "contents": [{
            "parts": [
                {"text": prompt},
                {"inlineData": {"mimeType": mime_type, "data": b64_data}},
            ],
        }],
        "generationConfig": {
            "responseMimeType": "application/json",
        },
    }
    req = request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
        method="POST",
    )
    with request.urlopen(req, timeout=60) as resp:
        payload = json.loads(resp.read().decode("utf-8"))

    candidates = payload.get("candidates", [])
    for candidate in candidates:
        content = candidate.get("content", {})
        parts = content.get("parts", [])
        for part in parts:
            text = part.get("text", "")
            if text:
                return text
    return ""


def _call_openai_compat_vl(base_url: str, api_key: str, model: str, prompt: str, mime_type: str, b64_data: str) -> str:
    body = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{b64_data}"}},
                ],
            }
        ],
        "response_format": {"type": "json_object"},
    }
    req = request.Request(
        f"{base_url.rstrip('/')}/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    with request.urlopen(req, timeout=60) as resp:
        payload = json.loads(resp.read().decode("utf-8"))

    choices = payload.get("choices", [])
    if choices:
        content = choices[0].get("message", {}).get("content", "")
        if isinstance(content, str):
            return content
    return ""


def _parse_vl_response(
    raw: str,
    threshold: float,
    allowed_categories: set[str],
    img_w: int = 1,
    img_h: int = 1,
) -> list[dict[str, Any]]:
    # Strip markdown code fences if present
    text = raw.strip()
    if text.startswith("```"):
        nl = text.find("\n")
        if nl != -1:
            text = text[nl + 1:]
        if text.endswith("```"):
            text = text[:-3].rstrip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []

    # Normalize response to a flat list of detection dicts
    items: list[dict] = []
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        items = data.get("detections", [])
        if not items:
            for v in data.values():
                if isinstance(v, list) and v and isinstance(v[0], dict):
                    items = v
                    break

    fallback_category = next(iter(allowed_categories), "object")
    detections: list[dict[str, Any]] = []

    for item in items:
        if not isinstance(item, dict):
            continue

        # --- Qwen2.5-VL bbox_2d format: pixel [x1, y1, x2, y2] ---
        if "bbox_2d" in item:
            category = str(item.get("label", "")).strip()
            confidence = float(item.get("confidence", 0))
            bbox_2d = item["bbox_2d"]
            if not category or not isinstance(bbox_2d, list) or len(bbox_2d) != 4:
                continue
            if category not in allowed_categories:
                category = fallback_category
            if confidence < threshold:
                continue
            try:
                x1, y1, x2, y2 = (float(v) for v in bbox_2d)
            except (ValueError, TypeError):
                continue
            nw = img_w if img_w > 0 else 1
            nh = img_h if img_h > 0 else 1
            bw = max((x2 - x1) / nw, 0.01)
            bh = max((y2 - y1) / nh, 0.01)
            cx = (x1 + x2) / 2 / nw
            cy = (y1 + y2) / 2 / nh
            cx = max(bw / 2, min(cx, 1.0 - bw / 2))
            cy = max(bh / 2, min(cy, 1.0 - bh / 2))
            detections.append({
                "category": category,
                "confidence": round(confidence, 4),
                "bbox": [round(cx, 4), round(cy, 4), round(bw, 4), round(bh, 4)],
            })
            continue

        # --- Original format: normalized [x_center, y_center, width, height] ---
        category = str(item.get("category", "")).strip()
        confidence = float(item.get("confidence", 0))
        bbox = item.get("bbox", [])
        if not category:
            continue
        if category not in allowed_categories:
            category = fallback_category
        if confidence < threshold:
            continue
        if not isinstance(bbox, list) or len(bbox) != 4:
            continue
        try:
            bbox = [float(v) for v in bbox]
        except (ValueError, TypeError):
            continue

        # Normalize pixel coordinates to 0-1 if necessary
        if any(v > 1.0 for v in bbox):
            bbox = [bbox[0] / img_w, bbox[1] / img_h, bbox[2] / img_w, bbox[3] / img_h]

        x_center = min(max(bbox[0], 0.0), 1.0)
        y_center = min(max(bbox[1], 0.0), 1.0)
        width = min(max(bbox[2], 0.0), 1.0)
        height = min(max(bbox[3], 0.0), 1.0)

        # Keep box within image bounds
        x_center = min(x_center, 1.0 - width / 2)
        x_center = max(x_center, width / 2)
        y_center = min(y_center, 1.0 - height / 2)
        y_center = max(y_center, height / 2)

        # Minor shrink to compensate for VL over-estimation
        shrink = 0.92
        width *= shrink
        height *= shrink
        x_center = min(max(x_center, width / 2), 1.0 - width / 2)
        y_center = min(max(y_center, height / 2), 1.0 - height / 2)

        detections.append({
            "category": category,
            "confidence": round(confidence, 4),
            "bbox": [round(x_center, 4), round(y_center, 4), round(width, 4), round(height, 4)],
        })
    return detections


def _draw_boxes_on_image(pil_img: Image.Image, detections: list[dict], img_w: int, img_h: int) -> None:
    """Draw detection boxes and coordinate rulers on image (in-place)."""
    draw = ImageDraw.Draw(pil_img)

    # Draw rulers on top edge
    step_x = max(img_w // 10, 1)
    for i in range(0, img_w + 1, step_x):
        draw.line([(i, 0), (i, 18)], fill=(0, 200, 0), width=1)
        draw.text((i + 2, 1), str(i), fill=(0, 200, 0))

    # Draw rulers on left edge
    step_y = max(img_h // 10, 1)
    for i in range(0, img_h + 1, step_y):
        draw.line([(0, i), (18, i)], fill=(0, 200, 0), width=1)
        draw.text((1, i + 2), str(i), fill=(0, 200, 0))

    # Draw each detection box with corner coordinates
    colors = [(255, 50, 50), (50, 50, 255), (255, 165, 0), (0, 200, 200)]
    for idx, det in enumerate(detections):
        cx, cy, bw, bh = det["bbox"]
        x1 = int((cx - bw / 2) * img_w)
        y1 = int((cy - bh / 2) * img_h)
        x2 = int((cx + bw / 2) * img_w)
        y2 = int((cy + bh / 2) * img_h)
        color = colors[idx % len(colors)]
        draw.rectangle([x1, y1, x2, y2], outline=color, width=2)
        draw.text((x1 + 2, max(y1 - 14, 18)), f"#{idx + 1} ({x1},{y1})", fill=color)
        draw.text((max(x2 - 60, 0), min(y2 + 2, img_h - 14)), f"({x2},{y2})", fill=color)


def _build_self_check_prompt(categories: list[str], detections: list[dict], img_w: int, img_h: int) -> str:
    """Build prompt asking model to verify and refine bounding boxes."""
    categories_str = ", ".join(categories)
    pred_lines = []
    for i, det in enumerate(detections):
        cx, cy, bw, bh = det["bbox"]
        x1 = round((cx - bw / 2) * img_w)
        y1 = round((cy - bh / 2) * img_h)
        x2 = round((cx + bw / 2) * img_w)
        y2 = round((cy + bh / 2) * img_h)
        pred_lines.append(f"  #{i + 1}: bbox_2d=[{x1}, {y1}, {x2}, {y2}] label={det['category']}")

    return "\n".join([
        f"The image shows predicted bounding boxes (colored rectangles) for: {categories_str}.",
        f"Image dimensions: {img_w} x {img_h} pixels.",
        "Rulers with pixel values are drawn on the top and left edges for reference.",
        "",
        "Current predictions:",
        *pred_lines,
        "",
        "Review each box. Fix these common issues:",
        "- Box too large (includes background) → shrink to tightly fit the object.",
        "- Box too small (cuts off part of the object) → expand slightly.",
        "- Box misaligned → shift to better center the object.",
        "",
        "Return ALL boxes (including unchanged ones):",
        '[{"bbox_2d": [x1, y1, x2, y2], "label": "...", "confidence": 0.95}]',
    ])


def _refine_detections(
    provider: str,
    model: str,
    api_key: str,
    base_url: str,
    pil_img: Image.Image,
    detections: list[dict],
    categories: list[str],
    img_w: int,
    img_h: int,
) -> list[dict]:
    """Self-check: draw predictions on image and ask model to refine."""
    if not detections:
        return detections

    annotated = pil_img.copy()
    _draw_boxes_on_image(annotated, detections, img_w, img_h)

    buf = io.BytesIO()
    annotated.save(buf, format="PNG")
    annotated_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

    prompt = _build_self_check_prompt(categories, detections, img_w, img_h)

    if provider == "gemini":
        raw = _call_gemini_vl(api_key, model, prompt, "image/png", annotated_b64)
    else:
        raw = _call_openai_compat_vl(base_url, api_key, model, prompt, "image/png", annotated_b64)

    allowed = set(categories)
    refined = _parse_vl_response(raw, 0.0, allowed, img_w, img_h)
    return refined if refined else detections


def _local_annotate(payload: dict[str, Any]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    threshold = float(payload["confidenceThreshold"])
    categories = payload.get("categories") or ["default"]

    for image in payload["images"]:
        detections: list[dict[str, Any]] = []
        seed = int(image["seed"])
        confidence = round(0.58 + ((seed % 35) / 100), 2)
        if image["ordinal"] % 7 != 0 and confidence >= threshold:
            x_center = round(min(0.24 + ((seed % 37) / 100), 0.84), 4)
            y_center = round(min(0.26 + (((seed // 10) % 33) / 100), 0.84), 4)
            width = round(min(0.10 + (((seed // 100) % 7) / 100), 0.18), 4)
            height = round(min(0.12 + (((seed // 1000) % 7) / 100), 0.20), 4)
            detections.append(
                {
                    "category": image["categoryHint"],
                    "confidence": confidence,
                    "bbox": [x_center, y_center, width, height],
                }
            )
        results.append(
            {
                "imageId": image["imageId"],
                "detections": detections,
                "status": "annotated" if detections else "empty",
            }
        )

    return results
