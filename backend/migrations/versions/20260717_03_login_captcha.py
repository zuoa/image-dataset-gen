"""add one-time login captcha challenges

Revision ID: 20260717_03
Revises: 20260717_02
Create Date: 2026-07-17 18:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260717_03"
down_revision: Union[str, Sequence[str], None] = "20260717_02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if "login_captchas" in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    op.create_table(
        "login_captchas",
        sa.Column("id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("answer_hash", sa.String(length=64), nullable=False),
        sa.Column("client_signature", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_login_captchas_expires_at", "login_captchas", ["expires_at"])
    op.create_index("ix_login_captchas_used_at", "login_captchas", ["used_at"])


def downgrade() -> None:
    op.drop_index("ix_login_captchas_used_at", table_name="login_captchas")
    op.drop_index("ix_login_captchas_expires_at", table_name="login_captchas")
    op.drop_table("login_captchas")
