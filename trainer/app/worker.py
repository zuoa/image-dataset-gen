from __future__ import annotations

import os
import socket
import threading
import time
from pathlib import Path
from typing import Any

from app import create_app
from app.client import BackendClient
from app.runner import predict_yolov8, train_yolov8
from werkzeug.serving import make_server


VERSION = "0.1.0"


def main() -> None:
    _configure_nofile_limit()

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

    if not worker_token:
        raise RuntimeError("TRAINER_WORKER_TOKEN is required")

    _start_health_server(health_port)

    client = BackendClient(backend_url, worker_token)
    worker = client.register(
        worker_id=worker_id,
        name=worker_name,
        version=VERSION,
        capabilities={
            "frameworks": ["yolov8"],
            "tasks": ["detect"],
            "inference": ["detect"],
            "artifacts": ["best.pt", "last.pt", "results.csv", "metrics.json"],
            "runtime": "cuda",
            "modelCacheDir": str(model_dir),
        },
    )
    worker_id = worker["id"]

    current_job_id = ""
    current_test_id = ""
    while True:
        try:
            client.heartbeat(worker_id, "busy" if current_job_id or current_test_id else "idle", current_job_id)
            job = client.poll(worker_id)
            if job is not None:
                current_job_id = str(job["id"])
                _run_job(client, job, work_root)
                current_job_id = ""
                continue

            test_job = client.poll_inference(worker_id)
            if test_job is None:
                current_test_id = ""
                time.sleep(poll_interval)
                continue

            current_test_id = str(test_job["id"])
            _run_inference(client, worker_id, test_job, work_root)
            current_test_id = ""
        except Exception as exc:
            if current_job_id:
                try:
                    client.update_status(current_job_id, "failed", error=str(exc))
                except Exception:
                    pass
                current_job_id = ""
            if current_test_id:
                try:
                    client.update_inference_status(worker_id, current_test_id, "failed", error=str(exc))
                except Exception:
                    pass
                current_test_id = ""
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


def _run_inference(client: BackendClient, worker_id: str, test_job: dict[str, Any], work_root: Path) -> None:
    test_id = str(test_job["id"])
    test_root = work_root / "inference" / test_id
    model_filename = str(((test_job.get("artifact") or {}).get("filename") or "model.pt"))
    image_mime_type = str(((test_job.get("image") or {}).get("mimeType") or "image/jpeg"))
    image_filename = "image.png" if image_mime_type == "image/png" else "image.jpg"
    model_path = test_root / model_filename
    image_path = test_root / image_filename
    test_root.mkdir(parents=True, exist_ok=True)

    client.update_inference_status(worker_id, test_id, "running")
    client.download_model(client.inference_model_download_url(test_id), model_path)
    client.download_image(client.inference_image_download_url(test_id), image_path)

    result = predict_yolov8(
        model_path,
        image_path,
        categories=[str(item) for item in test_job.get("categories") or []],
        confidence_threshold=float(test_job.get("confidenceThreshold") or 0.25),
        image_size=int(test_job.get("imageSize") or 640),
    )
    client.update_inference_status(
        worker_id,
        test_id,
        "completed",
        detections=result.get("detections") or [],
    )


def _start_health_server(port: int):
    server = make_server(
        "0.0.0.0",
        port,
        create_app(),
        threaded=True,
    )
    thread = threading.Thread(
        target=server.serve_forever,
        daemon=True,
    )
    thread.start()
    return server


def _configure_nofile_limit() -> None:
    try:
        import resource
    except ImportError:
        return

    requested = _env_int("TRAINER_NOFILE_LIMIT", 65535)
    if requested <= 0:
        return

    try:
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        if soft >= requested:
            return

        if hard == resource.RLIM_INFINITY:
            new_soft = requested
        else:
            new_soft = min(requested, hard)
        if new_soft > soft:
            resource.setrlimit(resource.RLIMIT_NOFILE, (new_soft, hard))
    except (OSError, ValueError):
        return


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    try:
        return int(value)
    except ValueError:
        return default


if __name__ == "__main__":
    main()
