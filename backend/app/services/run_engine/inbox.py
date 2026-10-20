"""Run inbox + SystemMemory — buffer correlated events while a gate waits.

Correlation strategy
--------------------
1. Target System: events are scoped to a ``system_id`` (webhook hook, SFTP
   registry match, etc.).
2. Optional correlation key extracted from the event payload, in order:
   ``correlation_key``, ``correlation_id``, ``transaction_id``.
3. A paused or running AgentLoop Run matches only with the same explicit
   correlation key and the target System's workspace. An absent key or a
   different key never selects an unrelated waiting Run.
4. When exactly one match exists, the event is **buffered** into ``run_inbox`` (and
   merged into ``system_memory``) instead of dispatching a new Run —
   “collect transactions while the gate waits”.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any, Optional
from uuid import uuid4

from sqlalchemy.orm import Session as DBSession

from app.core.logging import get_logger
from app.models.run import Run
from app.models.run_inbox import RunInbox
from app.models.system import System
from app.models.system_memory import SystemMemory

logger = get_logger(__name__)

_LEGACY_DEFAULT_CORRELATION = "_default"


class InboxRoutingError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def extract_correlation_key(payload: Any) -> Optional[str]:
    """Pull a correlation key from a trigger / webhook payload."""
    if not isinstance(payload, dict):
        return None
    for key in ("correlation_key", "correlation_id", "transaction_id"):
        value = payload.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    nested = payload.get("_correlation")
    if isinstance(nested, dict):
        return extract_correlation_key(nested)
    if isinstance(nested, str) and nested.strip():
        return nested.strip()
    return None


def run_correlation_key(run: Run) -> Optional[str]:
    """Correlation stamped on the Run at launch or on the HITL pause."""
    input_ref = run.input_ref if isinstance(run.input_ref, dict) else {}
    key = extract_correlation_key(input_ref)
    if key:
        return key
    for cp in reversed(list(run.checkpoints or [])):
        if not isinstance(cp, dict) or cp.get("kind") != "hitl_pause":
            continue
        stamped = cp.get("correlation_key")
        if stamped is not None and str(stamped).strip():
            return str(stamped).strip()
        state = cp.get("state") if isinstance(cp.get("state"), dict) else {}
        ctx = state.get("ctx") if isinstance(state.get("ctx"), dict) else {}
        key = extract_correlation_key(ctx) or extract_correlation_key(
            (state.get("pool") or {}).get("run") if isinstance(state.get("pool"), dict) else {}
        )
        if key:
            return key
    return None


def find_running_agent_loop_runs(
    db: DBSession,
    *,
    system_id: str,
    correlation_key: Optional[str] = None,
) -> list[Run]:
    """Running AgentLoop runs that can absorb a mid-flight steer / event."""

    from app.services.run_engine.agent_loop import run_has_agent_loop

    system = db.get(System, system_id)
    if not correlation_key or system is None:
        return []
    running = (
        db.query(Run)
        .filter(
            Run.system_id == system_id,
            Run.workspace_id == system.workspace_id,
            Run.status == "running",
        )
        .order_by(Run.started_at.desc())
        .all()
    )
    return [
        row
        for row in running
        if run_has_agent_loop(row) and run_correlation_key(row) == correlation_key
    ]


def find_paused_runs_for_event(
    db: DBSession,
    *,
    system_id: str,
    correlation_key: Optional[str] = None,
) -> list[Run]:
    """Return ``hitl_pending`` Runs that should buffer this event."""
    system = db.get(System, system_id)
    if not correlation_key or system is None:
        return []
    paused = (
        db.query(Run)
        .filter(
            Run.system_id == system_id,
            Run.workspace_id == system.workspace_id,
            Run.status == "hitl_pending",
        )
        .order_by(Run.started_at.desc())
        .all()
    )
    return [row for row in paused if run_correlation_key(row) == correlation_key]


def upsert_system_memory(
    db: DBSession,
    *,
    workspace_id: Optional[str],
    system_id: str,
    correlation_key: str,
    event_kind: str,
    payload: dict[str, Any],
) -> Optional[SystemMemory]:
    """Merge an inbound event into durable SystemMemory state."""
    if not workspace_id or not system_id or not correlation_key:
        return None
    row = (
        db.query(SystemMemory)
        .filter(
            SystemMemory.workspace_id == workspace_id,
            SystemMemory.system_id == system_id,
            SystemMemory.correlation_key == correlation_key,
        )
        .first()
    )
    now = datetime.utcnow()
    event_entry = {
        "t": now.isoformat(),
        "event_kind": event_kind,
        "payload": payload if isinstance(payload, dict) else {"value": payload},
    }
    if row is None:
        state = {
            "events": [event_entry],
            "latest": event_entry.get("payload"),
            "event_count": 1,
            "last_event_kind": event_kind,
        }
        row = SystemMemory(
            id=str(uuid4()),
            workspace_id=workspace_id,
            system_id=system_id,
            correlation_key=correlation_key,
            state=state,
            version=1,
            created_at=now,
            updated_at=now,
        )
        db.add(row)
    else:
        state = dict(row.state or {})
        events = list(state.get("events") or [])
        events.append(event_entry)
        # Cap retained event log to keep JSON bounded.
        state["events"] = events[-100:]
        state["latest"] = event_entry.get("payload")
        state["event_count"] = int(state.get("event_count") or 0) + 1
        state["last_event_kind"] = event_kind
        row.state = state
        row.version = int(row.version or 0) + 1
        row.updated_at = now
    return row


def buffer_event_for_paused_run(
    db: DBSession,
    run: Run,
    *,
    event_kind: str,
    payload: dict[str, Any],
    correlation_key: Optional[str] = None,
) -> RunInbox:
    """Persist one inbox row and update SystemMemory for the paused Run."""
    corr = correlation_key or extract_correlation_key(payload) or run_correlation_key(run)
    if not corr:
        raise InboxRoutingError("INBOX_CORRELATION_REQUIRED")
    if corr == _LEGACY_DEFAULT_CORRELATION:
        raise InboxRoutingError("INBOX_CORRELATION_RESERVED")
    row = RunInbox(
        id=str(uuid4()),
        run_id=run.id,
        workspace_id=run.workspace_id,
        system_id=run.system_id,
        event_kind=event_kind,
        correlation_key=corr,
        payload=payload if isinstance(payload, dict) else {"value": payload},
        received_at=datetime.utcnow(),
    )
    db.add(row)
    upsert_system_memory(
        db,
        workspace_id=run.workspace_id,
        system_id=str(run.system_id or ""),
        correlation_key=corr,
        event_kind=event_kind,
        payload=payload if isinstance(payload, dict) else {"value": payload},
    )
    # Surface a lightweight checkpoint so the cockpit can show activity.
    run.checkpoints = [
        *(run.checkpoints or []),
        {
            "kind": "run_inbox_buffered",
            "t": row.received_at.isoformat(),
            "event_kind": event_kind,
            "correlation_key": corr,
            "inbox_id": row.id,
        },
    ]
    # Transaction ownership belongs to the event emitter.  In particular the
    # secure-deposit hooks call this service inside their own business
    # transaction; committing here would make a partial staging/promotion
    # durable before its caller has completed.
    db.flush()
    logger.info(
        "inbox: buffered event for paused run",
        run_id=run.id,
        event_kind=event_kind,
        correlation_key=corr,
    )
    return row


def try_buffer_event(
    db: DBSession,
    *,
    system_id: str,
    event_kind: str,
    payload: dict[str, Any],
    workspace_id: str | None = None,
    before_buffer: Callable[[Run], None] | None = None,
) -> Optional[dict[str, Any]]:
    """If a matching paused run exists, buffer and return a result dict.

    Returns ``None`` when no paused run matches (caller should dispatch normally).
    """
    corr = extract_correlation_key(payload)
    if not corr:
        return None
    if corr == _LEGACY_DEFAULT_CORRELATION:
        raise InboxRoutingError("INBOX_CORRELATION_RESERVED")
    system = db.get(System, system_id)
    if system is None or (workspace_id is not None and system.workspace_id != workspace_id):
        raise InboxRoutingError("INBOX_WORKSPACE_MISMATCH")
    matched = [
        *find_paused_runs_for_event(db, system_id=system_id, correlation_key=corr),
        *find_running_agent_loop_runs(db, system_id=system_id, correlation_key=corr),
    ]
    if not matched:
        return None
    if len(matched) != 1:
        raise InboxRoutingError("INBOX_CORRELATION_AMBIGUOUS")
    target = matched[0]
    if before_buffer is not None:
        before_buffer(target)
    row = buffer_event_for_paused_run(
        db,
        target,
        event_kind=event_kind,
        payload=payload if isinstance(payload, dict) else {},
        correlation_key=corr,
    )
    return {
        "system_id": system_id,
        "status": "buffered",
        "run_id": target.id,
        "inbox_id": row.id,
        "correlation_key": corr,
    }


def inbox_count_for_run(db: DBSession, run_id: str) -> int:
    return db.query(RunInbox).filter(RunInbox.run_id == run_id).count()


def load_memory_for_run(db: DBSession, run: Run) -> Optional[SystemMemory]:
    """Latest SystemMemory row for this run's correlation context."""
    if not run.system_id or not run.workspace_id:
        return None
    corr = run_correlation_key(run)
    if not corr or corr == _LEGACY_DEFAULT_CORRELATION:
        # Historical "_default" rows remain auditable, but cannot silently
        # become context for another uncorrelated case.
        return None
    return (
        db.query(SystemMemory)
        .filter(
            SystemMemory.workspace_id == run.workspace_id,
            SystemMemory.system_id == run.system_id,
            SystemMemory.correlation_key == corr,
        )
        .first()
    )


def memory_pool_payload(memory: Optional[SystemMemory]) -> dict[str, Any]:
    """Shape injected into the walker pool as the ``memory`` namespace."""
    if memory is None:
        return {}
    state = memory.state if isinstance(memory.state, dict) else {}
    return {
        "correlation_key": memory.correlation_key,
        "version": memory.version,
        "updated_at": memory.updated_at.isoformat() if memory.updated_at else None,
        "state": state,
        "latest": state.get("latest"),
        "event_count": state.get("event_count") or 0,
        "last_event_kind": state.get("last_event_kind"),
    }


def reinject_memory_into_state(db: DBSession, run: Run, state) -> Optional[dict[str, Any]]:
    """Merge latest SystemMemory into ``state.pool`` / ``state.ctx`` on resume."""
    memory = load_memory_for_run(db, run)
    payload = memory_pool_payload(memory)
    if not payload:
        return None
    state.pool.set_namespace("memory", payload)
    state.ctx["memory"] = payload
    return payload
