from __future__ import annotations

import os
from pathlib import Path

from flask import Flask, jsonify
from marshmallow import ValidationError
from sqlalchemy import inspect, text
from werkzeug.security import generate_password_hash

from app.api.auth import auth_bp
from app.api.system import system_bp
from app.api.tasks import tasks_bp
from app.config import Config
from app.extensions import cors, db, jwt
from app.models import User
from app.services.model_profile_service import ensure_default_model_profiles


def create_app(
    config_object: type[Config] | None = None, *, instance_path: str | os.PathLike[str] | None = None
) -> Flask:
    app = Flask(__name__, instance_path=str(instance_path) if instance_path is not None else None)
    app.config.from_object(config_object or Config)
    _prepare_runtime_paths(app)

    db.init_app(app)
    jwt.init_app(app)
    cors.init_app(
        app,
        resources={f"{app.config['API_PREFIX']}/*": {"origins": app.config["FRONTEND_URL"]}},
        supports_credentials=True,
    )

    api_prefix = app.config["API_PREFIX"]
    app.register_blueprint(auth_bp, url_prefix=f"{api_prefix}/auth")
    app.register_blueprint(system_bp, url_prefix=f"{api_prefix}/system")
    app.register_blueprint(tasks_bp, url_prefix=f"{api_prefix}/tasks")

    @app.get(f"{api_prefix}/health")
    def healthcheck():
        return jsonify({"status": "ok"})

    @app.errorhandler(ValidationError)
    def handle_validation_error(error: ValidationError):
        return jsonify({"message": "validation_error", "errors": error.messages}), 422

    with app.app_context():
        os.makedirs(app.config["STORAGE_ROOT"], exist_ok=True)
        if app.config["AUTO_CREATE_SCHEMA"]:
            db.create_all()
            _ensure_schema_columns()
            _ensure_demo_user(app)

    return app


def _prepare_runtime_paths(app: Flask) -> None:
    os.makedirs(app.instance_path, exist_ok=True)
    app.config["SQLALCHEMY_DATABASE_URI"] = _normalize_sqlite_uri(
        app.config["SQLALCHEMY_DATABASE_URI"], app.instance_path
    )
    sqlite_path = _sqlite_database_path(app.config["SQLALCHEMY_DATABASE_URI"])
    if sqlite_path is not None:
        sqlite_path.parent.mkdir(parents=True, exist_ok=True)

    storage_root = Path(app.config["STORAGE_ROOT"]).expanduser()
    if not storage_root.is_absolute():
        storage_root = Path(app.root_path).parent / storage_root
    app.config["STORAGE_ROOT"] = str(storage_root.resolve())


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


def _ensure_demo_user(app: Flask) -> None:
    demo_email = app.config["DEMO_EMAIL"]
    existing = User.query.filter_by(email=demo_email).first()
    if existing:
        ensure_default_model_profiles(existing)
        return
    demo_user = User(
        email=demo_email,
        password_hash=generate_password_hash(app.config["DEMO_PASSWORD"]),
        plan="pro",
    )
    db.session.add(demo_user)
    db.session.commit()
    ensure_default_model_profiles(demo_user)


def _ensure_schema_columns() -> None:
    inspector = inspect(db.engine)
    if "model_profiles" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("model_profiles")}
    statements: list[str] = []
    if "profile_type" not in existing_columns:
        statements.append("ALTER TABLE model_profiles ADD COLUMN profile_type VARCHAR(16) NOT NULL DEFAULT 'image'")
    if "base_url" not in existing_columns:
        statements.append("ALTER TABLE model_profiles ADD COLUMN base_url VARCHAR(255)")

    for statement in statements:
        db.session.execute(text(statement))
    if statements:
        db.session.commit()
