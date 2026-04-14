from pathlib import Path
from unittest.mock import patch

from PIL import Image

from app import create_app
from app.config import TestConfig
from app.services.annotation_storage import load_annotation_result
from tests.helpers import wait_for_task


def _png_bytes() -> bytes:
    from io import BytesIO

    buffer = BytesIO()
    Image.new("RGB", (2, 2), color=(255, 255, 255)).save(buffer, format="PNG")
    return buffer.getvalue()


def test_annotation_flow_persists_annotation_files(tmp_path: Path):
    class AnnotationConfig(TestConfig):
        STORAGE_ROOT = str(tmp_path)
        ANNOTATOR_URL = ""

    app = create_app(AnnotationConfig)
    client = app.test_client()

    register = client.post(
        "/api/v1/auth/register",
        json={"email": "annotate@example.com", "password": "Annotate123!"},
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

    annotate = client.post(
        f"/api/v1/tasks/{task_id}/annotate",
        headers=headers,
        json={"confidence_threshold": 0.6},
    )

    assert annotate.status_code == 200
    assert annotate.get_json()["summary"]["provider"] == "local-fallback"

    annotation = load_annotation_result(str(tmp_path), task_id, image_id)
    assert annotation is not None
    assert "detections" in annotation

    refreshed_task = client.get(f"/api/v1/tasks/{task_id}", headers=headers).get_json()["task"]
    refreshed_image = next(image for image in refreshed_task["images"] if image["id"] == image_id)
    assert "detections" in refreshed_image


def test_manual_annotation_update_persists_to_task_payload(tmp_path: Path):
    class AnnotationConfig(TestConfig):
        STORAGE_ROOT = str(tmp_path)

    app = create_app(AnnotationConfig)
    client = app.test_client()

    register = client.post(
        "/api/v1/auth/register",
        json={"email": "annotate-edit@example.com", "password": "Annotate123!"},
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

    update_response = client.patch(
        f"/api/v1/tasks/{task_id}/images/{image_id}/annotations",
        headers=headers,
        json={
            "detections": [
                {
                    "category": "forklift",
                    "confidence": 0.91,
                    "bbox": [0.5, 0.5, 0.2, 0.3],
                }
            ]
        },
    )

    assert update_response.status_code == 200
    updated_image = next(
        image for image in update_response.get_json()["task"]["images"] if image["id"] == image_id
    )
    assert updated_image["annotationStatus"] == "annotated"
    assert updated_image["detections"][0]["bbox"] == [0.5, 0.5, 0.2, 0.3]
