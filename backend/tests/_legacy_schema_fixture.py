"""Create the smallest representative schema emitted by the pre-Alembic release."""

from datetime import UTC, datetime
import os
import uuid

import sqlalchemy as sa


def main() -> None:
    engine = sa.create_engine(os.environ["DATABASE_URL"])
    with engine.begin() as connection:
        connection.execute(sa.text("DROP TABLE IF EXISTS alembic_version"))

    metadata = sa.MetaData()
    users = sa.Table(
        "users",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False, unique=True, index=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("plan", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    training_workers = sa.Table(
        "training_workers",
        metadata,
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, index=True),
        sa.Column("capabilities_json", sa.JSON(), nullable=False),
        sa.Column("version", sa.String(64), nullable=False),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("current_job_id", sa.String(36), nullable=True, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            users.insert(),
            {
                "id": str(uuid.uuid4()),
                "email": "legacy-user",
                "password_hash": "legacy-password-hash",
                "plan": "pro",
                "created_at": datetime.now(UTC),
                "updated_at": datetime.now(UTC),
            },
        )
        connection.execute(
            training_workers.insert(),
            {
                "id": "legacy-worker",
                "name": "Legacy worker",
                "status": "idle",
                "capabilities_json": {},
                "version": "1.0",
                "created_at": datetime.now(UTC),
                "updated_at": datetime.now(UTC),
            },
        )


if __name__ == "__main__":
    main()
