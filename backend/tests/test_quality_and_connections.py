from __future__ import annotations

from io import BytesIO
import zipfile

from app import create_app
from app.config import TestConfig
from app.extensions import db
from app.models import ExternalConnection
from app.services.annotation_storage import load_annotation_result
from app.services.supervision_adapter import detections_from_records, records_from_detections
from tests.test_dataset_api import _auth_headers, _create_dataset, _png_bytes


def _image_archive() -> BytesIO:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("images/sample.png", _png_bytes())
    buffer.seek(0)
    return buffer


def _yolo_archive() -> BytesIO:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "data.yaml",
            "train: train/images\nval: train/images\nnames: [pedestrian, umbrella]\n",
        )
        archive.writestr("train/images/sample.png", _png_bytes())
        archive.writestr(
            "train/labels/sample.txt",
            "0 0.250000 0.500000 0.200000 0.400000\n"
            "1 0.750000 0.500000 0.300000 0.200000\n",
        )
    buffer.seek(0)
    return buffer


def test_supervision_adapter_round_trips_platform_boxes():
    records = [
        {
            "category": "person",
            "confidence": 0.83,
            "bbox": [0.5, 0.4, 0.2, 0.3],
        }
    ]
    detections = detections_from_records(records, ["person"], (1000, 500))
    assert detections.xyxy.tolist() == [[400.0, 125.0, 600.0, 275.0]]
    assert records_from_detections(detections, ["person"], (1000, 500)) == records


def test_quality_run_finds_unannotated_imported_images(tmp_path):
    class QualityConfig(TestConfig):
        STORAGE_ROOT = str(tmp_path)

    app = create_app(QualityConfig)
    client = app.test_client()
    headers = _auth_headers(client, "quality-user")
    dataset_id = _create_dataset(client, headers)
    imported = client.post(
        f"/api/v1/datasets/{dataset_id}/tasks/import",
        headers=headers,
        data={"archive": (_image_archive(), "images.zip")},
        content_type="multipart/form-data",
    )
    assert imported.status_code == 200

    response = client.post(
        f"/api/v1/datasets/{dataset_id}/quality-runs",
        headers=headers,
        json={},
    )
    assert response.status_code == 202
    quality_run = response.get_json()["qualityRun"]
    assert quality_run["status"] == "completed"
    assert quality_run["summary"]["issuesByType"] == {"missing_annotation": 1}
    assert quality_run["supervisionVersion"] == "0.28.0"

    issues = client.get(
        f"/api/v1/datasets/{dataset_id}/quality-runs/{quality_run['id']}/issues?status=open",
        headers=headers,
    )
    assert issues.status_code == 200
    assert issues.get_json()["issues"][0]["image"]["ordinal"] == 1


def test_yolo_archive_round_trips_multiple_detections(tmp_path):
    class ArchiveConfig(TestConfig):
        STORAGE_ROOT = str(tmp_path)

    app = create_app(ArchiveConfig)
    client = app.test_client()
    headers = _auth_headers(client, "supervision-archive-user")
    dataset_id = _create_dataset(client, headers)

    imported = client.post(
        f"/api/v1/datasets/{dataset_id}/tasks/import",
        headers=headers,
        data={"archive": (_yolo_archive(), "dataset.zip")},
        content_type="multipart/form-data",
    )
    assert imported.status_code == 200
    assert imported.get_json()["summary"] == {
        "annotatedCount": 1,
        "detectedFormat": "yolo",
        "emptyAnnotationCount": 0,
        "importedCount": 1,
        "skippedCount": 0,
        "skippedFiles": [],
    }
    image = client.get(
        f"/api/v1/datasets/{dataset_id}", headers=headers
    ).get_json()["dataset"]["images"][0]
    stored = load_annotation_result(str(tmp_path), dataset_id, image["id"])
    assert stored is not None
    assert len(stored["detections"]) == 2
    assert {item["category"] for item in stored["detections"]} == {
        "pedestrian",
        "umbrella",
    }

    exported = client.post(
        f"/api/v1/datasets/{dataset_id}/export",
        headers=headers,
        json={"export_format": "yolo", "image_format": "keep"},
    )
    assert exported.status_code == 201
    downloaded = client.get(
        f"/api/v1/datasets/{dataset_id}/exports/1/download", headers=headers
    )
    archive = zipfile.ZipFile(BytesIO(downloaded.data))
    label_name = next(name for name in archive.namelist() if name.endswith(".txt"))
    assert len(archive.read(label_name).decode("utf-8").splitlines()) == 2

    reimported_dataset_id = _create_dataset(client, headers)
    reimported = client.post(
        f"/api/v1/datasets/{reimported_dataset_id}/tasks/import",
        headers=headers,
        data={"archive": (BytesIO(downloaded.data), "exported-dataset.zip")},
        content_type="multipart/form-data",
    )
    assert reimported.status_code == 200
    assert reimported.get_json()["summary"] == {
        "annotatedCount": 1,
        "detectedFormat": "yolo",
        "emptyAnnotationCount": 0,
        "importedCount": 1,
        "skippedCount": 0,
        "skippedFiles": [],
    }
    reimported_image = client.get(
        f"/api/v1/datasets/{reimported_dataset_id}", headers=headers
    ).get_json()["dataset"]["images"][0]
    assert reimported_image["annotationStatus"] == "annotated"
    reimported_annotations = load_annotation_result(
        str(tmp_path), reimported_dataset_id, reimported_image["id"]
    )
    assert reimported_annotations is not None
    assert len(reimported_annotations["detections"]) == 2
    assert {item["category"] for item in reimported_annotations["detections"]} == {
        "pedestrian",
        "umbrella",
    }


def test_roboflow_connection_encrypts_secret_and_never_returns_it(tmp_path, monkeypatch):
    class ConnectionConfig(TestConfig):
        STORAGE_ROOT = str(tmp_path)

    app = create_app(ConnectionConfig)
    client = app.test_client()
    headers = _auth_headers(client, "connection-user")
    monkeypatch.setattr(
        "app.api.integrations.validate_roboflow_api_key",
        lambda _: {"workspace": "workspace-one"},
    )

    response = client.post(
        "/api/v1/integrations/roboflow/connections",
        headers=headers,
        json={"name": "Production", "apiKey": "roboflow-secret-key"},
    )
    assert response.status_code == 201
    payload = response.get_json()["connection"]
    assert payload["hasApiKey"] is True
    assert "apiKey" not in payload
    assert "secret" not in str(payload).lower()

    with app.app_context():
        connection = db.session.get(ExternalConnection, payload["id"])
        assert connection is not None
        assert connection.secret_encrypted != "roboflow-secret-key"
        assert "roboflow-secret-key" not in connection.secret_encrypted

    listed = client.get(
        "/api/v1/integrations/roboflow/connections", headers=headers
    )
    assert listed.status_code == 200
    assert listed.get_json()["connections"] == [payload]
