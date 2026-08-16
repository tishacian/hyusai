"""PostgreSQL-backed transactional outbox for durable Run dispatch.

Producers call :func:`enqueue_dispatch` inside their existing transaction.  A
maintenance process claims due rows with ``FOR UPDATE SKIP LOCKED`` and sends
identifier-only Celery messages.  Delivery is deliberately at-least-once: a
crash after the broker ACK expires the lease and republishes the same
deterministic task id, while Run coordination leases make execution idempotent.
"""
from __future__ import annotations

import hashlib
import math
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

from sqlalchemy import Integer, String, and_, cast, func, or_
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session as DBSession
from sqlalchemy.orm import aliased

from app.core.logging import get_logger
from app.db.base import SessionLocal
from app.models.decision import Decision
from app.models.run import Run
from app.models.run_dispatch_outbox import DISPATCH_EVENT_TYPES, RunDispatchOutbox
from app.services.run_engine.subflow_orchestration import _wave_ids_equal

logger = get_logger(__name__)

TRIGGER_RUN = "trigger_run"
SUBFLOW_RUN = "subflow_run"
SUBFLOW_PARENT_RESUME = "subflow_parent_resume"
SUBFLOW_HITL_RESUME = "subflow_hitl_resume"
RUN_HITL_RESUME = "run_hitl_resume"

_TASK_NAMES = {
    TRIGGER_RUN: "agentium.trigger_run",
    SUBFLOW_RUN: "agentium.subflow_run",
    SUBFLOW_PARENT_RESUME: "agentium.subflow_parent_resume",
    SUBFLOW_HITL_RESUME: "agentium.subflow_hitl_resume",
    RUN_HITL_RESUME: "agentium.run_hitl_resume",
}
_TERMINAL_RUN_STATUSES = {"completed", "failed", "cancelled"}
_RESOLVED_DECISION_STATUSES = {"accepted", "applied", "rejected"}
_EXPERIENCE_RECOVERY_GRACE_SECONDS = 60


class DispatchLeaseLost(RuntimeError):
    """Raised when a stale publisher tries to settle a reclaimed row."""


class PermanentDispatchError(ValueError):
    """Raised when an outbox row cannot form a valid identifier-only task."""


class ObsoleteDispatch(RuntimeError):
    """Raised when authoritative Run state proves a dispatch is no longer needed."""


class DispatchNotReady(RuntimeError):
    """Raised when committed coordination state is not publishable yet."""


def durable_initial_dispatch_source(run: Run) -> str | None:
    """Return the server-owned claim that authorises initial Run recovery."""
    if run.trigger == "webhook" and run.trigger_dedup_key:
        return str(run.trigger_dedup_key)
    claim = str(run.experience_idempotency_key or "")
    source = str(run.trigger_dedup_key or "")
    ingress = (run.input_ref or {}).get("_ingress")
    adapter = ingress.get("adapter") if isinstance(ingress, dict) else None
    request_sha256 = adapter.get("request_sha256") if isinstance(adapter, dict) else None
    required_provenance = (
        "experience_id",
        "experience_slug",
        "experience_release_id",
        "experience_deployment_id",
        "binding_key",
        "page_id",
        "component_id",
    )
    if (
        run.trigger != "manual"
        or not str(run.execution_surface or "").startswith("published_")
        or len(claim) != 64
        or any(character not in "0123456789abcdef" for character in claim)
        or source != f"experience:{claim}"
        or not isinstance(adapter, dict)
        or adapter.get("surface") != "experience"
        or not isinstance(request_sha256, str)
        or len(request_sha256) != 64
        or any(character not in "0123456789abcdef" for character in request_sha256)
        or any(
            not isinstance(adapter.get(field), str) or not adapter[field].strip()
            for field in required_provenance
        )
    ):
        return None
    return source


def _utc_naive(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _canonical_dedupe_key(
    *,
    event_type: str,
    workspace_id: str,
    run_id: str,
    source_id: str | None,
    decision_id: str | None,
    wave_id: int | None,
) -> str:
    raw = "\x1f".join(
        (
            "agentium-run-dispatch-v1",
            event_type,
            workspace_id,
            run_id,
            source_id or "",
            decision_id or "",
            "" if wave_id is None else str(wave_id),
        )
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def enqueue_dispatch(
    db: DBSession,
    *,
    event_type: str,
    workspace_id: str,
    run_id: str,
    source_id: str | None = None,
    decision_id: str | None = None,
    wave_id: int | None = None,
    dedupe_key: str | None = None,
    available_at: datetime | None = None,
) -> RunDispatchOutbox:
    """Idempotently add one dispatch to the caller's transaction.

    This function flushes so foreign keys and uniqueness are checked, but it
    never commits. PostgreSQL and SQLite use ``ON CONFLICT DO NOTHING`` so two
    producers racing on the same logical event converge without rolling back
    unrelated state in the transaction.
    """

    if event_type not in DISPATCH_EVENT_TYPES:
        raise ValueError(f"unsupported Run dispatch event_type: {event_type!r}")
    workspace_id = str(workspace_id or "").strip()
    run_id = str(run_id or "").strip()
    if not workspace_id or not run_id:
        raise ValueError("workspace_id and run_id are required for Run dispatch")
    if event_type in {SUBFLOW_HITL_RESUME, RUN_HITL_RESUME} and not decision_id:
        raise ValueError(f"decision_id is required for {event_type}")
    if wave_id is not None and (type(wave_id) is not int or wave_id < 0):
        raise ValueError("wave_id must be a non-negative integer")

    logical_key = str(dedupe_key or "").strip() or _canonical_dedupe_key(
        event_type=event_type,
        workspace_id=workspace_id,
        run_id=run_id,
        source_id=str(source_id) if source_id is not None else None,
        decision_id=str(decision_id) if decision_id is not None else None,
        wave_id=wave_id,
    )
    if len(logical_key) > 255:
        logical_key = hashlib.sha256(logical_key.encode("utf-8")).hexdigest()
    row_id = str(uuid5(NAMESPACE_URL, f"agentium:run-dispatch-row:{logical_key}"))
    task_id = str(uuid5(NAMESPACE_URL, f"agentium:run-dispatch-task:{logical_key}"))
    now = datetime.utcnow()
    values = {
        "id": row_id,
        "workspace_id": workspace_id,
        "run_id": run_id,
        "event_type": event_type,
        "source_id": str(source_id) if source_id is not None else None,
        "decision_id": str(decision_id) if decision_id is not None else None,
        "wave_id": wave_id,
        "dedupe_key": logical_key,
        "task_id": task_id,
        "state": "pending",
        "attempts": 0,
        "available_at": available_at or now,
        "created_at": now,
        "updated_at": now,
    }

    # SessionLocal disables autoflush. Flush pending Runs before issuing the
    # Core INSERT so the outbox FK remains valid within the same transaction.
    db.flush()
    dialect = db.get_bind().dialect.name
    if dialect == "postgresql":
        statement = postgresql_insert(RunDispatchOutbox).values(**values)
        statement = statement.on_conflict_do_nothing(index_elements=["dedupe_key"])
        db.execute(statement)
    elif dialect == "sqlite":
        statement = sqlite_insert(RunDispatchOutbox).values(**values)
        statement = statement.on_conflict_do_nothing(index_elements=["dedupe_key"])
        db.execute(statement)
    else:
        existing = (
            db.query(RunDispatchOutbox)
            .filter(RunDispatchOutbox.dedupe_key == logical_key)
            .first()
        )
        if existing is None:
            db.add(RunDispatchOutbox(**values))
            db.flush()
    row = (
        db.query(RunDispatchOutbox)
        .filter(RunDispatchOutbox.dedupe_key == logical_key)
        .one()
    )
    expected = (
        workspace_id,
        run_id,
        event_type,
        str(source_id) if source_id is not None else None,
        str(decision_id) if decision_id is not None else None,
        wave_id,
    )
    actual = (
        row.workspace_id,
        row.run_id,
        row.event_type,
        row.source_id,
        row.decision_id,
        row.wave_id,
    )
    if actual != expected:
        raise ValueError("dedupe_key is already bound to a different dispatch envelope")
    return row


def claim_dispatch_batch(
    db: DBSession,
    *,
    batch_size: int = 50,
    lease_seconds: int = 60,
    now: datetime | None = None,
) -> list[RunDispatchOutbox]:
    """Lease due rows; PostgreSQL reconcilers skip each other's locked rows."""

    if batch_size < 1 or lease_seconds < 1:
        raise ValueError("batch_size and lease_seconds must be positive")
    current = now or datetime.utcnow()
    due = or_(
        and_(
            RunDispatchOutbox.state == "pending",
            RunDispatchOutbox.available_at <= current,
        ),
        and_(
            RunDispatchOutbox.state == "leased",
            or_(
                RunDispatchOutbox.lease_expires_at.is_(None),
                RunDispatchOutbox.lease_expires_at <= current,
            ),
        ),
    )
    rows = (
        db.query(RunDispatchOutbox)
        .filter(due)
        .order_by(RunDispatchOutbox.available_at, RunDispatchOutbox.created_at)
        .with_for_update(skip_locked=True)
        .limit(batch_size)
        .all()
    )
    for row in rows:
        row.state = "leased"
        row.lease_token = str(uuid4())
        row.lease_expires_at = current + timedelta(seconds=lease_seconds)
        row.attempts = int(row.attempts or 0) + 1
        row.updated_at = current
    db.commit()
    return rows


def _leased_row(db: DBSession, outbox_id: str, lease_token: str) -> RunDispatchOutbox:
    row = (
        db.query(RunDispatchOutbox)
        .filter(
            RunDispatchOutbox.id == outbox_id,
            RunDispatchOutbox.state == "leased",
            RunDispatchOutbox.lease_token == lease_token,
        )
        .with_for_update()
        .first()
    )
    if row is None:
        raise DispatchLeaseLost(f"dispatch lease lost for outbox row {outbox_id}")
    return row


def mark_dispatch_published(
    db: DBSession,
    *,
    outbox_id: str,
    lease_token: str,
    now: datetime | None = None,
) -> RunDispatchOutbox:
    """Settle a publication only while the caller still owns its lease."""

    current = now or datetime.utcnow()
    row = _leased_row(db, outbox_id, lease_token)
    row.state = "published"
    row.published_at = current
    row.updated_at = current
    row.last_error = None
    row.lease_token = None
    row.lease_expires_at = None
    if row.event_type == TRIGGER_RUN:
        run = (
            db.query(Run)
            .filter(Run.id == row.run_id, Run.workspace_id == row.workspace_id)
            .first()
        )
        if run is not None:
            run.celery_task_id = row.task_id
    elif row.event_type == SUBFLOW_RUN:
        child = (
            db.query(Run)
            .filter(Run.id == row.run_id, Run.workspace_id == row.workspace_id)
            .first()
        )
        if child is not None:
            child.celery_task_id = row.task_id
            if child.parent_run_id and child.delegation_key:
                parent = (
                    db.query(Run)
                    .filter(
                        Run.id == child.parent_run_id,
                        Run.workspace_id == child.workspace_id,
                    )
                    .first()
                )
                if parent is not None and isinstance(parent.waiting_subflows, dict):
                    waiting = dict(parent.waiting_subflows)
                    meta = (
                        waiting.get("_meta")
                        if isinstance(waiting.get("_meta"), dict)
                        else {}
                    )
                    entry = dict(waiting.get(child.delegation_key) or {})
                    if (
                        entry.get("child_run_id") == child.id
                        and _wave_ids_equal(row.wave_id, meta.get("wave_id"))
                        and _wave_ids_equal(
                            entry.get("wave_id"),
                            meta.get("wave_id"),
                        )
                    ):
                        entry.update(
                            {
                                "celery_task_id": row.task_id,
                                "dispatch_state": "dispatched",
                            }
                        )
                        waiting[child.delegation_key] = entry
                        parent.waiting_subflows = waiting
    db.commit()
    return row


def _retry_delay_seconds(row: RunDispatchOutbox, *, base: float, cap: float) -> float:
    exponent = max(0, min(int(row.attempts or 1) - 1, 20))
    raw = min(cap, base * (2**exponent))
    digest = hashlib.sha256(f"{row.id}:{row.attempts}".encode("utf-8")).digest()
    jitter = 0.8 + (int.from_bytes(digest[:2], "big") / 65535.0) * 0.4
    return min(cap, raw * jitter)


def mark_dispatch_retry(
    db: DBSession,
    *,
    outbox_id: str,
    lease_token: str,
    error: str,
    now: datetime | None = None,
    base_delay_seconds: float = 1.0,
    max_delay_seconds: float = 300.0,
) -> RunDispatchOutbox:
    """Release a failed broker attempt with deterministic capped backoff."""

    current = now or datetime.utcnow()
    row = _leased_row(db, outbox_id, lease_token)
    delay = _retry_delay_seconds(
        row,
        base=max(0.01, base_delay_seconds),
        cap=max(base_delay_seconds, max_delay_seconds),
    )
    row.state = "pending"
    row.available_at = current + timedelta(seconds=delay)
    row.updated_at = current
    row.last_error = str(error)[:2000]
    row.lease_token = None
    row.lease_expires_at = None
    db.commit()
    return row


def mark_dispatch_dead(
    db: DBSession,
    *,
    outbox_id: str,
    lease_token: str,
    error: str,
    now: datetime | None = None,
) -> RunDispatchOutbox:
    current = now or datetime.utcnow()
    row = _leased_row(db, outbox_id, lease_token)
    row.state = "dead"
    row.updated_at = current
    row.last_error = str(error)[:2000]
    row.lease_token = None
    row.lease_expires_at = None
    db.commit()
    return row


def mark_dispatch_cancelled(
    db: DBSession,
    *,
    outbox_id: str,
    lease_token: str,
    reason: str,
    now: datetime | None = None,
) -> RunDispatchOutbox:
    """Settle a valid historical event that authoritative state superseded."""

    current = now or datetime.utcnow()
    row = _leased_row(db, outbox_id, lease_token)
    row.state = "cancelled"
    row.updated_at = current
    row.last_error = str(reason)[:2000]
    row.lease_token = None
    row.lease_expires_at = None
    db.commit()
    return row


def _active_parent_claim_envelope(
    db: DBSession,
    *,
    child: Run,
    workspace_id: str,
) -> tuple[Run, dict[str, Any], dict[str, Any]]:
    """Validate the active parent-owned half of a delegation contract."""

    if (
        child.workspace_id != workspace_id
        or not child.parent_run_id
        or not child.delegation_key
    ):
        raise PermanentDispatchError("delegated Run has no stable parent claim")
    parent = (
        db.query(Run)
        .filter(
            Run.id == child.parent_run_id,
            Run.workspace_id == workspace_id,
        )
        .first()
    )
    if parent is None:
        raise PermanentDispatchError("delegated Run parent no longer exists")
    waiting = parent.waiting_subflows if isinstance(parent.waiting_subflows, dict) else {}
    meta = waiting.get("_meta") if isinstance(waiting.get("_meta"), dict) else {}
    if meta.get("execution_plane") != "celery":
        raise PermanentDispatchError("delegated parent execution plane is invalid")
    entry = waiting.get(child.delegation_key)
    if not isinstance(entry, dict) or str(entry.get("child_run_id") or "") != child.id:
        raise PermanentDispatchError("delegated parent does not claim this child")
    active_wave = meta.get("wave_id")
    if active_wave is not None and not _wave_ids_equal(
        entry.get("wave_id"),
        active_wave,
    ):
        raise ObsoleteDispatch("delegation is not part of the active parent wave")
    return parent, entry, meta


def _active_delegation_envelope(
    db: DBSession,
    *,
    child: Run,
    workspace_id: str,
) -> tuple[Run, dict[str, Any], dict[str, Any]]:
    if not child.parent_run_id or not child.delegation_key:
        raise PermanentDispatchError("delegated Run has no stable parent envelope")
    delegation = (
        ((child.input_ref or {}).get("_delegation") or {})
        if isinstance(child.input_ref, dict)
        else {}
    )
    if (
        not isinstance(delegation, dict)
        or str(delegation.get("parent_run_id") or "") != child.parent_run_id
        or delegation.get("execution_plane") != "celery"
    ):
        raise PermanentDispatchError("delegated Run execution plane is invalid")
    parent, entry, meta = _active_parent_claim_envelope(
        db,
        child=child,
        workspace_id=workspace_id,
    )
    if str(entry.get("node_id") or "") != str(child.delegation_node_id or ""):
        raise PermanentDispatchError("delegation node does not match the child")
    if str(entry.get("branch") or "") != str(child.delegation_branch or ""):
        raise PermanentDispatchError("delegation branch does not match the child")
    return parent, entry, meta


def _watchdog_quarantine_attested(run: Run) -> bool:
    """Allow recovery from a corrupt child only after a stable quarantine."""

    return bool(
        run.status == "failed"
        and run.error == "subflow_hitl_watchdog_invalid_state"
        and run.delegation_quarantined_at is not None
    )


def _task_envelope(
    db: DBSession,
    row: RunDispatchOutbox,
) -> tuple[str, list[str], dict[str, Any]]:
    task_name = _TASK_NAMES.get(row.event_type)
    if task_name is None:
        raise PermanentDispatchError(f"unknown dispatch type {row.event_type!r}")
    if row.event_type in {SUBFLOW_HITL_RESUME, RUN_HITL_RESUME}:
        if not row.decision_id:
            raise PermanentDispatchError(f"{row.event_type} has no decision_id")
        args = [row.run_id, row.decision_id]
    else:
        args = [row.run_id]
    options: dict[str, Any] = {"task_id": row.task_id}
    run = (
        db.query(Run)
        .filter(Run.id == row.run_id, Run.workspace_id == row.workspace_id)
        .first()
    )
    if run is None:
        raise PermanentDispatchError("dispatch Run no longer exists")
    if row.event_type == TRIGGER_RUN:
        source = durable_initial_dispatch_source(run)
        if source is None:
            raise PermanentDispatchError("trigger dispatch Run has no durable initial claim")
        if str(row.source_id or "") != source:
            raise PermanentDispatchError("trigger dispatch does not match the Run claim")
        if run.status in _TERMINAL_RUN_STATUSES:
            raise ObsoleteDispatch("trigger Run is already terminal")
        if run.status not in {"pending", "running"}:
            raise ObsoleteDispatch("trigger Run no longer accepts initial dispatch")
    if row.event_type in {SUBFLOW_HITL_RESUME, RUN_HITL_RESUME}:
        decision = (
            db.query(Decision)
            .filter(
                Decision.id == row.decision_id,
                Decision.scope == "run",
                or_(
                    Decision.workspace_id == row.workspace_id,
                    Decision.workspace_id.is_(None),
                ),
            )
            .first()
        )
        if decision is None or not decision.target_id:
            raise PermanentDispatchError("HITL dispatch Decision no longer exists")
        target = (
            db.query(Run)
            .filter(
                Run.id == decision.target_id,
                Run.workspace_id == row.workspace_id,
            )
            .first()
        )
        if target is None:
            raise PermanentDispatchError("HITL Decision target is outside the workspace")
        current = target
        visited = {current.id}
        while current.id != run.id and current.parent_run_id:
            current = (
                db.query(Run)
                .filter(
                    Run.id == current.parent_run_id,
                    Run.workspace_id == row.workspace_id,
                )
                .first()
            )
            if current is None or current.id in visited:
                break
            visited.add(current.id)
        if current is None or current.id != run.id:
            raise PermanentDispatchError("HITL Decision target is outside the Run lineage")
        if decision.status not in _RESOLVED_DECISION_STATUSES:
            raise DispatchNotReady("HITL Decision is not resolved")
        if run.status in _TERMINAL_RUN_STATUSES:
            raise ObsoleteDispatch("HITL Run is already terminal")
        pause = next(
            (
                checkpoint
                for checkpoint in reversed(list(run.checkpoints or []))
                if isinstance(checkpoint, dict) and checkpoint.get("kind") == "hitl_pause"
            ),
            None,
        )
        if str((pause or {}).get("decision_id") or "") != decision.id:
            raise ObsoleteDispatch("HITL Decision is no longer the active pause")
        plane = next(
            (
                checkpoint.get("plane")
                for checkpoint in reversed(list(run.checkpoints or []))
                if isinstance(checkpoint, dict)
                and checkpoint.get("kind") == "hitl_resume_dispatch"
                and str(checkpoint.get("decision_id") or "") == decision.id
            ),
            None,
        )
        expected_plane = (
            "subflow_celery" if row.event_type == SUBFLOW_HITL_RESUME else "run_celery"
        )
        if plane != expected_plane:
            raise PermanentDispatchError("HITL dispatch plane does not match the event")
        if row.event_type == SUBFLOW_HITL_RESUME and run.delegation_deadline_at is not None:
            parent, _entry, _meta = _active_delegation_envelope(
                db,
                child=run,
                workspace_id=row.workspace_id,
            )
            if parent.status in _TERMINAL_RUN_STATUSES:
                raise ObsoleteDispatch("delegated HITL parent is already terminal")
            approved_at = _utc_naive(decision.approved_at)
            deadline = _utc_naive(run.delegation_deadline_at)
            if approved_at is None or approved_at > deadline:
                # The watchdog owns expiry. Publishing a late human response
                # first would let broker timing change the authoritative
                # deadline outcome.
                raise ObsoleteDispatch("delegated HITL Decision missed its deadline")
        elif row.event_type == SUBFLOW_HITL_RESUME:
            parent, _entry, _meta = _active_delegation_envelope(
                db,
                child=run,
                workspace_id=row.workspace_id,
            )
            if parent.status in _TERMINAL_RUN_STATUSES:
                raise ObsoleteDispatch("delegated HITL parent is already terminal")
    if row.event_type == SUBFLOW_RUN:
        parent, _entry, meta = _active_delegation_envelope(
            db,
            child=run,
            workspace_id=row.workspace_id,
        )
        if run.status not in {"pending", "running"}:
            raise ObsoleteDispatch("delegated child no longer needs initial dispatch")
        if parent.status in _TERMINAL_RUN_STATUSES:
            raise ObsoleteDispatch("delegated child parent is already terminal")
        if parent.status != "waiting_subflows":
            raise ObsoleteDispatch("delegated child parent no longer awaits this wave")
        if not _wave_ids_equal(row.wave_id, meta.get("wave_id")):
            raise ObsoleteDispatch("initial dispatch belongs to a stale fan-out wave")
        deadline = run.delegation_deadline_at
        if deadline is not None:
            remaining = max(0.0, (deadline - datetime.utcnow()).total_seconds())
            soft_limit = max(1, int(math.ceil(remaining)))
            options.update(soft_time_limit=soft_limit, time_limit=soft_limit + 5)
    elif row.event_type == SUBFLOW_PARENT_RESUME:
        if not row.source_id:
            raise PermanentDispatchError("parent resume has no source child")
        child = (
            db.query(Run)
            .filter(
                Run.id == row.source_id,
                Run.workspace_id == row.workspace_id,
                Run.parent_run_id == run.id,
            )
            .first()
        )
        if child is None:
            raise PermanentDispatchError("parent resume source child no longer exists")
        try:
            parent, _entry, meta = _active_delegation_envelope(
                db,
                child=child,
                workspace_id=row.workspace_id,
            )
        except PermanentDispatchError:
            if not _watchdog_quarantine_attested(child):
                raise
            # The watchdog may quarantine a child precisely because its local
            # envelope was lost. A matching active parent claim plus the
            # stable quarantine checkpoint is sufficient to wake that parent;
            # no normal child execution is authorised through this path.
            parent, _entry, meta = _active_parent_claim_envelope(
                db,
                child=child,
                workspace_id=row.workspace_id,
            )
        if parent.id != run.id:
            raise PermanentDispatchError("parent resume Run does not own its source child")
        if run.status in _TERMINAL_RUN_STATUSES:
            raise ObsoleteDispatch("subflow parent is already terminal")
        if run.status not in {"waiting_subflows", "running"}:
            raise ObsoleteDispatch("subflow parent no longer awaits a resume")
        if not _wave_ids_equal(row.wave_id, meta.get("wave_id")):
            raise ObsoleteDispatch("parent resume belongs to a stale fan-out wave")
        if child.status not in _TERMINAL_RUN_STATUSES:
            raise DispatchNotReady("parent resume source child is not terminal")
    return task_name, args, options


def publish_claimed_dispatch(
    db: DBSession,
    *,
    outbox_id: str,
    lease_token: str,
) -> str:
    """Publish one leased row and durably settle or retry it."""

    row = (
        db.query(RunDispatchOutbox)
        .filter(
            RunDispatchOutbox.id == outbox_id,
            RunDispatchOutbox.state == "leased",
            RunDispatchOutbox.lease_token == lease_token,
        )
        .first()
    )
    if row is None or (
        row.lease_expires_at is not None and row.lease_expires_at <= datetime.utcnow()
    ):
        db.rollback()
        raise DispatchLeaseLost(f"dispatch lease lost for outbox row {outbox_id}")
    try:
        task_name, args, options = _task_envelope(db, row)
        expected_task_id = row.task_id
        # The broker call must not hold a database row lock or transaction. A
        # publisher crash is recovered through lease expiry and a duplicate of
        # this same deterministic task id.
        db.rollback()
        from app.workers.celery_app import celery_app

        result = celery_app.send_task(task_name, args=args, kwargs={}, **options)
        result_id = str(getattr(result, "id", "") or "")
        if result_id != expected_task_id:
            raise RuntimeError("broker returned a different Celery task id")
    except ObsoleteDispatch:
        mark_dispatch_cancelled(
            db,
            outbox_id=outbox_id,
            lease_token=lease_token,
            reason="dispatch superseded by authoritative Run state",
        )
        raise
    except PermanentDispatchError:
        mark_dispatch_dead(
            db,
            outbox_id=outbox_id,
            lease_token=lease_token,
            error="invalid dispatch envelope",
        )
        raise
    except Exception as exc:
        mark_dispatch_retry(
            db,
            outbox_id=outbox_id,
            lease_token=lease_token,
            # Transport errors can embed broker URLs (and credentials). The
            # durable row records only a safe class; detailed diagnostics stay
            # in process logs with the platform's normal redaction policy.
            error=type(exc).__name__,
        )
        raise
    mark_dispatch_published(db, outbox_id=outbox_id, lease_token=lease_token)
    return expected_task_id


def repair_dispatch_gaps(
    db: DBSession,
    *,
    limit: int = 200,
) -> dict[str, int]:
    """Derive missing messages from authoritative persisted Run state.

    The scan intentionally ignores current feature flags.  An execution plane
    already snapshotted as Celery must drain after a kill-switch change.
    """

    ensured = {event_type: 0 for event_type in DISPATCH_EVENT_TYPES}
    if limit <= 0:
        return ensured
    experience_recovery_before = datetime.utcnow() - timedelta(
        seconds=_EXPERIENCE_RECOVERY_GRACE_SECONDS
    )
    trigger_dispatch_exists = (
        db.query(RunDispatchOutbox.id)
        .filter(
            RunDispatchOutbox.event_type == TRIGGER_RUN,
            RunDispatchOutbox.workspace_id == Run.workspace_id,
            RunDispatchOutbox.run_id == Run.id,
        )
        .exists()
    )
    trigger_candidates = (
        db.query(Run)
        .filter(
            Run.workspace_id.isnot(None),
            or_(
                and_(
                    Run.trigger == "webhook",
                    Run.trigger_dedup_key.isnot(None),
                ),
                and_(
                    Run.trigger == "manual",
                    Run.started_at <= experience_recovery_before,
                    Run.experience_idempotency_key.isnot(None),
                    Run.trigger_dedup_key.isnot(None),
                    Run.input_ref["_ingress"]["adapter"]["surface"].as_string()
                    == "experience",
                ),
            ),
            Run.status.in_(("pending", "running")),
            ~trigger_dispatch_exists,
        )
        .order_by(Run.started_at, Run.id)
        .limit(max(limit * 4, limit))
        .all()
    )
    for run in trigger_candidates:
        source = durable_initial_dispatch_source(run)
        if source is None:
            continue
        enqueue_dispatch(
            db,
            event_type=TRIGGER_RUN,
            workspace_id=str(run.workspace_id),
            run_id=run.id,
            source_id=source,
        )
        ensured[TRIGGER_RUN] += 1
        if ensured[TRIGGER_RUN] >= limit:
            break
    initial_dispatch_exists = (
        db.query(RunDispatchOutbox.id)
        .filter(
            RunDispatchOutbox.event_type == SUBFLOW_RUN,
            RunDispatchOutbox.workspace_id == Run.workspace_id,
            RunDispatchOutbox.run_id == Run.id,
        )
        .exists()
    )
    parent_resume_exists = (
        db.query(RunDispatchOutbox.id)
        .filter(
            RunDispatchOutbox.event_type == SUBFLOW_PARENT_RESUME,
            RunDispatchOutbox.workspace_id == Run.workspace_id,
            RunDispatchOutbox.run_id == Run.parent_run_id,
            RunDispatchOutbox.source_id == Run.id,
        )
        .exists()
    )
    repair_parent = aliased(Run, name="dispatch_repair_parent")
    repair_parent_entry = repair_parent.waiting_subflows.op("->")(
        Run.delegation_key,
    )
    dialect = db.get_bind().dialect.name
    if dialect not in {"postgresql", "sqlite"}:
        raise RuntimeError(
            f"dispatch gap repair does not support database dialect {dialect!r}"
        )
    parent_wave_json = repair_parent.waiting_subflows["_meta"].op("->")(
        "wave_id"
    )
    entry_wave_json = repair_parent_entry.op("->")("wave_id")
    parent_wave_scalar = repair_parent.waiting_subflows["_meta"].op("->>")(
        "wave_id"
    )
    entry_wave_scalar = repair_parent_entry.op("->>")("wave_id")
    # ``->>`` alone erases JSON scalar types (1 and "1" both become text
    # "1").  Cast the ``->`` JSON representation so the SQL candidate set is
    # no broader than the Python envelope validator.
    parent_wave_typed = cast(
        parent_wave_json,
        String,
    )
    entry_wave_typed = cast(
        entry_wave_json,
        String,
    )
    if dialect == "postgresql":
        parent_wave_is_canonical = and_(
            func.json_typeof(parent_wave_json) == "number",
            parent_wave_scalar.op("~")(r"^(0|[1-9][0-9]*)$"),
        )
        entry_wave_is_canonical = and_(
            func.json_typeof(entry_wave_json) == "number",
            entry_wave_scalar.op("~")(r"^(0|[1-9][0-9]*)$"),
        )
    else:
        parent_wave_is_canonical = and_(
            func.json_type(parent_wave_json) == "integer",
            cast(parent_wave_scalar, Integer) >= 0,
        )
        entry_wave_is_canonical = and_(
            func.json_type(entry_wave_json) == "integer",
            cast(entry_wave_scalar, Integer) >= 0,
        )
    child_celery_claim = (
        Run.input_ref["_delegation"]["execution_plane"].as_string() == "celery"
    )
    child_parent_claim = (
        Run.input_ref["_delegation"]["parent_run_id"].as_string()
        == Run.parent_run_id
    )
    parent_celery_claim = and_(
        repair_parent.id.isnot(None),
        repair_parent.waiting_subflows["_meta"]["execution_plane"].as_string()
        == "celery",
        repair_parent_entry.op("->>")("child_run_id") == Run.id,
        or_(
            parent_wave_scalar.is_(None),
            and_(
                parent_wave_is_canonical,
                entry_wave_is_canonical,
                entry_wave_typed == parent_wave_typed,
            ),
        ),
    )
    active_parent_celery_claim = and_(
        repair_parent.status == "waiting_subflows",
        parent_celery_claim,
    )
    strict_delegation_claim = and_(
        child_celery_claim,
        child_parent_claim,
        active_parent_celery_claim,
        func.coalesce(repair_parent_entry.op("->>")("node_id"), "")
        == func.coalesce(Run.delegation_node_id, ""),
        func.coalesce(repair_parent_entry.op("->>")("branch"), "")
        == func.coalesce(Run.delegation_branch, ""),
    )
    watchdog_quarantine_claim = and_(
        Run.status == "failed",
        Run.error == "subflow_hitl_watchdog_invalid_state",
        Run.delegation_quarantined_at.isnot(None),
        active_parent_celery_claim,
    )
    candidate_query = (
        db.query(Run)
        .outerjoin(
            repair_parent,
            and_(
                repair_parent.id == Run.parent_run_id,
                repair_parent.workspace_id == Run.workspace_id,
            ),
        )
        .filter(
            Run.parent_run_id.isnot(None),
            Run.delegation_key.isnot(None),
            or_(
                and_(
                    Run.status == "pending",
                    strict_delegation_claim,
                    ~initial_dispatch_exists,
                ),
                and_(
                    Run.status.in_(_TERMINAL_RUN_STATUSES),
                    or_(strict_delegation_claim, watchdog_quarantine_claim),
                    ~parent_resume_exists,
                ),
            ),
        )
    )
    # ``limit`` bounds repaired gaps, not merely inspected rows.  The SQL
    # predicate mirrors the strict/weak authoritative envelopes so durable
    # malformed rows are excluded before pagination; a hard scan cap also
    # keeps one maintenance tick finite under concurrent mutations.
    scan_batch_size = max(64, min(1000, limit * 4))
    max_scanned = max(256, min(8000, limit * 8))
    scanned = 0
    cursor: tuple[datetime, str] | None = None
    repaired_subflow_gaps = 0
    while repaired_subflow_gaps < limit:
        page_query = candidate_query
        if cursor is not None:
            cursor_started_at, cursor_id = cursor
            page_query = page_query.filter(
                or_(
                    Run.started_at > cursor_started_at,
                    and_(
                        Run.started_at == cursor_started_at,
                        Run.id > cursor_id,
                    ),
                )
            )
        candidates = (
            page_query.order_by(Run.started_at, Run.id)
            .limit(scan_batch_size)
            .all()
        )
        if not candidates:
            break
        for child in candidates:
            cursor = (child.started_at, child.id)
            scanned += 1
            delegation = (
                ((child.input_ref or {}).get("_delegation") or {})
                if isinstance(child.input_ref, dict)
                else {}
            )
            if not child.workspace_id:
                continue
            try:
                if child.status in _TERMINAL_RUN_STATUSES and _watchdog_quarantine_attested(
                    child
                ):
                    parent, _entry, parent_meta = _active_parent_claim_envelope(
                        db,
                        child=child,
                        workspace_id=str(child.workspace_id),
                    )
                else:
                    parent, _entry, parent_meta = _active_delegation_envelope(
                        db,
                        child=child,
                        workspace_id=str(child.workspace_id),
                    )
            except (PermanentDispatchError, ObsoleteDispatch):
                continue
            wave_id = parent_meta.get("wave_id")
            if child.delegation_deadline_at is None and delegation.get("deadline_at"):
                try:
                    child.delegation_deadline_at = datetime.fromisoformat(
                        str(delegation["deadline_at"]).replace("Z", "+00:00")
                    ).replace(tzinfo=None)
                except (TypeError, ValueError):
                    pass
            if child.status == "pending" and parent.status == "waiting_subflows":
                enqueue_dispatch(
                    db,
                    event_type=SUBFLOW_RUN,
                    workspace_id=str(child.workspace_id),
                    run_id=child.id,
                    source_id=child.delegation_key,
                    wave_id=wave_id,
                )
                ensured[SUBFLOW_RUN] += 1
                repaired_subflow_gaps += 1
            elif (
                child.status in _TERMINAL_RUN_STATUSES
                and parent.status == "waiting_subflows"
            ):
                enqueue_dispatch(
                    db,
                    event_type=SUBFLOW_PARENT_RESUME,
                    workspace_id=str(parent.workspace_id),
                    run_id=parent.id,
                    source_id=child.id,
                    wave_id=wave_id,
                )
                ensured[SUBFLOW_PARENT_RESUME] += 1
                repaired_subflow_gaps += 1
            if repaired_subflow_gaps >= limit:
                break
            if scanned >= max_scanned:
                break
        if len(candidates) < scan_batch_size or scanned >= max_scanned:
            break

    hitl_dispatch_exists = (
        db.query(RunDispatchOutbox.id)
        .filter(
            RunDispatchOutbox.event_type.in_((SUBFLOW_HITL_RESUME, RUN_HITL_RESUME)),
            RunDispatchOutbox.decision_id == Decision.id,
        )
        .exists()
    )
    paused = (
        db.query(Decision, Run)
        .join(
            Run,
            and_(
                Decision.scope == "run",
                Decision.target_id == Run.id,
                or_(
                    Decision.workspace_id == Run.workspace_id,
                    Decision.workspace_id.is_(None),
                ),
            ),
        )
        .filter(
            Run.status == "hitl_pending",
            Decision.status.in_(_RESOLVED_DECISION_STATUSES),
            Decision.approved_at.isnot(None),
            ~hitl_dispatch_exists,
        )
        .order_by(Decision.approved_at, Run.started_at)
        .limit(limit)
        .all()
    )
    for decision, target in paused:
        # In-process descendants copy their pause through each ancestor. The
        # durable continuation belongs to the outermost paused ancestor that
        # carries the same Decision, not necessarily Decision.target_id.
        run = target
        visited = {run.id}
        while run.parent_run_id:
            parent = (
                db.query(Run)
                .filter(
                    Run.id == run.parent_run_id,
                    Run.workspace_id == target.workspace_id,
                )
                .first()
            )
            if parent is None or parent.id in visited or parent.status != "hitl_pending":
                break
            parent_pause = next(
                (
                    value
                    for value in reversed(list(parent.checkpoints or []))
                    if isinstance(value, dict) and value.get("kind") == "hitl_pause"
                ),
                None,
            )
            if str((parent_pause or {}).get("decision_id") or "") != decision.id:
                break
            visited.add(parent.id)
            run = parent
        checkpoints = [value for value in (run.checkpoints or []) if isinstance(value, dict)]
        pause = next(
            (value for value in reversed(checkpoints) if value.get("kind") == "hitl_pause"),
            None,
        )
        if pause is None or not pause.get("decision_id"):
            continue
        decision_id = str(pause["decision_id"])
        plane = next(
            (
                value.get("plane")
                for value in reversed(checkpoints)
                if value.get("kind") == "hitl_resume_dispatch"
                and str(value.get("decision_id") or "") == decision_id
            ),
            None,
        )
        event_type = {
            "subflow_celery": SUBFLOW_HITL_RESUME,
            "run_celery": RUN_HITL_RESUME,
        }.get(str(plane or ""))
        if event_type is None:
            continue
        if not run.workspace_id:
            continue
        if decision.id != decision_id:
            continue
        if event_type == SUBFLOW_HITL_RESUME and run.delegation_deadline_at is not None:
            approved_at = _utc_naive(decision.approved_at)
            deadline = _utc_naive(run.delegation_deadline_at)
            if approved_at is None or approved_at > deadline:
                # Leave late resolutions to the deadline watchdog, which will
                # fail the child and enqueue the parent continuation.
                continue
        enqueue_dispatch(
            db,
            event_type=event_type,
            workspace_id=str(run.workspace_id),
            run_id=run.id,
            decision_id=decision_id,
        )
        ensured[event_type] += 1
    return ensured


def reconcile_dispatch_outbox(
    *,
    batch_size: int = 50,
    lease_seconds: int = 60,
) -> dict[str, Any]:
    """Run one bounded repair/claim/publish tick using an internal session."""

    with SessionLocal() as db:
        repaired = repair_dispatch_gaps(db, limit=max(batch_size * 4, batch_size))
        db.commit()
        claimed = claim_dispatch_batch(
            db,
            batch_size=batch_size,
            lease_seconds=lease_seconds,
        )
        leases = [(row.id, str(row.lease_token)) for row in claimed]

    published = 0
    retried = 0
    dead = 0
    cancelled = 0
    for outbox_id, lease_token in leases:
        with SessionLocal() as db:
            try:
                publish_claimed_dispatch(
                    db,
                    outbox_id=outbox_id,
                    lease_token=lease_token,
                )
                published += 1
            except ObsoleteDispatch:
                cancelled += 1
            except PermanentDispatchError:
                dead += 1
                logger.error(
                    "dispatch_outbox: invalid durable envelope",
                    outbox_id=outbox_id,
                )
            except DispatchLeaseLost:
                # Another owner recovered an expired lease; its result wins.
                continue
            except Exception as exc:
                retried += 1
                logger.warning(
                    "dispatch_outbox: broker publication deferred",
                    outbox_id=outbox_id,
                    error_type=type(exc).__name__,
                )
    return {
        "repaired": repaired,
        "claimed": len(leases),
        "published": published,
        "retried": retried,
        "dead": dead,
        "cancelled": cancelled,
    }
