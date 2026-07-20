from __future__ import annotations

import hmac
import os
from typing import Any

from flask import Flask, jsonify, request

from app.engine import (
    SegmenterError,
    SegmenterSessionNotFound,
    build_engine_from_environment,
)


def create_app(*, engine: Any | None = None, shared_token: str | None = None) -> Flask:
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = int(os.getenv("SEGMENTER_MAX_IMAGE_BYTES", str(25 * 1024 * 1024)))
    resolved_token = os.getenv("SEGMENTER_SHARED_TOKEN", "") if shared_token is None else shared_token
    if not resolved_token:
        raise RuntimeError("SEGMENTER_SHARED_TOKEN is required")
    resolved_engine = engine or build_engine_from_environment()

    def authorized() -> bool:
        if not resolved_token:
            return False
        authorization = request.headers.get("Authorization", "")
        scheme, _, supplied_token = authorization.partition(" ")
        return scheme.lower() == "bearer" and hmac.compare_digest(supplied_token, resolved_token)

    @app.before_request
    def require_service_token():
        if request.path.startswith("/health/"):
            return None
        if not authorized():
            return jsonify({"message": "unauthorized"}), 401
        return None

    @app.get("/health/live")
    def liveness():
        return jsonify({"status": "ok"})

    @app.get("/health/ready")
    def readiness():
        return jsonify({"status": "ok", "model": resolved_engine.model_name})

    @app.post("/v1/sessions")
    def create_session():
        uploaded = request.files.get("image")
        if uploaded is None:
            return jsonify({"message": "image is required"}), 422
        image_bytes = uploaded.read()
        if not image_bytes:
            return jsonify({"message": "image is empty"}), 422
        try:
            session_id, width, height, expires_in = resolved_engine.create_session(image_bytes)
        except SegmenterError as exc:
            return jsonify({"message": str(exc)}), 422
        return jsonify(
            {
                "sessionId": session_id,
                "imageWidth": width,
                "imageHeight": height,
                "expiresIn": expires_in,
                "model": resolved_engine.model_name,
            }
        ), 201

    @app.post("/v1/sessions/<session_id>/predict")
    def predict(session_id: str):
        payload = request.get_json(silent=True) or {}
        points = payload.get("points")
        validation_error = _validate_points(points)
        if validation_error:
            return jsonify({"message": validation_error}), 422
        try:
            result = resolved_engine.predict(session_id, points)
        except SegmenterSessionNotFound as exc:
            return jsonify({"message": str(exc)}), 404
        except (SegmenterError, ValueError) as exc:
            return jsonify({"message": str(exc)}), 422
        return jsonify(result)

    @app.delete("/v1/sessions/<session_id>")
    def delete_session(session_id: str):
        try:
            resolved_engine.delete_session(session_id)
        except SegmenterSessionNotFound:
            pass
        return "", 204

    return app


def _validate_points(points: object) -> str | None:
    if not isinstance(points, list) or not 1 <= len(points) <= 20:
        return "points must contain between 1 and 20 items"
    has_positive = False
    for point in points:
        if not isinstance(point, dict):
            return "each point must be an object"
        if point.get("label") not in {"positive", "negative"}:
            return "point label must be positive or negative"
        has_positive = has_positive or point.get("label") == "positive"
        for coordinate in ("x", "y"):
            value = point.get(coordinate)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= float(value) <= 1:
                return f"point {coordinate} must be between 0 and 1"
    if not has_positive:
        return "at least one positive point is required"
    return None
