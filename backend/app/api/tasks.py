from __future__ import annotations

from io import BytesIO
from pathlib import Path
import zipfile

from flask import Blueprint, current_app, jsonify, request, send_file
from flask_jwt_extended import get_jwt_identity, jwt_required

from app.clients.annotator_client import annotate_task_images
from app.extensions import db
from app.models import ModelProfile, Task, TaskExport
from app.schemas import (
    AnnotationUpdateSchema,
    PromptPreviewSchema,
    SelectionSchema,
    SubjectAssistSchema,
    TaskActionSchema,
    TaskSchema,
)
from app.services.annotation_storage import save_annotation_result
from app.services.export_service import build_export_archive, get_archive_path
from app.services.image_storage import existing_generated_image, normalize_uploaded_image, preview_data_url, save_generated_image
from app.services.prompt_engine import build_prompt_preview, estimate_cost
from app.services.subject_assist_service import suggest_subject_fields
from app.services.task_service import (
    build_dashboard_summary,
    build_export_payload,
    build_task_payload,
    generate_task_name,
    now_utc,
    sync_task_progress,
)
from app.utils.crypto import decrypt_secret, encrypt_secret

tasks_bp = Blueprint("tasks", __name__)
ALLOWED_ARCHIVE_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
MAX_IMPORTED_IMAGES = 200


def _task_for_user(task_id: str, user_id: str) -> Task:
    return Task.query.filter_by(id=task_id, user_id=user_id).first_or_404()


@tasks_bp.post("/prompt-preview")
@jwt_required()
def prompt_preview():
    payload = PromptPreviewSchema().load(request.get_json() or {})
    preview = build_prompt_preview(payload)
    return jsonify(preview)


@tasks_bp.post("/assist-subject")
@jwt_required()
def assist_subject():
    user_id = get_jwt_identity()
    payload = SubjectAssistSchema().load(request.get_json() or {})
    llm_profile = ModelProfile.query.filter_by(
        id=payload["llmProfileId"], user_id=user_id, profile_type="llm"
    ).first_or_404()

    suggestions = suggest_subject_fields(
        base_url=llm_profile.base_url or current_app.config["OPENAI_COMPAT_BASE_URL"],
        api_key=decrypt_secret(llm_profile.api_key_encrypted, current_app.config["ENCRYPTION_KEY"]),
        model=llm_profile.model,
        subject=payload["subject"],
    )
    return jsonify(suggestions)


@tasks_bp.get("")
@jwt_required()
def list_tasks():
    user_id = get_jwt_identity()
    tasks = Task.query.filter_by(user_id=user_id).order_by(Task.created_at.desc()).all()
    hydrated_tasks = [build_task_payload(sync_task_progress(task)) for task in tasks]
    return jsonify({"tasks": hydrated_tasks, "summary": build_dashboard_summary(tasks)})


@tasks_bp.post("")
@jwt_required()
def create_task():
    user_id = get_jwt_identity()
    payload = TaskSchema().load(request.get_json() or {})
    prompt = build_prompt_preview(payload)
    task = Task(
        user_id=user_id,
        task_name=payload.get("task_name") or generate_task_name(payload["subject"]),
        subject=payload["subject"],
        categories=payload["categories"],
        image_count=payload["image_count"],
        config_json=payload,
        prompt_json=prompt,
        status=payload.get("status", "draft"),
        estimated_cost=estimate_cost(payload),
        api_provider=payload["api_provider"],
        api_key_encrypted=encrypt_secret(payload["api_key"], current_app.config["ENCRYPTION_KEY"]),
    )
    db.session.add(task)
    db.session.commit()
    return jsonify({"task": build_task_payload(task)}), 201


@tasks_bp.get("/<task_id>")
@jwt_required()
def get_task(task_id: str):
    user_id = get_jwt_identity()
    task = _task_for_user(task_id, user_id)
    task = sync_task_progress(task)
    return jsonify({"task": build_task_payload(task)})


@tasks_bp.patch("/<task_id>")
@jwt_required()
def update_task(task_id: str):
    user_id = get_jwt_identity()
    payload = TaskSchema(partial=True).load(request.get_json() or {})
    task = _task_for_user(task_id, user_id)

    merged = {**(task.config_json or {}), **payload}
    if payload:
        task.config_json = merged
        if "subject" in merged:
            task.subject = merged["subject"]
            task.task_name = merged.get("task_name") or generate_task_name(merged["subject"])
        if "categories" in merged:
            task.categories = merged["categories"]
        if "image_count" in merged:
            task.image_count = merged["image_count"]
        if "api_provider" in merged:
            task.api_provider = merged["api_provider"]
        if payload.get("api_key"):
            task.api_key_encrypted = encrypt_secret(
                payload["api_key"], current_app.config["ENCRYPTION_KEY"]
            )
        task.prompt_json = build_prompt_preview(merged)
        task.estimated_cost = estimate_cost(merged)

    db.session.commit()
    return jsonify({"task": build_task_payload(task)})


@tasks_bp.post("/<task_id>/start")
@jwt_required()
def start_task(task_id: str):
    user_id = get_jwt_identity()
    task = _task_for_user(task_id, user_id)
    task.status = "running"
    task.started_at = now_utc()
    db.session.commit()
    task = sync_task_progress(task)
    return jsonify({"task": build_task_payload(task)})


@tasks_bp.post("/<task_id>/retry")
@jwt_required()
def retry_task(task_id: str):
    user_id = get_jwt_identity()
    task = _task_for_user(task_id, user_id)
    runtime = {**((task.config_json or {}).get("runtime") or {})}
    runtime.pop("generationError", None)
    runtime["retriedAt"] = now_utc().isoformat()
    task.config_json = {**(task.config_json or {}), "runtime": runtime}
    task.status = "running"
    task.started_at = now_utc()
    db.session.commit()
    task = sync_task_progress(task)
    return jsonify({"task": build_task_payload(task)})


@tasks_bp.post("/<task_id>/augment")
@jwt_required()
def augment_task(task_id: str):
    user_id = get_jwt_identity()
    action = TaskActionSchema().load(request.get_json() or {})
    task = sync_task_progress(_task_for_user(task_id, user_id))
    augmentation = ((task.config_json or {}).get("augmentation") or {})
    if augmentation.get("status") == "running":
        return jsonify({"message": "增强任务仍在进行中，请等待当前批次完成。"}), 400

    source_images = [image for image in task.images if image.selected and image.status != "augmented"]
    source_count = len(source_images)
    if source_count <= 0:
        return (
            jsonify({"message": "当前没有可增强的原始图片。增强只会基于原始图片执行，请先保留至少 1 张原始图片。"}),
            400,
        )

    estimated_added_images = source_count * max(action["multiplier"] - 1, 0)
    simulated_output = task.images_generated + estimated_added_images
    task.config_json = {
        **(task.config_json or {}),
        "augmentation": {
            "multiplier": action["multiplier"],
            "methods": action["augmentation_methods"],
            "sourceCount": source_count,
            "sourceImageIds": [image.id for image in source_images],
            "estimatedAddedImages": estimated_added_images,
            "simulatedOutput": simulated_output,
            "totalImagesToCreate": estimated_added_images,
            "completedImages": 0,
            "progressPercent": 0,
            "status": "running",
            "startedAt": now_utc().isoformat(),
            "updatedAt": now_utc().isoformat(),
        },
    }
    db.session.commit()
    task = sync_task_progress(task)
    return jsonify(
        {
            "summary": task.config_json["augmentation"],
            "task": build_task_payload(task),
        }
    )


@tasks_bp.post("/<task_id>/import-images")
@jwt_required()
def import_task_images(task_id: str):
    user_id = get_jwt_identity()
    task = sync_task_progress(_task_for_user(task_id, user_id))
    archive = request.files.get("archive")
    if archive is None or not archive.filename:
        return jsonify({"message": "请上传一个 ZIP 压缩包。"}), 400
    if not archive.filename.lower().endswith(".zip"):
        return jsonify({"message": "只支持上传 ZIP 压缩包。"}), 400

    archive_bytes = archive.read()
    if not archive_bytes:
        return jsonify({"message": "上传的 ZIP 压缩包为空。"}), 400

    try:
        zip_file = zipfile.ZipFile(BytesIO(archive_bytes))
    except zipfile.BadZipFile:
        return jsonify({"message": "无法解析 ZIP 压缩包。"}), 400

    imported_count = 0
    skipped_files: list[str] = []
    next_ordinal = max((image.ordinal for image in task.images), default=0) + 1

    with zip_file:
        for member in zip_file.infolist():
            if imported_count >= MAX_IMPORTED_IMAGES:
                break
            if member.is_dir():
                continue
            suffix = Path(member.filename).suffix.lower()
            if suffix not in ALLOWED_ARCHIVE_IMAGE_EXTENSIONS:
                skipped_files.append(Path(member.filename).name)
                continue

            normalized = normalize_uploaded_image(zip_file.read(member))
            if normalized is None:
                skipped_files.append(Path(member.filename).name)
                continue

            image_key = f"ordinal-{next_ordinal:06d}"
            save_generated_image(
                current_app.config["STORAGE_ROOT"],
                task.id,
                image_key,
                bytes(normalized["image_bytes"]),
                str(normalized["mime_type"]),
            )
            image = TaskImage(
                task_id=task.id,
                ordinal=next_ordinal,
                status="uploaded",
                seed=700000 + next_ordinal,
                prompt_text=f"uploaded image: {Path(member.filename).name}",
                diversity_vars={"composition": "uploaded asset"},
                latency_ms=0,
                preview_svg=preview_data_url(bytes(normalized["image_bytes"]), str(normalized["mime_type"])),
                selected=True,
                annotation_status="pending",
                confidence_score=None,
            )
            db.session.add(image)
            task.images.append(image)
            imported_count += 1
            next_ordinal += 1

    if imported_count == 0:
        return jsonify({"message": "压缩包中没有可导入的图片文件。"}), 400

    task.images_generated = len(task.images)
    task.selected_count = sum(1 for image in task.images if image.selected)
    if task.image_count > 0:
        task.progress_percent = min(100, round(min(task.images_generated, task.image_count) / task.image_count * 100))
    if task.status == "running" and task.images_generated >= task.image_count:
        task.status = "completed"
        task.completed_at = now_utc()
        task.progress_percent = 100

    db.session.commit()
    task = _task_for_user(task_id, user_id)
    return jsonify(
        {
            "summary": {
                "importedCount": imported_count,
                "skippedCount": len(skipped_files),
                "skippedFiles": skipped_files[:10],
            },
            "task": build_task_payload(task),
        }
    )


@tasks_bp.post("/<task_id>/annotate")
@jwt_required()
def annotate_task(task_id: str):
    user_id = get_jwt_identity()
    action = TaskActionSchema().load(request.get_json() or {})
    task = sync_task_progress(_task_for_user(task_id, user_id))
    results = annotate_task_images(
        task,
        confidence_threshold=action["confidence_threshold"],
        annotator_url=current_app.config["ANNOTATOR_URL"],
    )

    images_by_id = {image.id: image for image in task.images}
    detected_images = 0
    empty_labels = 0

    for result in results:
        image = images_by_id.get(result["imageId"])
        if not image:
            continue
        detections = result.get("detections", [])
        save_annotation_result(current_app.config["STORAGE_ROOT"], task.id, image.id, detections)
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
        "provider": "annotator-microservice" if current_app.config["ANNOTATOR_URL"] else "local-fallback",
        "confidenceThreshold": action["confidence_threshold"],
        "detectedImages": detected_images,
        "emptyLabels": empty_labels,
        "format": "yolo",
        "updatedAt": now_utc().isoformat(),
    }
    task.config_json = {**(task.config_json or {}), "annotation": annotation_summary}
    db.session.commit()
    return jsonify({"summary": annotation_summary, "task": build_task_payload(task)})


@tasks_bp.get("/<task_id>/images/<image_id>/preview")
@jwt_required()
def preview_task_image(task_id: str, image_id: str):
    user_id = get_jwt_identity()
    task = _task_for_user(task_id, user_id)
    image = next((candidate for candidate in task.images if candidate.id == image_id), None)
    if image is None:
        return jsonify({"message": "image not found"}), 404
    path = existing_generated_image(current_app.config["STORAGE_ROOT"], task.id, f"ordinal-{image.ordinal:06d}")
    if path is None:
        return jsonify({"message": "image file not found"}), 404
    mimetype = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    return send_file(path, mimetype=mimetype)


@tasks_bp.patch("/<task_id>/images/<image_id>/annotations")
@jwt_required()
def update_image_annotations(task_id: str, image_id: str):
    user_id = get_jwt_identity()
    payload = AnnotationUpdateSchema().load(request.get_json() or {})
    task = _task_for_user(task_id, user_id)
    image = next((candidate for candidate in task.images if candidate.id == image_id), None)
    if image is None:
        return jsonify({"message": "image not found"}), 404

    detections = payload["detections"]
    save_annotation_result(current_app.config["STORAGE_ROOT"], task.id, image.id, detections)
    image.annotation_status = "annotated" if detections else "empty"
    image.confidence_score = max(
        [float(detection["confidence"]) for detection in detections],
        default=None,
    )

    annotation_summary = {**((task.config_json or {}).get("annotation") or {})}
    annotation_summary["updatedAt"] = now_utc().isoformat()
    annotation_summary["manualEdits"] = int(annotation_summary.get("manualEdits", 0)) + 1
    task.config_json = {**(task.config_json or {}), "annotation": annotation_summary}

    db.session.commit()
    return jsonify({"task": build_task_payload(task)})


@tasks_bp.post("/<task_id>/export")
@jwt_required()
def export_task(task_id: str):
    user_id = get_jwt_identity()
    action = TaskActionSchema().load(request.get_json() or {})
    task = _task_for_user(task_id, user_id)
    if not any(image.selected for image in task.images):
        return jsonify({"message": "no images selected for export"}), 400

    latest_version = task.exports[0].version if task.exports else 0
    export_job = TaskExport(
        task_id=task.id,
        version=latest_version + 1,
        export_format=action["export_format"],
        download_url=f"{current_app.config['API_PREFIX']}/tasks/{task.id}/exports/{latest_version + 1}/download",
        summary_json={
            "imageFormat": action["image_format"],
            "includeReadme": action["include_readme"],
            "structure": "yolov8" if action["export_format"] == "yolo" else action["export_format"],
            "estimatedSizeMb": round(max(task.images_generated, 1) * 0.6, 1),
        },
    )
    db.session.add(export_job)
    db.session.flush()
    archive_summary = build_export_archive(
        task=task,
        export_job=export_job,
        export_format=action["export_format"],
        image_format=action["image_format"],
        include_readme=action["include_readme"],
        storage_root=current_app.config["STORAGE_ROOT"],
    )
    export_job.summary_json = archive_summary
    db.session.commit()
    return jsonify({"export": build_export_payload(export_job), "task": build_task_payload(task)}), 201


@tasks_bp.patch("/<task_id>/selection")
@jwt_required()
def update_selection(task_id: str):
    user_id = get_jwt_identity()
    payload = SelectionSchema().load(request.get_json() or {})
    task = _task_for_user(task_id, user_id)

    if payload["mode"] == "single":
        image = next((candidate for candidate in task.images if candidate.id == payload.get("image_id")), None)
        if image is None:
            return jsonify({"message": "image not found"}), 404
        image.selected = bool(payload.get("selected"))
    elif payload["mode"] == "all":
        for image in task.images:
            image.selected = True
    elif payload["mode"] == "none":
        for image in task.images:
            image.selected = False
    elif payload["mode"] == "invert":
        for image in task.images:
            image.selected = not image.selected

    task.selected_count = sum(1 for image in task.images if image.selected)
    db.session.commit()
    return jsonify({"task": build_task_payload(task)})


@tasks_bp.get("/<task_id>/exports/<int:version>/download")
@jwt_required()
def download_export(task_id: str, version: int):
    user_id = get_jwt_identity()
    task = _task_for_user(task_id, user_id)
    export_job = (
        TaskExport.query.filter_by(task_id=task.id, version=version).order_by(TaskExport.created_at.desc()).first_or_404()
    )
    archive_path = get_archive_path(current_app.config["STORAGE_ROOT"], export_job)
    return send_file(
        archive_path,
        as_attachment=True,
        download_name=f"{task.task_name.replace(' ', '-').lower()}-v{version}.zip",
        mimetype="application/zip",
    )
