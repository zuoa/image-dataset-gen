from __future__ import annotations

from flask import current_app

from app.extensions import celery, db
from app.models import Task, TaskExport, TaskImage


def _maybe_remove_session(is_eager: bool) -> None:
    if not is_eager:
        db.session.remove()


@celery.task(bind=True)
def generate_task_images(self, task_id: str) -> None:
    from app.services.task_service import (
        ImageGenerationError,
        _generate_next_task_image,
        _pause_task_generation,
        _update_generation_metrics,
    )

    session = db.session()
    task = session.get(Task, task_id)
    if task is None or task.status != "running":
        session.close()
        return

    try:
        while True:
            task = db.session.get(Task, task_id)
            if task is None or task.status != "running":
                return

            if len(task.images) >= task.image_count:
                _update_generation_metrics(task, len(task.images))
                db.session.commit()
                break

            try:
                _generate_next_task_image(task)
                db.session.commit()
                current_app.logger.info("Generated image for task %s, images now=%s", task_id, len(task.images))
            except ImageGenerationError as exc:
                current_app.logger.info("ImageGenerationError for task %s: %s", task_id, exc)
                _pause_task_generation(task, str(exc))
                db.session.commit()
                return

            _maybe_remove_session(self.request.is_eager)
    except Exception as exc:
        current_app.logger.exception("Background generation failed for task %s", task_id)
        task = db.session.get(Task, task_id)
        if task is not None and task.status == "running":
            _pause_task_generation(task, "background_generation_failed")
            db.session.commit()
        _maybe_remove_session(self.request.is_eager)
        raise
    finally:
        task = db.session.get(Task, task_id)
        if task is not None and task.status == "completed":
            _enqueue_auto_annotation(task)
        _maybe_remove_session(self.request.is_eager)


@celery.task(bind=True)
def augment_task_images(self, task_id: str) -> None:
    from app.services.image_storage import augment_generated_image, preview_data_url
    from app.services.task_service import now_utc

    task = db.session.get(Task, task_id)
    if task is None:
        return

    augmentation = {**((task.config_json or {}).get("augmentation") or {})}
    if augmentation.get("status") != "running":
        return

    total_to_create = max(0, int(augmentation.get("totalImagesToCreate", 0)))
    methods = [str(method) for method in augmentation.get("methods", [])]
    settings = augmentation.get("settings") if isinstance(augmentation.get("settings"), dict) else {}
    storage_root = current_app.config["STORAGE_ROOT"]

    source_image_ids = [str(image_id) for image_id in augmentation.get("sourceImageIds", [])]
    source_images = [image for image in task.images if image.id in source_image_ids]

    if not source_images:
        augmentation["status"] = "failed"
        augmentation["error"] = "source_images_not_found"
        augmentation["updatedAt"] = now_utc().isoformat()
        task.config_json = {**(task.config_json or {}), "augmentation": augmentation}
        db.session.commit()
        return

    while True:
        task = db.session.get(Task, task_id)
        if task is None:
            return

        augmentation = {**((task.config_json or {}).get("augmentation") or {})}
        if augmentation.get("status") != "running":
            return

        augmented_images = [image for image in task.images if image.status == "augmented"]
        completed_images = len(augmented_images)

        if completed_images >= total_to_create:
            augmentation["status"] = "completed"
            augmentation["completedImages"] = completed_images
            augmentation["progressPercent"] = 100
            augmentation["completedAt"] = now_utc().isoformat()
            augmentation["updatedAt"] = now_utc().isoformat()
            task.config_json = {**(task.config_json or {}), "augmentation": augmentation}
            db.session.commit()
            break

        next_ordinal = max((image.ordinal for image in task.images), default=0) + 1
        source_image = source_images[completed_images % len(source_images)]
        augmentation_seed = source_image.seed + 1000 + completed_images
        augmented = augment_generated_image(
            storage_root,
            task.id,
            f"ordinal-{source_image.ordinal:06d}",
            f"ordinal-{next_ordinal:06d}",
            methods,
            augmentation_seed,
            settings,
        )
        if augmented is None:
            augmentation["status"] = "failed"
            augmentation["error"] = "source_image_missing"
            augmentation["updatedAt"] = now_utc().isoformat()
            task.config_json = {**(task.config_json or {}), "augmentation": augmentation}
            db.session.commit()
            return

        applied_methods = [str(item) for item in augmented["applied_methods"]]
        image = TaskImage(
            task_id=task.id,
            ordinal=next_ordinal,
            status="augmented",
            seed=augmentation_seed,
            prompt_text=f'{source_image.prompt_text}, augmentation: {", ".join(applied_methods)}',
            diversity_vars={**(source_image.diversity_vars or {}), "augmentation": ", ".join(applied_methods)},
            latency_ms=max(400, int(source_image.latency_ms * 0.35)),
            preview_svg=preview_data_url(
                bytes(augmented["image_bytes"]),
                str(augmented["mime_type"]),
            ),
            selected=True,
            annotation_status="pending",
            confidence_score=source_image.confidence_score,
        )
        db.session.add(image)
        task.images.append(image)

        augmentation["completedImages"] = completed_images + 1
        augmentation["progressPercent"] = round((completed_images + 1) / total_to_create * 100)
        augmentation["updatedAt"] = now_utc().isoformat()
        task.config_json = {**(task.config_json or {}), "augmentation": augmentation}
        db.session.commit()
        _maybe_remove_session(self.request.is_eager)

    _enqueue_auto_annotation(task)


@celery.task(bind=True)
def annotate_task_images_task(
    self,
    task_id: str,
    confidence_threshold: float,
    vl_config: dict[str, str] | None = None,
    auto_annotate: bool = False,
) -> None:
    from app.clients.annotator_client import annotate_task_images
    from app.services.annotation_storage import save_annotation_result
    from app.services.task_service import now_utc

    task = db.session.get(Task, task_id)
    if task is None:
        return

    annotation = (task.config_json or {}).get("annotation") or {}
    storage_root = current_app.config["STORAGE_ROOT"]

    vl_config = vl_config or {}

    try:
        results = annotate_task_images(
            task,
            confidence_threshold=confidence_threshold,
            annotator_url=current_app.config.get("ANNOTATOR_URL", ""),
            storage_root=storage_root,
            vl_config=vl_config,
        )
    except Exception:
        current_app.logger.exception("Annotation API failed for task %s", task.id)
        annotation_summary = {
            **annotation,
            "status": "failed",
            "updatedAt": now_utc().isoformat(),
        }
        task.config_json = {**(task.config_json or {}), "annotation": annotation_summary}
        db.session.commit()
        return

    images_by_id = {image.id: image for image in task.images}
    detected_images = 0
    empty_labels = 0

    for result in results:
        image = images_by_id.get(result["imageId"])
        if not image:
            continue
        detections = result.get("detections", [])
        save_annotation_result(storage_root, task.id, image.id, detections)
        image.annotation_status = "annotated" if detections else "empty"
        image.confidence_score = max(
            [float(detection["confidence"]) for detection in detections],
            default=None,
        )
        if detections:
            detected_images += 1
        else:
            empty_labels += 1

    annotation_summary = {
        **annotation,
        "provider": "vl-auto" if vl_config.get("api_key") else "local-fallback",
        "confidenceThreshold": confidence_threshold,
        "detectedImages": detected_images,
        "emptyLabels": empty_labels,
        "format": "yolo",
        "updatedAt": now_utc().isoformat(),
    }
    if auto_annotate:
        annotation_summary["autoAnnotated"] = True

    task.config_json = {**(task.config_json or {}), "annotation": annotation_summary}
    db.session.commit()


@celery.task(bind=True)
def export_task_archive(self, export_job_id: str) -> None:
    from app.services.export_service import build_export_archive
    from app.services.task_service import now_utc

    export_job = db.session.get(TaskExport, export_job_id)
    if export_job is None:
        return

    task = export_job.task
    export_job.status = "running"
    db.session.commit()

    try:
        summary_json = export_job.summary_json or {}
        archive_summary = build_export_archive(
            task=task,
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
        current_app.logger.exception("Export failed for job %s", export_job_id)
        export_job.status = "failed"
        export_job.summary_json = {**(export_job.summary_json or {}), "errorAt": now_utc().isoformat()}
        db.session.commit()
        raise


def _enqueue_auto_annotation(task: Task) -> None:
    vl_config = {
        "provider": current_app.config.get("VL_ANNOTATOR_PROVIDER", "gemini"),
        "model": current_app.config.get("VL_ANNOTATOR_MODEL", "gemini-2.0-flash"),
        "api_key": current_app.config.get("VL_ANNOTATOR_API_KEY", ""),
        "base_url": current_app.config.get("VL_ANNOTATOR_BASE_URL", ""),
    }
    annotate_task_images_task.delay(str(task.id), 0.5, vl_config, auto_annotate=True)
