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


def test_selection_updates_selected_count_and_blocks_empty_export(tmp_path: Path):
    class SelectionConfig(TestConfig):
        STORAGE_ROOT = str(tmp_path)

    app = create_app(SelectionConfig)
    client = app.test_client()

    register = client.post(
        "/api/v1/auth/register",
        json={"username": "select-user", "password": "Select123!"},
    )
    token = register.get_json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    create = client.post(
        "/api/v1/tasks",
        headers=headers,
        json={
            "subject": "warehouse forklift detection",
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
    task_id = create.get_json()["task"]["id"]
    with patch(
        "app.services.task_service.generate_gemini_image",
        return_value={"image_bytes": _png_bytes(), "mime_type": "image/png", "prompt": "ok"},
    ):
        client.post(f"/api/v1/tasks/{task_id}/start", headers=headers, json={})
        task = wait_for_task(client, task_id, headers)

    assert task["selectedCount"] >= 1
    cleared = client.patch(f"/api/v1/tasks/{task_id}/selection", headers=headers, json={"mode": "none"})
    assert cleared.status_code == 200
    assert cleared.get_json()["task"]["selectedCount"] == 0

    export_attempt = client.post(
        f"/api/v1/tasks/{task_id}/export",
        headers=headers,
        json={"export_format": "yolo", "image_format": "png", "include_readme": True},
    )
    assert export_attempt.status_code == 400
