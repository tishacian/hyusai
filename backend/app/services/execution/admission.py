"""Atomic global/workspace resource reservations shared by native executors.

Transactions lock scopes in one order (global, workspace, native row). Unknown
worker outcomes retain their reservation until reconciliation; an expired lease
alone is not proof that a process stopped consuming resources.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.core.config import settings
from app.models.execution_control import ExecutionCapacity, ExecutionReservation
from app.models.workspace import Workspace


class AdmissionError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def lock_scopes(db, workspace_id: str):
    insert = sqlite_insert if db.bind.dialect.name == "sqlite" else pg_insert
    for scope in ("global", f"workspace:{workspace_id}"):
        db.execute(
            insert(ExecutionCapacity)
            .values(scope=scope, generation=0, paused=0)
            .on_conflict_do_nothing(index_elements=["scope"])
        )
        # UPDATE serializes SQLite too; PostgreSQL retains this lock until commit.
        db.execute(
            update(ExecutionCapacity)
            .where(ExecutionCapacity.scope == scope)
            .values(generation=ExecutionCapacity.generation + 1)
        )
        record = db.get(ExecutionCapacity, scope, populate_existing=True)
        if record.paused:
            raise AdmissionError("EXECUTION_ADMISSION_PAUSED")


def _number(value, name, *, minimum=0):
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value <= minimum
    ):
        raise AdmissionError(f"EXECUTION_INVALID_{name.upper()}")
    return value


def _policy(db, workspace_id):
    workspace = db.get(Workspace, workspace_id)
    if workspace is None:
        raise AdmissionError("EXECUTION_WORKSPACE_MISSING")
    limits = (workspace.settings or {}).get("execution_limits", {})
    if not isinstance(limits, dict):
        raise AdmissionError("EXECUTION_POLICY_INVALID")
    result = {}
    for key, operator in {
        "slots": settings.execution_workspace_slots,
        "cpu": settings.execution_workspace_cpu,
        "memory_mb": settings.execution_workspace_memory_mb,
        "core_hours_per_day": settings.execution_workspace_core_hours,
    }.items():
        result[key] = min(operator, _number(limits.get(key, operator), key))
    result["version"] = 1
    return result


def day_allocations(start: datetime, end: datetime, cores: float) -> dict[str, float]:
    result = {}
    current = start
    while current < end:
        next_day = current.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        stop = min(end, next_day)
        result[current.date().isoformat()] = (stop - current).total_seconds() * cores / 3600
        current = stop
    return result


def reserve(
    db,
    *,
    workspace_id: str,
    entity_kind: str,
    entity_id: str,
    cpu_cores: float,
    memory_mb: int,
    deadline_at: datetime,
    lane: str = "batch",
    now: datetime | None = None,
):
    now = now or datetime.utcnow()
    _number(cpu_cores, "cpu")
    _number(memory_mb, "memory")
    if (
        lane not in {"batch", "interactive"}
        or deadline_at <= now
        or deadline_at > now + timedelta(days=1)
    ):
        raise AdmissionError("EXECUTION_DEADLINE_INVALID")
    lock_scopes(db, workspace_id)
    existing = (
        db.query(ExecutionReservation)
        .filter_by(entity_kind=entity_kind, entity_id=entity_id)
        .one_or_none()
    )
    if existing:
        if existing.workspace_id != workspace_id or existing.released_at is not None:
            raise AdmissionError("EXECUTION_RESERVATION_ALREADY_SETTLED")
        return existing
    policy = _policy(db, workspace_id)
    active = db.query(ExecutionReservation).filter(ExecutionReservation.released_at.is_(None)).all()
    own = [r for r in active if r.workspace_id == workspace_id]
    if any(r.outcome or r.deadline_at <= now for r in own):
        # A lost process can continue spending beyond its original envelope.
        # Its daily cost is unknown until stop/reconciliation, not zero after
        # midnight. Keep other tenants bounded by the retained global slots.
        raise AdmissionError("EXECUTION_RECONCILIATION_REQUIRED")
    reserved_slots = min(
        settings.execution_interactive_reserved_slots, max(0, settings.execution_global_slots - 1)
    )
    batch = [r for r in active if r.lane == "batch"]
    if (
        len(active) >= settings.execution_global_slots
        or len(own) >= policy["slots"]
        or (lane == "batch" and len(batch) >= settings.execution_global_slots - reserved_slots)
    ):
        raise AdmissionError("EXECUTION_SLOTS_EXHAUSTED")
    if (
        sum(r.cpu_cores for r in active) + cpu_cores > settings.execution_global_cpu
        or sum(r.cpu_cores for r in own) + cpu_cores > policy["cpu"]
        or (
            lane == "batch"
            and sum(r.cpu_cores for r in batch) + cpu_cores
            > settings.execution_global_cpu - settings.execution_interactive_reserved_cpu
        )
    ):
        raise AdmissionError("EXECUTION_CPU_EXHAUSTED")
    if (
        sum(r.memory_mb for r in active) + memory_mb > settings.execution_global_memory_mb
        or sum(r.memory_mb for r in own) + memory_mb > policy["memory_mb"]
        or (
            lane == "batch"
            and sum(r.memory_mb for r in batch) + memory_mb
            > settings.execution_global_memory_mb
            - settings.execution_interactive_reserved_memory_mb
        )
    ):
        raise AdmissionError("EXECUTION_MEMORY_EXHAUSTED")
    requested = day_allocations(now, deadline_at, cpu_cores)
    # Admission is bounded to 24h, so rows whose envelope intersects this day or
    # the next are enough. Unknown old outcomes remain in the active set above.
    history = (
        db.query(ExecutionReservation)
        .filter(
            ExecutionReservation.workspace_id == workspace_id,
            ExecutionReservation.deadline_at
            >= now.replace(hour=0, minute=0, second=0, microsecond=0),
        )
        .all()
    )
    for day, hours in requested.items():
        occupied = sum(float((r.policy or {}).get("budget_days", {}).get(day, 0)) for r in history)
        if occupied + hours > policy["core_hours_per_day"]:
            raise AdmissionError("EXECUTION_BUDGET_EXHAUSTED")
    record = ExecutionReservation(
        id=str(uuid4()),
        workspace_id=workspace_id,
        entity_kind=entity_kind,
        entity_id=entity_id,
        lane=lane,
        cpu_cores=cpu_cores,
        memory_mb=memory_mb,
        reserved_core_hours=sum(requested.values()),
        policy={
            **policy,
            "budget_days": requested,
            "cpu_hour_usd": getattr(settings, "dataops_core_hour_usd", None),
            "gb_hour_usd": getattr(settings, "dataops_gb_hour_usd", None),
        },
        lease_token=str(uuid4()),
        created_at=now,
        deadline_at=deadline_at,
    )
    db.add(record)
    db.flush()
    return record


def settle(
    db,
    *,
    entity_kind: str,
    entity_id: str,
    token: str,
    outcome: str,
    now: datetime | None = None,
    cpu_seconds: float | None = None,
    peak_rss_bytes: float | None = None,
    process_stopped: bool = True,
):
    row = (
        db.query(ExecutionReservation)
        .filter_by(entity_kind=entity_kind, entity_id=entity_id)
        .with_for_update()
        .one_or_none()
    )
    if row is None or row.lease_token != token:
        raise AdmissionError("EXECUTION_RESERVATION_FENCE_LOST")
    if row.released_at is not None:
        return row
    row.outcome = outcome
    if not process_stopped:
        # Neither zero usage nor released capacity can be inferred from a loss.
        return row
    now = now or datetime.utcnow()
    row.released_at = now
    row.allocated_core_hours = max(0, (now - row.created_at).total_seconds()) * row.cpu_cores / 3600
    row.cpu_seconds = cpu_seconds
    row.peak_rss_bytes = peak_rss_bytes
    row.policy = {**row.policy, "budget_days": day_allocations(row.created_at, now, row.cpu_cores)}
    return row


def snapshot(db):
    rows = db.query(ExecutionReservation).filter(ExecutionReservation.released_at.is_(None)).all()
    return {
        "active": len(rows),
        "reserved_cpu": sum(r.cpu_cores for r in rows),
        "reserved_memory_mb": sum(r.memory_mb for r in rows),
        "limits": {
            "slots": settings.execution_global_slots,
            "cpu": settings.execution_global_cpu,
            "memory_mb": settings.execution_global_memory_mb,
        },
        "unreconciled": sum(bool(r.outcome) for r in rows),
    }
