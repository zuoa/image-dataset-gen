from __future__ import annotations

from datetime import datetime
from typing import Any

from flask import current_app

from app.models import TrainingJob, TrainingWorker
from app.services.dataset_service import now_utc


DEFAULT_TRAINING_MODELS = (
    {
        "id": "yolov8n.pt",
        "label": "YOLOv8 Nano",
        "framework": "yolov8",
        "task": "detect",
        "recommended": True,
    },
    {
        "id": "yolov8s.pt",
        "label": "YOLOv8 Small",
        "framework": "yolov8",
        "task": "detect",
        "recommended": False,
    },
    {
        "id": "yolov8m.pt",
        "label": "YOLOv8 Medium",
        "framework": "yolov8",
        "task": "detect",
        "recommended": False,
    },
    {
        "id": "yolov8l.pt",
        "label": "YOLOv8 Large",
        "framework": "yolov8",
        "task": "detect",
        "recommended": False,
    },
    {
        "id": "yolov8x.pt",
        "label": "YOLOv8 XLarge",
        "framework": "yolov8",
        "task": "detect",
        "recommended": False,
    },
    {
        "id": "yolo11n.pt",
        "label": "YOLO11 Nano",
        "framework": "yolo11",
        "task": "detect",
        "recommended": False,
    },
    {
        "id": "yolo11s.pt",
        "label": "YOLO11 Small",
        "framework": "yolo11",
        "task": "detect",
        "recommended": False,
    },
    {
        "id": "yolo11m.pt",
        "label": "YOLO11 Medium",
        "framework": "yolo11",
        "task": "detect",
        "recommended": False,
    },
    {
        "id": "yolo11l.pt",
        "label": "YOLO11 Large",
        "framework": "yolo11",
        "task": "detect",
        "recommended": False,
    },
    {
        "id": "yolo11x.pt",
        "label": "YOLO11 XLarge",
        "framework": "yolo11",
        "task": "detect",
        "recommended": False,
    },
)


def worker_is_online(worker: TrainingWorker, observed_at: datetime) -> bool:
    if worker.last_heartbeat_at is None:
        return False
    heartbeat_at = worker.last_heartbeat_at
    if heartbeat_at.tzinfo is None:
        heartbeat_at = heartbeat_at.replace(tzinfo=observed_at.tzinfo)
    heartbeat_age = (observed_at - heartbeat_at).total_seconds()
    return heartbeat_age <= int(current_app.config["TRAINING_WORKER_OFFLINE_SECONDS"])


def _string_capability_values(capabilities: dict[str, Any], key: str) -> set[str]:
    value = capabilities.get(key)
    if not isinstance(value, list):
        return set()
    return {
        item.strip()
        for item in value
        if isinstance(item, str) and item.strip()
    }


def training_framework_for_model(model_id: str) -> str:
    filename = model_id.strip().lower().replace("\\", "/").rsplit("/", 1)[-1]
    if filename.startswith("yolo11"):
        return "yolo11"
    if filename.startswith("yolov8"):
        return "yolov8"
    return "ultralytics"


def worker_model_capabilities(worker: TrainingWorker) -> list[dict[str, Any]]:
    capabilities = worker.capabilities_json or {}
    raw_models = capabilities.get("models")
    if not isinstance(raw_models, list):
        return []

    models: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw_model in raw_models:
        if isinstance(raw_model, str):
            model_id = raw_model.strip()
            model = {
                "id": model_id,
                "label": model_id,
                "framework": training_framework_for_model(model_id),
            }
        elif isinstance(raw_model, dict):
            model_id = str(raw_model.get("id") or "").strip()
            model = {
                "id": model_id,
                "label": str(raw_model.get("label") or model_id).strip(),
                "framework": str(
                    raw_model.get("framework")
                    or training_framework_for_model(model_id)
                ).strip(),
                "task": str(raw_model.get("task") or "detect").strip(),
                "recommended": bool(raw_model.get("recommended", False)),
                "cached": bool(raw_model.get("cached", False)),
            }
        else:
            continue
        if not model_id or model_id in seen:
            continue
        seen.add(model_id)
        model.setdefault("framework", training_framework_for_model(model_id))
        model.setdefault("task", "detect")
        model.setdefault("recommended", False)
        model.setdefault("cached", False)
        models.append(model)
    return models


def training_model_catalog(
    observed_at: datetime | None = None,
) -> tuple[list[dict[str, Any]], str, int]:
    observed_at = observed_at or now_utc()
    online_workers = [
        worker
        for worker in TrainingWorker.query.all()
        if worker_is_online(worker, observed_at)
    ]
    catalog: dict[str, dict[str, Any]] = {}
    for worker in online_workers:
        for model in worker_model_capabilities(worker):
            model_id = model["id"]
            entry = catalog.setdefault(
                model_id,
                {
                    **model,
                    "availableWorkerCount": 0,
                    "cachedWorkerCount": 0,
                },
            )
            entry["recommended"] = bool(entry["recommended"] or model["recommended"])
            entry["cached"] = bool(entry["cached"] or model["cached"])
            entry["availableWorkerCount"] += 1
            if model["cached"]:
                entry["cachedWorkerCount"] += 1

    if catalog:
        default_order = {
            model["id"]: index for index, model in enumerate(DEFAULT_TRAINING_MODELS)
        }
        models = sorted(
            catalog.values(),
            key=lambda model: (
                default_order.get(model["id"], len(default_order)),
                model["id"],
            ),
        )
        return models, "workers", len(online_workers)

    return (
        [
            {
                **model,
                "cached": False,
                "availableWorkerCount": 0,
                "cachedWorkerCount": 0,
            }
            for model in DEFAULT_TRAINING_MODELS
        ],
        "preset",
        len(online_workers),
    )


def online_worker_supports_custom_model(observed_at: datetime | None = None) -> bool:
    observed_at = observed_at or now_utc()
    return any(
        worker_is_online(worker, observed_at)
        and bool((worker.capabilities_json or {}).get("supportsCustomModel", False))
        for worker in TrainingWorker.query.all()
    )


def worker_supports_training_job(worker: TrainingWorker, job: TrainingJob) -> bool:
    capabilities = worker.capabilities_json or {}
    config = job.config_json or {}
    framework = str(config.get("framework") or "").strip()
    task = str(config.get("task") or "").strip()
    model = str(config.get("model") or "").strip()

    frameworks = _string_capability_values(capabilities, "frameworks")
    if frameworks and framework not in frameworks:
        return False
    tasks = _string_capability_values(capabilities, "tasks")
    if tasks and task not in tasks:
        return False
    if "models" not in capabilities:
        return True

    supported_models = {item["id"] for item in worker_model_capabilities(worker)}
    return model in supported_models or bool(
        capabilities.get("supportsCustomModel", False)
    )
