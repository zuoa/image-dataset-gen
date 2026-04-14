from pathlib import Path
from unittest.mock import patch

from PIL import Image

from app import create_app
from app.config import TestConfig
from tests.helpers import wait_for_task


def _png_bytes() -> bytes:
    from io import BytesIO

    buffer = BytesIO()
    image = Image.new("RGB", (32, 32), color=(80, 140, 220))
    for x in range(10, 22):
        for y in range(8, 24):
            image.putpixel((x, y), (240, 180, 40))
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_augmentation_saves_selected_methods(tmp_path: Path):
    class AugmentationConfig(TestConfig):
        STORAGE_ROOT = str(tmp_path)

    app = create_app(AugmentationConfig)
    client = app.test_client()

    register = client.post(
        "/api/v1/auth/register",
        json={"username": "augment-user", "password": "Augment123!"},
    )
    token = register.get_json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    create = client.post(
        "/api/v1/tasks",
        headers=headers,
        json={
            "subject": "warehouse forklift detection",
            "categories": ["forklift"],
            "image_count": 12,
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

    augment = client.post(
        f"/api/v1/tasks/{task_id}/augment",
        headers=headers,
        json={
            "multiplier": 4,
            "augmentation_methods": ["flip", "rotate", "noise"],
            "augmentation_settings": {
                "flip": {"mode": "horizontal"},
                "rotate": {"max_angle": 6},
                "noise": {"max_sigma": 18},
            },
        },
    )

    assert augment.status_code == 200
    summary = augment.get_json()["summary"]
    assert summary["multiplier"] == 4
    assert summary["methods"] == ["flip", "rotate", "noise"]
    assert summary["settings"]["flip"]["mode"] == "horizontal"
    assert summary["settings"]["rotate"]["max_angle"] == 6
    assert summary["settings"]["noise"]["max_sigma"] == 18
    assert summary["sourceCount"] >= 0
    assert summary["estimatedAddedImages"] >= 0
    assert summary["status"] in {"running", "completed"}
    assert summary["totalImagesToCreate"] == summary["estimatedAddedImages"]


def test_augmentation_rejects_when_only_augmented_images_are_selected(tmp_path: Path):
    class AugmentationConfig(TestConfig):
        STORAGE_ROOT = str(tmp_path)

    app = create_app(AugmentationConfig)
    client = app.test_client()

    register = client.post(
        "/api/v1/auth/register",
        json={"username": "augment-original-only-user", "password": "Augment123!"},
    )
    token = register.get_json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    create = client.post(
        "/api/v1/tasks",
        headers=headers,
        json={
            "subject": "warehouse forklift detection",
            "categories": ["forklift"],
            "image_count": 12,
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
        first_task = wait_for_task(client, task_id, headers)
        client.post(
            f"/api/v1/tasks/{task_id}/augment",
            headers=headers,
            json={"multiplier": 2, "augmentation_methods": ["flip"]},
        )
        augmented_task = wait_for_task(client, task_id, headers)

    original_images = [image for image in first_task["images"] if image["status"] != "augmented"]
    augmented_images = [image for image in augmented_task["images"] if image["status"] == "augmented"]
    assert original_images
    assert augmented_images

    for image in original_images:
        client.patch(
            f"/api/v1/tasks/{task_id}/selection",
            headers=headers,
            json={"mode": "single", "image_id": image["id"], "selected": False},
        )

    retry_augment = client.post(
        f"/api/v1/tasks/{task_id}/augment",
        headers=headers,
        json={"multiplier": 2, "augmentation_methods": ["flip"]},
    )

    assert retry_augment.status_code == 400
    assert "原始图片" in retry_augment.get_json()["message"]
