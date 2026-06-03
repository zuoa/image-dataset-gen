from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any

from flask import current_app
from PIL import Image, ImageDraw, ImageFont
from werkzeug.utils import secure_filename

from app.extensions import db
from app.models import TrainingArtifact, TrainingInferenceJob, TrainingJob
from app.services.dataset_service import now_utc
from app.services.image_storage import normalize_uploaded_image, preview_data_url


class TrainingInferenceError(RuntimeError):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def create_training_inference_job(
    job: TrainingJob,
    image_bytes: bytes,
    *,
    filename: str,
    artifact_id: str = "",
    confidence_threshold: float = 0.25,
    image_size: int = 640,
) -> TrainingInferenceJob:
    normalized = normalize_uploaded_image(image_bytes)
    if normalized is None:
        raise TrainingInferenceError("请上传有效图片。", 400)

    artifact = select_model_artifact(job, artifact_id)
    artifact_path = Path(artifact.storage_path)
    if not artifact_path.exists():
        raise TrainingInferenceError("模型产物文件不存在，请重新训练或重新上传产物。", 409)

    test_job = TrainingInferenceJob(
        training_job_id=job.id,
        dataset_id=job.dataset_id,
        user_id=job.user_id,
        artifact_id=artifact.id,
        status="queued",
        confidence_threshold=confidence_threshold,
        image_size=image_size,
        input_filename=secure_filename(filename) or "test-image",
        input_mime_type=str(normalized["mime_type"]),
        input_width=int(normalized["width"]),
        input_height=int(normalized["height"]),
    )
    db.session.add(test_job)
    db.session.flush()

    extension = "png" if test_job.input_mime_type == "image/png" else "jpg"
    input_path = training_inference_root(job.id, test_job.id) / f"input.{extension}"
    input_path.parent.mkdir(parents=True, exist_ok=True)
    input_path.write_bytes(bytes(normalized["image_bytes"]))
    test_job.input_storage_path = str(input_path)
    return test_job


def complete_training_inference_job(test_job: TrainingInferenceJob, detections: object) -> None:
    normalized_detections = normalize_detections(
        detections,
        test_job.training_job.dataset.categories if test_job.training_job and test_job.training_job.dataset else [],
    )
    input_path = Path(test_job.input_storage_path)
    if not input_path.exists():
        raise TrainingInferenceError("测试图片文件不存在。", 409)

    annotated_bytes, annotated_mime_type = render_annotated_image(
        input_path.read_bytes(),
        test_job.input_mime_type,
        normalized_detections,
    )
    extension = "png" if annotated_mime_type == "image/png" else "jpg"
    output_path = training_inference_root(test_job.training_job_id, test_job.id) / f"result.{extension}"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(annotated_bytes)

    test_job.status = "completed"
    test_job.detections_json = normalized_detections
    test_job.result_mime_type = annotated_mime_type
    test_job.result_storage_path = str(output_path)
    test_job.error_message = ""
    test_job.completed_at = now_utc()


def fail_training_inference_job(test_job: TrainingInferenceJob, error: str) -> None:
    test_job.status = "failed"
    test_job.error_message = error[:2000]
    test_job.completed_at = now_utc()


def build_training_inference_payload(test_job: TrainingInferenceJob) -> dict[str, Any]:
    artifact = test_job.artifact
    payload: dict[str, Any] = {
        "id": test_job.id,
        "trainingJobId": test_job.training_job_id,
        "datasetId": test_job.dataset_id,
        "artifact": {
            "id": artifact.id if artifact else test_job.artifact_id,
            "type": artifact.artifact_type if artifact else "",
            "filename": artifact.filename if artifact else "",
        },
        "workerId": test_job.worker_id,
        "status": test_job.status,
        "confidenceThreshold": test_job.confidence_threshold,
        "imageSize": test_job.image_size,
        "image": {
            "filename": test_job.input_filename,
            "mimeType": test_job.input_mime_type,
            "width": test_job.input_width,
            "height": test_job.input_height,
        },
        "detections": test_job.detections_json or [],
        "error": test_job.error_message,
        "result": _build_result_payload(test_job),
        "createdAt": test_job.created_at.isoformat() if test_job.created_at else None,
        "updatedAt": test_job.updated_at.isoformat() if test_job.updated_at else None,
        "startedAt": test_job.started_at.isoformat() if test_job.started_at else None,
        "completedAt": test_job.completed_at.isoformat() if test_job.completed_at else None,
    }
    return payload


def render_annotated_image(
    image_bytes: bytes,
    mime_type: str,
    detections: list[dict[str, Any]],
) -> tuple[bytes, str]:
    with Image.open(BytesIO(image_bytes)) as image:
        preserve_alpha = image.mode in {"RGBA", "LA"} or "transparency" in image.info
        working = image.convert("RGBA" if preserve_alpha else "RGB")

    draw = ImageDraw.Draw(working)
    font = ImageFont.load_default()
    width, height = working.size
    line_width = max(2, round(min(width, height) * 0.006))
    palette = (
        "#0f766e",
        "#2563eb",
        "#c2410c",
        "#9333ea",
        "#16a34a",
        "#dc2626",
        "#0891b2",
        "#ca8a04",
    )

    for index, detection in enumerate(detections):
        bbox = detection.get("bbox") or []
        if len(bbox) != 4:
            continue
        x_center, y_center, box_width, box_height = [_clamp(float(value)) for value in bbox]
        left = max(0, (x_center - box_width / 2) * width)
        top = max(0, (y_center - box_height / 2) * height)
        right = min(width, (x_center + box_width / 2) * width)
        bottom = min(height, (y_center + box_height / 2) * height)
        if right <= left or bottom <= top:
            continue

        color = palette[index % len(palette)]
        draw.rectangle((left, top, right, bottom), outline=color, width=line_width)

        label = str(detection.get("category") or "object")
        confidence = detection.get("confidence")
        if isinstance(confidence, (int, float)):
            label = f"{label} {float(confidence):.2f}"
        text_box = draw.textbbox((0, 0), label, font=font)
        text_width = text_box[2] - text_box[0]
        text_height = text_box[3] - text_box[1]
        label_top = max(0, top - text_height - 8)
        label_bottom = label_top + text_height + 8
        label_right = min(width, left + text_width + 12)
        draw.rectangle((left, label_top, label_right, label_bottom), fill=color)
        draw.text((left + 6, label_top + 4), label, fill="white", font=font)

    output = BytesIO()
    if mime_type == "image/png" and working.mode == "RGBA":
        working.save(output, format="PNG")
        return output.getvalue(), "image/png"

    working.convert("RGB").save(output, format="JPEG", quality=92)
    return output.getvalue(), "image/jpeg"


def training_inference_root(training_job_id: str, test_job_id: str) -> Path:
    return Path(current_app.config["STORAGE_ROOT"]) / "training" / training_job_id / "tests" / test_job_id


def select_model_artifact(job: TrainingJob, artifact_id: str) -> TrainingArtifact:
    artifacts = list(job.artifacts)
    if artifact_id:
        artifact = next((item for item in artifacts if item.id == artifact_id), None)
        if artifact is None:
            raise TrainingInferenceError("指定的模型产物不存在。", 404)
        if not is_model_artifact(artifact):
            raise TrainingInferenceError("请选择 best.pt 或 last.pt 模型产物。", 400)
        return artifact

    for artifact_type in ("best_model", "last_model"):
        artifact = next((item for item in artifacts if item.artifact_type == artifact_type), None)
        if artifact is not None:
            return artifact

    artifact = next((item for item in artifacts if is_model_artifact(item)), None)
    if artifact is None:
        raise TrainingInferenceError("当前训练作业没有可用于测试的模型产物。", 409)
    return artifact


def is_model_artifact(artifact: TrainingArtifact) -> bool:
    return artifact.artifact_type in {"best_model", "last_model"} or artifact.filename.lower().endswith(".pt")


def normalize_detections(raw_detections: object, categories: list[str]) -> list[dict[str, Any]]:
    if not isinstance(raw_detections, list):
        return []

    detections: list[dict[str, Any]] = []
    for item in raw_detections:
        if not isinstance(item, dict):
            continue
        bbox = item.get("bbox")
        if not isinstance(bbox, list) or len(bbox) != 4:
            continue
        class_id = item.get("classId")
        class_id_int = int(class_id) if isinstance(class_id, (int, float)) else -1
        category = str(item.get("category") or "").strip() or _category_name(class_id_int, categories)
        confidence = item.get("confidence")
        detections.append(
            {
                "category": category,
                "classId": class_id_int,
                "confidence": round(float(confidence), 6) if isinstance(confidence, (int, float)) else 0.0,
                "bbox": [_clamp(float(value)) for value in bbox],
            }
        )
    return detections


def _build_result_payload(test_job: TrainingInferenceJob) -> dict[str, Any] | None:
    if test_job.status != "completed" or not test_job.result_storage_path:
        return None

    result_path = Path(test_job.result_storage_path)
    if not result_path.exists():
        return None

    annotated_image = preview_data_url(result_path.read_bytes(), test_job.result_mime_type or "image/jpeg")
    input_path = Path(test_job.input_storage_path)
    source_image = (
        preview_data_url(input_path.read_bytes(), test_job.input_mime_type or "image/jpeg")
        if input_path.exists()
        else annotated_image
    )

    artifact = test_job.artifact
    return {
        "artifact": {
            "id": artifact.id if artifact else test_job.artifact_id,
            "type": artifact.artifact_type if artifact else "",
            "filename": artifact.filename if artifact else "",
        },
        "image": {
            "width": test_job.input_width,
            "height": test_job.input_height,
        },
        "confidenceThreshold": test_job.confidence_threshold,
        "imageSize": test_job.image_size,
        "detections": test_job.detections_json or [],
        "sourceImage": source_image,
        "annotatedImage": annotated_image,
    }


def _category_name(class_id: int, categories: list[str]) -> str:
    if 0 <= class_id < len(categories):
        return str(categories[class_id])
    return f"class_{class_id}" if class_id >= 0 else "object"


def _clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    return min(max(value, minimum), maximum)
