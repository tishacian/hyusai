"""Native RecipeExecution authority for new local DataOps attempts.

The controller is frozen on submission. Historical ComputeRun-backed attempts
drain under their original authority. Reservations coordinate resources only.
"""

from datetime import datetime, timedelta

from sqlalchemy import update

from app.core.config import settings
from app.models.recipe import RECIPE_EXECUTION_TERMINAL_STATUSES, RecipeExecution

from . import admission

CONTROLLER = "recipe_v1"


def register(db, row):
    row.lifecycle_controller = CONTROLLER
    db.flush()
    timeout_deadline = row.created_at + timedelta(
        seconds=row.timeout_s or settings.dataops_sql_timeout_s
    )
    row.deadline_at = (
        min(row.deadline_at, timeout_deadline) if row.deadline_at else timeout_deadline
    )
    return row


def start(db, row):
    """Claim with the caller's queued->running transaction, before any effect."""
    now = datetime.utcnow()
    try:
        admission.lock_scopes(db, row.workspace_id)
        from .control import parent_cancelled

        cancelled_parent = parent_cancelled(db, row.run_id, row.workspace_id)
        row = (
            db.query(RecipeExecution)
            .filter_by(id=row.id)
            .with_for_update()
            .populate_existing()
            .one()
        )
        if row.status != "queued":
            db.rollback()
            return False
        if cancelled_parent:
            row.cancel_requested = True
        if row.cancel_requested or not row.deadline_at or row.deadline_at <= now:
            row.status = "cancelled" if row.cancel_requested else "timed_out"
            row.finished_at, row.error = (
                now,
                "EXECUTION_CANCELLED" if row.cancel_requested else "EXECUTION_DEADLINE_EXCEEDED",
            )
            from app.services.dataops.compute_registry import fail_outputs

            fail_outputs(db, row)
            db.commit()
            return False
        allocation = admission.reserve(
            db,
            workspace_id=row.workspace_id,
            entity_kind="recipe_execution",
            entity_id=row.id,
            cpu_cores=settings.dataops_duckdb_threads,
            memory_mb=settings.dataops_runner_memory_limit_mb,
            deadline_at=row.deadline_at,
            now=now,
        )
        row.lease_token = allocation.lease_token
        row.lease_generation = (row.lease_generation or 0) + 1
        row.lease_expires_at = min(
            row.deadline_at, now + timedelta(seconds=settings.execution_lease_s)
        )
        row.timeout_s = max(0.01, (row.deadline_at - now).total_seconds())
        row._native_lease_token = row.lease_token
        db.flush()
        return True
    except admission.AdmissionError as exc:
        db.rollback()
        from .dispatch import defer_native

        defer_native(db, "recipe_execution", row.id, code=exc.code)
        db.commit()
        return False


def poll(db, identifier):
    row = db.get(RecipeExecution, identifier)
    token = getattr(row, "_native_lease_token", None)
    if getattr(row, "_native_settling", False):
        return row.cancel_requested or row.deadline_at <= datetime.utcnow()
    # Heartbeat is independent of the output publication transaction.
    from app.db.base import SessionLocal

    now = datetime.utcnow()
    with SessionLocal() as heartbeat_db:
        result = heartbeat_db.execute(
            update(RecipeExecution)
            .where(
                RecipeExecution.id == identifier,
                RecipeExecution.status == "running",
                RecipeExecution.lease_token == token,
                RecipeExecution.cancel_requested.is_(False),
                RecipeExecution.lease_expires_at > now,
                RecipeExecution.deadline_at > now,
            )
            .values(
                lease_expires_at=min(
                    row.deadline_at, now + timedelta(seconds=settings.execution_lease_s)
                )
            )
        )
        heartbeat_db.commit()
        return result.rowcount != 1


def begin_settlement(db, row):
    token = getattr(row, "_native_lease_token", None)
    with db.no_autoflush:
        row = (
            db.query(RecipeExecution)
            .filter_by(id=row.id)
            .with_for_update()
            .populate_existing()
            .one()
        )
    now = datetime.utcnow()
    if (
        row.status != "running"
        or not token
        or row.lease_token != token
        or row.cancel_requested
        or row.deadline_at <= now
        or not row.lease_expires_at
        or row.lease_expires_at <= now
    ):
        raise admission.AdmissionError("EXECUTION_LEASE_LOST")
    row.lease_expires_at = row.deadline_at
    row._native_settling = True
    db.flush()


def finalize(db, row):
    # Read authority without discarding the caller's pending terminal mutation.
    with db.no_autoflush:
        state = (
            db.execute(
                RecipeExecution.__table__.select()
                .where(RecipeExecution.id == row.id)
                .with_for_update()
            )
            .mappings()
            .one()
        )
    token = getattr(row, "_native_lease_token", None)
    now = datetime.utcnow()
    if state["lease_token"]:
        if state["lease_token"] != token:
            db.expire(row)
            raise admission.AdmissionError("EXECUTION_LEASE_LOST")
        if state["status"] in RECIPE_EXECUTION_TERMINAL_STATUSES:
            # A fenced worker can acknowledge physical stop after watchdog loss,
            # but can never publish a success over that terminal authority.
            row.status, row.error = state["status"], state["error"]
        elif state["cancel_requested"]:
            row.status, row.error = "cancelled", "EXECUTION_CANCELLED"
        elif state["deadline_at"] <= now:
            row.status, row.error = "timed_out", "EXECUTION_DEADLINE_EXCEEDED"
        elif state["lease_expires_at"] <= now:
            row.status, row.error = "failed", "EXECUTION_WORKER_LOST"
        admission.settle(
            db,
            entity_kind="recipe_execution",
            entity_id=row.id,
            token=token,
            outcome=row.status,
            now=now,
        )
    if row.status != "succeeded":
        from app.services.dataops.compute_registry import fail_outputs

        fail_outputs(db, row)
        row.output_json = None


def reap(db, *, limit=100):
    """Fence expired workers; keep uncertain capacity reserved for reconciliation."""
    now = datetime.utcnow()
    rows = (
        db.query(RecipeExecution)
        .filter(
            RecipeExecution.lifecycle_controller == CONTROLLER,
            RecipeExecution.status.in_(["queued", "running"]),
            (
                (RecipeExecution.deadline_at <= now)
                | (
                    (RecipeExecution.status == "running")
                    & (RecipeExecution.lease_expires_at <= now)
                )
            ),
        )
        .order_by(RecipeExecution.id)
        .with_for_update(skip_locked=True)
        .limit(limit)
        .all()
    )
    for row in rows:
        row.status = "timed_out" if row.deadline_at <= now else "failed"
        row.error = (
            "EXECUTION_DEADLINE_EXCEEDED" if row.deadline_at <= now else "EXECUTION_WORKER_LOST"
        )
        row.finished_at = now
        if row.lease_token:
            admission.settle(
                db,
                entity_kind="recipe_execution",
                entity_id=row.id,
                token=row.lease_token,
                outcome="reconciliation_required",
                now=now,
                process_stopped=False,
            )
        from app.services.dataops.compute_registry import fail_outputs

        fail_outputs(db, row)
    return len(rows)
