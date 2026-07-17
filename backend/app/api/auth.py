from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import secrets
from urllib.parse import urlsplit

from cryptography.exceptions import InvalidTag
from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import create_access_token, get_jwt_identity, jwt_required
from sqlalchemy import select
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db
from app.models import RefreshSession, User, generate_uuid
from app.schemas import CredentialSchema, LoginSchema
from app.services.captcha_service import consume_login_captcha, issue_login_captcha
from app.services.model_profile_service import ensure_default_model_profiles
from app.utils.crypto import decrypt_secret, encrypt_secret

auth_bp = Blueprint("auth", __name__)


def _serialize_user(user: User) -> dict[str, str]:
    return {"id": user.id, "username": user.email, "plan": user.plan}


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _client_ip() -> str:
    forwarded = request.headers.get("X-Forwarded-For", "").split(",", 1)[0].strip()
    return forwarded or request.remote_addr or ""


def _set_refresh_cookie(response, token: str) -> None:
    lifetime = current_app.config["JWT_REFRESH_TOKEN_EXPIRES"]
    response.set_cookie(
        current_app.config["REFRESH_COOKIE_NAME"],
        token,
        max_age=int(lifetime.total_seconds()),
        httponly=True,
        secure=bool(current_app.config["REFRESH_COOKIE_SECURE"]),
        samesite="Lax",
        path=f"{current_app.config['API_PREFIX']}/auth",
    )


def _clear_refresh_cookie(response) -> None:
    response.delete_cookie(
        current_app.config["REFRESH_COOKIE_NAME"],
        httponly=True,
        secure=bool(current_app.config["REFRESH_COOKIE_SECURE"]),
        samesite="Lax",
        path=f"{current_app.config['API_PREFIX']}/auth",
    )


def _new_refresh_session(user: User, *, family_id: str | None = None) -> tuple[RefreshSession, str]:
    raw_token = secrets.token_urlsafe(48)
    session = RefreshSession(
        user_id=user.id,
        token_hash=_token_hash(raw_token),
        family_id=family_id or generate_uuid(),
        expires_at=_utcnow() + current_app.config["JWT_REFRESH_TOKEN_EXPIRES"],
        user_agent=request.user_agent.string[:512],
        ip_address=_client_ip()[:64],
    )
    db.session.add(session)
    return session, raw_token


def _same_refresh_client(session: RefreshSession) -> bool:
    return secrets.compare_digest(
        session.user_agent, request.user_agent.string[:512]
    ) and secrets.compare_digest(
        session.ip_address,
        _client_ip()[:64],
    )


def _mark_rotated(
    session: RefreshSession,
    successor: RefreshSession,
    successor_token: str,
    now: datetime,
) -> None:
    session.revoked_at = now
    session.revocation_reason = "rotated"
    session.rotated_to_id = successor.id
    session.successor_token_encrypted = encrypt_secret(
        successor_token, current_app.config["ENCRYPTION_KEY"]
    )
    session.rotation_grace_expires_at = now + timedelta(
        seconds=max(0, int(current_app.config["REFRESH_ROTATION_GRACE_SECONDS"]))
    )


def _rotate_refresh_session(session: RefreshSession, user: User):
    now = _utcnow()
    successor, raw_token = _new_refresh_session(user, family_id=session.family_id)
    db.session.flush()
    _mark_rotated(session, successor, raw_token, now)
    db.session.commit()
    response = jsonify({"token": create_access_token(identity=user.id), "user": _serialize_user(user)})
    _set_refresh_cookie(response, raw_token)
    return response


def _revoke_refresh_family(family_id: str, reason: str) -> None:
    RefreshSession.query.filter_by(family_id=family_id, revoked_at=None).update(
        {
            RefreshSession.revoked_at: _utcnow(),
            RefreshSession.revocation_reason: reason,
        },
        synchronize_session=False,
    )
    RefreshSession.query.filter_by(family_id=family_id).update(
        {RefreshSession.successor_token_encrypted: ""},
        synchronize_session=False,
    )


def _auth_response(user: User, *, status: int = 200):
    _, refresh_token = _new_refresh_session(user)
    db.session.commit()
    response = jsonify({"token": create_access_token(identity=user.id), "user": _serialize_user(user)})
    _set_refresh_cookie(response, refresh_token)
    return response, status


def _trusted_cookie_request() -> bool:
    origin = _normalize_origin(request.headers.get("Origin", ""))
    if current_app.testing or not origin:
        return True

    configured_origins = {
        normalized
        for value in str(current_app.config["FRONTEND_URL"]).split(",")
        if (normalized := _normalize_origin(value))
    }
    forwarded_proto = request.headers.get("X-Forwarded-Proto", request.scheme).split(",", 1)[0].strip()
    forwarded_host = request.headers.get("X-Forwarded-Host", request.host).split(",", 1)[0].strip()
    current_origin = _normalize_origin(f"{forwarded_proto}://{forwarded_host}")
    trusted_origins = configured_origins | ({current_origin} if current_origin else set())
    return any(secrets.compare_digest(origin, expected) for expected in trusted_origins)


def _normalize_origin(value: str) -> str:
    try:
        parsed = urlsplit(value.strip().rstrip("/"))
        port = parsed.port
    except ValueError:
        return ""
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    hostname = (parsed.hostname or "").lower()
    if not hostname:
        return ""
    host = f"[{hostname}]" if ":" in hostname else hostname
    if port is not None and not (
        scheme == "http" and port == 80
    ) and not (
        scheme == "https" and port == 443
    ):
        host = f"{host}:{port}"
    return f"{scheme}://{host}"


@auth_bp.get("/captcha")
def captcha():
    response = jsonify(issue_login_captcha())
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, private"
    response.headers["Pragma"] = "no-cache"
    return response


@auth_bp.post("/register")
def register():
    if str(current_app.config.get("REGISTRATION_MODE", "disabled")).lower() != "open":
        return jsonify({"message": "registration is disabled"}), 403
    payload = CredentialSchema().load(request.get_json() or {})
    existing_user = User.query.filter_by(email=payload["username"]).first()
    if existing_user:
        return jsonify({"message": "username already registered"}), 409

    user = User(email=payload["username"], password_hash=generate_password_hash(payload["password"]))
    db.session.add(user)
    db.session.commit()
    ensure_default_model_profiles(user)

    return _auth_response(user, status=201)


@auth_bp.post("/login")
def login():
    payload = LoginSchema().load(request.get_json() or {})
    captcha_valid = consume_login_captcha(payload["captchaId"], payload["captchaCode"])
    if not captcha_valid:
        db.session.commit()
        return jsonify({"message": "验证码错误或已失效，请刷新后重试"}), 422

    user = User.query.filter_by(email=payload["username"]).first()
    if not user or not check_password_hash(user.password_hash, payload["password"]):
        db.session.commit()
        return jsonify({"message": "账号或密码错误"}), 401

    return _auth_response(user)


@auth_bp.post("/refresh")
def refresh_session():
    if not _trusted_cookie_request():
        return jsonify({"message": "untrusted origin"}), 403

    raw_token = request.cookies.get(current_app.config["REFRESH_COOKIE_NAME"], "")
    if not raw_token:
        return jsonify({"message": "refresh session is missing"}), 401

    session = db.session.execute(
        select(RefreshSession)
        .where(RefreshSession.token_hash == _token_hash(raw_token))
        .with_for_update()
    ).scalar_one_or_none()
    if session is None:
        response = jsonify({"message": "refresh session is invalid"})
        _clear_refresh_cookie(response)
        return response, 401

    if session.revoked_at is not None:
        within_rotation_grace = (
            session.revocation_reason == "rotated"
            and session.rotation_grace_expires_at is not None
            and _as_utc(session.rotation_grace_expires_at) > _utcnow()
            and _same_refresh_client(session)
        )
        if within_rotation_grace:
            successor = db.session.execute(
                select(RefreshSession)
                .where(
                    RefreshSession.id == session.rotated_to_id,
                    RefreshSession.family_id == session.family_id,
                )
                .with_for_update()
            ).scalar_one_or_none()
            user = db.session.get(User, session.user_id)
            if successor is not None and user is not None:
                response = jsonify(
                    {"token": create_access_token(identity=user.id), "user": _serialize_user(user)}
                )
                if successor.revoked_at is None and _as_utc(successor.expires_at) > _utcnow():
                    try:
                        successor_token = decrypt_secret(
                            session.successor_token_encrypted,
                            current_app.config["ENCRYPTION_KEY"],
                        )
                    except (InvalidTag, TypeError, ValueError):
                        successor_token = ""
                    if secrets.compare_digest(_token_hash(successor_token), successor.token_hash):
                        _set_refresh_cookie(response, successor_token)
                        db.session.rollback()
                        return response
                elif successor.revocation_reason == "rotated":
                    # Another legitimate refresh already advanced the shared browser cookie.
                    db.session.rollback()
                    return response

        _revoke_refresh_family(session.family_id, "reuse")
        db.session.commit()
        response = jsonify({"message": "refresh session reuse detected"})
        _clear_refresh_cookie(response)
        return response, 401

    if _as_utc(session.expires_at) <= _utcnow():
        session.revoked_at = _utcnow()
        session.revocation_reason = "expired"
        db.session.commit()
        response = jsonify({"message": "refresh session expired"})
        _clear_refresh_cookie(response)
        return response, 401

    user = db.session.get(User, session.user_id)
    if user is None:
        session.revoked_at = _utcnow()
        session.revocation_reason = "user_missing"
        db.session.commit()
        response = jsonify({"message": "user no longer exists"})
        _clear_refresh_cookie(response)
        return response, 401

    return _rotate_refresh_session(session, user)


@auth_bp.post("/logout")
def logout():
    if not _trusted_cookie_request():
        return jsonify({"message": "untrusted origin"}), 403
    raw_token = request.cookies.get(current_app.config["REFRESH_COOKIE_NAME"], "")
    if raw_token:
        session = RefreshSession.query.filter_by(token_hash=_token_hash(raw_token)).first()
        if session is not None and session.revoked_at is None:
            session.revoked_at = _utcnow()
            session.revocation_reason = "logout"
            db.session.commit()
    response = jsonify({"loggedOut": True})
    _clear_refresh_cookie(response)
    return response


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
