from __future__ import annotations

from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any
import zipfile

from flask import Blueprint, current_app, jsonify, request, send_file
from flask_jwt_extended import get_jwt_identity, jwt_required
from sqlalchemy import func
from sqlalchemy.orm import raiseload

from app.extensions import db
from app.models import Dataset, DatasetExport, DatasetImage, DatasetTask, ModelProfile, generate_uuid
from app.schemas import (
    AnnotationUpdateSchema,
    DatasetExportSchema,
    DatasetImageDeleteSchema,
    DatasetSchema,
    DatasetSelectionSchema,
    GenerationTaskSchema,
    PromptPreviewSchema,
    RoboflowImportSchema,
    SubjectAssistSchema,
    TaskActionSchema,
    VideoImportSchema,
)
from app.services.annotation_storage import (
    annotation_path,
    extract_detection_categories,
    save_annotation_result,
)
from app.services.dataset_export_service import get_dataset_archive_path
from app.services.dataset_service import (
    build_dataset_export_payload,
    build_dataset_detail_payload,
    build_dataset_image_payload,
    build_dataset_list_payload,
    build_dataset_payload,
    build_dataset_summary,
    build_dataset_task_summary_payload,
    dataset_has_selected_images,
    next_dataset_export_version,
    next_dataset_ordinal,
    now_utc,
    sample_pool_split_map_for_images,
    selected_original_image_ids,
    sync_dataset,
    sync_dataset_stats_from_db,
    sync_dataset_task_stats_from_db,
)
from app.services.image_storage import (
    existing_generated_image,
    normalize_uploaded_image,
    preview_data_url,
    remove_generated_image_variants,
    save_generated_image,
)
from app.services.model_profile_service import _resolved_profile_api_key
from app.services.prompt_engine import build_prompt_preview, estimate_cost
from app.services.roboflow_import_service import RoboflowImportError, import_roboflow_dataset
from app.services.subject_assist_service import suggest_subject_fields
from app.services.video_import_service import (
    DEFAULT_VIDEO_FILENAME_PREFIX,
    DEFAULT_VIDEO_FRAME_INTERVAL,
    DEFAULT_VIDEO_FRAME_INTERVAL_MODE,
    DEFAULT_VIDEO_FRAME_INTERVAL_SECONDS,
    DEFAULT_VIDEO_JPEG_QUALITY,
    DEFAULT_VIDEO_OUTPUT_FORMAT,
    DEFAULT_VIDEO_TARGET_SIZE,
    is_allowed_video_filename,
    normalize_video_frame_interval_mode,
    normalize_video_target_size,
    sanitize_filename_prefix,
    save_video_import_source,
    video_target_size_max_dimension,
)
from app.utils.crypto import encrypt_secret

datasets_bp = Blueprint("datasets", __name__)

ALLOWED_ARCHIVE_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


def _dataset_for_user(dataset_id: str, user_id: str) -> Dataset:
    return Dataset.query.filter_by(id=dataset_id, user_id=user_id).first_or_404()


def _task_for_dataset(dataset: Dataset, task_id: str) -> DatasetTask:
    return DatasetTask.query.filter_by(id=task_id, dataset_id=dataset.id).first_or_404()


def _sync_and_payload(dataset: Dataset) -> dict:
    dataset = sync_dataset_stats_from_db(dataset)
    return build_dataset_detail_payload(dataset, include_images=False)


def _delete_dataset_image_assets(dataset: Dataset, image: DatasetImage) -> None:
    remove_generated_image_variants(
        current_app.config["STORAGE_ROOT"], dataset.id, f"image-{image.ordinal:06d}"
    )

    annotation_file = annotation_path(current_app.config["STORAGE_ROOT"], dataset.id, image.id)
    annotation_file.unlink(missing_ok=True)


def _delete_dataset_images(dataset: Dataset, images: list[DatasetImage]) -> dict:
    deleted_ids = [image.id for image in images]
    affected_task_ids = {image.source_task_id for image in images if image.source_task_id}

    for image in images:
        _delete_dataset_image_assets(dataset, image)
        db.session.delete(image)

    db.session.flush()
    sync_dataset_stats_from_db(dataset, commit=False)
    if affected_task_ids:
        affected_tasks = DatasetTask.query.filter(DatasetTask.id.in_(affected_task_ids)).all()
        for task in affected_tasks:
            sync_dataset_task_stats_from_db(task)
    db.session.commit()

    return {
        "deletedImageIds": deleted_ids,
        "deletedCount": len(deleted_ids),
        "dataset": build_dataset_detail_payload(sync_dataset_stats_from_db(dataset), include_images=False),
    }


def _max_imported_images() -> int:
    return max(1, int(current_app.config.get("MAX_IMPORTED_IMAGES", 2000)))


def _dispatch_background_task(task_callable, *args: object) -> None:
    try:
        task_callable.delay(*args)
    except Exception:
        task_name = getattr(task_callable, "name", repr(task_callable))
        current_app.logger.exception(
            "Failed to enqueue background task %s; falling back to inline execution",
            task_name,
        )
        task_callable.apply(args=args, throw=False)


@datasets_bp.post("/generation/prompt-preview")
@jwt_required()
def prompt_preview():
    payload = PromptPreviewSchema().load(request.get_json() or {})
    preview = build_prompt_preview(payload)
    return jsonify(preview)


@datasets_bp.post("/assist-subject")
@jwt_required()
def assist_subject():
    user_id = get_jwt_identity()
    payload = SubjectAssistSchema().load(request.get_json() or {})
    llm_profile = ModelProfile.query.filter_by(
        id=payload["llmProfileId"], user_id=user_id, profile_type="llm"
    ).first_or_404()

    suggestions = suggest_subject_fields(
        base_url=llm_profile.base_url or current_app.config["OPENAI_COMPAT_BASE_URL"],
        api_key=_resolved_profile_api_key(llm_profile),
        model=llm_profile.model,
        subject=payload["subject"],
    )
    return jsonify(suggestions)


@datasets_bp.get("")
@jwt_required()
def list_datasets():
    user_id = get_jwt_identity()
    datasets = (
        Dataset.query.options(
            raiseload(Dataset.images),
            raiseload(Dataset.tasks),
            raiseload(Dataset.exports),
            raiseload(Dataset.training_jobs),
        )
        .filter_by(user_id=user_id)
        .order_by(Dataset.created_at.desc())
        .all()
    )
    dataset_ids = [dataset.id for dataset in datasets]
    latest_tasks_by_dataset_id: dict[str, DatasetTask] = {}
    if dataset_ids:
        ranked_tasks = (
            db.session.query(
                DatasetTask.id.label("id"),
                func.row_number()
                .over(
                    partition_by=DatasetTask.dataset_id,
                    order_by=[DatasetTask.created_at.desc(), DatasetTask.id.desc()],
                )
                .label("row_number"),
            )
            .filter(DatasetTask.dataset_id.in_(dataset_ids))
            .subquery()
        )
        latest_tasks = (
            DatasetTask.query.options(raiseload(DatasetTask.images), raiseload(DatasetTask.dataset))
            .join(ranked_tasks, DatasetTask.id == ranked_tasks.c.id)
            .filter(ranked_tasks.c.row_number == 1)
            .all()
        )
        latest_tasks_by_dataset_id = {task.dataset_id: task for task in latest_tasks}

    return jsonify(
        {
            "datasets": [
                build_dataset_list_payload(dataset, latest_tasks_by_dataset_id.get(dataset.id))
                for dataset in datasets
            ],
            "summary": build_dataset_summary(datasets),
        }
    )


@datasets_bp.post("")
@jwt_required()
def create_dataset():
    user_id = get_jwt_identity()
    payload = DatasetSchema().load(request.get_json() or {})
    dataset = Dataset(
        user_id=user_id,
        name=payload["name"].strip(),
        description=(payload.get("description") or "").strip(),
        categories=[str(category).strip() for category in payload["categories"] if str(category).strip()],
    )
    db.session.add(dataset)
    db.session.commit()
    return jsonify({"dataset": build_dataset_payload(dataset)}), 201


def _parse_image_filter() -> dict[str, Any] | None:
    class_filter = (request.args.get("filter_class") or "").strip() or None
    split_filter = (request.args.get("filter_split") or "").strip() or None
    annotation_filter = (request.args.get("filter_annotation") or "").strip() or None
    if not class_filter and not split_filter and not annotation_filter:
        return None
    if annotation_filter not in (None, "annotated", "unannotated"):
        annotation_filter = None
    if split_filter not in (None, "train", "val", "test", "unselected"):
        split_filter = None
    return {
        "class": class_filter,
        "split": split_filter,
        "annotation": annotation_filter,
    }


@datasets_bp.get("/<dataset_id>")
@jwt_required()
def get_dataset(dataset_id: str):
    user_id = get_jwt_identity()
    dataset = (
        Dataset.query.options(
            raiseload(Dataset.images),
            raiseload(Dataset.tasks),
            raiseload(Dataset.exports),
            raiseload(Dataset.training_jobs),
        )
        .filter_by(id=dataset_id, user_id=user_id)
        .first_or_404()
    )
    dataset = sync_dataset_stats_from_db(dataset)
    image_filter = _parse_image_filter()
    try:
        images_offset = max(0, int(request.args.get("images_offset", 0)))
    except (TypeError, ValueError):
        images_offset = 0
    try:
        images_limit_raw = request.args.get("images_limit", None)
        images_limit = int(images_limit_raw) if images_limit_raw is not None else None
    except (TypeError, ValueError):
        images_limit = None
    payload = build_dataset_detail_payload(
        dataset,
        image_filter=image_filter,
        images_offset=images_offset,
        images_limit=images_limit,
    )
    return jsonify({"dataset": payload})


@datasets_bp.patch("/<dataset_id>")
@jwt_required()
def update_dataset(dataset_id: str):
    user_id = get_jwt_identity()
    payload = DatasetSchema(partial=True).load(request.get_json() or {})
    dataset = _dataset_for_user(dataset_id, user_id)

    if "name" in payload:
        dataset.name = payload["name"].strip()
    if "description" in payload:
        dataset.description = (payload.get("description") or "").strip()
    if "categories" in payload:
        dataset.categories = [str(category).strip() for category in payload["categories"] if str(category).strip()]

    db.session.commit()
    return jsonify({"dataset": _sync_and_payload(dataset)})


@datasets_bp.post("/<dataset_id>/tasks/generation")
@jwt_required()
def create_generation_task(dataset_id: str):
    user_id = get_jwt_identity()
    dataset = _dataset_for_user(dataset_id, user_id)
    payload = GenerationTaskSchema().load(request.get_json() or {})
    generation_payload = {**payload, "categories": dataset.categories}
    prompt = build_prompt_preview(generation_payload)
    task = DatasetTask(
        dataset_id=dataset.id,
        user_id=user_id,
        task_type="generation",
        task_name=(payload.get("task_name") or payload["subject"]).strip(),
        subject=payload["subject"],
        image_count=payload["image_count"],
        categories=dataset.categories,
        config_json=generation_payload,
        prompt_json=prompt,
        status=payload.get("status", "draft"),
        estimated_cost=estimate_cost(generation_payload),
        api_provider=payload["api_provider"],
        api_key_encrypted=encrypt_secret(payload["api_key"], current_app.config["ENCRYPTION_KEY"])
        if payload.get("api_key")
        else None,
    )
    db.session.add(task)
    db.session.flush()
    sync_dataset_stats_from_db(dataset, commit=False)
    db.session.commit()
    return jsonify({
        "task": build_dataset_task_summary_payload(task),
        "dataset": build_dataset_detail_payload(sync_dataset_stats_from_db(dataset), include_images=False),
    }), 201


@datasets_bp.get("/<dataset_id>/tasks/<task_id>")
@jwt_required()
def get_dataset_task(dataset_id: str, task_id: str):
    user_id = get_jwt_identity()
    dataset = sync_dataset_stats_from_db(_dataset_for_user(dataset_id, user_id))
    task = _task_for_dataset(dataset, task_id)
    return jsonify({"task": build_dataset_task_summary_payload(task)})


@datasets_bp.post("/<dataset_id>/tasks/<task_id>/start")
@jwt_required()
def start_dataset_task(dataset_id: str, task_id: str):
    user_id = get_jwt_identity()
    dataset = _dataset_for_user(dataset_id, user_id)
    task = _task_for_dataset(dataset, task_id)
    runtime = {**((task.config_json or {}).get("runtime") or {})}
    runtime.pop("generationError", None)
    runtime["startedAt"] = now_utc().isoformat()
    task.config_json = {**(task.config_json or {}), "runtime": runtime}
    task.status = "running"
    task.started_at = now_utc()
    task.completed_at = None
    db.session.commit()

    if task.task_type == "generation":
        from app.worker_tasks import generate_dataset_task_images

        _dispatch_background_task(generate_dataset_task_images, task.id)
    elif task.task_type == "augmentation":
        from app.worker_tasks import augment_dataset_task_images

        _dispatch_background_task(augment_dataset_task_images, task.id)
    elif task.task_type == "import" and (task.config_json or {}).get("source") == "video":
        from app.worker_tasks import extract_dataset_video_frames

        _dispatch_background_task(extract_dataset_video_frames, task.id)

    return jsonify({"task": build_dataset_task_summary_payload(task), "dataset": _sync_and_payload(dataset)})


@datasets_bp.post("/<dataset_id>/tasks/<task_id>/retry")
@jwt_required()
def retry_dataset_task(dataset_id: str, task_id: str):
    user_id = get_jwt_identity()
    dataset = _dataset_for_user(dataset_id, user_id)
    task = _task_for_dataset(dataset, task_id)
    runtime = {**((task.config_json or {}).get("runtime") or {})}
    runtime.pop("generationError", None)
    runtime["retriedAt"] = now_utc().isoformat()
    next_config = {**(task.config_json or {}), "runtime": runtime}
    if task.task_type == "augmentation":
        augmentation = {**((task.config_json or {}).get("augmentation") or {})}
        if augmentation:
            augmentation["status"] = "running"
            augmentation["completedImages"] = len(task.images)
            total_to_create = max(int(augmentation.get("totalImagesToCreate", task.image_count or 0)), 0)
            if total_to_create > 0:
                augmentation["progressPercent"] = min(100, round(len(task.images) / total_to_create * 100))
            else:
                augmentation["progressPercent"] = 0
            augmentation["updatedAt"] = now_utc().isoformat()
            augmentation["startedAt"] = augmentation.get("startedAt") or now_utc().isoformat()
            augmentation.pop("completedAt", None)
            augmentation.pop("error", None)
            next_config["augmentation"] = augmentation
    task.config_json = next_config
    task.status = "running"
    task.started_at = now_utc()
    task.completed_at = None
    db.session.commit()

    if task.task_type == "generation":
        from app.worker_tasks import generate_dataset_task_images

        _dispatch_background_task(generate_dataset_task_images, task.id)
    elif task.task_type == "augmentation":
        from app.worker_tasks import augment_dataset_task_images

        _dispatch_background_task(augment_dataset_task_images, task.id)
    elif task.task_type == "import" and (task.config_json or {}).get("source") == "video":
        from app.worker_tasks import extract_dataset_video_frames

        _dispatch_background_task(extract_dataset_video_frames, task.id)

    return jsonify({"task": build_dataset_task_summary_payload(task), "dataset": _sync_and_payload(dataset)})


@datasets_bp.post("/<dataset_id>/tasks/import")
@jwt_required()
def import_dataset_images(dataset_id: str):
    user_id = get_jwt_identity()
    dataset = sync_dataset(_dataset_for_user(dataset_id, user_id))
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

    task = DatasetTask(
        dataset_id=dataset.id,
        user_id=user_id,
        task_type="import",
        task_name=f"导入批次 {int(dataset.task_count or 0) + 1}",
        subject=dataset.name,
        image_count=0,
        categories=dataset.categories,
        config_json={"source": "zip"},
        prompt_json={},
        status="running",
        progress_percent=0,
        api_provider="local",
        started_at=now_utc(),
    )
    db.session.add(task)
    db.session.flush()

    imported_count = 0
    skipped_files: list[str] = []
    next_ordinal = next_dataset_ordinal(dataset)

    with zip_file:
        for member in zip_file.infolist():
            if imported_count >= _max_imported_images():
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

            image_key = f"image-{next_ordinal:06d}"
            save_generated_image(
                current_app.config["STORAGE_ROOT"],
                dataset.id,
                image_key,
                bytes(normalized["image_bytes"]),
                str(normalized["mime_type"]),
            )
            image = DatasetImage(
                dataset_id=dataset.id,
                source_task_id=task.id,
                source_type="import",
                source_ordinal=imported_count + 1,
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
            imported_count += 1
            next_ordinal += 1

    if imported_count == 0:
        db.session.rollback()
        return jsonify({"message": "压缩包中没有可导入的图片文件。"}), 400

    task.image_count = imported_count
    task.images_generated = imported_count
    task.selected_count = imported_count
    task.progress_percent = 100
    task.status = "completed"
    task.completed_at = now_utc()
    sync_dataset_task_stats_from_db(task)
    sync_dataset_stats_from_db(dataset, commit=False)
    db.session.commit()
    dataset = _dataset_for_user(dataset.id, user_id)
    return jsonify(
        {
            "summary": {
                "importedCount": imported_count,
                "skippedCount": len(skipped_files),
                "skippedFiles": skipped_files[:10],
            },
            "task": build_dataset_task_summary_payload(task),
            "dataset": build_dataset_detail_payload(dataset, include_images=False),
        }
    )


@datasets_bp.post("/<dataset_id>/tasks/import/video")
@jwt_required()
def import_dataset_video(dataset_id: str):
    user_id = get_jwt_identity()
    dataset = sync_dataset(_dataset_for_user(dataset_id, user_id))
    upload = request.files.get("video")
    if upload is None or not upload.filename:
        return jsonify({"message": "请上传一个视频文件。"}), 400
    if not is_allowed_video_filename(upload.filename):
        return jsonify(
            {"message": "只支持上传 MP4、MOV、AVI、MKV、WEBM、DAV（海康）、MPG/MPEG 或 PS 视频。"}
        ), 400

    payload = VideoImportSchema().load(request.form.to_dict() or {})
    frame_interval_mode = normalize_video_frame_interval_mode(
        payload.get("frame_interval_mode") or DEFAULT_VIDEO_FRAME_INTERVAL_MODE
    )
    frame_interval = int(payload.get("frame_interval") or DEFAULT_VIDEO_FRAME_INTERVAL)
    frame_interval_seconds = float(
        payload.get("frame_interval_seconds") or DEFAULT_VIDEO_FRAME_INTERVAL_SECONDS
    )
    output_format = str(payload.get("output_format") or DEFAULT_VIDEO_OUTPUT_FORMAT)
    jpeg_quality = int(payload.get("jpeg_quality") or DEFAULT_VIDEO_JPEG_QUALITY)
    filename_prefix = sanitize_filename_prefix(payload.get("filename_prefix") or DEFAULT_VIDEO_FILENAME_PREFIX)
    target_size = normalize_video_target_size(payload.get("target_size") or DEFAULT_VIDEO_TARGET_SIZE)
    target_max_dimension = video_target_size_max_dimension(target_size)

    task = DatasetTask(
        id=generate_uuid(),
        dataset_id=dataset.id,
        user_id=user_id,
        task_type="import",
        task_name=f"视频抽帧批次 {int(dataset.task_count or 0) + 1}",
        subject=dataset.name,
        image_count=0,
        categories=dataset.categories,
        config_json={},
        prompt_json={},
        status="running",
        progress_percent=0,
        api_provider="local",
        started_at=now_utc(),
    )

    try:
        source_path = save_video_import_source(current_app.config["STORAGE_ROOT"], task.id, upload)
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Failed to save uploaded video for dataset %s", dataset.id)
        return jsonify({"message": "视频文件保存失败，请重新上传。"}), 400

    db.session.add(task)
    task.config_json = {
        "source": "video",
        "sourcePath": source_path,
        "video": {
            "filename": Path(upload.filename).name,
            "frameIntervalMode": frame_interval_mode,
            "frameInterval": frame_interval,
            "frameIntervalSeconds": frame_interval_seconds,
            "outputFormat": output_format,
            "jpegQuality": jpeg_quality,
            "filenamePrefix": filename_prefix,
            "targetSize": target_size,
            "targetMaxDimension": target_max_dimension,
            "status": "running",
            "startedAt": now_utc().isoformat(),
            "updatedAt": now_utc().isoformat(),
        },
    }
    db.session.flush()
    sync_dataset_stats_from_db(dataset, commit=False)
    db.session.commit()

    from app.worker_tasks import extract_dataset_video_frames

    _dispatch_background_task(extract_dataset_video_frames, task.id)
    dataset = _dataset_for_user(dataset.id, user_id)
    task = _task_for_dataset(dataset, task.id)
    return (
        jsonify(
            {
                "summary": {
                    "importedCount": task.images_generated,
                    "status": task.status,
                    "source": "video",
                },
                "task": build_dataset_task_summary_payload(task),
                "dataset": build_dataset_detail_payload(dataset, include_images=False),
            }
        ),
        201,
    )


@datasets_bp.post("/<dataset_id>/tasks/import/roboflow")
@jwt_required()
def import_roboflow_dataset_images(dataset_id: str):
    user_id = get_jwt_identity()
    payload = RoboflowImportSchema().load(request.get_json() or {})
    dataset = sync_dataset(_dataset_for_user(dataset_id, user_id))
    api_key = payload["apiKey"].strip()
    workspace = payload["workspace"].strip()
    project = payload["project"].strip()
    version = payload["version"].strip()
    if not api_key or not workspace or not project or not version:
        return jsonify({"message": "请填写 Roboflow API Key、workspace、project 和 version。"}), 400

    try:
        summary = import_roboflow_dataset(
            dataset=dataset,
            user_id=user_id,
            api_key=api_key,
            workspace=workspace,
            project=project,
            version=version,
            model_format=payload["format"],
        )
    except RoboflowImportError as exc:
        db.session.rollback()
        return jsonify({"message": str(exc)}), 400

    dataset = _dataset_for_user(dataset.id, user_id)
    task = (
        DatasetTask.query.filter_by(dataset_id=dataset.id, task_type="import")
        .order_by(DatasetTask.created_at.desc(), DatasetTask.id.desc())
        .first()
    )
    return jsonify(
        {
            "summary": summary,
            "task": build_dataset_task_summary_payload(task),
            "dataset": build_dataset_detail_payload(dataset, include_images=False),
        }
    )


@datasets_bp.post("/<dataset_id>/tasks/augmentation")
@jwt_required()
def create_augmentation_task(dataset_id: str):
    user_id = get_jwt_identity()
    dataset = sync_dataset(_dataset_for_user(dataset_id, user_id))
    action = TaskActionSchema().load(request.get_json() or {})

    source_image_ids = selected_original_image_ids(dataset.id)
    source_count = len(source_image_ids)
    if source_count <= 0:
        return (
            jsonify({"message": "当前没有可增强的原始图片。请先保留至少 1 张非增强图片。"}),
            400,
        )

    estimated_added_images = source_count * max(action["multiplier"] - 1, 0)
    if estimated_added_images <= 0:
        return jsonify({"message": "增强倍数至少要让样本数量增加。"}), 400

    task = DatasetTask(
        dataset_id=dataset.id,
        user_id=user_id,
        task_type="augmentation",
        task_name=f"增强批次 {int(dataset.task_count or 0) + 1}",
        subject=dataset.name,
        image_count=estimated_added_images,
        categories=dataset.categories,
        config_json={
            "augmentation": {
                "multiplier": action["multiplier"],
                "methods": action["augmentation_methods"],
                "settings": action["augmentation_settings"],
                "sourceScope": "selected_original",
                "sourceCount": source_count,
                "sourceImageIds": source_image_ids,
                "estimatedAddedImages": estimated_added_images,
                "totalImagesToCreate": estimated_added_images,
                "completedImages": 0,
                "progressPercent": 0,
                "status": "running",
                "startedAt": now_utc().isoformat(),
                "updatedAt": now_utc().isoformat(),
            }
        },
        prompt_json={},
        status="running",
        progress_percent=0,
        api_provider="local",
        started_at=now_utc(),
    )
    db.session.add(task)
    db.session.flush()
    sync_dataset_stats_from_db(dataset, commit=False)
    db.session.commit()

    from app.worker_tasks import augment_dataset_task_images

    _dispatch_background_task(augment_dataset_task_images, task.id)
    return jsonify({
        "task": build_dataset_task_summary_payload(task),
        "dataset": build_dataset_detail_payload(dataset, include_images=False),
    }), 201


@datasets_bp.post("/<dataset_id>/annotate")
@jwt_required()
def annotate_dataset(dataset_id: str):
    user_id = get_jwt_identity()
    action = TaskActionSchema().load(request.get_json() or {})
    dataset = sync_dataset(_dataset_for_user(dataset_id, user_id))

    annotation = dataset.annotation_json or {}
    if annotation.get("status") == "running":
        updated_at_raw = annotation.get("updatedAt")
        if updated_at_raw:
            try:
                last = datetime.fromisoformat(str(updated_at_raw))
                if (now_utc() - last).total_seconds() > 600:
                    annotation["status"] = "failed"
                    annotation["error"] = "timeout_or_interrupted"
                    dataset.annotation_json = annotation
                    db.session.commit()
            except ValueError:
                pass

    vl_config = {
        "provider": current_app.config.get("VL_ANNOTATOR_PROVIDER", "gemini"),
        "model": current_app.config.get("VL_ANNOTATOR_MODEL", "gemini-2.0-flash"),
        "api_key": current_app.config.get("VL_ANNOTATOR_API_KEY", ""),
        "base_url": current_app.config.get("VL_ANNOTATOR_BASE_URL", ""),
    }

    from app.worker_tasks import annotate_dataset_images_task

    _dispatch_background_task(
        annotate_dataset_images_task,
        dataset.id,
        action["confidence_threshold"],
        vl_config,
        action["skip_annotated"],
    )
    dataset.annotation_json = {
        **annotation,
        "provider": "vl-auto" if vl_config.get("api_key") else "local-fallback",
        "vlProvider": vl_config.get("provider", "gemini") if vl_config.get("api_key") else "local",
        "confidenceThreshold": action["confidence_threshold"],
        "status": "running",
        "updatedAt": now_utc().isoformat(),
    }
    db.session.commit()
    return jsonify({"summary": dataset.annotation_json, "dataset": build_dataset_detail_payload(dataset, include_images=False)})


@datasets_bp.get("/<dataset_id>/images/<image_id>/preview")
@jwt_required()
def preview_dataset_image(dataset_id: str, image_id: str):
    user_id = get_jwt_identity()
    dataset = _dataset_for_user(dataset_id, user_id)
    image = DatasetImage.query.filter_by(id=image_id, dataset_id=dataset.id).first()
    if image is None:
        return jsonify({"message": "image not found"}), 404

    path = existing_generated_image(current_app.config["STORAGE_ROOT"], dataset.id, f"image-{image.ordinal:06d}")
    if path is None:
        return jsonify({"message": "image file not found"}), 404
    mimetype = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    return send_file(path, mimetype=mimetype)


@datasets_bp.delete("/<dataset_id>/images/<image_id>")
@jwt_required()
def delete_dataset_image(dataset_id: str, image_id: str):
    user_id = get_jwt_identity()
    dataset = _dataset_for_user(dataset_id, user_id)
    image = DatasetImage.query.filter_by(id=image_id, dataset_id=dataset.id).first()
    if image is None:
        return jsonify({"message": "image not found"}), 404

    return jsonify(_delete_dataset_images(dataset, [image]))


@datasets_bp.delete("/<dataset_id>/images")
@jwt_required()
def delete_dataset_images(dataset_id: str):
    user_id = get_jwt_identity()
    payload = DatasetImageDeleteSchema().load(request.get_json() or {})
    image_ids = list(dict.fromkeys(payload["image_ids"]))
    dataset = _dataset_for_user(dataset_id, user_id)
    images = DatasetImage.query.filter(
        DatasetImage.dataset_id == dataset.id,
        DatasetImage.id.in_(image_ids),
    ).all()
    image_by_id = {image.id: image for image in images}
    missing_ids = [image_id for image_id in image_ids if image_id not in image_by_id]
    if missing_ids:
        return jsonify({"message": "one or more images not found"}), 404

    return jsonify(_delete_dataset_images(dataset, [image_by_id[image_id] for image_id in image_ids]))


@datasets_bp.patch("/<dataset_id>/images/<image_id>/annotations")
@jwt_required()
def update_dataset_image_annotations(dataset_id: str, image_id: str):
    user_id = get_jwt_identity()
    payload = AnnotationUpdateSchema().load(request.get_json() or {})
    dataset = _dataset_for_user(dataset_id, user_id)
    image = DatasetImage.query.filter_by(id=image_id, dataset_id=dataset.id).first()
    if image is None:
        return jsonify({"message": "image not found"}), 404

    detections = payload["detections"]
    save_annotation_result(current_app.config["STORAGE_ROOT"], dataset.id, image.id, detections)
    image.annotation_status = "annotated" if detections else "empty"
    image.confidence_score = max([float(detection["confidence"]) for detection in detections], default=None)
    image.detection_categories = extract_detection_categories(
        current_app.config["STORAGE_ROOT"], dataset.id, image.id
    )

    annotation_summary = {**(dataset.annotation_json or {})}
    annotation_summary["updatedAt"] = now_utc().isoformat()
    annotation_summary["manualEdits"] = int(annotation_summary.get("manualEdits", 0)) + 1
    dataset.annotation_json = annotation_summary
    db.session.commit()
    return jsonify(
        {
            "dataset": build_dataset_detail_payload(dataset, include_images=False),
            "image": build_dataset_image_payload(
                dataset,
                image,
                split_map=sample_pool_split_map_for_images(
                    dataset.id,
                    [image],
                    selected_count=int(dataset.selected_count or 0),
                ),
            ),
        }
    )


@datasets_bp.patch("/<dataset_id>/selection")
@jwt_required()
def update_dataset_selection(dataset_id: str):
    user_id = get_jwt_identity()
    payload = DatasetSelectionSchema().load(request.get_json() or {})
    dataset = _dataset_for_user(dataset_id, user_id)

    if payload["mode"] == "single":
        image = DatasetImage.query.filter_by(id=payload.get("image_id"), dataset_id=dataset.id).first()
        if image is None:
            return jsonify({"message": "image not found"}), 404
        image.selected = bool(payload.get("selected"))
    else:
        selection_query = DatasetImage.query.filter(DatasetImage.dataset_id == dataset.id)
        scoped_ids = payload.get("image_ids")
        if scoped_ids is not None:
            scoped_id_set = set(scoped_ids)
            found_count = (
                db.session.query(func.count(DatasetImage.id))
                .filter(DatasetImage.dataset_id == dataset.id)
                .filter(DatasetImage.id.in_(scoped_id_set))
                .scalar()
                or 0
            )
            if int(found_count) != len(scoped_id_set):
                return jsonify({"message": "one or more images not found"}), 404
            selection_query = selection_query.filter(DatasetImage.id.in_(scoped_id_set))
        elif payload.get("scope") == "unannotated_unretained":
            selection_query = (
                selection_query.filter(DatasetImage.selected.is_(False))
                .filter(~DatasetImage.annotation_status.in_(["annotated", "empty"]))
            )

        if payload["mode"] == "all":
            selection_query.update({DatasetImage.selected: True}, synchronize_session=False)
        elif payload["mode"] == "none":
            selection_query.update({DatasetImage.selected: False}, synchronize_session=False)
        elif payload["mode"] == "invert":
            selection_query.update(
                {DatasetImage.selected: ~DatasetImage.selected},
                synchronize_session=False,
            )

    db.session.flush()
    affected_tasks = DatasetTask.query.filter_by(dataset_id=dataset.id).all()
    for task in affected_tasks:
        sync_dataset_task_stats_from_db(task)
    sync_dataset_stats_from_db(dataset, commit=False)
    db.session.commit()
    return jsonify({"dataset": build_dataset_detail_payload(sync_dataset_stats_from_db(dataset), include_images=False)})


@datasets_bp.post("/<dataset_id>/export")
@jwt_required()
def export_dataset(dataset_id: str):
    user_id = get_jwt_identity()
    action = DatasetExportSchema().load(request.get_json() or {})
    dataset = sync_dataset(_dataset_for_user(dataset_id, user_id))
    if not dataset_has_selected_images(dataset.id):
        return jsonify({"message": "no images selected for export"}), 400

    version = next_dataset_export_version(dataset)
    export_job = DatasetExport(
        dataset_id=dataset.id,
        version=version,
        export_format=action["export_format"],
        status="pending",
        download_url=f"{current_app.config['API_PREFIX']}/datasets/{dataset.id}/exports/{version}/download",
        summary_json={
            "imageFormat": action["image_format"],
            "includeReadme": action["include_readme"],
            "structure": "yolov8" if action["export_format"] == "yolo" else action["export_format"],
            "estimatedSizeMb": round(max(dataset.image_count, 1) * 0.6, 1),
        },
    )
    db.session.add(export_job)
    db.session.flush()

    from app.worker_tasks import export_dataset_archive

    _dispatch_background_task(export_dataset_archive, export_job.id)
    db.session.commit()
    return jsonify({
        "export": build_dataset_export_payload(export_job),
        "dataset": build_dataset_detail_payload(dataset, include_images=False),
    }), 201


@datasets_bp.get("/<dataset_id>/exports/<int:version>/download")
@jwt_required()
def download_export(dataset_id: str, version: int):
    user_id = get_jwt_identity()
    dataset = _dataset_for_user(dataset_id, user_id)
    export_job = (
        DatasetExport.query.filter_by(dataset_id=dataset.id, version=version)
        .order_by(DatasetExport.created_at.desc())
        .first_or_404()
    )
    archive_path = get_dataset_archive_path(current_app.config["STORAGE_ROOT"], export_job)
    return send_file(
        archive_path,
        as_attachment=True,
        download_name=f"{dataset.name.replace(' ', '-').lower()}-v{version}.zip",
        mimetype="application/zip",
    )
