from app import create_app
from app.extensions import celery

flask_app = create_app()

# Expose celery instance for worker CLI:
#   celery -A app.celery_worker worker --concurrency=1 --pool=solo --loglevel=info
