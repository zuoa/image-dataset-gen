from __future__ import annotations

import base64
import json
from typing import Any
from urllib import error, request


class GeminiGenerationError(RuntimeError):
    pass


SUPPORTED_ASPECT_RATIOS = ("1:1", "4:3", "3:4", "16:9", "9:16")

DEFAULT_PIXEL_SIZE_BY_RATIO = {
    "1:1": "1024x1024",
    "4:3": "1536x1152",
    "3:4": "1152x1536",
    "16:9": "1536x864",
    "9:16": "864x1536",
}


def _build_opener(proxy_url: str) -> request.OpenerDirector:
    if proxy_url:
        handler = request.ProxyHandler({"https": proxy_url, "http": proxy_url})
        return request.build_opener(handler)
    return request.build_opener()


def generate_image(
    *,
    api_key: str,
    model: str,
    prompt: str,
    aspect_ratio: str,
    person_generation: str,
    proxy_url: str = "",
) -> dict[str, Any]:
    if model.startswith("gemini-"):
        return _generate_gemini_native_image(
            api_key=api_key,
            model=model,
            prompt=prompt,
            aspect_ratio=aspect_ratio,
            proxy_url=proxy_url,
        )

    body = {
        "instances": [{"prompt": prompt}],
        "parameters": {
            "sampleCount": 1,
            "aspectRatio": aspect_ratio,
            "personGeneration": person_generation,
        },
    }
    http_request = request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:predict",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
        },
        method="POST",
    )

    try:
        with _build_opener(proxy_url).open(http_request, timeout=45) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise GeminiGenerationError(f"gemini_http_{exc.code}: {detail}") from exc
    except error.URLError as exc:
        raise GeminiGenerationError(f"gemini_network_error: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise GeminiGenerationError("gemini_invalid_json") from exc

    prediction = _extract_prediction(payload)
    if not prediction:
        raise GeminiGenerationError("gemini_empty_prediction")

    image_b64 = prediction.get("bytesBase64Encoded")
    mime_type = prediction.get("mimeType", "image/png")
    if not image_b64:
        raise GeminiGenerationError("gemini_filtered_or_missing_image")
    return {
        "image_bytes": base64.b64decode(image_b64),
        "mime_type": mime_type,
        "prompt": prediction.get("prompt", prompt),
    }


def _generate_gemini_native_image(
    *,
    api_key: str,
    model: str,
    prompt: str,
    aspect_ratio: str,
    proxy_url: str = "",
) -> dict[str, Any]:
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseModalities": ["IMAGE"],
            "imageConfig": {
                "aspectRatio": aspect_ratio,
            },
        },
    }
    http_request = request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
        },
        method="POST",
    )

    try:
        with _build_opener(proxy_url).open(http_request, timeout=45) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise GeminiGenerationError(f"gemini_http_{exc.code}: {detail}") from exc
    except error.URLError as exc:
        raise GeminiGenerationError(f"gemini_network_error: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise GeminiGenerationError("gemini_invalid_json") from exc

    inline_data = _extract_inline_data(payload)
    if not inline_data:
        raise GeminiGenerationError("gemini_filtered_or_missing_image")

    return {
        "image_bytes": base64.b64decode(inline_data["data"]),
        "mime_type": inline_data.get("mimeType", "image/png"),
        "prompt": prompt,
    }


def normalize_aspect_ratio(aspect_ratio: str) -> str:
    normalized = aspect_ratio.strip()
    if normalized not in SUPPORTED_ASPECT_RATIOS:
        raise ValueError(f"unsupported aspect ratio: {aspect_ratio}")
    return normalized


def pixel_size_for_aspect_ratio(aspect_ratio: str) -> str:
    return DEFAULT_PIXEL_SIZE_BY_RATIO[normalize_aspect_ratio(aspect_ratio)]


def _extract_prediction(payload: dict[str, Any]) -> dict[str, Any] | None:
    predictions = payload.get("predictions")
    if isinstance(predictions, list) and predictions:
        first = predictions[0]
        if isinstance(first, dict):
            return first

    generated_images = payload.get("generatedImages")
    if isinstance(generated_images, list) and generated_images:
        first = generated_images[0]
        if isinstance(first, dict):
            image_node = first.get("image", {})
            if isinstance(image_node, dict):
                image_bytes = image_node.get("imageBytes")
                if image_bytes:
                    return {
                        "bytesBase64Encoded": image_bytes,
                        "mimeType": image_node.get("mimeType", "image/png"),
                    }
    return None


def _extract_inline_data(payload: dict[str, Any]) -> dict[str, Any] | None:
    candidates = payload.get("candidates")
    if not isinstance(candidates, list):
        return None

    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        content = candidate.get("content")
        if not isinstance(content, dict):
            continue
        parts = content.get("parts")
        if not isinstance(parts, list):
            continue
        for part in parts:
            if not isinstance(part, dict):
                continue
            inline_data = part.get("inlineData")
            if isinstance(inline_data, dict) and inline_data.get("data"):
                return inline_data

    return None
