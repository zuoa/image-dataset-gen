from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from flask import current_app
from PIL import Image, UnidentifiedImageError

from app.extensions import db
from app.models import AnnotationRevision, DatasetImage, QualityIssue, QualityRun, utcnow
from app.services.annotation_storage import load_annotation_result
from app.services.dataset_service import sample_pool_split_map_for_images
from app.services.storage_backend import resolve_asset_path
from app.services.supervision_adapter import (
    detections_from_records,
    pairwise_iou,
    supervision_version,
)


ANNOTATION_ISSUE_TYPES = {
    "missing_annotation",
    "empty_annotation",
    "out_of_bounds_box",
    "tiny_box",
    "large_box",
    "extreme_aspect_ratio",
    "duplicate_box",
    "false_positive",
    "false_negative",
    "class_confusion",
    "low_iou",
}


def build_quality_run_payload(run: QualityRun, *, include_issues: bool = False) -> dict[str, Any]:
    counts = Counter(issue.status for issue in run.issues)
    payload = {
        "id": run.id,
        "datasetId": run.dataset_id,
        "trainingJobId": run.training_job_id,
        "exportId": run.export_id,
        "runType": run.run_type,
        "status": run.status,
        "config": run.config_json or {},
        "summary": run.summary_json or {},
        "supervisionVersion": run.supervision_version,
        "error": run.error_message,
        "issueCounts": {
            "total": len(run.issues),
            "open": counts.get("open", 0),
            "resolved": counts.get("resolved", 0),
            "dismissed": counts.get("dismissed", 0),
        },
        "createdAt": run.created_at.isoformat() if run.created_at else None,
        "startedAt": run.started_at.isoformat() if run.started_at else None,
        "completedAt": run.completed_at.isoformat() if run.completed_at else None,
    }
    if include_issues:
        payload["issues"] = [build_quality_issue_payload(issue) for issue in run.issues]
    return payload


def build_quality_issue_payload(issue: QualityIssue) -> dict[str, Any]:
    payload = {
        "id": issue.id,
        "qualityRunId": issue.quality_run_id,
        "imageId": issue.image_id,
        "annotationRevisionId": issue.annotation_revision_id,
        "issueType": issue.issue_type,
        "severity": issue.severity,
        "score": issue.score,
        "status": issue.status,
        "details": issue.details_json or {},
        "resolvedAt": issue.resolved_at.isoformat() if issue.resolved_at else None,
        "createdAt": issue.created_at.isoformat() if issue.created_at else None,
    }
    if issue.image is not None:
        payload["image"] = {
            "id": issue.image.id,
            "ordinal": issue.image.ordinal,
            "annotationStatus": issue.image.annotation_status,
        }
    return payload


def run_dataset_quality_analysis(run: QualityRun) -> dict[str, Any]:
    dataset = run.dataset
    images = (
        DatasetImage.query.filter_by(dataset_id=dataset.id, selected=True)
        .order_by(DatasetImage.ordinal.asc())
        .all()
    )
    categories = list(dataset.categories or [])
    config = run.config_json or {}
    duplicate_iou_threshold = max(0.9, float(config.get("iouThreshold", 0.5)))
    class_counts: Counter[str] = Counter()
    issues: list[QualityIssue] = []
    issues_by_type: Counter[str] = Counter()
    issues_by_severity: Counter[str] = Counter()
    hashes: defaultdict[str, list[DatasetImage]] = defaultdict(list)

    current_revisions = {
        revision.image_id: revision
        for revision in AnnotationRevision.query.filter(
            AnnotationRevision.image_id.in_([image.id for image in images]),
            AnnotationRevision.is_current.is_(True),
        ).all()
    }

    def add_issue(
        image: DatasetImage,
        issue_type: str,
        severity: str,
        score: float,
        details: dict[str, Any] | None = None,
        *,
        revision: AnnotationRevision | None = None,
    ) -> None:
        issue = QualityIssue(
            run=run,
            image_id=image.id,
            annotation_revision_id=revision.id if revision else None,
            issue_type=issue_type,
            severity=severity,
            score=min(max(float(score), 0.0), 1.0),
            status="open",
            details_json=details or {},
        )
        issues.append(issue)
        db.session.add(issue)
        issues_by_type[issue_type] += 1
        issues_by_severity[severity] += 1

    for image in images:
        revision = current_revisions.get(image.id)
        if image.asset and image.asset.sha256:
            hashes[image.asset.sha256].append(image)
        if image.asset is None:
            add_issue(image, "missing_image_asset", "error", 1.0)
        else:
            try:
                asset_path = resolve_asset_path(
                    current_app.config["STORAGE_ROOT"], image.asset
                )
                with Image.open(asset_path) as stored_image:
                    stored_image.verify()
            except (FileNotFoundError, OSError, UnidentifiedImageError):
                add_issue(
                    image,
                    "corrupt_image_asset",
                    "error",
                    1.0,
                    {"assetId": image.asset.id},
                )
        stored = load_annotation_result(
            current_app.config["STORAGE_ROOT"], dataset.id, image.id
        )
        if stored is None:
            add_issue(image, "missing_annotation", "error", 1.0)
            continue
        records = list(stored.get("detections", []))
        if not records:
            add_issue(image, "empty_annotation", "info", 0.25, revision=revision)
            continue

        for index, detection in enumerate(records):
            category = str(detection.get("category") or "")
            if category:
                class_counts[category] += 1
            bbox = detection.get("bbox") or []
            if len(bbox) != 4:
                continue
            x_center, y_center, width, height = [float(value) for value in bbox]
            area = width * height
            box_details = {"detectionIndex": index, "category": category, "bbox": bbox}
            if (
                x_center - width / 2 < 0
                or y_center - height / 2 < 0
                or x_center + width / 2 > 1
                or y_center + height / 2 > 1
            ):
                add_issue(image, "out_of_bounds_box", "error", 0.9, box_details, revision=revision)
            if area < 0.0025:
                add_issue(image, "tiny_box", "warning", 0.7, {**box_details, "area": area}, revision=revision)
            elif area > 0.8:
                add_issue(image, "large_box", "warning", 0.65, {**box_details, "area": area}, revision=revision)
            aspect_ratio = max(width / height, height / width) if width > 0 and height > 0 else 999
            if aspect_ratio > 10:
                add_issue(
                    image,
                    "extreme_aspect_ratio",
                    "warning",
                    0.65,
                    {**box_details, "aspectRatio": round(aspect_ratio, 3)},
                    revision=revision,
                )

        detections = detections_from_records(records, categories, (1000, 1000))
        iou_matrix = pairwise_iou(detections)
        for left_index in range(len(detections)):
            for right_index in range(left_index + 1, len(detections)):
                if (
                    detections.class_id[left_index] == detections.class_id[right_index]
                    and iou_matrix[left_index, right_index] >= duplicate_iou_threshold
                ):
                    add_issue(
                        image,
                        "duplicate_box",
                        "warning",
                        float(iou_matrix[left_index, right_index]),
                        {
                            "detectionIndexes": [left_index, right_index],
                            "iou": round(float(iou_matrix[left_index, right_index]), 4),
                        },
                        revision=revision,
                    )

    for duplicate_images in hashes.values():
        if len(duplicate_images) < 2:
            continue
        original = duplicate_images[0]
        for duplicate in duplicate_images[1:]:
            add_issue(
                duplicate,
                "exact_duplicate_image",
                "warning",
                0.85,
                {"duplicateOfImageId": original.id},
            )

    split_map = sample_pool_split_map_for_images(
        dataset.id, images, selected_count=len(images)
    )
    split_class_counts: dict[str, Counter[str]] = {
        "train": Counter(),
        "val": Counter(),
        "test": Counter(),
    }
    for image in images:
        split = split_map.get(image.id)
        if split in split_class_counts:
            for category in image.detection_categories or []:
                split_class_counts[split][str(category)] += 1

    total_objects = sum(class_counts.values())
    class_shares = {
        category: round(class_counts.get(category, 0) / total_objects, 4)
        if total_objects
        else 0
        for category in categories
    }
    missing_by_split = {
        split: [category for category in categories if counts.get(category, 0) == 0]
        for split, counts in split_class_counts.items()
        if any(split_map.get(image.id) == split for image in images)
    }
    weighted = (
        issues_by_severity.get("error", 0) * 1.0
        + issues_by_severity.get("warning", 0) * 0.5
        + issues_by_severity.get("info", 0) * 0.1
    )
    quality_score = round(max(0.0, 100.0 - weighted / max(len(images), 1) * 20), 1)
    return {
        "qualityScore": quality_score,
        "imageCount": len(images),
        "objectCount": total_objects,
        "issueCount": len(issues),
        "issuesByType": dict(sorted(issues_by_type.items())),
        "issuesBySeverity": dict(sorted(issues_by_severity.items())),
        "classCounts": {category: class_counts.get(category, 0) for category in categories},
        "classShares": class_shares,
        "missingClassesBySplit": missing_by_split,
    }


def resolve_annotation_quality_issues(image_id: str) -> None:
    QualityIssue.query.filter(
        QualityIssue.image_id == image_id,
        QualityIssue.status == "open",
        QualityIssue.issue_type.in_(ANNOTATION_ISSUE_TYPES),
    ).update(
        {"status": "resolved", "resolved_at": utcnow()},
        synchronize_session=False,
    )
