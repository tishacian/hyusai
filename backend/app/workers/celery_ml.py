"""Celery app for model-family images: the ML tasks and nothing else.

A family image (``ML_RUNTIME`` other than ``worker``) runs
``celery -A app.workers.celery_ml:celery_ml worker -Q <its queues>``. It shares
the general app's broker and settings but includes ``ml_tasks`` alone, so the
image never imports the RAG, OCR or capture planes — nor the libraries they
pull. Importing it also connects the heartbeat that makes the family's models
trainable in the catalog.
"""

from __future__ import annotations

from celery import Celery

from app.core.config import settings
from app.workers import ml_runtime_signals  # noqa: F401 - connects the heartbeat
from app.workers.celery_app import configure

celery_ml = configure(
    Celery(
        "agentium-ml",
        broker=settings.celery_broker_url,
        backend=settings.celery_result_backend,
        include=["app.workers.ml_tasks"],
    )
)
