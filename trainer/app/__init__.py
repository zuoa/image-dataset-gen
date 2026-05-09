from __future__ import annotations

from flask import Flask, jsonify


def create_app() -> Flask:
    app = Flask(__name__)

    @app.get("/health")
    def healthcheck():
        return jsonify({"status": "ok", "service": "trainer"})

    return app
