"""Torch-free acquisition worker: no general RAG/ML task registration."""

from celery import Celery

from app.core.config import settings
from app.workers.celery_app import configure

celery_hub = configure(
    Celery(
        "agentium-hub",
        broker=settings.celery_broker_url,
        backend=settings.celery_result_backend,
        include=["app.workers.hub_fetch"],
    )
)
celery_hub.conf.task_default_queue = "hub_fetch"
celery_hub.conf.task_routes = {
    "agentium.hf_dataset_materialize": {"queue": settings.celery_task_default_queue},
    "agentium.hf_bundle_dataset_import": {"queue": settings.celery_task_default_queue},
    "agentium.hf_bundle_dataset_export": {"queue": settings.celery_task_default_queue},
    "agentium.hf_*": {"queue": "hub_fetch"},
}
