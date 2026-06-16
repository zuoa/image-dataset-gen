from __future__ import annotations

import time

from flask import current_app
from sqlalchemy.exc import OperationalError

from app.clients.gemini_client import (
    GeminiGenerationError,
    generate_image as generate_gemini_image,
    normalize_aspect_ratio,
    pixel_size_for_aspect_ratio,
)
from app.clients.jimeng_client import JimengGenerationError, generate_image as generate_jimeng_image
from app.extensions import celery, db
from app.models import Dataset, DatasetExport, DatasetImage, DatasetTask
from app.services.dataset_service import (
    next_dataset_ordinal,
    now_utc,
    sync_dataset_stats_inplace,
    sync_dataset_task_inplace,
)
from app.services.image_storage import augment_generated_image, preview_data_url, save_generated_image
from app.services.video_import_service import (
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
from app.utils.crypto import decrypt_secret


def _maybe_remove_session(is_eager: bool) -> None:
    if not is_eager:
        db.session.remove()


def _dispatch_followup_task(task_callable, *args: object) -> None:
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


@celery.task(bind=True)
def generate_dataset_task_images(self, task_id: str) -> None:
    task = db.session.get(DatasetTask, task_id)
    if task is None or task.status != "running":
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
                db.session.commit()
                break

            source_ordinal = len(task.images) + 1
            dataset_ordinal = next_dataset_ordinal(dataset)
            variant = _dataset_variant_for_ordinal(task, source_ordinal)

            try:
                preview, latency_ms = _generate_dataset_asset(task, dataset, variant, dataset_ordinal)
            except RuntimeError as exc:
                _pause_dataset_task_generation(task, str(exc))
                sync_dataset_task_inplace(task)
                sync_dataset_stats_inplace(dataset)
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
            )
            db.session.add(image)
            dataset.images.append(image)
            task.images.append(image)
            sync_dataset_task_inplace(task)
            sync_dataset_stats_inplace(dataset)
            db.session.commit()
            _maybe_remove_session(self.request.is_eager)
    finally:
        task = db.session.get(DatasetTask, task_id)
        if task is not None and task.status == "completed":
            dataset = db.session.get(Dataset, task.dataset_id)
            if dataset is not None:
                _enqueue_auto_annotation_dataset(dataset)
        _maybe_remove_session(self.request.is_eager)


@celery.task(bind=True)
def augment_dataset_task_images(self, task_id: str) -> None:
    task = db.session.get(DatasetTask, task_id)
    if task is None or task.task_type != "augmentation":
        return

    dataset = db.session.get(Dataset, task.dataset_id)
    if dataset is None:
        return

    augmentation = {**((task.config_json or {}).get("augmentation") or {})}
    if augmentation.get("status") != "running":
        return

    total_to_create = max(0, int(augmentation.get("totalImagesToCreate", 0)))
    methods = [str(method) for method in augmentation.get("methods", [])]
    settings = augmentation.get("settings") if isinstance(augmentation.get("settings"), dict) else {}
    storage_root = current_app.config["STORAGE_ROOT"]
    source_image_ids = [str(image_id) for image_id in augmentation.get("sourceImageIds", [])]

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

        source_images = [image for image in dataset.images if image.id in source_image_ids]
        if not source_images:
            augmentation["status"] = "failed"
            augmentation["error"] = "source_images_not_found"
            augmentation["updatedAt"] = now_utc().isoformat()
            task.config_json = {**(task.config_json or {}), "augmentation": augmentation}
            task.status = "failed"
            db.session.commit()
            return

        completed_images = len(task.images)
        if completed_images >= total_to_create:
            augmentation["status"] = "completed"
            augmentation["completedImages"] = completed_images
            augmentation["progressPercent"] = 100
            augmentation["completedAt"] = now_utc().isoformat()
            augmentation["updatedAt"] = now_utc().isoformat()
            task.config_json = {**(task.config_json or {}), "augmentation": augmentation}
            task.status = "completed"
            task.completed_at = now_utc()
            sync_dataset_task_inplace(task)
            sync_dataset_stats_inplace(dataset)
            db.session.commit()
            break

        source_image = source_images[completed_images % len(source_images)]
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
        )
        db.session.add(image)
        dataset.images.append(image)
        task.images.append(image)

        augmentation["completedImages"] = completed_images + 1
        augmentation["progressPercent"] = round((completed_images + 1) / total_to_create * 100)
        augmentation["updatedAt"] = now_utc().isoformat()
        task.config_json = {**(task.config_json or {}), "augmentation": augmentation}
        sync_dataset_task_inplace(task)
        sync_dataset_stats_inplace(dataset)
        db.session.commit()
        _maybe_remove_session(self.request.is_eager)

    dataset = db.session.get(Dataset, task.dataset_id)
    if dataset is not None:
        _enqueue_auto_annotation_dataset(dataset)


@celery.task(bind=True)
def extract_dataset_video_frames(self, task_id: str) -> None:
    task = db.session.get(DatasetTask, task_id)
    if task is None or task.task_type != "import" or (task.config_json or {}).get("source") != "video":
        return
    if task.status != "running":
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
            str(video_config.get("frameIntervalMode") or "frames")
        )
        frame_interval = max(1, int(video_config.get("frameInterval", 30)))
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
                save_generated_image(
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
                )
                db.session.add(image)
                dataset.images.append(image)
                task.images.append(image)

                video_config = {**((task.config_json or {}).get("video") or {})}
                video_config["extractedFrames"] = len(task.images)
                video_config["updatedAt"] = now_utc().isoformat()
                task.config_json = {**(task.config_json or {}), "video": video_config}
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
        with db.session.no_autoflush:
            sync_dataset_task_inplace(task)
            sync_dataset_stats_inplace(dataset)
        db.session.commit()
        cleanup_video_import_source(storage_root, source_path_value)
    except Exception as exc:
        current_app.logger.exception("Video frame extraction failed for task %s", task_id)
        _mark_video_import_failed(task_id, str(exc))
    finally:
        _maybe_remove_session(self.request.is_eager)


@celery.task(bind=True)
def annotate_dataset_images_task(
    self,
    dataset_id: str,
    confidence_threshold: float,
    vl_config: dict[str, str] | None = None,
    skip_annotated: bool = False,
) -> None:
    from app.clients.annotator_client import annotate_dataset_images
    from app.services.annotation_storage import save_annotation_result

    dataset = db.session.get(Dataset, dataset_id)
    if dataset is None:
        return

    annotation = dataset.annotation_json or {}
    storage_root = current_app.config["STORAGE_ROOT"]
    vl_config = vl_config or {}

    images_to_process = dataset.images
    if skip_annotated:
        images_to_process = [img for img in dataset.images if img.annotation_status != "annotated"]

    if not images_to_process:
        dataset.annotation_json = {
            **annotation,
            "status": "completed",
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
    except Exception:
        current_app.logger.exception("Annotation API failed for dataset %s", dataset.id)
        dataset.annotation_json = {
            **annotation,
            "status": "failed",
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
        save_annotation_result(storage_root, dataset.id, image.id, detections)
        image.annotation_status = "annotated" if detections else "empty"
        image.confidence_score = max([float(detection["confidence"]) for detection in detections], default=None)
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
        "updatedAt": now_utc().isoformat(),
    }
    db.session.commit()


@celery.task(bind=True)
def export_dataset_archive(self, export_job_id: str) -> None:
    export_job = db.session.get(DatasetExport, export_job_id)
    if export_job is None:
        return

    dataset = export_job.dataset
    export_job.status = "running"
    db.session.commit()

    try:
        from app.services.dataset_export_service import build_dataset_export_archive

        summary_json = export_job.summary_json or {}
        archive_summary = build_dataset_export_archive(
            dataset=dataset,
            export_job=export_job,
            export_format=export_job.export_format,
            image_format=summary_json.get("imageFormat", "jpg"),
            include_readme=summary_json.get("includeReadme", True),
            storage_root=current_app.config["STORAGE_ROOT"],
        )
        export_job.summary_json = archive_summary
        export_job.status = "ready"
        db.session.commit()
    except Exception:
        current_app.logger.exception("Dataset export failed for job %s", export_job_id)
        export_job.status = "failed"
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
) -> tuple[str, int]:
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

    save_generated_image(
        current_app.config["STORAGE_ROOT"],
        dataset.id,
        f"image-{dataset_ordinal:06d}",
        generated["image_bytes"],
        generated["mime_type"],
    )
    return preview_data_url(generated["image_bytes"], generated["mime_type"]), 6500 + dataset_ordinal * 110


def _pause_dataset_task_generation(task: DatasetTask, error_message: str) -> None:
    runtime = {**((task.config_json or {}).get("runtime") or {})}
    runtime["generationError"] = error_message
    runtime["lastErrorAt"] = now_utc().isoformat()
    task.config_json = {**(task.config_json or {}), "runtime": runtime}
    task.status = "paused"
    task.completed_at = None


def _enqueue_auto_annotation_dataset(dataset: Dataset) -> None:
    vl_config = {
        "provider": current_app.config.get("VL_ANNOTATOR_PROVIDER", "gemini"),
        "model": current_app.config.get("VL_ANNOTATOR_MODEL", "gemini-2.0-flash"),
        "api_key": current_app.config.get("VL_ANNOTATOR_API_KEY", ""),
        "base_url": current_app.config.get("VL_ANNOTATOR_BASE_URL", ""),
    }
    _dispatch_followup_task(annotate_dataset_images_task, str(dataset.id), 0.5, vl_config)
