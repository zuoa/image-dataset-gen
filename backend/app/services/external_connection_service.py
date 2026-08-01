from __future__ import annotations

import re
from typing import Any
from urllib.parse import unquote, urlsplit

from flask import current_app

from app.models import ExternalConnection, utcnow
from app.services.roboflow_import_service import _make_roboflow_client
from app.utils.crypto import decrypt_secret, encrypt_secret


class ConnectionValidationError(RuntimeError):
    pass


class RoboflowProjectResolutionError(RuntimeError):
    pass


ROBOFLOW_SLUG_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


def resolve_roboflow_project_link(api_key: str, project_url: str) -> dict[str, Any]:
    workspace_id, project_id, requested_version = _parse_roboflow_project_link(
        project_url
    )
    try:
        client = _make_roboflow_client(api_key)
        project = client.workspace(workspace_id).project(project_id)
        version_information = project.get_version_information()
    except Exception as exc:
        raise RoboflowProjectResolutionError(
            "无法读取 Roboflow 项目，请检查连接权限和项目链接。"
        ) from exc

    versions = _normalize_roboflow_versions(version_information)
    available_versions = {item["version"] for item in versions}
    if requested_version and requested_version not in available_versions:
        raise RoboflowProjectResolutionError("链接中的 Roboflow 数据版本不存在或不可用。")

    return {
        "workspace": workspace_id,
        "project": project_id,
        "projectName": str(getattr(project, "name", "") or project_id),
        "projectType": str(getattr(project, "type", "") or ""),
        "versions": versions,
        "selectedVersion": requested_version
        or (versions[0]["version"] if versions else None),
    }


def _parse_roboflow_project_link(project_url: str) -> tuple[str, str, str | None]:
    raw_url = str(project_url or "").strip()
    try:
        parsed = urlsplit(raw_url)
    except ValueError as exc:
        raise RoboflowProjectResolutionError("Roboflow 项目链接格式不正确。") from exc

    try:
        invalid_authority = (
            parsed.scheme.lower() != "https"
            or parsed.hostname != "app.roboflow.com"
            or parsed.port is not None
            or parsed.username is not None
            or parsed.password is not None
        )
    except ValueError as exc:
        raise RoboflowProjectResolutionError(
            "Roboflow 项目链接格式不正确。"
        ) from exc
    if invalid_authority:
        raise RoboflowProjectResolutionError(
            "请输入 https://app.roboflow.com 的项目链接。"
        )

    segments = [
        unquote(segment).strip() for segment in parsed.path.split("/") if segment
    ]
    if (
        len(segments) != 3
        or not ROBOFLOW_SLUG_PATTERN.fullmatch(segments[0])
        or not ROBOFLOW_SLUG_PATTERN.fullmatch(segments[1])
    ):
        raise RoboflowProjectResolutionError(
            "链接应为 Roboflow 项目的 browse 页面或数据版本页面。"
        )

    workspace_id, project_id, page = segments
    requested_version = None
    if page != "browse":
        if not page.isdigit() or int(page) < 1:
            raise RoboflowProjectResolutionError(
                "链接应为 Roboflow 项目的 browse 页面或数据版本页面。"
            )
        requested_version = str(int(page))
    return workspace_id, project_id, requested_version


def _normalize_roboflow_versions(version_information: object) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    if not isinstance(version_information, list):
        return normalized

    for item in version_information:
        if not isinstance(item, dict):
            continue
        raw_version = (
            str(item.get("id") or item.get("version") or "")
            .rstrip("/")
            .split("/")[-1]
        )
        if not raw_version.isdigit() or int(raw_version) < 1:
            continue
        try:
            image_count = max(0, int(item.get("images") or 0))
        except (TypeError, ValueError):
            image_count = 0
        normalized.append(
            {
                "version": str(int(raw_version)),
                "name": str(item.get("name") or "").strip(),
                "imageCount": image_count,
            }
        )

    normalized.sort(key=lambda item: int(item["version"]), reverse=True)
    return normalized


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
