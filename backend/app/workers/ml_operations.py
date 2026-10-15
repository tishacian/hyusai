"""Small serving accounting batches and bounded network delivery on the IO lane.

Uses the existing general Celery worker/scheduler, never the latency-sensitive
execution control worker. PostgreSQL leases make duplicate wakeups harmless.
"""

from datetime import datetime, timedelta

from app.core.config import settings
from app.db.base import SessionLocal
from app.models.ml_operations import MLInferenceUsage
from app.services import ml_alerts, ml_operations
from app.workers.celery_app import celery_app


@celery_app.task(
    name="agentium.ml_operations_tick", ignore_result=True, soft_time_limit=150, time_limit=180
)
def tick():
    result = {"rolled_up": 0, "monitor_failures": 0, "keys": 0, "delivered": 0}
    if ml_operations.enabled():
        with SessionLocal() as db:
            result["rolled_up"] = ml_operations.rollup_usage(db)
            db.commit()
            # Raw accounting retains no prediction values. Delete only rows
            # whose counts have already been committed to durable aggregates.
            before = datetime.utcnow() - timedelta(
                days=int(getattr(settings, "ml_usage_retention_days", 30))
            )
            ids = (
                db.query(MLInferenceUsage.id)
                .filter(
                    MLInferenceUsage.rolled_up_at.isnot(None), MLInferenceUsage.created_at < before
                )
                .limit(10000)
                .all()
            )
            if ids:
                db.query(MLInferenceUsage).filter(
                    MLInferenceUsage.id.in_([row[0] for row in ids])
                ).delete(synchronize_session=False)
                db.commit()
    if ml_alerts.enabled():
        with SessionLocal() as db:
            result["monitor_failures"] = ml_alerts.scan_monitor_failures(db)
            result["keys"] = ml_alerts.scan_key_expiry(db)
            db.commit()
        result["delivered"] = ml_alerts.deliver_pending(SessionLocal)
    return result
