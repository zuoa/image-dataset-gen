from __future__ import annotations

from pathlib import Path
import shutil
from typing import Any

from flask import Blueprint, current_app, jsonify, request, send_file
from flask_jwt_extended import get_jwt_identity, jwt_required
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

from app.extensions import db
from app.models import Dataset, DatasetExport, TrainingArtifact, TrainingInferenceJob, TrainingJob, TrainingWorker
from app.schemas import (
    TrainingJobSchema,
    TrainingJobStatusSchema,
    TrainingWorkerHeartbeatSchema,
    TrainingWorkerRegisterSchema,
)
from app.services.dataset_export_service import get_dataset_archive_path
from app.services.dataset_service import (
    build_dataset_export_payload,
    build_dataset_payload,
    next_dataset_export_version,
    now_utc,
    sync_dataset,
)
from app.services.training_inference_service import (
    TrainingInferenceError,
    build_training_inference_payload,
    complete_training_inference_job,
    create_training_inference_job,
    fail_training_inference_job,
)

training_bp = Blueprint("training", __name__)

ACTIVE_JOB_STATUSES = {"assigned", "preparing", "running", "uploading"}
ACTIVE_INFERENCE_STATUSES = {"assigned", "running"}


def _dispatch_background_task(task_callable, *args: object) -> None:
    try:
        task_callable.delay(*args)
    except Exception:
        task_name = getattr(task_callable, "name", repr(task_callable))
        current_app.logger.exception(
            "Failed to enqueue background task %s; falling back to inline execution",
            task_name,
        )
        task_callable.apply(args=args, throw=False)


def _dataset_for_user(dataset_id: str, user_id: str) -> Dataset:
    return Dataset.query.filter_by(id=dataset_id, user_id=user_id).first_or_404()


def _require_worker_token() -> tuple[dict[str, str], int] | None:
    expected = str(current_app.config.get("TRAINING_WORKER_TOKEN") or "").strip()
    if not expected:
        return {"message": "training worker token is not configured"}, 503

    supplied = (
        request.headers.get("X-Training-Worker-Token")
        or request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    )
    if supplied != expected:
        return {"message": "invalid training worker token"}, 401
    return None


def _artifact_root(job_id: str) -> Path:
    return Path(current_app.config["STORAGE_ROOT"]) / "training" / job_id


def _inference_download_url(test_job: TrainingInferenceJob, kind: str) -> str:
    return (
        f"{request.url_root.rstrip('/')}{current_app.config['API_PREFIX']}"
        f"/training/inference-jobs/{test_job.id}/{kind}"
    )


def _build_training_inference_assignment(test_job: TrainingInferenceJob) -> dict[str, Any]:
    payload = build_training_inference_payload(test_job)
    payload.update(
        {
            "modelDownloadUrl": _inference_download_url(test_job, "model"),
            "imageDownloadUrl": _inference_download_url(test_job, "image"),
            "categories": test_job.training_job.dataset.categories if test_job.training_job and test_job.training_job.dataset else [],
        }
    )
    return payload


def _artifact_download_url(job: TrainingJob, artifact: TrainingArtifact) -> str:
    return (
        f"{current_app.config['API_PREFIX']}/datasets/{job.dataset_id}/training-jobs/"
        f"{job.id}/artifacts/{artifact.id}/download"
    )


def _build_worker_payload(worker: TrainingWorker) -> dict[str, Any]:
    return {
        "id": worker.id,
        "name": worker.name,
        "status": worker.status,
        "capabilities": worker.capabilities_json or {},
        "version": worker.version,
        "currentJobId": worker.current_job_id,
        "lastHeartbeatAt": worker.last_heartbeat_at.isoformat() if worker.last_heartbeat_at else None,
        "createdAt": worker.created_at.isoformat() if worker.created_at else None,
        "updatedAt": worker.updated_at.isoformat() if worker.updated_at else None,
    }


def _build_training_job_payload(job: TrainingJob, *, include_assignment: bool = False) -> dict[str, Any]:
    artifacts = [
        {
            "id": artifact.id,
            "type": artifact.artifact_type,
            "filename": artifact.filename,
            "sizeBytes": artifact.size_bytes,
            "downloadUrl": _artifact_download_url(job, artifact),
            "createdAt": artifact.created_at.isoformat() if artifact.created_at else None,
        }
        for artifact in job.artifacts
    ]
    payload: dict[str, Any] = {
        "id": job.id,
        "datasetId": job.dataset_id,
        "exportId": job.export_id,
        "workerId": job.worker_id,
        "status": job.status,
        "progressPercent": int(job.progress_percent or 0),
        "config": job.config_json or {},
        "metrics": job.metrics_json or {},
        "error": job.error_message,
        "artifacts": artifacts,
        "export": build_dataset_export_payload(job.export) if job.export else None,
        "createdAt": job.created_at.isoformat() if job.created_at else None,
        "updatedAt": job.updated_at.isoformat() if job.updated_at else None,
        "startedAt": job.started_at.isoformat() if job.started_at else None,
        "completedAt": job.completed_at.isoformat() if job.completed_at else None,
    }
    if include_assignment:
        payload["datasetDownloadUrl"] = (
            f"{request.url_root.rstrip('/')}{current_app.config['API_PREFIX']}"
            f"/training/jobs/{job.id}/dataset.zip"
        )
        payload["datasetName"] = job.dataset.name if job.dataset else ""
        payload["categories"] = job.dataset.categories if job.dataset else []
    return payload


def _create_yolo_export(dataset: Dataset) -> DatasetExport:
    version = next_dataset_export_version(dataset)
    export_job = DatasetExport(
        dataset_id=dataset.id,
        version=version,
        export_format="yolo",
        status="pending",
        download_url=f"{current_app.config['API_PREFIX']}/datasets/{dataset.id}/exports/{version}/download",
        summary_json={
            "imageFormat": "keep",
            "includeReadme": True,
            "structure": "yolov8",
            "estimatedSizeMb": round(max(dataset.selected_count or dataset.image_count, 1) * 0.6, 1),
        },
    )
    db.session.add(export_job)
    db.session.commit()

    from app.worker_tasks import export_dataset_archive

    _dispatch_background_task(export_dataset_archive, export_job.id)
    db.session.refresh(export_job)
    return export_job


@training_bp.post("/datasets/<dataset_id>/training-jobs")
@jwt_required()
def create_training_job(dataset_id: str):
    user_id = get_jwt_identity()
    payload = TrainingJobSchema().load(request.get_json() or {})
    dataset = sync_dataset(_dataset_for_user(dataset_id, user_id))
    if not any(image.selected for image in dataset.images):
        return jsonify({"message": "no images selected for training"}), 400
    classes = sorted(dict.fromkeys(int(index) for index in payload["classes"]))
    invalid_classes = [index for index in classes if index >= len(dataset.categories)]
    if invalid_classes:
        return jsonify({"message": "training classes contain indexes outside dataset categories"}), 400

    export_job = _create_yolo_export(dataset)
    config_json = {
        "framework": "yolov8",
        "task": "detect",
        "model": payload["model"],
        "epochs": payload["epochs"],
        "imageSize": payload["image_size"],
        "batchSize": payload["batch_size"],
        "patience": payload["patience"],
        "dropout": payload["dropout"],
        "mixup": payload["mixup"],
        "weightDecay": payload["weight_decay"],
        "classes": classes,
        "device": payload.get("device") or "",
    }
    if payload.get("workers") is not None:
        config_json["workers"] = payload["workers"]

    job = TrainingJob(
        dataset_id=dataset.id,
        user_id=user_id,
        export_id=export_job.id,
        status="queued",
        progress_percent=0,
        config_json=config_json,
    )
    db.session.add(job)
    db.session.commit()
    return jsonify({"job": _build_training_job_payload(job), "dataset": build_dataset_payload(dataset)}), 201


@training_bp.get("/datasets/<dataset_id>/training-jobs")
@jwt_required()
def list_training_jobs(dataset_id: str):
    user_id = get_jwt_identity()
    _dataset_for_user(dataset_id, user_id)
    jobs = TrainingJob.query.filter_by(dataset_id=dataset_id).order_by(TrainingJob.created_at.desc()).all()
    return jsonify({"jobs": [_build_training_job_payload(job) for job in jobs]})


@training_bp.get("/datasets/<dataset_id>/training-jobs/<job_id>")
@jwt_required()
def get_training_job(dataset_id: str, job_id: str):
    user_id = get_jwt_identity()
    _dataset_for_user(dataset_id, user_id)
    job = TrainingJob.query.filter_by(id=job_id, dataset_id=dataset_id).first_or_404()
    return jsonify({"job": _build_training_job_payload(job)})


@training_bp.get("/datasets/<dataset_id>/training-jobs/<job_id>/artifacts/<artifact_id>/download")
@jwt_required()
def download_training_artifact(dataset_id: str, job_id: str, artifact_id: str):
    user_id = get_jwt_identity()
    _dataset_for_user(dataset_id, user_id)
    job = TrainingJob.query.filter_by(id=job_id, dataset_id=dataset_id).first_or_404()
    artifact = TrainingArtifact.query.filter_by(id=artifact_id, job_id=job.id).first_or_404()
    artifact_path = Path(artifact.storage_path)
    return send_file(
        artifact_path,
        as_attachment=True,
        download_name=artifact.filename,
        mimetype="application/octet-stream",
    )


@training_bp.post("/datasets/<dataset_id>/training-jobs/<job_id>/test")
@jwt_required()
def test_training_job_model(dataset_id: str, job_id: str):
    user_id = get_jwt_identity()
    _dataset_for_user(dataset_id, user_id)
    job = TrainingJob.query.filter_by(id=job_id, dataset_id=dataset_id, user_id=user_id).first_or_404()
    if job.status != "completed":
        return jsonify({"message": "训练完成后才能测试模型。"}), 409

    uploaded: FileStorage | None = request.files.get("image")
    if uploaded is None or not uploaded.filename:
        return jsonify({"message": "请上传一张测试图片。"}), 400

    image_bytes = uploaded.read()
    if not image_bytes:
        return jsonify({"message": "上传的测试图片为空。"}), 400

    try:
        confidence_threshold = _bounded_form_float("confidence_threshold", default=0.25, minimum=0.01, maximum=1.0)
        image_size = _bounded_form_int("image_size", default=640, minimum=64, maximum=2048)
        test_job = create_training_inference_job(
            job,
            image_bytes,
            filename=uploaded.filename,
            artifact_id=(request.form.get("artifact_id") or "").strip(),
            confidence_threshold=confidence_threshold,
            image_size=image_size,
        )
    except TrainingInferenceError as exc:
        return jsonify({"message": str(exc)}), exc.status_code

    db.session.commit()
    return jsonify({"test": build_training_inference_payload(test_job)}), 201


@training_bp.get("/datasets/<dataset_id>/training-jobs/<job_id>/tests/<test_id>")
@jwt_required()
def get_training_inference_job(dataset_id: str, job_id: str, test_id: str):
    user_id = get_jwt_identity()
    _dataset_for_user(dataset_id, user_id)
    test_job = TrainingInferenceJob.query.filter_by(
        id=test_id,
        training_job_id=job_id,
        dataset_id=dataset_id,
        user_id=user_id,
    ).first_or_404()
    return jsonify({"test": build_training_inference_payload(test_job)})


@training_bp.delete("/datasets/<dataset_id>/training-jobs/<job_id>")
@jwt_required()
def delete_training_job(dataset_id: str, job_id: str):
    user_id = get_jwt_identity()
    dataset = _dataset_for_user(dataset_id, user_id)
    job = TrainingJob.query.filter_by(id=job_id, dataset_id=dataset.id, user_id=user_id).first_or_404()
    deleted_job_id = job.id

    if job.worker is not None and job.worker.current_job_id == job.id:
        job.worker.current_job_id = None
        job.worker.status = "idle"

    shutil.rmtree(_artifact_root(job.id), ignore_errors=True)
    db.session.delete(job)
    db.session.commit()
    return jsonify({"deletedJobId": deleted_job_id, "dataset": build_dataset_payload(sync_dataset(dataset))})


def _bounded_form_float(name: str, *, default: float, minimum: float, maximum: float) -> float:
    raw_value = request.form.get(name)
    if raw_value is None or raw_value == "":
        return default
    try:
        value = float(raw_value)
    except ValueError as exc:
        raise TrainingInferenceError(f"{name} must be a number", 422) from exc
    if value < minimum or value > maximum:
        raise TrainingInferenceError(f"{name} must be between {minimum} and {maximum}", 422)
    return value


def _bounded_form_int(name: str, *, default: int, minimum: int, maximum: int) -> int:
    raw_value = request.form.get(name)
    if raw_value is None or raw_value == "":
        return default
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise TrainingInferenceError(f"{name} must be an integer", 422) from exc
    if value < minimum or value > maximum:
        raise TrainingInferenceError(f"{name} must be between {minimum} and {maximum}", 422)
    return value


@training_bp.post("/training/workers/register")
def register_training_worker():
    token_error = _require_worker_token()
    if token_error is not None:
        body, status = token_error
        return jsonify(body), status

    payload = TrainingWorkerRegisterSchema().load(request.get_json() or {})
    worker_id = (payload.get("worker_id") or "").strip() or None
    worker = db.session.get(TrainingWorker, worker_id) if worker_id else None
    if worker is None:
        worker = TrainingWorker(id=worker_id, name=payload["name"].strip())
        db.session.add(worker)

    worker.name = payload["name"].strip()
    worker.version = (payload.get("version") or "").strip()
    worker.capabilities_json = payload.get("capabilities") or {}
    worker.status = "idle"
    worker.last_heartbeat_at = now_utc()
    db.session.commit()
    return jsonify({"worker": _build_worker_payload(worker)})


@training_bp.post("/training/workers/<worker_id>/heartbeat")
def heartbeat_training_worker(worker_id: str):
    token_error = _require_worker_token()
    if token_error is not None:
        body, status = token_error
        return jsonify(body), status

    worker = db.session.get(TrainingWorker, worker_id)
    if worker is None:
        return jsonify({"message": "worker not registered"}), 404

    payload = TrainingWorkerHeartbeatSchema().load(request.get_json() or {})
    worker.last_heartbeat_at = now_utc()
    current_job_id = (payload.get("current_job_id") or "").strip()
    worker.current_job_id = current_job_id or worker.current_job_id
    worker.status = "busy" if worker.current_job_id else payload["status"]
    db.session.commit()
    return jsonify({"worker": _build_worker_payload(worker)})


@training_bp.post("/training/workers/<worker_id>/poll")
def poll_training_job(worker_id: str):
    token_error = _require_worker_token()
    if token_error is not None:
        body, status = token_error
        return jsonify(body), status

    worker = db.session.get(TrainingWorker, worker_id)
    if worker is None:
        return jsonify({"message": "worker not registered"}), 404

    worker.last_heartbeat_at = now_utc()
    if worker.current_job_id:
        active_job = db.session.get(TrainingJob, worker.current_job_id)
        if active_job is not None and active_job.status in ACTIVE_JOB_STATUSES:
            worker.status = "busy"
            db.session.commit()
            return jsonify({"job": _build_training_job_payload(active_job, include_assignment=True)})
        worker.current_job_id = None

    queued_jobs = TrainingJob.query.filter_by(status="queued").order_by(TrainingJob.created_at.asc()).all()
    for job in queued_jobs:
        if job.export.status == "failed":
            job.status = "failed"
            job.error_message = "dataset_export_failed"
            job.completed_at = now_utc()
            continue
        archive_path = get_dataset_archive_path(current_app.config["STORAGE_ROOT"], job.export)
        if job.export.status != "ready" or not archive_path.exists():
            continue

        job.status = "assigned"
        job.worker_id = worker.id
        worker.current_job_id = job.id
        worker.status = "busy"
        db.session.commit()
        return jsonify({"job": _build_training_job_payload(job, include_assignment=True)})

    worker.status = "idle"
    db.session.commit()
    return jsonify({"job": None})


@training_bp.post("/training/workers/<worker_id>/inference/poll")
def poll_training_inference_job(worker_id: str):
    token_error = _require_worker_token()
    if token_error is not None:
        body, status = token_error
        return jsonify(body), status

    worker = db.session.get(TrainingWorker, worker_id)
    if worker is None:
        return jsonify({"message": "worker not registered"}), 404

    worker.last_heartbeat_at = now_utc()
    if worker.current_job_id:
        active_job = db.session.get(TrainingJob, worker.current_job_id)
        if active_job is not None and active_job.status in ACTIVE_JOB_STATUSES:
            worker.status = "busy"
            db.session.commit()
            return jsonify({"test": None})
        worker.current_job_id = None

    active_test = (
        TrainingInferenceJob.query.filter_by(worker_id=worker.id)
        .filter(TrainingInferenceJob.status.in_(ACTIVE_INFERENCE_STATUSES))
        .order_by(TrainingInferenceJob.created_at.asc())
        .first()
    )
    if active_test is not None:
        worker.status = "busy"
        db.session.commit()
        return jsonify({"test": _build_training_inference_assignment(active_test)})

    queued_test = (
        TrainingInferenceJob.query.filter_by(status="queued")
        .order_by(TrainingInferenceJob.created_at.asc())
        .first()
    )
    if queued_test is None:
        worker.status = "idle"
        db.session.commit()
        return jsonify({"test": None})

    queued_test.status = "assigned"
    queued_test.worker_id = worker.id
    worker.status = "busy"
    db.session.commit()
    return jsonify({"test": _build_training_inference_assignment(queued_test)})


@training_bp.get("/training/inference-jobs/<test_id>/model")
def download_training_inference_model(test_id: str):
    token_error = _require_worker_token()
    if token_error is not None:
        body, status = token_error
        return jsonify(body), status

    test_job = db.session.get(TrainingInferenceJob, test_id)
    if test_job is None:
        return jsonify({"message": "test job not found"}), 404
    artifact = test_job.artifact
    if artifact is None:
        return jsonify({"message": "model artifact not found"}), 404
    artifact_path = Path(artifact.storage_path)
    if not artifact_path.exists():
        return jsonify({"message": "model artifact file not found"}), 409
    return send_file(
        artifact_path,
        as_attachment=True,
        download_name=artifact.filename,
        mimetype="application/octet-stream",
    )


@training_bp.get("/training/inference-jobs/<test_id>/image")
def download_training_inference_image(test_id: str):
    token_error = _require_worker_token()
    if token_error is not None:
        body, status = token_error
        return jsonify(body), status

    test_job = db.session.get(TrainingInferenceJob, test_id)
    if test_job is None:
        return jsonify({"message": "test job not found"}), 404
    input_path = Path(test_job.input_storage_path)
    if not input_path.exists():
        return jsonify({"message": "test image file not found"}), 409
    return send_file(
        input_path,
        as_attachment=True,
        download_name=test_job.input_filename or input_path.name,
        mimetype=test_job.input_mime_type,
    )


@training_bp.patch("/training/workers/<worker_id>/inference-jobs/<test_id>/status")
def update_training_inference_job_status(worker_id: str, test_id: str):
    token_error = _require_worker_token()
    if token_error is not None:
        body, status = token_error
        return jsonify(body), status

    worker = db.session.get(TrainingWorker, worker_id)
    if worker is None:
        return jsonify({"message": "worker not registered"}), 404
    test_job = db.session.get(TrainingInferenceJob, test_id)
    if test_job is None:
        return jsonify({"message": "test job not found"}), 404

    payload = request.get_json() or {}
    next_status = str(payload.get("status") or "").strip()
    if next_status not in {"running", "completed", "failed"}:
        return jsonify({"message": "status must be running, completed or failed"}), 422

    test_job.worker_id = worker.id
    if next_status == "running":
        test_job.status = "running"
        if test_job.started_at is None:
            test_job.started_at = now_utc()
        worker.status = "busy"
    elif next_status == "completed":
        try:
            complete_training_inference_job(test_job, payload.get("detections") or [])
        except TrainingInferenceError as exc:
            return jsonify({"message": str(exc)}), exc.status_code
        worker.status = "idle"
    elif next_status == "failed":
        fail_training_inference_job(test_job, str(payload.get("error") or "prediction_failed"))
        worker.status = "idle"

    db.session.commit()
    return jsonify({"test": build_training_inference_payload(test_job)})


@training_bp.get("/training/jobs/<job_id>/dataset.zip")
def download_training_dataset(job_id: str):
    token_error = _require_worker_token()
    if token_error is not None:
        body, status = token_error
        return jsonify(body), status

    job = db.session.get(TrainingJob, job_id)
    if job is None:
        return jsonify({"message": "job not found"}), 404
    archive_path = get_dataset_archive_path(current_app.config["STORAGE_ROOT"], job.export)
    if job.export.status != "ready" or not archive_path.exists():
        return jsonify({"message": "dataset export is not ready"}), 409
    return send_file(
        archive_path,
        as_attachment=True,
        download_name=f"{job.dataset.name.replace(' ', '-').lower()}-training.zip",
        mimetype="application/zip",
    )


@training_bp.patch("/training/jobs/<job_id>/status")
def update_training_job_status(job_id: str):
    token_error = _require_worker_token()
    if token_error is not None:
        body, status = token_error
        return jsonify(body), status

    job = db.session.get(TrainingJob, job_id)
    if job is None:
        return jsonify({"message": "job not found"}), 404

    payload = TrainingJobStatusSchema().load(request.get_json() or {})
    next_status = payload["status"]
    job.status = next_status
    if payload.get("progress_percent") is not None:
        job.progress_percent = int(payload["progress_percent"])
    elif next_status == "completed":
        job.progress_percent = 100
    if payload.get("metrics"):
        job.metrics_json = {**(job.metrics_json or {}), **payload["metrics"]}
    if payload.get("error"):
        job.error_message = payload["error"]
    if next_status in {"preparing", "running"} and job.started_at is None:
        job.started_at = now_utc()
    if next_status in {"completed", "failed"}:
        job.completed_at = now_utc()
        if job.worker is not None:
            job.worker.current_job_id = None
            job.worker.status = "idle"
    db.session.commit()
    return jsonify({"job": _build_training_job_payload(job)})


@training_bp.post("/training/jobs/<job_id>/artifacts")
def upload_training_artifact(job_id: str):
    token_error = _require_worker_token()
    if token_error is not None:
        body, status = token_error
        return jsonify(body), status

    job = db.session.get(TrainingJob, job_id)
    if job is None:
        return jsonify({"message": "job not found"}), 404

    uploaded: FileStorage | None = request.files.get("artifact")
    if uploaded is None or not uploaded.filename:
        return jsonify({"message": "artifact file is required"}), 400

    artifact_type = request.form.get("artifact_type", "other").strip() or "other"
    filename = secure_filename(uploaded.filename) or f"{artifact_type}.bin"
    output_dir = _artifact_root(job.id)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / filename
    uploaded.save(output_path)

    artifact = TrainingArtifact(
        job_id=job.id,
        artifact_type=artifact_type,
        filename=filename,
        storage_path=str(output_path),
        size_bytes=output_path.stat().st_size,
    )
    db.session.add(artifact)
    db.session.commit()
    return jsonify({"artifact": _build_training_job_payload(job)["artifacts"][-1]}), 201
