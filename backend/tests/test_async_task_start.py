from pathlib import Path
from unittest.mock import patch

from PIL import Image

from app import create_app
from app.config import TestConfig
from tests.helpers import wait_for_task


def _png_bytes() -> bytes:
    from io import BytesIO

    buffer = BytesIO()
    Image.new("RGB", (2, 2), color=(255, 255, 255)).save(buffer, format="PNG")
    return buffer.getvalue()


def test_start_task_returns_and_completes_generation(tmp_path: Path):
    class AsyncStartConfig(TestConfig):
        STORAGE_ROOT = str(tmp_path)

    app = create_app(AsyncStartConfig)
    client = app.test_client()

    register = client.post(
        "/api/v1/auth/register",
        json={"username": "async-start-user", "password": "Async123!"},
    )
    token = register.get_json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    create = client.post(
        "/api/v1/tasks",
        headers=headers,
        json={
            "subject": "warehouse forklift detection",
            "categories": ["forklift"],
            "image_count": 5,
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
    task_id = create.get_json()["task"]["id"]

    with patch(
        "app.services.task_service.generate_gemini_image",
        return_value={"image_bytes": _png_bytes(), "mime_type": "image/png", "prompt": "ok"},
    ):
        started = client.post(f"/api/v1/tasks/{task_id}/start", headers=headers, json={})
        payload = started.get_json()["task"]

        assert started.status_code == 200
        assert payload["status"] in ("running", "completed")

        completed = wait_for_task(client, task_id, headers)

    assert completed["imagesGenerated"] >= 1
