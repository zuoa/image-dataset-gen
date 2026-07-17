from pathlib import Path
from unittest.mock import patch

from app import create_app
from app.config import TestConfig
from app.extensions import db
from app.models import OutboxEvent
from app.services.outbox_service import dispatch_pending_events, enqueue_background_task
from app.worker_tasks import export_dataset_archive


def test_outbox_dispatches_committed_task_to_named_queue(tmp_path: Path):
    class OutboxConfig(TestConfig):
        STORAGE_ROOT = str(tmp_path)

    app = create_app(OutboxConfig)
    with app.app_context():
        event = enqueue_background_task(export_dataset_archive, "export-id")
        db.session.commit()

        with patch("app.services.outbox_service.celery.send_task") as send_task:
            assert dispatch_pending_events() == 1

        send_task.assert_called_once_with(
            export_dataset_archive.name,
            args=["export-id"],
            queue="media",
        )
        assert db.session.get(OutboxEvent, event.id).published_at is not None


def test_outbox_failure_is_retained_for_retry(tmp_path: Path):
    class OutboxConfig(TestConfig):
        STORAGE_ROOT = str(tmp_path)

    app = create_app(OutboxConfig)
    with app.app_context():
        event = enqueue_background_task(export_dataset_archive, "export-id")
        db.session.commit()

        with patch(
            "app.services.outbox_service.celery.send_task", side_effect=RuntimeError("redis down")
        ):
            assert dispatch_pending_events() == 0

        stored = db.session.get(OutboxEvent, event.id)
        assert stored.published_at is None
        assert stored.attempt_count == 1
        assert stored.last_error == "redis down"
