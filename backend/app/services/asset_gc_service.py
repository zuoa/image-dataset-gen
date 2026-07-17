from __future__ import annotations

from datetime import timedelta

from app.extensions import db
from app.models import Asset, IdempotencyRecord, LoginCaptcha, RefreshSession
from app.services.dataset_service import now_utc
from app.services.storage_backend import local_backend


def garbage_collect_deleted_assets(storage_root: str, *, retention_hours: int = 24) -> int:
    cutoff = now_utc() - timedelta(hours=max(0, retention_hours))
    assets = (
        Asset.query.filter_by(storage_backend="local", status="deleted")
        .filter(Asset.deleted_at.is_not(None), Asset.deleted_at <= cutoff)
        .order_by(Asset.deleted_at.asc())
        .limit(1000)
        .all()
    )
    backend = local_backend(storage_root)
    for asset in assets:
        backend.delete(asset.storage_key)
        asset.status = "purged"
    db.session.commit()
    return len(assets)


def garbage_collect_expired_records() -> int:
    now = now_utc()
    RefreshSession.query.filter(
        RefreshSession.rotation_grace_expires_at.is_not(None),
        RefreshSession.rotation_grace_expires_at <= now,
        RefreshSession.successor_token_encrypted != "",
    ).update(
        {RefreshSession.successor_token_encrypted: ""},
        synchronize_session=False,
    )
    idempotency_deleted = IdempotencyRecord.query.filter(IdempotencyRecord.expires_at <= now).delete(
        synchronize_session=False
    )
    refresh_deleted = RefreshSession.query.filter(RefreshSession.expires_at <= now).delete(
        synchronize_session=False
    )
    captchas_deleted = LoginCaptcha.query.filter(LoginCaptcha.expires_at <= now).delete(
        synchronize_session=False
    )
    db.session.commit()
    return (
        int(idempotency_deleted or 0)
        + int(refresh_deleted or 0)
        + int(captchas_deleted or 0)
    )
