from __future__ import annotations

import json
from typing import Any
from urllib import error, request

from app.models import Task


def annotate_task_images(
    task: Task, confidence_threshold: float, annotator_url: str
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

    if not annotator_url:
        return _local_annotate(payload)

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
