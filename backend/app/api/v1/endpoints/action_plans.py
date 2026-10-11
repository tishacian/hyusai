"""Workspace action planner API."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DBSession

from app.core.auth import get_current_user, get_current_workspace
from app.db.base import get_db
from app.models.user import User
from app.models.workspace import Workspace
from app.services.action_plans import (
    cancel_action_item,
    complete_action_item,
    create_action_item,
    list_action_items,
    serialize_action_item,
    summary_payload,
    update_action_item,
)


router = APIRouter()


class ActionPlanCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: str = ""
    target_kind: str = "cabinet"
    target_id: str = ""
    target_label: str = ""
    priority: str = "medium"
    due_at: Optional[datetime] = None
    owner_label: str = "Cabinet"
    source_kind: str = "assistant"
    source_id: str = ""
    calendar_event_id: Optional[str] = None
    run_id: Optional[str] = None
    confidence: str = "medium"
    recommended_window: dict[str, Any] = Field(default_factory=dict)
    scenario_options: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ActionPlanPatch(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    target_kind: Optional[str] = None
    target_id: Optional[str] = None
    target_label: Optional[str] = None
    priority: Optional[str] = None
    status: Optional[str] = None
    due_at: Optional[datetime] = None
    owner_label: Optional[str] = None
    source_kind: Optional[str] = None
    source_id: Optional[str] = None
    calendar_event_id: Optional[str] = None
    confidence: Optional[str] = None
    recommended_window: Optional[dict[str, Any]] = None
    scenario_options: Optional[list[dict[str, Any]]] = None
    metadata: Optional[dict[str, Any]] = None


class ActionPlanCancel(BaseModel):
    reason: str = ""


@router.get("/")
async def action_plan_list(
    status: Optional[str] = Query(default=None),
    target_kind: Optional[str] = Query(default=None),
    include_cancelled: bool = Query(default=True),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    rows = list_action_items(db, workspace, status=status, target_kind=target_kind, include_cancelled=include_cancelled)
    return {
        "items": [serialize_action_item(row) for row in rows],
        "summary": summary_payload(db, workspace),
    }


@router.post("/")
async def action_plan_create(
    body: ActionPlanCreate,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    try:
        item = create_action_item(
            db,
            workspace,
            user,
            title=body.title,
            description=body.description,
            target_kind=body.target_kind,
            target_id=body.target_id,
            target_label=body.target_label,
            priority=body.priority,
            due_at=body.due_at,
            owner_label=body.owner_label,
            source_kind=body.source_kind,
            source_id=body.source_id,
            calendar_event_id=body.calendar_event_id,
            run_id=body.run_id,
            confidence=body.confidence,
            recommended_window=body.recommended_window,
            scenario_options=body.scenario_options or None,
            metadata=body.metadata,
        )
        db.commit()
        return serialize_action_item(item)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/{item_id}")
async def action_plan_update(
    item_id: str,
    body: ActionPlanPatch,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    try:
        item = update_action_item(db, workspace, user, item_id, body.model_dump(exclude_unset=True))
        db.commit()
        return serialize_action_item(item)
    except LookupError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail="Action item not found") from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{item_id}/cancel")
async def action_plan_cancel(
    item_id: str,
    body: ActionPlanCancel,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    try:
        item = cancel_action_item(db, workspace, user, item_id, body.reason)
        db.commit()
        return serialize_action_item(item)
    except LookupError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail="Action item not found") from exc


@router.post("/{item_id}/complete")
async def action_plan_complete(
    item_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    try:
        item = complete_action_item(db, workspace, user, item_id)
        db.commit()
        return serialize_action_item(item)
    except LookupError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail="Action item not found") from exc
