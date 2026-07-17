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


def test_refresh_cookie_rotates_and_logout_revokes_session(tmp_path: Path):
    class AuthConfig(TestConfig):
        STORAGE_ROOT = str(tmp_path)

    app = create_app(AuthConfig)
    client = app.test_client()
    login = client.post(
        "/api/v1/auth/login",
        json={"username": "dataset", "password": "Dataset123!"},
    )
    assert login.status_code == 200
    first_cookie = login.headers.get("Set-Cookie", "")
    assert "HttpOnly" in first_cookie
    assert "dataset_gen_refresh=" in first_cookie

    refreshed = client.post("/api/v1/auth/refresh")
    assert refreshed.status_code == 200
    assert refreshed.get_json()["token"] != login.get_json()["token"]
    assert refreshed.headers.get("Set-Cookie", "") != first_cookie

    logout = client.post("/api/v1/auth/logout")
    assert logout.status_code == 200
    assert client.post("/api/v1/auth/refresh").status_code == 401


def test_reusing_rotated_refresh_token_revokes_session_family(tmp_path: Path):
    class AuthConfig(TestConfig):
        STORAGE_ROOT = str(tmp_path)
        REFRESH_ROTATION_GRACE_SECONDS = 0

    app = create_app(AuthConfig)
    client = app.test_client()
    login = client.post(
        "/api/v1/auth/login",
        json={"username": "dataset", "password": "Dataset123!"},
    )
    old_token = login.headers["Set-Cookie"].split("dataset_gen_refresh=", 1)[1].split(";", 1)[0]
    rotated = client.post("/api/v1/auth/refresh")
    assert rotated.status_code == 200
    new_token = rotated.headers["Set-Cookie"].split("dataset_gen_refresh=", 1)[1].split(";", 1)[0]

    client.set_cookie("dataset_gen_refresh", old_token, path="/api/v1/auth")
    assert client.post("/api/v1/auth/refresh").status_code == 401
    client.set_cookie("dataset_gen_refresh", new_token, path="/api/v1/auth")
    assert client.post("/api/v1/auth/refresh").status_code == 401


def test_concurrent_refresh_rotation_advances_successor_without_revoking_family(tmp_path: Path):
    class AuthConfig(TestConfig):
        STORAGE_ROOT = str(tmp_path)
        REFRESH_ROTATION_GRACE_SECONDS = 10

    app = create_app(AuthConfig)
    client = app.test_client()
    login = client.post(
        "/api/v1/auth/login",
        json={"username": "dataset", "password": "Dataset123!"},
    )
    old_token = login.headers["Set-Cookie"].split("dataset_gen_refresh=", 1)[1].split(";", 1)[0]

    first_rotation = client.post("/api/v1/auth/refresh")
    assert first_rotation.status_code == 200
    successor_token = first_rotation.headers["Set-Cookie"].split(
        "dataset_gen_refresh=", 1
    )[1].split(";", 1)[0]
    client.set_cookie("dataset_gen_refresh", old_token, path="/api/v1/auth")
    concurrent_rotation = client.post("/api/v1/auth/refresh")

    assert concurrent_rotation.status_code == 200
    assert concurrent_rotation.get_json()["token"]
    assert successor_token in concurrent_rotation.headers["Set-Cookie"]
    assert client.post("/api/v1/auth/refresh").status_code == 200


def test_registration_can_be_disabled(tmp_path: Path):
    class AuthConfig(TestConfig):
        STORAGE_ROOT = str(tmp_path)
        REGISTRATION_MODE = "disabled"

    app = create_app(AuthConfig)
    response = app.test_client().post(
        "/api/v1/auth/register",
        json={"username": "closed", "password": "Dataset123!"},
    )
    assert response.status_code == 403


def test_dashboard_summary_uses_dataset_summary_helper(tmp_path: Path):
    class AuthConfig(TestConfig):
        STORAGE_ROOT = str(tmp_path)

    app = create_app(AuthConfig)
    client = app.test_client()

    register = client.post(
        "/api/v1/auth/register",
        json={"username": "dashboard_user", "password": "Dataset123!"},
    )
    token = register.get_json()["token"]

    response = client.get(
        "/api/v1/system/dashboard",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    summary = response.get_json()["summary"]
    assert summary["totalDatasets"] == 0
    assert summary["totalImages"] == 0
