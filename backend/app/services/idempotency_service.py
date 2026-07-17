from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import hashlib
import json
from typing import Any

from flask import current_app, request
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import IdempotencyRecord
from app.services.dataset_service import now_utc


class IdempotencyError(RuntimeError):
    def __init__(self, message: str, status_code: int = 409) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class IdempotencyReplay:
    body: dict[str, Any]
    status_code: int


def begin_idempotent_request(
    user_id: str,
    scope: str,
    payload: dict[str, Any],
) -> tuple[IdempotencyRecord | None, IdempotencyReplay | None]:
    key = request.headers.get("Idempotency-Key", "").strip()
    if not key:
        return None, None
    if len(key) > 255:
        raise IdempotencyError("Idempotency-Key must not exceed 255 characters", 422)

    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    request_hash = hashlib.sha256(f"{scope}\n{canonical}".encode("utf-8")).hexdigest()
    existing = IdempotencyRecord.query.filter_by(
        user_id=user_id, scope=scope, idempotency_key=key
    ).first()
    if existing is not None:
        return _existing_result(existing, request_hash)

    record = IdempotencyRecord(
        user_id=user_id,
        scope=scope,
        idempotency_key=key,
        request_hash=request_hash,
        expires_at=now_utc() + timedelta(hours=int(current_app.config["IDEMPOTENCY_TTL_HOURS"])),
    )
    try:
        with db.session.begin_nested():
            db.session.add(record)
            db.session.flush()
    except IntegrityError:
        existing = IdempotencyRecord.query.filter_by(
            user_id=user_id, scope=scope, idempotency_key=key
        ).first()
        if existing is None:
            raise IdempotencyError("idempotency request is being claimed")
        return _existing_result(existing, request_hash)
    return record, None


def complete_idempotent_request(
    record: IdempotencyRecord | None,
    body: dict[str, Any],
    status_code: int,
) -> None:
    if record is None:
        return
    record.response_json = body
    record.response_status = status_code
    record.completed_at = now_utc()


def _existing_result(
    record: IdempotencyRecord, request_hash: str
) -> tuple[None, IdempotencyReplay | None]:
    if record.request_hash != request_hash:
        raise IdempotencyError("Idempotency-Key was already used with a different request")
    if record.completed_at is None:
        raise IdempotencyError("request with this Idempotency-Key is still in progress")
    return None, IdempotencyReplay(dict(record.response_json or {}), int(record.response_status))
