"""Persistence helpers for ``meeting_decisions`` (Phase I).

Decisions logged via AYA's ``aya.log_decision`` action or via the
``/api/v1/meetings/{event_id}/decisions`` endpoint are kept here and never
leave the workspace boundary (workspace-scoped, audit-logged, advisory).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable, Optional
from uuid import uuid4

from sqlalchemy.orm import Session as DBSession

from app.models.meeting_decision import MeetingDecision
from app.models.user import User
from app.models.workspace import Workspace
from app.services.audit_logger import emit_audit_event


def _actor(user: Optional[User]) -> tuple[Optional[str], str]:
    if not user:
        return None, "Cabinet"
    label = (user.email or user.username or "VP")
    return user.id, label


def serialize_decision(decision: MeetingDecision) -> dict[str, Any]:
    return {
        "id": decision.id,
        "workspace_id": decision.workspace_id,
        "calendar_event_id": decision.calendar_event_id,
        "agenda_item_ref": decision.agenda_item_ref,
        "decided_at": decision.decided_at.isoformat() if decision.decided_at else None,
        "decided_by_user_id": decision.decided_by_user_id,
        "decided_by_label": decision.decided_by_label,
        "options_offered": list(decision.options_offered or []),
        "chosen_option": decision.chosen_option,
        "rationale": decision.rationale,
        "source_refs": list(decision.source_refs or []),
        "status": decision.status,
        "metadata": dict(decision.meta_data or {}),
    }


def log_decision_for_workspace(
    db: DBSession,
    workspace: Workspace,
    user: Optional[User],
    *,
    calendar_event_id: str,
    agenda_item_ref: str,
    options_offered: Iterable[dict[str, Any]],
    chosen_option: str,
    rationale: str,
    source_refs: Iterable[str],
    status: str = "logged",
    metadata: Optional[dict[str, Any]] = None,
) -> MeetingDecision:
    user_id, user_label = _actor(user)
    options_list = [dict(item) for item in options_offered]
    refs_list = [str(item) for item in source_refs]
    decision = MeetingDecision(
        id=str(uuid4()),
        workspace_id=workspace.id,
        calendar_event_id=str(calendar_event_id),
        agenda_item_ref=str(agenda_item_ref),
        decided_at=datetime.utcnow(),
        decided_by_user_id=user_id,
        decided_by_label=user_label,
        options_offered=options_list,
        chosen_option=str(chosen_option),
        rationale=str(rationale),
        source_refs=refs_list,
        status=str(status) if status in {"logged", "applied", "superseded"} else "logged",
        meta_data=dict(metadata or {}),
    )
    db.add(decision)
    db.flush()
    audit_id = emit_audit_event(
        db=db,
        workspace_id=workspace.id,
        event_type="meeting.decision.logged",
        actor=user_label,
        details={
            "decision_id": decision.id,
            "calendar_event_id": decision.calendar_event_id,
            "agenda_item_ref": decision.agenda_item_ref,
            "chosen_option": decision.chosen_option,
        },
    )
    decision.audit_log_ref = audit_id
    db.flush()
    return decision


def list_decisions_for_event(
    db: DBSession,
    workspace: Workspace,
    calendar_event_id: str,
) -> list[MeetingDecision]:
    return (
        db.query(MeetingDecision)
        .filter(
            MeetingDecision.workspace_id == workspace.id,
            MeetingDecision.calendar_event_id == str(calendar_event_id),
        )
        .order_by(MeetingDecision.decided_at.asc())
        .all()
    )


def list_decisions_for_workspace(
    db: DBSession,
    workspace: Workspace,
    *,
    topic: Optional[str] = None,
    limit: int = 50,
) -> list[MeetingDecision]:
    query = (
        db.query(MeetingDecision)
        .filter(MeetingDecision.workspace_id == workspace.id)
        .order_by(MeetingDecision.decided_at.desc())
    )
    rows = query.limit(max(1, min(int(limit), 200))).all()
    if not topic:
        return rows
    needle = str(topic).lower()
    filtered = [
        row
        for row in rows
        if needle in (row.agenda_item_ref or "").lower()
        or needle in (row.rationale or "").lower()
        or any(needle in str(ref).lower() for ref in (row.source_refs or []))
    ]
    return filtered or rows
