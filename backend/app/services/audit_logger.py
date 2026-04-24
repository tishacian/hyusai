"""In-process audit log emission helper.

``POST /api/v1/audit`` is the HTTP surface for audit events — but it
requires a request context (``Depends(get_current_user)``) which is
unavailable from background workers, subservices and migrations. This
helper gives those call-sites a one-liner to persist an
:class:`~app.models.audit.AuditLog` row directly.

Design notes:
- **Own session.** Callers coming from a background task shouldn't
  share the request-scoped ``Session`` (it's closed, or about to be).
  Pass ``db=None`` (default) and we open a fresh ``SessionLocal`` +
  commit + close; pass ``db=...`` explicitly only when you're inside
  a request and want to join the already-open unit of work.
- **Non-critical path.** Any exception is swallowed + logged. An audit
  write failure must never cascade into the business operation the
  caller was executing (e.g. a successful SharePoint sync shouldn't be
  marked ``failed`` just because the audit commit tripped a race).
- **Event naming.** Dotted lowercase, ``<domain>.<entity>.<action>``
  (see ``docs/vague-e-plan.md`` scope commun E4 — ``sharepoint.sync.*``,
  ``sharepoint.session.*``). The helper doesn't enforce this; up to
  callers to stay consistent.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session as DBSession

from app.db.base import SessionLocal
from app.models.audit import AuditLog

logger = logging.getLogger(__name__)


def emit_audit_event(
    *,
    workspace_id: Optional[str],
    event_type: str,
    actor: str,
    details: Optional[Dict[str, Any]] = None,
    trace_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    severity: str = "info",
    db: Optional[DBSession] = None,
) -> Optional[str]:
    """Persist an ``AuditLog`` row.

    :returns: the row id on success, ``None`` on failure (errors are
        swallowed so business flows aren't interrupted by audit hiccups).
    """
    owns_session = db is None
    session: DBSession = db or SessionLocal()
    try:
        entry = AuditLog(
            id=str(uuid.uuid4()),
            workspace_id=workspace_id,
            timestamp=datetime.utcnow(),
            event_type=event_type,
            actor=actor or "system",
            details=details or {},
            trace_id=trace_id,
            agent_id=agent_id,
            severity=severity,
        )
        session.add(entry)
        if owns_session:
            session.commit()
        else:
            # Caller flushes/commits in their own transaction. Flush so
            # they see the row via queries within their unit of work.
            session.flush()
        return entry.id
    except Exception:  # noqa: BLE001 — audit is best-effort
        logger.exception(
            "Failed to emit audit event event_type=%s workspace_id=%s",
            event_type,
            workspace_id,
        )
        if owns_session:
            try:
                session.rollback()
            except Exception:  # noqa: BLE001
                pass
        return None
    finally:
        if owns_session:
            session.close()
