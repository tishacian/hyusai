"""Celery application for Agentium worker tasks."""
from __future__ import annotations

from celery import Celery

from app.core.config import settings


celery_app = Celery(
    "agentium",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    accept_content=["json"],
    result_serializer="json",
    task_serializer="json",
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_default_queue=settings.celery_task_default_queue,
)


celery_app.conf.beat_schedule = {
    "refresh-macro-indicators-24h": {
        "task": "agentium.refresh_macro_indicators",
        "schedule": 24 * 60 * 60,
        "args": ("sentinel-ci", False),
    },
}
