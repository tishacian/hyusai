"""Rolling window version store for ``System.flow_definition`` — E3.1.

Keep the table simple, keep the semantics boring:

- Every ``PATCH /systems/{id}`` that mutates ``flow_definition`` lands
  a new row here via :func:`record_new_version`. ``version_number``
  auto-increments per system so the editor can display v1, v2, v3…
  without guessing.
- When the row count for a system exceeds
  ``settings.custom_chain_version_window`` (default 500, decision
  2026-04-24), the oldest ``version_number`` is purged FIFO.
- Rollback (:func:`rollback_to_version`) never rewrites history: it
  creates a *new* version whose ``flow_definition`` equals the target
  one. The editor renders "v42 — rolled back to v17" via
  ``rolled_back_from_id``.

Every mutation emits an audit event (``chain.version.created``,
``chain.version.purged``, ``chain.rollback``) with workspace/system/
version context but *not* the full ``flow_definition`` (too big for
the audit log, and the version row already holds it).

All public functions are pure with respect to HTTP: they take a
``Session`` and the minimum context they need, so the same service
is reusable from a BackgroundTask, a CLI, or a future Celery worker
without touching FastAPI internals.
"""
from __future__ import annotations

import copy
import json
import logging
from typing import Any, Dict, List, Mapping, Optional, Tuple
from uuid import uuid4

from sqlalchemy import desc
from sqlalchemy.orm import Session as DBSession

from app.core.config import settings
from app.models.system import System
from app.models.system_version import SystemVersion
from app.services.audit_logger import emit_audit_event


logger = logging.getLogger(__name__)


class ChainVersionError(Exception):
    """Raised when a rollback / lookup cannot be satisfied."""


def _next_version_number(db: DBSession, system_id: str) -> int:
    """Return the next ``version_number`` for a system (1-based)."""
    latest = (
        db.query(SystemVersion.version_number)
        .filter(SystemVersion.system_id == system_id)
        .order_by(desc(SystemVersion.version_number))
        .limit(1)
        .scalar()
    )
    return (latest or 0) + 1


def _flow_definitions_equal(a: Any, b: Any) -> bool:
    """Conservative structural equality on JSON-ish trees.

    We compare after ``json.dumps(sort_keys=True)`` so key ordering
    on nested dicts doesn't create false positives. Non-JSON-safe
    inputs fall back to ``repr`` equality which is looser but safe.
    """
    if a is b:
        return True
    try:
        return json.dumps(a, sort_keys=True, default=str) == json.dumps(
            b, sort_keys=True, default=str
        )
    except (TypeError, ValueError):  # pragma: no cover — defensive
        return repr(a) == repr(b)


def record_new_version(
    *,
    db: DBSession,
    system: System,
    flow_definition: Mapping[str, Any],
    created_by: str,
    message: Optional[str] = None,
    rolled_back_from_id: Optional[str] = None,
    audit_actor: Optional[str] = None,
) -> Optional[SystemVersion]:
    """Persist a new ``SystemVersion`` for this system and trim the
    rolling window. Commits on the caller's session (we only flush —
    the caller decides when to commit so we stay inside their
    transaction when embedded in a larger write).

    Returns the new version, or ``None`` if ``flow_definition`` is
    identical to the latest one on file (no-op save).
    """

    latest = (
        db.query(SystemVersion)
        .filter(SystemVersion.system_id == system.id)
        .order_by(desc(SystemVersion.version_number))
        .first()
    )

    if latest is not None and _flow_definitions_equal(latest.flow_definition, flow_definition):
        return None

    version = SystemVersion(
        id=str(uuid4()),
        system_id=system.id,
        workspace_id=system.workspace_id,
        version_number=_next_version_number(db, system.id),
        flow_definition=copy.deepcopy(dict(flow_definition)),
        message=message,
        rolled_back_from_id=rolled_back_from_id,
        created_by=created_by or "demo-user",
    )
    db.add(version)
    db.flush()

    purged_ids = _purge_window(db=db, system_id=system.id)

    emit_audit_event(
        workspace_id=system.workspace_id,
        event_type="chain.version.created",
        actor=audit_actor or created_by or "demo-user",
        details={
            "system_id": system.id,
            "version_id": version.id,
            "version_number": version.version_number,
            "rolled_back_from_id": rolled_back_from_id,
            "message_len": len(message) if message else 0,
        },
        # Reuse the caller's session so we stay inside their unit of
        # work (same transaction, same connection). Production doesn't
        # care (Postgres handles multi-session concurrency fine) but
        # SQLite serialises writes — opening a second SessionLocal
        # against the test DB while the caller still holds the write
        # lock produces "database is locked". ``emit_audit_event``
        # handles the reused-session path (flush-only, no commit).
        db=db,
    )

    if purged_ids:
        emit_audit_event(
            workspace_id=system.workspace_id,
            event_type="chain.version.purged",
            actor=audit_actor or "system",
            details={
                "system_id": system.id,
                "purged_count": len(purged_ids),
                "purged_ids": purged_ids,
                "window": settings.custom_chain_version_window,
            },
            db=db,
        )

    return version


def _purge_window(*, db: DBSession, system_id: str) -> List[str]:
    """Trim the oldest versions so the system stays within
    ``settings.custom_chain_version_window``. Return the ids of purged
    rows.
    """

    window = max(1, int(settings.custom_chain_version_window))
    total = (
        db.query(SystemVersion)
        .filter(SystemVersion.system_id == system_id)
        .count()
    )
    if total <= window:
        return []

    overflow = total - window
    to_purge = (
        db.query(SystemVersion)
        .filter(SystemVersion.system_id == system_id)
        .order_by(SystemVersion.version_number.asc())
        .limit(overflow)
        .all()
    )
    purged_ids = [v.id for v in to_purge]
    for v in to_purge:
        db.delete(v)
    db.flush()
    logger.info(
        "Purged %d SystemVersion rows for system %s (window=%d)",
        len(purged_ids),
        system_id,
        window,
    )
    return purged_ids


def list_versions(
    *,
    db: DBSession,
    system_id: str,
    workspace_id: Optional[str],
    limit: int = 100,
    offset: int = 0,
) -> Tuple[List[SystemVersion], int]:
    """Return ``(rows, total)`` for the given system, workspace-scoped.

    ``limit`` is hard-capped at 500 (the rolling window size) to make
    pagination trivial — callers that need more should implement their
    own pagination on top.
    """

    q = db.query(SystemVersion).filter(SystemVersion.system_id == system_id)
    if workspace_id is not None:
        q = q.filter(SystemVersion.workspace_id == workspace_id)
    total = q.count()
    rows = (
        q.order_by(desc(SystemVersion.version_number))
        .offset(max(0, int(offset)))
        .limit(max(1, min(500, int(limit))))
        .all()
    )
    return rows, total


def get_version(
    *,
    db: DBSession,
    system_id: str,
    workspace_id: Optional[str],
    version_number: int,
) -> Optional[SystemVersion]:
    q = db.query(SystemVersion).filter(
        SystemVersion.system_id == system_id,
        SystemVersion.version_number == int(version_number),
    )
    if workspace_id is not None:
        q = q.filter(SystemVersion.workspace_id == workspace_id)
    return q.first()


def rollback_to_version(
    *,
    db: DBSession,
    system: System,
    version_number: int,
    created_by: str,
    message: Optional[str] = None,
    audit_actor: Optional[str] = None,
) -> SystemVersion:
    """Roll the system back to ``version_number`` by creating a new
    version whose ``flow_definition`` equals that target. Also updates
    ``System.flow_definition`` in place so the run engine sees the
    rollback on its next read.

    Returns the newly created version row. Raises
    :class:`ChainVersionError` if the target doesn't exist (e.g. it
    was purged out of the rolling window, or it belongs to another
    workspace).
    """

    target = get_version(
        db=db,
        system_id=system.id,
        workspace_id=system.workspace_id,
        version_number=version_number,
    )
    if target is None:
        raise ChainVersionError(
            f"Version {version_number} not found for system {system.id!r} "
            "(possibly purged by the rolling window)."
        )

    new_version = record_new_version(
        db=db,
        system=system,
        flow_definition=target.flow_definition,
        created_by=created_by,
        message=message or f"Rolled back to v{target.version_number}",
        rolled_back_from_id=target.id,
        audit_actor=audit_actor,
    )
    # `record_new_version` returns None when the target flow is identical
    # to the current flow — in that case the rollback is a no-op but we
    # still want to signal it in the audit trail as a rollback intent.
    if new_version is None:
        emit_audit_event(
            workspace_id=system.workspace_id,
            event_type="chain.rollback",
            actor=audit_actor or created_by or "demo-user",
            details={
                "system_id": system.id,
                "target_version_number": target.version_number,
                "target_version_id": target.id,
                "no_op": True,
            },
            db=db,
        )
        return target

    # Keep System.flow_definition in sync so run engine sees the rollback.
    system.flow_definition = copy.deepcopy(dict(target.flow_definition))
    db.add(system)
    db.flush()

    emit_audit_event(
        workspace_id=system.workspace_id,
        event_type="chain.rollback",
        actor=audit_actor or created_by or "demo-user",
        details={
            "system_id": system.id,
            "target_version_number": target.version_number,
            "target_version_id": target.id,
            "new_version_number": new_version.version_number,
            "new_version_id": new_version.id,
            "no_op": False,
        },
        db=db,
    )

    return new_version


def serialize_version(version: SystemVersion) -> Dict[str, Any]:
    """Shape for API responses."""
    return {
        "id": version.id,
        "system_id": version.system_id,
        "workspace_id": version.workspace_id,
        "version_number": version.version_number,
        "flow_definition": version.flow_definition,
        "message": version.message,
        "rolled_back_from_id": version.rolled_back_from_id,
        "created_at": version.created_at.isoformat() if version.created_at else None,
        "created_by": version.created_by,
    }


def serialize_version_summary(version: SystemVersion) -> Dict[str, Any]:
    """Listing shape — drops the heavyweight ``flow_definition`` so the
    versions panel can stay snappy even with 500 rows.
    """
    flow = version.flow_definition or {}
    nodes = flow.get("nodes") if isinstance(flow, Mapping) else None
    edges = flow.get("edges") if isinstance(flow, Mapping) else None
    return {
        "id": version.id,
        "system_id": version.system_id,
        "version_number": version.version_number,
        "message": version.message,
        "rolled_back_from_id": version.rolled_back_from_id,
        "created_at": version.created_at.isoformat() if version.created_at else None,
        "created_by": version.created_by,
        "node_count": len(nodes) if isinstance(nodes, list) else 0,
        "edge_count": len(edges) if isinstance(edges, list) else 0,
    }
