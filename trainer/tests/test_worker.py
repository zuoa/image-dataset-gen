from __future__ import annotations

import json
import urllib.request

from app.worker import _start_health_server


def test_health_server_returns_trainer_status() -> None:
    server = _start_health_server(0)
    port = server.server_address[1]
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=5) as response:
            assert response.status == 200
            assert response.headers["Content-Type"] == "application/json"
            assert json.loads(response.read().decode("utf-8")) == {
                "status": "ok",
                "service": "trainer",
            }
    finally:
        server.shutdown()
        server.server_close()
