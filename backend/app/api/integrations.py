from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import ExternalConnection
from app.schemas import ExternalConnectionSchema
from app.services.external_connection_service import (
    ConnectionValidationError,
    build_connection_payload,
    connection_secret,
    mark_connection_valid,
    set_connection_secret,
    validate_roboflow_api_key,
)
from app.utils.crypto import encrypt_secret


integrations_bp = Blueprint("integrations", __name__)


def _connection_for_user(connection_id: str, user_id: str) -> ExternalConnection:
    return ExternalConnection.query.filter_by(
        id=connection_id, user_id=user_id, provider="roboflow"
    ).first_or_404()


@integrations_bp.get("/roboflow/connections")
@jwt_required()
def list_roboflow_connections():
    user_id = get_jwt_identity()
    connections = (
        ExternalConnection.query.filter_by(user_id=user_id, provider="roboflow")
        .order_by(ExternalConnection.created_at.asc())
        .all()
    )
    return jsonify(
        {"connections": [build_connection_payload(item) for item in connections]}
    )


@integrations_bp.post("/roboflow/connections")
@jwt_required()
def create_roboflow_connection():
    user_id = get_jwt_identity()
    payload = ExternalConnectionSchema().load(request.get_json() or {})
    api_key = str(payload.get("apiKey") or "").strip()
    if len(api_key) < 8:
        return jsonify({"message": "API Key 至少需要 8 个字符。"}), 422
    try:
        metadata = validate_roboflow_api_key(api_key)
    except ConnectionValidationError as exc:
        return jsonify({"message": str(exc)}), 400

    connection = ExternalConnection(
        user_id=user_id,
        provider="roboflow",
        name=payload["name"].strip(),
        secret_encrypted=encrypt_secret(
            api_key, current_app.config["ENCRYPTION_KEY"]
        ),
        key_version=1,
    )
    mark_connection_valid(connection, metadata)
    db.session.add(connection)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"message": "已存在同名 Roboflow 连接。"}), 409
    return jsonify({"connection": build_connection_payload(connection)}), 201


@integrations_bp.patch("/roboflow/connections/<connection_id>")
@jwt_required()
def update_roboflow_connection(connection_id: str):
    user_id = get_jwt_identity()
    payload = ExternalConnectionSchema().load(request.get_json() or {}, partial=True)
    connection = _connection_for_user(connection_id, user_id)
    if "name" in payload:
        connection.name = payload["name"].strip()
    api_key = str(payload.get("apiKey") or "").strip()
    if api_key:
        if len(api_key) < 8:
            return jsonify({"message": "API Key 至少需要 8 个字符。"}), 422
        try:
            metadata = validate_roboflow_api_key(api_key)
        except ConnectionValidationError as exc:
            return jsonify({"message": str(exc)}), 400
        set_connection_secret(connection, api_key)
        mark_connection_valid(connection, metadata)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"message": "已存在同名 Roboflow 连接。"}), 409
    return jsonify({"connection": build_connection_payload(connection)})


@integrations_bp.post("/roboflow/connections/<connection_id>/validate")
@jwt_required()
def validate_roboflow_connection(connection_id: str):
    user_id = get_jwt_identity()
    connection = _connection_for_user(connection_id, user_id)
    try:
        metadata = validate_roboflow_api_key(connection_secret(connection))
    except ConnectionValidationError as exc:
        connection.status = "invalid"
        connection.last_error = "validation_failed"
        db.session.commit()
        return jsonify({"message": str(exc), "connection": build_connection_payload(connection)}), 400
    mark_connection_valid(connection, metadata)
    db.session.commit()
    return jsonify({"connection": build_connection_payload(connection)})


@integrations_bp.delete("/roboflow/connections/<connection_id>")
@jwt_required()
def delete_roboflow_connection(connection_id: str):
    user_id = get_jwt_identity()
    connection = _connection_for_user(connection_id, user_id)
    db.session.delete(connection)
    db.session.commit()
    return jsonify({"deleted": True, "id": connection_id})
