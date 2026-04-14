from __future__ import annotations

import json
from pathlib import Path
from typing import Any


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
) -> None:
    annotation_path(storage_root, task_id, image_id).write_text(
        json.dumps({"detections": detections}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_annotation_result(
    storage_root: str,
    task_id: str,
    image_id: str,
) -> dict[str, Any] | None:
    path = annotation_path(storage_root, task_id, image_id)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))
