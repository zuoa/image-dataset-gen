from io import BytesIO
from pathlib import Path
import zipfile
from unittest.mock import patch
from types import SimpleNamespace

from PIL import Image

from app import create_app
from app.config import TestConfig
from app.extensions import db
from app.models import DatasetImage, DatasetTask
from app.services.annotation_storage import load_annotation_result
from app.services.image_storage import save_generated_image


def _png_bytes(color: tuple[int, int, int] = (255, 255, 255)) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (4, 4), color=color).save(buffer, format="PNG")
    return buffer.getvalue()


def _transparent_png_bytes() -> bytes:
    buffer = BytesIO()
    image = Image.new("RGBA", (4, 4), color=(255, 0, 0, 0))
    image.putpixel((1, 1), (0, 255, 0, 96))
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _avi_video_bytes(tmp_path: Path, frame_count: int = 6) -> bytes:
    import cv2
    import numpy as np

    video_path = tmp_path / "sample.avi"
    writer = cv2.VideoWriter(str(video_path), cv2.VideoWriter_fourcc(*"MJPG"), 5.0, (8, 8))
    assert writer.isOpened()
    for index in range(frame_count):
        frame = np.full((8, 8, 3), (index * 30, 120, 220 - index * 20), dtype=np.uint8)
        writer.write(frame)
    writer.release()
    return video_path.read_bytes()


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


def test_generation_start_falls_back_to_inline_execution_when_queue_is_unavailable(tmp_path: Path):
    class DatasetConfig(TestConfig):
        STORAGE_ROOT = str(tmp_path)

    app = create_app(DatasetConfig)
    client = app.test_client()
    headers = _auth_headers(client, "dataset-inline-fallback")
    dataset_id = _create_dataset(client, headers)
    task_id = _create_generation_task(client, dataset_id, headers)

    with (
        patch(
            "app.worker_tasks.generate_gemini_image",
            return_value={"image_bytes": _png_bytes(), "mime_type": "image/png", "prompt": "ok"},
        ),
        patch("app.worker_tasks.generate_dataset_task_images.delay", side_effect=RuntimeError("queue unavailable")),
    ):
        response = client.post(
            f"/api/v1/datasets/{dataset_id}/tasks/{task_id}/start",
            headers=headers,
            json={},
        )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["task"]["imagesGenerated"] == 5
    assert payload["dataset"]["imageCount"] == 5


def test_import_and_export_operate_at_dataset_level(tmp_path: Path):
    class DatasetConfig(TestConfig):
        STORAGE_ROOT = str(tmp_path)

    app = create_app(DatasetConfig)
    client = app.test_client()
    headers = _auth_headers(client, "dataset-import")
    dataset_id = _create_dataset(client, headers)

    archive_buffer = BytesIO()
    with zipfile.ZipFile(archive_buffer, "w") as archive:
        archive.writestr("sample-a.png", _transparent_png_bytes())
        archive.writestr("sample-b.png", _transparent_png_bytes())
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
    assert export_payload["export"]["summary"]["imageFormat"] == "png"

    download = client.get(
        f"/api/v1/datasets/{dataset_id}/exports/1/download",
        headers=headers,
    )
    assert download.status_code == 200
    assert download.mimetype == "application/zip"

    archive = zipfile.ZipFile(BytesIO(download.data))
    image_names = [name for name in archive.namelist() if name.endswith(".png")]
    assert image_names
    exported_image = Image.open(BytesIO(archive.read(image_names[0])))
    assert exported_image.mode == "RGBA"


def test_video_import_extracts_frames_into_dataset_pool_and_export_names(tmp_path: Path):
    class DatasetConfig(TestConfig):
        STORAGE_ROOT = str(tmp_path)

    app = create_app(DatasetConfig)
    client = app.test_client()
    headers = _auth_headers(client, "dataset-video-import")
    dataset_id = _create_dataset(client, headers)

    import_response = client.post(
        f"/api/v1/datasets/{dataset_id}/tasks/import/video",
        headers=headers,
        data={
            "video": (BytesIO(_avi_video_bytes(tmp_path, frame_count=6)), "sample.avi"),
            "frame_interval": "2",
            "output_format": "png",
            "jpeg_quality": "95",
            "filename_prefix": "video_frame",
        },
        content_type="multipart/form-data",
    )

    assert import_response.status_code == 201
    payload = import_response.get_json()
    assert payload["summary"]["importedCount"] == 3
    assert payload["task"]["taskType"] == "import"
    assert payload["task"]["status"] == "completed"
    assert payload["task"]["config"]["source"] == "video"
    assert payload["task"]["config"]["video"]["frameInterval"] == 2
    dataset = payload["dataset"]
    assert dataset["imageCount"] == 3
    assert dataset["selectedCount"] == 3
    assert {image["sourceType"] for image in dataset["images"]} == {"video"}
    assert dataset["images"][0]["diversityVars"]["outputFilename"] == "video_frame_000000.png"

    second_import_response = client.post(
        f"/api/v1/datasets/{dataset_id}/tasks/import/video",
        headers=headers,
        data={
            "video": (BytesIO(_avi_video_bytes(tmp_path, frame_count=6)), "sample-again.avi"),
            "frame_interval": "2",
            "output_format": "png",
            "jpeg_quality": "95",
            "filename_prefix": "video_frame",
        },
        content_type="multipart/form-data",
    )
    assert second_import_response.status_code == 201

    export_response = client.post(
        f"/api/v1/datasets/{dataset_id}/export",
        headers=headers,
        json={"export_format": "yolo", "image_format": "keep"},
    )
    assert export_response.status_code == 201

    download = client.get(
        f"/api/v1/datasets/{dataset_id}/exports/1/download",
        headers=headers,
    )
    assert download.status_code == 200
    archive = zipfile.ZipFile(BytesIO(download.data))
    image_names = [name for name in archive.namelist() if name.endswith(".png")]
    label_names = [name for name in archive.namelist() if name.endswith(".txt")]
    assert len(image_names) == 6
    assert len(label_names) == 6
    assert any(name.endswith("video_frame_000000_000001.png") for name in image_names)
    assert any(name.endswith("video_frame_000000_000004.png") for name in image_names)


def test_video_import_rejects_unsupported_file_type(tmp_path: Path):
    class DatasetConfig(TestConfig):
        STORAGE_ROOT = str(tmp_path)

    app = create_app(DatasetConfig)
    client = app.test_client()
    headers = _auth_headers(client, "dataset-video-invalid")
    dataset_id = _create_dataset(client, headers)

    response = client.post(
        f"/api/v1/datasets/{dataset_id}/tasks/import/video",
        headers=headers,
        data={"video": (BytesIO(b"not a video"), "sample.txt")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 400
    assert "只支持上传" in response.get_json()["message"]


def test_roboflow_import_downloads_images_and_yolo_annotations(tmp_path: Path):
    class DatasetConfig(TestConfig):
        STORAGE_ROOT = str(tmp_path)

    app = create_app(DatasetConfig)
    client = app.test_client()
    headers = _auth_headers(client, "dataset-roboflow-import")
    dataset_id = _create_dataset(client, headers)

    class FakeRoboflowVersion:
        def download(self, model_format: str, location: str, overwrite: bool = False):
            assert model_format == "yolov8"
            assert overwrite is True
            assert not Path(location).exists()
            root = Path(location) / "workspace-project-1"
            images_dir = root / "train" / "images"
            labels_dir = root / "train" / "labels"
            images_dir.mkdir(parents=True)
            labels_dir.mkdir(parents=True)
            (root / "data.yaml").write_text("names:\n- pedestrian\n- umbrella\n", encoding="utf-8")
            (images_dir / "sample-a.png").write_bytes(_png_bytes())
            (labels_dir / "sample-a.txt").write_text("1 0.500000 0.600000 0.250000 0.300000\n", encoding="utf-8")
            (images_dir / "sample-b.png").write_bytes(_png_bytes((20, 40, 60)))
            return SimpleNamespace(location=str(root))

    class FakeRoboflowProject:
        def version(self, version: str):
            assert version == "1"
            return FakeRoboflowVersion()

    class FakeRoboflowWorkspace:
        def project(self, project: str):
            assert project == "street-project"
            return FakeRoboflowProject()

    class FakeRoboflowClient:
        def workspace(self, workspace: str):
            assert workspace == "demo-workspace"
            return FakeRoboflowWorkspace()

    with patch("app.services.roboflow_import_service._make_roboflow_client", return_value=FakeRoboflowClient()):
        response = client.post(
            f"/api/v1/datasets/{dataset_id}/tasks/import/roboflow",
            headers=headers,
            json={
                "apiKey": "roboflow-test-key",
                "workspace": "demo-workspace",
                "project": "street-project",
                "version": "1",
                "format": "yolov8",
            },
        )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["summary"]["importedCount"] == 2
    assert payload["summary"]["annotatedCount"] == 1
    assert payload["summary"]["emptyAnnotationCount"] == 1
    assert payload["task"]["taskType"] == "import"
    assert payload["task"]["config"]["source"] == "roboflow"
    dataset = payload["dataset"]
    assert dataset["imageCount"] == 2
    assert dataset["annotation"]["provider"] == "roboflow"
    assert {image["sourceType"] for image in dataset["images"]} == {"roboflow"}

    annotated_image = next(image for image in dataset["images"] if image["annotationStatus"] == "annotated")
    assert annotated_image["detections"] == [
        {
            "category": "umbrella",
            "confidence": 1.0,
            "bbox": [0.5, 0.6, 0.25, 0.3],
        }
    ]

    stored = load_annotation_result(str(tmp_path), dataset_id, annotated_image["id"])
    assert stored is not None
    assert stored["detections"][0]["category"] == "umbrella"


def test_roboflow_import_decodes_labels_with_imported_category_order(tmp_path: Path):
    class DatasetConfig(TestConfig):
        STORAGE_ROOT = str(tmp_path)

    app = create_app(DatasetConfig)
    client = app.test_client()
    headers = _auth_headers(client, "dataset-roboflow-category-order")
    response = client.post(
        "/api/v1/datasets",
        headers=headers,
        json={
            "name": "mixed category dataset",
            "categories": ["vehicle"],
            "description": "existing categories should not shift imported Roboflow class ids",
        },
    )
    assert response.status_code == 201
    dataset_id = response.get_json()["dataset"]["id"]

    class FakeRoboflowVersion:
        def download(self, model_format: str, location: str, overwrite: bool = False):
            root = Path(location) / "workspace-project-1"
            images_dir = root / "train" / "images"
            labels_dir = root / "train" / "labels"
            images_dir.mkdir(parents=True)
            labels_dir.mkdir(parents=True)
            (root / "data.yaml").write_text("names:\n- pedestrian\n- umbrella\n", encoding="utf-8")
            (images_dir / "sample-a.png").write_bytes(_png_bytes())
            (labels_dir / "sample-a.txt").write_text("1 0.500000 0.600000 0.250000 0.300000\n", encoding="utf-8")
            return SimpleNamespace(location=str(root))

    class FakeRoboflowProject:
        def version(self, version: str):
            return FakeRoboflowVersion()

    class FakeRoboflowWorkspace:
        def project(self, project: str):
            return FakeRoboflowProject()

    class FakeRoboflowClient:
        def workspace(self, workspace: str):
            return FakeRoboflowWorkspace()

    with patch("app.services.roboflow_import_service._make_roboflow_client", return_value=FakeRoboflowClient()):
        import_response = client.post(
            f"/api/v1/datasets/{dataset_id}/tasks/import/roboflow",
            headers=headers,
            json={
                "apiKey": "roboflow-test-key",
                "workspace": "demo-workspace",
                "project": "street-project",
                "version": "1",
                "format": "yolov8",
            },
        )

    assert import_response.status_code == 200
    dataset = import_response.get_json()["dataset"]
    assert dataset["categories"] == ["vehicle", "pedestrian", "umbrella"]
    assert dataset["images"][0]["detections"][0]["category"] == "umbrella"

    export_response = client.post(
        f"/api/v1/datasets/{dataset_id}/export",
        headers=headers,
        json={"export_format": "yolo", "image_format": "keep"},
    )
    assert export_response.status_code == 201
    download = client.get(
        f"/api/v1/datasets/{dataset_id}/exports/1/download",
        headers=headers,
    )
    archive = zipfile.ZipFile(BytesIO(download.data))
    label_name = next(name for name in archive.namelist() if name.endswith(".txt"))
    assert archive.read(label_name).decode("utf-8").startswith("2 0.500000 0.600000 0.250000 0.300000")


def test_roboflow_import_extracts_downloaded_zip_archives(tmp_path: Path):
    class DatasetConfig(TestConfig):
        STORAGE_ROOT = str(tmp_path)

    app = create_app(DatasetConfig)
    client = app.test_client()
    headers = _auth_headers(client, "dataset-roboflow-zip")
    dataset_id = _create_dataset(client, headers)

    class FakeRoboflowVersion:
        def download(self, model_format: str, location: str, overwrite: bool = False):
            assert overwrite is True
            assert not Path(location).exists()
            archive_path = Path(location) / "roboflow-export.zip"
            archive_path.parent.mkdir(parents=True)
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("export/data.yaml", "names: ['pedestrian', 'umbrella']\n")
                archive.writestr("export/valid/images/sample-a.png", _png_bytes())
                archive.writestr("export/valid/labels/sample-a.txt", "0 0.500000 0.500000 0.400000 0.400000\n")
            return SimpleNamespace(location=str(archive_path))

    class FakeRoboflowProject:
        def version(self, version: str):
            assert version == "release-v2"
            return FakeRoboflowVersion()

    class FakeRoboflowWorkspace:
        def project(self, project: str):
            return FakeRoboflowProject()

    class FakeRoboflowClient:
        def workspace(self, workspace: str):
            return FakeRoboflowWorkspace()

    with patch("app.services.roboflow_import_service._make_roboflow_client", return_value=FakeRoboflowClient()):
        response = client.post(
            f"/api/v1/datasets/{dataset_id}/tasks/import/roboflow",
            headers=headers,
            json={
                "apiKey": "roboflow-test-key",
                "workspace": "demo-workspace",
                "project": "street-project",
                "version": "release-v2",
            },
        )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["summary"]["importedCount"] == 1
    assert payload["summary"]["annotatedCount"] == 1
    assert payload["dataset"]["images"][0]["detections"][0]["category"] == "pedestrian"


def test_roboflow_import_requires_api_key_payload(tmp_path: Path):
    class DatasetConfig(TestConfig):
        STORAGE_ROOT = str(tmp_path)

    app = create_app(DatasetConfig)
    client = app.test_client()
    headers = _auth_headers(client, "dataset-roboflow-missing-key")
    dataset_id = _create_dataset(client, headers)

    response = client.post(
        f"/api/v1/datasets/{dataset_id}/tasks/import/roboflow",
        headers=headers,
        json={"workspace": "demo", "project": "project", "version": "1"},
    )

    assert response.status_code == 422
    assert "apiKey" in response.get_json()["errors"]


def test_retry_failed_augmentation_task_resets_augmentation_status(tmp_path: Path):
    class DatasetConfig(TestConfig):
        STORAGE_ROOT = str(tmp_path)

    app = create_app(DatasetConfig)
    client = app.test_client()
    headers = _auth_headers(client, "dataset-augmentation-retry")
    dataset_id = _create_dataset(client, headers)

    with app.app_context():
        source_image = DatasetImage(
            dataset_id=dataset_id,
            source_type="generation",
            source_ordinal=1,
            ordinal=1,
            status="ready",
            seed=17,
            prompt_text="street scene",
            diversity_vars={"weather": "rain"},
            preview_svg="data:image/png;base64,",
            selected=True,
            annotation_status="pending",
        )
        db.session.add(source_image)
        db.session.flush()

        save_generated_image(
            app.config["STORAGE_ROOT"],
            dataset_id,
            "image-000001",
            _png_bytes((20, 40, 60)),
            "image/png",
        )

        task = DatasetTask(
            dataset_id=dataset_id,
            user_id=source_image.dataset.user_id,
            task_type="augmentation",
            task_name="增强批次 1",
            subject=source_image.dataset.name,
            image_count=1,
            categories=source_image.dataset.categories,
            config_json={
                "augmentation": {
                    "multiplier": 2,
                    "methods": ["flip"],
                    "settings": {},
                    "sourceCount": 1,
                    "sourceImageIds": [source_image.id],
                    "estimatedAddedImages": 1,
                    "totalImagesToCreate": 1,
                    "completedImages": 0,
                    "progressPercent": 0,
                    "status": "failed",
                    "error": "simulated_failure",
                    "updatedAt": "2025-01-01T00:00:00",
                }
            },
            prompt_json={},
            status="failed",
            progress_percent=0,
            api_provider="local",
        )
        db.session.add(task)
        db.session.commit()
        task_id = task.id

    response = client.post(
        f"/api/v1/datasets/{dataset_id}/tasks/{task_id}/retry",
        headers=headers,
        json={},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["task"]["status"] == "completed"
    assert payload["task"]["imagesGenerated"] == 1
    assert payload["task"]["config"]["augmentation"]["status"] == "completed"
    assert payload["dataset"]["imageCount"] == 2


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
