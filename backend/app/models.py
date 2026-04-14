from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func

from app.extensions import db


def generate_uuid() -> str:
    return str(uuid.uuid4())


def naive_utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


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

    tasks = db.relationship("Task", back_populates="user", cascade="all, delete-orphan")
    model_profiles = db.relationship(
        "ModelProfile",
        back_populates="user",
        cascade="all, delete-orphan",
        order_by="ModelProfile.created_at.asc()",
    )


class Task(TimestampMixin, db.Model):
    __tablename__ = "tasks"

    id = db.Column(db.String(36), primary_key=True, default=generate_uuid)
    user_id = db.Column(db.String(36), db.ForeignKey("users.id"), nullable=False, index=True)
    task_name = db.Column(db.String(255), nullable=False)
    subject = db.Column(db.String(255), nullable=False)
    categories = db.Column(db.JSON, nullable=False, default=list)
    image_count = db.Column(db.Integer, nullable=False)
    config_json = db.Column(db.JSON, nullable=False, default=dict)
    prompt_json = db.Column(db.JSON, nullable=False, default=dict)
    status = db.Column(db.String(32), nullable=False, default="draft", index=True)
    progress_percent = db.Column(db.Integer, nullable=False, default=0)
    images_generated = db.Column(db.Integer, nullable=False, default=0)
    selected_count = db.Column(db.Integer, nullable=False, default=0)
    estimated_cost = db.Column(db.Float, nullable=False, default=0.0)
    spent_cost = db.Column(db.Float, nullable=False, default=0.0)
    budget_limit = db.Column(db.Float, nullable=True)
    api_provider = db.Column(db.String(64), nullable=False)
    api_key_encrypted = db.Column(db.Text, nullable=True)
    started_at = db.Column(db.DateTime(timezone=True), nullable=True)
    completed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    last_synced_at = db.Column(db.DateTime(timezone=True), nullable=True)

    user = db.relationship("User", back_populates="tasks")
    images = db.relationship(
        "TaskImage",
        back_populates="task",
        cascade="all, delete-orphan",
        order_by="TaskImage.ordinal.asc()",
    )
    exports = db.relationship(
        "TaskExport",
        back_populates="task",
        cascade="all, delete-orphan",
        order_by="TaskExport.version.desc()",
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


class TaskImage(TimestampMixin, db.Model):
    __tablename__ = "task_images"

    id = db.Column(db.String(36), primary_key=True, default=generate_uuid)
    task_id = db.Column(db.String(36), db.ForeignKey("tasks.id"), nullable=False, index=True)
    ordinal = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(32), nullable=False, default="ready")
    latency_ms = db.Column(db.Integer, nullable=False, default=0)
    seed = db.Column(db.Integer, nullable=False)
    prompt_text = db.Column(db.Text, nullable=False)
    diversity_vars = db.Column(db.JSON, nullable=False, default=dict)
    preview_svg = db.Column(db.Text, nullable=False)
    selected = db.Column(db.Boolean, nullable=False, default=True)
    annotation_status = db.Column(db.String(32), nullable=False, default="pending")
    confidence_score = db.Column(db.Float, nullable=True)
    generated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=naive_utcnow)

    task = db.relationship("Task", back_populates="images")


class TaskExport(TimestampMixin, db.Model):
    __tablename__ = "task_exports"

    id = db.Column(db.String(36), primary_key=True, default=generate_uuid)
    task_id = db.Column(db.String(36), db.ForeignKey("tasks.id"), nullable=False, index=True)
    version = db.Column(db.Integer, nullable=False, default=1)
    export_format = db.Column(db.String(32), nullable=False)
    status = db.Column(db.String(32), nullable=False, default="ready")
    summary_json = db.Column(db.JSON, nullable=False, default=dict)
    download_url = db.Column(db.String(255), nullable=False)

    task = db.relationship("Task", back_populates="exports")
