"""track augmentation source image lineage

Revision ID: 20260721_01
Revises: 20260717_03
Create Date: 2026-07-21 12:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260721_01"
down_revision: Union[str, Sequence[str], None] = "20260717_03"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("dataset_images")}
    if "augmentation_source_image_id" not in columns:
        with op.batch_alter_table("dataset_images") as batch_op:
            batch_op.add_column(
                sa.Column("augmentation_source_image_id", sa.Uuid(as_uuid=False), nullable=True)
            )
            batch_op.create_foreign_key(
                "fk_dataset_images_augmentation_source_image_id",
                "dataset_images",
                ["augmentation_source_image_id"],
                ["id"],
                ondelete="SET NULL",
            )
            batch_op.create_index(
                "ix_dataset_images_augmentation_source_image_id",
                ["augmentation_source_image_id"],
            )

    _backfill_augmentation_sources(bind)


def _backfill_augmentation_sources(bind) -> None:
    metadata = sa.MetaData()
    tasks = sa.Table("dataset_tasks", metadata, autoload_with=bind)
    images = sa.Table("dataset_images", metadata, autoload_with=bind)
    task_rows = bind.execute(
        sa.select(tasks.c.id, tasks.c.dataset_id, tasks.c.config_json).where(
            tasks.c.task_type == "augmentation"
        )
    )
    for task_id, dataset_id, config_json in task_rows:
        config = config_json if isinstance(config_json, dict) else {}
        augmentation = config.get("augmentation")
        if not isinstance(augmentation, dict):
            continue
        source_ids = augmentation.get("sourceImageIds")
        if not isinstance(source_ids, list) or not source_ids:
            continue

        existing_ids = set(
            bind.execute(
                sa.select(images.c.id).where(images.c.dataset_id == dataset_id)
            ).scalars()
        )
        normalized_source_ids = [str(source_id) for source_id in source_ids]
        if not any(source_id in existing_ids for source_id in normalized_source_ids):
            continue

        child_rows = bind.execute(
            sa.select(images.c.id, images.c.source_ordinal)
            .where(images.c.source_task_id == task_id)
            .where(images.c.source_type == "augmentation")
            .where(images.c.augmentation_source_image_id.is_(None))
        )
        for image_id, source_ordinal in child_rows:
            source_index = (max(1, int(source_ordinal or 1)) - 1) % len(normalized_source_ids)
            source_image_id = normalized_source_ids[source_index]
            if source_image_id not in existing_ids:
                continue
            bind.execute(
                images.update()
                .where(images.c.id == image_id)
                .values(augmentation_source_image_id=source_image_id)
            )


def downgrade() -> None:
    columns = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("dataset_images")
    }
    if "augmentation_source_image_id" not in columns:
        return

    with op.batch_alter_table("dataset_images") as batch_op:
        batch_op.drop_index("ix_dataset_images_augmentation_source_image_id")
        batch_op.drop_constraint(
            "fk_dataset_images_augmentation_source_image_id",
            type_="foreignkey",
        )
        batch_op.drop_column("augmentation_source_image_id")
