from __future__ import annotations

import json
from pathlib import Path
from typing import Any

CENTER_BBOX_SEMANTICS = "center_size"
LEGACY_LEFT_BOTTOM_BBOX_SEMANTICS = "left_bottom_size_legacy"


def annotation_dir(storage_root: str, task_id: str) -> Path:
    path = Path(storage_root) / "annotations" / task_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def annotation_path(storage_root: str, task_id: str, image_id: str) -> Path:
    return annotation_dir(storage_root, task_id) / f"{image_id}.json"


def save_annotation_result(
    storage_root: str,
    task_id: str,
    image_id: str,
    detections: list[dict[str, Any]],
    *,
    bbox_semantics: str = CENTER_BBOX_SEMANTICS,
) -> None:
    annotation_path(storage_root, task_id, image_id).write_text(
        json.dumps(
            {
                "bboxSemantics": bbox_semantics,
                "detections": detections,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def load_annotation_result(
    storage_root: str,
    task_id: str,
    image_id: str,
    *,
    default_bbox_semantics: str | None = None,
) -> dict[str, Any] | None:
    path = annotation_path(storage_root, task_id, image_id)
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return normalize_annotation_result(payload, default_bbox_semantics=default_bbox_semantics)


def infer_default_bbox_semantics(annotation_summary: dict[str, Any] | None) -> str:
    summary = annotation_summary or {}
    if summary.get("provider") != "vl-auto":
        return CENTER_BBOX_SEMANTICS

    # Historic Gemini VL auto-annotations were stored as [left, bottom, width, height].
    vl_provider = str(summary.get("vlProvider") or "gemini")
    if vl_provider == "gemini":
        return LEGACY_LEFT_BOTTOM_BBOX_SEMANTICS
    return CENTER_BBOX_SEMANTICS


def normalize_annotation_result(
    payload: dict[str, Any],
    *,
    default_bbox_semantics: str | None = None,
) -> dict[str, Any]:
    semantics = str(payload.get("bboxSemantics") or default_bbox_semantics or CENTER_BBOX_SEMANTICS)
    detections = payload.get("detections", [])
    if semantics == LEGACY_LEFT_BOTTOM_BBOX_SEMANTICS:
        detections = [_legacy_left_bottom_detection_to_center(detection) for detection in detections]
        semantics = CENTER_BBOX_SEMANTICS
    return {
        **payload,
        "bboxSemantics": semantics,
        "detections": detections,
    }


def _legacy_left_bottom_detection_to_center(detection: dict[str, Any]) -> dict[str, Any]:
    bbox = detection.get("bbox")
    if not isinstance(bbox, list) or len(bbox) != 4:
        return detection
    try:
        left, bottom, width, height = (float(value) for value in bbox)
    except (TypeError, ValueError):
        return detection
    return {
        **detection,
        "bbox": _clip_bbox(left + width / 2, bottom - height / 2, width, height),
    }


def _clip_bbox(x_center: float, y_center: float, width: float, height: float) -> list[float]:
    width = min(max(width, 0.001), 1.0)
    height = min(max(height, 0.001), 1.0)
    x_center = min(max(x_center, width / 2), 1.0 - width / 2)
    y_center = min(max(y_center, height / 2), 1.0 - height / 2)
    return [round(x_center, 4), round(y_center, 4), round(width, 4), round(height, 4)]
