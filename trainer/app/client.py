from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Any

import requests


class BackendClient:
    def __init__(self, base_url: str, worker_token: str, timeout: int = 30) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"X-Training-Worker-Token": worker_token})

    def register(self, worker_id: str, name: str, version: str, capabilities: dict[str, Any]) -> dict[str, Any]:
        response = self.session.post(
            f"{self.base_url}/training/workers/register",
            json={
                "worker_id": worker_id,
                "name": name,
                "version": version,
                "capabilities": capabilities,
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        worker_token = payload.get("workerToken")
        if worker_token:
            self.session.headers.update({"X-Training-Worker-Token": str(worker_token)})
        return payload["worker"]

    def heartbeat(self, worker_id: str, status: str, current_job_id: str = "") -> None:
        response = self.session.post(
            f"{self.base_url}/training/workers/{worker_id}/heartbeat",
            json={"status": status, "current_job_id": current_job_id},
            timeout=self.timeout,
        )
        response.raise_for_status()

    def poll(self, worker_id: str) -> dict[str, Any] | None:
        response = self.session.post(
            f"{self.base_url}/training/workers/{worker_id}/poll",
            json={},
            timeout=self.timeout,
        )
        response.raise_for_status()
        job = response.json().get("job")
        if job and job.get("assignmentToken"):
            self.session.headers.update({"X-Assignment-Token": str(job["assignmentToken"])})
        return job

    def poll_inference(self, worker_id: str) -> dict[str, Any] | None:
        response = self.session.post(
            f"{self.base_url}/training/workers/{worker_id}/inference/poll",
            json={},
            timeout=self.timeout,
        )
        response.raise_for_status()
        test_job = response.json().get("test")
        if test_job and test_job.get("assignmentToken"):
            self.session.headers.update({"X-Assignment-Token": str(test_job["assignmentToken"])})
        return test_job

    def dataset_download_url(self, job_id: str) -> str:
        return f"{self.base_url}/training/jobs/{job_id}/dataset.zip"

    def inference_model_download_url(self, test_id: str) -> str:
        return f"{self.base_url}/training/inference-jobs/{test_id}/model"

    def inference_image_download_url(self, test_id: str) -> str:
        return f"{self.base_url}/training/inference-jobs/{test_id}/image"

    def download_job_dataset(self, job_id: str, output_path: Path) -> None:
        self.download_dataset(self.dataset_download_url(job_id), output_path)

    def update_status(
        self,
        job_id: str,
        status: str,
        progress_percent: int | None = None,
        metrics: dict[str, Any] | None = None,
        error: str = "",
    ) -> None:
        payload: dict[str, Any] = {"status": status}
        if progress_percent is not None:
            payload["progress_percent"] = progress_percent
        if metrics:
            payload["metrics"] = metrics
        if error:
            payload["error"] = error[:2000]
        response = self.session.patch(
            f"{self.base_url}/training/jobs/{job_id}/status",
            json=payload,
            timeout=self.timeout,
        )
        response.raise_for_status()

    def update_inference_status(
        self,
        worker_id: str,
        test_id: str,
        status: str,
        detections: list[dict[str, Any]] | None = None,
        error: str = "",
    ) -> None:
        payload: dict[str, Any] = {"status": status}
        if detections is not None:
            payload["detections"] = detections
        if error:
            payload["error"] = error[:2000]
        response = self.session.patch(
            f"{self.base_url}/training/workers/{worker_id}/inference-jobs/{test_id}/status",
            json=payload,
            timeout=max(self.timeout, 120),
        )
        response.raise_for_status()

    def download_file(self, url: str, output_path: Path) -> None:
        self._download_with_metadata(url, output_path)

    def download_model(self, url: str, output_path: Path) -> None:
        metadata = self._download_with_metadata(url, output_path)
        if _is_supported_torch_checkpoint(output_path):
            return
        raise RuntimeError(
            _invalid_download_message("downloaded model is not a valid PyTorch checkpoint", metadata, output_path)
        )

    def download_image(self, url: str, output_path: Path) -> None:
        metadata = self._download_with_metadata(url, output_path)
        if _is_supported_image(output_path):
            return
        raise RuntimeError(
            _invalid_download_message("downloaded test image is not a supported image file", metadata, output_path)
        )

    def download_dataset(self, url: str, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        status_code = 0
        content_type = ""
        bytes_written = 0
        with self.session.get(url, stream=True, timeout=self.timeout) as response:
            status_code = response.status_code
            content_type = response.headers.get("content-type", "")
            response.raise_for_status()
            with output_path.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        handle.write(chunk)
                        bytes_written += len(chunk)

        if not zipfile.is_zipfile(output_path):
            with output_path.open("rb") as handle:
                prefix = handle.read(160)
            raise RuntimeError(
                "downloaded dataset is not a zip file "
                f"(url={url}, status={status_code}, content_type={content_type or 'unknown'}, "
                f"size_bytes={bytes_written}, first_bytes={prefix!r})"
            )

    def _download_with_metadata(self, url: str, output_path: Path) -> dict[str, Any]:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        status_code = 0
        content_type = ""
        bytes_written = 0
        with self.session.get(url, stream=True, timeout=self.timeout) as response:
            status_code = response.status_code
            content_type = response.headers.get("content-type", "")
            response.raise_for_status()
            with output_path.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        handle.write(chunk)
                        bytes_written += len(chunk)

        metadata = {
            "url": url,
            "status": status_code,
            "content_type": content_type or "unknown",
            "size_bytes": bytes_written,
        }
        if bytes_written == 0:
            raise RuntimeError(_invalid_download_message("downloaded file is empty", metadata, output_path))
        return metadata

    def upload_artifact(self, job_id: str, artifact_type: str, path: Path) -> None:
        with path.open("rb") as handle:
            response = self.session.post(
                f"{self.base_url}/training/jobs/{job_id}/artifacts",
                data={"artifact_type": artifact_type},
                files={"artifact": (path.name, handle)},
                timeout=max(self.timeout, 120),
            )
        response.raise_for_status()


def _is_supported_torch_checkpoint(path: Path) -> bool:
    if zipfile.is_zipfile(path):
        return True
    return _file_prefix(path, 2).startswith(b"\x80")


def _is_supported_image(path: Path) -> bool:
    prefix = _file_prefix(path, 16)
    return (
        prefix.startswith(b"\xff\xd8\xff")
        or prefix.startswith(b"\x89PNG\r\n\x1a\n")
        or (prefix.startswith(b"RIFF") and prefix[8:12] == b"WEBP")
        or prefix.startswith(b"BM")
        or prefix.startswith(b"II*\x00")
        or prefix.startswith(b"MM\x00*")
    )


def _invalid_download_message(message: str, metadata: dict[str, Any], path: Path) -> str:
    prefix = _file_prefix(path, 160)
    return (
        f"{message} "
        f"(url={metadata['url']}, status={metadata['status']}, content_type={metadata['content_type']}, "
        f"size_bytes={metadata['size_bytes']}, first_bytes={prefix!r})"
    )


def _file_prefix(path: Path, size: int) -> bytes:
    with path.open("rb") as handle:
        return handle.read(size)
