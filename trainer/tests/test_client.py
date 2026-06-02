from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.client import BackendClient


class _FakeResponse:
    status_code = 200
    headers = {"content-type": "text/html; charset=utf-8"}

    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def raise_for_status(self) -> None:
        return None

    def iter_content(self, chunk_size: int) -> list[bytes]:
        return [self.body]


def test_dataset_download_url_uses_configured_backend_base_url() -> None:
    client = BackendClient("https://platform.example.com/api/v1", "token")

    assert (
        client.dataset_download_url("job-1")
        == "https://platform.example.com/api/v1/training/jobs/job-1/dataset.zip"
    )


def test_inference_download_urls_use_configured_backend_base_url() -> None:
    client = BackendClient("https://platform.example.com:4173/api/v1", "token")

    assert (
        client.inference_model_download_url("test-1")
        == "https://platform.example.com:4173/api/v1/training/inference-jobs/test-1/model"
    )
    assert (
        client.inference_image_download_url("test-1")
        == "https://platform.example.com:4173/api/v1/training/inference-jobs/test-1/image"
    )


def test_download_dataset_rejects_non_zip_response(tmp_path: Path) -> None:
    client = BackendClient("https://platform.example.com/api/v1", "token")
    body = b"<!doctype html><html><body>app shell</body></html>"

    def fake_get(*args: Any, **kwargs: Any) -> _FakeResponse:
        return _FakeResponse(body)

    client.session.get = fake_get  # type: ignore[method-assign]

    with pytest.raises(RuntimeError) as error:
        client.download_dataset(
            "https://platform.example.com/api/v1/training/jobs/job-1/dataset.zip",
            tmp_path / "dataset.zip",
        )

    message = str(error.value)
    assert "downloaded dataset is not a zip file" in message
    assert "content_type=text/html; charset=utf-8" in message
    assert "<!doctype html>" in message


def test_download_model_rejects_non_checkpoint_response(tmp_path: Path) -> None:
    client = BackendClient("https://platform.example.com/api/v1", "token")
    body = b"<!doctype html><html><body>app shell</body></html>"

    def fake_get(*args: Any, **kwargs: Any) -> _FakeResponse:
        return _FakeResponse(body)

    client.session.get = fake_get  # type: ignore[method-assign]

    with pytest.raises(RuntimeError) as error:
        client.download_model(
            "https://platform.example.com/api/v1/training/inference-jobs/test-1/model",
            tmp_path / "best.pt",
        )

    message = str(error.value)
    assert "downloaded model is not a valid PyTorch checkpoint" in message
    assert "content_type=text/html; charset=utf-8" in message
    assert "<!doctype html>" in message


def test_download_image_rejects_non_image_response(tmp_path: Path) -> None:
    client = BackendClient("https://platform.example.com/api/v1", "token")
    body = b'{"message":"invalid training worker token"}'

    def fake_get(*args: Any, **kwargs: Any) -> _FakeResponse:
        return _FakeResponse(body)

    client.session.get = fake_get  # type: ignore[method-assign]

    with pytest.raises(RuntimeError) as error:
        client.download_image(
            "https://platform.example.com/api/v1/training/inference-jobs/test-1/image",
            tmp_path / "image.jpg",
        )

    message = str(error.value)
    assert "downloaded test image is not a supported image file" in message
    assert "invalid training worker token" in message
