from __future__ import annotations

import json
from typing import Any
from urllib import error, request


class OpenAICompatibleError(RuntimeError):
    pass


def chat_completion(
    *,
    base_url: str,
    api_key: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
) -> str:
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }
    base = base_url.rstrip("/")
    http_request = request.Request(
        f"{base}/chat/completions",
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
        raise OpenAICompatibleError(f"openai_compat_http_{exc.code}: {detail}") from exc
    except error.URLError as exc:
        raise OpenAICompatibleError(f"openai_compat_network_error: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise OpenAICompatibleError("openai_compat_invalid_json") from exc

    content = _extract_message_content(payload)
    if not content:
        raise OpenAICompatibleError("openai_compat_empty_message")
    return content


def _extract_message_content(payload: dict[str, Any]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    message = choices[0].get("message", {})
    content = message.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text_parts = []
        for part in content:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                text_parts.append(part["text"])
        return "\n".join(text_parts)
    return ""
