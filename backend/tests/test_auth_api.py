from pathlib import Path

from app import create_app
from app.config import TestConfig


def test_default_demo_user_logs_in_with_username(tmp_path: Path):
    class AuthConfig(TestConfig):
        STORAGE_ROOT = str(tmp_path)

    app = create_app(AuthConfig)
    client = app.test_client()

    login = client.post(
        "/api/v1/auth/login",
        json={"username": "dataset", "password": "Dataset123!"},
    )

    assert login.status_code == 200
    payload = login.get_json()
    assert payload["user"]["username"] == "dataset"
    assert "email" not in payload["user"]

    me = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {payload['token']}"},
    )

    assert me.status_code == 200
    me_payload = me.get_json()["user"]
    assert me_payload["username"] == "dataset"
    assert me_payload["demoUsername"] == "dataset"


def test_register_accepts_plain_username(tmp_path: Path):
    class AuthConfig(TestConfig):
        STORAGE_ROOT = str(tmp_path)

    app = create_app(AuthConfig)
    client = app.test_client()

    register = client.post(
        "/api/v1/auth/register",
        json={"username": "dataset_ops", "password": "Dataset123!"},
    )

    assert register.status_code == 201
    payload = register.get_json()
    assert payload["user"]["username"] == "dataset_ops"
    assert "email" not in payload["user"]
