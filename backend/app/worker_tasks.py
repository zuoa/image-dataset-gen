from __future__ import annotations

from flask import current_app

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
def annotate_dataset_images_task(
    self,
    dataset_id: str,
    confidence_threshold: float,
    vl_config: dict[str, str] | None = None,
) -> None:
    from app.clients.annotator_client import annotate_dataset_images
    from app.services.annotation_storage import save_annotation_result

    dataset = db.session.get(Dataset, dataset_id)
    if dataset is None:
        return

    annotation = dataset.annotation_json or {}
    storage_root = current_app.config["STORAGE_ROOT"]
    vl_config = vl_config or {}

    try:
        results = annotate_dataset_images(
            dataset,
            confidence_threshold=confidence_threshold,
            annotator_url=current_app.config.get("ANNOTATOR_URL", ""),
            storage_root=storage_root,
            vl_config=vl_config,
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
