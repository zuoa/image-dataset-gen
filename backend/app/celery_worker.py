from app import create_app
from app.extensions import celery

flask_app = create_app()

import app.worker_tasks  # noqa: F401 — register tasks with Celery

# Expose celery instance for worker CLI:
#   celery -A app.celery_worker worker --concurrency=1 --pool=solo --loglevel=info
