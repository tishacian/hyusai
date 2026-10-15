"""Bounded retention runs on the ordinary maintenance queue, never on control."""

from app.core.config import settings
from app.db.base import SessionLocal
from app.workers.celery_app import celery_app


@celery_app.task(name="agentium.ml_prediction_retention", ignore_result=True)
def retain():
    if not settings.ml_retention_enabled:
        return {"deleted": 0, "enabled": False}
    from app.services.ml_governance import purge_predictions

    with SessionLocal() as db:
        return {"deleted": purge_predictions(db), "enabled": True}
