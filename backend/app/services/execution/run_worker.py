"""Execute an identifier-only manual Run command with native deduplication."""

from datetime import datetime

from app.db.base import SessionLocal
from app.models.execution_control import ExecutionDispatch
from app.models.run import Run

from . import admission
from .contracts import ExecutionPolicy


def execute(run_id):
    from app.core.config import settings
    from app.services.run_engine.engine import schedule_run
    from app.services.run_engine.subflow_orchestration import postgres_coordination_lease

    if not settings.database_url.startswith("postgresql"):
        return {"id": run_id, "status": "unsupported_coordination_database"}
    with postgres_coordination_lease("execution-run", run_id) as acquired:
        if not acquired:
            return {"id": run_id, "status": "already_claimed"}
        with SessionLocal() as db:
            run = db.get(Run, run_id)
            if run is None:
                return {"id": run_id, "status": "missing"}
            run = db.query(Run).filter_by(id=run_id).with_for_update().populate_existing().one()
            intent = (
                db.query(ExecutionDispatch).filter_by(entity_kind="run", entity_id=run_id).first()
            )
            if run is None or intent is None or run.execution_policy is None:
                return {"id": run_id, "status": "invalid_dispatch"}
            if run.status in {
                "completed",
                "failed",
                "cancelled",
                "hitl_pending",
                "debug_pending",
                "waiting_subflows",
            }:
                return {"id": run_id, "status": run.status}
            policy = ExecutionPolicy.model_validate(run.execution_policy)
            if policy.engine != "legacy":
                return {"id": run_id, "status": "wrong_engine"}
            if run.status == "running":
                # Coordination lock is free but a previous owner started:
                # effects can be uncertain. Never replay the entire Flow.
                from .control import request_run_cancel

                request_run_cancel(db, run, commit=False)
                run.status, run.error = "failed", "EXECUTION_OUTCOME_REQUIRES_RECONCILIATION"
                run.completed_at = datetime.utcnow()
                from app.models.execution_control import ExecutionReservation

                allocation = (
                    db.query(ExecutionReservation)
                    .filter_by(entity_kind="run", entity_id=run.id)
                    .first()
                )
                if allocation:
                    admission.settle(
                        db,
                        entity_kind="run",
                        entity_id=run.id,
                        token=allocation.lease_token,
                        outcome="reconciliation_required",
                        process_stopped=False,
                    )
                db.commit()
                return {"id": run_id, "status": run.status}
            if policy.runtime_revision != settings.agentium_image_revision:
                run.status, run.error = "failed", "EXECUTION_VERSION_UNAVAILABLE"
                run.completed_at = datetime.utcnow()
                db.commit()
                return {"id": run_id, "status": run.status}
            if run.cancel_requested or policy.remaining_seconds() <= 0:
                run.status = "cancelled" if run.cancel_requested else "failed"
                run.error = (
                    "EXECUTION_CANCELLED" if run.cancel_requested else "EXECUTION_DEADLINE_EXCEEDED"
                )
                run.completed_at = datetime.utcnow()
                db.commit()
                return {"id": run_id, "status": run.status}
            # Orchestration does not occupy a compute admission slot while
            # waiting for its own Recipe/ML/connector child. Its concurrency is
            # still bounded by the legacy Flow worker queue; freeing that
            # waiting worker requires the qualified durable runtime.
            run.status = "running"
            db.commit()
        schedule_run(run_id)
        return {"id": run_id, "status": "scheduled"}


def reap(db, *, limit=100, now=None):
    """Expire abandoned legacy dispatches without replaying uncertain effects.

    A live owner receives a cooperative stop request. A released PostgreSQL
    coordination lease proves ownership loss, not that a remote effect stopped:
    reservations therefore remain occupied until an explicit acknowledgement.
    """
    from app.models.execution_control import ExecutionReservation
    from app.services.execution.control import request_run_cancel
    from app.services.run_engine.subflow_orchestration import postgres_coordination_lease

    now = now or datetime.utcnow()
    rows = (
        db.query(Run)
        .join(
            ExecutionDispatch,
            (ExecutionDispatch.entity_kind == "run") & (ExecutionDispatch.entity_id == Run.id),
        )
        .filter(
            ExecutionDispatch.task_name == "agentium.execution_run",
            Run.execution_policy.isnot(None),
            Run.status.in_(["pending", "running"]),
            ExecutionDispatch.deadline_at <= now,
        )
        .order_by(ExecutionDispatch.deadline_at, Run.id)
        .with_for_update(of=Run, skip_locked=True)
        .limit(limit)
        .all()
    )
    changed = 0
    for run in rows:
        if (run.execution_policy or {}).get("engine", "legacy") != "legacy":
            continue
        with postgres_coordination_lease("execution-run", run.id) as unowned:
            if not unowned and run.status == "running":
                request_run_cancel(db, run, commit=False)
            else:
                request_run_cancel(db, run, commit=False)
                run.status, run.error = (
                    "failed",
                    "EXECUTION_DEADLINE_EXCEEDED"
                    if run.status == "cancelled"
                    else "EXECUTION_OUTCOME_REQUIRES_RECONCILIATION",
                )
                run.completed_at = now
                allocation = (
                    db.query(ExecutionReservation)
                    .filter_by(entity_kind="run", entity_id=run.id)
                    .one_or_none()
                )
                if allocation is not None and allocation.released_at is None:
                    admission.settle(
                        db,
                        entity_kind="run",
                        entity_id=run.id,
                        token=allocation.lease_token,
                        outcome="reconciliation_required",
                        process_stopped=False,
                    )
            changed += 1
    return changed
