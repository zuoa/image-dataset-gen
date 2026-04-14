from pathlib import Path

from app import create_app
from app.config import TestConfig


def test_model_profiles_are_seeded_and_support_crud(tmp_path: Path):
    class ModelProfileConfig(TestConfig):
        STORAGE_ROOT = str(tmp_path)

    app = create_app(ModelProfileConfig)
    client = app.test_client()

    register = client.post(
        "/api/v1/auth/register",
        json={"email": "profiles@example.com", "password": "Profiles123!"},
    )
    token = register.get_json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    seeded = client.get("/api/v1/system/model-profiles", headers=headers)
    assert seeded.status_code == 200
    seeded_profiles = seeded.get_json()["profiles"]
    assert len(seeded_profiles) >= 4
    assert seeded_profiles[0]["apiKey"] == ""
    assert any(profile["profileType"] == "llm" for profile in seeded_profiles)

    created = client.post(
        "/api/v1/system/model-profiles",
        headers=headers,
        json={
            "profileType": "image",
            "name": "Custom Gemini Ultra",
            "providerId": "gemini",
            "baseUrl": "",
            "model": "imagen-4.0-ultra-generate-001",
            "apiKey": "super-secret-key",
            "concurrency": 2,
            "batchSize": 8,
            "jimengWatermark": True,
            "notes": "For premium exports",
        },
    )
    assert created.status_code == 201
    created_profile = created.get_json()["profile"]
    assert created_profile["name"] == "Custom Gemini Ultra"
    assert created_profile["apiKey"] == "super-secret-key"

    updated = client.patch(
        f"/api/v1/system/model-profiles/{created_profile['id']}",
        headers=headers,
        json={
            "profileType": "image",
            "name": "Custom Gemini Ultra Updated",
            "providerId": "jimeng",
            "baseUrl": "",
            "model": "doubao-seedream-5-0-260128",
            "apiKey": "another-secret",
            "concurrency": 5,
            "batchSize": 6,
            "jimengWatermark": False,
            "notes": "Switched to jimeng",
        },
    )
    assert updated.status_code == 200
    updated_profile = updated.get_json()["profile"]
    assert updated_profile["providerId"] == "jimeng"
    assert updated_profile["jimengWatermark"] is False
    assert updated_profile["apiKey"] == "another-secret"

    deleted = client.delete(
        f"/api/v1/system/model-profiles/{created_profile['id']}",
        headers=headers,
    )
    assert deleted.status_code == 200
    assert deleted.get_json()["deleted"] is True

    after_delete = client.get("/api/v1/system/model-profiles", headers=headers).get_json()["profiles"]
    assert all(profile["id"] != created_profile["id"] for profile in after_delete)

    llm_create = client.post(
        "/api/v1/system/model-profiles",
        headers=headers,
        json={
            "profileType": "llm",
            "name": "OpenAI Compatible Assistant",
            "providerId": "openai_compatible",
            "baseUrl": "https://llm.example.com/v1",
            "model": "custom-chat-model",
            "apiKey": "llm-secret-key",
            "concurrency": 1,
            "batchSize": 1,
            "jimengWatermark": False,
            "notes": "assist subject fields",
        },
    )
    assert llm_create.status_code == 201
    llm_profile = llm_create.get_json()["profile"]
    assert llm_profile["profileType"] == "llm"
    assert llm_profile["baseUrl"] == "https://llm.example.com/v1"
