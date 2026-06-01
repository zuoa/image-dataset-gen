from __future__ import annotations

from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
import socket
import threading
import time
from pathlib import Path
from typing import Any

from app.client import BackendClient
from app.runner import train_yolov8


VERSION = "0.1.0"


class _HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path != "/health":
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        payload = b'{"status":"ok","service":"trainer"}\n'
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: object) -> None:
        return


def main() -> None:
    backend_url = os.getenv("TRAINER_BACKEND_URL", "http://backend:8000/api/v1")
    worker_token = os.getenv("TRAINER_WORKER_TOKEN", "")
    worker_id = os.getenv("TRAINER_WORKER_ID", socket.gethostname())
    worker_name = os.getenv("TRAINER_WORKER_NAME", f"trainer-{worker_id}")
    poll_interval = float(os.getenv("TRAINER_POLL_INTERVAL_SECONDS", "5"))
    work_root = Path(os.getenv("TRAINER_WORK_ROOT", "/app/work")).resolve()
    model_dir = Path(os.getenv("TRAINER_MODEL_DIR", "/app/models")).resolve()
    health_port = int(os.getenv("TRAINER_HEALTH_PORT", "8010"))
    work_root.mkdir(parents=True, exist_ok=True)
    model_dir.mkdir(parents=True, exist_ok=True)

    _start_health_server(health_port)

    if not worker_token:
        raise RuntimeError("TRAINER_WORKER_TOKEN is required")

    client = BackendClient(backend_url, worker_token)
    worker = client.register(
        worker_id=worker_id,
        name=worker_name,
        version=VERSION,
        capabilities={
            "frameworks": ["yolov8"],
            "tasks": ["detect"],
            "artifacts": ["best.pt", "last.pt", "results.csv", "metrics.json"],
            "runtime": "cuda",
            "modelCacheDir": str(model_dir),
        },
    )
    worker_id = worker["id"]

    current_job_id = ""
    while True:
        try:
            client.heartbeat(worker_id, "busy" if current_job_id else "idle", current_job_id)
            job = client.poll(worker_id)
            if job is None:
                current_job_id = ""
                time.sleep(poll_interval)
                continue
            current_job_id = str(job["id"])
            _run_job(client, job, work_root)
            current_job_id = ""
        except Exception as exc:
            if current_job_id:
                try:
                    client.update_status(current_job_id, "failed", error=str(exc))
                except Exception:
                    pass
                current_job_id = ""
            time.sleep(poll_interval)


def _run_job(client: BackendClient, job: dict[str, Any], work_root: Path) -> None:
    job_id = str(job["id"])
    job_root = work_root / job_id
    dataset_zip = job_root / "dataset.zip"
    job_root.mkdir(parents=True, exist_ok=True)

    client.update_status(job_id, "preparing", progress_percent=1)
    client.download_job_dataset(job_id, dataset_zip)

    def report_progress(percent: int) -> None:
        client.update_status(job_id, "running", progress_percent=percent)

    client.update_status(job_id, "running", progress_percent=3)
    result = train_yolov8(job, dataset_zip, work_root, report_progress)

    client.update_status(job_id, "uploading", progress_percent=96, metrics=result.get("metrics") or {})
    for artifact_type, path in result.get("artifacts") or []:
        client.upload_artifact(job_id, artifact_type, Path(path))
    client.update_status(job_id, "completed", progress_percent=100, metrics=result.get("metrics") or {})


def _start_health_server(port: int) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("0.0.0.0", port), _HealthHandler)
    thread = threading.Thread(
        target=server.serve_forever,
        daemon=True,
    )
    thread.start()
    return server


if __name__ == "__main__":
    main()
