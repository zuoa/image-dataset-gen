from __future__ import annotations

import base64
import json
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from urllib import error, request

from app.models import Task
from app.services.image_storage import existing_generated_image


def annotate_task_images(
    task: Task,
    confidence_threshold: float,
    annotator_url: str,
    storage_root: str,
    vl_config: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    payload = {
        "taskId": task.id,
        "subject": task.subject,
        "categories": task.categories,
        "confidenceThreshold": confidence_threshold,
        "images": [
            {
                "imageId": image.id,
                "ordinal": image.ordinal,
                "seed": image.seed,
                "categoryHint": task.categories[(image.ordinal - 1) % len(task.categories or ["default"])],
                "promptText": image.prompt_text,
            }
            for image in task.images
        ],
    }

    vl_config = vl_config or {}
    if vl_config.get("api_key"):
        return _vl_annotate(task, confidence_threshold, storage_root, vl_config)

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


def _vl_annotate(
    task: Task,
    confidence_threshold: float,
    storage_root: str,
    vl_config: dict[str, str],
) -> list[dict[str, Any]]:
    provider = vl_config.get("provider", "gemini")
    model = vl_config.get("model", "gemini-2.0-flash")
    api_key = vl_config.get("api_key", "")
    base_url = vl_config.get("base_url", "")

    if not api_key:
        return _local_annotate({
            "taskId": task.id,
            "subject": task.subject,
            "categories": task.categories,
            "confidenceThreshold": confidence_threshold,
            "images": [
                {
                    "imageId": image.id,
                    "ordinal": image.ordinal,
                    "seed": image.seed,
                    "categoryHint": task.categories[(image.ordinal - 1) % len(task.categories or ["default"])],
                    "promptText": image.prompt_text,
                }
                for image in task.images
            ],
        })

    categories = task.categories or ["default"]
    allowed = set(categories)

    def annotate_single(image: Any) -> dict[str, Any]:
        path = existing_generated_image(storage_root, task.id, f"ordinal-{image.ordinal:06d}")
        if not path:
            return {"imageId": image.id, "detections": [], "status": "empty"}

        image_bytes = path.read_bytes()
        mime_type = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
        b64 = base64.b64encode(image_bytes).decode("utf-8")
        prompt = _build_vl_prompt(task.subject, categories)

        try:
            if provider == "gemini":
                raw = _call_gemini_vl(api_key, model, prompt, mime_type, b64)
            else:
                raw = _call_openai_compat_vl(base_url, api_key, model, prompt, mime_type, b64)
            detections = _parse_vl_response(raw, confidence_threshold, allowed)
            return {"imageId": image.id, "detections": detections, "status": "annotated" if detections else "empty"}
        except Exception:
            return {"imageId": image.id, "detections": [], "status": "empty"}

    with ThreadPoolExecutor(max_workers=3) as executor:
        results = list(executor.map(annotate_single, task.images))

    return results


def _build_vl_prompt(subject: str, categories: list[str]) -> str:
    categories_str = ", ".join(categories)
    return (
        f"You are an expert computer vision assistant. The image is about '{subject}'. "
        f"Detect all objects that belong to these categories: {categories_str}. "
        "For each detection, return the category name, confidence score (0-1), and bounding box "
        "in normalized [x_center, y_center, width, height] coordinates (0-1). "
        'Return strictly as JSON: {"detections": [{"category": "...", "confidence": 0.95, "bbox": [0.5, 0.5, 0.2, 0.3]}]}. '
        'If nothing is found, return {"detections": []}.'
    )


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


def _parse_vl_response(raw: str, threshold: float, allowed_categories: set[str]) -> list[dict[str, Any]]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []

    detections: list[dict[str, Any]] = []
    for item in data.get("detections", []):
        category = str(item.get("category", "")).strip()
        confidence = float(item.get("confidence", 0))
        bbox = item.get("bbox", [])
        if category not in allowed_categories:
            continue
        if confidence < threshold:
            continue
        if not isinstance(bbox, list) or len(bbox) != 4:
            continue
        detections.append({
            "category": category,
            "confidence": round(confidence, 4),
            "bbox": [round(float(v), 4) for v in bbox],
        })
    return detections


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
            width = round(min(0.20 + (((seed // 100) % 13) / 100), 0.36), 4)
            height = round(min(0.22 + (((seed // 1000) % 13) / 100), 0.4), 4)
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
