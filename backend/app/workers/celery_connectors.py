"""Connector worker scaffold. Business tasks arrive with the C1 runner.

Do not import the general worker's tasks: this image is not a consumer for
Flows, ML or DataOps. The two queues are served by separate OS processes.
"""

from celery import Celery
from kombu import Queue

from app.core.config import settings

celery_connectors = Celery(
    "agentium_connectors",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)
celery_connectors.conf.update(
    accept_content=["json"],
    result_serializer="json",
    task_serializer="json",
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_default_queue=settings.celery_connectors_queue,
    task_create_missing_queues=False,
    task_queues=(
        Queue(settings.celery_connectors_queue),
        Queue(settings.celery_connectors_interactive_queue),
    ),
    beat_schedule={},
)
