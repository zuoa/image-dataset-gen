from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import hmac
from pathlib import Path
import secrets
import shutil
from typing import Any

from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required
from sqlalchemy import select
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
from app.services.file_delivery import deliver_local_file
from app.services.dataset_service import (
    build_dataset_export_payload,
    build_dataset_detail_payload,
    dataset_has_selected_images,
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
from app.services.storage_backend import local_backend, register_local_asset
from app.services.idempotency_service import (
    IdempotencyError,
    begin_idempotent_request,
    complete_idempotent_request,
)
from app.services.outbox_service import enqueue_background_task

training_bp = Blueprint("training", __name__)

ACTIVE_JOB_STATUSES = {"assigned", "preparing", "running", "uploading"}
ACTIVE_INFERENCE_STATUSES = {"assigned", "running"}


def _dispatch_background_task(task_callable, *args: object) -> None:
    if not current_app.testing:
        enqueue_background_task(task_callable, *args)
        return
    db.session.commit()
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


def _require_worker_token(
    worker: TrainingWorker | None = None, *, allow_bootstrap: bool = False
) -> tuple[dict[str, str], int] | None:
    expected = str(current_app.config.get("TRAINING_WORKER_TOKEN") or "").strip()
    if not expected:
        return {"message": "training worker token is not configured"}, 503

    supplied = (
        request.headers.get("X-Training-Worker-Token")
        or request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    )
    if allow_bootstrap and hmac.compare_digest(supplied, expected):
        return None
    if worker is not None and worker.token_hash and hmac.compare_digest(
        _assignment_hash(supplied), worker.token_hash
    ):
        return None
    if current_app.testing and hmac.compare_digest(supplied, expected):
        return None
    return {"message": "invalid training worker token"}, 401


def _artifact_root(job_id: str) -> Path:
    return Path(current_app.config["STORAGE_ROOT"]) / "training" / job_id


def _inference_download_url(test_job: TrainingInferenceJob, kind: str) -> str:
    return (
        f"{request.url_root.rstrip('/')}{current_app.config['API_PREFIX']}"
        f"/training/inference-jobs/{test_job.id}/{kind}"
    )


def _build_training_inference_assignment(
    test_job: TrainingInferenceJob, *, assignment_token: str | None = None
) -> dict[str, Any]:
    payload = build_training_inference_payload(test_job)
    payload.update(
        {
            "modelDownloadUrl": _inference_download_url(test_job, "model"),
            "imageDownloadUrl": _inference_download_url(test_job, "image"),
            "categories": test_job.training_job.dataset.categories if test_job.training_job and test_job.training_job.dataset else [],
        }
    )
    if assignment_token:
        payload["assignmentToken"] = assignment_token
        payload["leaseExpiresAt"] = (
            test_job.lease_expires_at.isoformat() if test_job.lease_expires_at else None
        )
    return payload


def _artifact_download_url(job: TrainingJob, artifact: TrainingArtifact) -> str:
    return (
        f"{current_app.config['API_PREFIX']}/datasets/{job.dataset_id}/training-jobs/"
        f"{job.id}/artifacts/{artifact.id}/download"
    )


def _build_worker_payload(
    worker: TrainingWorker, *, observed_at: datetime | None = None
) -> dict[str, Any]:
    heartbeat_age_seconds: int | None = None
    is_online = False
    if worker.last_heartbeat_at is not None:
        heartbeat_age_seconds = max(
            0,
            int(((observed_at or now_utc()) - _as_utc(worker.last_heartbeat_at)).total_seconds()),
        )
        is_online = heartbeat_age_seconds <= int(
            current_app.config["TRAINING_WORKER_OFFLINE_SECONDS"]
        )
    return {
        "id": worker.id,
        "name": worker.name,
        "status": worker.status,
        "isOnline": is_online,
        "heartbeatAgeSeconds": heartbeat_age_seconds,
        "capabilities": worker.capabilities_json or {},
        "version": worker.version,
        "currentJobId": worker.current_job_id,
        "lastHeartbeatAt": worker.last_heartbeat_at.isoformat() if worker.last_heartbeat_at else None,
        "createdAt": worker.created_at.isoformat() if worker.created_at else None,
        "updatedAt": worker.updated_at.isoformat() if worker.updated_at else None,
    }


def _build_training_job_payload(
    job: TrainingJob,
    *,
    include_assignment: bool = False,
    assignment_token: str | None = None,
) -> dict[str, Any]:
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
        if assignment_token:
            payload["assignmentToken"] = assignment_token
            payload["leaseExpiresAt"] = job.lease_expires_at.isoformat() if job.lease_expires_at else None
    return payload


def _assignment_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _lease_deadline() -> datetime:
    return now_utc() + timedelta(seconds=int(current_app.config["TRAINING_JOB_LEASE_SECONDS"]))


def _issue_assignment(record: TrainingJob | TrainingInferenceJob) -> str:
    token = secrets.token_urlsafe(32)
    record.assignment_token_hash = _assignment_hash(token)
    record.lease_expires_at = _lease_deadline()
    record.attempt_count = int(record.attempt_count or 0) + 1
    return token


def _assignment_error(
    record: TrainingJob | TrainingInferenceJob,
    *,
    worker_id: str | None = None,
) -> tuple[dict[str, str], int] | None:
    if worker_id is not None and record.worker_id != worker_id:
        return {"message": "assignment does not belong to this worker"}, 409
    supplied = request.headers.get("X-Assignment-Token", "")
    if current_app.testing and not supplied:
        return None
    if not supplied or not record.assignment_token_hash or not hmac.compare_digest(
        _assignment_hash(supplied), record.assignment_token_hash
    ):
        return {"message": "invalid assignment token"}, 401
    if record.lease_expires_at is None or _as_utc(record.lease_expires_at) <= now_utc():
        return {"message": "assignment lease expired"}, 409
    return None


def _requeue_expired_assignments() -> None:
    now = now_utc()
    expired_jobs = db.session.execute(
        select(TrainingJob)
        .where(TrainingJob.status.in_(ACTIVE_JOB_STATUSES))
        .where(TrainingJob.lease_expires_at.is_not(None))
        .where(TrainingJob.lease_expires_at <= now)
        .with_for_update(skip_locked=True)
    ).scalars()
    for job in expired_jobs:
        if job.worker is not None and job.worker.current_job_id == job.id:
            job.worker.current_job_id = None
            job.worker.status = "idle"
        job.status = "queued"
        job.worker_id = None
        job.assignment_token_hash = ""
        job.lease_expires_at = None

    expired_tests = db.session.execute(
        select(TrainingInferenceJob)
        .where(TrainingInferenceJob.status.in_(ACTIVE_INFERENCE_STATUSES))
        .where(TrainingInferenceJob.lease_expires_at.is_not(None))
        .where(TrainingInferenceJob.lease_expires_at <= now)
        .with_for_update(skip_locked=True)
    ).scalars()
    for test_job in expired_tests:
        if test_job.worker is not None:
            test_job.worker.status = "idle"
        test_job.status = "queued"
        test_job.worker_id = None
        test_job.assignment_token_hash = ""
        test_job.lease_expires_at = None


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
    db.session.flush()
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
    if not dataset_has_selected_images(dataset.id):
        return jsonify({"message": "no images selected for training"}), 400
    classes = sorted(dict.fromkeys(int(index) for index in payload["classes"]))
    invalid_classes = [index for index in classes if index >= len(dataset.categories)]
    if invalid_classes:
        return jsonify({"message": "training classes contain indexes outside dataset categories"}), 400
    try:
        idempotency, replay = begin_idempotent_request(
            user_id, f"datasets.{dataset_id}.training-jobs.create", payload
        )
    except IdempotencyError as exc:
        return jsonify({"message": str(exc)}), exc.status_code
    if replay is not None:
        return jsonify(replay.body), replay.status_code

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
    db.session.flush()
    response_body = {
        "job": _build_training_job_payload(job),
        "dataset": build_dataset_detail_payload(dataset, include_images=False),
    }
    complete_idempotent_request(idempotency, response_body, 201)
    db.session.commit()
    return jsonify(response_body), 201


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
    return deliver_local_file(
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
        test_job = create_training_inference_job(
            job,
            image_bytes,
            filename=uploaded.filename,
            artifact_id=(request.form.get("artifact_id") or "").strip(),
            confidence_threshold=confidence_threshold,
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
    return jsonify({
        "deletedJobId": deleted_job_id,
        "dataset": build_dataset_detail_payload(sync_dataset(dataset), include_images=False),
    })


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


@training_bp.get("/training/workers")
@jwt_required()
def list_training_workers():
    observed_at = now_utc()
    workers = TrainingWorker.query.order_by(
        TrainingWorker.last_heartbeat_at.desc(), TrainingWorker.name.asc()
    ).all()
    payloads = [_build_worker_payload(worker, observed_at=observed_at) for worker in workers]
    online_count = sum(1 for worker in payloads if worker["isOnline"])
    busy_count = sum(
        1 for worker in payloads if worker["isOnline"] and worker["status"] == "busy"
    )
    return jsonify(
        {
            "workers": payloads,
            "summary": {
                "total": len(payloads),
                "online": online_count,
                "idle": online_count - busy_count,
                "busy": busy_count,
                "offline": len(payloads) - online_count,
            },
            "offlineAfterSeconds": int(
                current_app.config["TRAINING_WORKER_OFFLINE_SECONDS"]
            ),
            "observedAt": observed_at.isoformat(),
        }
    )


@training_bp.post("/training/workers/register")
def register_training_worker():
    token_error = _require_worker_token(allow_bootstrap=True)
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
    worker_token = secrets.token_urlsafe(48)
    worker.token_hash = _assignment_hash(worker_token)
    worker.token_scopes = ["training", "inference"]
    worker.status = "idle"
    worker.last_heartbeat_at = now_utc()
    db.session.commit()
    return jsonify({"worker": _build_worker_payload(worker), "workerToken": worker_token})


@training_bp.post("/training/workers/<worker_id>/heartbeat")
def heartbeat_training_worker(worker_id: str):
    worker = db.session.get(TrainingWorker, worker_id)
    if worker is None:
        return jsonify({"message": "worker not registered"}), 404
    token_error = _require_worker_token(worker)
    if token_error is not None:
        body, status = token_error
        return jsonify(body), status

    payload = TrainingWorkerHeartbeatSchema().load(request.get_json() or {})
    worker.last_heartbeat_at = now_utc()
    reported_job_id = (payload.get("current_job_id") or "").strip()
    if reported_job_id:
        worker.current_job_id = reported_job_id
        active_job = db.session.get(TrainingJob, reported_job_id)
        if active_job is not None and active_job.worker_id == worker.id:
            assignment_error = _assignment_error(active_job, worker_id=worker.id)
            if assignment_error is not None:
                body, status = assignment_error
                return jsonify(body), status
            active_job.last_heartbeat_at = now_utc()
            active_job.lease_expires_at = _lease_deadline()
    worker.status = "busy" if worker.current_job_id else payload["status"]
    db.session.commit()
    return jsonify({"worker": _build_worker_payload(worker)})


@training_bp.post("/training/workers/<worker_id>/poll")
def poll_training_job(worker_id: str):
    worker = db.session.execute(
        select(TrainingWorker).where(TrainingWorker.id == worker_id).with_for_update()
    ).scalar_one_or_none()
    if worker is None:
        return jsonify({"message": "worker not registered"}), 404
    token_error = _require_worker_token(worker)
    if token_error is not None:
        body, status = token_error
        return jsonify(body), status

    worker.last_heartbeat_at = now_utc()
    _requeue_expired_assignments()
    if worker.current_job_id:
        active_job = db.session.get(TrainingJob, worker.current_job_id)
        if active_job is not None and active_job.status in ACTIVE_JOB_STATUSES:
            assignment_token = _issue_assignment(active_job)
            worker.status = "busy"
            db.session.commit()
            return jsonify({
                "job": _build_training_job_payload(
                    active_job, include_assignment=True, assignment_token=assignment_token
                )
            })
        worker.current_job_id = None

    queued_jobs = db.session.execute(
        select(TrainingJob)
        .where(TrainingJob.status == "queued")
        .order_by(TrainingJob.created_at.asc())
        .limit(50)
        .with_for_update(skip_locked=True)
    ).scalars()
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
        assignment_token = _issue_assignment(job)
        worker.current_job_id = job.id
        worker.status = "busy"
        db.session.commit()
        return jsonify({
            "job": _build_training_job_payload(
                job, include_assignment=True, assignment_token=assignment_token
            )
        })

    worker.status = "idle"
    db.session.commit()
    return jsonify({"job": None})


@training_bp.post("/training/workers/<worker_id>/inference/poll")
def poll_training_inference_job(worker_id: str):
    worker = db.session.execute(
        select(TrainingWorker).where(TrainingWorker.id == worker_id).with_for_update()
    ).scalar_one_or_none()
    if worker is None:
        return jsonify({"message": "worker not registered"}), 404
    token_error = _require_worker_token(worker)
    if token_error is not None:
        body, status = token_error
        return jsonify(body), status

    worker.last_heartbeat_at = now_utc()
    _requeue_expired_assignments()
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
        assignment_token = _issue_assignment(active_test)
        worker.status = "busy"
        db.session.commit()
        return jsonify({
            "test": _build_training_inference_assignment(
                active_test, assignment_token=assignment_token
            )
        })

    queued_test = db.session.execute(
        select(TrainingInferenceJob)
        .where(TrainingInferenceJob.status == "queued")
        .order_by(TrainingInferenceJob.created_at.asc())
        .limit(1)
        .with_for_update(skip_locked=True)
    ).scalar_one_or_none()
    if queued_test is None:
        worker.status = "idle"
        db.session.commit()
        return jsonify({"test": None})

    queued_test.status = "assigned"
    queued_test.worker_id = worker.id
    assignment_token = _issue_assignment(queued_test)
    worker.status = "busy"
    db.session.commit()
    return jsonify({
        "test": _build_training_inference_assignment(
            queued_test, assignment_token=assignment_token
        )
    })


@training_bp.get("/training/inference-jobs/<test_id>/model")
def download_training_inference_model(test_id: str):
    test_job = db.session.get(TrainingInferenceJob, test_id)
    if test_job is None:
        return jsonify({"message": "test job not found"}), 404
    token_error = _require_worker_token(test_job.worker)
    if token_error is not None:
        body, status = token_error
        return jsonify(body), status
    assignment_error = _assignment_error(test_job)
    if assignment_error is not None:
        body, status = assignment_error
        return jsonify(body), status
    artifact = test_job.artifact
    if artifact is None:
        return jsonify({"message": "model artifact not found"}), 404
    artifact_path = Path(artifact.storage_path)
    if not artifact_path.exists():
        return jsonify({"message": "model artifact file not found"}), 409
    return deliver_local_file(
        artifact_path,
        as_attachment=True,
        download_name=artifact.filename,
        mimetype="application/octet-stream",
    )


@training_bp.get("/training/inference-jobs/<test_id>/image")
def download_training_inference_image(test_id: str):
    test_job = db.session.get(TrainingInferenceJob, test_id)
    if test_job is None:
        return jsonify({"message": "test job not found"}), 404
    token_error = _require_worker_token(test_job.worker)
    if token_error is not None:
        body, status = token_error
        return jsonify(body), status
    assignment_error = _assignment_error(test_job)
    if assignment_error is not None:
        body, status = assignment_error
        return jsonify(body), status
    input_path = Path(test_job.input_storage_path)
    if not input_path.exists():
        return jsonify({"message": "test image file not found"}), 409
    return deliver_local_file(
        input_path,
        as_attachment=True,
        download_name=test_job.input_filename or input_path.name,
        mimetype=test_job.input_mime_type,
    )


@training_bp.patch("/training/workers/<worker_id>/inference-jobs/<test_id>/status")
def update_training_inference_job_status(worker_id: str, test_id: str):
    worker = db.session.get(TrainingWorker, worker_id)
    if worker is None:
        return jsonify({"message": "worker not registered"}), 404
    token_error = _require_worker_token(worker)
    if token_error is not None:
        body, status = token_error
        return jsonify(body), status
    test_job = db.session.get(TrainingInferenceJob, test_id)
    if test_job is None:
        return jsonify({"message": "test job not found"}), 404
    assignment_error = _assignment_error(test_job, worker_id=worker.id)
    if assignment_error is not None:
        body, status = assignment_error
        return jsonify(body), status

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
        test_job.lease_expires_at = _lease_deadline()
    elif next_status == "completed":
        try:
            complete_training_inference_job(test_job, payload.get("detections") or [])
        except TrainingInferenceError as exc:
            return jsonify({"message": str(exc)}), exc.status_code
        worker.status = "idle"
        test_job.assignment_token_hash = ""
        test_job.lease_expires_at = None
    elif next_status == "failed":
        fail_training_inference_job(test_job, str(payload.get("error") or "prediction_failed"))
        worker.status = "idle"
        test_job.assignment_token_hash = ""
        test_job.lease_expires_at = None

    db.session.commit()
    return jsonify({"test": build_training_inference_payload(test_job)})


@training_bp.get("/training/jobs/<job_id>/dataset.zip")
def download_training_dataset(job_id: str):
    job = db.session.get(TrainingJob, job_id)
    if job is None:
        return jsonify({"message": "job not found"}), 404
    token_error = _require_worker_token(job.worker)
    if token_error is not None:
        body, status = token_error
        return jsonify(body), status
    assignment_error = _assignment_error(job)
    if assignment_error is not None:
        body, status = assignment_error
        return jsonify(body), status
    archive_path = get_dataset_archive_path(current_app.config["STORAGE_ROOT"], job.export)
    if job.export.status != "ready" or not archive_path.exists():
        return jsonify({"message": "dataset export is not ready"}), 409
    return deliver_local_file(
        archive_path,
        as_attachment=True,
        download_name=f"{job.dataset.name.replace(' ', '-').lower()}-training.zip",
        mimetype="application/zip",
    )


@training_bp.patch("/training/jobs/<job_id>/status")
def update_training_job_status(job_id: str):
    job = db.session.get(TrainingJob, job_id)
    if job is None:
        return jsonify({"message": "job not found"}), 404
    token_error = _require_worker_token(job.worker)
    if token_error is not None:
        body, status = token_error
        return jsonify(body), status
    assignment_error = _assignment_error(job)
    if assignment_error is not None:
        body, status = assignment_error
        return jsonify(body), status

    payload = TrainingJobStatusSchema().load(request.get_json() or {})
    next_status = payload["status"]
    valid_transitions = {
        "assigned": {"preparing", "running", "failed"},
        "preparing": {"preparing", "running", "failed"},
        "running": {"running", "uploading", "completed", "failed"},
        "uploading": {"uploading", "completed", "failed"},
    }
    is_test_shortcut = current_app.testing and job.status == "queued" and next_status == "completed"
    if not is_test_shortcut and next_status not in valid_transitions.get(job.status, set()):
        return jsonify({"message": f"invalid training status transition: {job.status} -> {next_status}"}), 409
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
    if next_status in ACTIVE_JOB_STATUSES:
        job.last_heartbeat_at = now_utc()
        job.lease_expires_at = _lease_deadline()
    if next_status in {"completed", "failed"}:
        job.completed_at = now_utc()
        job.assignment_token_hash = ""
        job.lease_expires_at = None
        if job.worker is not None:
            job.worker.current_job_id = None
            job.worker.status = "idle"
    if next_status == "completed":
        from app.services.training_evaluation_service import ingest_training_evaluation

        ingest_training_evaluation(job)
    db.session.commit()
    return jsonify({"job": _build_training_job_payload(job)})


@training_bp.post("/training/jobs/<job_id>/artifacts")
def upload_training_artifact(job_id: str):
    job = db.session.get(TrainingJob, job_id)
    if job is None:
        return jsonify({"message": "job not found"}), 404
    token_error = _require_worker_token(job.worker)
    if token_error is not None:
        body, status = token_error
        return jsonify(body), status
    assignment_error = _assignment_error(job)
    if assignment_error is not None:
        body, status = assignment_error
        return jsonify(body), status

    uploaded: FileStorage | None = request.files.get("artifact")
    if uploaded is None or not uploaded.filename:
        return jsonify({"message": "artifact file is required"}), 400

    artifact_type = request.form.get("artifact_type", "other").strip() or "other"
    filename = secure_filename(uploaded.filename) or f"{artifact_type}.bin"
    stored = local_backend(current_app.config["STORAGE_ROOT"]).put_stream(
        f"training/{job.id}/artifacts/{filename}", uploaded.stream
    )
    output_path = stored.path

    asset = register_local_asset(
        current_app.config["STORAGE_ROOT"],
        output_path,
        user_id=job.user_id,
        dataset_id=job.dataset_id,
        kind="training_artifact",
        mime_type=uploaded.mimetype or "application/octet-stream",
        original_filename=filename,
    )
    artifact = TrainingArtifact.query.filter_by(job_id=job.id, artifact_type=artifact_type).first()
    created = artifact is None
    if artifact is None:
        artifact = TrainingArtifact(job_id=job.id, artifact_type=artifact_type)
        db.session.add(artifact)
    artifact.filename = filename
    artifact.storage_path = str(output_path)
    artifact.size_bytes = output_path.stat().st_size
    artifact.asset = asset
    job.lease_expires_at = _lease_deadline()
    db.session.commit()
    artifact_payload = next(
        item for item in _build_training_job_payload(job)["artifacts"] if item["id"] == artifact.id
    )
    return jsonify({"artifact": artifact_payload}), 201 if created else 200
