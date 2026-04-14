from pathlib import Path
from unittest.mock import patch
import zipfile

from PIL import Image

from app import create_app
from app.config import TestConfig
from tests.helpers import wait_for_task


def _png_bytes() -> bytes:
    from io import BytesIO

    buffer = BytesIO()
    Image.new("RGB", (2, 2), color=(255, 255, 255)).save(buffer, format="PNG")
    return buffer.getvalue()


def test_export_creates_zip_archive(tmp_path: Path):
    class ExportTestConfig(TestConfig):
        STORAGE_ROOT = str(tmp_path)

    app = create_app(ExportTestConfig)
    client = app.test_client()

    register = client.post(
        "/api/v1/auth/register",
        json={"username": "export-user", "password": "Export123!"},
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
        wait_for_task(client, task_id, headers)

    exported = client.post(
        f"/api/v1/tasks/{task_id}/export",
        headers=headers,
        json={"export_format": "yolo", "image_format": "png", "include_readme": True},
    )
    assert exported.status_code == 201
    download = client.get(f"/api/v1/tasks/{task_id}/exports/1/download", headers=headers)
    assert download.status_code == 200

    archive_path = tmp_path / "exports"
    files = list(archive_path.glob("*.zip"))
    assert files

    with zipfile.ZipFile(files[0]) as archive:
        members = archive.namelist()
        assert any(member.endswith("data.yaml") for member in members)
        assert any(member.endswith(".txt") for member in members)
        assert any(member.endswith(".png") for member in members)


def test_export_uses_manually_updated_annotations(tmp_path: Path):
    class ExportTestConfig(TestConfig):
        STORAGE_ROOT = str(tmp_path)

    app = create_app(ExportTestConfig)
    client = app.test_client()

    register = client.post(
        "/api/v1/auth/register",
        json={"username": "export-manual-user", "password": "Export123!"},
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

    image_id = task["images"][0]["id"]
    client.patch(
        f"/api/v1/tasks/{task_id}/images/{image_id}/annotations",
        headers=headers,
        json={
            "detections": [
                {
                    "category": "forklift",
                    "confidence": 0.93,
                    "bbox": [0.5, 0.5, 0.2, 0.3],
                }
            ]
        },
    )

    exported = client.post(
        f"/api/v1/tasks/{task_id}/export",
        headers=headers,
        json={"export_format": "yolo", "image_format": "png", "include_readme": True},
    )
    assert exported.status_code == 201

    files = list((tmp_path / "exports").glob("*.zip"))
    assert files

    with zipfile.ZipFile(files[0]) as archive:
        label_name = next(member for member in archive.namelist() if member.endswith(".txt"))
        label_content = archive.read(label_name).decode("utf-8").strip()
        assert label_content == "0 0.500000 0.500000 0.200000 0.300000"
