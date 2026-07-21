from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from app.extensions import db
from app.models import ModelProfile, User
from app.schemas import ModelProfileSchema
from app.services.dataset_service import build_dataset_summary_for_user
from app.services.model_profile_service import (
    _resolved_profile_api_key,
    build_model_profile_payload,
    create_model_profile,
    ensure_default_model_profiles,
)
from app.services.provider_catalog import PROVIDER_CATALOG
from app.services.provider_model_service import list_available_image_models
from app.utils.crypto import encrypt_secret

system_bp = Blueprint("system", __name__)


@system_bp.get("/providers")
def providers():
    return jsonify({"providers": PROVIDER_CATALOG})


@system_bp.get("/dashboard")
@jwt_required()
def dashboard():
    user_id = get_jwt_identity()
    return jsonify({"summary": build_dataset_summary_for_user(user_id)})


@system_bp.get("/model-profiles")
@jwt_required()
def list_model_profiles():
    user_id = get_jwt_identity()
    user = User.query.get_or_404(user_id)
    ensure_default_model_profiles(user)
    profiles = (
        ModelProfile.query.filter_by(user_id=user_id).order_by(ModelProfile.created_at.asc()).all()
    )
    return jsonify({"profiles": [build_model_profile_payload(profile) for profile in profiles]})


@system_bp.get("/model-profiles/<profile_id>/available-models")
@jwt_required()
def available_models(profile_id: str):
    user_id = get_jwt_identity()
    profile = ModelProfile.query.filter_by(id=profile_id, user_id=user_id).first_or_404()
    if profile.profile_type != "image":
        return jsonify({"message": "available models are only supported for image profiles"}), 422

    force_refresh = request.args.get("refresh", "").lower() in {"1", "true", "yes"}
    result = list_available_image_models(
        provider_id=profile.provider_id,
        api_key=_resolved_profile_api_key(profile),
        force_refresh=force_refresh,
    )
    return jsonify(result)


@system_bp.post("/model-profiles")
@jwt_required()
def create_model_profile_endpoint():
    user_id = get_jwt_identity()
    payload = ModelProfileSchema().load(request.get_json() or {})
    if len(payload["apiKey"].strip()) < 8:
        return jsonify({"message": "apiKey must contain at least 8 characters"}), 422
    profile = create_model_profile(
        user_id,
        {
            "profile_type": payload["profileType"],
            "name": payload["name"],
            "provider_id": payload["providerId"],
            "base_url": (payload.get("baseUrl") or "").strip() or None,
            "model": payload["model"],
            "api_key": payload["apiKey"],
            "concurrency": payload["concurrency"],
            "batch_size": payload["batchSize"],
            "jimeng_watermark": payload["jimengWatermark"],
            "notes": payload.get("notes") or "",
        },
    )
    db.session.commit()
    return jsonify({"profile": build_model_profile_payload(profile)}), 201


@system_bp.patch("/model-profiles/<profile_id>")
@jwt_required()
def update_model_profile_endpoint(profile_id: str):
    user_id = get_jwt_identity()
    payload = ModelProfileSchema().load(request.get_json() or {})
    profile = ModelProfile.query.filter_by(id=profile_id, user_id=user_id).first_or_404()
    replacement_api_key = payload["apiKey"].strip()
    if payload["providerId"] != profile.provider_id and not replacement_api_key:
        return jsonify({"message": "apiKey is required when changing providers"}), 422

    profile.profile_type = payload["profileType"]
    profile.name = payload["name"]
    profile.provider_id = payload["providerId"]
    profile.base_url = (payload.get("baseUrl") or "").strip() or None
    profile.model = payload["model"]
    if replacement_api_key:
        if len(replacement_api_key) < 8:
            return jsonify({"message": "apiKey must contain at least 8 characters"}), 422
        profile.api_key_encrypted = encrypt_secret(
            replacement_api_key, current_app.config["ENCRYPTION_KEY"]
        )
    profile.concurrency = payload["concurrency"]
    profile.batch_size = payload["batchSize"]
    profile.jimeng_watermark = payload["jimengWatermark"]
    profile.notes = payload.get("notes") or ""

    db.session.commit()
    return jsonify({"profile": build_model_profile_payload(profile)})


@system_bp.delete("/model-profiles/<profile_id>")
@jwt_required()
def delete_model_profile_endpoint(profile_id: str):
    user_id = get_jwt_identity()
    profile = ModelProfile.query.filter_by(id=profile_id, user_id=user_id).first_or_404()
    db.session.delete(profile)
    db.session.commit()
    return jsonify({"deleted": True, "id": profile_id})
