from __future__ import annotations

from threading import Lock, Thread
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

from flask import Flask, current_app
from sqlalchemy import case, func, select

from app.clients.gemini_client import (
    GeminiGenerationError,
    generate_image as generate_gemini_image,
    normalize_aspect_ratio,
    pixel_size_for_aspect_ratio,
)
from app.clients.jimeng_client import (
    JimengGenerationError,
    generate_image as generate_jimeng_image,
)
from app.extensions import db
from app.models import Task, TaskExport, TaskImage
from app.services.annotation_storage import load_annotation_result
from app.services.image_storage import (
    augment_generated_image,
    existing_generated_image,
    preview_data_url,
    save_generated_image,
)
from app.services.prompt_engine import build_prompt_preview, estimate_cost
from app.utils.crypto import decrypt_secret


PROVIDER_CATALOG = [
    {
        "id": "gemini",
        "name": "Nano Banana 2",
        "latency": "4-8s",
        "recommendConcurrency": 3,
        "unitPrice": 0.045,
        "supportsStrictMode": True,
        "promptLanguage": "en",
        "defaultModel": "gemini-3.1-flash-image-preview",
        "models": [
            "gemini-3.1-flash-image-preview",
            "gemini-3-pro-image-preview",
            "gemini-2.5-flash-image",
            "imagen-4.0-generate-001",
            "imagen-4.0-fast-generate-001",
        ],
        "sizeHint": "Supports aspect ratio control; all generated images include SynthID watermark",
        "notes": [
            "Nano Banana 2 maps to Gemini 3.1 Flash Image Preview",
            "Legacy imagen-* models remain available for backward compatibility",
            "Failures pause the task immediately",
        ],
    },
    {
        "id": "jimeng",
        "name": "即梦 AI",
        "latency": "4-8s",
        "recommendConcurrency": 5,
        "unitPrice": 0.028,
        "supportsStrictMode": True,
        "promptLanguage": "zh",
        "defaultModel": "doubao-seedream-3-0-t2i-250415",
        "models": [
            "doubao-seedream-5-0-lite-260128",
            "doubao-seedream-5-0-260128",
            "doubao-seedream-4-5-251128",
            "doubao-seedream-4-0-250828",
            "doubao-seedream-3-0-t2i-250415",
        ],
        "sizeHint": "选择宽高比例即可，服务端会映射到稳定的默认像素尺寸，当前输出 JPG",
        "notes": [
            "Backed by Volcengine Seedream image API",
            "Prompt prefers Chinese descriptions",
            "Current model uses b64_json response and optional watermark",
        ],
    },
    {
        "id": "stability",
        "name": "Stability AI",
        "latency": "6-12s",
        "recommendConcurrency": 4,
        "unitPrice": 0.032,
        "supportsStrictMode": True,
        "promptLanguage": "en",
        "defaultModel": "",
        "models": [],
        "sizeHint": "Not yet implemented in this repo",
        "notes": ["Placeholder provider metadata only"],
    },
    {
        "id": "custom",
        "name": "Custom Adapter",
        "latency": "variable",
        "recommendConcurrency": 2,
        "unitPrice": 0.040,
        "supportsStrictMode": True,
        "promptLanguage": "mixed",
        "defaultModel": "",
        "models": [],
        "sizeHint": "Requires custom backend implementation",
        "notes": ["Currently unsupported and will pause immediately"],
    },
]

_active_generation_tasks: set[str] = set()
_active_generation_lock = Lock()


def now_utc() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class ImageGenerationError(RuntimeError):
    pass


def build_task_payload(
    task: Task,
    *,
    include_images: bool = True,
    include_exports: bool = True,
) -> dict[str, Any]:
    config = task.config_json or {}
    prompt = task.prompt_json or {}
    sample_count = len(task.images) if include_images else int(task.images_generated or 0)
    return {
        "id": task.id,
        "subject": task.subject,
        "categories": task.categories,
        "imageCount": task.image_count,
        "sampleCount": sample_count,
        "status": task.status,
        "progressPercent": task.progress_percent,
        "imagesGenerated": task.images_generated,
        "selectedCount": task.selected_count,
        "estimatedCost": task.estimated_cost,
        "spentCost": task.spent_cost,
        "apiProvider": task.api_provider,
        "startedAt": task.started_at.isoformat() if task.started_at else None,
        "completedAt": task.completed_at.isoformat() if task.completed_at else None,
        "createdAt": task.created_at.isoformat() if task.created_at else None,
        "updatedAt": task.updated_at.isoformat() if task.updated_at else None,
        "config": config,
        "prompt": prompt,
        "runtime": (config or {}).get("runtime", {}),
        "images": [build_image_payload(task, image) for image in task.images] if include_images else [],
        "exports": [build_export_payload(export_job) for export_job in task.exports] if include_exports else [],
    }


def build_task_list_payload(task: Task) -> dict[str, Any]:
    return build_task_payload(task, include_images=False, include_exports=False)


def build_image_payload(task: Task, image: TaskImage) -> dict[str, Any]:
    stored_annotation = load_annotation_result(current_app.config["STORAGE_ROOT"], task.id, image.id) or {}
    detections = stored_annotation.get("detections", [])
    if image.status == "augmented":
        source = "augmented"
    elif image.status == "uploaded":
        source = "uploaded"
    else:
        source = "placeholder" if image.preview_svg.startswith("data:image/svg+xml") else task.api_provider

    preview: str
    if image.preview_svg.startswith("data:image/svg+xml"):
        preview = image.preview_svg
    else:
        image_base_url = (current_app.config.get("IMAGE_BASE_URL") or "").rstrip("/")
        image_path = existing_generated_image(
            current_app.config["STORAGE_ROOT"], task.id, f"ordinal-{image.ordinal:06d}"
        )
        if image_base_url and image_path is not None:
            preview = f"{image_base_url}/{task.id}/{image_path.name}"
        else:
            preview = f"{current_app.config['API_PREFIX']}/tasks/{task.id}/images/{image.id}/preview"
    return {
        "id": image.id,
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
        "source": source,
        "detections": detections,
    }


def build_export_payload(export_job: TaskExport) -> dict[str, Any]:
    return {
        "id": export_job.id,
        "version": export_job.version,
        "status": export_job.status,
        "exportFormat": export_job.export_format,
        "downloadUrl": export_job.download_url,
        "summary": export_job.summary_json,
        "createdAt": export_job.created_at.isoformat() if export_job.created_at else None,
    }


def build_demo_svg(task: Task, ordinal: int, category: str, variant: dict[str, Any]) -> str:
    label = category.upper()
    subtitle = task.subject[:36]
    accent = ["#111111", "#1f1f1f", "#2b2b2b", "#3b3b3b"][ordinal % 4]
    svg = f"""
    <svg xmlns="http://www.w3.org/2000/svg" width="512" height="512" viewBox="0 0 512 512">
      <defs>
        <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stop-color="#060606" />
          <stop offset="100%" stop-color="{accent}" />
        </linearGradient>
      </defs>
      <rect width="512" height="512" fill="url(#bg)" rx="36"/>
      <rect x="24" y="24" width="464" height="464" rx="28" fill="none" stroke="#d4d4d4" stroke-opacity="0.16"/>
      <text x="40" y="92" fill="#f5f5f5" font-size="52" font-family="IBM Plex Sans, Arial, sans-serif">{label}</text>
      <text x="40" y="138" fill="#b4b4b4" font-size="20" font-family="IBM Plex Mono, monospace">#{ordinal:03d} · {variant["seed"]}</text>
      <text x="40" y="430" fill="#d4d4d4" font-size="20" font-family="IBM Plex Sans, Arial, sans-serif">{subtitle}</text>
      <text x="40" y="462" fill="#9a9a9a" font-size="16" font-family="IBM Plex Mono, monospace">{variant["diversity_vars"]["composition"]}</text>
    </svg>
    """.strip()
    return f"data:image/svg+xml;utf8,{quote(svg)}"


def enqueue_task_generation(app: Flask, task_id: str) -> bool:
    with _active_generation_lock:
        if task_id in _active_generation_tasks:
            return False
        _active_generation_tasks.add(task_id)

    thread = Thread(
        target=_run_task_generation,
        args=(app, task_id),
        daemon=True,
        name=f"task-generation-{task_id}",
    )
    thread.start()
    return True


def sync_task_progress(task: Task) -> Task:
    return sync_task_augmentation_progress(task)


def sync_task_augmentation_progress(task: Task) -> Task:
    if not _sync_augmentation_progress_inplace(task):
        return task

    task.images_generated = len(task.images)
    task.selected_count = sum(1 for image in task.images if image.selected)
    db.session.commit()
    db.session.refresh(task)
    return task


def _sync_augmentation_progress_inplace(task: Task) -> bool:
    augmentation = {**((task.config_json or {}).get("augmentation") or {})}
    if augmentation.get("status") != "running":
        return False

    started_at_raw = augmentation.get("startedAt")
    try:
        started_at = datetime.fromisoformat(str(started_at_raw)) if started_at_raw else now_utc()
    except ValueError:
        started_at = now_utc()

    source_image_ids = [str(image_id) for image_id in augmentation.get("sourceImageIds", [])]
    source_images = [image for image in task.images if image.id in source_image_ids]
    if not source_images:
        augmentation["status"] = "failed"
        augmentation["error"] = "source_images_not_found"
        augmentation["updatedAt"] = now_utc().isoformat()
        task.config_json = {**(task.config_json or {}), "augmentation": augmentation}
        return True

    total_to_create = max(0, int(augmentation.get("totalImagesToCreate", 0)))
    augmented_images = [image for image in task.images if image.status == "augmented"]
    completed_images = len(augmented_images)
    if total_to_create == 0:
        augmentation["status"] = "completed"
        augmentation["completedImages"] = 0
        augmentation["progressPercent"] = 100
        augmentation["completedAt"] = now_utc().isoformat()
        augmentation["updatedAt"] = now_utc().isoformat()
        task.config_json = {**(task.config_json or {}), "augmentation": augmentation}
        return True

    elapsed_seconds = max(0.0, (now_utc() - started_at).total_seconds())
    target_completed = min(total_to_create, int(elapsed_seconds / 0.55) + 1)
    batch_limit = max(1, int(task.config_json.get("concurrency", 1)))
    target_completed = min(target_completed, completed_images + batch_limit)

    next_ordinal = max((image.ordinal for image in task.images), default=0) + 1
    methods = [str(method) for method in augmentation.get("methods", [])]
    settings = augmentation.get("settings") if isinstance(augmentation.get("settings"), dict) else {}
    storage_root = current_app.config["STORAGE_ROOT"]

    while completed_images < target_completed:
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
            return True

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
        completed_images += 1
        next_ordinal += 1

    augmentation["completedImages"] = completed_images
    augmentation["progressPercent"] = round(completed_images / total_to_create * 100)
    augmentation["updatedAt"] = now_utc().isoformat()
    if completed_images >= total_to_create:
        augmentation["status"] = "completed"
        augmentation["completedAt"] = now_utc().isoformat()
    task.config_json = {**(task.config_json or {}), "augmentation": augmentation}
    return True


def _run_task_generation(app: Flask, task_id: str) -> None:
    try:
        with app.app_context():
            while True:
                task = db.session.get(Task, task_id)
                if task is None or task.status != "running":
                    return

                if len(task.images) >= task.image_count:
                    _update_generation_metrics(task, len(task.images))
                    db.session.commit()
                    return

                try:
                    _generate_next_task_image(task)
                    db.session.commit()
                except ImageGenerationError as exc:
                    _pause_task_generation(task, str(exc))
                    db.session.commit()
                    return

                db.session.remove()
    except Exception:
        with app.app_context():
            app.logger.exception("Background generation failed for task %s", task_id)
            task = db.session.get(Task, task_id)
            if task is not None and task.status == "running":
                _pause_task_generation(task, "background_generation_failed")
                db.session.commit()
            db.session.remove()
    finally:
        with _active_generation_lock:
            _active_generation_tasks.discard(task_id)


def _generate_next_task_image(task: Task) -> None:
    existing_count = len(task.images)
    if existing_count >= task.image_count:
        _update_generation_metrics(task, existing_count)
        return

    ordinal = existing_count + 1
    variant = _variant_for_ordinal(task, ordinal)
    category = _category_for_ordinal(task, ordinal)
    preview, latency_ms = _generate_preview_asset(task, variant, ordinal, category)
    image = TaskImage(
        task_id=task.id,
        ordinal=ordinal,
        seed=variant["seed"],
        prompt_text=variant["prompt"],
        diversity_vars=variant["diversity_vars"],
        latency_ms=latency_ms,
        preview_svg=preview,
        annotation_status="pending",
        confidence_score=round(0.66 + ((ordinal % 8) * 0.03), 2),
    )
    db.session.add(image)
    task.images.append(image)
    _update_generation_metrics(task, ordinal)


def _variant_for_ordinal(task: Task, ordinal: int) -> dict[str, Any]:
    variants = (task.prompt_json or {}).get("variants") or []
    if variants:
        return variants[(ordinal - 1) % max(1, len(variants))]
    return {
        "seed": 100000 + ordinal,
        "prompt": (task.prompt_json or {}).get("positive_prompt", task.subject),
        "diversity_vars": {"composition": "centered composition"},
    }


def _category_for_ordinal(task: Task, ordinal: int) -> str:
    categories = task.categories or ["default"]
    return categories[(ordinal - 1) % len(categories)]


def _update_generation_metrics(task: Task, generated_count: int) -> None:
    effective_image_count = max(int(task.image_count or 0), 1)
    ratio = min(generated_count, effective_image_count) / effective_image_count
    task.images_generated = generated_count
    task.selected_count = sum(1 for image in task.images if image.selected)
    task.progress_percent = round(ratio * 100)
    task.spent_cost = round(estimate_cost(task.config_json) * ratio, 2)
    task.last_synced_at = now_utc()

    if generated_count >= task.image_count:
        task.status = "completed"
        task.completed_at = now_utc()
        task.progress_percent = 100
    else:
        task.completed_at = None


def _pause_task_generation(task: Task, error_message: str) -> None:
    runtime = {**((task.config_json or {}).get("runtime") or {})}
    runtime["generationError"] = error_message
    runtime["lastErrorAt"] = now_utc().isoformat()
    task.config_json = {**(task.config_json or {}), "runtime": runtime}
    task.status = "paused"
    task.completed_at = None
    _update_generation_metrics(task, len(task.images))


def _resolve_task_api_key(task: Task, *, fallback_config_key: str = "") -> str | None:
    if task.api_key_encrypted:
        try:
            task_api_key = decrypt_secret(task.api_key_encrypted, current_app.config["ENCRYPTION_KEY"]).strip()
        except Exception:
            task_api_key = ""
        if task_api_key:
            return task_api_key

    if fallback_config_key:
        fallback_api_key = str(current_app.config.get(fallback_config_key, "") or "").strip()
        if fallback_api_key:
            return fallback_api_key

    return None


def _generate_preview_asset(task: Task, variant: dict[str, Any], ordinal: int, category: str) -> tuple[str, int]:
    if task.api_provider == "jimeng":
        return _generate_jimeng_asset(task, variant, ordinal)
    if task.api_provider != "gemini":
        raise ImageGenerationError(f"provider_not_supported:{task.api_provider}")
    api_key = _resolve_task_api_key(task, fallback_config_key="GEMINI_API_KEY")
    if not api_key:
        raise ImageGenerationError("missing_api_key")

    try:
        generated = generate_gemini_image(
            api_key=api_key,
            model=task.config_json.get("provider_model") or current_app.config["GEMINI_IMAGE_MODEL"],
            prompt=variant["prompt"],
            aspect_ratio=normalize_aspect_ratio(task.config_json.get("aspect_ratio", "1:1")),
            person_generation=current_app.config["GEMINI_PERSON_GENERATION"],
            proxy_url=current_app.config.get("GEMINI_HTTP_PROXY", ""),
        )
        save_generated_image(
            current_app.config["STORAGE_ROOT"],
            task.id,
            f"ordinal-{ordinal:06d}",
            generated["image_bytes"],
            generated["mime_type"],
        )
        return preview_data_url(generated["image_bytes"], generated["mime_type"]), 6500 + ordinal * 110
    except GeminiGenerationError as exc:
        raise ImageGenerationError(str(exc)) from exc


def _generate_jimeng_asset(task: Task, variant: dict[str, Any], ordinal: int) -> tuple[str, int]:
    if not task.api_key_encrypted:
        raise ImageGenerationError("missing_api_key")

    try:
        api_key = decrypt_secret(task.api_key_encrypted, current_app.config["ENCRYPTION_KEY"])
        generated = generate_jimeng_image(
            api_key=api_key,
            base_url=current_app.config["JIMENG_BASE_URL"],
            model=task.config_json.get("provider_model") or current_app.config["JIMENG_IMAGE_MODEL"],
            prompt=variant["prompt"],
            size=pixel_size_for_aspect_ratio(task.config_json.get("aspect_ratio", "1:1")),
            watermark=bool(task.config_json.get("jimeng_watermark", current_app.config["JIMENG_WATERMARK"])),
        )
        save_generated_image(
            current_app.config["STORAGE_ROOT"],
            task.id,
            f"ordinal-{ordinal:06d}",
            generated["image_bytes"],
            generated["mime_type"],
        )
        return preview_data_url(generated["image_bytes"], generated["mime_type"]), 7200 + ordinal * 120
    except JimengGenerationError as exc:
        raise ImageGenerationError(str(exc)) from exc


def build_dashboard_summary(tasks: list[Task]) -> dict[str, Any]:
    completed = sum(1 for task in tasks if task.status == "completed")
    running = sum(1 for task in tasks if task.status == "running")
    draft = sum(1 for task in tasks if task.status == "draft")
    total_images = sum(int(task.images_generated or 0) for task in tasks)
    cost_to_date = round(sum(float(task.spent_cost or 0.0) for task in tasks), 2)
    return _build_dashboard_summary_payload(
        total_tasks=len(tasks),
        running_tasks=running,
        completed_tasks=completed,
        draft_tasks=draft,
        total_images=total_images,
        cost_to_date=cost_to_date,
    )


def build_dashboard_summary_for_user(user_id: str) -> dict[str, Any]:
    summary = db.session.execute(
        select(
            func.count(Task.id),
            func.coalesce(func.sum(case((Task.status == "running", 1), else_=0)), 0),
            func.coalesce(func.sum(case((Task.status == "completed", 1), else_=0)), 0),
            func.coalesce(func.sum(case((Task.status == "draft", 1), else_=0)), 0),
            func.coalesce(func.sum(Task.images_generated), 0),
            func.coalesce(func.sum(Task.spent_cost), 0.0),
        ).where(Task.user_id == user_id)
    ).one()
    return _build_dashboard_summary_payload(
        total_tasks=int(summary[0] or 0),
        running_tasks=int(summary[1] or 0),
        completed_tasks=int(summary[2] or 0),
        draft_tasks=int(summary[3] or 0),
        total_images=int(summary[4] or 0),
        cost_to_date=round(float(summary[5] or 0.0), 2),
    )


def _build_dashboard_summary_payload(
    *,
    total_tasks: int,
    running_tasks: int,
    completed_tasks: int,
    draft_tasks: int,
    total_images: int,
    cost_to_date: float,
) -> dict[str, Any]:
    return {
        "totalTasks": total_tasks,
        "runningTasks": running_tasks,
        "completedTasks": completed_tasks,
        "draftTasks": draft_tasks,
        "totalImages": total_images,
        "avgCompletionMinutes": 27,
        "successRate": 98.7,
        "costToDate": cost_to_date,
    }
