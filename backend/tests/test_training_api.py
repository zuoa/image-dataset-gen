from io import BytesIO
from pathlib import Path
import zipfile

from PIL import Image

from app import create_app
from app.config import TestConfig
from app.extensions import db
from app.models import DatasetImage, TrainingArtifact, TrainingJob, TrainingWorker
from app.services.image_storage import save_generated_image


def _png_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (8, 8), color=(120, 140, 160)).save(buffer, format="PNG")
    return buffer.getvalue()


def _auth_headers(client, username: str = "training-user") -> dict[str, str]:
    register = client.post(
        "/api/v1/auth/register",
        json={"username": username, "password": "Dataset123!"},
    )
    token = register.get_json()["token"]
    return {"Authorization": f"Bearer {token}"}


def _worker_headers() -> dict[str, str]:
    return {"X-Training-Worker-Token": "worker-token"}


def _create_dataset_with_image(app, client, headers: dict[str, str]) -> str:
    response = client.post(
        "/api/v1/datasets",
        headers=headers,
        json={
            "name": "training dataset",
            "categories": ["widget"],
            "description": "dataset-level training workflow",
        },
    )
    assert response.status_code == 201
    dataset_id = response.get_json()["dataset"]["id"]

    with app.app_context():
        image = DatasetImage(
            dataset_id=dataset_id,
            source_type="import",
            source_ordinal=1,
            ordinal=1,
            status="uploaded",
            seed=12,
            prompt_text="uploaded widget",
            diversity_vars={},
            preview_svg="data:image/png;base64,",
            selected=True,
            annotation_status="pending",
        )
        db.session.add(image)
        save_generated_image(app.config["STORAGE_ROOT"], dataset_id, "image-000001", _png_bytes(), "image/png")
        db.session.commit()

    return dataset_id


def test_training_job_uses_default_training_parameters(tmp_path: Path):
    class TrainingConfig(TestConfig):
        STORAGE_ROOT = str(tmp_path)
        TRAINING_WORKER_TOKEN = "worker-token"

    app = create_app(TrainingConfig)
    client = app.test_client()
    headers = _auth_headers(client, "training-defaults")
    dataset_id = _create_dataset_with_image(app, client, headers)

    response = client.post(
        f"/api/v1/datasets/{dataset_id}/training-jobs",
        headers=headers,
        json={},
    )

    assert response.status_code == 201
    config = response.get_json()["job"]["config"]
    assert config["epochs"] == 200
    assert config["patience"] == 50
    assert config["dropout"] == 0.1
    assert config["mixup"] == 0.15
    assert config["weightDecay"] == 0.001
    assert config["classes"] == []


def test_training_job_accepts_regularization_and_class_filter(tmp_path: Path):
    class TrainingConfig(TestConfig):
        STORAGE_ROOT = str(tmp_path)
        TRAINING_WORKER_TOKEN = "worker-token"

    app = create_app(TrainingConfig)
    client = app.test_client()
    headers = _auth_headers(client, "training-class-filter")
    dataset_id = _create_dataset_with_image(app, client, headers)

    response = client.post(
        f"/api/v1/datasets/{dataset_id}/training-jobs",
        headers=headers,
        json={
            "dropout": 0.2,
            "mixup": 0.25,
            "weight_decay": 0.002,
            "classes": [0],
        },
    )

    assert response.status_code == 201
    config = response.get_json()["job"]["config"]
    assert config["dropout"] == 0.2
    assert config["mixup"] == 0.25
    assert config["weightDecay"] == 0.002
    assert config["classes"] == [0]


def test_training_job_rejects_unknown_class_index(tmp_path: Path):
    class TrainingConfig(TestConfig):
        STORAGE_ROOT = str(tmp_path)
        TRAINING_WORKER_TOKEN = "worker-token"

    app = create_app(TrainingConfig)
    client = app.test_client()
    headers = _auth_headers(client, "training-invalid-class")
    dataset_id = _create_dataset_with_image(app, client, headers)

    response = client.post(
        f"/api/v1/datasets/{dataset_id}/training-jobs",
        headers=headers,
        json={"classes": [1]},
    )

    assert response.status_code == 400


def test_training_job_queue_worker_poll_status_and_artifact_upload(tmp_path: Path):
    class TrainingConfig(TestConfig):
        STORAGE_ROOT = str(tmp_path)
        TRAINING_WORKER_TOKEN = "worker-token"

    app = create_app(TrainingConfig)
    client = app.test_client()
    headers = _auth_headers(client, "training-flow")
    dataset_id = _create_dataset_with_image(app, client, headers)

    job_response = client.post(
        f"/api/v1/datasets/{dataset_id}/training-jobs",
        headers=headers,
        json={"model": "yolov8n.pt", "epochs": 2, "image_size": 320, "batch_size": 1, "patience": 1},
    )
    assert job_response.status_code == 201
    job = job_response.get_json()["job"]
    assert job["status"] == "queued"
    assert job["config"]["framework"] == "yolov8"

    register = client.post(
        "/api/v1/training/workers/register",
        headers=_worker_headers(),
        json={"worker_id": "gpu-1", "name": "GPU 1", "capabilities": {"frameworks": ["yolov8"]}},
    )
    assert register.status_code == 200
    assert register.get_json()["worker"]["id"] == "gpu-1"

    poll = client.post("/api/v1/training/workers/gpu-1/poll", headers=_worker_headers(), json={})
    assert poll.status_code == 200
    assigned = poll.get_json()["job"]
    assert assigned["id"] == job["id"]
    assert assigned["datasetDownloadUrl"].endswith(f"/api/v1/training/jobs/{job['id']}/dataset.zip")

    dataset_download = client.get(f"/api/v1/training/jobs/{job['id']}/dataset.zip", headers=_worker_headers())
    assert dataset_download.status_code == 200
    archive = zipfile.ZipFile(BytesIO(dataset_download.data))
    data_yaml_name = next(name for name in archive.namelist() if name.endswith("data.yaml"))
    data_yaml = archive.read(data_yaml_name).decode("utf-8")
    assert "path:" not in data_yaml
    assert "val: images/train" in data_yaml

    status = client.patch(
        f"/api/v1/training/jobs/{job['id']}/status",
        headers=_worker_headers(),
        json={"status": "running", "progress_percent": 42, "metrics": {"mAP50": 0.12}},
    )
    assert status.status_code == 200
    assert status.get_json()["job"]["progressPercent"] == 42
    assert status.get_json()["job"]["metrics"]["mAP50"] == 0.12

    artifact = client.post(
        f"/api/v1/training/jobs/{job['id']}/artifacts",
        headers=_worker_headers(),
        data={"artifact_type": "best_model", "artifact": (BytesIO(b"model-weights"), "best.pt")},
        content_type="multipart/form-data",
    )
    assert artifact.status_code == 201
    artifact_id = artifact.get_json()["artifact"]["id"]

    completed = client.patch(
        f"/api/v1/training/jobs/{job['id']}/status",
        headers=_worker_headers(),
        json={"status": "completed", "metrics": {"mAP50": 0.5, "mAP50_95": 0.25}},
    )
    assert completed.status_code == 200
    assert completed.get_json()["job"]["status"] == "completed"
    assert completed.get_json()["job"]["progressPercent"] == 100

    download = client.get(
        f"/api/v1/datasets/{dataset_id}/training-jobs/{job['id']}/artifacts/{artifact_id}/download",
        headers=headers,
    )
    assert download.status_code == 200
    assert download.data == b"model-weights"

    with app.app_context():
        stored_job = db.session.get(TrainingJob, job["id"])
        stored_worker = db.session.get(TrainingWorker, "gpu-1")
        stored_artifact = db.session.get(TrainingArtifact, artifact_id)
        assert stored_job is not None and stored_job.status == "completed"
        assert stored_worker is not None and stored_worker.status == "idle"
        assert stored_artifact is not None and Path(stored_artifact.storage_path).exists()


def test_training_worker_requires_shared_token(tmp_path: Path):
    class TrainingConfig(TestConfig):
        STORAGE_ROOT = str(tmp_path)
        TRAINING_WORKER_TOKEN = "worker-token"

    app = create_app(TrainingConfig)
    client = app.test_client()

    response = client.post(
        "/api/v1/training/workers/register",
        json={"worker_id": "gpu-1", "name": "GPU 1", "capabilities": {}},
    )

    assert response.status_code == 401


def test_user_can_delete_stuck_training_job_and_create_another(tmp_path: Path):
    class TrainingConfig(TestConfig):
        STORAGE_ROOT = str(tmp_path)
        TRAINING_WORKER_TOKEN = "worker-token"

    app = create_app(TrainingConfig)
    client = app.test_client()
    headers = _auth_headers(client, "training-delete")
    dataset_id = _create_dataset_with_image(app, client, headers)

    job_response = client.post(
        f"/api/v1/datasets/{dataset_id}/training-jobs",
        headers=headers,
        json={"model": "yolov8n.pt", "epochs": 2, "image_size": 320, "batch_size": 1, "patience": 1},
    )
    job = job_response.get_json()["job"]

    client.post(
        "/api/v1/training/workers/register",
        headers=_worker_headers(),
        json={"worker_id": "gpu-1", "name": "GPU 1", "capabilities": {"frameworks": ["yolov8"]}},
    )
    client.post("/api/v1/training/workers/gpu-1/poll", headers=_worker_headers(), json={})
    artifact = client.post(
        f"/api/v1/training/jobs/{job['id']}/artifacts",
        headers=_worker_headers(),
        data={"artifact_type": "results_csv", "artifact": (BytesIO(b"epoch,metric\n"), "results.csv")},
        content_type="multipart/form-data",
    )
    assert artifact.status_code == 201

    with app.app_context():
        stored_job = db.session.get(TrainingJob, job["id"])
        assert stored_job is not None
        artifact_dir = Path(app.config["STORAGE_ROOT"]) / "training" / job["id"]
        assert artifact_dir.exists()

    delete_response = client.delete(
        f"/api/v1/datasets/{dataset_id}/training-jobs/{job['id']}",
        headers=headers,
    )

    assert delete_response.status_code == 200
    assert delete_response.get_json()["deletedJobId"] == job["id"]
    with app.app_context():
        assert db.session.get(TrainingJob, job["id"]) is None
        worker = db.session.get(TrainingWorker, "gpu-1")
        assert worker is not None and worker.status == "idle" and worker.current_job_id is None
        assert not artifact_dir.exists()

    replacement_response = client.post(
        f"/api/v1/datasets/{dataset_id}/training-jobs",
        headers=headers,
        json={"model": "yolov8s.pt", "epochs": 1, "image_size": 320, "batch_size": 1, "patience": 1},
    )
    assert replacement_response.status_code == 201
    assert replacement_response.get_json()["job"]["status"] == "queued"
