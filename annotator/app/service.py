from __future__ import annotations

from typing import Any


def annotate_payload(payload: dict[str, Any]) -> dict[str, Any]:
    threshold = float(payload.get("confidenceThreshold", 0.6))
    results: list[dict[str, Any]] = []

    for image in payload.get("images", []):
        ordinal = int(image["ordinal"])
        seed = int(image["seed"])
        confidence = round(0.58 + ((seed % 35) / 100), 2)
        detections: list[dict[str, Any]] = []
        if ordinal % 7 != 0 and confidence >= threshold:
            detections.append(
                {
                    "category": image["categoryHint"],
                    "confidence": confidence,
                    "bbox": [
                        round(min(0.24 + ((seed % 37) / 100), 0.84), 4),
                        round(min(0.26 + (((seed // 10) % 33) / 100), 0.84), 4),
                        round(min(0.20 + (((seed // 100) % 13) / 100), 0.36), 4),
                        round(min(0.22 + (((seed // 1000) % 13) / 100), 0.4), 4),
                    ],
                }
            )
        results.append(
            {
                "imageId": image["imageId"],
                "detections": detections,
                "status": "annotated" if detections else "empty",
            }
        )

    return {"results": results}
