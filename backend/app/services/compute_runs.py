"""Durable local admission and fenced lifecycle shared by execution planes.

No credentials belong in this registry or its Celery messages. A lease is never
reclaimed to replay a launched operation: uncertain writes require reconciliation.
"""

from __future__ import annotations

import json
import math
import re
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import func, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.compute_run import ACTIVE_STATUSES, TERMINAL_STATUSES, ComputeRun
from app.models.workspace import Workspace

INTERACTIVE = frozenset({"test", "catalog", "table", "preview"})
OPERATIONS = INTERACTIVE | {
    "import",
    "export",
    "write_append",
    "write_overwrite",
    "write_upsert",
    "watch",
    "sql_transform",
    "data_prep",
    "reconcile_write",
    "tool_write",
    "write_preview",
}
WRITES = frozenset({"tool_write", "export", "write_append", "write_overwrite", "write_upsert"})
TASK_NAME = "agentium.connector_execute"


class ComputeRunError(RuntimeError):
    def __init__(self, code: str, status_code: int = 400):
        self.code, self.status_code = code, status_code
        super().__init__(code)


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _utc(value: datetime) -> datetime:
    return value.astimezone(UTC).replace(tzinfo=None) if value.tzinfo else value


def _lock_workspace(db: Session, workspace_id: str) -> Workspace:
    # A no-op UPDATE also serializes admissions on SQLite, where FOR UPDATE is
    # ignored. On PostgreSQL this obtains the same per-workspace row lock.
    updated = db.execute(
        update(Workspace).where(Workspace.id == workspace_id).values(settings=Workspace.settings)
    )
    if updated.rowcount != 1:
        raise ComputeRunError("CONNECTOR_WORKSPACE_NOT_FOUND", 404)
    return db.query(Workspace).filter_by(id=workspace_id).populate_existing().one()


def _limit(workspace: Workspace, name: str, default: float) -> float:
    operator = float(getattr(settings, f"connector_{name}", default))
    # Tenant policy can reduce an operator ceiling, never raise it.
    policy = (workspace.settings or {}).get("dataops", {})
    value = policy.get(name, operator) if isinstance(policy, dict) else operator
    if (
        isinstance(value, bool)
        or not isinstance(value, (float, int))
        or not math.isfinite(value)
        or value <= 0
    ):
        raise ComputeRunError("CONNECTOR_QUOTA_POLICY_INVALID", 503)
    return min(float(value), operator)


def _public_parameters(value: dict | None) -> dict:
    value = value or {}
    if not isinstance(value, dict):
        raise ComputeRunError("CONNECTOR_PARAMETERS_INVALID")

    def inspect(item):
        if isinstance(item, dict):
            for key, nested in item.items():
                if not isinstance(key, str) or (
                    re.search(r"password|secret|credential|authorization|token", key, re.I)
                    and not (key in {"token_start", "token_end"} and type(nested) is int)
                ):
                    raise ComputeRunError("CONNECTOR_SECRET_PARAMETER_FORBIDDEN")
                inspect(nested)
        elif isinstance(item, (list, tuple)):
            for nested in item:
                inspect(nested)

    inspect(value)
    try:
        encoded = json.dumps(value, allow_nan=False)
    except (ValueError, TypeError):
        raise ComputeRunError("CONNECTOR_PARAMETERS_INVALID") from None
    if len(encoded.encode()) > 65536:
        raise ComputeRunError("CONNECTOR_PARAMETERS_TOO_LARGE")
    return json.loads(encoded)


def create_run(
    db: Session,
    *,
    workspace_id: str,
    user_id: str | None,
    connection_id: str | None,
    operation: str,
    parameters: dict | None = None,
    deadline_at: datetime | None = None,
    system_id: str | None = None,
    system_version_id: str | None = None,
    delegation_id: str | None = None,
    run_id: str | None = None,
    node_id: str | None = None,
    kind: str = "connector_read",
    cpu_cores: float = 1.0,
    recipe_execution_id: str | None = None,
) -> ComputeRun:
    if operation not in OPERATIONS or kind not in {
        "connector_read",
        "connector_write",
        "data_prep",
        "sql_transform",
    }:
        raise ComputeRunError("CONNECTOR_OPERATION_UNSUPPORTED")
    if operation in WRITES:
        kind = "connector_write"
    if (
        isinstance(cpu_cores, bool)
        or not isinstance(cpu_cores, (int, float))
        or not math.isfinite(cpu_cores)
        or not 0 < cpu_cores <= (64 if kind in {"data_prep", "sql_transform"} else 2)
    ):
        raise ComputeRunError("CONNECTOR_RESOURCE_INVALID")
    public_parameters = _public_parameters(parameters)
    workspace = _lock_workspace(db, workspace_id)
    now = utcnow()
    timeout = _limit(
        workspace,
        "interactive_timeout_s" if operation in INTERACTIVE else "max_timeout_s",
        30 if operation in INTERACTIVE else 3600,
    )
    deadline = (
        min(_utc(deadline_at), now + timedelta(seconds=timeout))
        if deadline_at
        else now + timedelta(seconds=timeout)
    )
    if deadline <= now:
        raise ComputeRunError("CONNECTOR_BUSY", 429)
    existing = (
        db.query(ComputeRun).filter_by(recipe_execution_id=recipe_execution_id).first()
        if recipe_execution_id
        else None
    )
    if existing:
        if existing.workspace_id != workspace_id:
            raise ComputeRunError("CONNECTOR_RUN_NOT_FOUND", 404)
        return existing
    pending = (
        db.query(func.count(ComputeRun.id))
        .filter(
            ComputeRun.workspace_id == workspace_id, ComputeRun.status.notin_(TERMINAL_STATUSES)
        )
        .scalar()
    )
    if pending >= _limit(workspace, "max_pending_runs", 100):
        raise ComputeRunError("CONNECTOR_QUOTA_EXCEEDED", 429)
    reserved = cpu_cores * (deadline - now).total_seconds() / 3600
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    used = (
        db.query(func.coalesce(func.sum(ComputeRun.core_hours), 0))
        .filter(ComputeRun.workspace_id == workspace_id, ComputeRun.finished_at >= day)
        .scalar()
    )
    committed = (
        db.query(func.coalesce(func.sum(ComputeRun.reserved_core_hours), 0))
        .filter(
            ComputeRun.workspace_id == workspace_id, ComputeRun.status.notin_(TERMINAL_STATUSES)
        )
        .scalar()
    )
    if float(used) + float(committed) + reserved > _limit(workspace, "max_core_hours_per_day", 24):
        raise ComputeRunError("CONNECTOR_QUOTA_EXCEEDED", 429)
    revision = profile_key = None
    if connection_id:
        from app.services.connectors.connections import get_connection

        connection = get_connection(db, workspace_id, connection_id)
        revision, profile_key = connection.revision, connection.profile_key
    elif kind.startswith("connector_"):
        raise ComputeRunError("CONNECTOR_CONNECTION_REQUIRED")
    row = ComputeRun(
        id=str(uuid4()),
        workspace_id=workspace_id,
        user_id=user_id,
        connection_id=connection_id,
        connection_revision=revision,
        profile=profile_key,
        operation=operation,
        kind=kind,
        input_json=public_parameters,
        deadline_at=deadline,
        cpu_cores=cpu_cores,
        reserved_core_hours=reserved,
        memory_mb=int(getattr(settings, "connector_runner_memory_mb", 1024)),
        system_id=system_id,
        system_version_id=system_version_id,
        delegation_id=delegation_id,
        run_id=run_id,
        node_id=node_id,
        recipe_execution_id=recipe_execution_id,
        created_at=now,
    )
    db.add(row)
    db.flush()
    from app.services.execution.rollout import durable_for, enabled_for
    if enabled_for(db, workspace_id, "execution_control_enabled"):
        row.metrics_json = {**(row.metrics_json or {}), "coordination_version": 1}
    if durable_for(db, workspace_id) and not recipe_execution_id:
        from app.services.execution.dispatch import stage
        stage(db, "compute_run", row, deadline_at=row.deadline_at)
    return row


def get_run(db: Session, workspace_id: str, run_id: str) -> ComputeRun:
    row = (
        db.query(ComputeRun)
        .filter_by(id=run_id, workspace_id=workspace_id)
        .populate_existing()
        .first()
    )
    if row is None:
        raise ComputeRunError("CONNECTOR_RUN_NOT_FOUND", 404)
    now = utcnow()
    if row.status not in TERMINAL_STATUSES and (
        row.deadline_at <= now or (row.lease_expires_at and row.lease_expires_at <= now)
    ):
        row = (
            db.query(ComputeRun)
            .filter_by(id=run_id, workspace_id=workspace_id)
            .with_for_update()
            .populate_existing()
            .one()
        )
        if row.status not in TERMINAL_STATUSES and (
            row.deadline_at <= now or (row.lease_expires_at and row.lease_expires_at <= now)
        ):
            expired = row.deadline_at <= now
            _finish(
                row,
                "timed_out" if expired else "lost",
                "CONNECTOR_BUSY"
                if row.status == "queued"
                else "CONNECTOR_TIMEOUT"
                if expired
                else "CONNECTOR_WORKER_LOST",
                now,
                process_stopped=row.status == "queued",
            )
            db.commit()
    return row


def dispatch_run(db: Session, row: ComputeRun) -> str:
    if row.recipe_execution_id:
        raise ComputeRunError("COMPUTE_LEGACY_DISPATCH_REQUIRED")
    from app.services.execution.rollout import durable_for
    if durable_for(db, row.workspace_id):
        from app.services.execution.dispatch import stage
        intent = stage(db, "compute_run", row, deadline_at=row.deadline_at)
        db.commit()
        return intent.task_id
    from app.workers.celery_connectors import celery_connectors

    # Commit the durable intent before publishing; the message contains only an
    # opaque registry ID. Dispatch failure does not erase the durable evidence.
    task_id = str(uuid4())
    row.celery_task_id = task_id
    db.commit()
    try:
        celery_connectors.send_task(
            TASK_NAME,
            args=[row.id],
            task_id=task_id,
            queue=settings.celery_connectors_interactive_queue
            if row.operation in INTERACTIVE
            else settings.celery_connectors_queue,
        )
    except Exception:
        db.query(ComputeRun).filter_by(id=row.id, status="queued").update(
            {
                "status": "failed",
                "stage": "failed",
                "error_code": "CONNECTOR_DISPATCH_FAILED",
                "finished_at": utcnow(),
            }
        )
        db.commit()
        raise ComputeRunError("CONNECTOR_DISPATCH_FAILED", 503) from None
    return task_id


def _finish(
    row: ComputeRun, status: str, error_code: str | None, now: datetime, output: dict | None = None,
    *, process_stopped: bool = True,
) -> None:
    if row.write_started and status != "succeeded":
        status, error_code, row.outcome_unknown = "lost", "CONNECTOR_WRITE_OUTCOME_UNKNOWN", True
    row.status = row.stage = status
    row.error_code, row.finished_at = error_code, now
    row.lease_expires_at = None
    row.output_json = output if status == "succeeded" else None
    seconds = max(0, (now - row.started_at).total_seconds()) if row.started_at else 0
    row.core_hours = seconds * row.cpu_cores / 3600
    cpu_rate = getattr(settings, "dataops_core_hour_usd", None)
    memory_rate = getattr(settings, "dataops_gb_hour_usd", None)
    row.cost_usd = (
        None
        if cpu_rate is None or memory_rate is None
        else row.core_hours * cpu_rate + seconds / 3600 * row.memory_mb / 1024 * memory_rate
    )
    row.metrics_json = {
        **(row.metrics_json or {}),
        "wall_seconds": seconds,
        "core_hours": row.core_hours,
        "cost_basis": "requested_resources_x_wall_time",
        "cost_usd": row.cost_usd,
    }
    from sqlalchemy.orm import object_session

    from app.models.execution_control import ExecutionReservation
    db = object_session(row)
    allocation = db.query(ExecutionReservation).filter_by(entity_kind="compute_run", entity_id=row.id).one_or_none() if db else None
    if allocation:
        from app.services.execution.admission import settle
        settle(db, entity_kind="compute_run", entity_id=row.id, token=allocation.lease_token,
               outcome=status if process_stopped else "reconciliation_required", now=now,
               process_stopped=process_stopped)
        # Frozen tariffs, never a new price applied retroactively.
        cpu_rate, memory_rate = allocation.policy.get("cpu_hour_usd"), allocation.policy.get("gb_hour_usd")
        row.cost_usd = None if cpu_rate is None or memory_rate is None else row.core_hours * cpu_rate + seconds / 3600 * row.memory_mb / 1024 * memory_rate
        row.metrics_json = {**row.metrics_json, "cost_usd": row.cost_usd}
    if row.operation == "test":
        from sqlalchemy.orm import object_session

        from app.services.connectors.runtime_identity import record_test

        db = object_session(row)
        if db is not None:
            record_test(db, row, row.output_json or {})
    if row.operation == "reconcile_write":
        from sqlalchemy.orm import object_session

        from app.services.connectors.writes import settle_reconciliation

        db = object_session(row)
        if db is not None:
            settle_reconciliation(db, row, row.output_json)
    if row.operation in WRITES:
        from sqlalchemy.orm import object_session

        from app.services.connectors.writes import settle

        db = object_session(row)
        if db is not None:
            settle(db, row, row.output_json)


def claim_run(db: Session, run_id: str, *, now: datetime | None = None) -> str | None:
    now = _utc(now) if now else utcnow()
    row = db.get(ComputeRun, run_id)
    if row is None:
        return None
    controlled = (row.metrics_json or {}).get("coordination_version") == 1
    if controlled:
        from app.services.execution.admission import AdmissionError, lock_scopes
        try:
            lock_scopes(db, row.workspace_id)
        except AdmissionError as exc:
            db.rollback()
            from app.services.execution.dispatch import defer_native
            defer_native(db, "compute_run", run_id, code=exc.code)
            db.commit()
            return None
    workspace = _lock_workspace(db, row.workspace_id)
    from app.services.execution.control import parent_cancelled
    cancelled_parent = parent_cancelled(db, row.run_id, row.workspace_id)
    row = db.query(ComputeRun).filter_by(id=run_id).with_for_update().populate_existing().one()
    if row.status in TERMINAL_STATUSES:
        return None
    if row.status in ACTIVE_STATUSES:
        if row.lease_expires_at is None or row.lease_expires_at <= now:
            _finish(row, "lost", "CONNECTOR_WORKER_LOST", now, process_stopped=False)
            db.commit()
        return None
    if cancelled_parent:
        row.cancel_requested = True
    if row.cancel_requested or row.deadline_at <= now:
        _finish(
            row,
            "cancelled" if row.cancel_requested else "timed_out",
            "CONNECTOR_CANCELLED" if row.cancel_requested else "CONNECTOR_BUSY",
            now,
        )
        db.commit()
        return None
    running = (
        db.query(func.count(ComputeRun.id))
        .filter(ComputeRun.workspace_id == row.workspace_id, ComputeRun.status.in_(ACTIVE_STATUSES))
        .scalar()
    )
    if running >= _limit(workspace, "max_concurrent_runs", 2):
        from app.models.execution_control import ExecutionDispatch
        if db.query(ExecutionDispatch.id).filter_by(entity_kind="compute_run", entity_id=run_id).first():
            db.rollback()
            from app.services.execution.dispatch import defer_native
            defer_native(db, "compute_run", run_id, code="CONNECTOR_BUSY")
            db.commit()
            return None
        raise ComputeRunError("CONNECTOR_BUSY", 429)
    if controlled:
        from app.services.execution.admission import AdmissionError, reserve
        try:
            reserve(db, workspace_id=row.workspace_id, entity_kind="compute_run", entity_id=row.id,
                    cpu_cores=row.cpu_cores, memory_mb=row.memory_mb, deadline_at=row.deadline_at,
                    lane="interactive" if row.operation in INTERACTIVE else "batch", now=now)
        except AdmissionError as exc:
            db.rollback()
            from app.services.execution.dispatch import defer_native
            defer_native(db, "compute_run", row.id, code=exc.code)
            db.commit()
            return None
    token = str(uuid4())
    changed = (
        db.query(ComputeRun)
        .filter_by(id=run_id, status="queued", cancel_requested=False)
        .update(
            {
                "status": "admitted",
                "stage": "admitted",
                "started_at": now,
                "lease_token": token,
                "lease_expires_at": min(
                    row.deadline_at, now + timedelta(seconds=settings.connector_lease_s)
                ),
            }
        )
    )
    db.commit()
    return token if changed == 1 else None


def advance_run(
    db: Session,
    run_id: str,
    token: str,
    status: str,
    *,
    now: datetime | None = None,
    write_started: bool = False,
) -> bool:
    if status not in {"launching", "running", "committing"}:
        raise ComputeRunError("COMPUTE_TRANSITION_INVALID")
    previous = {"launching": "admitted", "running": "launching", "committing": "running"}[status]
    now = _utc(now) if now else utcnow()
    values = {"status": status, "stage": status}
    if write_started:
        values["write_started"] = True
    changed = (
        db.query(ComputeRun)
        .filter(
            ComputeRun.id == run_id,
            ComputeRun.lease_token == token,
            ComputeRun.status == previous,
            ComputeRun.cancel_requested.is_(False),
            ComputeRun.deadline_at > now,
            ComputeRun.lease_expires_at > now,
        )
        .update(values)
    )
    db.commit()
    return changed == 1


def heartbeat(db: Session, run_id: str, token: str, *, now: datetime | None = None) -> bool:
    now = _utc(now) if now else utcnow()
    changed = (
        db.query(ComputeRun)
        .filter(
            ComputeRun.id == run_id,
            ComputeRun.lease_token == token,
            ComputeRun.status.in_(ACTIVE_STATUSES),
            ComputeRun.cancel_requested.is_(False),
            ComputeRun.deadline_at > now,
            ComputeRun.lease_expires_at > now,
        )
        .update({"lease_expires_at": now + timedelta(seconds=settings.connector_lease_s)})
    )
    db.commit()
    return changed == 1


def finish_run(
    db: Session,
    run_id: str,
    token: str,
    *,
    status: str,
    error_code: str | None = None,
    output: dict | None = None,
    now: datetime | None = None,
    publish=None,
) -> bool:
    if status not in TERMINAL_STATUSES:
        raise ComputeRunError("COMPUTE_TRANSITION_INVALID")
    now = _utc(now) if now else utcnow()
    row = (
        db.query(ComputeRun)
        .filter_by(id=run_id, lease_token=token)
        .with_for_update()
        .populate_existing()
        .first()
    )
    if row is None:
        return False
    if row.status in TERMINAL_STATUSES:
        # A reaper fences publication while physical stop is still unknown.
        # This matching worker has now left its child supervisor, so it may
        # acknowledge stopped resources without changing the terminal result.
        from app.models.execution_control import ExecutionReservation
        allocation = db.query(ExecutionReservation).filter_by(entity_kind="compute_run", entity_id=row.id).one_or_none()
        if allocation is not None and allocation.released_at is None:
            from app.services.execution.admission import settle
            settle(db, entity_kind="compute_run", entity_id=row.id, token=allocation.lease_token,
                   outcome=row.status, now=now, process_stopped=True)
            db.commit()
        return False
    if row.cancel_requested:
        status, error_code = "cancelled", "CONNECTOR_CANCELLED"
    elif row.deadline_at <= now:
        status, error_code = "timed_out", "CONNECTOR_TIMEOUT"
    elif row.lease_expires_at is None or row.lease_expires_at <= now:
        status, error_code = "lost", "CONNECTOR_WORKER_LOST"
    if status == "succeeded" and publish is not None:
        # We own the database row lock and passed the live lease fence. The
        # atomic publication cannot heartbeat against its own lock; its commit
        # lease now lasts until the absolute deadline. Reaper/cancel serialize
        # at this same boundary, while a crash still rolls back publication.
        row.lease_expires_at = row.deadline_at
        try:
            with db.begin_nested():
                output = publish()
                now = utcnow()
                if row.deadline_at <= now or row.lease_expires_at <= now:
                    raise ComputeRunError("CONNECTOR_TIMEOUT")
        except Exception as exc:
            status, output = "failed", None
            error_code = getattr(exc, "code", "CONNECTOR_PUBLICATION_FAILED")
            if error_code == "CONNECTOR_TIMEOUT":
                status = "timed_out"
    _finish(row, status, error_code, now, output)
    db.commit()
    return True


def request_cancel(db: Session, row: ComputeRun, *, commit: bool = True) -> ComputeRun:
    row = (
        db.query(ComputeRun)
        .filter_by(id=row.id, workspace_id=row.workspace_id)
        .with_for_update()
        .populate_existing()
        .one()
    )
    if row.status not in TERMINAL_STATUSES:
        row.cancel_requested = True
        if row.status == "queued":
            _finish(row, "cancelled", "CONNECTOR_CANCELLED", utcnow())
        if row.recipe_execution_id:
            from app.models.recipe import RecipeExecution
            from app.services.recipe_executions import request_cancel as cancel_legacy

            legacy = db.get(RecipeExecution, row.recipe_execution_id)
            if legacy:
                cancel_legacy(db, legacy, commit=False)
        db.commit() if commit else db.flush()
    return row


def reap_runs(db: Session, *, now: datetime | None = None, limit: int = 100) -> int:
    now = _utc(now) if now else utcnow()
    rows = (
        db.query(ComputeRun)
        .filter(
            ComputeRun.status.notin_(TERMINAL_STATUSES),
            ((ComputeRun.deadline_at <= now) | (ComputeRun.lease_expires_at <= now)),
        )
        .order_by(ComputeRun.created_at)
        .with_for_update(skip_locked=True)
        .limit(limit)
        .all()
    )
    for row in rows:
        pending = row.status == "queued"
        status = "timed_out" if row.deadline_at <= now else "lost"
        error = (
            "CONNECTOR_BUSY"
            if pending
            else "CONNECTOR_TIMEOUT"
            if status == "timed_out"
            else "CONNECTOR_WORKER_LOST"
        )
        _finish(row, status, error, now, process_stopped=pending)
    db.commit()
    return len(rows)


def serialize_run(row: ComputeRun) -> dict:
    return {
        "id": row.id,
        "workspace_id": row.workspace_id,
        "connection_id": row.connection_id,
        "operation": row.operation,
        "kind": row.kind,
        "status": row.status,
        "stage": row.stage,
        "cancel_requested": row.cancel_requested,
        "outcome_unknown": row.outcome_unknown,
        "error_code": row.error_code,
        "output": row.output_json,
        "metrics": row.metrics_json,
        "cost_usd": row.cost_usd,
        "created_at": row.created_at.isoformat(),
        "deadline_at": row.deadline_at.isoformat(),
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "finished_at": row.finished_at.isoformat() if row.finished_at else None,
    }
