from __future__ import annotations

import uuid
from decimal import Decimal
from datetime import UTC, datetime

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import JSONB

from app.extensions import db


def generate_uuid() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(UTC)


def json_column_type():
    return db.JSON().with_variant(JSONB(), "postgresql")


def uuid_column_type():
    """Use native PostgreSQL UUID while keeping string values in Python/tests."""
    return db.Uuid(as_uuid=False)


class TimestampMixin:
    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utcnow, server_default=func.now()
    )
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        server_default=func.now(),
        onupdate=func.now(),
    )


class User(TimestampMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(uuid_column_type(), primary_key=True, default=generate_uuid)
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
    assets = db.relationship("Asset", back_populates="user")
    external_connections = db.relationship(
        "ExternalConnection",
        back_populates="user",
        cascade="all, delete-orphan",
        order_by="ExternalConnection.created_at.asc()",
    )


class ModelProfile(TimestampMixin, db.Model):
    __tablename__ = "model_profiles"

    id = db.Column(uuid_column_type(), primary_key=True, default=generate_uuid)
    user_id = db.Column(
        uuid_column_type(), db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    profile_type = db.Column(db.String(16), nullable=False, default="image")
    name = db.Column(db.String(120), nullable=False)
    provider_id = db.Column(db.String(64), nullable=False)
    base_url = db.Column(db.String(255), nullable=True)
    model = db.Column(db.String(120), nullable=False)
    api_key_encrypted = db.Column(db.Text, nullable=False)
    key_version = db.Column(db.Integer, nullable=False, default=1, server_default="1")
    concurrency = db.Column(db.Integer, nullable=False, default=3)
    batch_size = db.Column(db.Integer, nullable=False, default=10)
    jimeng_watermark = db.Column(db.Boolean, nullable=False, default=True)
    notes = db.Column(db.Text, nullable=False, default="")

    user = db.relationship("User", back_populates="model_profiles")


class ExternalConnection(TimestampMixin, db.Model):
    __tablename__ = "external_connections"
    __table_args__ = (
        db.UniqueConstraint(
            "user_id", "provider", "name", name="uq_external_connections_user_provider_name"
        ),
    )

    id = db.Column(uuid_column_type(), primary_key=True, default=generate_uuid)
    user_id = db.Column(
        uuid_column_type(), db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider = db.Column(db.String(32), nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    secret_encrypted = db.Column(db.Text, nullable=False)
    key_version = db.Column(db.Integer, nullable=False, default=1, server_default="1")
    status = db.Column(db.String(24), nullable=False, default="unverified", index=True)
    last_validated_at = db.Column(db.DateTime(timezone=True), nullable=True)
    last_error = db.Column(db.Text, nullable=False, default="")
    metadata_json = db.Column(json_column_type(), nullable=False, default=dict)

    user = db.relationship("User", back_populates="external_connections")


class Dataset(TimestampMixin, db.Model):
    __tablename__ = "datasets"

    __table_args__ = (
        db.CheckConstraint("image_count >= 0", name="ck_datasets_image_count_nonnegative"),
        db.CheckConstraint("selected_count >= 0", name="ck_datasets_selected_count_nonnegative"),
        db.CheckConstraint("task_count >= 0", name="ck_datasets_task_count_nonnegative"),
        db.CheckConstraint("spent_cost >= 0", name="ck_datasets_spent_cost_nonnegative"),
    )

    id = db.Column(uuid_column_type(), primary_key=True, default=generate_uuid)
    user_id = db.Column(
        uuid_column_type(), db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=False, default="")
    categories = db.Column(json_column_type(), nullable=False, default=list)
    status = db.Column(db.String(32), nullable=False, default="draft", index=True)
    image_count = db.Column(db.Integer, nullable=False, default=0)
    selected_count = db.Column(db.Integer, nullable=False, default=0)
    task_count = db.Column(db.Integer, nullable=False, default=0)
    next_image_ordinal = db.Column(db.Integer, nullable=False, default=1, server_default="1")
    next_export_version = db.Column(db.Integer, nullable=False, default=1, server_default="1")
    spent_cost = db.Column(db.Numeric(14, 4), nullable=False, default=Decimal("0"), server_default="0")
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
    category_rows = db.relationship(
        "DatasetCategory",
        back_populates="dataset",
        cascade="all, delete-orphan",
        order_by="DatasetCategory.position.asc()",
    )
    quality_runs = db.relationship(
        "QualityRun",
        back_populates="dataset",
        cascade="all, delete-orphan",
        order_by="QualityRun.created_at.desc()",
    )


class DatasetTask(TimestampMixin, db.Model):
    __tablename__ = "dataset_tasks"
    __table_args__ = (
        db.Index("ix_dataset_tasks_dataset_created_at", "dataset_id", "created_at"),
        db.Index("ix_dataset_tasks_status_created_at", "status", "created_at"),
        db.CheckConstraint(
            "progress_percent >= 0 AND progress_percent <= 100",
            name="ck_dataset_tasks_progress_range",
        ),
        db.CheckConstraint("image_count >= 0", name="ck_dataset_tasks_image_count_nonnegative"),
    )

    id = db.Column(uuid_column_type(), primary_key=True, default=generate_uuid)
    dataset_id = db.Column(
        uuid_column_type(), db.ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id = db.Column(
        uuid_column_type(), db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
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
    estimated_cost = db.Column(db.Numeric(14, 4), nullable=False, default=Decimal("0"), server_default="0")
    spent_cost = db.Column(db.Numeric(14, 4), nullable=False, default=Decimal("0"), server_default="0")
    api_provider = db.Column(db.String(64), nullable=False, default="")
    api_key_encrypted = db.Column(db.Text, nullable=True)
    started_at = db.Column(db.DateTime(timezone=True), nullable=True)
    completed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    last_synced_at = db.Column(db.DateTime(timezone=True), nullable=True)
    source_asset_id = db.Column(
        uuid_column_type(), db.ForeignKey("assets.id", ondelete="RESTRICT"), nullable=True, index=True
    )

    dataset = db.relationship("Dataset", back_populates="tasks")
    images = db.relationship(
        "DatasetImage",
        back_populates="source_task",
        order_by="DatasetImage.ordinal.asc()",
    )
    items = db.relationship(
        "TaskItem",
        back_populates="task",
        cascade="all, delete-orphan",
        order_by="TaskItem.item_index.asc()",
    )
    source_asset = db.relationship("Asset", foreign_keys=[source_asset_id])


class DatasetImage(TimestampMixin, db.Model):
    __tablename__ = "dataset_images"
    __table_args__ = (
        db.Index("ix_dataset_images_dataset_selected_ordinal", "dataset_id", "selected", "ordinal"),
        db.Index("ix_dataset_images_dataset_annotation_status", "dataset_id", "annotation_status"),
        db.UniqueConstraint("dataset_id", "ordinal", name="uq_dataset_images_dataset_ordinal"),
        db.UniqueConstraint("source_task_id", "source_ordinal", name="uq_dataset_images_task_ordinal"),
        db.CheckConstraint("ordinal > 0", name="ck_dataset_images_ordinal_positive"),
        db.CheckConstraint("source_ordinal > 0", name="ck_dataset_images_source_ordinal_positive"),
        db.CheckConstraint(
            "confidence_score IS NULL OR (confidence_score >= 0 AND confidence_score <= 1)",
            name="ck_dataset_images_confidence_range",
        ),
    )

    id = db.Column(uuid_column_type(), primary_key=True, default=generate_uuid)
    dataset_id = db.Column(
        uuid_column_type(), db.ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_task_id = db.Column(
        uuid_column_type(), db.ForeignKey("dataset_tasks.id", ondelete="SET NULL"), nullable=True, index=True
    )
    asset_id = db.Column(
        uuid_column_type(), db.ForeignKey("assets.id", ondelete="RESTRICT"), nullable=True, index=True
    )
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
    generated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    dataset = db.relationship("Dataset", back_populates="images")
    source_task = db.relationship("DatasetTask", back_populates="images")
    asset = db.relationship("Asset", back_populates="images")
    annotation_revisions = db.relationship(
        "AnnotationRevision",
        back_populates="image",
        cascade="all, delete-orphan",
        order_by="AnnotationRevision.revision.desc()",
    )


class DatasetExport(TimestampMixin, db.Model):
    __tablename__ = "dataset_exports"
    __table_args__ = (
        db.UniqueConstraint("dataset_id", "version", name="uq_dataset_exports_dataset_version"),
        db.CheckConstraint("version > 0", name="ck_dataset_exports_version_positive"),
        db.CheckConstraint("attempt_count >= 0", name="ck_dataset_exports_attempts_nonnegative"),
    )

    id = db.Column(uuid_column_type(), primary_key=True, default=generate_uuid)
    dataset_id = db.Column(
        uuid_column_type(), db.ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    asset_id = db.Column(
        uuid_column_type(), db.ForeignKey("assets.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    version = db.Column(db.Integer, nullable=False, default=1)
    export_format = db.Column(db.String(32), nullable=False)
    status = db.Column(db.String(32), nullable=False, default="ready")
    summary_json = db.Column(json_column_type(), nullable=False, default=dict)
    download_url = db.Column(db.String(255), nullable=False)
    attempt_count = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    lease_expires_at = db.Column(db.DateTime(timezone=True), nullable=True, index=True)

    dataset = db.relationship("Dataset", back_populates="exports")
    asset = db.relationship("Asset", back_populates="exports")


class TrainingWorker(TimestampMixin, db.Model):
    __tablename__ = "training_workers"

    id = db.Column(db.String(64), primary_key=True, default=generate_uuid)
    name = db.Column(db.String(120), nullable=False)
    status = db.Column(db.String(32), nullable=False, default="idle", index=True)
    capabilities_json = db.Column(json_column_type(), nullable=False, default=dict)
    version = db.Column(db.String(64), nullable=False, default="")
    last_heartbeat_at = db.Column(db.DateTime(timezone=True), nullable=True)
    current_job_id = db.Column(db.String(36), nullable=True, index=True)
    token_hash = db.Column(db.String(128), nullable=False, default="")
    token_scopes = db.Column(json_column_type(), nullable=False, default=lambda: ["training", "inference"])

    jobs = db.relationship("TrainingJob", back_populates="worker")
    inference_jobs = db.relationship("TrainingInferenceJob", back_populates="worker")


class TrainingJob(TimestampMixin, db.Model):
    __tablename__ = "training_jobs"

    __table_args__ = (
        db.Index("ix_training_jobs_queue", "status", "created_at"),
        db.CheckConstraint(
            "progress_percent >= 0 AND progress_percent <= 100",
            name="ck_training_jobs_progress_range",
        ),
    )

    id = db.Column(uuid_column_type(), primary_key=True, default=generate_uuid)
    dataset_id = db.Column(
        uuid_column_type(), db.ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id = db.Column(
        uuid_column_type(), db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    export_id = db.Column(
        uuid_column_type(), db.ForeignKey("dataset_exports.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    worker_id = db.Column(db.String(64), db.ForeignKey("training_workers.id"), nullable=True, index=True)
    status = db.Column(db.String(32), nullable=False, default="queued", index=True)
    progress_percent = db.Column(db.Integer, nullable=False, default=0)
    config_json = db.Column(json_column_type(), nullable=False, default=dict)
    metrics_json = db.Column(json_column_type(), nullable=False, default=dict)
    error_message = db.Column(db.Text, nullable=False, default="")
    started_at = db.Column(db.DateTime(timezone=True), nullable=True)
    completed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    assignment_token_hash = db.Column(db.String(128), nullable=False, default="")
    lease_expires_at = db.Column(db.DateTime(timezone=True), nullable=True, index=True)
    last_heartbeat_at = db.Column(db.DateTime(timezone=True), nullable=True)
    attempt_count = db.Column(db.Integer, nullable=False, default=0, server_default="0")

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

    __table_args__ = (
        db.UniqueConstraint("job_id", "artifact_type", name="uq_training_artifacts_job_type"),
    )

    id = db.Column(uuid_column_type(), primary_key=True, default=generate_uuid)
    job_id = db.Column(
        uuid_column_type(), db.ForeignKey("training_jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    asset_id = db.Column(
        uuid_column_type(), db.ForeignKey("assets.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    artifact_type = db.Column(db.String(32), nullable=False, index=True)
    filename = db.Column(db.String(255), nullable=False)
    storage_path = db.Column(db.String(512), nullable=False)
    size_bytes = db.Column(db.BigInteger, nullable=False, default=0)

    job = db.relationship("TrainingJob", back_populates="artifacts")
    asset = db.relationship("Asset", back_populates="training_artifacts")
    inference_jobs = db.relationship("TrainingInferenceJob", back_populates="artifact")


class TrainingInferenceJob(TimestampMixin, db.Model):
    __tablename__ = "training_inference_jobs"

    __table_args__ = (
        db.Index("ix_training_inference_jobs_queue", "status", "created_at"),
        db.CheckConstraint(
            "confidence_threshold >= 0 AND confidence_threshold <= 1",
            name="ck_training_inference_confidence_range",
        ),
    )

    id = db.Column(uuid_column_type(), primary_key=True, default=generate_uuid)
    training_job_id = db.Column(
        uuid_column_type(), db.ForeignKey("training_jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    dataset_id = db.Column(
        uuid_column_type(), db.ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id = db.Column(
        uuid_column_type(), db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    artifact_id = db.Column(
        uuid_column_type(), db.ForeignKey("training_artifacts.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    worker_id = db.Column(db.String(64), db.ForeignKey("training_workers.id"), nullable=True, index=True)
    status = db.Column(db.String(32), nullable=False, default="queued", index=True)
    confidence_threshold = db.Column(db.Float, nullable=False, default=0.25)
    image_size = db.Column(db.Integer, nullable=False, default=640)
    input_filename = db.Column(db.String(255), nullable=False, default="")
    input_mime_type = db.Column(db.String(64), nullable=False, default="image/jpeg")
    input_storage_path = db.Column(db.String(512), nullable=False, default="")
    input_asset_id = db.Column(
        uuid_column_type(), db.ForeignKey("assets.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    input_width = db.Column(db.Integer, nullable=False, default=0)
    input_height = db.Column(db.Integer, nullable=False, default=0)
    result_mime_type = db.Column(db.String(64), nullable=False, default="")
    result_storage_path = db.Column(db.String(512), nullable=False, default="")
    result_asset_id = db.Column(
        uuid_column_type(), db.ForeignKey("assets.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    detections_json = db.Column(json_column_type(), nullable=False, default=list)
    error_message = db.Column(db.Text, nullable=False, default="")
    started_at = db.Column(db.DateTime(timezone=True), nullable=True)
    completed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    assignment_token_hash = db.Column(db.String(128), nullable=False, default="")
    lease_expires_at = db.Column(db.DateTime(timezone=True), nullable=True, index=True)
    attempt_count = db.Column(db.Integer, nullable=False, default=0, server_default="0")

    training_job = db.relationship("TrainingJob", back_populates="inference_jobs")
    artifact = db.relationship("TrainingArtifact", back_populates="inference_jobs")
    worker = db.relationship("TrainingWorker", back_populates="inference_jobs")
    input_asset = db.relationship("Asset", foreign_keys=[input_asset_id])
    result_asset = db.relationship("Asset", foreign_keys=[result_asset_id])


class DatasetCategory(TimestampMixin, db.Model):
    __tablename__ = "dataset_categories"
    __table_args__ = (
        db.UniqueConstraint("dataset_id", "name", name="uq_dataset_categories_dataset_name"),
        db.UniqueConstraint("dataset_id", "position", name="uq_dataset_categories_dataset_position"),
        db.CheckConstraint("position >= 0", name="ck_dataset_categories_position_nonnegative"),
    )

    id = db.Column(uuid_column_type(), primary_key=True, default=generate_uuid)
    dataset_id = db.Column(
        uuid_column_type(), db.ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name = db.Column(db.String(255), nullable=False)
    position = db.Column(db.Integer, nullable=False)
    active = db.Column(db.Boolean, nullable=False, default=True, server_default="true")

    dataset = db.relationship("Dataset", back_populates="category_rows")
    detections = db.relationship("Detection", back_populates="category")


class Asset(TimestampMixin, db.Model):
    __tablename__ = "assets"
    __table_args__ = (
        db.UniqueConstraint("storage_backend", "storage_key", name="uq_assets_backend_key"),
        db.CheckConstraint("size_bytes >= 0", name="ck_assets_size_nonnegative"),
        db.CheckConstraint("width >= 0 AND height >= 0", name="ck_assets_dimensions_nonnegative"),
    )

    id = db.Column(uuid_column_type(), primary_key=True, default=generate_uuid)
    user_id = db.Column(
        uuid_column_type(), db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    dataset_id = db.Column(
        uuid_column_type(), db.ForeignKey("datasets.id", ondelete="SET NULL"), nullable=True, index=True
    )
    kind = db.Column(db.String(32), nullable=False, index=True)
    storage_backend = db.Column(db.String(32), nullable=False, default="local", server_default="local")
    storage_key = db.Column(db.String(1024), nullable=False)
    original_filename = db.Column(db.String(255), nullable=False, default="")
    mime_type = db.Column(db.String(128), nullable=False)
    size_bytes = db.Column(db.BigInteger, nullable=False, default=0)
    sha256 = db.Column(db.String(64), nullable=False, index=True)
    width = db.Column(db.Integer, nullable=False, default=0)
    height = db.Column(db.Integer, nullable=False, default=0)
    status = db.Column(db.String(24), nullable=False, default="ready", index=True)
    metadata_json = db.Column(json_column_type(), nullable=False, default=dict)
    deleted_at = db.Column(db.DateTime(timezone=True), nullable=True, index=True)

    user = db.relationship("User", back_populates="assets")
    images = db.relationship("DatasetImage", back_populates="asset")
    exports = db.relationship("DatasetExport", back_populates="asset")
    training_artifacts = db.relationship("TrainingArtifact", back_populates="asset")


class AnnotationRevision(TimestampMixin, db.Model):
    __tablename__ = "annotation_revisions"
    __table_args__ = (
        db.UniqueConstraint("image_id", "revision", name="uq_annotation_revisions_image_revision"),
        db.CheckConstraint("revision > 0", name="ck_annotation_revisions_revision_positive"),
    )

    id = db.Column(uuid_column_type(), primary_key=True, default=generate_uuid)
    image_id = db.Column(
        uuid_column_type(), db.ForeignKey("dataset_images.id", ondelete="CASCADE"), nullable=False, index=True
    )
    revision = db.Column(db.Integer, nullable=False)
    source = db.Column(db.String(32), nullable=False, default="manual")
    status = db.Column(db.String(24), nullable=False, default="annotated")
    provider = db.Column(db.String(64), nullable=False, default="")
    model = db.Column(db.String(128), nullable=False, default="")
    bbox_semantics = db.Column(db.String(32), nullable=False, default="center_size")
    is_current = db.Column(db.Boolean, nullable=False, default=True, index=True)
    metadata_json = db.Column(json_column_type(), nullable=False, default=dict)

    image = db.relationship("DatasetImage", back_populates="annotation_revisions")
    detections = db.relationship(
        "Detection", back_populates="revision_row", cascade="all, delete-orphan"
    )


class Detection(TimestampMixin, db.Model):
    __tablename__ = "detections"
    __table_args__ = (
        db.CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_detections_confidence_range"),
        db.CheckConstraint("x_center >= 0 AND x_center <= 1", name="ck_detections_x_range"),
        db.CheckConstraint("y_center >= 0 AND y_center <= 1", name="ck_detections_y_range"),
        db.CheckConstraint("width > 0 AND width <= 1", name="ck_detections_width_range"),
        db.CheckConstraint("height > 0 AND height <= 1", name="ck_detections_height_range"),
    )

    id = db.Column(uuid_column_type(), primary_key=True, default=generate_uuid)
    revision_id = db.Column(
        uuid_column_type(), db.ForeignKey("annotation_revisions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    category_id = db.Column(
        uuid_column_type(), db.ForeignKey("dataset_categories.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    confidence = db.Column(db.Float, nullable=False)
    x_center = db.Column(db.Float, nullable=False)
    y_center = db.Column(db.Float, nullable=False)
    width = db.Column(db.Float, nullable=False)
    height = db.Column(db.Float, nullable=False)
    metadata_json = db.Column(json_column_type(), nullable=False, default=dict)

    revision_row = db.relationship("AnnotationRevision", back_populates="detections")
    category = db.relationship("DatasetCategory", back_populates="detections")


class QualityRun(TimestampMixin, db.Model):
    __tablename__ = "quality_runs"
    __table_args__ = (
        db.Index("ix_quality_runs_dataset_created", "dataset_id", "created_at"),
        db.Index("ix_quality_runs_status_created", "status", "created_at"),
        db.CheckConstraint("attempt_count >= 0", name="ck_quality_runs_attempts_nonnegative"),
    )

    id = db.Column(uuid_column_type(), primary_key=True, default=generate_uuid)
    dataset_id = db.Column(
        uuid_column_type(), db.ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id = db.Column(
        uuid_column_type(), db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    training_job_id = db.Column(
        uuid_column_type(), db.ForeignKey("training_jobs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    export_id = db.Column(
        uuid_column_type(), db.ForeignKey("dataset_exports.id", ondelete="SET NULL"), nullable=True, index=True
    )
    run_type = db.Column(db.String(24), nullable=False, default="dataset", index=True)
    status = db.Column(db.String(24), nullable=False, default="queued", index=True)
    config_json = db.Column(json_column_type(), nullable=False, default=dict)
    summary_json = db.Column(json_column_type(), nullable=False, default=dict)
    supervision_version = db.Column(db.String(32), nullable=False, default="")
    error_message = db.Column(db.Text, nullable=False, default="")
    started_at = db.Column(db.DateTime(timezone=True), nullable=True)
    completed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    attempt_count = db.Column(db.Integer, nullable=False, default=0, server_default="0")

    dataset = db.relationship("Dataset", back_populates="quality_runs")
    training_job = db.relationship("TrainingJob")
    export = db.relationship("DatasetExport")
    issues = db.relationship(
        "QualityIssue",
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="QualityIssue.score.desc()",
    )


class QualityIssue(TimestampMixin, db.Model):
    __tablename__ = "quality_issues"
    __table_args__ = (
        db.Index("ix_quality_issues_run_status", "quality_run_id", "status"),
        db.Index("ix_quality_issues_image_status", "image_id", "status"),
        db.CheckConstraint("score >= 0 AND score <= 1", name="ck_quality_issues_score_range"),
    )

    id = db.Column(uuid_column_type(), primary_key=True, default=generate_uuid)
    quality_run_id = db.Column(
        uuid_column_type(), db.ForeignKey("quality_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    image_id = db.Column(
        uuid_column_type(), db.ForeignKey("dataset_images.id", ondelete="CASCADE"), nullable=False, index=True
    )
    annotation_revision_id = db.Column(
        uuid_column_type(), db.ForeignKey("annotation_revisions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    issue_type = db.Column(db.String(48), nullable=False, index=True)
    severity = db.Column(db.String(16), nullable=False, default="warning", index=True)
    score = db.Column(db.Float, nullable=False, default=0.5)
    status = db.Column(db.String(16), nullable=False, default="open", index=True)
    details_json = db.Column(json_column_type(), nullable=False, default=dict)
    resolved_at = db.Column(db.DateTime(timezone=True), nullable=True)

    run = db.relationship("QualityRun", back_populates="issues")
    image = db.relationship("DatasetImage")
    annotation_revision = db.relationship("AnnotationRevision")


class TaskItem(TimestampMixin, db.Model):
    __tablename__ = "task_items"
    __table_args__ = (
        db.UniqueConstraint("task_id", "item_index", name="uq_task_items_task_index"),
        db.Index("ix_task_items_dispatch", "status", "available_at", "created_at"),
        db.CheckConstraint("item_index > 0", name="ck_task_items_index_positive"),
        db.CheckConstraint("attempt_count >= 0", name="ck_task_items_attempts_nonnegative"),
    )

    id = db.Column(uuid_column_type(), primary_key=True, default=generate_uuid)
    task_id = db.Column(
        uuid_column_type(), db.ForeignKey("dataset_tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    item_index = db.Column(db.Integer, nullable=False)
    item_type = db.Column(db.String(32), nullable=False)
    status = db.Column(db.String(24), nullable=False, default="queued", index=True)
    payload_json = db.Column(json_column_type(), nullable=False, default=dict)
    result_json = db.Column(json_column_type(), nullable=False, default=dict)
    attempt_count = db.Column(db.Integer, nullable=False, default=0)
    available_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    lease_token_hash = db.Column(db.String(128), nullable=False, default="")
    lease_expires_at = db.Column(db.DateTime(timezone=True), nullable=True, index=True)
    last_error = db.Column(db.Text, nullable=False, default="")
    completed_at = db.Column(db.DateTime(timezone=True), nullable=True)

    task = db.relationship("DatasetTask", back_populates="items")


class OutboxEvent(TimestampMixin, db.Model):
    __tablename__ = "outbox_events"
    __table_args__ = (
        db.UniqueConstraint("deduplication_key", name="uq_outbox_events_deduplication_key"),
        db.Index("ix_outbox_events_pending", "published_at", "available_at", "created_at"),
        db.CheckConstraint("attempt_count >= 0", name="ck_outbox_events_attempts_nonnegative"),
    )

    id = db.Column(uuid_column_type(), primary_key=True, default=generate_uuid)
    event_type = db.Column(db.String(64), nullable=False, index=True)
    aggregate_type = db.Column(db.String(64), nullable=False)
    aggregate_id = db.Column(db.String(64), nullable=False, index=True)
    deduplication_key = db.Column(db.String(255), nullable=False)
    payload_json = db.Column(json_column_type(), nullable=False, default=dict)
    available_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    attempt_count = db.Column(db.Integer, nullable=False, default=0)
    last_error = db.Column(db.Text, nullable=False, default="")
    published_at = db.Column(db.DateTime(timezone=True), nullable=True)


class RefreshSession(TimestampMixin, db.Model):
    __tablename__ = "refresh_sessions"
    __table_args__ = (
        db.UniqueConstraint("token_hash", name="uq_refresh_sessions_token_hash"),
    )

    id = db.Column(uuid_column_type(), primary_key=True, default=generate_uuid)
    user_id = db.Column(
        uuid_column_type(), db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash = db.Column(db.String(128), nullable=False)
    family_id = db.Column(uuid_column_type(), nullable=False, default=generate_uuid, index=True)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False, index=True)
    revoked_at = db.Column(db.DateTime(timezone=True), nullable=True)
    revocation_reason = db.Column(db.String(32), nullable=False, default="")
    rotated_to_id = db.Column(
        uuid_column_type(),
        db.ForeignKey("refresh_sessions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    successor_token_encrypted = db.Column(db.Text, nullable=False, default="")
    rotation_grace_expires_at = db.Column(db.DateTime(timezone=True), nullable=True)
    user_agent = db.Column(db.String(512), nullable=False, default="")
    ip_address = db.Column(db.String(64), nullable=False, default="")


class LoginCaptcha(TimestampMixin, db.Model):
    __tablename__ = "login_captchas"

    id = db.Column(uuid_column_type(), primary_key=True, default=generate_uuid)
    answer_hash = db.Column(db.String(64), nullable=False)
    client_signature = db.Column(db.String(64), nullable=False)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False, index=True)
    used_at = db.Column(db.DateTime(timezone=True), nullable=True, index=True)


class IdempotencyRecord(TimestampMixin, db.Model):
    __tablename__ = "idempotency_records"
    __table_args__ = (
        db.UniqueConstraint(
            "user_id", "scope", "idempotency_key", name="uq_idempotency_user_scope_key"
        ),
        db.Index("ix_idempotency_records_expiry", "expires_at", "completed_at"),
    )

    id = db.Column(uuid_column_type(), primary_key=True, default=generate_uuid)
    user_id = db.Column(
        uuid_column_type(), db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    scope = db.Column(db.String(255), nullable=False)
    idempotency_key = db.Column(db.String(255), nullable=False)
    request_hash = db.Column(db.String(64), nullable=False)
    response_json = db.Column(json_column_type(), nullable=False, default=dict)
    response_status = db.Column(db.Integer, nullable=False, default=0)
    completed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False)
