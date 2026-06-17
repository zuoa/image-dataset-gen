from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import JSONB

from app.extensions import db


def generate_uuid() -> str:
    return str(uuid.uuid4())


def naive_utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def json_column_type():
    return db.JSON().with_variant(JSONB(), "postgresql")


class TimestampMixin:
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class User(TimestampMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.String(36), primary_key=True, default=generate_uuid)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    plan = db.Column(db.String(32), nullable=False, default="pro")

    model_profiles = db.relationship(
        "ModelProfile",
        back_populates="user",
        cascade="all, delete-orphan",
        order_by="ModelProfile.created_at.asc()",
    )
    datasets = db.relationship(
        "Dataset",
        back_populates="user",
        cascade="all, delete-orphan",
        order_by="Dataset.created_at.desc()",
    )


class ModelProfile(TimestampMixin, db.Model):
    __tablename__ = "model_profiles"

    id = db.Column(db.String(36), primary_key=True, default=generate_uuid)
    user_id = db.Column(db.String(36), db.ForeignKey("users.id"), nullable=False, index=True)
    profile_type = db.Column(db.String(16), nullable=False, default="image")
    name = db.Column(db.String(120), nullable=False)
    provider_id = db.Column(db.String(64), nullable=False)
    base_url = db.Column(db.String(255), nullable=True)
    model = db.Column(db.String(120), nullable=False)
    api_key_encrypted = db.Column(db.Text, nullable=False)
    concurrency = db.Column(db.Integer, nullable=False, default=3)
    batch_size = db.Column(db.Integer, nullable=False, default=10)
    jimeng_watermark = db.Column(db.Boolean, nullable=False, default=True)
    notes = db.Column(db.Text, nullable=False, default="")

    user = db.relationship("User", back_populates="model_profiles")


class Dataset(TimestampMixin, db.Model):
    __tablename__ = "datasets"

    id = db.Column(db.String(36), primary_key=True, default=generate_uuid)
    user_id = db.Column(db.String(36), db.ForeignKey("users.id"), nullable=False, index=True)
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=False, default="")
    categories = db.Column(json_column_type(), nullable=False, default=list)
    status = db.Column(db.String(32), nullable=False, default="draft", index=True)
    image_count = db.Column(db.Integer, nullable=False, default=0)
    selected_count = db.Column(db.Integer, nullable=False, default=0)
    task_count = db.Column(db.Integer, nullable=False, default=0)
    spent_cost = db.Column(db.Float, nullable=False, default=0.0)
    annotation_json = db.Column(json_column_type(), nullable=False, default=dict)

    user = db.relationship("User", back_populates="datasets")
    tasks = db.relationship(
        "DatasetTask",
        back_populates="dataset",
        cascade="all, delete-orphan",
        order_by="DatasetTask.created_at.desc()",
    )
    images = db.relationship(
        "DatasetImage",
        back_populates="dataset",
        cascade="all, delete-orphan",
        order_by="DatasetImage.ordinal.asc()",
    )
    exports = db.relationship(
        "DatasetExport",
        back_populates="dataset",
        cascade="all, delete-orphan",
        order_by="DatasetExport.version.desc()",
    )
    training_jobs = db.relationship(
        "TrainingJob",
        back_populates="dataset",
        cascade="all, delete-orphan",
        order_by="TrainingJob.created_at.desc()",
    )


class DatasetTask(TimestampMixin, db.Model):
    __tablename__ = "dataset_tasks"
    __table_args__ = (
        db.Index("ix_dataset_tasks_dataset_created_at", "dataset_id", "created_at"),
    )

    id = db.Column(db.String(36), primary_key=True, default=generate_uuid)
    dataset_id = db.Column(db.String(36), db.ForeignKey("datasets.id"), nullable=False, index=True)
    user_id = db.Column(db.String(36), db.ForeignKey("users.id"), nullable=False, index=True)
    task_type = db.Column(db.String(32), nullable=False, index=True)
    task_name = db.Column(db.String(255), nullable=False)
    subject = db.Column(db.String(255), nullable=False, default="")
    image_count = db.Column(db.Integer, nullable=False, default=0)
    categories = db.Column(json_column_type(), nullable=False, default=list)
    config_json = db.Column(json_column_type(), nullable=False, default=dict)
    prompt_json = db.Column(json_column_type(), nullable=False, default=dict)
    status = db.Column(db.String(32), nullable=False, default="draft", index=True)
    progress_percent = db.Column(db.Integer, nullable=False, default=0)
    images_generated = db.Column(db.Integer, nullable=False, default=0)
    selected_count = db.Column(db.Integer, nullable=False, default=0)
    estimated_cost = db.Column(db.Float, nullable=False, default=0.0)
    spent_cost = db.Column(db.Float, nullable=False, default=0.0)
    api_provider = db.Column(db.String(64), nullable=False, default="")
    api_key_encrypted = db.Column(db.Text, nullable=True)
    started_at = db.Column(db.DateTime(timezone=True), nullable=True)
    completed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    last_synced_at = db.Column(db.DateTime(timezone=True), nullable=True)

    dataset = db.relationship("Dataset", back_populates="tasks")
    images = db.relationship(
        "DatasetImage",
        back_populates="source_task",
        order_by="DatasetImage.ordinal.asc()",
    )


class DatasetImage(TimestampMixin, db.Model):
    __tablename__ = "dataset_images"
    __table_args__ = (
        db.Index("ix_dataset_images_dataset_ordinal", "dataset_id", "ordinal"),
        db.Index("ix_dataset_images_dataset_selected_ordinal", "dataset_id", "selected", "ordinal"),
        db.Index("ix_dataset_images_dataset_annotation_status", "dataset_id", "annotation_status"),
    )

    id = db.Column(db.String(36), primary_key=True, default=generate_uuid)
    dataset_id = db.Column(db.String(36), db.ForeignKey("datasets.id"), nullable=False, index=True)
    source_task_id = db.Column(db.String(36), db.ForeignKey("dataset_tasks.id"), nullable=True, index=True)
    source_type = db.Column(db.String(32), nullable=False, default="generation")
    source_ordinal = db.Column(db.Integer, nullable=False, default=1)
    ordinal = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(32), nullable=False, default="ready")
    latency_ms = db.Column(db.Integer, nullable=False, default=0)
    seed = db.Column(db.Integer, nullable=False, default=0)
    prompt_text = db.Column(db.Text, nullable=False, default="")
    diversity_vars = db.Column(json_column_type(), nullable=False, default=dict)
    preview_svg = db.Column(db.Text, nullable=False, default="")
    selected = db.Column(db.Boolean, nullable=False, default=True)
    annotation_status = db.Column(db.String(32), nullable=False, default="pending")
    confidence_score = db.Column(db.Float, nullable=True)
    detection_categories = db.Column(json_column_type(), nullable=False, default=list)
    generated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=naive_utcnow)

    dataset = db.relationship("Dataset", back_populates="images")
    source_task = db.relationship("DatasetTask", back_populates="images")


class DatasetExport(TimestampMixin, db.Model):
    __tablename__ = "dataset_exports"
    __table_args__ = (
        db.Index("ix_dataset_exports_dataset_version", "dataset_id", "version"),
    )

    id = db.Column(db.String(36), primary_key=True, default=generate_uuid)
    dataset_id = db.Column(db.String(36), db.ForeignKey("datasets.id"), nullable=False, index=True)
    version = db.Column(db.Integer, nullable=False, default=1)
    export_format = db.Column(db.String(32), nullable=False)
    status = db.Column(db.String(32), nullable=False, default="ready")
    summary_json = db.Column(json_column_type(), nullable=False, default=dict)
    download_url = db.Column(db.String(255), nullable=False)

    dataset = db.relationship("Dataset", back_populates="exports")


class TrainingWorker(TimestampMixin, db.Model):
    __tablename__ = "training_workers"

    id = db.Column(db.String(64), primary_key=True, default=generate_uuid)
    name = db.Column(db.String(120), nullable=False)
    status = db.Column(db.String(32), nullable=False, default="idle", index=True)
    capabilities_json = db.Column(json_column_type(), nullable=False, default=dict)
    version = db.Column(db.String(64), nullable=False, default="")
    last_heartbeat_at = db.Column(db.DateTime(timezone=True), nullable=True)
    current_job_id = db.Column(db.String(36), nullable=True, index=True)

    jobs = db.relationship("TrainingJob", back_populates="worker")
    inference_jobs = db.relationship("TrainingInferenceJob", back_populates="worker")


class TrainingJob(TimestampMixin, db.Model):
    __tablename__ = "training_jobs"

    id = db.Column(db.String(36), primary_key=True, default=generate_uuid)
    dataset_id = db.Column(db.String(36), db.ForeignKey("datasets.id"), nullable=False, index=True)
    user_id = db.Column(db.String(36), db.ForeignKey("users.id"), nullable=False, index=True)
    export_id = db.Column(db.String(36), db.ForeignKey("dataset_exports.id"), nullable=False, index=True)
    worker_id = db.Column(db.String(64), db.ForeignKey("training_workers.id"), nullable=True, index=True)
    status = db.Column(db.String(32), nullable=False, default="queued", index=True)
    progress_percent = db.Column(db.Integer, nullable=False, default=0)
    config_json = db.Column(json_column_type(), nullable=False, default=dict)
    metrics_json = db.Column(json_column_type(), nullable=False, default=dict)
    error_message = db.Column(db.Text, nullable=False, default="")
    started_at = db.Column(db.DateTime(timezone=True), nullable=True)
    completed_at = db.Column(db.DateTime(timezone=True), nullable=True)

    dataset = db.relationship("Dataset", back_populates="training_jobs")
    export = db.relationship("DatasetExport")
    worker = db.relationship("TrainingWorker", back_populates="jobs")
    artifacts = db.relationship(
        "TrainingArtifact",
        back_populates="job",
        cascade="all, delete-orphan",
        order_by="TrainingArtifact.created_at.asc()",
    )
    inference_jobs = db.relationship(
        "TrainingInferenceJob",
        back_populates="training_job",
        cascade="all, delete-orphan",
        order_by="TrainingInferenceJob.created_at.desc()",
    )


class TrainingArtifact(TimestampMixin, db.Model):
    __tablename__ = "training_artifacts"

    id = db.Column(db.String(36), primary_key=True, default=generate_uuid)
    job_id = db.Column(db.String(36), db.ForeignKey("training_jobs.id"), nullable=False, index=True)
    artifact_type = db.Column(db.String(32), nullable=False, index=True)
    filename = db.Column(db.String(255), nullable=False)
    storage_path = db.Column(db.String(512), nullable=False)
    size_bytes = db.Column(db.Integer, nullable=False, default=0)

    job = db.relationship("TrainingJob", back_populates="artifacts")
    inference_jobs = db.relationship("TrainingInferenceJob", back_populates="artifact")


class TrainingInferenceJob(TimestampMixin, db.Model):
    __tablename__ = "training_inference_jobs"

    id = db.Column(db.String(36), primary_key=True, default=generate_uuid)
    training_job_id = db.Column(db.String(36), db.ForeignKey("training_jobs.id"), nullable=False, index=True)
    dataset_id = db.Column(db.String(36), db.ForeignKey("datasets.id"), nullable=False, index=True)
    user_id = db.Column(db.String(36), db.ForeignKey("users.id"), nullable=False, index=True)
    artifact_id = db.Column(db.String(36), db.ForeignKey("training_artifacts.id"), nullable=False, index=True)
    worker_id = db.Column(db.String(64), db.ForeignKey("training_workers.id"), nullable=True, index=True)
    status = db.Column(db.String(32), nullable=False, default="queued", index=True)
    confidence_threshold = db.Column(db.Float, nullable=False, default=0.25)
    image_size = db.Column(db.Integer, nullable=False, default=640)
    input_filename = db.Column(db.String(255), nullable=False, default="")
    input_mime_type = db.Column(db.String(64), nullable=False, default="image/jpeg")
    input_storage_path = db.Column(db.String(512), nullable=False, default="")
    input_width = db.Column(db.Integer, nullable=False, default=0)
    input_height = db.Column(db.Integer, nullable=False, default=0)
    result_mime_type = db.Column(db.String(64), nullable=False, default="")
    result_storage_path = db.Column(db.String(512), nullable=False, default="")
    detections_json = db.Column(json_column_type(), nullable=False, default=list)
    error_message = db.Column(db.Text, nullable=False, default="")
    started_at = db.Column(db.DateTime(timezone=True), nullable=True)
    completed_at = db.Column(db.DateTime(timezone=True), nullable=True)

    training_job = db.relationship("TrainingJob", back_populates="inference_jobs")
    artifact = db.relationship("TrainingArtifact", back_populates="inference_jobs")
    worker = db.relationship("TrainingWorker", back_populates="inference_jobs")
