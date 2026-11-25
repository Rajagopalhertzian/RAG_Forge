"""
ContextForge Celery App

Celery configuration for async task processing.
"""

from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from contextforge.config import settings

# Create Celery app
celery_app = Celery("contextforge")

# Configuration
celery_app.conf.update(
    broker_url=settings.CELERY_BROKER_URL,
    result_backend=settings.CELERY_RESULT_BACKEND,
    task_serializer=settings.CELERY_TASK_SERIALIZER,
    result_serializer=settings.CELERY_RESULT_SERIALIZER,
    accept_content=settings.CELERY_ACCEPT_CONTENT,
    timezone=settings.CELERY_TIMEZONE,
    enable_utc=True,
    task_track_started=settings.CELERY_TASK_TRACK_STARTED,
    task_time_limit=settings.CELERY_TASK_TIME_LIMIT,
    worker_prefetch_multiplier=settings.CELERY_WORKER_PREFETCH_MULTIPLIER,
    worker_max_tasks_per_child=settings.CELERY_WORKER_MAX_TASKS_PER_CHILD,
    result_expires=3600,
    task_routes={
        "contextforge.workers.tasks.ingest_document_task": {"queue": "ingestion"},
        "contextforge.workers.tasks.reindex_task": {"queue": "maintenance"},
        "contextforge.workers.tasks.cleanup_task": {"queue": "maintenance"},
    },
    task_default_queue="default",
    task_create_missing_queues=True,
    beat_schedule={
        "cleanup-old-jobs": {
            "task": "contextforge.workers.tasks.cleanup_old_jobs",
            "schedule": crontab(hour=2, minute=0),  # Daily at 2 AM
        },
        "reindex-stale": {
            "task": "contextforge.workers.tasks.reindex_stale_documents",
            "schedule": crontab(hour=3, minute=0),  # Daily at 3 AM
        },
    },
)

# Auto-discover tasks
celery_app.autodiscover_tasks(["contextforge.workers.tasks"])


@celery_app.task(bind=True, ignore_result=True)
def debug_task(self):
    """Debug task."""
    print(f"Request: {self.request!r}")
