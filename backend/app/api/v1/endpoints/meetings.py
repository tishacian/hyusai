"""Live meeting API surfaces (Phase I).

Backed by ``WorkspaceCalendarEvent`` (existing) and ``MeetingDecision``
(new). All side-effects are workspace-scoped and audit-logged.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DBSession

from app.core.auth import get_current_user, get_current_workspace
from app.db.base import get_db
from app.models.user import User
from app.models.workspace import Workspace
from app.services.meeting_decisions import (
    list_decisions_for_event,
    log_decision_for_workspace,
    serialize_decision,
)
from app.services.workspace_calendar import _get_event, serialize_event


router = APIRouter()


class DecisionOption(BaseModel):
    key: str = Field(..., min_length=1, max_length=64)
    label: str = Field(..., min_length=1, max_length=255)
    summary: Optional[str] = Field(default=None, max_length=1024)


class MeetingDecisionCreate(BaseModel):
    agenda_item_ref: str = Field(default="", max_length=160)
    options_offered: list[dict[str, Any]] = Field(default_factory=list)
    chosen_option: str = Field(..., min_length=1, max_length=64)
    rationale: str = Field(default="", max_length=4096)
    source_refs: list[str] = Field(default_factory=list)


def _resolve_event(db: DBSession, workspace: Workspace, event_id: str):
    try:
        return _get_event(db, workspace, event_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="meeting_not_found") from exc


@router.get("/{event_id}")
def meeting_detail(
    event_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    event = _resolve_event(db, workspace, event_id)
    decisions = list_decisions_for_event(db, workspace, event.id)
    metadata = event.meta_data or {}
    return {
        "event": serialize_event(event),
        "agenda_items": list(metadata.get("agenda_items") or []),
        "decisions": [serialize_decision(item) for item in decisions],
        "decision_count": len(decisions),
    }


@router.get("/{event_id}/decisions")
def meeting_decisions_list(
    event_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    event = _resolve_event(db, workspace, event_id)
    decisions = list_decisions_for_event(db, workspace, event.id)
    return {"event_id": event.id, "decisions": [serialize_decision(item) for item in decisions]}


@router.post("/{event_id}/decisions")
def meeting_decisions_create(
    event_id: str,
    body: MeetingDecisionCreate,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    event = _resolve_event(db, workspace, event_id)
    decision = log_decision_for_workspace(
        db,
        workspace,
        user,
        calendar_event_id=event.id,
        agenda_item_ref=body.agenda_item_ref,
        options_offered=body.options_offered,
        chosen_option=body.chosen_option,
        rationale=body.rationale,
        source_refs=body.source_refs,
    )
    db.commit()
    return serialize_decision(decision)
