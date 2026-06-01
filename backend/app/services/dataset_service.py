from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from flask import current_app

from app.extensions import db
from app.models import Dataset, DatasetExport, DatasetImage, DatasetTask
from app.services.annotation_storage import infer_default_bbox_semantics, load_annotation_result
from app.services.image_storage import existing_generated_image


def now_utc() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def next_dataset_ordinal(dataset: Dataset) -> int:
    return max((image.ordinal for image in dataset.images), default=0) + 1


def next_dataset_export_version(dataset: Dataset) -> int:
    return max((export.version for export in dataset.exports), default=0) + 1


def build_dataset_payload(
    dataset: Dataset,
    *,
    include_images: bool = True,
    include_tasks: bool = True,
    include_exports: bool = True,
) -> dict[str, Any]:
    return {
        "id": dataset.id,
        "name": dataset.name,
        "description": dataset.description,
        "categories": dataset.categories,
        "status": dataset.status,
        "imageCount": int(dataset.image_count or 0),
        "selectedCount": int(dataset.selected_count or 0),
        "taskCount": int(dataset.task_count or 0),
        "spentCost": float(dataset.spent_cost or 0.0),
        "annotation": dataset.annotation_json or {},
        "createdAt": dataset.created_at.isoformat() if dataset.created_at else None,
        "updatedAt": dataset.updated_at.isoformat() if dataset.updated_at else None,
        "images": [build_dataset_image_payload(dataset, image) for image in dataset.images] if include_images else [],
        "tasks": [build_dataset_task_payload(task) for task in dataset.tasks] if include_tasks else [],
        "exports": [build_dataset_export_payload(export_job) for export_job in dataset.exports]
        if include_exports
        else [],
    }


def build_dataset_list_payload(dataset: Dataset) -> dict[str, Any]:
    latest_task = dataset.tasks[0] if dataset.tasks else None
    return {
        **build_dataset_payload(dataset, include_images=False, include_tasks=False, include_exports=False),
        "latestTask": build_dataset_task_payload(latest_task) if latest_task else None,
    }


def build_dataset_task_payload(task: DatasetTask | None) -> dict[str, Any] | None:
    if task is None:
        return None
    config = task.config_json or {}
    source_images = sorted(task.images, key=lambda image: image.ordinal)
    return {
        "id": task.id,
        "datasetId": task.dataset_id,
        "taskType": task.task_type,
        "taskName": task.task_name,
        "subject": task.subject,
        "categories": task.categories,
        "imageCount": int(task.image_count or 0),
        "imagesGenerated": int(task.images_generated or 0),
        "selectedCount": int(task.selected_count or 0),
        "progressPercent": int(task.progress_percent or 0),
        "status": task.status,
        "estimatedCost": float(task.estimated_cost or 0.0),
        "spentCost": float(task.spent_cost or 0.0),
        "apiProvider": task.api_provider,
        "config": config,
        "prompt": task.prompt_json or {},
        "runtime": config.get("runtime", {}),
        "sourceImageIds": [image.id for image in source_images],
        "createdAt": task.created_at.isoformat() if task.created_at else None,
        "updatedAt": task.updated_at.isoformat() if task.updated_at else None,
        "startedAt": task.started_at.isoformat() if task.started_at else None,
        "completedAt": task.completed_at.isoformat() if task.completed_at else None,
    }


def build_dataset_image_payload(dataset: Dataset, image: DatasetImage) -> dict[str, Any]:
    stored_annotation = (
        load_annotation_result(
            current_app.config["STORAGE_ROOT"],
            dataset.id,
            image.id,
            default_bbox_semantics=infer_default_bbox_semantics(dataset.annotation_json or {}),
        )
        or {}
    )
    detections = stored_annotation.get("detections", [])
    if image.preview_svg.startswith("data:image/svg+xml"):
        preview = image.preview_svg
    else:
        image_base_url = (current_app.config.get("IMAGE_BASE_URL") or "").rstrip("/")
        image_path = existing_generated_image(
            current_app.config["STORAGE_ROOT"], dataset.id, f"image-{image.ordinal:06d}"
        )
        if image_base_url and image_path is not None:
            preview = f"{image_base_url}/{dataset.id}/{image_path.name}"
        else:
            preview = f"{current_app.config['API_PREFIX']}/datasets/{dataset.id}/images/{image.id}/preview"

    return {
        "id": image.id,
        "datasetId": image.dataset_id,
        "sourceTaskId": image.source_task_id,
        "sourceType": image.source_type,
        "sourceOrdinal": image.source_ordinal,
        "ordinal": image.ordinal,
        "status": image.status,
        "latencyMs": image.latency_ms,
        "seed": image.seed,
        "promptText": image.prompt_text,
        "diversityVars": image.diversity_vars,
        "previewSvg": preview,
        "selected": image.selected,
        "annotationStatus": image.annotation_status,
        "confidenceScore": image.confidence_score,
        "source": image.source_type,
        "detections": detections,
    }


def build_dataset_export_payload(export_job: DatasetExport) -> dict[str, Any]:
    return {
        "id": export_job.id,
        "version": export_job.version,
        "status": export_job.status,
        "exportFormat": export_job.export_format,
        "downloadUrl": export_job.download_url,
        "summary": export_job.summary_json,
        "createdAt": export_job.created_at.isoformat() if export_job.created_at else None,
    }


def build_dataset_summary(datasets: list[Dataset]) -> dict[str, Any]:
    total_tasks = sum(int(dataset.task_count or 0) for dataset in datasets)
    total_images = sum(int(dataset.image_count or 0) for dataset in datasets)
    selected_images = sum(int(dataset.selected_count or 0) for dataset in datasets)
    cost_to_date = round(sum(float(dataset.spent_cost or 0.0) for dataset in datasets), 2)
    active_datasets = sum(1 for dataset in datasets if dataset.status == "running")
    return {
        "totalDatasets": len(datasets),
        "activeDatasets": active_datasets,
        "totalTasks": total_tasks,
        "totalImages": total_images,
        "selectedImages": selected_images,
        "costToDate": cost_to_date,
    }


def build_dataset_summary_for_user(user_id: str) -> dict[str, Any]:
    datasets = Dataset.query.filter_by(user_id=user_id).all()
    return build_dataset_summary(datasets)


def sync_dataset(dataset: Dataset) -> Dataset:
    changed = False
    for task in dataset.tasks:
        changed = sync_dataset_task_inplace(task) or changed

    changed = sync_dataset_stats_inplace(dataset) or changed
    if changed:
        db.session.commit()
        db.session.refresh(dataset)
    return dataset


def sync_dataset_task_inplace(task: DatasetTask) -> bool:
    config = task.config_json or {}
    generated_images = [image for image in task.images]
    generated_count = len(generated_images)
    selected_count = sum(1 for image in generated_images if image.selected)
    target_count = max(int(task.image_count or 0), 0)

    changed = False
    if task.images_generated != generated_count:
        task.images_generated = generated_count
        changed = True
    if task.selected_count != selected_count:
        task.selected_count = selected_count
        changed = True

    if task.task_type in {"generation", "augmentation"}:
        progress_percent = 100 if target_count <= 0 else min(100, round(generated_count / max(target_count, 1) * 100))
        spent_cost = _task_spent_cost(task, generated_count, target_count)
        if task.progress_percent != progress_percent:
            task.progress_percent = progress_percent
            changed = True
        if task.spent_cost != spent_cost:
            task.spent_cost = spent_cost
            changed = True
        if target_count > 0 and generated_count >= target_count and task.status == "running":
            task.status = "completed"
            task.completed_at = now_utc()
            changed = True
    elif task.task_type == "import" and config.get("source") == "video":
        if task.status == "running":
            progress_percent = 0 if target_count <= 0 else min(99, round(generated_count / max(target_count, 1) * 100))
            if task.progress_percent != progress_percent:
                task.progress_percent = progress_percent
                changed = True
        elif task.status == "completed" and task.progress_percent != 100:
            task.progress_percent = 100
            changed = True
    elif task.task_type == "import":
        if task.progress_percent != 100:
            task.progress_percent = 100
            changed = True
        if task.status not in {"completed", "failed"}:
            task.status = "completed"
            task.completed_at = task.completed_at or now_utc()
            changed = True

    return changed


def sync_dataset_stats_inplace(dataset: Dataset) -> bool:
    image_count = len(dataset.images)
    selected_count = sum(1 for image in dataset.images if image.selected)
    task_count = len(dataset.tasks)
    spent_cost = round(sum(float(task.spent_cost or 0.0) for task in dataset.tasks), 2)

    if any(task.status == "running" for task in dataset.tasks):
        status = "running"
    elif image_count > 0:
        status = "ready"
    else:
        status = "draft"

    changed = False
    if dataset.image_count != image_count:
        dataset.image_count = image_count
        changed = True
    if dataset.selected_count != selected_count:
        dataset.selected_count = selected_count
        changed = True
    if dataset.task_count != task_count:
        dataset.task_count = task_count
        changed = True
    if dataset.spent_cost != spent_cost:
        dataset.spent_cost = spent_cost
        changed = True
    if dataset.status != status:
        dataset.status = status
        changed = True
    return changed


def _task_spent_cost(task: DatasetTask, generated_count: int, target_count: int) -> float:
    if target_count <= 0:
        return round(float(task.estimated_cost or 0.0), 2)
    ratio = min(generated_count, target_count) / max(target_count, 1)
    return round(float(task.estimated_cost or 0.0) * ratio, 2)
