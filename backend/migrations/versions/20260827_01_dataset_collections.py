"""dataset collections for hierarchical list management

Revision ID: 20260827_01
Revises: 20260721_01
Create Date: 2026-08-27 12:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260827_01"
down_revision: Union[str, Sequence[str], None] = "20260721_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _uuid_type():
    return sa.Uuid(as_uuid=False)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "dataset_collections" not in tables:
        op.create_table(
            "dataset_collections",
            sa.Column("id", _uuid_type(), nullable=False),
            sa.Column("user_id", _uuid_type(), nullable=False),
            sa.Column("parent_id", _uuid_type(), nullable=True),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("description", sa.Text(), nullable=False),
            sa.Column("path", sa.String(length=1024), nullable=False),
            sa.Column("depth", sa.Integer(), server_default="1", nullable=False),
            sa.Column("position", sa.Integer(), server_default="0", nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.CheckConstraint("depth >= 1 AND depth <= 4", name="ck_dataset_collections_depth_range"),
            sa.CheckConstraint("position >= 0", name="ck_dataset_collections_position_nonnegative"),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["parent_id"], ["dataset_collections.id"], ondelete="RESTRICT"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_dataset_collections_user_id", "dataset_collections", ["user_id"])
        op.create_index("ix_dataset_collections_parent_id", "dataset_collections", ["parent_id"])
        op.create_index(
            "ix_dataset_collections_user_parent_position",
            "dataset_collections",
            ["user_id", "parent_id", "position"],
        )
        op.create_index(
            "ix_dataset_collections_user_path",
            "dataset_collections",
            ["user_id", "path"],
        )
        op.create_index(
            "uq_dataset_collections_user_root_name",
            "dataset_collections",
            ["user_id", "name"],
            unique=True,
            sqlite_where=sa.text("parent_id IS NULL"),
            postgresql_where=sa.text("parent_id IS NULL"),
        )
        op.create_index(
            "uq_dataset_collections_user_parent_name",
            "dataset_collections",
            ["user_id", "parent_id", "name"],
            unique=True,
            sqlite_where=sa.text("parent_id IS NOT NULL"),
            postgresql_where=sa.text("parent_id IS NOT NULL"),
        )

    dataset_columns = {column["name"] for column in sa.inspect(bind).get_columns("datasets")}
    if "collection_id" not in dataset_columns:
        with op.batch_alter_table("datasets") as batch_op:
            batch_op.add_column(sa.Column("collection_id", _uuid_type(), nullable=True))
            batch_op.create_foreign_key(
                "fk_datasets_collection_id",
                "dataset_collections",
                ["collection_id"],
                ["id"],
                ondelete="SET NULL",
            )
            batch_op.create_index("ix_datasets_collection_id", ["collection_id"])
            batch_op.create_index("ix_datasets_user_collection_id", ["user_id", "collection_id"])


def downgrade() -> None:
    bind = op.get_bind()
    dataset_columns = {column["name"] for column in sa.inspect(bind).get_columns("datasets")}
    if "collection_id" in dataset_columns:
        with op.batch_alter_table("datasets") as batch_op:
            batch_op.drop_index("ix_datasets_user_collection_id")
            batch_op.drop_index("ix_datasets_collection_id")
            batch_op.drop_constraint("fk_datasets_collection_id", type_="foreignkey")
            batch_op.drop_column("collection_id")

    tables = set(sa.inspect(bind).get_table_names())
    if "dataset_collections" in tables:
        op.drop_index("uq_dataset_collections_user_parent_name", table_name="dataset_collections")
        op.drop_index("uq_dataset_collections_user_root_name", table_name="dataset_collections")
        op.drop_index("ix_dataset_collections_user_path", table_name="dataset_collections")
        op.drop_index("ix_dataset_collections_user_parent_position", table_name="dataset_collections")
        op.drop_index("ix_dataset_collections_parent_id", table_name="dataset_collections")
        op.drop_index("ix_dataset_collections_user_id", table_name="dataset_collections")
        op.drop_table("dataset_collections")
