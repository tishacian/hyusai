"""Workspace calendar API."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DBSession

from app.core.auth import get_current_user, get_current_workspace
from app.db.base import get_db
from app.models.user import User
from app.models.workspace import Workspace
from app.services.workspace_calendar import (
    cancel_event,
    create_event,
    list_events,
    serialize_event,
    summary_payload,
    update_event,
)


router = APIRouter()


class CalendarEventCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    start_at: datetime
    end_at: Optional[datetime] = None
    location: str = ""
    description: str = ""
    participants: list[str] = Field(default_factory=list)
    category: str = "ministerial"
    priority: str = "medium"
    status: str = "scheduled"
    metadata: dict[str, Any] = Field(default_factory=dict)


class CalendarEventPatch(BaseModel):
    title: Optional[str] = Field(default=None, max_length=255)
    start_at: Optional[datetime] = None
    end_at: Optional[datetime] = None
    location: Optional[str] = None
    description: Optional[str] = None
    participants: Optional[list[str]] = None
    category: Optional[str] = None
    priority: Optional[str] = None
    status: Optional[str] = None


class CalendarCancelRequest(BaseModel):
    reason: str = ""


@router.get("/events")
async def calendar_events(
    start: Optional[datetime] = Query(default=None),
    end: Optional[datetime] = Query(default=None),
    status: Optional[str] = Query(default=None),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    rows = list_events(db, workspace, start=start, end=end, status=status)
    return {"events": [serialize_event(row) for row in rows]}


@router.post("/events")
async def calendar_create_event(
    body: CalendarEventCreate,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    try:
        event = create_event(
            db,
            workspace,
            user,
            title=body.title,
            start_at=body.start_at,
            end_at=body.end_at,
            location=body.location,
            description=body.description,
            participants=body.participants,
            category=body.category,
            priority=body.priority,
            status=body.status,
            metadata=body.metadata,
        )
        db.commit()
        return serialize_event(event)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/events/{event_id}")
async def calendar_update_event(
    event_id: str,
    body: CalendarEventPatch,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    try:
        event = update_event(
            db,
            workspace,
            user,
            event_id,
            updates=body.model_dump(exclude_unset=True),
        )
        db.commit()
        return serialize_event(event)
    except LookupError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail="Calendar event not found") from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/events/{event_id}/cancel")
async def calendar_cancel_event(
    event_id: str,
    body: CalendarCancelRequest,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    try:
        event = cancel_event(db, workspace, user, event_id, body.reason)
        db.commit()
        return serialize_event(event)
    except LookupError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail="Calendar event not found") from exc


@router.get("/summary")
async def calendar_summary(
    day: Optional[date] = Query(default=None),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    return summary_payload(db, workspace, day=day)
