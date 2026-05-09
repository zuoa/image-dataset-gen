from __future__ import annotations

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
        return response.json()["worker"]

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
        return response.json().get("job")

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

    def download_dataset(self, url: str, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with self.session.get(url, stream=True, timeout=self.timeout) as response:
            response.raise_for_status()
            with output_path.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        handle.write(chunk)

    def upload_artifact(self, job_id: str, artifact_type: str, path: Path) -> None:
        with path.open("rb") as handle:
            response = self.session.post(
                f"{self.base_url}/training/jobs/{job_id}/artifacts",
                data={"artifact_type": artifact_type},
                files={"artifact": (path.name, handle)},
                timeout=max(self.timeout, 120),
            )
        response.raise_for_status()
