from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import create_access_token, get_jwt_identity, jwt_required
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db
from app.models import User
from app.schemas import CredentialSchema
from app.services.model_profile_service import ensure_default_model_profiles

auth_bp = Blueprint("auth", __name__)


def _serialize_user(user: User) -> dict[str, str]:
    return {"id": user.id, "username": user.email, "plan": user.plan}


@auth_bp.post("/register")
def register():
    payload = CredentialSchema().load(request.get_json() or {})
    existing_user = User.query.filter_by(email=payload["username"]).first()
    if existing_user:
        return jsonify({"message": "username already registered"}), 409

    user = User(email=payload["username"], password_hash=generate_password_hash(payload["password"]))
    db.session.add(user)
    db.session.commit()
    ensure_default_model_profiles(user)

    access_token = create_access_token(identity=user.id)
    return jsonify({"token": access_token, "user": _serialize_user(user)}), 201


@auth_bp.post("/login")
def login():
    payload = CredentialSchema().load(request.get_json() or {})
    user = User.query.filter_by(email=payload["username"]).first()
    if not user or not check_password_hash(user.password_hash, payload["password"]):
        return jsonify({"message": "invalid username or password"}), 401

    access_token = create_access_token(identity=user.id)
    return jsonify({"token": access_token, "user": _serialize_user(user)})


@auth_bp.get("/me")
@jwt_required()
def me():
    user_id = get_jwt_identity()
    user = User.query.get_or_404(user_id)
    return jsonify(
        {
            "user": {
                "id": user.id,
                "username": user.email,
                "plan": user.plan,
                "demoUsername": current_app.config["DEMO_USERNAME"],
            }
        }
    )
