from __future__ import annotations

import logging
import shutil
import time
import uuid

from flask import Flask, Response, g, has_request_context, request
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from pythonjsonlogger.json import JsonFormatter


HTTP_REQUESTS = Counter(
    "dataset_gen_http_requests_total",
    "HTTP requests handled by the API",
    ("method", "route", "status"),
)
HTTP_LATENCY = Histogram(
    "dataset_gen_http_request_duration_seconds",
    "HTTP request latency",
    ("method", "route"),
)
OUTBOX_PENDING = Gauge("dataset_gen_outbox_pending", "Unpublished transactional outbox events")
ACTIVE_TRAINING_JOBS = Gauge(
    "dataset_gen_training_jobs_active", "Training jobs currently assigned or running"
)
STORAGE_FREE_BYTES = Gauge("dataset_gen_storage_free_bytes", "Free bytes in the storage filesystem")


class RequestContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = getattr(g, "request_id", "") if has_request_context() else ""
        record.http_method = request.method if has_request_context() else ""
        record.http_path = request.path if has_request_context() else ""
        return True


def configure_observability(app: Flask) -> None:
    formatter = JsonFormatter(
        "%(_timestamp)s %(levelname)s %(name)s %(message)s %(request_id)s %(http_method)s %(http_path)s",
        rename_fields={"_timestamp": "timestamp", "levelname": "level", "name": "logger"},
        timestamp=True,
    )
    context_filter = RequestContextFilter()
    for handler in app.logger.handlers:
        handler.setFormatter(formatter)
        handler.addFilter(context_filter)

    @app.before_request
    def start_request_observation() -> None:
        supplied = request.headers.get("X-Request-ID", "").strip()
        g.request_id = supplied[:128] if supplied else str(uuid.uuid4())
        g.request_started_at = time.perf_counter()

    @app.after_request
    def finish_request_observation(response):
        route = request.url_rule.rule if request.url_rule is not None else "unmatched"
        duration = max(0.0, time.perf_counter() - getattr(g, "request_started_at", time.perf_counter()))
        HTTP_REQUESTS.labels(request.method, route, str(response.status_code)).inc()
        HTTP_LATENCY.labels(request.method, route).observe(duration)
        response.headers["X-Request-ID"] = getattr(g, "request_id", "")
        app.logger.info(
            "request completed",
            extra={"status_code": response.status_code, "duration_ms": round(duration * 1000, 2)},
        )
        return response

    @app.get("/metrics")
    def metrics() -> Response:
        try:
            from app.models import OutboxEvent, TrainingJob

            OUTBOX_PENDING.set(OutboxEvent.query.filter(OutboxEvent.published_at.is_(None)).count())
            ACTIVE_TRAINING_JOBS.set(
                TrainingJob.query.filter(
                    TrainingJob.status.in_(["assigned", "preparing", "running", "uploading"])
                ).count()
            )
            STORAGE_FREE_BYTES.set(shutil.disk_usage(app.config["STORAGE_ROOT"]).free)
        except Exception:
            app.logger.exception("failed to collect application gauges")
        return Response(generate_latest(), mimetype=CONTENT_TYPE_LATEST)
