from pathlib import Path

from app import create_app
from app.config import TestConfig
from tests.helpers import wait_for_task


def test_unsupported_provider_pauses_task_without_fallback(tmp_path: Path):
    class StrictConfig(TestConfig):
        STORAGE_ROOT = str(tmp_path)

    app = create_app(StrictConfig)
    client = app.test_client()

    register = client.post(
        "/api/v1/auth/register",
        json={"email": "strict@example.com", "password": "Strict123!"},
    )
    token = register.get_json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    create = client.post(
        "/api/v1/tasks",
        headers=headers,
        json={
            "subject": "forklift detection",
            "categories": ["forklift"],
            "image_count": 10,
            "distance": "mid",
            "angle": "front",
            "lighting": ["indoor"],
            "background": ["indoor"],
            "aspect_ratio": "1:1",
            "format": "jpg",
            "style": "realistic",
            "api_provider": "custom",
            "api_key": "demo-api-key",
            "concurrency": 3,
            "batch_size": 10,
            "extra_desc": "",
        },
    )
    task_id = create.get_json()["task"]["id"]
    client.post(f"/api/v1/tasks/{task_id}/start", headers=headers, json={})
    task = wait_for_task(client, task_id, headers)

    assert task["status"] == "paused"
    assert task["imagesGenerated"] == 0
    assert task["config"]["runtime"]["generationError"] == "provider_not_supported:custom"


def test_retry_task_clears_generation_error(tmp_path: Path):
    class StrictConfig(TestConfig):
        STORAGE_ROOT = str(tmp_path)

    app = create_app(StrictConfig)
    client = app.test_client()

    register = client.post(
        "/api/v1/auth/register",
        json={"email": "retry@example.com", "password": "Strict123!"},
    )
    token = register.get_json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    create = client.post(
        "/api/v1/tasks",
        headers=headers,
        json={
            "subject": "forklift detection",
            "categories": ["forklift"],
            "image_count": 10,
            "distance": "mid",
            "angle": "front",
            "lighting": ["indoor"],
            "background": ["indoor"],
            "aspect_ratio": "1:1",
            "format": "jpg",
            "style": "realistic",
            "api_provider": "custom",
            "api_key": "demo-api-key",
            "concurrency": 3,
            "batch_size": 10,
            "extra_desc": "",
        },
    )
    task_id = create.get_json()["task"]["id"]
    client.post(f"/api/v1/tasks/{task_id}/start", headers=headers, json={})
    wait_for_task(client, task_id, headers)
    retried = client.post(f"/api/v1/tasks/{task_id}/retry", headers=headers, json={})
    task = wait_for_task(client, task_id, headers)

    assert retried.status_code == 200
    assert retried.get_json()["task"]["status"] == "running"
    assert task["status"] == "paused"
