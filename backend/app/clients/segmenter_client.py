from __future__ import annotations

from pathlib import Path
from typing import Any

import requests


class SegmenterClientError(RuntimeError):
    status_code = 502


class SegmenterUnavailableError(SegmenterClientError):
    status_code = 503


class SegmenterTimeoutError(SegmenterClientError):
    status_code = 504


class SegmenterSessionExpiredError(SegmenterClientError):
    status_code = 410


def create_segmenter_session(
    *,
    base_url: str,
    shared_token: str,
    image_path: Path,
    connect_timeout: float,
    read_timeout: float,
) -> dict[str, Any]:
    mime_type = "image/png" if image_path.suffix.lower() == ".png" else "image/jpeg"
    with image_path.open("rb") as image_file:
        response = _request(
            "POST",
            f"{base_url.rstrip('/')}/v1/sessions",
            shared_token=shared_token,
            timeout=(connect_timeout, read_timeout),
            files={"image": (image_path.name, image_file, mime_type)},
        )
    return _json_object(response)


def predict_segmenter_session(
    *,
    base_url: str,
    shared_token: str,
    session_id: str,
    points: list[dict[str, Any]],
    connect_timeout: float,
    read_timeout: float,
) -> dict[str, Any]:
    response = _request(
        "POST",
        f"{base_url.rstrip('/')}/v1/sessions/{session_id}/predict",
        shared_token=shared_token,
        timeout=(connect_timeout, read_timeout),
        json={"points": points},
    )
    return _json_object(response)


def delete_segmenter_session(
    *,
    base_url: str,
    shared_token: str,
    session_id: str,
    connect_timeout: float,
    read_timeout: float,
) -> None:
    _request(
        "DELETE",
        f"{base_url.rstrip('/')}/v1/sessions/{session_id}",
        shared_token=shared_token,
        timeout=(connect_timeout, read_timeout),
    )


def _request(method: str, url: str, *, shared_token: str, timeout: tuple[float, float], **kwargs: Any):
    try:
        response = requests.request(
            method,
            url,
            headers={"Authorization": f"Bearer {shared_token}"},
            timeout=timeout,
            **kwargs,
        )
    except requests.Timeout as exc:
        raise SegmenterTimeoutError("segment assist timed out") from exc
    except requests.RequestException as exc:
        raise SegmenterUnavailableError("segment assist service is unavailable") from exc

    if response.status_code == 404:
        raise SegmenterSessionExpiredError("segment assist session expired")
    if not response.ok:
        message = _response_message(response) or f"segment assist failed with status {response.status_code}"
        error = SegmenterUnavailableError if response.status_code >= 500 else SegmenterClientError
        raise error(message)
    return response


def _json_object(response: requests.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise SegmenterClientError("segment assist returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise SegmenterClientError("segment assist returned an invalid payload")
    return payload


def _response_message(response: requests.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return ""
    return str(payload.get("message") or "") if isinstance(payload, dict) else ""
