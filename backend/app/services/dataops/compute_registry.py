"""Dispatch lifecycle calls to the controller frozen at submission.

The existing task names and subprocess supervisor are retained. Admission, lease,
absolute deadline, cancellation and accounting stay with the original authority.
New O3 attempts use RecipeExecution; C0 attempts drain through ComputeRun.
"""

from __future__ import annotations

from datetime import UTC, timedelta

from sqlalchemy.orm import object_session

from app.core.config import settings
from app.models.compute_run import ACTIVE_STATUSES, TERMINAL_STATUSES, ComputeRun
from app.services import compute_runs as runs

KINDS = {"data_prep", "ml_stream_score", "sql_transform"}


def applicable(execution):
    return (
        execution.lifecycle_controller in {"recipe_v1", "compute_v1"}
        or (settings.connector_framework_enabled and (execution.input_json or {}).get("kind") in KINDS)
    )


def register(db, execution):
    from sqlalchemy import inspect

    from app.services.execution import recipe_lifecycle
    from app.services.execution.rollout import durable_for, enabled_for
    is_new = inspect(execution).pending
    if is_new and (execution.input_json or {}).get("kind") in KINDS:
        # The parent freezes an absolute deadline; queueing time must consume
        # that same budget. A child never receives a fresh, longer T0 window.
        if execution.run_id:
            from app.models.run import Run
            from app.services.execution.contracts import ExecutionPolicy
            parent = db.get(Run, execution.run_id)
            if parent is not None and parent.workspace_id == execution.workspace_id and parent.execution_policy:
                policy = ExecutionPolicy.model_validate(parent.execution_policy)
                if policy.deadline_at is not None:
                    deadline = policy.deadline_at.astimezone(UTC).replace(tzinfo=None)
                    execution.deadline_at = min(execution.deadline_at, deadline) if execution.deadline_at else deadline
                    remaining = max(1, int((deadline - runs.utcnow()).total_seconds()))
                    execution.timeout_s = min(execution.timeout_s or settings.dataops_sql_timeout_s, remaining)
        if enabled_for(db, execution.workspace_id, "execution_control_enabled"):
            recipe_lifecycle.register(db, execution)
        else:
            execution.lifecycle_controller = "compute_v1" if settings.connector_framework_enabled else "legacy"
        if durable_for(db, execution.workspace_id):
            from app.services.execution.dispatch import stage
            stage(db, "recipe_execution", execution, deadline_at=execution.deadline_at or (
                runs.utcnow() + timedelta(seconds=execution.timeout_s or settings.dataops_sql_timeout_s)))
    if execution.lifecycle_controller == recipe_lifecycle.CONTROLLER:
        return execution
    if execution.lifecycle_controller == "legacy":
        return None
    if not applicable(execution):
        return None
    db.flush()
    kind = "sql_transform" if execution.input_json["kind"] == "sql_transform" else "data_prep"
    now = execution.created_at or runs.utcnow()
    row = runs.create_run(
        db,
        workspace_id=execution.workspace_id,
        user_id=None,
        connection_id=None,
        operation=kind,
        kind=kind,
        recipe_execution_id=execution.id,
        run_id=execution.run_id,
        node_id=execution.node_id,
        cpu_cores=settings.dataops_duckdb_threads,
        deadline_at=execution.deadline_at or now + timedelta(seconds=execution.timeout_s or settings.dataops_sql_timeout_s),
    )
    row.memory_mb = settings.dataops_runner_memory_limit_mb
    row.fingerprint = execution.code_sha256
    return row


def start(db, execution):
    if execution.lifecycle_controller == "recipe_v1":
        from app.services.execution.recipe_lifecycle import start as native_start
        return native_start(db, execution)
    if execution.lifecycle_controller == "legacy":
        if execution.deadline_at and execution.deadline_at <= runs.utcnow():
            from app.services.recipe_executions import finalize_execution
            fail_outputs(db, execution)
            finalize_execution(execution, status="timed_out", error="EXECUTION_DEADLINE_EXCEEDED")
            db.commit()
            return False
        from app.services.execution.control import parent_cancelled
        if parent_cancelled(db, execution.run_id, execution.workspace_id):
            from app.services.recipe_executions import request_cancel
            request_cancel(db, execution)
            return False
        from app.models.execution_control import ExecutionDispatch
        if db.query(ExecutionDispatch.id).filter_by(entity_kind="recipe_execution", entity_id=execution.id).first():
            from app.models.recipe import RecipeExecution
            execution = db.query(RecipeExecution).filter_by(id=execution.id).with_for_update().populate_existing().one()
            return execution.status == "queued" and not execution.cancel_requested
        return True
    if not applicable(execution):
        return True
    if execution.status != "queued":
        return False
    try:
        row = register(db, execution)
        db.commit()
        token = runs.claim_run(db, row.id)
        if not token:
            db.refresh(row)
            if row.status in TERMINAL_STATUSES:
                execution.status = "failed" if row.status == "lost" else row.status
                execution.error, execution.finished_at = row.error_code, row.finished_at
                fail_outputs(db, execution)
                db.commit()
            return False
        execution._compute_lease_token = token
        if not runs.advance_run(db, row.id, token, "launching") or not runs.advance_run(
            db, row.id, token, "running"
        ):
            raise runs.ComputeRunError("COMPUTE_LEASE_LOST")
        # Legacy runners continue accepting relative timeouts, bounded now by
        # the same absolute deadline that included their queue delay.
        execution.timeout_s = max(0.01, (row.deadline_at - runs.utcnow()).total_seconds())
        return True
    except runs.ComputeRunError as exc:
        db.rollback()
        from app.services.recipe_executions import finalize_execution

        finalize_execution(execution, status="failed", error=exc.code)
        db.commit()
        return False


def poll(db, execution_id):
    from app.db.base import SessionLocal
    from app.models.recipe import RecipeExecution

    execution = db.get(RecipeExecution, execution_id)
    if execution and execution.lifecycle_controller == "recipe_v1":
        from app.services.execution.recipe_lifecycle import poll as native_poll
        return native_poll(db, execution_id)
    if not settings.connector_framework_enabled and (not execution or execution.lifecycle_controller != "compute_v1"):
        return False
    token = getattr(execution, "_compute_lease_token", None)
    # A heartbeat must be committed independently of dataset publication. Never
    # hold the compute row lock throughout the child runtime: cancellation and
    # the reaper must remain able to observe/update it.
    with db.no_autoflush:
        row = (
            db.query(ComputeRun)
            .filter_by(recipe_execution_id=execution_id)
            .populate_existing()
            .first()
        )
    if row is None:
        return False
    now = runs.utcnow()
    if (
        row.status not in ACTIVE_STATUSES
        or row.lease_token != token
        or row.cancel_requested
        or row.deadline_at <= now
        or not row.lease_expires_at
        or row.lease_expires_at <= now
    ):
        return True
    if getattr(execution, "_compute_settling", False) or db.new or db.dirty or db.deleted:
        # begin_settlement holds the lifecycle row lock through publication;
        # the absolute deadline replaces heartbeats in that transaction.
        return False
    with SessionLocal() as heartbeat_db:
        return not runs.heartbeat(heartbeat_db, row.id, token)


def begin_settlement(db, execution):
    """Fence publication before any pointer mutation, with one lock order.

    ComputeRun precedes RecipeExecution, as in the reaper. Once fenced, the
    transaction owns publication until the absolute deadline; a separate
    heartbeat could not renew a lease while this row is locked.
    """
    if execution.lifecycle_controller == "recipe_v1":
        from app.services.execution.recipe_lifecycle import begin_settlement as native_begin
        return native_begin(db, execution)
    if execution.lifecycle_controller == "legacy" or not applicable(execution):
        return
    with db.no_autoflush:
        row = (
            db.query(ComputeRun)
            .filter_by(recipe_execution_id=execution.id)
            .with_for_update()
            .populate_existing()
            .one_or_none()
        )
    now = runs.utcnow()
    if (
        row is None
        or row.status not in ACTIVE_STATUSES
        or row.lease_token != getattr(execution, "_compute_lease_token", None)
        or row.cancel_requested
        or row.deadline_at <= now
        or not row.lease_expires_at
        or row.lease_expires_at <= now
    ):
        raise runs.ComputeRunError("COMPUTE_LEASE_LOST")
    row.lease_expires_at = row.deadline_at
    row.status = "committing"
    db.flush()
    execution._compute_settling = True


def fail_outputs(db, execution):
    from app.models.tabular import TabularDataset

    spec = execution.input_json or {}
    identifiers = list((spec.get("outputs") or {}).values())
    if spec.get("output_id"):
        identifiers.append(spec["output_id"])
    if (execution.output_json or {}).get("dataset_id"):
        identifiers.append(execution.output_json["dataset_id"])
    for identifier in identifiers:
        dataset = db.get(TabularDataset, identifier)
        if (
            dataset
            and dataset.workspace_id == execution.workspace_id
            and dataset.status in {"ingesting", "ready"}
        ):
            dataset.status, dataset.error = "failed", execution.error or "COMPUTE_CANCELLED"


def finalize(execution):
    if execution.lifecycle_controller == "recipe_v1":
        from app.services.execution.recipe_lifecycle import finalize as native_finalize
        db = object_session(execution)
        if db is not None:
            return native_finalize(db, execution)
        return
    if execution.lifecycle_controller == "legacy":
        return
    if not applicable(execution):
        return
    db = object_session(execution)
    if db is None:
        return
    row = (
        db.query(ComputeRun)
        .filter_by(recipe_execution_id=execution.id)
        .with_for_update()
        .populate_existing()
        .first()
    )
    if row is None:
        return
    now = runs.utcnow()
    status = execution.status
    error = None if status == "succeeded" else "DATAOPS_EXECUTION_FAILED"
    if row.status in TERMINAL_STATUSES:
        status, error = row.status, row.error_code
    elif row.cancel_requested:
        status, error = "cancelled", "COMPUTE_CANCELLED"
    elif row.deadline_at <= now:
        status, error = "timed_out", "COMPUTE_TIMEOUT"
    elif row.status in ACTIVE_STATUSES and (
        not row.lease_expires_at or row.lease_expires_at <= now
    ):
        status, error = "lost", "COMPUTE_WORKER_LOST"
    elif (
        row.status in ACTIVE_STATUSES
        and getattr(execution, "_compute_lease_token", None) != row.lease_token
    ):
        # Refuse publication from a stale worker without overwriting the current
        # compute owner. Its local legacy projection must fail closed as well.
        execution.status, execution.error = "failed", "COMPUTE_LEASE_LOST"
        fail_outputs(db, execution)
        execution.output_json = None
        return
    if row.status not in TERMINAL_STATUSES:
        runs._finish(row, status, error, now, execution.output_json)
    if status != "succeeded":
        execution.status = "failed" if status == "lost" else status
        execution.error = execution.error or error
        fail_outputs(db, execution)
        execution.output_json = None
