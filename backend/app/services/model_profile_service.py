from __future__ import annotations

from typing import Any

from flask import current_app

from app.extensions import db
from app.models import ModelProfile, User
from app.utils.crypto import decrypt_secret, encrypt_secret


DEFAULT_MODEL_PROFILES = [
    {
        "profile_type": "image",
        "name": "Nano Banana 2 · 通用写实",
        "provider_id": "gemini",
        "base_url": None,
        "model": "gemini-3.1-flash-image-preview",
        "api_key": "",
        "concurrency": 3,
        "batch_size": 10,
        "jimeng_watermark": True,
        "notes": "通用默认配置，适合大多数写实数据集任务。",
    },
    {
        "profile_type": "image",
        "name": "Nano Banana · 高吞吐",
        "provider_id": "gemini",
        "base_url": None,
        "model": "gemini-2.5-flash-image",
        "api_key": "",
        "concurrency": 4,
        "batch_size": 12,
        "jimeng_watermark": True,
        "notes": "适合快速试跑和小规模验证。",
    },
    {
        "profile_type": "image",
        "name": "即梦 AI · 中文生产",
        "provider_id": "jimeng",
        "base_url": None,
        "model": "doubao-seedream-3-0-t2i-250415",
        "api_key": "",
        "concurrency": 5,
        "batch_size": 10,
        "jimeng_watermark": True,
        "notes": "适合中文描述任务，固定输出 JPG。",
    },
    {
        "profile_type": "llm",
        "name": "DeepSeek · 自动补全",
        "provider_id": "openai_compatible",
        "base_url": None,
        "model": "",
        "api_key": "",
        "concurrency": 1,
        "batch_size": 1,
        "jimeng_watermark": False,
        "notes": "用于根据目标对象自动补全类别标签和补充描述。",
    },
]

LEGACY_DEFAULT_PROFILE_UPDATES = {
    "Gemini Imagen · 通用写实": {
        "name": "Nano Banana 2 · 通用写实",
        "model": "gemini-3.1-flash-image-preview",
        "notes": "通用默认配置，适合大多数写实数据集任务。",
    },
    "Gemini Imagen · 快速预览": {
        "name": "Nano Banana · 高吞吐",
        "model": "gemini-2.5-flash-image",
        "notes": "适合快速试跑和小规模验证。",
    },
    "OpenAI-Compatible · 自动补全": {
        "name": "DeepSeek · 自动补全",
        "model": "deepseek-chat",
        "notes": "默认使用 DeepSeek 的 OpenAI-compatible 接口，根据目标对象自动补全类别标签和补充描述。",
    },
}

DEFAULT_PROFILE_NAMES = {template["name"] for template in DEFAULT_MODEL_PROFILES} | set(
    LEGACY_DEFAULT_PROFILE_UPDATES.keys()
)


def _default_api_key_for_profile(profile_type: str, provider_id: str) -> str:
    if profile_type == "image" and provider_id == "gemini":
        return str(current_app.config.get("GEMINI_API_KEY", "") or "")
    if profile_type == "llm" and provider_id == "openai_compatible":
        return str(current_app.config.get("OPENAI_COMPAT_API_KEY", "") or "")
    return ""


def _resolved_profile_api_key(profile: ModelProfile) -> str:
    try:
        stored_api_key = decrypt_secret(profile.api_key_encrypted, current_app.config["ENCRYPTION_KEY"])
    except Exception:
        stored_api_key = ""
    return stored_api_key or _default_api_key_for_profile(profile.profile_type, profile.provider_id)


def build_model_profile_payload(profile: ModelProfile) -> dict[str, Any]:
    return {
        "id": profile.id,
        "profileType": profile.profile_type,
        "name": profile.name,
        "providerId": profile.provider_id,
        "baseUrl": profile.base_url,
        "model": profile.model,
        "apiKey": _resolved_profile_api_key(profile),
        "concurrency": profile.concurrency,
        "batchSize": profile.batch_size,
        "jimengWatermark": profile.jimeng_watermark,
        "notes": profile.notes or "",
        "createdAt": profile.created_at.isoformat() if profile.created_at else None,
        "updatedAt": profile.updated_at.isoformat() if profile.updated_at else None,
    }


def create_model_profile(user_id: str, payload: dict[str, Any]) -> ModelProfile:
    api_key = str(payload.get("api_key") or "") or _default_api_key_for_profile(
        payload["profile_type"], payload["provider_id"]
    )
    profile = ModelProfile(
        user_id=user_id,
        profile_type=payload["profile_type"],
        name=payload["name"],
        provider_id=payload["provider_id"],
        base_url=payload.get("base_url"),
        model=payload["model"],
        api_key_encrypted=encrypt_secret(api_key, current_app.config["ENCRYPTION_KEY"]),
        concurrency=payload["concurrency"],
        batch_size=payload["batch_size"],
        jimeng_watermark=payload["jimeng_watermark"],
        notes=payload.get("notes", ""),
    )
    db.session.add(profile)
    return profile


def ensure_default_model_profiles(user: User) -> None:
    if user.model_profiles:
        changed = False
        has_llm_profile = any(profile.profile_type == "llm" for profile in user.model_profiles)
        for profile in user.model_profiles:
            legacy_update = LEGACY_DEFAULT_PROFILE_UPDATES.get(profile.name)
            if profile.name in DEFAULT_PROFILE_NAMES:
                current_api_key = _resolved_profile_api_key(profile)
                env_api_key = _default_api_key_for_profile(profile.profile_type, profile.provider_id)
                if current_api_key == "demo-api-key":
                    profile.api_key_encrypted = encrypt_secret(
                        "", current_app.config["ENCRYPTION_KEY"]
                    )
                    changed = True
                elif env_api_key and env_api_key != current_api_key:
                    profile.api_key_encrypted = encrypt_secret(
                        env_api_key, current_app.config["ENCRYPTION_KEY"]
                    )
                    changed = True

                # Sync default models / base_url from environment variables
                if profile.profile_type == "image":
                    expected_model = None
                    if profile.provider_id == "gemini":
                        if profile.name in ("Nano Banana 2 · 通用写实", "Gemini Imagen · 通用写实"):
                            expected_model = "gemini-3.1-flash-image-preview"
                        elif profile.name in ("Nano Banana · 高吞吐", "Gemini Imagen · 快速预览"):
                            expected_model = "gemini-2.5-flash-image"
                    elif profile.provider_id == "jimeng" and profile.name == "即梦 AI · 中文生产":
                        expected_model = "doubao-seedream-3-0-t2i-250415"
                    if expected_model and profile.model != expected_model:
                        profile.model = expected_model
                        changed = True

                if profile.profile_type == "llm" and profile.provider_id == "openai_compatible":
                    expected_model = current_app.config["OPENAI_COMPAT_MODEL"]
                    expected_base_url = current_app.config["OPENAI_COMPAT_BASE_URL"]
                    if profile.model != expected_model:
                        profile.model = expected_model
                        changed = True
                    if profile.base_url != expected_base_url:
                        profile.base_url = expected_base_url
                        changed = True

            if not legacy_update:
                continue
            if profile.profile_type == "image" and profile.provider_id == "gemini":
                profile.name = legacy_update["name"]
                profile.model = legacy_update["model"]
                profile.notes = legacy_update["notes"]
                changed = True
            if profile.profile_type == "llm" and profile.provider_id == "openai_compatible":
                profile.name = legacy_update["name"]
                profile.model = current_app.config["OPENAI_COMPAT_MODEL"]
                profile.base_url = current_app.config["OPENAI_COMPAT_BASE_URL"]
                profile.notes = legacy_update["notes"]
                changed = True
        if not has_llm_profile:
            llm_defaults = [template for template in DEFAULT_MODEL_PROFILES if template["profile_type"] == "llm"]
            for template in llm_defaults:
                payload = dict(template)
                payload["base_url"] = current_app.config["OPENAI_COMPAT_BASE_URL"]
                payload["model"] = current_app.config["OPENAI_COMPAT_MODEL"]
                create_model_profile(user.id, payload)
                changed = True
        if changed:
            db.session.commit()
        return

    for template in DEFAULT_MODEL_PROFILES:
        payload = dict(template)
        if payload["profile_type"] == "llm":
            payload["base_url"] = current_app.config["OPENAI_COMPAT_BASE_URL"]
            payload["model"] = current_app.config["OPENAI_COMPAT_MODEL"]
        create_model_profile(user.id, payload)
    db.session.commit()
