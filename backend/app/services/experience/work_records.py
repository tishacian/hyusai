"""Work record attempts: which Runs a Work record received, in order.

A binding that declares a record identity (namespace + input field) links each
Run it starts to the record reference found in the payload. Rows are appended,
never replaced, and always read back per user: a reader sees the attempts they
started, which is the same visibility rule as the last-result lookup.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Optional
from uuid import uuid4

from sqlalchemy.orm import Session as DBSession

from app.models.run import Run
from app.models.work_record_run import WorkRecordRun
from app.services.experience.bindings import record_ref_from_payload

MAX_PAGE = 50


def record_work_attempt(
    db: DBSession,
    *,
    workspace_id: str,
    experience_id: str,
    snapshot: Mapping[str, Any],
    payload: Any,
    run: Run,
    user_id: Optional[str],
) -> Optional[WorkRecordRun]:
    """Append the Run to its record's attempts when the binding declares an
    identity and the payload carries a reference. Returns the row or None."""
    identity = snapshot.get("record_identity")
    if not isinstance(identity, Mapping):
        return None
    record_ref = record_ref_from_payload(identity, payload)
    if record_ref is None:
        return None
    row = WorkRecordRun(
        id=str(uuid4()),
        workspace_id=workspace_id,
        experience_id=experience_id,
        binding_key=str(snapshot.get("binding_key") or ""),
        record_namespace=str(identity["namespace"]),
        record_ref=record_ref,
        run_id=run.id,
        initiated_by_user_id=user_id,
        created_at=datetime.utcnow(),
    )
    db.add(row)
    db.flush()
    return row


def record_attempts_page(
    db: DBSession,
    *,
    workspace_id: str,
    experience_id: str,
    namespace: str,
    record_ref: str,
    user_id: Optional[str],
    limit: int,
    offset: int,
) -> tuple[list[tuple[WorkRecordRun, Run]], bool]:
    """Newest first, this reader's own attempts only, with one extra row
    fetched to say whether a next page exists."""
    size = max(1, min(int(limit), MAX_PAGE))
    rows = (
        db.query(WorkRecordRun, Run)
        .join(Run, Run.id == WorkRecordRun.run_id)
        .filter(
            WorkRecordRun.workspace_id == workspace_id,
            WorkRecordRun.experience_id == experience_id,
            WorkRecordRun.record_namespace == namespace,
            WorkRecordRun.record_ref == record_ref,
            WorkRecordRun.initiated_by_user_id == user_id,
            Run.workspace_id == workspace_id,
        )
        .order_by(WorkRecordRun.created_at.desc(), WorkRecordRun.id.desc())
        .offset(max(0, int(offset)))
        .limit(size + 1)
        .all()
    )
    return rows[:size], len(rows) > size
