from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from flask import current_app
from sqlalchemy import func, text

from app.extensions import db
from app.models import Dataset, DatasetExport, DatasetImage, DatasetTask
from app.services.annotation_storage import infer_default_bbox_semantics, load_annotation_result
from app.services.image_storage import existing_generated_image


def now_utc() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _dataset_id(dataset: Dataset | str) -> str:
    return dataset.id if isinstance(dataset, Dataset) else dataset


def next_dataset_ordinal(dataset: Dataset | str) -> int:
    max_ordinal = (
        db.session.query(func.max(DatasetImage.ordinal))
        .filter(DatasetImage.dataset_id == _dataset_id(dataset))
        .scalar()
        or 0
    )
    return int(max_ordinal) + 1


def next_dataset_export_version(dataset: Dataset | str) -> int:
    max_version = (
        db.session.query(func.max(DatasetExport.version))
        .filter(DatasetExport.dataset_id == _dataset_id(dataset))
        .scalar()
        or 0
    )
    return int(max_version) + 1


def sample_pool_split_map(dataset: Dataset) -> dict[str, str]:
    return _selected_split_maps(dataset.id)[0]


def _is_image_annotated(image: DatasetImage) -> bool:
    return image.annotation_status in ("annotated", "empty")


def _image_class_counts(dataset: Dataset) -> dict[str, int]:
    counts: dict[str, int] = {category: 0 for category in (dataset.categories or [])}
    for image in dataset.images:
        for category in image.detection_categories or []:
            if category in counts:
                counts[category] += 1
            else:
                counts[category] = (counts.get(category) or 0) + 1
    return counts


def _image_split_counts(dataset: Dataset, split_map: dict[str, str]) -> dict[str, int]:
    counts = {"train": 0, "val": 0, "test": 0, "unselected": 0}
    for image in dataset.images:
        split = split_map.get(image.id) if image.selected else "unselected"
        key = split or "unselected"
        counts[key] = counts.get(key, 0) + 1
    return counts


def _image_annotation_counts(dataset: Dataset) -> dict[str, int]:
    annotated = sum(1 for image in dataset.images if _is_image_annotated(image))
    return {"annotated": annotated, "unannotated": len(dataset.images) - annotated}


def _filter_dataset_images(
    dataset: Dataset,
    image_filter: dict[str, Any] | None,
    split_map: dict[str, str],
) -> list[DatasetImage]:
    if not image_filter:
        return list(dataset.images)

    class_filter = image_filter.get("class")
    split_filter = image_filter.get("split")
    annotation_filter = image_filter.get("annotation")

    result: list[DatasetImage] = []
    for image in dataset.images:
        if class_filter and class_filter not in (image.detection_categories or []):
            continue
        if split_filter:
            split = split_map.get(image.id) if image.selected else "unselected"
            if (split or "unselected") != split_filter:
                continue
        if annotation_filter:
            is_annotated = _is_image_annotated(image)
            if annotation_filter == "annotated" and not is_annotated:
                continue
            if annotation_filter == "unannotated" and is_annotated:
                continue
        result.append(image)
    return result


def _sample_pool_split_for_selected_count(total: int, index: int) -> str:
    if total <= 1:
        return "train"
    if total <= 3:
        return "train" if index < total - 1 else "val"

    train_cutoff = max(1, int(total * 0.7))
    val_cutoff = min(total, max(train_cutoff + 1, int(total * 0.9)))
    if index < train_cutoff:
        return "train"
    if index < val_cutoff:
        return "val"
    return "test"


def _dataset_base_payload(dataset: Dataset) -> dict[str, Any]:
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
    }


def _selected_split_maps(dataset_id: str) -> tuple[dict[str, str], dict[str, int]]:
    selected_rows = (
        DatasetImage.query.with_entities(DatasetImage.id, DatasetImage.ordinal)
        .filter_by(dataset_id=dataset_id, selected=True)
        .order_by(DatasetImage.ordinal.asc())
        .all()
    )
    total = len(selected_rows)
    split_map: dict[str, str] = {}
    split_counts = {"train": 0, "val": 0, "test": 0, "unselected": 0}
    for index, row in enumerate(selected_rows):
        split = _sample_pool_split_for_selected_count(total, index)
        split_map[row.id] = split
        split_counts[split] += 1
    return split_map, split_counts


def _selected_split_counts(selected_count: int) -> dict[str, int]:
    selected_count = max(0, int(selected_count or 0))
    if selected_count <= 0:
        return {"train": 0, "val": 0, "test": 0}
    if selected_count <= 1:
        return {"train": selected_count, "val": 0, "test": 0}
    if selected_count <= 3:
        return {"train": selected_count - 1, "val": 1, "test": 0}

    train_cutoff = max(1, int(selected_count * 0.7))
    val_cutoff = min(selected_count, max(train_cutoff + 1, int(selected_count * 0.9)))
    return {
        "train": train_cutoff,
        "val": val_cutoff - train_cutoff,
        "test": selected_count - val_cutoff,
    }


def _image_split_counts_for_totals(image_count: int, selected_count: int) -> dict[str, int]:
    counts = _selected_split_counts(selected_count)
    counts["unselected"] = max(0, int(image_count or 0) - int(selected_count or 0))
    return counts


def _selected_rank_bounds(selected_count: int, split: str) -> tuple[int, int]:
    counts = _selected_split_counts(selected_count)
    if split == "train":
        return 1, counts["train"]
    if split == "val":
        return counts["train"] + 1, counts["train"] + counts["val"]
    if split == "test":
        return counts["train"] + counts["val"] + 1, counts["train"] + counts["val"] + counts["test"]
    return 1, 0


def _ranked_selected_images_subquery(dataset_id: str):
    return (
        db.session.query(
            DatasetImage.id.label("id"),
            func.row_number()
            .over(order_by=[DatasetImage.ordinal.asc(), DatasetImage.id.asc()])
            .label("selected_rank"),
        )
        .filter(DatasetImage.dataset_id == dataset_id)
        .filter(DatasetImage.selected.is_(True))
        .subquery()
    )


def _filter_by_sample_split(query, dataset_id: str, split_filter: str, selected_count: int):
    if split_filter == "unselected":
        return query.filter(DatasetImage.selected.is_(False))

    start_rank, end_rank = _selected_rank_bounds(selected_count, split_filter)
    if end_rank < start_rank:
        return query.filter(False)

    ranked_selected = _ranked_selected_images_subquery(dataset_id)
    return (
        query.join(ranked_selected, DatasetImage.id == ranked_selected.c.id)
        .filter(ranked_selected.c.selected_rank >= start_rank)
        .filter(ranked_selected.c.selected_rank <= end_rank)
    )


def sample_pool_split_map_for_images(
    dataset_id: str,
    images: list[DatasetImage],
    *,
    selected_count: int | None = None,
) -> dict[str, str]:
    selected_ids = [image.id for image in images if image.selected]
    if not selected_ids:
        return {}

    if selected_count is None:
        selected_count = (
            db.session.query(func.count(DatasetImage.id))
            .filter(DatasetImage.dataset_id == dataset_id)
            .filter(DatasetImage.selected.is_(True))
            .scalar()
            or 0
        )

    ranked_selected = _ranked_selected_images_subquery(dataset_id)
    rows = (
        db.session.query(ranked_selected.c.id, ranked_selected.c.selected_rank)
        .filter(ranked_selected.c.id.in_(selected_ids))
        .all()
    )
    return {
        row.id: _sample_pool_split_for_selected_count(int(selected_count), int(row.selected_rank) - 1)
        for row in rows
    }


def _image_class_counts_for_dataset(dataset: Dataset) -> dict[str, int]:
    counts: dict[str, int] = {category: 0 for category in (dataset.categories or [])}
    if db.engine.dialect.name == "sqlite":
        rows = db.session.execute(
            text(
                """
                SELECT json_each.value AS category, COUNT(*) AS image_count
                FROM dataset_images, json_each(dataset_images.detection_categories)
                WHERE dataset_images.dataset_id = :dataset_id
                GROUP BY json_each.value
                """
            ),
            {"dataset_id": dataset.id},
        ).all()
        for row in rows:
            category = str(row.category)
            counts[category] = int(row.image_count or 0)
        return counts

    rows = (
        DatasetImage.query.with_entities(DatasetImage.detection_categories)
        .filter_by(dataset_id=dataset.id)
        .all()
    )
    for row in rows:
        for category in row.detection_categories or []:
            if category in counts:
                counts[category] += 1
            else:
                counts[category] = (counts.get(category) or 0) + 1
    return counts


def _image_ids_for_class(dataset_id: str, class_filter: str | None) -> set[str] | None:
    if not class_filter:
        return None
    rows = (
        DatasetImage.query.with_entities(DatasetImage.id, DatasetImage.detection_categories)
        .filter_by(dataset_id=dataset_id)
        .all()
    )
    return {
        row.id
        for row in rows
        if class_filter in (row.detection_categories or [])
    }


def _filter_by_image_class(query, dataset_id: str, class_filter: str | None):
    if not class_filter:
        return query
    if db.engine.dialect.name == "sqlite":
        return query.filter(
            text(
                """
                EXISTS (
                    SELECT 1
                    FROM json_each(dataset_images.detection_categories)
                    WHERE json_each.value = :class_filter
                )
                """
            )
        ).params(class_filter=class_filter)

    class_ids = _image_ids_for_class(dataset_id, class_filter)
    if class_ids is not None:
        return query.filter(DatasetImage.id.in_(class_ids))
    return query


def _annotation_counts_for_dataset(dataset_id: str, image_count: int) -> dict[str, int]:
    annotated = (
        db.session.query(func.count(DatasetImage.id))
        .filter(DatasetImage.dataset_id == dataset_id)
        .filter(DatasetImage.annotation_status.in_(["annotated", "empty"]))
        .scalar()
        or 0
    )
    return {"annotated": int(annotated), "unannotated": max(0, int(image_count or 0) - int(annotated))}


def build_dataset_payload(
    dataset: Dataset,
    *,
    include_images: bool = True,
    include_tasks: bool = True,
    include_exports: bool = True,
    image_filter: dict[str, Any] | None = None,
    images_offset: int = 0,
    images_limit: int | None = None,
) -> dict[str, Any]:
    split_map = sample_pool_split_map(dataset)
    class_counts = _image_class_counts(dataset)
    split_counts = _image_split_counts(dataset, split_map)
    annotation_counts = _image_annotation_counts(dataset)

    selected_original_count = sum(
        1 for image in dataset.images if image.selected and image.status != "augmented"
    )
    unretained_unannotated_count = sum(
        1 for image in dataset.images if not image.selected and not _is_image_annotated(image)
    )

    filtered_images = _filter_dataset_images(dataset, image_filter, split_map)
    filtered_total = len(filtered_images)

    if images_limit is None:
        page_images = filtered_images
    else:
        start = max(0, int(images_offset or 0))
        end = start + max(0, int(images_limit))
        page_images = filtered_images[start:end]

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
        "images": [build_dataset_image_payload(dataset, image, split_map=split_map) for image in page_images] if include_images else [],
        "imagesTotal": filtered_total,
        "imageClassCounts": class_counts,
        "imageSplitCounts": split_counts,
        "imageAnnotationCounts": annotation_counts,
        "selectedOriginalCount": selected_original_count,
        "unretainedUnannotatedImageCount": unretained_unannotated_count,
        "tasks": [build_dataset_task_payload(task) for task in dataset.tasks] if include_tasks else [],
        "exports": [build_dataset_export_payload(export_job) for export_job in dataset.exports]
        if include_exports
        else [],
    }


def build_dataset_detail_payload(
    dataset: Dataset,
    *,
    include_images: bool = True,
    include_tasks: bool = True,
    include_exports: bool = True,
    image_filter: dict[str, Any] | None = None,
    images_offset: int = 0,
    images_limit: int | None = None,
) -> dict[str, Any]:
    image_count = int(dataset.image_count or 0)
    selected_count = int(dataset.selected_count or 0)
    split_counts = _image_split_counts_for_totals(image_count, selected_count)
    class_counts = _image_class_counts_for_dataset(dataset)
    annotation_counts = _annotation_counts_for_dataset(dataset.id, image_count)

    selected_original_count = (
        db.session.query(func.count(DatasetImage.id))
        .filter(DatasetImage.dataset_id == dataset.id)
        .filter(DatasetImage.selected.is_(True))
        .filter(DatasetImage.status != "augmented")
        .scalar()
        or 0
    )
    unretained_unannotated_count = (
        db.session.query(func.count(DatasetImage.id))
        .filter(DatasetImage.dataset_id == dataset.id)
        .filter(DatasetImage.selected.is_(False))
        .filter(~DatasetImage.annotation_status.in_(["annotated", "empty"]))
        .scalar()
        or 0
    )

    filtered_query = DatasetImage.query.filter_by(dataset_id=dataset.id)
    class_filter = (image_filter or {}).get("class") if image_filter else None
    split_filter = (image_filter or {}).get("split") if image_filter else None
    annotation_filter = (image_filter or {}).get("annotation") if image_filter else None

    filtered_query = _filter_by_image_class(filtered_query, dataset.id, class_filter)

    if split_filter:
        filtered_query = _filter_by_sample_split(
            filtered_query,
            dataset.id,
            str(split_filter),
            selected_count,
        )

    if annotation_filter == "annotated":
        filtered_query = filtered_query.filter(DatasetImage.annotation_status.in_(["annotated", "empty"]))
    elif annotation_filter == "unannotated":
        filtered_query = filtered_query.filter(~DatasetImage.annotation_status.in_(["annotated", "empty"]))

    filtered_total = filtered_query.count()
    page_images: list[DatasetImage] = []
    if include_images:
        image_query = filtered_query.order_by(DatasetImage.ordinal.asc())
        if images_limit is None:
            page_images = image_query.all()
        else:
            page_images = (
                image_query.offset(max(0, int(images_offset or 0)))
                .limit(max(0, int(images_limit)))
                .all()
            )

    page_split_map = (
        sample_pool_split_map_for_images(dataset.id, page_images, selected_count=selected_count)
        if include_images
        else {}
    )

    payload = {
        **_dataset_base_payload(dataset),
        "images": [
            build_dataset_image_payload(dataset, image, split_map=page_split_map)
            for image in page_images
        ] if include_images else [],
        "imagesTotal": filtered_total,
        "imageClassCounts": class_counts,
        "imageSplitCounts": split_counts,
        "imageAnnotationCounts": annotation_counts,
        "selectedOriginalCount": int(selected_original_count),
        "unretainedUnannotatedImageCount": int(unretained_unannotated_count),
        "tasks": [],
        "exports": [],
    }
    if include_tasks:
        tasks = DatasetTask.query.filter_by(dataset_id=dataset.id).order_by(DatasetTask.created_at.desc()).all()
        payload["tasks"] = [build_dataset_task_summary_payload(task) for task in tasks]
    if include_exports:
        exports = DatasetExport.query.filter_by(dataset_id=dataset.id).order_by(DatasetExport.version.desc()).all()
        payload["exports"] = [build_dataset_export_payload(export_job) for export_job in exports]
    return payload


def build_dataset_list_item_payload(dataset: Dataset, latest_task: DatasetTask | None = None) -> dict[str, Any]:
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
        "images": [],
        "imagesTotal": int(dataset.image_count or 0),
        "tasks": [],
        "exports": [],
        "latestTask": build_dataset_task_summary_payload(latest_task),
    }


def build_dataset_list_payload(dataset: Dataset, latest_task: DatasetTask | None = None) -> dict[str, Any]:
    return build_dataset_list_item_payload(dataset, latest_task)


def _task_summary_config(config: dict[str, Any]) -> dict[str, Any]:
    summary = {**config}
    if isinstance(summary.get("augmentation"), dict):
        augmentation = {**summary["augmentation"]}
        augmentation.pop("sourceImageIds", None)
        summary["augmentation"] = augmentation
    return summary


def build_dataset_task_summary_payload(task: DatasetTask | None) -> dict[str, Any] | None:
    if task is None:
        return None
    config = task.config_json or {}
    summary_config = _task_summary_config(config)
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
        "config": summary_config,
        "prompt": {},
        "runtime": summary_config.get("runtime", {}),
        "createdAt": task.created_at.isoformat() if task.created_at else None,
        "updatedAt": task.updated_at.isoformat() if task.updated_at else None,
        "startedAt": task.started_at.isoformat() if task.started_at else None,
        "completedAt": task.completed_at.isoformat() if task.completed_at else None,
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


def build_dataset_image_payload(
    dataset: Dataset,
    image: DatasetImage,
    *,
    split_map: dict[str, str] | None = None,
) -> dict[str, Any]:
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
            preview = f"{image_base_url}/{dataset.id}/{image_path.name}?v={image.id}"
        else:
            preview = f"{current_app.config['API_PREFIX']}/datasets/{dataset.id}/images/{image.id}/preview"

    split_value = None
    if split_map is not None:
        split_value = split_map.get(image.id) if image.selected else "unselected"
        split_value = split_value or "unselected"

    payload = {
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
    if split_map is not None:
        payload["split"] = split_value
    return payload


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


def dataset_has_selected_images(dataset_id: str) -> bool:
    return (
        db.session.query(DatasetImage.id)
        .filter(DatasetImage.dataset_id == dataset_id)
        .filter(DatasetImage.selected.is_(True))
        .limit(1)
        .first()
        is not None
    )


def selected_original_image_ids(dataset_id: str) -> list[str]:
    rows = (
        DatasetImage.query.with_entities(DatasetImage.id)
        .filter(DatasetImage.dataset_id == dataset_id)
        .filter(DatasetImage.selected.is_(True))
        .filter(DatasetImage.status != "augmented")
        .order_by(DatasetImage.ordinal.asc(), DatasetImage.id.asc())
        .all()
    )
    return [str(row.id) for row in rows]


def sync_dataset(dataset: Dataset) -> Dataset:
    tasks = DatasetTask.query.filter_by(dataset_id=dataset.id).all()
    for task in tasks:
        sync_dataset_task_stats_from_db(task)

    sync_dataset_stats_from_db(dataset, commit=False)
    db.session.commit()
    db.session.refresh(dataset)
    return dataset


def sync_dataset_stats_from_db(dataset: Dataset, *, commit: bool = True) -> Dataset:
    image_count = (
        db.session.query(func.count(DatasetImage.id))
        .filter(DatasetImage.dataset_id == dataset.id)
        .scalar()
        or 0
    )
    selected_count = (
        db.session.query(func.count(DatasetImage.id))
        .filter(DatasetImage.dataset_id == dataset.id)
        .filter(DatasetImage.selected.is_(True))
        .scalar()
        or 0
    )
    task_count = (
        db.session.query(func.count(DatasetTask.id))
        .filter(DatasetTask.dataset_id == dataset.id)
        .scalar()
        or 0
    )
    spent_cost = round(
        float(
            db.session.query(func.coalesce(func.sum(DatasetTask.spent_cost), 0.0))
            .filter(DatasetTask.dataset_id == dataset.id)
            .scalar()
            or 0.0
        ),
        2,
    )
    has_running_task = (
        db.session.query(func.count(DatasetTask.id))
        .filter(DatasetTask.dataset_id == dataset.id)
        .filter(DatasetTask.status == "running")
        .scalar()
        or 0
    ) > 0
    if has_running_task:
        status = "running"
    elif int(image_count) > 0:
        status = "ready"
    else:
        status = "draft"

    changed = False
    if dataset.image_count != int(image_count):
        dataset.image_count = int(image_count)
        changed = True
    if dataset.selected_count != int(selected_count):
        dataset.selected_count = int(selected_count)
        changed = True
    if dataset.task_count != int(task_count):
        dataset.task_count = int(task_count)
        changed = True
    if dataset.spent_cost != spent_cost:
        dataset.spent_cost = spent_cost
        changed = True
    if dataset.status != status:
        dataset.status = status
        changed = True
    if changed:
        if commit:
            db.session.commit()
            db.session.refresh(dataset)
        else:
            db.session.flush()
    return dataset


def sync_dataset_task_inplace(task: DatasetTask) -> bool:
    config = task.config_json or {}
    generated_images = [image for image in task.images]
    generated_count = len(generated_images)
    selected_count = sum(1 for image in generated_images if image.selected)
    return sync_dataset_task_counts_inplace(task, generated_count=generated_count, selected_count=selected_count)


def sync_dataset_task_stats_from_db(task: DatasetTask) -> bool:
    generated_count = (
        db.session.query(func.count(DatasetImage.id))
        .filter(DatasetImage.source_task_id == task.id)
        .scalar()
        or 0
    )
    selected_count = (
        db.session.query(func.count(DatasetImage.id))
        .filter(DatasetImage.source_task_id == task.id)
        .filter(DatasetImage.selected.is_(True))
        .scalar()
        or 0
    )
    return sync_dataset_task_counts_inplace(
        task,
        generated_count=int(generated_count),
        selected_count=int(selected_count),
    )


def sync_dataset_task_counts_inplace(
    task: DatasetTask,
    *,
    generated_count: int,
    selected_count: int,
) -> bool:
    config = task.config_json or {}
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
