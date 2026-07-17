from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from app.extensions import db
from app.models import Dataset, QualityIssue, QualityRun, utcnow
from app.schemas import QualityIssueUpdateSchema, QualityRunCreateSchema
from app.services.outbox_service import enqueue_background_task
from app.services.quality_service import (
    build_quality_issue_payload,
    build_quality_run_payload,
)


quality_bp = Blueprint("quality", __name__)


def _dataset_for_user(dataset_id: str, user_id: str) -> Dataset:
    return Dataset.query.filter_by(id=dataset_id, user_id=user_id).first_or_404()


def _run_for_user(dataset_id: str, run_id: str, user_id: str) -> QualityRun:
    return QualityRun.query.filter_by(
        id=run_id, dataset_id=dataset_id, user_id=user_id
    ).first_or_404()


@quality_bp.post("/<dataset_id>/quality-runs")
@jwt_required()
def create_quality_run(dataset_id: str):
    user_id = get_jwt_identity()
    dataset = _dataset_for_user(dataset_id, user_id)
    payload = QualityRunCreateSchema().load(request.get_json() or {})
    active = QualityRun.query.filter_by(
        dataset_id=dataset.id, run_type="dataset"
    ).filter(QualityRun.status.in_(["queued", "running"])).first()
    if active is not None:
        return jsonify({"message": "该数据集已有质量检查正在运行。"}), 409
    run = QualityRun(
        dataset_id=dataset.id,
        user_id=user_id,
        run_type="dataset",
        status="queued",
        config_json=payload,
    )
    db.session.add(run)
    db.session.flush()
    from app.worker_tasks import analyze_dataset_quality

    enqueue_background_task(analyze_dataset_quality, run.id)
    db.session.commit()
    if current_app.testing and db.session.get(QualityRun, run.id).status == "queued":
        analyze_dataset_quality.apply(args=(run.id,), throw=False)
    run = db.session.get(QualityRun, run.id)
    return jsonify({"qualityRun": build_quality_run_payload(run)}), 202


@quality_bp.get("/<dataset_id>/quality-runs")
@jwt_required()
def list_quality_runs(dataset_id: str):
    user_id = get_jwt_identity()
    _dataset_for_user(dataset_id, user_id)
    runs = (
        QualityRun.query.filter_by(dataset_id=dataset_id, user_id=user_id)
        .order_by(QualityRun.created_at.desc())
        .limit(50)
        .all()
    )
    return jsonify({"qualityRuns": [build_quality_run_payload(run) for run in runs]})


@quality_bp.get("/<dataset_id>/quality-runs/<run_id>")
@jwt_required()
def get_quality_run(dataset_id: str, run_id: str):
    user_id = get_jwt_identity()
    run = _run_for_user(dataset_id, run_id, user_id)
    return jsonify({"qualityRun": build_quality_run_payload(run)})


@quality_bp.get("/<dataset_id>/quality-runs/<run_id>/issues")
@jwt_required()
def list_quality_issues(dataset_id: str, run_id: str):
    user_id = get_jwt_identity()
    run = _run_for_user(dataset_id, run_id, user_id)
    query = QualityIssue.query.filter_by(quality_run_id=run.id)
    if request.args.get("status"):
        query = query.filter_by(status=request.args["status"])
    if request.args.get("issue_type"):
        query = query.filter_by(issue_type=request.args["issue_type"])
    if request.args.get("severity"):
        query = query.filter_by(severity=request.args["severity"])
    limit = min(max(int(request.args.get("limit", 100)), 1), 500)
    offset = max(int(request.args.get("offset", 0)), 0)
    total = query.count()
    issues = query.order_by(QualityIssue.score.desc(), QualityIssue.created_at.asc()).offset(offset).limit(limit).all()
    return jsonify(
        {
            "issues": [build_quality_issue_payload(issue) for issue in issues],
            "total": total,
        }
    )


@quality_bp.patch("/<dataset_id>/quality-issues/<issue_id>")
@jwt_required()
def update_quality_issue(dataset_id: str, issue_id: str):
    user_id = get_jwt_identity()
    _dataset_for_user(dataset_id, user_id)
    payload = QualityIssueUpdateSchema().load(request.get_json() or {})
    issue = (
        QualityIssue.query.join(QualityRun)
        .filter(
            QualityIssue.id == issue_id,
            QualityRun.dataset_id == dataset_id,
            QualityRun.user_id == user_id,
        )
        .first_or_404()
    )
    issue.status = payload["status"]
    issue.resolved_at = utcnow() if issue.status == "resolved" else None
    db.session.commit()
    return jsonify({"issue": build_quality_issue_payload(issue)})
