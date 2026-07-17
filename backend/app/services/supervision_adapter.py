from __future__ import annotations

from typing import Any, Iterable

import numpy as np


def supervision_version() -> str:
    """Return the installed Supervision version for diagnostics and reports."""
    import supervision as sv

    return str(getattr(sv, "__version__", "unknown"))


def detections_from_records(
    records: Iterable[dict[str, Any]],
    categories: list[str],
    image_size: tuple[int, int],
):
    """Convert platform center-size records to ``sv.Detections``.

    Platform boxes are normalized ``[x_center, y_center, width, height]`` while
    Supervision uses pixel ``xyxy`` coordinates. Keeping this conversion in one
    module prevents model, import, export, and quality code from drifting.
    """
    import supervision as sv

    image_width, image_height = image_size
    category_to_id = {name: index for index, name in enumerate(categories)}
    boxes: list[list[float]] = []
    confidences: list[float] = []
    class_ids: list[int] = []
    class_names: list[str] = []

    for record in records:
        bbox = record.get("bbox")
        if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
            continue
        try:
            x_center, y_center, width, height = [float(value) for value in bbox]
            confidence = min(max(float(record.get("confidence", 0.0)), 0.0), 1.0)
        except (TypeError, ValueError):
            continue
        if width <= 0 or height <= 0:
            continue
        category = str(record.get("category") or "").strip()
        if category not in category_to_id:
            continue
        boxes.append(
            [
                (x_center - width / 2) * image_width,
                (y_center - height / 2) * image_height,
                (x_center + width / 2) * image_width,
                (y_center + height / 2) * image_height,
            ]
        )
        confidences.append(confidence)
        class_ids.append(category_to_id[category])
        class_names.append(category)

    return sv.Detections(
        xyxy=np.asarray(boxes, dtype=float).reshape((-1, 4)),
        confidence=np.asarray(confidences, dtype=float),
        class_id=np.asarray(class_ids, dtype=int),
        data={"class_name": np.asarray(class_names, dtype=str)},
    )


def records_from_detections(
    detections,
    categories: list[str],
    image_size: tuple[int, int],
) -> list[dict[str, Any]]:
    """Convert ``sv.Detections`` into platform center-size records."""
    image_width, image_height = image_size
    if image_width <= 0 or image_height <= 0:
        raise ValueError("image dimensions must be positive")

    class_names = detections.data.get("class_name") if detections.data else None
    records: list[dict[str, Any]] = []
    for index, xyxy in enumerate(detections.xyxy):
        x1, y1, x2, y2 = [float(value) for value in xyxy]
        class_id = int(detections.class_id[index]) if detections.class_id is not None else -1
        if class_names is not None and index < len(class_names):
            category = str(class_names[index])
        elif 0 <= class_id < len(categories):
            category = categories[class_id]
        else:
            category = f"class_{class_id}" if class_id >= 0 else "object"
        confidence = (
            float(detections.confidence[index])
            if detections.confidence is not None
            else 1.0
        )
        records.append(
            {
                "category": category,
                "confidence": round(min(max(confidence, 0.0), 1.0), 6),
                "bbox": [
                    round(((x1 + x2) / 2) / image_width, 6),
                    round(((y1 + y2) / 2) / image_height, 6),
                    round(max(0.0, x2 - x1) / image_width, 6),
                    round(max(0.0, y2 - y1) / image_height, 6),
                ],
            }
        )
    return records


def pairwise_iou(detections) -> np.ndarray:
    """Return a pairwise IoU matrix for Supervision detections."""
    import supervision as sv

    if len(detections) == 0:
        return np.empty((0, 0), dtype=float)
    return np.asarray(sv.box_iou_batch(detections.xyxy, detections.xyxy), dtype=float)
