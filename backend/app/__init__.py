from __future__ import annotations

import base64
import os
from pathlib import Path

import click
from flask import Flask, jsonify
from marshmallow import ValidationError
from sqlalchemy import inspect, or_, text
from sqlalchemy.exc import IntegrityError, OperationalError
from werkzeug.security import generate_password_hash

from app.api.auth import auth_bp
from app.api.datasets import datasets_bp
from app.api.integrations import integrations_bp
from app.api.quality import quality_bp
from app.api.system import system_bp
from app.api.training import training_bp
from app.config import Config, normalize_database_uri
from app.extensions import celery, cors, db, jwt
from app.models import DatasetImage, User
from app.observability import configure_observability
from app.services.model_profile_service import ensure_default_model_profiles


def create_app(
    config_object: type[Config] | None = None, *, instance_path: str | os.PathLike[str] | None = None
) -> Flask:
    app = Flask(__name__, instance_path=str(instance_path) if instance_path is not None else None)
    app.config.from_object(config_object or Config)
    _validate_production_config(app)
    _prepare_runtime_paths(app)
    _configure_database_engine(app)

    db.init_app(app)
    jwt.init_app(app)
    cors.init_app(
        app,
        resources={f"{app.config['API_PREFIX']}/*": {"origins": app.config["FRONTEND_URL"]}},
        supports_credentials=True,
    )
    _make_celery(app)

    api_prefix = app.config["API_PREFIX"]
    app.register_blueprint(auth_bp, url_prefix=f"{api_prefix}/auth")
    app.register_blueprint(system_bp, url_prefix=f"{api_prefix}/system")
    app.register_blueprint(datasets_bp, url_prefix=f"{api_prefix}/datasets")
    app.register_blueprint(quality_bp, url_prefix=f"{api_prefix}/datasets")
    app.register_blueprint(integrations_bp, url_prefix=f"{api_prefix}/integrations")
    app.register_blueprint(training_bp, url_prefix=api_prefix)

    configure_observability(app)

    @app.get(f"{api_prefix}/health/live")
    @app.get(f"{api_prefix}/health")
    def liveness():
        return jsonify({"status": "ok", "check": "liveness"})

    @app.get(f"{api_prefix}/health/ready")
    def readiness():
        checks: dict[str, str] = {}
        try:
            db.session.execute(text("SELECT 1"))
            checks["database"] = "ok"
        except Exception:
            db.session.rollback()
            checks["database"] = "failed"

        storage_root = Path(app.config["STORAGE_ROOT"])
        checks["storage"] = "ok" if storage_root.is_dir() and os.access(storage_root, os.W_OK) else "failed"
        try:
            from redis import Redis

            Redis.from_url(app.config["CELERY_BROKER_URL"], socket_connect_timeout=1).ping()
            checks["redis"] = "ok"
        except Exception:
            checks["redis"] = "failed"

        ready = all(value == "ok" for value in checks.values())
        return jsonify({"status": "ok" if ready else "not_ready", "checks": checks}), 200 if ready else 503

    @app.errorhandler(ValidationError)
    def handle_validation_error(error: ValidationError):
        return jsonify({"message": "validation_error", "errors": error.messages}), 422

    with app.app_context():
        os.makedirs(app.config["STORAGE_ROOT"], exist_ok=True)
        if app.config["AUTO_CREATE_SCHEMA"]:
            if _is_sqlite_file_uri(app.config["SQLALCHEMY_DATABASE_URI"]):
                with db.engine.connect() as conn:
                    conn.execute(text("PRAGMA journal_mode=WAL"))
                    conn.execute(text("PRAGMA busy_timeout=60000"))
            try:
                db.create_all()
            except OperationalError:
                app.logger.exception("Database schema initialization failed")
            else:
                if app.config.get("BOOTSTRAP_DEMO_USER", False):
                    _ensure_demo_user(app)

    _register_cli(app)

    return app


def _prepare_runtime_paths(app: Flask) -> None:
    os.makedirs(app.instance_path, exist_ok=True)
    app.config["SQLALCHEMY_DATABASE_URI"] = normalize_database_uri(
        app.config["SQLALCHEMY_DATABASE_URI"]
    )
    app.config["SQLALCHEMY_DATABASE_URI"] = _normalize_sqlite_uri(
        app.config["SQLALCHEMY_DATABASE_URI"],
        app.instance_path,
    )
    sqlite_path = _sqlite_database_path(app.config["SQLALCHEMY_DATABASE_URI"])
    if sqlite_path is not None:
        sqlite_path.parent.mkdir(parents=True, exist_ok=True)

    storage_root = Path(app.config["STORAGE_ROOT"]).expanduser()
    if not storage_root.is_absolute():
        storage_root = Path(app.root_path).parent / storage_root
    app.config["STORAGE_ROOT"] = str(storage_root.resolve())


def _validate_production_config(app: Flask) -> None:
    if str(app.config.get("APP_ENV", "development")).lower() != "production":
        return
    errors: list[str] = []
    for key in ("SECRET_KEY", "JWT_SECRET_KEY"):
        value = str(app.config.get(key, ""))
        if len(value) < 32 or "change-me" in value or value.startswith("dev-"):
            errors.append(f"{key} must be a unique value of at least 32 characters")
    worker_token = str(app.config.get("TRAINING_WORKER_TOKEN", ""))
    if len(worker_token) < 32 or "change-me" in worker_token:
        errors.append("TRAINING_WORKER_TOKEN must be a unique value of at least 32 characters")
    if str(app.config.get("ENCRYPTION_KEY", "")) == "ZGF0YXNldC1nZW4tZGVtby1rZXktMzItYnl0ZXMhISE=":
        errors.append("ENCRYPTION_KEY must not use the repository demo value")
    try:
        encryption_key = base64.urlsafe_b64decode(str(app.config.get("ENCRYPTION_KEY", "")))
        if len(encryption_key) != 32:
            raise ValueError
    except Exception:
        errors.append("ENCRYPTION_KEY must be a base64-encoded 32-byte key")
    if not str(app.config.get("SQLALCHEMY_DATABASE_URI", "")).startswith("postgresql"):
        errors.append("production DATABASE_URL must use PostgreSQL")
    if app.config.get("AUTO_CREATE_SCHEMA"):
        errors.append("AUTO_CREATE_SCHEMA must be false in production; run Alembic migrations")
    if str(app.config.get("REGISTRATION_MODE", "disabled")) not in {"disabled", "open"}:
        errors.append("REGISTRATION_MODE must be disabled or open")
    if errors:
        raise RuntimeError("Invalid production configuration: " + "; ".join(errors))


def _normalize_sqlite_uri(database_uri: str, instance_path: str) -> str:
    sqlite_prefix = "sqlite:///"
    if not database_uri.startswith(sqlite_prefix) or database_uri == "sqlite:///:memory:":
        return database_uri
    if database_uri.startswith("sqlite:////"):
        return database_uri

    raw_path = database_uri[len(sqlite_prefix) :]
    if os.path.isabs(raw_path):
        return database_uri
    return f"{sqlite_prefix}{(Path(instance_path) / raw_path).resolve().as_posix()}"


def _sqlite_database_path(database_uri: str) -> Path | None:
    if database_uri == "sqlite:///:memory:":
        return None
    if not database_uri.startswith("sqlite:///"):
        return None
    return Path(database_uri.removeprefix("sqlite:///"))


def _is_sqlite_file_uri(database_uri: str) -> bool:
    return database_uri.startswith("sqlite:///") and database_uri != "sqlite:///:memory:"


def _ensure_demo_user(app: Flask) -> None:
    demo_username = app.config["DEMO_USERNAME"]
    existing = User.query.filter_by(email=demo_username).first()
    if existing:
        ensure_default_model_profiles(existing)
        return
    demo_user = User(
        email=demo_username,
        password_hash=generate_password_hash(app.config["DEMO_PASSWORD"]),
        plan="pro",
    )
    db.session.add(demo_user)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        existing = User.query.filter_by(email=demo_username).first()
        if existing:
            ensure_default_model_profiles(existing)
        return
    ensure_default_model_profiles(demo_user)


def _configure_database_engine(app: Flask) -> None:
    uri = app.config.get("SQLALCHEMY_DATABASE_URI", "")
    options = dict(app.config.get("SQLALCHEMY_ENGINE_OPTIONS") or {})
    if _is_sqlite_file_uri(uri):
        connect_args = dict(options.get("connect_args") or {})
        connect_args.setdefault("timeout", 60)
        connect_args.setdefault("check_same_thread", False)
        options["connect_args"] = connect_args
    elif uri.startswith("postgresql"):
        options.setdefault("pool_pre_ping", True)
        options.setdefault("pool_size", int(app.config["DATABASE_POOL_SIZE"]))
        options.setdefault("max_overflow", int(app.config["DATABASE_MAX_OVERFLOW"]))
        options.setdefault("pool_timeout", int(app.config["DATABASE_POOL_TIMEOUT"]))
        options.setdefault("pool_recycle", 1800)
        connect_args = dict(options.get("connect_args") or {})
        timeout = int(app.config["DATABASE_STATEMENT_TIMEOUT_MS"])
        connect_args.setdefault(
            "options",
            f"-c statement_timeout={timeout} -c idle_in_transaction_session_timeout={timeout}",
        )
        options["connect_args"] = connect_args

    if options:
        app.config["SQLALCHEMY_ENGINE_OPTIONS"] = options


def _backfill_detection_categories(app: Flask, *, batch_size: int = 500) -> None:
    inspector = inspect(db.engine)
    if "dataset_images" not in inspector.get_table_names():
        return
    image_columns = {column["name"] for column in inspector.get_columns("dataset_images")}
    if "detection_categories" not in image_columns:
        return

    from app.services.annotation_storage import load_annotation_result

    storage_root = app.config["STORAGE_ROOT"]
    pending = (
        DatasetImage.query.filter(DatasetImage.annotation_status == "annotated")
        .filter(or_(DatasetImage.detection_categories.is_(None), DatasetImage.detection_categories == []))
        .order_by(DatasetImage.created_at.asc(), DatasetImage.ordinal.asc())
        .limit(batch_size)
        .all()
    )
    if not pending:
        return

    for image in pending:
        result = load_annotation_result(storage_root, image.dataset_id, image.id)
        categories = sorted(
            {
                str(detection["category"])
                for detection in (result or {}).get("detections", [])
                if detection.get("category")
            }
        )
        image.detection_categories = categories
    db.session.commit()


def _register_cli(app: Flask) -> None:
    @app.cli.command("create-admin")
    @click.option("--username", prompt=True)
    @click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True)
    def create_admin(username: str, password: str) -> None:
        """Create the first production user without startup side effects."""
        normalized = username.strip()
        if User.query.filter_by(email=normalized).first() is not None:
            raise click.ClickException("username already exists")
        user = User(email=normalized, password_hash=generate_password_hash(password), plan="pro")
        db.session.add(user)
        db.session.commit()
        ensure_default_model_profiles(user)
        click.echo(f"created admin user {normalized}")

    @app.cli.command("backfill-detection-categories")
    @click.option("--batch-size", default=500, type=click.IntRange(min=1))
    def backfill_detection_categories(batch_size: int) -> None:
        """Run the legacy annotation category backfill explicitly."""
        _backfill_detection_categories(app, batch_size=batch_size)
        click.echo("backfill batch complete")

    @app.cli.command("gc-assets")
    @click.option("--retention-hours", type=int, default=None)
    def garbage_collect_assets(retention_hours: int | None) -> None:
        """Purge files whose asset tombstones passed the retention window."""
        from app.services.asset_gc_service import garbage_collect_deleted_assets

        count = garbage_collect_deleted_assets(
            app.config["STORAGE_ROOT"],
            retention_hours=(
                int(retention_hours)
                if retention_hours is not None
                else int(app.config["ASSET_GC_RETENTION_HOURS"])
            ),
        )
        click.echo(f"purged {count} deleted assets")


def _make_celery(app: Flask) -> None:
    celery.conf.update(
        broker_url=app.config["CELERY_BROKER_URL"],
        result_backend=app.config["CELERY_RESULT_BACKEND"],
        task_track_started=app.config.get("CELERY_TASK_TRACK_STARTED", True),
        task_time_limit=app.config.get("CELERY_TASK_TIME_LIMIT", 3600),
        broker_connection_retry_on_startup=app.config.get("CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP", True),
    )

    # Propagate any other CELERY_ prefixed config keys (strip CELERY_ prefix and lower-case)
    for key, value in app.config.items():
        if key.startswith("CELERY_"):
            celery.conf[key[7:].lower()] = value

    celery.conf["flask_app"] = app
