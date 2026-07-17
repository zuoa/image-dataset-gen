from __future__ import annotations

from typing import Any

from flask import current_app

from app.models import ExternalConnection, utcnow
from app.services.roboflow_import_service import _make_roboflow_client
from app.utils.crypto import decrypt_secret, encrypt_secret


class ConnectionValidationError(RuntimeError):
    pass


def validate_roboflow_api_key(api_key: str) -> dict[str, Any]:
    """Validate a key without retaining it or exposing provider errors."""
    try:
        client = _make_roboflow_client(api_key)
        workspace = client.workspace()
    except Exception as exc:
        raise ConnectionValidationError("Roboflow API Key 验证失败。") from exc

    workspace_name = str(
        getattr(workspace, "name", "")
        or getattr(workspace, "workspace", "")
        or ""
    ).strip()
    return {"workspace": workspace_name}


def set_connection_secret(connection: ExternalConnection, api_key: str) -> None:
    connection.secret_encrypted = encrypt_secret(
        api_key, current_app.config["ENCRYPTION_KEY"]
    )
    connection.key_version = int(connection.key_version or 0) + 1


def connection_secret(connection: ExternalConnection) -> str:
    return decrypt_secret(
        connection.secret_encrypted, current_app.config["ENCRYPTION_KEY"]
    )


def mark_connection_valid(
    connection: ExternalConnection, metadata: dict[str, Any] | None = None
) -> None:
    connection.status = "valid"
    connection.last_validated_at = utcnow()
    connection.last_error = ""
    connection.metadata_json = {**(connection.metadata_json or {}), **(metadata or {})}


def build_connection_payload(connection: ExternalConnection) -> dict[str, Any]:
    return {
        "id": connection.id,
        "provider": connection.provider,
        "name": connection.name,
        "hasApiKey": bool(connection.secret_encrypted),
        "status": connection.status,
        "metadata": connection.metadata_json or {},
        "lastValidatedAt": (
            connection.last_validated_at.isoformat()
            if connection.last_validated_at
            else None
        ),
        "createdAt": connection.created_at.isoformat() if connection.created_at else None,
        "updatedAt": connection.updated_at.isoformat() if connection.updated_at else None,
    }
