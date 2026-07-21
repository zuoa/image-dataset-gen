from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from flask import current_app
from werkzeug.datastructures import FileStorage

from app.extensions import db
from app.models import Dataset, DatasetImage, DatasetTask
from app.services.dataset_service import (
    now_utc,
    reserve_dataset_ordinals,
    sync_dataset_stats_from_db,
    sync_dataset_task_stats_from_db,
)
from app.services.image_storage import (
    normalize_uploaded_image,
    preview_data_url,
    save_generated_image,
)
from app.services.storage_backend import register_local_asset


UPLOAD_IMAGE_SUFFIXES = {".bmp", ".gif", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"}


class DatasetUploadImportError(RuntimeError):
    pass


@dataclass
class PreparedUploadImage:
    name: str
    image_bytes: bytes
    mime_type: str
    width: int
    height: int


def is_allowed_upload_image_filename(filename: str) -> bool:
    return Path(filename or "").suffix.lower() in UPLOAD_IMAGE_SUFFIXES


def prepare_uploaded_image(upload: FileStorage) -> PreparedUploadImage | None:
    """Read and normalize a single uploaded image. Returns ``None`` on decode failure."""
    data = upload.read()
    normalized = normalize_uploaded_image(data)
    if normalized is None:
        return None
    return PreparedUploadImage(
        name=upload.filename or "image",
        image_bytes=bytes(normalized["image_bytes"]),
        mime_type=str(normalized["mime_type"]),
        width=int(normalized["width"]),
        height=int(normalized["height"]),
    )


def import_uploaded_images(
    *,
    dataset: Dataset,
    user_id: str,
    uploads: list[FileStorage],
) -> dict[str, Any]:
    """Synchronously persist one or more uploaded images into a dataset.

    Mirrors the archive import pipeline (normalize -> reserve ordinals -> save
    image -> register asset -> create ``DatasetImage``) but runs inline because
    single-image batches are small. One ``import`` task (source=``upload``)
    wraps the batch and is completed immediately.
    """
    prepared: list[PreparedUploadImage] = []
    skipped: list[str] = []
    for upload in uploads:
        filename = upload.filename or ""
        if not filename or not is_allowed_upload_image_filename(filename):
            skipped.append(filename or "unknown")
            continue
        item = prepare_uploaded_image(upload)
        if item is None:
            skipped.append(filename)
            continue
        prepared.append(item)

    if not prepared:
        raise DatasetUploadImportError("没有可导入的图片文件，请检查文件格式。")

    storage_root = current_app.config["STORAGE_ROOT"]
    task = DatasetTask(
        dataset_id=dataset.id,
        user_id=user_id,
        task_type="import",
        task_name=f"图片上传批次 {int(dataset.task_count or 0) + 1}",
        subject=dataset.name,
        image_count=len(prepared),
        categories=dataset.categories,
        config_json={
            "source": "upload",
            "filenames": [item.name for item in prepared],
        },
        prompt_json={},
        status="running",
        progress_percent=0,
        api_provider="local",
        started_at=now_utc(),
    )
    db.session.add(task)
    db.session.flush()

    next_ordinal = reserve_dataset_ordinals(dataset, len(prepared))
    for offset, item in enumerate(prepared):
        source_ordinal = offset + 1
        image_key = f"image-{next_ordinal:06d}"
        saved_path = save_generated_image(
            storage_root,
            dataset.id,
            image_key,
            item.image_bytes,
            item.mime_type,
        )
        image = DatasetImage(
            dataset_id=dataset.id,
            source_task_id=task.id,
            source_type="import",
            source_ordinal=source_ordinal,
            ordinal=next_ordinal,
            status="uploaded",
            seed=800000 + next_ordinal,
            prompt_text=f"uploaded image: {item.name}",
            diversity_vars={"composition": "uploaded asset", "importSplit": ""},
            latency_ms=0,
            preview_svg=preview_data_url(item.image_bytes, item.mime_type),
            selected=True,
            annotation_status="pending",
            asset=register_local_asset(
                storage_root,
                saved_path,
                user_id=user_id,
                dataset_id=dataset.id,
                kind="dataset_image",
                mime_type=item.mime_type,
                original_filename=item.name,
                width=item.width,
                height=item.height,
            ),
        )
        db.session.add(image)
        next_ordinal += 1

    db.session.flush()
    sync_dataset_task_stats_from_db(task)
    sync_dataset_stats_from_db(dataset, commit=False)
    db.session.commit()

    return {
        "importedCount": len(prepared),
        "skippedCount": len(skipped),
        "skippedFiles": skipped[:10],
        "status": "completed",
        "source": "upload",
        "taskId": task.id,
    }
