from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parent.parent


def _default_sqlite_uri() -> str:
    return f"sqlite:///{(BACKEND_ROOT / 'instance' / 'dataset_gen_dev.db').resolve().as_posix()}"


def _default_storage_root() -> str:
    return str((BACKEND_ROOT / "storage").resolve())


def _default_encryption_key() -> str:
    return base64.b64encode(b"dataset-gen-demo-key-32-bytes!!!").decode("utf-8")


@dataclass
class Config:
    SECRET_KEY: str = os.getenv("SECRET_KEY", "dev-secret-key-please-change-123456")
    JWT_SECRET_KEY: str = os.getenv("JWT_SECRET_KEY", "dev-jwt-secret-key-please-change-123456")
    JWT_ACCESS_TOKEN_EXPIRES: timedelta = timedelta(
        days=int(os.getenv("JWT_ACCESS_TOKEN_EXPIRES_DAYS", "7"))
    )
    SQLALCHEMY_DATABASE_URI: str = os.getenv("DATABASE_URL", _default_sqlite_uri())
    SQLALCHEMY_TRACK_MODIFICATIONS: bool = False
    FRONTEND_URL: str = os.getenv("FRONTEND_URL", "http://localhost:4173")
    API_PREFIX: str = "/api/v1"
    DEMO_EMAIL: str = os.getenv("DEMO_EMAIL", "demo@dataset.local")
    DEMO_PASSWORD: str = os.getenv("DEMO_PASSWORD", "Dataset123!")
    ENCRYPTION_KEY: str = os.getenv("ENCRYPTION_KEY", _default_encryption_key())
    AUTO_CREATE_SCHEMA: bool = os.getenv("AUTO_CREATE_SCHEMA", "true").lower() == "true"
    STORAGE_ROOT: str = os.getenv("STORAGE_ROOT", _default_storage_root())
    ANNOTATOR_URL: str = os.getenv("ANNOTATOR_URL", "")
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_IMAGE_MODEL: str = os.getenv("GEMINI_IMAGE_MODEL", "gemini-3.1-flash-image-preview")
    GEMINI_PERSON_GENERATION: str = os.getenv("GEMINI_PERSON_GENERATION", "allow_adult")
    JIMENG_BASE_URL: str = os.getenv(
        "JIMENG_BASE_URL", "https://operator.las.cn-beijing.volces.com/api/v1"
    )
    JIMENG_IMAGE_MODEL: str = os.getenv("JIMENG_IMAGE_MODEL", "doubao-seedream-3-0-t2i-250415")
    JIMENG_WATERMARK: bool = os.getenv("JIMENG_WATERMARK", "true").lower() == "true"
    OPENAI_COMPAT_API_KEY: str = os.getenv("OPENAI_COMPAT_API_KEY", "")
    OPENAI_COMPAT_BASE_URL: str = os.getenv("OPENAI_COMPAT_BASE_URL", "https://api.deepseek.com/v1")
    OPENAI_COMPAT_MODEL: str = os.getenv("OPENAI_COMPAT_MODEL", "deepseek-chat")
    IMAGE_BASE_URL: str = os.getenv("IMAGE_BASE_URL", "")


@dataclass
class TestConfig(Config):
    __test__ = False
    TESTING: bool = True
    SQLALCHEMY_DATABASE_URI: str = "sqlite:///:memory:"
    AUTO_CREATE_SCHEMA: bool = True
