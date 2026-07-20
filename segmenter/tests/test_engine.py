from collections import OrderedDict
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from PIL import Image

from app.engine import Sam2Engine, SegmenterError


def _engine_with_sessions(last_accessed_values: list[float], *, ttl: int = 10, maximum: int = 2):
    engine = Sam2Engine.__new__(Sam2Engine)
    engine._session_ttl_seconds = ttl
    engine._max_sessions = maximum
    engine._sessions = OrderedDict(
        (
            f"session-{index}",
            SimpleNamespace(last_accessed_at=last_accessed),
        )
        for index, last_accessed in enumerate(last_accessed_values)
    )
    return engine


def test_evicts_expired_sessions():
    engine = _engine_with_sessions([80.0, 95.0])
    with patch("app.engine.time.monotonic", return_value=100.0):
        engine._evict_expired_locked()
    assert list(engine._sessions) == ["session-1"]


def test_evicts_least_recently_used_sessions_over_capacity():
    engine = _engine_with_sessions([80.0, 90.0, 95.0])
    engine._evict_overflow_locked()
    assert list(engine._sessions) == ["session-1", "session-2"]


def test_rejects_excessive_pixel_count_before_decoding(monkeypatch):
    buffer = BytesIO()
    Image.new("RGB", (32, 24), "white").save(buffer, format="PNG")
    engine = Sam2Engine.__new__(Sam2Engine)
    monkeypatch.setenv("SEGMENTER_MAX_IMAGE_PIXELS", "100")

    with patch("app.engine.Image.Image.convert") as convert:
        with pytest.raises(SegmenterError, match="pixel limit"):
            engine.create_session(buffer.getvalue())

    convert.assert_not_called()
