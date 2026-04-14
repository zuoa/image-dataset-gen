from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import create_access_token, get_jwt_identity, jwt_required
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db
from app.models import User
from app.schemas import LoginSchema, RegisterSchema
from app.services.model_profile_service import ensure_default_model_profiles

auth_bp = Blueprint("auth", __name__)


@auth_bp.post("/register")
def register():
    payload = RegisterSchema().load(request.get_json() or {})
    existing_user = User.query.filter_by(email=payload["email"]).first()
    if existing_user:
        return jsonify({"message": "email already registered"}), 409

    user = User(email=payload["email"], password_hash=generate_password_hash(payload["password"]))
    db.session.add(user)
    db.session.commit()
    ensure_default_model_profiles(user)

    access_token = create_access_token(identity=user.id)
    return (
        jsonify(
            {
                "token": access_token,
                "user": {"id": user.id, "email": user.email, "plan": user.plan},
            }
        ),
        201,
    )


@auth_bp.post("/login")
def login():
    payload = LoginSchema().load(request.get_json() or {})
    user = User.query.filter_by(email=payload["email"]).first()
    if not user or not check_password_hash(user.password_hash, payload["password"]):
        return jsonify({"message": "invalid email or password"}), 401

    access_token = create_access_token(identity=user.id)
    return jsonify({"token": access_token, "user": {"id": user.id, "email": user.email, "plan": user.plan}})


@auth_bp.get("/me")
@jwt_required()
def me():
    user_id = get_jwt_identity()
    user = User.query.get_or_404(user_id)
    return jsonify(
        {
            "user": {
                "id": user.id,
                "email": user.email,
                "plan": user.plan,
                "demoEmail": current_app.config["DEMO_EMAIL"],
            }
        }
    )
