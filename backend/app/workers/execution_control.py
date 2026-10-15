"""Short control-plane worker. Never consumes Flow, ML or DataOps tasks.

Run a dedicated worker and beat with this app; it keeps cancellation, outbox
publication and expired leases moving even when every compute slot is busy.
"""

import logging

from celery import Celery
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.config import settings
from app.workers.celery_app import configure

logger = logging.getLogger(__name__)

app = configure(
    Celery(
        "agentium-control",
        broker=settings.celery_broker_url,
        backend=settings.celery_result_backend,
    )
)
app.conf.task_default_queue = settings.celery_control_queue
app.conf.broker_connection_timeout = 2
app.conf.broker_transport_options = {
    **app.conf.broker_transport_options,
    "connect_timeout": 2,
    "read_timeout": 2,
    "write_timeout": 2,
    "confirm_timeout": 2,
}
app.conf.task_routes = {"agentium.execution_control_tick": {"queue": settings.celery_control_queue}}
app.conf.beat_schedule = {
    "execution-control-1s": {
        "task": "agentium.execution_control_tick",
        "schedule": 1.0,
        "options": {"queue": settings.celery_control_queue, "expires": 5},
    }
}


def _reap_bounded(session_factory, controller, *, limit):
    """One controller's contended publication must not stall the other planes."""
    with session_factory() as db:
        postgres = db.get_bind().dialect.name == "postgresql"
        try:
            if postgres:
                db.execute(
                    text(
                        "SELECT set_config('lock_timeout', '250ms', true), set_config('statement_timeout', '1s', true)"
                    )
                )
            count = controller(db, limit=limit)
            db.commit()
            return count
        except DBAPIError as exc:
            db.rollback()
            code = getattr(exc.orig, "sqlstate", None) or getattr(exc.orig, "pgcode", None)
            if not postgres or code not in {"55P03", "57014"}:
                raise
            # No row is acknowledged after the rollback. The next tick rereads
            # native state; neither SQL text nor driver messages reach the log.
            logger.info("EXECUTION_REAPER_DEFERRED_CONTENTION")
            return 0


@app.task(name="agentium.execution_control_tick", ignore_result=True)
def tick():
    # Deployment of this dedicated worker is opt-in. Feature flags govern new
    # submissions/UI, never abandon already-persisted commands or leases.
    from app import models as registered_models  # noqa: F401 - install transactional source observation
    from app.db.base import SessionLocal
    from app.services.activity_observability.commands import process_commands
    from app.services.execution.dispatch import publish_due
    from app.services.execution.ml_lifecycle import reap as reap_training
    from app.services.execution.recipe_lifecycle import reap
    from app.services.execution.run_worker import reap as reap_flows

    with SessionLocal() as db:
        applied = process_commands(db, limit=20)
        db.commit()
    reaped = sum(
        _reap_bounded(SessionLocal, controller, limit=20)
        for controller in (reap, reap_training, reap_flows)
    )
    # No optional queue is created when this runtime has no active native work.
    # Existing work still gets reconciliation after admission is switched off.
    from app.models.execution_control import ExecutionDispatch
    from app.models.run import Run

    with SessionLocal() as db:
        temporal_pending = (
            db.query(Run.id)
            .join(
                ExecutionDispatch,
                (ExecutionDispatch.entity_kind == "run") & (ExecutionDispatch.entity_id == Run.id),
            )
            .filter(
                ExecutionDispatch.task_name == "agentium.execution_temporal_start",
                Run.status.in_(["pending", "running", "hitl_pending"]),
            )
            .first()
            is not None
        )
    if temporal_pending:
        try:
            app.send_task(
                "agentium.execution_temporal_reconcile",
                queue=settings.celery_orchestration_queue,
                expires=5,
                retry=False,
            )
        except Exception:
            pass  # The next tick re-derives this wakeup from durable native state.
    # Drains persisted intents even if admission is subsequently disabled.
    return {
        "commands": applied,
        "expired": reaped,
        "published": publish_due(SessionLocal, publisher=app.send_task, limit=20),
    }
