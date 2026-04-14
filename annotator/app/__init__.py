from __future__ import annotations

from flask import Flask, jsonify, request

from app.service import annotate_payload


def create_app() -> Flask:
    app = Flask(__name__)

    @app.get("/health")
    def healthcheck():
        return jsonify({"status": "ok"})

    @app.post("/annotate")
    def annotate():
        payload = request.get_json() or {}
        return jsonify(annotate_payload(payload))

    return app
