from __future__ import annotations

from datetime import timedelta
import time
import uuid
from typing import Any

from flask import current_app

from app.extensions import celery, db
from app.models import OutboxEvent
from app.services.dataset_service import now_utc


TASK_QUEUES = {
    "app.worker_tasks.generate_dataset_task_images": "generation",
    "app.worker_tasks.annotate_dataset_images_task": "generation",
    "app.worker_tasks.augment_dataset_task_images": "media",
    "app.worker_tasks.extract_dataset_video_frames": "media",
    "app.worker_tasks.extract_dataset_archive_images": "media",
    "app.worker_tasks.export_dataset_archive": "media",
    "app.worker_tasks.import_roboflow_dataset_task": "media",
    "app.worker_tasks.analyze_dataset_quality": "media",
}


def enqueue_background_task(
    task_callable: Any,
    *args: object,
    deduplication_key: str = "",
    queue: str = "",
) -> OutboxEvent:
    task_name = str(getattr(task_callable, "name", ""))
    if not task_name:
        raise ValueError("background task must have a registered Celery name")
    event = OutboxEvent(
        event_type="celery.task",
        aggregate_type="background_task",
        aggregate_id=str(args[0]) if args else task_name,
        deduplication_key=deduplication_key or f"{task_name}:{uuid.uuid4()}",
        payload_json={
            "taskName": task_name,
            "args": list(args),
            "queue": queue or TASK_QUEUES.get(task_name, "generation"),
        },
        available_at=now_utc(),
    )
    db.session.add(event)
    return event


def dispatch_pending_events(*, batch_size: int | None = None) -> int:
    limit = batch_size or int(current_app.config.get("OUTBOX_BATCH_SIZE", 100))
    events = (
        OutboxEvent.query.filter(OutboxEvent.published_at.is_(None))
        .filter(OutboxEvent.available_at <= now_utc())
        .order_by(OutboxEvent.created_at.asc())
        .with_for_update(skip_locked=True)
        .limit(limit)
        .all()
    )
    published = 0
    for event in events:
        payload = event.payload_json or {}
        try:
            options = {}
            if payload.get("queue"):
                options["queue"] = str(payload["queue"])
            celery.send_task(str(payload["taskName"]), args=list(payload.get("args") or []), **options)
        except Exception as exc:
            event.attempt_count = int(event.attempt_count or 0) + 1
            event.last_error = str(exc)[:2000]
            delay_seconds = min(300, 2 ** min(event.attempt_count, 8))
            event.available_at = now_utc() + timedelta(seconds=delay_seconds)
        else:
            event.published_at = now_utc()
            event.last_error = ""
            published += 1
    db.session.commit()
    return published


def run_dispatcher_forever() -> None:
    interval = max(0.1, float(current_app.config.get("OUTBOX_POLL_INTERVAL_SECONDS", 1)))
    while True:
        try:
            dispatched = dispatch_pending_events()
        except Exception:
            db.session.rollback()
            current_app.logger.exception("outbox dispatch failed")
            dispatched = 0
        finally:
            db.session.remove()
        if dispatched == 0:
            time.sleep(interval)
