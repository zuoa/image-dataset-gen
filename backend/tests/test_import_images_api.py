from io import BytesIO
from pathlib import Path
import zipfile

from PIL import Image

from app import create_app
from app.config import TestConfig


def _zip_with_images() -> bytes:
    archive_bytes = BytesIO()
    with zipfile.ZipFile(archive_bytes, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for index, color in enumerate(((220, 80, 80), (80, 180, 120)), start=1):
            buffer = BytesIO()
            Image.new("RGB", (24, 24), color=color).save(buffer, format="PNG")
            archive.writestr(f"images/sample-{index}.png", buffer.getvalue())
        archive.writestr("images/readme.txt", b"skip me")
    return archive_bytes.getvalue()


def test_import_images_archive_adds_uploaded_images_to_task(tmp_path: Path):
    class ImportConfig(TestConfig):
        STORAGE_ROOT = str(tmp_path)

    app = create_app(ImportConfig)
    client = app.test_client()

    register = client.post(
        "/api/v1/auth/register",
        json={"email": "import@example.com", "password": "Import123!"},
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

    response = client.post(
        f"/api/v1/tasks/{task_id}/import-images",
        headers=headers,
        data={"archive": (BytesIO(_zip_with_images()), "local-images.zip")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["summary"]["importedCount"] == 2
    assert payload["summary"]["skippedCount"] == 1
    assert payload["task"]["imagesGenerated"] == 2
    assert payload["task"]["selectedCount"] == 2
    assert all(image["status"] == "uploaded" for image in payload["task"]["images"])
