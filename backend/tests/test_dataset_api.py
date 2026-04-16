from io import BytesIO
from pathlib import Path
import zipfile
from unittest.mock import patch

from PIL import Image

from app import create_app
from app.config import TestConfig


def _png_bytes(color: tuple[int, int, int] = (255, 255, 255)) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (4, 4), color=color).save(buffer, format="PNG")
    return buffer.getvalue()


def _auth_headers(client, username: str = "dataset-user") -> dict[str, str]:
    register = client.post(
        "/api/v1/auth/register",
        json={"username": username, "password": "Dataset123!"},
    )
    token = register.get_json()["token"]
    return {"Authorization": f"Bearer {token}"}


def _create_dataset(client, headers: dict[str, str]) -> str:
    response = client.post(
        "/api/v1/datasets",
        headers=headers,
        json={
            "name": "street pedestrian dataset",
            "categories": ["pedestrian", "umbrella"],
            "description": "dataset-level workflow",
        },
    )
    assert response.status_code == 201
    return response.get_json()["dataset"]["id"]


def _create_generation_task(client, dataset_id: str, headers: dict[str, str]) -> str:
    response = client.post(
        f"/api/v1/datasets/{dataset_id}/tasks/generation",
        headers=headers,
        json={
            "subject": "rainy crosswalk pedestrians",
            "categories": ["pedestrian", "umbrella"],
            "image_count": 5,
            "distance": "mid",
            "angle": "front",
            "lighting": ["night"],
            "background": ["city"],
            "aspect_ratio": "1:1",
            "format": "jpg",
            "style": "realistic",
            "api_provider": "gemini",
            "api_key": "demo-api-key",
            "concurrency": 2,
            "batch_size": 4,
            "extra_desc": "",
        },
    )
    assert response.status_code == 201
    return response.get_json()["task"]["id"]


def test_generation_task_writes_images_into_dataset_pool(tmp_path: Path):
    class DatasetConfig(TestConfig):
        STORAGE_ROOT = str(tmp_path)

    app = create_app(DatasetConfig)
    client = app.test_client()
    headers = _auth_headers(client, "dataset-generation")
    dataset_id = _create_dataset(client, headers)
    task_id = _create_generation_task(client, dataset_id, headers)

    with patch(
        "app.worker_tasks.generate_gemini_image",
        return_value={"image_bytes": _png_bytes(), "mime_type": "image/png", "prompt": "ok"},
    ):
        response = client.post(f"/api/v1/datasets/{dataset_id}/tasks/{task_id}/start", headers=headers, json={})

    assert response.status_code == 200
    payload = response.get_json()
    dataset = payload["dataset"]
    task = payload["task"]
    assert dataset["imageCount"] == 5
    assert task["imagesGenerated"] == 5
    assert len(dataset["images"]) == 5
    assert all(image["datasetId"] == dataset_id for image in dataset["images"])
    assert all(image["sourceTaskId"] == task_id for image in dataset["images"])
    assert all(image["sourceType"] == "generation" for image in dataset["images"])


def test_import_and_export_operate_at_dataset_level(tmp_path: Path):
    class DatasetConfig(TestConfig):
        STORAGE_ROOT = str(tmp_path)

    app = create_app(DatasetConfig)
    client = app.test_client()
    headers = _auth_headers(client, "dataset-import")
    dataset_id = _create_dataset(client, headers)

    archive_buffer = BytesIO()
    with zipfile.ZipFile(archive_buffer, "w") as archive:
        archive.writestr("sample-a.png", _png_bytes((255, 0, 0)))
        archive.writestr("sample-b.png", _png_bytes((0, 255, 0)))
    archive_buffer.seek(0)

    import_response = client.post(
        f"/api/v1/datasets/{dataset_id}/tasks/import",
        headers=headers,
        data={"archive": (archive_buffer, "dataset.zip")},
        content_type="multipart/form-data",
    )
    assert import_response.status_code == 200
    import_payload = import_response.get_json()
    dataset = import_payload["dataset"]
    assert dataset["imageCount"] == 2
    assert dataset["selectedCount"] == 2
    assert dataset["taskCount"] == 1
    assert all(image["sourceType"] == "import" for image in dataset["images"])

    export_response = client.post(
        f"/api/v1/datasets/{dataset_id}/export",
        headers=headers,
        json={"export_format": "yolo", "image_format": "keep"},
    )
    assert export_response.status_code == 201
    export_payload = export_response.get_json()
    assert export_payload["export"]["status"] == "ready"

    download = client.get(
        f"/api/v1/datasets/{dataset_id}/exports/1/download",
        headers=headers,
    )
    assert download.status_code == 200
    assert download.mimetype == "application/zip"


def test_assist_subject_returns_categories_and_description(tmp_path: Path):
    class DatasetConfig(TestConfig):
        STORAGE_ROOT = str(tmp_path)

    app = create_app(DatasetConfig)
    client = app.test_client()
    headers = _auth_headers(client, "dataset-assist")

    profiles_response = client.get("/api/v1/system/model-profiles", headers=headers)
    assert profiles_response.status_code == 200
    llm_profile = next(
        profile
        for profile in profiles_response.get_json()["profiles"]
        if profile["profileType"] == "llm"
    )

    with patch(
        "app.api.datasets.suggest_subject_fields",
        return_value={
            "categories": ["pedestrian", "umbrella"],
            "extra_desc": "夜间雨天路口，突出行人遮挡、雨伞形态和车灯眩光影响。",
        },
    ):
        response = client.post(
            "/api/v1/datasets/assist-subject",
            headers=headers,
            json={
                "subject": "雨天城市道路行人检测",
                "llmProfileId": llm_profile["id"],
            },
        )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["categories"] == ["pedestrian", "umbrella"]
    assert payload["extra_desc"] == "夜间雨天路口，突出行人遮挡、雨伞形态和车灯眩光影响。"
