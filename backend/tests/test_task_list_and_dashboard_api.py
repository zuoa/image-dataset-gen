from pathlib import Path
from unittest.mock import patch

from app import create_app
from app.config import TestConfig
from app.extensions import db
from app.models import Task


def _register_and_create_task(client, email: str, headers_subject: str) -> tuple[dict[str, str], str]:
    register = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "Latency123!"},
    )
    token = register.get_json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    create = client.post(
        "/api/v1/tasks",
        headers=headers,
        json={
            "subject": headers_subject,
            "categories": ["forklift"],
            "image_count": 10,
            "distance": "mid",
            "angle": "front",
            "lighting": ["indoor"],
            "background": ["indoor"],
            "aspect_ratio": "1:1",
            "format": "jpg",
            "style": "realistic",
            "api_provider": "gemini",
            "api_key": "demo-api-key",
            "concurrency": 3,
            "batch_size": 10,
            "extra_desc": "",
        },
    )
    return headers, create.get_json()["task"]["id"]


def test_list_tasks_uses_persisted_state_without_syncing(tmp_path: Path):
    class TaskListConfig(TestConfig):
        STORAGE_ROOT = str(tmp_path)

    app = create_app(TaskListConfig)
    client = app.test_client()
    headers, task_id = _register_and_create_task(client, "task-list@example.com", "warehouse forklift detection")

    with app.app_context():
        task = db.session.get(Task, task_id)
        assert task is not None
        task.status = "running"
        task.progress_percent = 40
        task.images_generated = 4
        task.selected_count = 2
        task.spent_cost = 0.18
        db.session.commit()

    with patch("app.api.tasks.sync_task_progress", side_effect=AssertionError("list endpoint should not sync")):
        response = client.get("/api/v1/tasks", headers=headers)

    assert response.status_code == 200
    payload = response.get_json()
    task = payload["tasks"][0]
    assert task["status"] == "running"
    assert task["sampleCount"] == 4
    assert task["imagesGenerated"] == 4
    assert task["selectedCount"] == 2
    assert task["images"] == []
    assert task["exports"] == []
    assert payload["summary"]["totalImages"] == 4
    assert payload["summary"]["runningTasks"] == 1


def test_dashboard_aggregates_persisted_counters(tmp_path: Path):
    class DashboardConfig(TestConfig):
        STORAGE_ROOT = str(tmp_path)

    app = create_app(DashboardConfig)
    client = app.test_client()
    headers, task_id = _register_and_create_task(client, "dashboard@example.com", "yard vehicle detection")

    with app.app_context():
        task = db.session.get(Task, task_id)
        assert task is not None
        task.status = "completed"
        task.images_generated = 7
        task.selected_count = 5
        task.spent_cost = 1.23
        db.session.commit()

    response = client.get("/api/v1/system/dashboard", headers=headers)

    assert response.status_code == 200
    summary = response.get_json()["summary"]
    assert summary["totalTasks"] == 1
    assert summary["runningTasks"] == 0
    assert summary["completedTasks"] == 1
    assert summary["draftTasks"] == 0
    assert summary["totalImages"] == 7
    assert summary["costToDate"] == 1.23
