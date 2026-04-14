from __future__ import annotations

import base64
import json
from typing import Any
from urllib import error, request


class JimengGenerationError(RuntimeError):
    pass


def generate_image(
    *,
    api_key: str,
    base_url: str,
    model: str,
    prompt: str,
    size: str,
    watermark: bool,
) -> dict[str, Any]:
    body = {
        "model": model,
        "prompt": prompt,
        "size": size,
        "response_format": "b64_json",
        "watermark": watermark,
    }
    http_request = request.Request(
        f"{base_url.rstrip('/')}/images/generations",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with request.urlopen(http_request, timeout=45) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise JimengGenerationError(f"jimeng_http_{exc.code}: {detail}") from exc
    except error.URLError as exc:
        raise JimengGenerationError(f"jimeng_network_error: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise JimengGenerationError("jimeng_invalid_json") from exc

    if payload.get("error"):
        raise JimengGenerationError(str(payload["error"]))

    data = payload.get("data") or []
    if not data:
        raise JimengGenerationError("jimeng_empty_data")

    first = data[0]
    b64_json = first.get("b64_json")
    if not b64_json:
        raise JimengGenerationError("jimeng_missing_b64_json")

    return {
        "image_bytes": base64.b64decode(b64_json),
        "mime_type": "image/jpeg",
        "prompt": prompt,
    }
