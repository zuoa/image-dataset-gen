from __future__ import annotations

from io import BytesIO
import zipfile

import pytest

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
    runtime = imported.get_json()["task"]["config"]["runtime"]
    assert runtime["annotatedCount"] == 1
    assert runtime["detectedFormat"] == "yolo"
    assert runtime["emptyAnnotationCount"] == 0
    assert runtime["importedCount"] == 1
    assert runtime["skippedCount"] == 0
    assert runtime["skippedFiles"] == []
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
    reimported_runtime = reimported.get_json()["task"]["config"]["runtime"]
    assert reimported_runtime["annotatedCount"] == 1
    assert reimported_runtime["detectedFormat"] == "yolo"
    assert reimported_runtime["emptyAnnotationCount"] == 0
    assert reimported_runtime["importedCount"] == 1
    assert reimported_runtime["skippedCount"] == 0
    assert reimported_runtime["skippedFiles"] == []
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


def test_roboflow_project_link_resolves_versions(tmp_path, monkeypatch):
    class ConnectionConfig(TestConfig):
        STORAGE_ROOT = str(tmp_path)

    class FakeProject:
        name = "Cherry Tomato Plants"
        type = "object-detection"

        def get_version_information(self):
            return [
                {
                    "id": "ajs-workspace-eapuq/cherry-tomato-plants2-0-rdqhi/2",
                    "name": "baseline",
                    "images": 25,
                },
                {
                    "id": "ajs-workspace-eapuq/cherry-tomato-plants2-0-rdqhi/10",
                    "name": "latest",
                    "images": 42,
                },
            ]

    class FakeWorkspace:
        def project(self, project_id):
            assert project_id == "cherry-tomato-plants2-0-rdqhi"
            return FakeProject()

    class FakeClient:
        def workspace(self, workspace_id):
            assert workspace_id == "ajs-workspace-eapuq"
            return FakeWorkspace()

    app = create_app(ConnectionConfig)
    client = app.test_client()
    headers = _auth_headers(client, "project-link-user")
    monkeypatch.setattr(
        "app.api.integrations.validate_roboflow_api_key",
        lambda _: {"workspace": "ajs-workspace-eapuq"},
    )
    monkeypatch.setattr(
        "app.services.external_connection_service._make_roboflow_client",
        lambda api_key: FakeClient() if api_key == "roboflow-secret-key" else None,
    )
    connection = client.post(
        "/api/v1/integrations/roboflow/connections",
        headers=headers,
        json={"name": "Production", "apiKey": "roboflow-secret-key"},
    ).get_json()["connection"]

    response = client.post(
        "/api/v1/integrations/roboflow/project-links/resolve",
        headers=headers,
        json={
            "connectionId": connection["id"],
            "url": (
                "https://app.roboflow.com/ajs-workspace-eapuq/"
                "cherry-tomato-plants2-0-rdqhi/browse/?tab=images#top"
            ),
        },
    )

    assert response.status_code == 200
    assert response.get_json()["project"] == {
        "workspace": "ajs-workspace-eapuq",
        "project": "cherry-tomato-plants2-0-rdqhi",
        "projectName": "Cherry Tomato Plants",
        "projectType": "object-detection",
        "versions": [
            {"version": "10", "name": "latest", "imageCount": 42},
            {"version": "2", "name": "baseline", "imageCount": 25},
        ],
        "selectedVersion": "10",
    }
    assert "roboflow-secret-key" not in response.get_data(as_text=True)


def test_roboflow_version_link_selects_and_validates_requested_version(
    tmp_path, monkeypatch
):
    class ConnectionConfig(TestConfig):
        STORAGE_ROOT = str(tmp_path)

    class FakeProject:
        name = "Project"
        type = "object-detection"

        def get_version_information(self):
            return [{"id": "workspace/project/3", "images": 10}]

    class FakeWorkspace:
        def project(self, _):
            return FakeProject()

    class FakeClient:
        def workspace(self, _):
            return FakeWorkspace()

    app = create_app(ConnectionConfig)
    client = app.test_client()
    headers = _auth_headers(client, "version-link-user")
    monkeypatch.setattr(
        "app.api.integrations.validate_roboflow_api_key", lambda _: {"workspace": "workspace"}
    )
    monkeypatch.setattr(
        "app.services.external_connection_service._make_roboflow_client",
        lambda _: FakeClient(),
    )
    connection_id = client.post(
        "/api/v1/integrations/roboflow/connections",
        headers=headers,
        json={"name": "Production", "apiKey": "roboflow-secret-key"},
    ).get_json()["connection"]["id"]

    selected = client.post(
        "/api/v1/integrations/roboflow/project-links/resolve",
        headers=headers,
        json={
            "connectionId": connection_id,
            "url": "https://app.roboflow.com/workspace/project/3",
        },
    )
    missing = client.post(
        "/api/v1/integrations/roboflow/project-links/resolve",
        headers=headers,
        json={
            "connectionId": connection_id,
            "url": "https://app.roboflow.com/workspace/project/4",
        },
    )

    assert selected.status_code == 200
    assert selected.get_json()["project"]["selectedVersion"] == "3"
    assert missing.status_code == 400
    assert missing.get_json()["message"] == "链接中的 Roboflow 数据版本不存在或不可用。"


@pytest.mark.parametrize(
    "project_url",
    [
        "http://app.roboflow.com/workspace/project/browse",
        "https://evil.example/workspace/project/browse",
        "https://app.roboflow.com/workspace/project/settings",
        "https://app.roboflow.com/workspace/project/0",
        "https://app.roboflow.com/workspace/project/browse/extra",
        "https://app.roboflow.com/workspace%2Fescaped/project/browse",
    ],
)
def test_roboflow_project_link_rejects_unsupported_urls(project_url):
    from app.services.external_connection_service import (
        RoboflowProjectResolutionError,
        _parse_roboflow_project_link,
    )

    with pytest.raises(RoboflowProjectResolutionError):
        _parse_roboflow_project_link(project_url)


def test_roboflow_project_link_requires_owned_valid_connection(tmp_path, monkeypatch):
    class ConnectionConfig(TestConfig):
        STORAGE_ROOT = str(tmp_path)

    app = create_app(ConnectionConfig)
    client = app.test_client()
    owner_headers = _auth_headers(client, "project-owner")
    other_headers = _auth_headers(client, "different-user")
    monkeypatch.setattr(
        "app.api.integrations.validate_roboflow_api_key",
        lambda _: {"workspace": "workspace"},
    )
    connection_id = client.post(
        "/api/v1/integrations/roboflow/connections",
        headers=owner_headers,
        json={"name": "Production", "apiKey": "roboflow-secret-key"},
    ).get_json()["connection"]["id"]
    request_payload = {
        "connectionId": connection_id,
        "url": "https://app.roboflow.com/workspace/project/browse",
    }

    not_owned = client.post(
        "/api/v1/integrations/roboflow/project-links/resolve",
        headers=other_headers,
        json=request_payload,
    )
    with app.app_context():
        connection = db.session.get(ExternalConnection, connection_id)
        connection.status = "invalid"
        db.session.commit()
    invalid = client.post(
        "/api/v1/integrations/roboflow/project-links/resolve",
        headers=owner_headers,
        json=request_payload,
    )

    assert not_owned.status_code == 404
    assert invalid.status_code == 409
    assert invalid.get_json()["message"] == "Roboflow 连接不可用，请先重新验证。"


def test_roboflow_version_normalization_handles_empty_and_malformed_values():
    from app.services.external_connection_service import _normalize_roboflow_versions

    assert _normalize_roboflow_versions([]) == []
    assert _normalize_roboflow_versions(
        [
            {"id": "workspace/project/2", "images": "invalid"},
            {"id": "workspace/project/not-a-version", "images": 4},
            None,
        ]
    ) == [{"version": "2", "name": "", "imageCount": 0}]
