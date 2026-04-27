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

MAX_PROMPT_CONTEXT_CHARS = 160
LARGE_BOX_AREA_THRESHOLD = 0.12
LARGE_BOX_DIM_THRESHOLD = 0.34
TIGHTEN_MARGIN_RATIO = 0.18
TIGHTEN_MIN_MARGIN_PX = 24
TIGHTEN_MAX_CENTER_SHIFT = 0.12
TIGHTEN_MAX_AREA_EXPANSION = 1.08
MERGE_IOU_THRESHOLD = 0.65
MERGE_CONFIDENCE_EPS = 0.05


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
        prompt_text = getattr(image, "prompt_text", "")
        detect_targets: list[str | None]
        if provider != "gemini" and len(categories) <= 6:
            detect_targets = list(categories)
        else:
            detect_targets = [None]

        try:
            detections: list[dict[str, Any]] = []
            for target_category in detect_targets:
                prompt = _build_vl_prompt(
                    dataset.name,
                    categories,
                    prompt_text,
                    img_w=img_w,
                    img_h=img_h,
                    provider=provider,
                    target_category=target_category,
                )
                raw = _call_vl_model(provider, base_url, api_key, model, prompt, mime_type, b64)
                detections.extend(
                    _parse_vl_response(
                        raw,
                        confidence_threshold,
                        {target_category} if target_category else allowed,
                        img_w,
                        img_h,
                    )
                )

            detections = _merge_detections(detections)

            if provider != "gemini" and detections:
                try:
                    with Image.open(path) as refine_img:
                        detections = _tighten_large_detections(
                            provider,
                            model,
                            api_key,
                            base_url,
                            refine_img,
                            detections,
                            img_w,
                            img_h,
                        )
                        if len(detections) > 1:
                            detections = _merge_detections(
                                _refine_detections(
                                    provider,
                                    model,
                                    api_key,
                                    base_url,
                                    refine_img,
                                    detections,
                                    categories,
                                    img_w,
                                    img_h,
                                )
                            )
                except Exception:
                    pass

            return {"imageId": image.id, "detections": detections, "status": "annotated" if detections else "empty"}
        except Exception:
            return {"imageId": image.id, "detections": [], "status": "empty"}

    with ThreadPoolExecutor(max_workers=3) as executor:
        results = list(executor.map(annotate_single, target_images))

    return results


def _build_vl_prompt(
    subject: str,
    categories: list[str],
    prompt_text: str = "",
    *,
    img_w: int = 0,
    img_h: int = 0,
    provider: str = "gemini",
    target_category: str | None = None,
) -> str:
    categories_str = ", ".join(categories)

    if provider != "gemini" and img_w > 0 and img_h > 0:
        focus_line = f"Target category: {target_category}." if target_category else f"Target categories: {categories_str}."
        parts = [
            "You are an expert object-grounding annotator.",
            f"Dataset subject: {subject}.",
            f"Image dimensions: {img_w} x {img_h} pixels.",
            focus_line,
            "",
            'Return strictly as JSON object with no markdown: {"detections": [{"bbox_2d": [x1, y1, x2, y2], "label": "...", "confidence": 0.95}]}.',
            "",
            "Rules:",
            "- [x1, y1] = top-left corner, [x2, y2] = bottom-right corner.",
            "- Return one box per object instance.",
            "- Never use one large box to cover multiple nearby objects.",
            "- The box must tightly fit only the visible pixels of the object.",
            "- Do NOT pad the box with extra background.",
            "- Exclude shadow, reflection, and invisible or guessed object extent.",
            "- If the object is partly occluded, annotate only the visible portion.",
            "- If unsure, skip the detection instead of returning a loose box.",
        ]
        if prompt_text:
            parts.extend(
                [
                    "",
                    f'Weak generation hint only: "{_truncate_prompt_context(prompt_text)}".',
                    "Use the image as the source of truth. Do not enlarge boxes based on the hint.",
                ]
            )
        if target_category:
            parts.append(f"- Only return detections whose label matches '{target_category}'.")
        else:
            parts.append(f"- Only return detections from this closed set: {categories_str}.")
        parts.extend([
            "",
            'If nothing is found, return {"detections": []}.',
        ])
        return "\n".join(parts)

    # Gemini / generic format
    parts = [
        "You are a professional bounding-box annotator. Your ONLY task is to output precise, tight bounding boxes.",
        f"Dataset subject: '{subject}'.",
        f"Target categories: {categories_str}.",
        f"Image dimensions: {img_w} x {img_h} pixels.",
    ]
    if prompt_text:
        parts.append(f'Image was generated from prompt: "{prompt_text}".')
    parts.extend([
        "",
        "CRITICAL RULES FOR BOUNDING BOXES:",
        '- Format: pixel corners as {"detections": [{"bbox_2d": [x1, y1, x2, y2], "label": "...", "confidence": 0.95}]}.',
        "- [x1, y1] is the top-left corner and [x2, y2] is the bottom-right corner.",
        "- The box must tightly contour the object's actual visible boundary — no extra margin.",
        "- Do NOT add any padding or safety margin around the object.",
        "- Coordinates must use the actual pixel space of this image, not normalized values.",
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
        'Return strictly as JSON with no markdown: {"detections": [{"bbox_2d": [x1, y1, x2, y2], "label": "...", "confidence": 0.95}]}. '
        'If nothing is found, return {"detections": []}.',
    ])
    return "\n".join(parts)


def _truncate_prompt_context(prompt_text: str) -> str:
    compact = " ".join(prompt_text.split())
    if len(compact) <= MAX_PROMPT_CONTEXT_CHARS:
        return compact
    return compact[: MAX_PROMPT_CONTEXT_CHARS - 3].rstrip() + "..."


def _call_vl_model(
    provider: str,
    base_url: str,
    api_key: str,
    model: str,
    prompt: str,
    mime_type: str,
    b64_data: str,
) -> str:
    if provider == "gemini":
        return _call_gemini_vl(api_key, model, prompt, mime_type, b64_data)
    return _call_openai_compat_vl(base_url, api_key, model, prompt, mime_type, b64_data)


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
            "temperature": 0,
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
        "temperature": 0,
        "max_tokens": 512,
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

        # --- Qwen2.5-VL bbox_2d format: pixel/normalized [x1, y1, x2, y2] ---
        if "bbox_2d" in item:
            raw_label = str(item.get("label", "")).strip()
            category = _resolve_allowed_category(raw_label, allowed_categories)
            bbox_2d = item["bbox_2d"]
            if category is None and len(allowed_categories) == 1 and not raw_label:
                category = fallback_category
            if not category or not isinstance(bbox_2d, list) or len(bbox_2d) != 4:
                continue
            confidence = _parse_confidence(item.get("confidence"), default=1.0)
            if confidence < threshold:
                continue
            try:
                x1, y1, x2, y2 = (float(v) for v in bbox_2d)
            except (ValueError, TypeError):
                continue
            if x2 <= x1 or y2 <= y1:
                continue
            detections.append({
                "category": category,
                "confidence": round(confidence, 4),
                "bbox": _corners_to_bbox_auto(x1, y1, x2, y2, img_w, img_h),
            })
            continue

        # --- Original format: normalized [x_center, y_center, width, height] ---
        # Some VL models ignore the requested bbox_2d key and return pixel corners
        # under "bbox"; detect that before falling back to center-size semantics.
        raw_label = str(item.get("category", "") or item.get("label", "")).strip()
        category = _resolve_allowed_category(
            raw_label,
            allowed_categories,
        )
        if category is None and len(allowed_categories) == 1 and not raw_label:
            category = fallback_category
        confidence = _parse_confidence(item.get("confidence"), default=0.0)
        bbox = item.get("bbox", [])
        if not category:
            continue
        if confidence < threshold:
            continue
        if not isinstance(bbox, list) or len(bbox) != 4:
            continue
        try:
            bbox = [float(v) for v in bbox]
        except (ValueError, TypeError):
            continue

        if _bbox_field_looks_like_corners(bbox, img_w, img_h):
            detections.append({
                "category": category,
                "confidence": round(confidence, 4),
                "bbox": _corners_to_bbox_auto(bbox[0], bbox[1], bbox[2], bbox[3], img_w, img_h),
            })
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
            "bbox": _clip_bbox(x_center, y_center, width, height),
        })
    return _merge_detections(detections)


def _parse_confidence(value: Any, *, default: float) -> float:
    if value is None:
        return default
    if isinstance(value, str):
        value = value.strip().rstrip("%")
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return default
    if confidence > 1.0:
        confidence /= 100.0
    return min(max(confidence, 0.0), 1.0)


def _resolve_allowed_category(label: str, allowed_categories: set[str]) -> str | None:
    if not label:
        return None
    if label in allowed_categories:
        return label

    normalized_label = label.casefold().replace("-", " ").replace("_", " ")
    for category in allowed_categories:
        normalized_category = category.casefold().replace("-", " ").replace("_", " ")
        if normalized_label == normalized_category:
            return category
        if normalized_label.startswith(normalized_category) or normalized_category in normalized_label:
            return category
    return None


def _clip_bbox(x_center: float, y_center: float, width: float, height: float) -> list[float]:
    width = min(max(width, 0.001), 1.0)
    height = min(max(height, 0.001), 1.0)
    x_center = min(max(x_center, width / 2), 1.0 - width / 2)
    y_center = min(max(y_center, height / 2), 1.0 - height / 2)
    return [round(x_center, 4), round(y_center, 4), round(width, 4), round(height, 4)]


def _bbox_to_corners(bbox: list[float], img_w: int, img_h: int) -> tuple[int, int, int, int]:
    cx, cy, bw, bh = bbox
    x1 = int(round((cx - bw / 2) * img_w))
    y1 = int(round((cy - bh / 2) * img_h))
    x2 = int(round((cx + bw / 2) * img_w))
    y2 = int(round((cy + bh / 2) * img_h))
    x1 = max(0, min(x1, max(img_w - 1, 0)))
    y1 = max(0, min(y1, max(img_h - 1, 0)))
    x2 = max(x1 + 1, min(x2, max(img_w, 1)))
    y2 = max(y1 + 1, min(y2, max(img_h, 1)))
    return x1, y1, x2, y2


def _corners_to_bbox(x1: float, y1: float, x2: float, y2: float, img_w: int, img_h: int) -> list[float]:
    safe_w = max(img_w, 1)
    safe_h = max(img_h, 1)
    x1 = min(max(x1, 0.0), float(safe_w - 1))
    y1 = min(max(y1, 0.0), float(safe_h - 1))
    x2 = min(max(x2, x1 + 1.0), float(safe_w))
    y2 = min(max(y2, y1 + 1.0), float(safe_h))
    width = max((x2 - x1) / safe_w, 0.001)
    height = max((y2 - y1) / safe_h, 0.001)
    x_center = ((x1 + x2) / 2) / safe_w
    y_center = ((y1 + y2) / 2) / safe_h
    return _clip_bbox(x_center, y_center, width, height)


def _corners_to_bbox_auto(x1: float, y1: float, x2: float, y2: float, img_w: int, img_h: int) -> list[float]:
    values = [x1, y1, x2, y2]
    if _bbox_values_are_normalized(values):
        x1 = min(max(x1, 0.0), 1.0)
        y1 = min(max(y1, 0.0), 1.0)
        x2 = min(max(x2, x1 + 0.001), 1.0)
        y2 = min(max(y2, y1 + 0.001), 1.0)
        return _clip_bbox((x1 + x2) / 2, (y1 + y2) / 2, x2 - x1, y2 - y1)
    return _corners_to_bbox(x1, y1, x2, y2, img_w, img_h)


def _bbox_field_looks_like_corners(bbox: list[float], img_w: int, img_h: int) -> bool:
    x1, y1, x2, y2 = bbox
    if x2 <= x1 or y2 <= y1:
        return False
    if not _bbox_values_are_normalized(bbox):
        return x1 < img_w and y1 < img_h and x2 <= img_w * 1.05 and y2 <= img_h * 1.05

    _, _, width, height = bbox
    center_size_would_be_out_of_bounds = (
        x1 < width / 2
        or x1 > 1.0 - width / 2
        or y1 < height / 2
        or y1 > 1.0 - height / 2
    )
    return center_size_would_be_out_of_bounds


def _bbox_values_are_normalized(values: list[float]) -> bool:
    return all(0.0 <= value <= 1.0 for value in values)


def _bbox_area(bbox: list[float]) -> float:
    return max(bbox[2], 0.0) * max(bbox[3], 0.0)


def _bbox_iou(a: list[float], b: list[float]) -> float:
    ax1 = a[0] - a[2] / 2
    ay1 = a[1] - a[3] / 2
    ax2 = a[0] + a[2] / 2
    ay2 = a[1] + a[3] / 2
    bx1 = b[0] - b[2] / 2
    by1 = b[1] - b[3] / 2
    bx2 = b[0] + b[2] / 2
    by2 = b[1] + b[3] / 2

    inter_x1 = max(ax1, bx1)
    inter_y1 = max(ay1, by1)
    inter_x2 = min(ax2, bx2)
    inter_y2 = min(ay2, by2)
    inter_w = max(inter_x2 - inter_x1, 0.0)
    inter_h = max(inter_y2 - inter_y1, 0.0)
    inter_area = inter_w * inter_h
    if inter_area <= 0:
        return 0.0
    union = _bbox_area(a) + _bbox_area(b) - inter_area
    if union <= 0:
        return 0.0
    return inter_area / union


def _merge_detections(detections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    for detection in detections:
        if not detection.get("bbox"):
            continue
        replaced = False
        for index, existing in enumerate(merged):
            if detection["category"] != existing["category"]:
                continue
            if _bbox_iou(detection["bbox"], existing["bbox"]) < MERGE_IOU_THRESHOLD:
                continue
            merged[index] = _prefer_tighter_detection(existing, detection)
            replaced = True
            break
        if not replaced:
            merged.append(detection)
    return merged


def _prefer_tighter_detection(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    left_confidence = float(left.get("confidence", 0.0))
    right_confidence = float(right.get("confidence", 0.0))
    if abs(left_confidence - right_confidence) <= MERGE_CONFIDENCE_EPS:
        if _bbox_area(right["bbox"]) < _bbox_area(left["bbox"]):
            return right
        return left
    return right if right_confidence > left_confidence else left


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
        '{"detections": [{"bbox_2d": [x1, y1, x2, y2], "label": "...", "confidence": 0.95}]}',
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
    raw = _call_vl_model(provider, base_url, api_key, model, prompt, "image/png", annotated_b64)

    allowed = set(categories)
    refined = _parse_vl_response(raw, 0.0, allowed, img_w, img_h)
    return refined if refined else detections


def _tighten_large_detections(
    provider: str,
    model: str,
    api_key: str,
    base_url: str,
    pil_img: Image.Image,
    detections: list[dict[str, Any]],
    img_w: int,
    img_h: int,
) -> list[dict[str, Any]]:
    tightened: list[dict[str, Any]] = []
    for detection in detections:
        if not _is_suspicious_large_box(detection["bbox"]):
            tightened.append(detection)
            continue
        tightened.append(
            _tighten_single_detection(
                provider,
                model,
                api_key,
                base_url,
                pil_img,
                detection,
                img_w,
                img_h,
            )
        )
    return _merge_detections(tightened)


def _is_suspicious_large_box(bbox: list[float]) -> bool:
    return _bbox_area(bbox) >= LARGE_BOX_AREA_THRESHOLD or bbox[2] >= LARGE_BOX_DIM_THRESHOLD or bbox[3] >= LARGE_BOX_DIM_THRESHOLD


def _tighten_single_detection(
    provider: str,
    model: str,
    api_key: str,
    base_url: str,
    pil_img: Image.Image,
    detection: dict[str, Any],
    img_w: int,
    img_h: int,
) -> dict[str, Any]:
    x1, y1, x2, y2 = _bbox_to_corners(detection["bbox"], img_w, img_h)
    margin_x = max(int((x2 - x1) * TIGHTEN_MARGIN_RATIO), TIGHTEN_MIN_MARGIN_PX)
    margin_y = max(int((y2 - y1) * TIGHTEN_MARGIN_RATIO), TIGHTEN_MIN_MARGIN_PX)
    crop_x1 = max(0, x1 - margin_x)
    crop_y1 = max(0, y1 - margin_y)
    crop_x2 = min(img_w, x2 + margin_x)
    crop_y2 = min(img_h, y2 + margin_y)
    if crop_x2 <= crop_x1 or crop_y2 <= crop_y1:
        return detection

    crop = pil_img.crop((crop_x1, crop_y1, crop_x2, crop_y2))
    crop_w, crop_h = crop.size
    if crop_w <= 1 or crop_h <= 1:
        return detection

    buffer = io.BytesIO()
    crop.save(buffer, format="PNG")
    crop_b64 = base64.b64encode(buffer.getvalue()).decode("utf-8")
    prompt = _build_tighten_prompt(detection["category"], crop_w, crop_h)
    raw = _call_vl_model(provider, base_url, api_key, model, prompt, "image/png", crop_b64)
    local_candidates = _parse_vl_response(raw, 0.0, {detection["category"]}, crop_w, crop_h)
    if not local_candidates:
        return detection

    best_local = min(
        local_candidates,
        key=lambda item: (
            (item["bbox"][0] - 0.5) ** 2 + (item["bbox"][1] - 0.5) ** 2,
            _bbox_area(item["bbox"]),
        ),
    )
    local_x1, local_y1, local_x2, local_y2 = _bbox_to_corners(best_local["bbox"], crop_w, crop_h)
    candidate = {
        "category": detection["category"],
        "confidence": round(max(float(detection.get("confidence", 0.0)), float(best_local.get("confidence", 0.0))), 4),
        "bbox": _corners_to_bbox(
            crop_x1 + local_x1,
            crop_y1 + local_y1,
            crop_x1 + local_x2,
            crop_y1 + local_y2,
            img_w,
            img_h,
        ),
    }
    if not _accept_tightened_detection(detection, candidate):
        return detection
    return candidate


def _build_tighten_prompt(category: str, crop_w: int, crop_h: int) -> str:
    return "\n".join([
        f"You are refining one coarse detection for category '{category}'.",
        f"Crop dimensions: {crop_w} x {crop_h} pixels.",
        "The target object is near the center of this crop.",
        'Return strictly as JSON object with no markdown: {"detections": [{"bbox_2d": [x1, y1, x2, y2], "label": "...", "confidence": 0.95}]}.',
        "",
        "Rules:",
        "- Return at most one detection.",
        f"- Only return category '{category}'.",
        "- The new box must be as tight as possible around the visible object pixels.",
        "- Exclude background, shadow, reflection, and invisible extent.",
        "- If no clear instance is present, return {\"detections\": []}.",
    ])


def _accept_tightened_detection(original: dict[str, Any], candidate: dict[str, Any]) -> bool:
    original_area = _bbox_area(original["bbox"])
    candidate_area = _bbox_area(candidate["bbox"])
    center_shift = (
        (original["bbox"][0] - candidate["bbox"][0]) ** 2 + (original["bbox"][1] - candidate["bbox"][1]) ** 2
    ) ** 0.5
    if candidate_area > original_area * TIGHTEN_MAX_AREA_EXPANSION:
        return False
    if center_shift > TIGHTEN_MAX_CENTER_SHIFT:
        return False
    return True


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
