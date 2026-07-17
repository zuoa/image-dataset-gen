from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.extensions import db
from app.models import (
    AnnotationRevision,
    DatasetImage,
    QualityIssue,
    QualityRun,
    TrainingArtifact,
    TrainingJob,
    utcnow,
)


MAX_EVALUATION_REPORT_BYTES = 25 * 1024 * 1024


def ingest_training_evaluation(job: TrainingJob) -> QualityRun | None:
    existing = QualityRun.query.filter_by(
        training_job_id=job.id, run_type="model"
    ).first()
    if existing is not None:
        return existing
    artifact = TrainingArtifact.query.filter_by(
        job_id=job.id, artifact_type="evaluation_report"
    ).first()
    if artifact is None:
        return None
    path = Path(artifact.storage_path)
    if not path.is_file() or path.stat().st_size > MAX_EVALUATION_REPORT_BYTES:
        return None
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(report, dict) or int(report.get("schemaVersion", 0)) != 1:
        return None

    issues_payload = report.get("issues") if isinstance(report.get("issues"), list) else []
    run = QualityRun(
        dataset_id=job.dataset_id,
        user_id=job.user_id,
        training_job_id=job.id,
        export_id=job.export_id,
        run_type="model",
        status="completed",
        config_json=report.get("config") if isinstance(report.get("config"), dict) else {},
        summary_json={
            "metrics": report.get("metrics") or {},
            "perClass": report.get("perClass") or [],
            "confusionMatrix": report.get("confusionMatrix") or [],
            "confusionMatrixLabels": report.get("confusionMatrixLabels") or [],
            "split": report.get("split") or "val",
            "issueCount": len(issues_payload),
        },
        supervision_version=str(report.get("supervisionVersion") or ""),
        started_at=job.completed_at or utcnow(),
        completed_at=job.completed_at or utcnow(),
        attempt_count=1,
    )
    db.session.add(run)
    db.session.flush()

    image_ids = {
        str(item.get("imageId"))
        for item in issues_payload
        if isinstance(item, dict) and item.get("imageId")
    }
    valid_image_ids = {
        row.id
        for row in DatasetImage.query.filter(
            DatasetImage.dataset_id == job.dataset_id,
            DatasetImage.id.in_(image_ids),
        ).all()
    }
    revisions_by_key = {
        (revision.image_id, revision.revision): revision
        for revision in AnnotationRevision.query.filter(
            AnnotationRevision.image_id.in_(valid_image_ids)
        ).all()
    }
    for item in issues_payload:
        if not isinstance(item, dict):
            continue
        image_id = str(item.get("imageId") or "")
        if image_id not in valid_image_ids:
            continue
        try:
            revision_number = int(item.get("annotationRevision"))
        except (TypeError, ValueError):
            revision_number = 0
        revision = revisions_by_key.get((image_id, revision_number))
        db.session.add(
            QualityIssue(
                run=run,
                image_id=image_id,
                annotation_revision_id=revision.id if revision else None,
                issue_type=str(item.get("issueType") or "model_error")[:48],
                severity=str(item.get("severity") or "warning")[:16],
                score=min(max(float(item.get("score") or 0.5), 0.0), 1.0),
                status="open",
                details_json=item.get("details") if isinstance(item.get("details"), dict) else {},
            )
        )
    return run
