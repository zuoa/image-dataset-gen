from unittest.mock import patch

import pytest
import requests

from app.clients.segmenter_client import (
    SegmenterClientError,
    SegmenterSessionExpiredError,
    SegmenterTimeoutError,
    SegmenterUnavailableError,
    predict_segmenter_session,
)


def _predict():
    return predict_segmenter_session(
        base_url="http://segmenter:8100",
        shared_token="test-token",
        session_id="session-1",
        points=[{"x": 0.5, "y": 0.5, "label": "positive"}],
        connect_timeout=2,
        read_timeout=15,
    )


def _response(status_code: int, content: bytes) -> requests.Response:
    response = requests.Response()
    response.status_code = status_code
    response._content = content
    response.headers["Content-Type"] = "application/json"
    return response


def test_predict_maps_timeout_and_connection_errors():
    with patch("app.clients.segmenter_client.requests.request", side_effect=requests.Timeout):
        with pytest.raises(SegmenterTimeoutError) as timeout_error:
            _predict()
    assert timeout_error.value.status_code == 504

    with patch("app.clients.segmenter_client.requests.request", side_effect=requests.ConnectionError):
        with pytest.raises(SegmenterUnavailableError) as unavailable_error:
            _predict()
    assert unavailable_error.value.status_code == 503


def test_predict_maps_expired_session_and_invalid_payload():
    with patch(
        "app.clients.segmenter_client.requests.request",
        return_value=_response(404, b'{"message":"not found"}'),
    ):
        with pytest.raises(SegmenterSessionExpiredError) as expired_error:
            _predict()
    assert expired_error.value.status_code == 410

    with patch(
        "app.clients.segmenter_client.requests.request",
        return_value=_response(200, b"[]"),
    ):
        with pytest.raises(SegmenterClientError):
            _predict()
