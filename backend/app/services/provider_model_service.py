from __future__ import annotations

import hashlib
import threading
import time
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from flask import current_app

from app.clients.gemini_client import GeminiGenerationError, list_models as list_gemini_models
from app.services.provider_catalog import PROVIDER_CATALOG


_MODEL_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_MODEL_CACHE_LOCK = threading.Lock()
_MAX_CACHE_ENTRIES = 128


def list_available_image_models(
    *,
    provider_id: str,
    api_key: str,
    force_refresh: bool = False,
) -> dict[str, Any]:
    fallback_models = _catalog_models(provider_id)
    if provider_id != "gemini":
        return _fallback_result(
            provider_id,
            fallback_models,
            _provider_discovery_warning(provider_id),
        )

    if not api_key:
        return _fallback_result(
            provider_id,
            fallback_models,
            "请先保存有效的 Gemini API Key；当前显示内置兼容模型。",
        )

    cache_key = _cache_key(provider_id, api_key)
    if not force_refresh:
        cached = _get_cached_result(cache_key)
        if cached is not None:
            cached["source"] = "cache"
            return cached

    try:
        discovered = list_gemini_models(
            api_key=api_key,
            proxy_url=str(current_app.config.get("GEMINI_HTTP_PROXY", "") or ""),
        )
        models = _compatible_gemini_image_models(discovered)
        if not models:
            return _fallback_result(
                provider_id,
                fallback_models,
                "Gemini 返回了模型列表，但没有找到当前生成客户端兼容的图像模型。",
            )
    except GeminiGenerationError as exc:
        current_app.logger.warning("Unable to discover Gemini image models: %s", exc)
        return _fallback_result(
            provider_id,
            fallback_models,
            _gemini_error_warning(exc),
        )

    result = {
        "providerId": provider_id,
        "models": models,
        "source": "live",
        "fetchedAt": datetime.now(timezone.utc).isoformat(),
        "warning": None,
    }
    _store_cached_result(cache_key, result)
    return result


def clear_provider_model_cache() -> None:
    """Clear process-local discovery data. Primarily useful for tests."""
    with _MODEL_CACHE_LOCK:
        _MODEL_CACHE.clear()


def _compatible_gemini_image_models(models: list[dict[str, Any]]) -> list[str]:
    compatible: list[str] = []
    seen: set[str] = set()

    for model in models:
        raw_name = model.get("name")
        if not isinstance(raw_name, str):
            continue
        model_id = raw_name.removeprefix("models/").strip()
        methods = model.get("supportedGenerationMethods")
        supported_methods = (
            {method for method in methods if isinstance(method, str)}
            if isinstance(methods, list)
            else set()
        )
        is_imagen = model_id.startswith("imagen-") and "predict" in supported_methods
        is_native_image = (
            model_id.startswith("gemini-")
            and "-image" in model_id
            and "generateContent" in supported_methods
        )
        if not model_id or not (is_imagen or is_native_image) or model_id in seen:
            continue
        seen.add(model_id)
        compatible.append(model_id)

    return compatible


def _catalog_models(provider_id: str) -> list[str]:
    provider = next((item for item in PROVIDER_CATALOG if item["id"] == provider_id), None)
    if not provider:
        return []
    return [str(model) for model in provider.get("models", []) if str(model).strip()]


def _fallback_result(provider_id: str, models: list[str], warning: str) -> dict[str, Any]:
    return {
        "providerId": provider_id,
        "models": models,
        "source": "catalog",
        "fetchedAt": None,
        "warning": warning,
    }


def _provider_discovery_warning(provider_id: str) -> str:
    if provider_id == "jimeng":
        return "即梦推理 API Key 不能调用火山方舟管理接口；当前显示内置兼容模型。"
    if provider_id == "stability":
        return "Stability AI 生成适配器尚未实现，请手动填写模型 ID。"
    return "该服务商没有统一的模型发现接口，请手动填写模型 ID。"


def _gemini_error_warning(exc: GeminiGenerationError) -> str:
    message = str(exc)
    if "_401" in message or "_403" in message:
        return "Gemini 拒绝了模型列表请求，请检查 API Key 和项目权限；当前显示内置兼容模型。"
    if "network_error" in message:
        return "暂时无法连接 Gemini；当前显示内置兼容模型。"
    return "暂时无法读取 Gemini 模型列表；当前显示内置兼容模型。"


def _cache_key(provider_id: str, api_key: str) -> str:
    fingerprint = hashlib.sha256(api_key.encode("utf-8")).hexdigest()
    return f"{provider_id}:{fingerprint}"


def _get_cached_result(cache_key: str) -> dict[str, Any] | None:
    now = time.monotonic()
    with _MODEL_CACHE_LOCK:
        cached = _MODEL_CACHE.get(cache_key)
        if cached is None:
            return None
        expires_at, result = cached
        if expires_at <= now:
            _MODEL_CACHE.pop(cache_key, None)
            return None
        return deepcopy(result)


def _store_cached_result(cache_key: str, result: dict[str, Any]) -> None:
    ttl_seconds = max(
        0,
        int(current_app.config.get("PROVIDER_MODEL_CACHE_TTL_SECONDS", 900)),
    )
    if ttl_seconds == 0:
        return

    now = time.monotonic()
    with _MODEL_CACHE_LOCK:
        expired_keys = [key for key, (expires_at, _) in _MODEL_CACHE.items() if expires_at <= now]
        for key in expired_keys:
            _MODEL_CACHE.pop(key, None)
        if len(_MODEL_CACHE) >= _MAX_CACHE_ENTRIES:
            oldest_key = min(_MODEL_CACHE, key=lambda key: _MODEL_CACHE[key][0])
            _MODEL_CACHE.pop(oldest_key, None)
        _MODEL_CACHE[cache_key] = (now + ttl_seconds, deepcopy(result))
