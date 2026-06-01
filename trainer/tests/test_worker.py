from __future__ import annotations

import json
import urllib.request

from app.worker import _run_inference, _start_health_server


def test_health_server_returns_trainer_status() -> None:
    server = _start_health_server(0)
    port = server.server_address[1]
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=5) as response:
            assert response.status == 200
            assert response.headers["Content-Type"] == "application/json"
            assert json.loads(response.read().decode("utf-8")) == {
                "status": "ok",
                "service": "trainer",
            }
    finally:
        server.shutdown()
        server.server_close()


def test_run_inference_downloads_files_and_uploads_detections(tmp_path, monkeypatch) -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.statuses: list[tuple[str, list[dict] | None]] = []

        def update_inference_status(self, worker_id, test_id, status, detections=None, error="") -> None:
            assert worker_id == "gpu-1"
            assert test_id == "test-1"
            self.statuses.append((status, detections))

        def download_file(self, url, output_path) -> None:
            if url.endswith("/model"):
                output_path.write_bytes(b"model-weights")
            elif url.endswith("/image"):
                output_path.write_bytes(b"image-bytes")
            else:
                raise AssertionError(url)

    def fake_predict_yolov8(model_path, image_path, *, categories, confidence_threshold, image_size):
        assert model_path.read_bytes() == b"model-weights"
        assert image_path.read_bytes() == b"image-bytes"
        assert categories == ["widget"]
        assert confidence_threshold == 0.4
        assert image_size == 512
        return {
            "detections": [
                {
                    "category": "widget",
                    "classId": 0,
                    "confidence": 0.91,
                    "bbox": [0.5, 0.5, 0.5, 0.5],
                }
            ]
        }

    monkeypatch.setattr("app.worker.predict_yolov8", fake_predict_yolov8)
    client = FakeClient()

    _run_inference(
        client,  # type: ignore[arg-type]
        "gpu-1",
        {
            "id": "test-1",
            "modelDownloadUrl": "https://example.com/model",
            "imageDownloadUrl": "https://example.com/image",
            "artifact": {"filename": "best.pt"},
            "image": {"filename": "sample.jpg"},
            "categories": ["widget"],
            "confidenceThreshold": 0.4,
            "imageSize": 512,
        },
        tmp_path,
    )

    assert client.statuses[0] == ("running", None)
    assert client.statuses[1][0] == "completed"
    assert client.statuses[1][1][0]["category"] == "widget"
