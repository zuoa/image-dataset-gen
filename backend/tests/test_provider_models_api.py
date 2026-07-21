from pathlib import Path

from app import create_app
from app.clients.gemini_client import GeminiGenerationError
from app.config import TestConfig
from app.services import provider_model_service


def _register(client, username: str) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/register",
        json={"username": username, "password": "Profiles123!"},
    )
    assert response.status_code == 201
    return {"Authorization": f"Bearer {response.get_json()['token']}"}


def _profiles(client, headers: dict[str, str]) -> list[dict]:
    response = client.get("/api/v1/system/model-profiles", headers=headers)
    assert response.status_code == 200
    return response.get_json()["profiles"]


def test_gemini_available_models_are_filtered_cached_and_refreshable(
    tmp_path: Path,
    monkeypatch,
):
    class ProviderModelsConfig(TestConfig):
        STORAGE_ROOT = str(tmp_path)
        GEMINI_API_KEY = "test-gemini-api-key"
        PROVIDER_MODEL_CACHE_TTL_SECONDS = 900

    app = create_app(ProviderModelsConfig)
    client = app.test_client()
    headers = _register(client, "provider-models-user")
    gemini_profile = next(
        profile for profile in _profiles(client, headers) if profile["providerId"] == "gemini"
    )
    calls: list[str] = []

    def fake_list_models(*, api_key: str, proxy_url: str = "") -> list[dict]:
        calls.append(api_key)
        assert proxy_url == ""
        return [
            {
                "name": "models/gemini-3.1-flash-image-preview",
                "supportedGenerationMethods": ["generateContent"],
            },
            {
                "name": "models/gemini-3.5-flash",
                "supportedGenerationMethods": ["generateContent"],
            },
            {
                "name": "models/imagen-4.0-generate-001",
                "supportedGenerationMethods": ["predict"],
            },
            {
                "name": "models/imagen-4.0-generate-001",
                "supportedGenerationMethods": ["predict"],
            },
        ]

    provider_model_service.clear_provider_model_cache()
    monkeypatch.setattr(provider_model_service, "list_gemini_models", fake_list_models)
    endpoint = f"/api/v1/system/model-profiles/{gemini_profile['id']}/available-models"

    live = client.get(endpoint, headers=headers)
    assert live.status_code == 200
    assert live.get_json()["source"] == "live"
    assert live.get_json()["models"] == [
        "gemini-3.1-flash-image-preview",
        "imagen-4.0-generate-001",
    ]
    assert live.get_json()["fetchedAt"]
    assert calls == ["test-gemini-api-key"]

    cached = client.get(endpoint, headers=headers)
    assert cached.status_code == 200
    assert cached.get_json()["source"] == "cache"
    assert calls == ["test-gemini-api-key"]

    refreshed = client.get(f"{endpoint}?refresh=1", headers=headers)
    assert refreshed.status_code == 200
    assert refreshed.get_json()["source"] == "live"
    assert calls == ["test-gemini-api-key", "test-gemini-api-key"]


def test_available_models_fall_back_without_supported_discovery(tmp_path: Path):
    class ProviderModelsConfig(TestConfig):
        STORAGE_ROOT = str(tmp_path)

    app = create_app(ProviderModelsConfig)
    client = app.test_client()
    headers = _register(client, "provider-fallback-user")
    profiles = _profiles(client, headers)
    jimeng_profile = next(profile for profile in profiles if profile["providerId"] == "jimeng")
    llm_profile = next(profile for profile in profiles if profile["profileType"] == "llm")

    fallback = client.get(
        f"/api/v1/system/model-profiles/{jimeng_profile['id']}/available-models",
        headers=headers,
    )
    assert fallback.status_code == 200
    assert fallback.get_json()["source"] == "catalog"
    assert fallback.get_json()["models"]
    assert "推理 API Key" in fallback.get_json()["warning"]

    rejected = client.get(
        f"/api/v1/system/model-profiles/{llm_profile['id']}/available-models",
        headers=headers,
    )
    assert rejected.status_code == 422


def test_gemini_discovery_error_returns_compatible_catalog(
    tmp_path: Path,
    monkeypatch,
):
    class ProviderModelsConfig(TestConfig):
        STORAGE_ROOT = str(tmp_path)
        GEMINI_API_KEY = "test-gemini-api-key"

    app = create_app(ProviderModelsConfig)
    client = app.test_client()
    headers = _register(client, "provider-error-user")
    gemini_profile = next(
        profile for profile in _profiles(client, headers) if profile["providerId"] == "gemini"
    )

    def fail_list_models(**_: str) -> list[dict]:
        raise GeminiGenerationError("gemini_models_http_403")

    provider_model_service.clear_provider_model_cache()
    monkeypatch.setattr(provider_model_service, "list_gemini_models", fail_list_models)
    response = client.get(
        f"/api/v1/system/model-profiles/{gemini_profile['id']}/available-models?refresh=true",
        headers=headers,
    )

    assert response.status_code == 200
    assert response.get_json()["source"] == "catalog"
    assert "gemini-3.1-flash-image-preview" in response.get_json()["models"]
    assert "API Key" in response.get_json()["warning"]
