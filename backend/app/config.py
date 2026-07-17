from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parent.parent


def _default_postgresql_uri() -> str:
    return "postgresql+psycopg://dataset_gen:dataset_gen@localhost:5432/dataset_gen"


def normalize_database_uri(database_uri: str) -> str:
    if database_uri.startswith("postgres://"):
        return f"postgresql+psycopg://{database_uri.removeprefix('postgres://')}"
    if database_uri.startswith("postgresql://"):
        return f"postgresql+psycopg://{database_uri.removeprefix('postgresql://')}"
    return database_uri


def _database_uri() -> str:
    return normalize_database_uri(os.getenv("DATABASE_URL", _default_postgresql_uri()))


def _default_storage_root() -> str:
    return str((BACKEND_ROOT / "storage").resolve())


def _default_encryption_key() -> str:
    return base64.b64encode(b"dataset-gen-demo-key-32-bytes!!!").decode("utf-8")


def _default_demo_username() -> str:
    explicit_username = os.getenv("DEMO_USERNAME", "").strip()
    if explicit_username:
        return explicit_username

    legacy_demo_email = os.getenv("DEMO_EMAIL", "").strip()
    if legacy_demo_email and "@" not in legacy_demo_email:
        return legacy_demo_email

    return "dataset"


@dataclass
class Config:
    APP_ENV: str = os.getenv("APP_ENV", "development")
    SECRET_KEY: str = os.getenv("SECRET_KEY", "dev-secret-key-please-change-123456")
    JWT_SECRET_KEY: str = os.getenv("JWT_SECRET_KEY", "dev-jwt-secret-key-please-change-123456")
    JWT_ACCESS_TOKEN_EXPIRES: timedelta = timedelta(
        minutes=int(os.getenv("JWT_ACCESS_TOKEN_EXPIRES_MINUTES", "15"))
    )
    JWT_REFRESH_TOKEN_EXPIRES: timedelta = timedelta(
        days=int(os.getenv("JWT_REFRESH_TOKEN_EXPIRES_DAYS", "30"))
    )
    SQLALCHEMY_DATABASE_URI: str = _database_uri()
    SQLALCHEMY_TRACK_MODIFICATIONS: bool = False
    FRONTEND_URL: str = os.getenv("FRONTEND_URL", "http://localhost:4173")
    API_PREFIX: str = "/api/v1"
    DEMO_USERNAME: str = _default_demo_username()
    DEMO_PASSWORD: str = os.getenv("DEMO_PASSWORD", "Dataset123!")
    ENCRYPTION_KEY: str = os.getenv("ENCRYPTION_KEY", _default_encryption_key())
    AUTO_CREATE_SCHEMA: bool = os.getenv("AUTO_CREATE_SCHEMA", "false").lower() == "true"
    BOOTSTRAP_DEMO_USER: bool = os.getenv("BOOTSTRAP_DEMO_USER", "false").lower() == "true"
    REGISTRATION_MODE: str = os.getenv("REGISTRATION_MODE", "disabled")
    REFRESH_COOKIE_NAME: str = os.getenv("REFRESH_COOKIE_NAME", "dataset_gen_refresh")
    REFRESH_COOKIE_SECURE: bool = os.getenv(
        "REFRESH_COOKIE_SECURE", "true" if os.getenv("APP_ENV", "development") == "production" else "false"
    ).lower() == "true"
    REFRESH_ROTATION_GRACE_SECONDS: int = int(os.getenv("REFRESH_ROTATION_GRACE_SECONDS", "10"))
    STORAGE_ROOT: str = os.getenv("STORAGE_ROOT", _default_storage_root())
    STORAGE_BACKEND: str = os.getenv("STORAGE_BACKEND", "local")
    USE_X_ACCEL_REDIRECT: bool = os.getenv("USE_X_ACCEL_REDIRECT", "false").lower() == "true"
    MAX_CONTENT_LENGTH: int = int(os.getenv("MAX_UPLOAD_BYTES", str(2 * 1024 * 1024 * 1024)))
    MAX_IMPORTED_IMAGES: int = int(os.getenv("MAX_IMPORTED_IMAGES", "2000"))
    ANNOTATOR_URL: str = os.getenv("ANNOTATOR_URL", "")
    VL_ANNOTATOR_PROVIDER: str = os.getenv("VL_ANNOTATOR_PROVIDER", "gemini")
    VL_ANNOTATOR_MODEL: str = os.getenv("VL_ANNOTATOR_MODEL", "gemini-2.0-flash")
    VL_ANNOTATOR_API_KEY: str = os.getenv("VL_ANNOTATOR_API_KEY", "")
    VL_ANNOTATOR_BASE_URL: str = os.getenv("VL_ANNOTATOR_BASE_URL", "")
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_IMAGE_MODEL: str = os.getenv("GEMINI_IMAGE_MODEL", "gemini-3.1-flash-image-preview")
    GEMINI_PERSON_GENERATION: str = os.getenv("GEMINI_PERSON_GENERATION", "allow_adult")
    GEMINI_HTTP_PROXY: str = os.getenv("GEMINI_HTTP_PROXY", "")
    JIMENG_BASE_URL: str = os.getenv(
        "JIMENG_BASE_URL", "https://operator.las.cn-beijing.volces.com/api/v1"
    )
    JIMENG_IMAGE_MODEL: str = os.getenv("JIMENG_IMAGE_MODEL", "doubao-seedream-3-0-t2i-250415")
    JIMENG_WATERMARK: bool = os.getenv("JIMENG_WATERMARK", "true").lower() == "true"
    OPENAI_COMPAT_API_KEY: str = os.getenv("OPENAI_COMPAT_API_KEY", "")
    OPENAI_COMPAT_BASE_URL: str = os.getenv("OPENAI_COMPAT_BASE_URL", "https://api.deepseek.com/v1")
    OPENAI_COMPAT_MODEL: str = os.getenv("OPENAI_COMPAT_MODEL", "deepseek-chat")
    IMAGE_BASE_URL: str = os.getenv("IMAGE_BASE_URL", "")
    TRAINING_WORKER_TOKEN: str = os.getenv("TRAINING_WORKER_TOKEN", "")
    TRAINING_DEFAULT_MODEL: str = os.getenv("TRAINING_DEFAULT_MODEL", "yolov8n.pt")
    CELERY_BROKER_URL: str = os.getenv("CELERY_BROKER_URL", "redis://redis:6379/0")
    CELERY_RESULT_BACKEND: str = os.getenv("CELERY_RESULT_BACKEND", "redis://redis:6379/0")
    CELERY_TASK_TRACK_STARTED: bool = True
    CELERY_TASK_TIME_LIMIT: int = 3600
    CELERY_TASK_SOFT_TIME_LIMIT: int = 3300
    CELERY_TASK_ACKS_LATE: bool = True
    CELERY_TASK_REJECT_ON_WORKER_LOST: bool = True
    CELERY_WORKER_PREFETCH_MULTIPLIER: int = 1
    CELERY_TASK_IGNORE_RESULT: bool = True
    CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP: bool = True
    DATABASE_POOL_SIZE: int = int(os.getenv("DATABASE_POOL_SIZE", "10"))
    DATABASE_MAX_OVERFLOW: int = int(os.getenv("DATABASE_MAX_OVERFLOW", "10"))
    DATABASE_POOL_TIMEOUT: int = int(os.getenv("DATABASE_POOL_TIMEOUT", "30"))
    DATABASE_STATEMENT_TIMEOUT_MS: int = int(os.getenv("DATABASE_STATEMENT_TIMEOUT_MS", "60000"))
    TRAINING_JOB_LEASE_SECONDS: int = int(os.getenv("TRAINING_JOB_LEASE_SECONDS", "120"))
    TRAINING_WORKER_OFFLINE_SECONDS: int = int(os.getenv("TRAINING_WORKER_OFFLINE_SECONDS", "60"))
    TASK_ITEM_LEASE_SECONDS: int = int(os.getenv("TASK_ITEM_LEASE_SECONDS", "900"))
    ASSET_GC_RETENTION_HOURS: int = int(os.getenv("ASSET_GC_RETENTION_HOURS", "24"))
    IDEMPOTENCY_TTL_HOURS: int = int(os.getenv("IDEMPOTENCY_TTL_HOURS", "24"))
    OUTBOX_POLL_INTERVAL_SECONDS: float = float(os.getenv("OUTBOX_POLL_INTERVAL_SECONDS", "1"))
    OUTBOX_BATCH_SIZE: int = int(os.getenv("OUTBOX_BATCH_SIZE", "100"))


@dataclass
class TestConfig(Config):
    __test__ = False
    TESTING: bool = True
    SQLALCHEMY_DATABASE_URI: str = "sqlite:///:memory:"
    AUTO_CREATE_SCHEMA: bool = True
    BOOTSTRAP_DEMO_USER: bool = True
    REGISTRATION_MODE: str = "open"
    REFRESH_COOKIE_SECURE: bool = False
    CELERY_BROKER_URL: str = "memory://"
    CELERY_RESULT_BACKEND: str = "cache+memory://"
    CELERY_TASK_ALWAYS_EAGER: bool = True
    CELERY_TASK_EAGER_PROPAGATES: bool = True
