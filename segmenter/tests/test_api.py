from io import BytesIO

from PIL import Image

from app import create_app


class FakeEngine:
    model_name = "test-sam"

    def create_session(self, image_bytes: bytes):
        assert image_bytes
        return "session-1", 32, 24, 600.0

    def predict(self, session_id: str, points: list[dict]):
        assert session_id == "session-1"
        assert points[0]["label"] == "positive"
        return {
            "bbox": [0.5, 0.5, 0.25, 0.5],
            "maskDataUrl": "data:image/png;base64,eA==",
            "maskScore": 0.91,
        }

    def delete_session(self, session_id: str):
        assert session_id == "session-1"


def _image_bytes() -> bytes:
    output = BytesIO()
    Image.new("RGB", (32, 24), "white").save(output, format="PNG")
    return output.getvalue()


def test_session_prediction_and_cleanup():
    app = create_app(engine=FakeEngine(), shared_token="secret")
    client = app.test_client()
    headers = {"Authorization": "Bearer secret"}

    created = client.post(
        "/v1/sessions",
        data={"image": (BytesIO(_image_bytes()), "sample.png")},
        headers=headers,
        content_type="multipart/form-data",
    )
    assert created.status_code == 201
    assert created.get_json()["sessionId"] == "session-1"

    predicted = client.post(
        "/v1/sessions/session-1/predict",
        json={"points": [{"x": 0.25, "y": 0.5, "label": "positive"}]},
        headers=headers,
    )
    assert predicted.status_code == 200
    assert predicted.get_json()["bbox"] == [0.5, 0.5, 0.25, 0.5]

    assert client.delete("/v1/sessions/session-1", headers=headers).status_code == 204


def test_requires_service_auth_and_valid_positive_points():
    app = create_app(engine=FakeEngine(), shared_token="secret")
    client = app.test_client()
    assert client.post("/v1/sessions").status_code == 401

    response = client.post(
        "/v1/sessions/session-1/predict",
        json={"points": [{"x": 0.25, "y": 0.5, "label": "negative"}]},
        headers={"Authorization": "Bearer secret"},
    )
    assert response.status_code == 422
    assert "positive" in response.get_json()["message"]
