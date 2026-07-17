"""add quality runs and external connections

Revision ID: 20260717_02
Revises: 20260717_01
Create Date: 2026-07-17 15:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import Text
from sqlalchemy.dialects import postgresql


revision: str = "20260717_02"
down_revision: Union[str, Sequence[str], None] = "20260717_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _uuid_type():
    return sa.Uuid(as_uuid=False)


def _json_type():
    return sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), "postgresql")


def upgrade() -> None:
    existing_tables = set(sa.inspect(op.get_bind()).get_table_names())
    if {
        "external_connections",
        "quality_runs",
        "quality_issues",
    }.issubset(existing_tables):
        return
    op.create_table(
        "external_connections",
        sa.Column("id", _uuid_type(), nullable=False),
        sa.Column("user_id", _uuid_type(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("secret_encrypted", sa.Text(), nullable=False),
        sa.Column("key_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("last_validated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=False),
        sa.Column("metadata_json", _json_type(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "provider", "name", name="uq_external_connections_user_provider_name"
        ),
    )
    op.create_index("ix_external_connections_provider", "external_connections", ["provider"])
    op.create_index("ix_external_connections_status", "external_connections", ["status"])
    op.create_index("ix_external_connections_user_id", "external_connections", ["user_id"])

    op.create_table(
        "quality_runs",
        sa.Column("id", _uuid_type(), nullable=False),
        sa.Column("dataset_id", _uuid_type(), nullable=False),
        sa.Column("user_id", _uuid_type(), nullable=False),
        sa.Column("training_job_id", _uuid_type(), nullable=True),
        sa.Column("export_id", _uuid_type(), nullable=True),
        sa.Column("run_type", sa.String(length=24), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("config_json", _json_type(), nullable=False),
        sa.Column("summary_json", _json_type(), nullable=False),
        sa.Column("supervision_version", sa.String(length=32), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("attempt_count >= 0", name="ck_quality_runs_attempts_nonnegative"),
        sa.ForeignKeyConstraint(["dataset_id"], ["datasets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["export_id"], ["dataset_exports.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["training_job_id"], ["training_jobs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_quality_runs_dataset_created", "quality_runs", ["dataset_id", "created_at"])
    op.create_index("ix_quality_runs_dataset_id", "quality_runs", ["dataset_id"])
    op.create_index("ix_quality_runs_export_id", "quality_runs", ["export_id"])
    op.create_index("ix_quality_runs_run_type", "quality_runs", ["run_type"])
    op.create_index("ix_quality_runs_status", "quality_runs", ["status"])
    op.create_index("ix_quality_runs_status_created", "quality_runs", ["status", "created_at"])
    op.create_index("ix_quality_runs_training_job_id", "quality_runs", ["training_job_id"])
    op.create_index("ix_quality_runs_user_id", "quality_runs", ["user_id"])

    op.create_table(
        "quality_issues",
        sa.Column("id", _uuid_type(), nullable=False),
        sa.Column("quality_run_id", _uuid_type(), nullable=False),
        sa.Column("image_id", _uuid_type(), nullable=False),
        sa.Column("annotation_revision_id", _uuid_type(), nullable=True),
        sa.Column("issue_type", sa.String(length=48), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("details_json", _json_type(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("score >= 0 AND score <= 1", name="ck_quality_issues_score_range"),
        sa.ForeignKeyConstraint(
            ["annotation_revision_id"], ["annotation_revisions.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["image_id"], ["dataset_images.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["quality_run_id"], ["quality_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_quality_issues_annotation_revision_id", "quality_issues", ["annotation_revision_id"])
    op.create_index("ix_quality_issues_image_id", "quality_issues", ["image_id"])
    op.create_index("ix_quality_issues_image_status", "quality_issues", ["image_id", "status"])
    op.create_index("ix_quality_issues_issue_type", "quality_issues", ["issue_type"])
    op.create_index("ix_quality_issues_quality_run_id", "quality_issues", ["quality_run_id"])
    op.create_index("ix_quality_issues_run_status", "quality_issues", ["quality_run_id", "status"])
    op.create_index("ix_quality_issues_severity", "quality_issues", ["severity"])
    op.create_index("ix_quality_issues_status", "quality_issues", ["status"])


def downgrade() -> None:
    op.drop_table("quality_issues")
    op.drop_table("quality_runs")
    op.drop_table("external_connections")
