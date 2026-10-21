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
        broker_transport_options={"confirm_publish": True},
        task_default_queue=settings.celery_task_default_queue,
    )
    return app


celery_app = configure(
    Celery(
        "agentium",
        broker=settings.celery_broker_url,
        backend=settings.celery_result_backend,
        include=[
            "app.workers.tasks",
            "app.workers.hf_datasets",
            "app.workers.ml_governance",
            "app.workers.ml_operations",
            "app.workers.mission_tasks",
        ],
    )
)

celery_app.conf.task_routes = {
    "agentium.dataops_sample_recovery": {"queue": settings.celery_task_default_queue},
    "agentium.dataops_build_sample": {"queue": settings.celery_dataops_queue},
    "agentium.hf_import": {"queue": "hub_fetch"},
    "agentium.hf_materialize_cache": {"queue": "hub_fetch"},
    "agentium.hf_cleanup_temporary": {"queue": "hub_fetch"},
    "agentium.hf_recover": {"queue": "hub_fetch"},
    "agentium.hf_purge_artifact": {"queue": "hub_fetch"},
    "agentium.hf_drain_revoked": {"queue": "hub_fetch"},
    "agentium.hf_bundle_import": {"queue": "hub_fetch"},
    "agentium.hf_bundle_export": {"queue": "hub_fetch"},
    "agentium.hf_dataset_materialize": {"queue": settings.celery_task_default_queue},
}


celery_app.conf.beat_schedule = {
    "mission-recovery-30s": {"task": "agentium.recover_missions", "schedule": 30.0},
    "ml-prediction-retention-hourly": {
        "task": "agentium.ml_prediction_retention",
        "schedule": 3600.0,
        "options": {"queue": settings.celery_task_default_queue},
    },
    "dataops-sample-recovery-60s": {
        "task": "agentium.dataops_sample_recovery",
        "schedule": 60.0,
        "options": {"queue": settings.celery_task_default_queue},
    },
    "hf-import-recovery-60s": {
        "task": "agentium.hf_recover",
        "schedule": 60.0,
        "options": {"queue": "hub_fetch"},
    },
    "ml-retraining-recovery-60s": {"task": "agentium.ml_retraining_recovery", "schedule": 60.0},
    "ml-shadow-recovery-30s": {
        "task": "agentium.ml_shadow_recover",
        "schedule": 30.0,
    },
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
    "public-retrieval-bench-24h": {
        "task": "agentium.public_retrieval_bench",
        "schedule": 24 * 60 * 60,
    },
}

# The general scheduler dispatches recovery to the short connector queue only
# when the optional execution plane is enabled. It never consumes that queue.
if settings.connector_framework_enabled:
    celery_app.conf.beat_schedule["connector-run-recovery-30s"] = {
        "task": "agentium.connector_reap",
        "schedule": 30.0,
        "options": {"queue": settings.celery_connectors_interactive_queue},
    }

if getattr(settings, "ml_operations_enabled", False) or getattr(
    settings, "ml_alerts_enabled", False
):
    celery_app.conf.beat_schedule["ml-operations-60s"] = {
        "task": "agentium.ml_operations_tick",
        "schedule": 60.0,
        "options": {"queue": settings.celery_task_default_queue, "expires": 60},
    }
