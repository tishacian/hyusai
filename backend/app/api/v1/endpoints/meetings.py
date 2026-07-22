"""Live meeting API surfaces (Phase I).

Backed by ``WorkspaceCalendarEvent`` (existing) and ``MeetingDecision``
(new). All side-effects are workspace-scoped and audit-logged.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DBSession

from app.core.auth import get_current_user, get_current_workspace
from app.db.base import get_db
from app.models.user import User
from app.models.workspace import Workspace
from app.services.actions.executor import (
    set_current_meeting,
    set_pending_agenda_patch,
)
from app.services.audit_logger import emit_audit_event
from app.services.meeting_decisions import (
    list_decisions_for_event,
    list_decisions_for_workspace,
    log_decision_for_workspace,
    serialize_decision,
)
from app.services.workspace_calendar import _get_event, serialize_event, update_event

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


class AgendaPatchPropose(BaseModel):
    """Stage a pending agenda patch — same shape AYA produces via voice."""

    agenda_items: list[dict[str, Any]] = Field(..., min_length=1)


class AgendaPatchConfirm(BaseModel):
    """Confirm a pending patch. ``agenda_items`` overrides any pending payload."""

    agenda_items: Optional[list[dict[str, Any]]] = None


def _pending_agenda_patch(workspace: Workspace) -> Optional[dict[str, Any]]:
    settings = workspace.settings or {}
    actions = settings.get("actions") or {}
    pending = actions.get("pending_agenda_patch")
    return dict(pending) if isinstance(pending, dict) else None


def _resolve_event(db: DBSession, workspace: Workspace, event_id: str):
    try:
        return _get_event(db, workspace, event_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="meeting_not_found") from exc


def _actor_label(user: Optional[User]) -> str:
    if not user:
        return "system"
    return user.email or user.username or user.id


def _serialize_pending_patch(
    workspace: Workspace, *, event_id: str
) -> Optional[dict[str, Any]]:
    pending = _pending_agenda_patch(workspace)
    if not pending or str(pending.get("event_id") or "") != event_id:
        return None
    return pending


@router.get("/decisions-log")
def meeting_decisions_log(
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Return the active workspace's persisted meeting-decision ledger."""

    decisions = list_decisions_for_workspace(db, workspace, limit=200)
    return {"decisions": [serialize_decision(item) for item in decisions]}


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
        "event": serialize_event(event, workspace=workspace),
        "agenda_items": list(metadata.get("agenda_items") or []),
        "decisions": [serialize_decision(item) for item in decisions],
        "decision_count": len(decisions),
        "pending_agenda_patch": _serialize_pending_patch(workspace, event_id=event.id),
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


@router.post("/{event_id}/start")
def meeting_start(
    event_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Mirror ``aya.start_meeting`` — set ``current_meeting`` workspace state.

    The actual UI navigation is performed client-side. This endpoint exists so a
    click-driven start path produces the same workspace-level side-effect as the
    voice path (so a follow-up ``aya.log_decision`` finds an active meeting).
    """

    event = _resolve_event(db, workspace, event_id)
    set_current_meeting(db, workspace, event.id)
    db.commit()
    emit_audit_event(
        db=db,
        workspace_id=workspace.id,
        event_type="meeting.started.click",
        actor=_actor_label(user),
        details={"event_id": event.id, "surface": "ui"},
    )
    return {"event": serialize_event(event, workspace=workspace), "current_meeting": event.id}


@router.get("/{event_id}/agenda-patch")
def meeting_agenda_patch_pending(
    event_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    event = _resolve_event(db, workspace, event_id)
    return {
        "event_id": event.id,
        "pending_agenda_patch": _serialize_pending_patch(workspace, event_id=event.id),
    }


@router.post("/{event_id}/agenda-patch")
def meeting_agenda_patch_propose(
    event_id: str,
    body: AgendaPatchPropose,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Stage a pending agenda patch — same shape AYA produces via voice."""

    event = _resolve_event(db, workspace, event_id)
    items = list(body.agenda_items)
    set_current_meeting(db, workspace, event.id)
    set_pending_agenda_patch(
        db,
        workspace,
        {
            "event_id": event.id,
            "agenda_items": items,
            "proposed_at": datetime.utcnow().isoformat(),
            "proposed_via": "ui",
        },
    )
    db.commit()
    emit_audit_event(
        db=db,
        workspace_id=workspace.id,
        event_type="meeting.agenda_patch.proposed",
        actor=_actor_label(user),
        details={"event_id": event.id, "items": len(items), "surface": "ui"},
    )
    return {
        "event_id": event.id,
        "pending_agenda_patch": _serialize_pending_patch(workspace, event_id=event.id),
    }


@router.post("/{event_id}/agenda-patch/confirm")
def meeting_agenda_patch_confirm(
    event_id: str,
    body: AgendaPatchConfirm,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Apply the pending agenda patch (or the supplied ``agenda_items``)."""

    event = _resolve_event(db, workspace, event_id)
    pending = _serialize_pending_patch(workspace, event_id=event.id)
    items = body.agenda_items or (pending.get("agenda_items") if pending else None)
    if not items:
        raise HTTPException(status_code=400, detail="no_pending_agenda_patch")

    try:
        updated = update_event(
            db,
            workspace,
            user,
            event.id,
            updates={"metadata": {"agenda_items": list(items)}},
        )
    except LookupError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail="meeting_not_found") from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    set_pending_agenda_patch(db, workspace, None)
    db.commit()
    emit_audit_event(
        db=db,
        workspace_id=workspace.id,
        event_type="meeting.agenda_patch.confirmed",
        actor=_actor_label(user),
        details={"event_id": event.id, "items": len(items), "surface": "ui"},
    )
    return {
        "event": serialize_event(updated, workspace=workspace),
        "agenda_items": list((updated.meta_data or {}).get("agenda_items") or []),
        "pending_agenda_patch": None,
    }
