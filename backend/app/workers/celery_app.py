"""Celery application for Agentium worker tasks."""
from __future__ import annotations

from celery import Celery

from app.core.config import settings


def configure(app: Celery) -> Celery:
    """The settings every Agentium Celery app shares (general and ML images)."""

    app.conf.update(
        accept_content=["json"],
        result_serializer="json",
        task_serializer="json",
        task_track_started=True,
        task_acks_late=True,
        worker_prefetch_multiplier=1,
        task_default_queue=settings.celery_task_default_queue,
    )
    return app


celery_app = configure(
    Celery(
        "agentium",
        broker=settings.celery_broker_url,
        backend=settings.celery_result_backend,
        include=["app.workers.tasks"],
    )
)


celery_app.conf.beat_schedule = {
    "refresh-macro-indicators-24h": {
        "task": "agentium.refresh_macro_indicators",
        "schedule": 24 * 60 * 60,
        "args": ("sentinel-ci", False),
    },
    # Orchestration Phase 3 — fire due ``run_schedules`` every minute.
    "scheduler-tick-60s": {
        "task": "agentium.scheduler_tick",
        "schedule": 60.0,
    },
    # Python recipe venv storage governor (TTL + LRU quota + pip cache cap).
    # The task itself no-ops unless recipe execution is enabled.
    "recipe-env-sweep-1h": {
        "task": "agentium.recipe_env_sweep",
        "schedule": 60 * 60,
    },
}
