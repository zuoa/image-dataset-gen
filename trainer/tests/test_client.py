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
