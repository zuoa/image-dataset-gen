from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
import hashlib
from pathlib import Path
import secrets

from billiard.exceptions import SoftTimeLimitExceeded
from flask import current_app
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, OperationalError

from app.clients.gemini_client import (
    GeminiGenerationError,
    generate_image as generate_gemini_image,
    normalize_aspect_ratio,
    pixel_size_for_aspect_ratio,
)
from app.clients.jimeng_client import JimengGenerationError, generate_image as generate_jimeng_image
from app.extensions import celery, db
from app.models import (
    Dataset,
    DatasetExport,
    DatasetImage,
    DatasetTask,
    ExternalConnection,
    QualityRun,
    TaskItem,
    generate_uuid,
)
from app.services.annotation_storage import (
    extract_detection_categories,
    infer_default_bbox_semantics,
    load_annotation_result,
    save_annotation_result,
    transform_detections_for_augmentation,
)
from app.services.dataset_service import (
    next_dataset_ordinal,
    now_utc,
    sync_dataset_stats_from_db,
    sync_dataset_stats_inplace,
    sync_dataset_task_stats_from_db,
    sync_dataset_task_inplace,
)
from app.services.image_storage import augment_generated_image, preview_data_url, save_generated_image
from app.services.storage_backend import register_local_asset
from app.services.external_connection_service import connection_secret
from app.services.outbox_service import enqueue_background_task
from app.services.video_import_service import (
    DEFAULT_VIDEO_FRAME_INTERVAL,
    DEFAULT_VIDEO_FRAME_INTERVAL_MODE,
    DEFAULT_VIDEO_FRAME_INTERVAL_SECONDS,
    cleanup_video_import_source,
    expected_extracted_frame_count,
    iter_video_frames,
    normalize_video_frame_interval_mode,
    normalize_video_target_size,
    prepare_video_source,
    resolve_video_import_source,
    video_target_size_max_dimension,
    video_frame_count,
    video_frame_rate,
)
from app.services.dataset_archive_import_service import (
    cleanup_zip_import_source,
    resolve_zip_import_source,
    run_archive_import_task,
)
from app.utils.crypto import decrypt_secret


def _maybe_remove_session(is_eager: bool) -> None:
    if not is_eager:
        db.session.remove()


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _task_item_deadline() -> datetime:
    return now_utc() + timedelta(seconds=int(current_app.config["TASK_ITEM_LEASE_SECONDS"]))


def _claim_task_execution(task_id: str, item_type: str) -> str | None:
    item = TaskItem.query.filter_by(task_id=task_id, item_index=1).first()
    if item is None:
        try:
            with db.session.begin_nested():
                item = TaskItem(task_id=task_id, item_index=1, item_type=item_type)
                db.session.add(item)
                db.session.flush()
        except IntegrityError:
            item = None

    item = db.session.execute(
        select(TaskItem)
        .where(TaskItem.task_id == task_id, TaskItem.item_index == 1)
        .with_for_update()
    ).scalar_one_or_none()
    if item is None or item.status == "completed":
        db.session.rollback()
        return None
    if (
        item.status == "running"
        and item.lease_expires_at is not None
        and _aware(item.lease_expires_at) > now_utc()
    ):
        db.session.rollback()
        return None

    raw_token = secrets.token_urlsafe(24)
    item.item_type = item_type
    item.status = "running"
    item.attempt_count = int(item.attempt_count or 0) + 1
    item.lease_token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    item.lease_expires_at = _task_item_deadline()
    item.last_error = ""
    db.session.commit()
    return item.id


def _renew_task_execution(item_id: str) -> None:
    item = db.session.get(TaskItem, item_id)
    if item is not None and item.status == "running":
        item.lease_expires_at = _task_item_deadline()


def _finish_task_execution(item_id: str, status: str, error: str = "") -> None:
    item = db.session.get(TaskItem, item_id)
    if item is None:
        return
    item.status = status
    item.last_error = error[:2000]
    item.lease_token_hash = ""
    item.lease_expires_at = None
    item.completed_at = now_utc() if status == "completed" else None


def _mark_dataset_task_execution_failed(task_id: str, error: str) -> None:
    db.session.rollback()
    task = db.session.get(DatasetTask, task_id)
    if task is None or task.status in {"completed", "paused"}:
        return
    task.status = "failed"
    task.completed_at = now_utc()
    config = {**(task.config_json or {})}
    runtime = {**(config.get("runtime") or {})}
    runtime["workerError"] = error[:2000]
    runtime["failedAt"] = now_utc().isoformat()
    config["runtime"] = runtime
    if task.task_type == "augmentation":
        augmentation = {**(config.get("augmentation") or {})}
        augmentation["status"] = "failed"
        augmentation["error"] = error[:2000]
        augmentation["updatedAt"] = now_utc().isoformat()
        config["augmentation"] = augmentation
    task.config_json = config
    item = TaskItem.query.filter_by(task_id=task_id, item_index=1).first()
    if item is not None:
        _finish_task_execution(item.id, "failed", error)
    if task.dataset is not None:
        sync_dataset_task_stats_from_db(task)
        sync_dataset_stats_from_db(task.dataset, commit=False)
    db.session.commit()


def _release_dataset_task_execution_for_retry(task_id: str, error: str) -> None:
    """Release the lease without converting a resumable interruption into failure."""
    db.session.rollback()
    task = db.session.get(DatasetTask, task_id)
    if task is None or task.status in {"completed", "paused", "failed"}:
        return
    config = {**(task.config_json or {})}
    runtime = {**(config.get("runtime") or {})}
    runtime["lastRetryReason"] = error[:2000]
    runtime["retryScheduledAt"] = now_utc().isoformat()
    config["runtime"] = runtime
    task.config_json = config
    task.completed_at = None
    item = TaskItem.query.filter_by(task_id=task_id, item_index=1).first()
    if item is not None and item.status != "completed":
        item.status = "queued"
        item.available_at = now_utc()
        item.last_error = error[:2000]
        item.lease_token_hash = ""
        item.lease_expires_at = None
        item.completed_at = None
    db.session.commit()


def _dispatch_followup_task(task_callable, *args: object) -> None:
    if not current_app.testing:
        enqueue_background_task(task_callable, *args)
        db.session.commit()
        return
    db.session.commit()
    try:
        task_callable.delay(*args)
    except Exception:
        task_name = getattr(task_callable, "name", repr(task_callable))
        current_app.logger.exception(
            "Failed to enqueue follow-up task %s; falling back to inline execution",
            task_name,
        )
        task_callable.apply(args=args, throw=False)


def _is_sqlite_database_locked(exc: OperationalError) -> bool:
    return "database is locked" in str(getattr(exc, "orig", exc)).lower()


def _mark_video_import_failed(task_id: str, error: str) -> None:
    for attempt in range(3):
        try:
            db.session.rollback()
            task = db.session.get(DatasetTask, task_id)
            if task is None:
                return

            dataset = db.session.get(Dataset, task.dataset_id)
            video_config = {**((task.config_json or {}).get("video") or {})}
            video_config["status"] = "failed"
            video_config["error"] = error
            video_config["updatedAt"] = now_utc().isoformat()
            task.config_json = {**(task.config_json or {}), "video": video_config}
            task.status = "failed"
            task.progress_percent = int(task.progress_percent or 0)
            if dataset is not None:
                with db.session.no_autoflush:
                    sync_dataset_task_inplace(task)
                    sync_dataset_stats_inplace(dataset)
            db.session.commit()
            return
        except OperationalError as mark_exc:
            db.session.rollback()
            if _is_sqlite_database_locked(mark_exc) and attempt < 2:
                time.sleep(0.5 * (attempt + 1))
                continue
            current_app.logger.exception("Failed to mark video import task %s as failed", task_id)
            return
        except Exception:
            db.session.rollback()
            current_app.logger.exception("Failed to mark video import task %s as failed", task_id)
            return


def _task_image_count(task_id: str) -> int:
    return int(
        db.session.query(func.count(DatasetImage.id))
        .filter(DatasetImage.source_task_id == task_id)
        .scalar()
        or 0
    )


def _augmentation_source_query(task: DatasetTask, augmentation: dict[str, object]):
    query = DatasetImage.query.filter(DatasetImage.dataset_id == task.dataset_id)
    source_image_ids = [str(image_id) for image_id in augmentation.get("sourceImageIds", [])]
    if source_image_ids:
        return query.filter(DatasetImage.id.in_(source_image_ids)).order_by(
            DatasetImage.ordinal.asc(),
            DatasetImage.id.asc(),
        )
    return (
        query.filter(DatasetImage.selected.is_(True))
        .filter(DatasetImage.status != "augmented")
        .order_by(DatasetImage.ordinal.asc(), DatasetImage.id.asc())
    )


def _augmentation_source_count(task: DatasetTask, augmentation: dict[str, object]) -> int:
    return int(_augmentation_source_query(task, augmentation).count() or 0)


def _augmentation_source_at(
    task: DatasetTask,
    augmentation: dict[str, object],
    index: int,
) -> DatasetImage | None:
    return _augmentation_source_query(task, augmentation).offset(index).limit(1).first()


def _max_detection_confidence(detections: list[dict[str, object]]) -> float | None:
    values: list[float] = []
    for detection in detections:
        try:
            values.append(float(detection["confidence"]))
        except (KeyError, TypeError, ValueError):
            continue
    return max(values, default=None)


def _inherit_augmented_annotation(
    storage_root: str,
    dataset: Dataset,
    source_image: DatasetImage,
    target_image: DatasetImage,
    augmentation_ops: list[dict[str, object]],
) -> None:
    if source_image.annotation_status == "empty":
        save_annotation_result(
            storage_root, dataset.id, target_image.id, [], source="augmentation"
        )
        target_image.annotation_status = "empty"
        target_image.detection_categories = []
        target_image.confidence_score = None
        return

    if source_image.annotation_status != "annotated":
        return

    source_annotation = load_annotation_result(
        storage_root,
        dataset.id,
        source_image.id,
        default_bbox_semantics=infer_default_bbox_semantics(dataset.annotation_json or {}),
    )
    if source_annotation is None:
        return

    source_detections = source_annotation.get("detections", [])
    if not isinstance(source_detections, list):
        source_detections = []
    transformed_detections = transform_detections_for_augmentation(
        source_detections,
        augmentation_ops,
    )
    save_annotation_result(
        storage_root,
        dataset.id,
        target_image.id,
        transformed_detections,
        source="augmentation",
    )
    target_image.annotation_status = "annotated" if transformed_detections else "empty"
    target_image.confidence_score = _max_detection_confidence(transformed_detections)
    target_image.detection_categories = extract_detection_categories(storage_root, dataset.id, target_image.id)


@celery.task(bind=True, max_retries=None)
def generate_dataset_task_images(self, task_id: str) -> None:
    task = db.session.get(DatasetTask, task_id)
    if task is None or task.status != "running":
        return
    execution_item_id = _claim_task_execution(task_id, "generation")
    if execution_item_id is None:
        return

    try:
        while True:
            task = db.session.get(DatasetTask, task_id)
            if task is None or task.status != "running":
                return

            dataset = db.session.get(Dataset, task.dataset_id)
            if dataset is None:
                return

            if len(task.images) >= task.image_count:
                sync_dataset_task_inplace(task)
                sync_dataset_stats_inplace(dataset)
                _finish_task_execution(execution_item_id, "completed")
                db.session.commit()
                break

            source_ordinal = len(task.images) + 1
            dataset_ordinal = next_dataset_ordinal(dataset)
            variant = _dataset_variant_for_ordinal(task, source_ordinal)

            try:
                preview, latency_ms, generated_path, mime_type = _generate_dataset_asset(
                    task, dataset, variant, dataset_ordinal
                )
            except RuntimeError as exc:
                _pause_dataset_task_generation(task, str(exc))
                sync_dataset_task_inplace(task)
                sync_dataset_stats_inplace(dataset)
                _finish_task_execution(execution_item_id, "failed", str(exc))
                db.session.commit()
                return

            image = DatasetImage(
                dataset_id=dataset.id,
                source_task_id=task.id,
                source_type="generation",
                source_ordinal=source_ordinal,
                ordinal=dataset_ordinal,
                status="ready",
                latency_ms=latency_ms,
                seed=variant["seed"],
                prompt_text=variant["prompt"],
                diversity_vars=variant["diversity_vars"],
                preview_svg=preview,
                selected=True,
                annotation_status="pending",
                confidence_score=round(0.66 + ((source_ordinal % 8) * 0.03), 2),
                asset=register_local_asset(
                    current_app.config["STORAGE_ROOT"],
                    generated_path,
                    user_id=task.user_id,
                    dataset_id=dataset.id,
                    kind="dataset_image",
                    mime_type=mime_type,
                ),
            )
            db.session.add(image)
            dataset.images.append(image)
            task.images.append(image)
            sync_dataset_task_inplace(task)
            sync_dataset_stats_inplace(dataset)
            _renew_task_execution(execution_item_id)
            db.session.commit()
            _maybe_remove_session(self.request.is_eager)
    except SoftTimeLimitExceeded as exc:
        current_app.logger.warning("Dataset generation reached its soft limit; rescheduling task %s", task_id)
        _release_dataset_task_execution_for_retry(task_id, "soft time limit reached")
        raise self.retry(exc=exc, countdown=5)
    except Exception as exc:
        current_app.logger.exception("Dataset generation failed for task %s", task_id)
        _mark_dataset_task_execution_failed(task_id, str(exc))
        raise
    finally:
        task = db.session.get(DatasetTask, task_id)
        if task is not None and task.status == "completed":
            dataset = db.session.get(Dataset, task.dataset_id)
            if dataset is not None:
                _enqueue_auto_annotation_dataset(dataset)
        _maybe_remove_session(self.request.is_eager)


@celery.task(bind=True, max_retries=None)
def augment_dataset_task_images(self, task_id: str) -> None:
    try:
        _run_augmentation_task(self, task_id)
    except SoftTimeLimitExceeded as exc:
        current_app.logger.warning("Dataset augmentation reached its soft limit; rescheduling task %s", task_id)
        _release_dataset_task_execution_for_retry(task_id, "soft time limit reached")
        raise self.retry(exc=exc, countdown=5)
    except Exception as exc:
        current_app.logger.exception("Dataset augmentation failed for task %s", task_id)
        _mark_dataset_task_execution_failed(task_id, str(exc))
        raise


def _run_augmentation_task(self, task_id: str) -> None:
    task = db.session.get(DatasetTask, task_id)
    if task is None or task.task_type != "augmentation":
        return

    dataset = db.session.get(Dataset, task.dataset_id)
    if dataset is None:
        return

    augmentation = {**((task.config_json or {}).get("augmentation") or {})}
    if augmentation.get("status") != "running":
        return
    execution_item_id = _claim_task_execution(task_id, "augmentation")
    if execution_item_id is None:
        return

    total_to_create = max(0, int(augmentation.get("totalImagesToCreate", 0)))
    methods = [str(method) for method in augmentation.get("methods", [])]
    settings = augmentation.get("settings") if isinstance(augmentation.get("settings"), dict) else {}
    storage_root = current_app.config["STORAGE_ROOT"]

    while True:
        task = db.session.get(DatasetTask, task_id)
        if task is None:
            return

        dataset = db.session.get(Dataset, task.dataset_id)
        if dataset is None:
            return

        augmentation = {**((task.config_json or {}).get("augmentation") or {})}
        if augmentation.get("status") != "running":
            return

        source_count = _augmentation_source_count(task, augmentation)
        if source_count <= 0:
            augmentation["status"] = "failed"
            augmentation["error"] = "source_images_not_found"
            augmentation["updatedAt"] = now_utc().isoformat()
            task.config_json = {**(task.config_json or {}), "augmentation": augmentation}
            task.status = "failed"
            _finish_task_execution(execution_item_id, "failed", "source_images_not_found")
            db.session.commit()
            return

        completed_images = _task_image_count(task.id)
        if completed_images >= total_to_create:
            augmentation["status"] = "completed"
            augmentation["completedImages"] = completed_images
            augmentation["progressPercent"] = 100
            augmentation["completedAt"] = now_utc().isoformat()
            augmentation["updatedAt"] = now_utc().isoformat()
            task.config_json = {**(task.config_json or {}), "augmentation": augmentation}
            task.status = "completed"
            task.completed_at = now_utc()
            sync_dataset_task_stats_from_db(task)
            sync_dataset_stats_from_db(dataset, commit=False)
            _finish_task_execution(execution_item_id, "completed")
            db.session.commit()
            break

        source_image = _augmentation_source_at(task, augmentation, completed_images % source_count)
        if source_image is None:
            augmentation["status"] = "failed"
            augmentation["error"] = "source_images_not_found"
            augmentation["updatedAt"] = now_utc().isoformat()
            task.config_json = {**(task.config_json or {}), "augmentation": augmentation}
            task.status = "failed"
            _finish_task_execution(execution_item_id, "failed", "source_images_not_found")
            db.session.commit()
            return

        dataset_ordinal = next_dataset_ordinal(dataset)
        augmentation_seed = source_image.seed + 1000 + completed_images
        augmented = augment_generated_image(
            storage_root,
            dataset.id,
            f"image-{source_image.ordinal:06d}",
            f"image-{dataset_ordinal:06d}",
            methods,
            augmentation_seed,
            settings,
        )
        if augmented is None:
            augmentation["status"] = "failed"
            augmentation["error"] = "source_image_missing"
            augmentation["updatedAt"] = now_utc().isoformat()
            task.config_json = {**(task.config_json or {}), "augmentation": augmentation}
            task.status = "failed"
            _finish_task_execution(execution_item_id, "failed", "source_image_missing")
            db.session.commit()
            return

        applied_methods = [str(item) for item in augmented["applied_methods"]]
        image = DatasetImage(
            dataset_id=dataset.id,
            source_task_id=task.id,
            source_type="augmentation",
            source_ordinal=completed_images + 1,
            ordinal=dataset_ordinal,
            status="augmented",
            seed=augmentation_seed,
            prompt_text=f'{source_image.prompt_text}, augmentation: {", ".join(applied_methods)}',
            diversity_vars={**(source_image.diversity_vars or {}), "augmentation": ", ".join(applied_methods)},
            latency_ms=max(400, int(source_image.latency_ms * 0.35)),
            preview_svg=preview_data_url(bytes(augmented["image_bytes"]), str(augmented["mime_type"])),
            selected=True,
            annotation_status="pending",
            confidence_score=source_image.confidence_score,
            asset=register_local_asset(
                storage_root,
                Path(augmented["path"]),
                user_id=task.user_id,
                dataset_id=dataset.id,
                kind="dataset_image",
                mime_type=str(augmented["mime_type"]),
            ),
        )
        db.session.add(image)
        db.session.flush()
        _inherit_augmented_annotation(
            storage_root,
            dataset,
            source_image,
            image,
            [dict(item) for item in augmented.get("augmentation_ops", []) if isinstance(item, dict)],
        )

        augmentation["completedImages"] = completed_images + 1
        augmentation["progressPercent"] = round((completed_images + 1) / total_to_create * 100)
        augmentation["updatedAt"] = now_utc().isoformat()
        task.config_json = {**(task.config_json or {}), "augmentation": augmentation}
        sync_dataset_task_stats_from_db(task)
        sync_dataset_stats_from_db(dataset, commit=False)
        _renew_task_execution(execution_item_id)
        db.session.commit()
        _maybe_remove_session(self.request.is_eager)

    dataset = db.session.get(Dataset, task.dataset_id)
    if dataset is not None:
        _enqueue_auto_annotation_dataset(dataset, skip_annotated=True)


@celery.task(bind=True, max_retries=None)
def extract_dataset_video_frames(self, task_id: str) -> None:
    task = db.session.get(DatasetTask, task_id)
    if task is None or task.task_type != "import" or (task.config_json or {}).get("source") != "video":
        return
    if task.status != "running":
        return
    execution_item_id = _claim_task_execution(task_id, "video_import")
    if execution_item_id is None:
        return

    dataset = db.session.get(Dataset, task.dataset_id)
    if dataset is None:
        return

    config = task.config_json or {}
    video_config = {**(config.get("video") or {})}
    source_path_value = str(config.get("sourcePath") or "")
    storage_root = current_app.config["STORAGE_ROOT"]

    try:
        source_path = resolve_video_import_source(storage_root, source_path_value)
        if not source_path.exists():
            raise RuntimeError("视频源文件不存在，请重新上传。")

        frame_interval_mode = normalize_video_frame_interval_mode(
            str(video_config.get("frameIntervalMode") or DEFAULT_VIDEO_FRAME_INTERVAL_MODE)
        )
        frame_interval = max(1, int(video_config.get("frameInterval", DEFAULT_VIDEO_FRAME_INTERVAL)))
        frame_interval_seconds = max(
            0.01,
            float(video_config.get("frameIntervalSeconds") or DEFAULT_VIDEO_FRAME_INTERVAL_SECONDS),
        )
        output_format = "png" if video_config.get("outputFormat") == "png" else "jpg"
        jpeg_quality = max(1, min(100, int(video_config.get("jpegQuality", 95))))
        filename_prefix = str(video_config.get("filenamePrefix") or "frame")
        target_size = normalize_video_target_size(str(video_config.get("targetSize") or "original"))
        target_max_dimension = video_target_size_max_dimension(target_size)
        max_images = max(1, int(current_app.config.get("MAX_IMPORTED_IMAGES", 2000)))

        with prepare_video_source(source_path) as video_path:
            total_frames = video_frame_count(video_path)
            frame_rate = video_frame_rate(video_path)
            effective_frame_interval = frame_interval
            if frame_interval_mode == "seconds":
                if frame_rate <= 0:
                    raise RuntimeError("无法读取视频帧率，不能按秒抽帧。")
                effective_frame_interval = max(1, round(frame_rate * frame_interval_seconds))
            expected_count = expected_extracted_frame_count(total_frames, effective_frame_interval, max_images)

            video_config = {
                **video_config,
                "frameIntervalMode": frame_interval_mode,
                "frameInterval": frame_interval,
                "frameIntervalSeconds": frame_interval_seconds,
                "effectiveFrameInterval": effective_frame_interval,
                "frameRate": frame_rate,
                "targetSize": target_size,
                "targetMaxDimension": target_max_dimension,
                "totalFrames": total_frames,
                "expectedFrames": expected_count,
                "extractedFrames": len(task.images),
                "status": "running",
                "updatedAt": now_utc().isoformat(),
            }
            task.image_count = expected_count
            task.config_json = {**config, "video": video_config}
            _renew_task_execution(execution_item_id)
            with db.session.no_autoflush:
                sync_dataset_task_inplace(task)
                sync_dataset_stats_inplace(dataset)
            db.session.commit()

            existing_count = len(task.images)
            for extracted in iter_video_frames(
                video_path,
                frame_interval=effective_frame_interval,
                output_format=output_format,
                jpeg_quality=jpeg_quality,
                filename_prefix=filename_prefix,
                max_images=max_images,
                target_max_dimension=target_max_dimension,
                skip_selected_frames=existing_count,
            ):
                task = db.session.get(DatasetTask, task_id)
                if task is None or task.status != "running":
                    return
                dataset = db.session.get(Dataset, task.dataset_id)
                if dataset is None:
                    return

                dataset_ordinal = next_dataset_ordinal(dataset)
                image_key = f"image-{dataset_ordinal:06d}"
                saved_path = save_generated_image(
                    storage_root,
                    dataset.id,
                    image_key,
                    extracted.image_bytes,
                    extracted.mime_type,
                )
                image = DatasetImage(
                    dataset_id=dataset.id,
                    source_task_id=task.id,
                    source_type="video",
                    source_ordinal=extracted.source_ordinal,
                    ordinal=dataset_ordinal,
                    status="uploaded",
                    seed=800000 + extracted.source_frame_index,
                    prompt_text=f"video frame: {video_config.get('filename', 'uploaded video')} #{extracted.source_frame_index}",
                    diversity_vars={
                        "source": "video",
                        "sourceFrame": str(extracted.source_frame_index),
                        "outputFilename": extracted.output_filename,
                    },
                    latency_ms=0,
                    preview_svg=preview_data_url(extracted.image_bytes, extracted.mime_type),
                    selected=True,
                    annotation_status="pending",
                    confidence_score=None,
                    asset=register_local_asset(
                        storage_root,
                        saved_path,
                        user_id=task.user_id,
                        dataset_id=dataset.id,
                        kind="dataset_image",
                        mime_type=extracted.mime_type,
                        original_filename=extracted.output_filename,
                    ),
                )
                db.session.add(image)
                dataset.images.append(image)
                task.images.append(image)

                video_config = {**((task.config_json or {}).get("video") or {})}
                video_config["extractedFrames"] = len(task.images)
                video_config["updatedAt"] = now_utc().isoformat()
                task.config_json = {**(task.config_json or {}), "video": video_config}
                _renew_task_execution(execution_item_id)
                with db.session.no_autoflush:
                    sync_dataset_task_inplace(task)
                    sync_dataset_stats_inplace(dataset)
                db.session.commit()
                _maybe_remove_session(self.request.is_eager)

        task = db.session.get(DatasetTask, task_id)
        if task is None:
            return
        dataset = db.session.get(Dataset, task.dataset_id)
        if dataset is None:
            return

        if len(task.images) <= 0:
            raise RuntimeError("视频中没有可抽取的帧。")

        video_config = {**((task.config_json or {}).get("video") or {})}
        video_config["status"] = "completed"
        video_config["extractedFrames"] = len(task.images)
        video_config["progressPercent"] = 100
        video_config["completedAt"] = now_utc().isoformat()
        video_config["updatedAt"] = now_utc().isoformat()
        task.config_json = {**(task.config_json or {}), "video": video_config}
        task.image_count = len(task.images)
        task.status = "completed"
        task.progress_percent = 100
        task.completed_at = now_utc()
        _finish_task_execution(execution_item_id, "completed")
        with db.session.no_autoflush:
            sync_dataset_task_inplace(task)
            sync_dataset_stats_inplace(dataset)
        if task.source_asset is not None:
            task.source_asset.status = "deleted"
            task.source_asset.deleted_at = now_utc()
        db.session.commit()
        cleanup_video_import_source(storage_root, source_path_value)
    except SoftTimeLimitExceeded as exc:
        current_app.logger.warning("Video import reached its soft limit; rescheduling task %s", task_id)
        _release_dataset_task_execution_for_retry(task_id, "soft time limit reached")
        raise self.retry(exc=exc, countdown=5)
    except Exception as exc:
        current_app.logger.exception("Video frame extraction failed for task %s", task_id)
        _mark_video_import_failed(task_id, str(exc))
        _finish_task_execution(execution_item_id, "failed", str(exc))
        db.session.commit()
    finally:
        _maybe_remove_session(self.request.is_eager)


@celery.task(bind=True, max_retries=2)
def extract_dataset_archive_images(self, task_id: str) -> None:
    task = db.session.get(DatasetTask, task_id)
    if (
        task is None
        or task.task_type != "import"
        or (task.config_json or {}).get("source") != "zip"
        or task.status != "running"
    ):
        return
    execution_item_id = _claim_task_execution(task_id, "zip_import")
    if execution_item_id is None:
        return

    try:
        run_archive_import_task(task_id)
        _finish_task_execution(execution_item_id, "completed")
        db.session.commit()
    except SoftTimeLimitExceeded as exc:
        current_app.logger.warning(
            "Archive import reached soft limit; rescheduling task %s", task_id
        )
        _release_dataset_task_execution_for_retry(task_id, "soft time limit reached")
        raise self.retry(exc=exc, countdown=5)
    except Exception as exc:
        current_app.logger.exception("Archive import failed for task %s", task_id)
        _mark_dataset_task_execution_failed(task_id, str(exc))
        _finish_task_execution(execution_item_id, "failed", str(exc))
        db.session.commit()
    finally:
        _maybe_remove_session(self.request.is_eager)


@celery.task(bind=True, max_retries=2)
def import_roboflow_dataset_task(self, task_id: str) -> None:
    task = db.session.get(DatasetTask, task_id)
    if (
        task is None
        or task.task_type != "import"
        or (task.config_json or {}).get("source") != "roboflow"
        or task.status != "running"
    ):
        return
    execution_item_id = _claim_task_execution(task_id, "roboflow_import")
    if execution_item_id is None:
        return

    try:
        config = task.config_json or {}
        connection_id = str(config.get("connectionId") or "")
        if connection_id:
            connection = ExternalConnection.query.filter_by(
                id=connection_id,
                user_id=task.user_id,
                provider="roboflow",
            ).first()
            if connection is None or connection.status != "valid":
                raise RuntimeError("Roboflow 连接已删除或不可用。")
            api_key = connection_secret(connection)
        elif task.api_key_encrypted:
            api_key = decrypt_secret(
                task.api_key_encrypted, current_app.config["ENCRYPTION_KEY"]
            )
        else:
            raise RuntimeError("Roboflow 导入任务缺少有效连接。")

        from app.services.roboflow_import_service import import_roboflow_dataset

        import_roboflow_dataset(
            dataset=task.dataset,
            user_id=task.user_id,
            api_key=api_key,
            workspace=str(config.get("workspace") or ""),
            project=str(config.get("project") or ""),
            version=str(config.get("version") or ""),
            model_format=str(config.get("format") or "yolov8"),
            task=task,
        )
        task = db.session.get(DatasetTask, task_id)
        if task is not None:
            task.api_key_encrypted = None
        _finish_task_execution(execution_item_id, "completed")
        db.session.commit()
    except SoftTimeLimitExceeded as exc:
        _release_dataset_task_execution_for_retry(task_id, "soft time limit reached")
        raise self.retry(exc=exc, countdown=5)
    except Exception as exc:
        current_app.logger.warning("Roboflow import task %s failed", task_id)
        _mark_dataset_task_execution_failed(task_id, str(exc))
        raise
    finally:
        _maybe_remove_session(self.request.is_eager)


@celery.task(bind=True, max_retries=2)
def analyze_dataset_quality(self, run_id: str) -> None:
    run = db.session.execute(
        select(QualityRun).where(QualityRun.id == run_id).with_for_update()
    ).scalar_one_or_none()
    if run is None or run.status not in {"queued", "failed"}:
        db.session.rollback()
        return
    run.status = "running"
    run.started_at = now_utc()
    run.completed_at = None
    run.error_message = ""
    run.attempt_count = int(run.attempt_count or 0) + 1
    db.session.commit()

    try:
        from app.services.quality_service import run_dataset_quality_analysis
        from app.services.supervision_adapter import supervision_version

        run = db.session.get(QualityRun, run_id)
        run.summary_json = run_dataset_quality_analysis(run)
        run.supervision_version = supervision_version()
        run.status = "completed"
        run.completed_at = now_utc()
        db.session.commit()
    except SoftTimeLimitExceeded as exc:
        run = db.session.get(QualityRun, run_id)
        if run is not None:
            run.status = "queued"
            run.error_message = "soft time limit reached"
            db.session.commit()
        raise self.retry(exc=exc, countdown=5)
    except Exception as exc:
        db.session.rollback()
        run = db.session.get(QualityRun, run_id)
        if run is not None:
            run.status = "failed"
            run.error_message = str(exc)[:2000]
            run.completed_at = now_utc()
            db.session.commit()
        current_app.logger.exception("Quality analysis failed for run %s", run_id)
        if int(getattr(self.request, "retries", 0)) < 2:
            if run is not None:
                run.status = "queued"
                db.session.commit()
            raise self.retry(exc=exc, countdown=5)
    finally:
        _maybe_remove_session(self.request.is_eager)


@celery.task(bind=True, max_retries=None)
def annotate_dataset_images_task(
    self,
    dataset_id: str,
    confidence_threshold: float,
    vl_config: dict[str, str] | None = None,
    skip_annotated: bool = False,
    execution_id: str | None = None,
) -> None:
    from app.clients.annotator_client import annotate_dataset_images

    dataset = db.session.execute(
        select(Dataset).where(Dataset.id == dataset_id).with_for_update()
    ).scalar_one_or_none()
    if dataset is None:
        return

    annotation = {**(dataset.annotation_json or {})}
    if execution_id:
        if annotation.get("executionId") != execution_id:
            db.session.rollback()
            return
        if annotation.get("executionState") in {"completed", "failed"}:
            db.session.rollback()
            return
    lease_raw = annotation.get("executionLeaseExpiresAt")
    if annotation.get("executionState") == "running" and lease_raw:
        try:
            if _aware(datetime.fromisoformat(str(lease_raw))) > now_utc():
                db.session.rollback()
                return
        except ValueError:
            pass
    annotation["executionState"] = "running"
    annotation["executionLeaseExpiresAt"] = _task_item_deadline().isoformat()
    annotation["updatedAt"] = now_utc().isoformat()
    dataset.annotation_json = annotation
    db.session.commit()
    storage_root = current_app.config["STORAGE_ROOT"]
    vl_config = {
        **(vl_config or {}),
        "api_key": current_app.config.get("VL_ANNOTATOR_API_KEY", ""),
    }

    images_to_process = dataset.images
    if skip_annotated:
        images_to_process = [img for img in dataset.images if img.annotation_status not in {"annotated", "empty"}]

    if not images_to_process:
        dataset.annotation_json = {
            **annotation,
            "status": "completed",
            "executionState": "completed",
            "executionLeaseExpiresAt": None,
            "updatedAt": now_utc().isoformat(),
            "skipped": True,
        }
        db.session.commit()
        return

    try:
        results = annotate_dataset_images(
            dataset,
            confidence_threshold=confidence_threshold,
            annotator_url=current_app.config.get("ANNOTATOR_URL", ""),
            storage_root=storage_root,
            vl_config=vl_config,
            images=images_to_process,
        )
    except SoftTimeLimitExceeded as exc:
        current_app.logger.warning("Annotation reached its soft limit; rescheduling dataset %s", dataset.id)
        dataset.annotation_json = {
            **annotation,
            "executionState": "queued",
            "executionLeaseExpiresAt": None,
            "updatedAt": now_utc().isoformat(),
        }
        db.session.commit()
        raise self.retry(exc=exc, countdown=5)
    except Exception:
        current_app.logger.exception("Annotation API failed for dataset %s", dataset.id)
        dataset.annotation_json = {
            **annotation,
            "status": "failed",
            "executionState": "failed",
            "executionLeaseExpiresAt": None,
            "updatedAt": now_utc().isoformat(),
        }
        db.session.commit()
        return

    images_by_id = {image.id: image for image in dataset.images}
    detected_images = 0
    empty_labels = 0

    for result in results:
        image = images_by_id.get(result["imageId"])
        if not image:
            continue
        detections = result.get("detections", [])
        save_annotation_result(
            storage_root,
            dataset.id,
            image.id,
            detections,
            source="automatic",
            provider=str(vl_config.get("provider") or "local"),
            model=str(vl_config.get("model") or ""),
        )
        image.annotation_status = "annotated" if detections else "empty"
        image.confidence_score = max([float(detection["confidence"]) for detection in detections], default=None)
        image.detection_categories = extract_detection_categories(storage_root, dataset.id, image.id)
        if detections:
            detected_images += 1
        else:
            empty_labels += 1

    dataset.annotation_json = {
        **annotation,
        "provider": "vl-auto" if vl_config.get("api_key") else "local-fallback",
        "vlProvider": vl_config.get("provider", "gemini") if vl_config.get("api_key") else "local",
        "confidenceThreshold": confidence_threshold,
        "detectedImages": detected_images,
        "emptyLabels": empty_labels,
        "format": "yolo",
        "status": "completed",
        "executionState": "completed",
        "executionLeaseExpiresAt": None,
        "updatedAt": now_utc().isoformat(),
    }
    db.session.commit()


@celery.task(bind=True, max_retries=None)
def export_dataset_archive(self, export_job_id: str) -> None:
    export_job = db.session.execute(
        select(DatasetExport).where(DatasetExport.id == export_job_id).with_for_update()
    ).scalar_one_or_none()
    if export_job is None:
        return

    if export_job.status == "ready":
        db.session.rollback()
        return
    if (
        export_job.status == "running"
        and export_job.lease_expires_at is not None
        and _aware(export_job.lease_expires_at) > now_utc()
    ):
        db.session.rollback()
        return

    dataset = export_job.dataset
    export_job.status = "running"
    export_job.attempt_count = int(export_job.attempt_count or 0) + 1
    export_job.lease_expires_at = now_utc() + timedelta(
        seconds=int(current_app.config.get("CELERY_TASK_TIME_LIMIT", 3600)) + 60
    )
    db.session.commit()

    try:
        from app.services.dataset_export_service import (
            build_dataset_export_archive,
            dataset_export_download_name,
        )

        summary_json = export_job.summary_json or {}
        archive_summary = build_dataset_export_archive(
            dataset=dataset,
            export_job=export_job,
            export_format=export_job.export_format,
            image_format=summary_json.get("imageFormat", "jpg"),
            include_readme=summary_json.get("includeReadme", True),
            storage_root=current_app.config["STORAGE_ROOT"],
        )
        archive_path = Path(str(archive_summary["archivePath"]))
        export_job.summary_json = archive_summary
        export_job.asset = register_local_asset(
            current_app.config["STORAGE_ROOT"],
            archive_path,
            user_id=dataset.user_id,
            dataset_id=dataset.id,
            kind="dataset_export",
            mime_type="application/zip",
            original_filename=dataset_export_download_name(dataset.name, export_job),
        )
        export_job.status = "ready"
        export_job.lease_expires_at = None
        db.session.commit()
    except SoftTimeLimitExceeded as exc:
        db.session.rollback()
        export_job = db.session.get(DatasetExport, export_job_id)
        if export_job is not None and export_job.status != "ready":
            export_job.status = "pending"
            export_job.lease_expires_at = None
            export_job.summary_json = {
                **(export_job.summary_json or {}),
                "retryScheduledAt": now_utc().isoformat(),
            }
            db.session.commit()
        raise self.retry(exc=exc, countdown=5)
    except Exception:
        current_app.logger.exception("Dataset export failed for job %s", export_job_id)
        export_job.status = "failed"
        export_job.lease_expires_at = None
        export_job.summary_json = {**(export_job.summary_json or {}), "errorAt": now_utc().isoformat()}
        db.session.commit()
        raise


def _dataset_variant_for_ordinal(task: DatasetTask, ordinal: int) -> dict[str, object]:
    variants = (task.prompt_json or {}).get("variants") or []
    if variants:
        return variants[(ordinal - 1) % max(1, len(variants))]
    subject = task.subject or task.dataset.name
    return {
        "seed": 100000 + ordinal,
        "prompt": subject,
        "diversity_vars": {"composition": "centered composition"},
    }


def _resolve_dataset_task_api_key(task: DatasetTask, *, fallback_config_key: str = "") -> str | None:
    if task.api_key_encrypted:
        try:
            api_key = decrypt_secret(task.api_key_encrypted, current_app.config["ENCRYPTION_KEY"]).strip()
        except Exception:
            api_key = ""
        if api_key:
            return api_key

    if fallback_config_key:
        fallback_api_key = str(current_app.config.get(fallback_config_key, "") or "").strip()
        if fallback_api_key:
            return fallback_api_key

    return None


def _generate_dataset_asset(
    task: DatasetTask,
    dataset: Dataset,
    variant: dict[str, object],
    dataset_ordinal: int,
) -> tuple[str, int, Path, str]:
    if task.api_provider == "jimeng":
        api_key = _resolve_dataset_task_api_key(task)
        if not api_key:
            raise RuntimeError("missing_api_key")
        try:
            generated = generate_jimeng_image(
                api_key=api_key,
                base_url=current_app.config["JIMENG_BASE_URL"],
                model=(task.config_json or {}).get("provider_model") or current_app.config["JIMENG_IMAGE_MODEL"],
                prompt=str(variant["prompt"]),
                size=pixel_size_for_aspect_ratio((task.config_json or {}).get("aspect_ratio", "1:1")),
                watermark=bool((task.config_json or {}).get("jimeng_watermark", current_app.config["JIMENG_WATERMARK"])),
            )
        except JimengGenerationError as exc:
            raise RuntimeError(str(exc)) from exc
    elif task.api_provider == "gemini":
        api_key = _resolve_dataset_task_api_key(task, fallback_config_key="GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("missing_api_key")
        try:
            generated = generate_gemini_image(
                api_key=api_key,
                model=(task.config_json or {}).get("provider_model") or current_app.config["GEMINI_IMAGE_MODEL"],
                prompt=str(variant["prompt"]),
                aspect_ratio=normalize_aspect_ratio((task.config_json or {}).get("aspect_ratio", "1:1")),
                person_generation=current_app.config["GEMINI_PERSON_GENERATION"],
                proxy_url=current_app.config.get("GEMINI_HTTP_PROXY", ""),
            )
        except GeminiGenerationError as exc:
            raise RuntimeError(str(exc)) from exc
    else:
        raise RuntimeError(f"provider_not_supported:{task.api_provider}")

    generated_path = save_generated_image(
        current_app.config["STORAGE_ROOT"],
        dataset.id,
        f"image-{dataset_ordinal:06d}",
        generated["image_bytes"],
        generated["mime_type"],
    )
    return (
        preview_data_url(generated["image_bytes"], generated["mime_type"]),
        6500 + dataset_ordinal * 110,
        generated_path,
        str(generated["mime_type"]),
    )


def _pause_dataset_task_generation(task: DatasetTask, error_message: str) -> None:
    runtime = {**((task.config_json or {}).get("runtime") or {})}
    runtime["generationError"] = error_message
    runtime["lastErrorAt"] = now_utc().isoformat()
    task.config_json = {**(task.config_json or {}), "runtime": runtime}
    task.status = "paused"
    task.completed_at = None


def _enqueue_auto_annotation_dataset(dataset: Dataset, *, skip_annotated: bool = False) -> None:
    vl_config = {
        "provider": current_app.config.get("VL_ANNOTATOR_PROVIDER", "gemini"),
        "model": current_app.config.get("VL_ANNOTATOR_MODEL", "gemini-2.0-flash"),
        "base_url": current_app.config.get("VL_ANNOTATOR_BASE_URL", ""),
    }
    execution_id = generate_uuid()
    dataset.annotation_json = {
        **(dataset.annotation_json or {}),
        "status": "running",
        "executionState": "queued",
        "executionId": execution_id,
        "updatedAt": now_utc().isoformat(),
    }
    _dispatch_followup_task(
        annotate_dataset_images_task,
        str(dataset.id),
        0.5,
        vl_config,
        skip_annotated,
        execution_id,
    )
