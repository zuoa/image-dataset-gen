from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
import hashlib
import hmac
from io import BytesIO
import secrets

from flask import current_app, request
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from sqlalchemy import select

from app.extensions import db
from app.models import LoginCaptcha, generate_uuid


CAPTCHA_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _random_code() -> str:
    length = max(4, min(8, int(current_app.config["LOGIN_CAPTCHA_LENGTH"])))
    return "".join(secrets.choice(CAPTCHA_ALPHABET) for _ in range(length))


def _request_ip() -> str:
    forwarded = request.headers.get("X-Forwarded-For", "").split(",", 1)[0].strip()
    return forwarded or request.remote_addr or ""


def _client_signature() -> str:
    client = f"{request.user_agent.string[:512]}\n{_request_ip()[:64]}"
    return hmac.new(
        str(current_app.config["SECRET_KEY"]).encode("utf-8"),
        client.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _answer_hash(captcha_id: str, code: str) -> str:
    normalized = code.strip().upper()
    return hmac.new(
        str(current_app.config["SECRET_KEY"]).encode("utf-8"),
        f"{captcha_id}:{normalized}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    try:
        return ImageFont.truetype("DejaVuSans-Bold.ttf", size)
    except OSError:
        return ImageFont.load_default(size=size)


def _render_captcha(code: str) -> str:
    width, height = 184, 58
    image = Image.new("RGB", (width, height), (248, 250, 252))
    draw = ImageDraw.Draw(image)

    for _ in range(7):
        color = (
            125 + secrets.randbelow(80),
            125 + secrets.randbelow(80),
            125 + secrets.randbelow(80),
        )
        points = [
            (secrets.randbelow(width), secrets.randbelow(height)),
            (secrets.randbelow(width), secrets.randbelow(height)),
            (secrets.randbelow(width), secrets.randbelow(height)),
        ]
        draw.line(points, fill=color, width=1 + secrets.randbelow(2), joint="curve")

    font = _load_font(34)
    slot_width = 30
    start_x = (width - slot_width * len(code)) // 2
    colors = ((30, 41, 59), (49, 46, 129), (12, 74, 110), (76, 29, 149))
    for index, character in enumerate(code):
        glyph = Image.new("RGBA", (44, 52), (255, 255, 255, 0))
        glyph_draw = ImageDraw.Draw(glyph)
        glyph_draw.text((7, 3), character, font=font, fill=secrets.choice(colors))
        angle = secrets.randbelow(25) - 12
        glyph = glyph.rotate(angle, resample=Image.Resampling.BICUBIC, expand=False)
        x = start_x + index * slot_width + secrets.randbelow(5) - 2
        y = 3 + secrets.randbelow(5)
        image.paste(glyph, (x, y), glyph)

    for _ in range(130):
        x, y = secrets.randbelow(width), secrets.randbelow(height)
        shade = 145 + secrets.randbelow(90)
        draw.point((x, y), fill=(shade, shade, shade))

    image = image.filter(ImageFilter.SMOOTH)
    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    encoded = base64.b64encode(output.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def issue_login_captcha() -> dict[str, object]:
    code = _random_code()
    expires_in = max(30, int(current_app.config["LOGIN_CAPTCHA_EXPIRES_SECONDS"]))
    captcha_id = generate_uuid()
    captcha = LoginCaptcha(
        id=captcha_id,
        answer_hash=_answer_hash(captcha_id, code),
        client_signature=_client_signature(),
        expires_at=_utcnow() + timedelta(seconds=expires_in),
    )
    db.session.add(captcha)
    db.session.commit()
    return {
        "captchaId": captcha.id,
        "image": _render_captcha(code),
        "expiresIn": expires_in,
    }


def consume_login_captcha(captcha_id: str, answer: str) -> bool:
    captcha_id = str(captcha_id)
    captcha = db.session.execute(
        select(LoginCaptcha).where(LoginCaptcha.id == captcha_id).with_for_update()
    ).scalar_one_or_none()
    if captcha is None or captcha.used_at is not None:
        return False

    now = _utcnow()
    captcha.used_at = now
    return (
        _as_utc(captcha.expires_at) > now
        and secrets.compare_digest(captcha.client_signature, _client_signature())
        and secrets.compare_digest(captcha.answer_hash, _answer_hash(captcha.id, answer))
    )
