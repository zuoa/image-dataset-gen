import importlib.util
from pathlib import Path
import uuid

from alembic import command
from alembic.config import Config as AlembicConfig
import sqlalchemy as sa


def _load_augmentation_lineage_migration():
    migration_path = (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "versions"
        / "20260721_01_augmentation_source_lineage.py"
    )
    spec = importlib.util.spec_from_file_location("augmentation_lineage_migration", migration_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_initial_migration_adopts_unversioned_auto_created_schema(tmp_path: Path, monkeypatch):
    database_path = tmp_path / "legacy.db"
    database_url = f"sqlite:///{database_path}"
    engine = sa.create_engine(database_url)
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
    user_id = str(uuid.uuid4())
    with engine.begin() as connection:
        connection.execute(
            users.insert(),
            {
                "id": user_id,
                "email": "legacy-user",
                "password_hash": "legacy-hash",
                "plan": "pro",
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
            },
        )

    backend_root = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("DATABASE_URL", database_url)
    alembic_config = AlembicConfig(str(backend_root / "alembic.ini"))
    alembic_config.set_main_option("script_location", str(backend_root / "migrations"))
    command.upgrade(alembic_config, "head")

    inspector = sa.inspect(engine)
    assert inspector.get_table_names()
    assert "refresh_sessions" in inspector.get_table_names()
    assert "login_captchas" in inspector.get_table_names()
    assert "task_items" in inspector.get_table_names()
    worker_columns = {column["name"] for column in inspector.get_columns("training_workers")}
    assert {"token_hash", "token_scopes"} <= worker_columns
    image_columns = {column["name"] for column in inspector.get_columns("dataset_images")}
    assert "augmentation_source_image_id" in image_columns
    with engine.connect() as connection:
        assert connection.scalar(sa.text("SELECT version_num FROM alembic_version")) == "20260721_01"
        assert connection.scalar(sa.text("SELECT id FROM users WHERE email = 'legacy-user'")) == user_id


def test_augmentation_lineage_migration_backfills_source_snapshot(tmp_path: Path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'lineage.db'}")
    metadata = sa.MetaData()
    tasks = sa.Table(
        "dataset_tasks",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("dataset_id", sa.String(36), nullable=False),
        sa.Column("task_type", sa.String(32), nullable=False),
        sa.Column("config_json", sa.JSON(), nullable=False),
    )
    images = sa.Table(
        "dataset_images",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("dataset_id", sa.String(36), nullable=False),
        sa.Column("source_task_id", sa.String(36), nullable=True),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("source_ordinal", sa.Integer(), nullable=False),
        sa.Column("augmentation_source_image_id", sa.String(36), nullable=True),
    )
    metadata.create_all(engine)

    with engine.begin() as connection:
        connection.execute(
            tasks.insert(),
            {
                "id": "task-1",
                "dataset_id": "dataset-1",
                "task_type": "augmentation",
                "config_json": {
                    "augmentation": {"sourceImageIds": ["source-1", "source-2"]}
                },
            },
        )
        connection.execute(
            images.insert(),
            [
                {
                    "id": "source-1",
                    "dataset_id": "dataset-1",
                    "source_task_id": None,
                    "source_type": "generation",
                    "source_ordinal": 1,
                },
                {
                    "id": "source-2",
                    "dataset_id": "dataset-1",
                    "source_task_id": None,
                    "source_type": "generation",
                    "source_ordinal": 2,
                },
                *[
                    {
                        "id": f"augmented-{index}",
                        "dataset_id": "dataset-1",
                        "source_task_id": "task-1",
                        "source_type": "augmentation",
                        "source_ordinal": index,
                    }
                    for index in range(1, 4)
                ],
            ],
        )
        _load_augmentation_lineage_migration()._backfill_augmentation_sources(connection)
        rows = connection.execute(
            sa.select(images.c.id, images.c.augmentation_source_image_id)
            .where(images.c.source_type == "augmentation")
            .order_by(images.c.source_ordinal)
        ).all()

    assert rows == [
        ("augmented-1", "source-1"),
        ("augmented-2", "source-2"),
        ("augmented-3", "source-1"),
    ]
