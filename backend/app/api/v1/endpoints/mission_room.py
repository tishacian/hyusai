"""Government mission-room demo endpoints.

All payloads are workspace-scoped and advisory-only. The public product shape is
generic (`mission-room`) while SENTINEL-CI is supplied by the seeded demo
workspace and fixtures.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session as DBSession

from app.core.auth import get_current_user, get_current_workspace
from app.db.base import get_db
from app.models.user import User
from app.models.workspace import Workspace
from app.services.audit_logger import emit_audit_event
from app.services.mission_room import (
    briefing_payload,
    cockpit_payload,
    decisions_payload,
    draft_instruction_payload,
    evidence_graph_payload,
    library_payload,
    map_payload,
    monitor_payload,
    navigation_payload,
    news_payload,
    overview_payload,
    projects_payload,
    search_payload,
    timeline_payload,
)

router = APIRouter()


class DraftInstructionRequest(BaseModel):
    target_id: str
    target_type: str = "project"
    instruction_type: str = "dircab_instruction"
    tone: Optional[str] = "ministerial"


def _actor(user: User) -> str:
    return user.email or user.username or user.id


def _audit(
    *,
    db: DBSession,
    workspace: Workspace,
    user: User,
    event_type: str,
    details: dict,
) -> None:
    emit_audit_event(
        db=db,
        workspace_id=workspace.id,
        event_type=event_type,
        actor=_actor(user),
        details=details,
    )


@router.get("/overview")
async def overview(
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    payload = overview_payload(workspace)
    _audit(db=db, workspace=workspace, user=user, event_type="mission_room.overview.viewed", details={"surface": "overview"})
    return payload


@router.get("/navigation")
async def navigation(
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    payload = navigation_payload(db, workspace)
    _audit(
        db=db,
        workspace=workspace,
        user=user,
        event_type="mission_room.navigation.viewed",
        details={"views": len(payload.get("items") or []), "surface": "navigation"},
    )
    return payload


@router.get("/cockpit")
async def cockpit(
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    payload = cockpit_payload(workspace, db=db)
    press = payload.get("press_intelligence") or {}
    _audit(
        db=db,
        workspace=workspace,
        user=user,
        event_type="mission_room.cockpit.viewed",
        details={
            "surface": "cockpit",
            "priorities": len(payload.get("priorities") or []),
            "last_run_id": press.get("last_run_id"),
            "live_news_used": bool(press.get("live_news_used")),
        },
    )
    return payload


@router.get("/briefing")
async def briefing(
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    payload = briefing_payload(workspace, db=db)
    _audit(
        db=db,
        workspace=workspace,
        user=user,
        event_type="mission_room.briefing.generated",
        details={"sections": len(payload.get("sections") or []), "advisory_only": True},
    )
    return payload


@router.get("/timeline")
async def timeline(
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    payload = timeline_payload(workspace, db=db)
    _audit(
        db=db,
        workspace=workspace,
        user=user,
        event_type="mission_room.timeline.viewed",
        details={
            "agenda": len(payload.get("agenda") or []),
            "messages": len(payload.get("messages") or []),
            "connector_id": "institutional_calendar",
            "synthetic": not bool((payload.get("calendar") or {}).get("events")),
        },
    )
    return payload


@router.get("/projects")
async def projects(
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    payload = projects_payload(workspace, db=db)
    _audit(
        db=db,
        workspace=workspace,
        user=user,
        event_type="mission_room.projects.explained",
        details={"projects": len(payload.get("projects") or []), "advisory_only": True},
    )
    return payload


@router.get("/decisions")
async def decisions(
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    payload = decisions_payload(workspace, db=db)
    _audit(
        db=db,
        workspace=workspace,
        user=user,
        event_type="mission_room.decisions.viewed",
        details={
            "decisions": len(payload.get("decisions") or []),
            "action_items": len(payload.get("action_items") or []),
            "advisory_only": True,
        },
    )
    return payload


@router.get("/library")
async def library(
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    payload = library_payload(workspace)
    _audit(
        db=db,
        workspace=workspace,
        user=user,
        event_type="mission_room.library.viewed",
        details={"items": len(payload.get("items") or []), "metadata_only": True},
    )
    return payload


@router.get("/search")
async def search(
    q: str = Query("", max_length=200),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    payload = search_payload(workspace, q)
    _audit(
        db=db,
        workspace=workspace,
        user=user,
        event_type="mission_room.search.performed",
        details={"query": q, "results": payload.get("total"), "synthetic_scope": True},
    )
    return payload


@router.get("/map")
async def strategic_map(
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    payload = map_payload(workspace, db=db)
    _audit(
        db=db,
        workspace=workspace,
        user=user,
        event_type="mission_room.map.generated",
        details={"zones": len(payload.get("zones") or []), "accuracy": (payload.get("map") or {}).get("accuracy")},
    )
    return payload


@router.get("/monitor")
async def situation_monitor(
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    payload = monitor_payload(workspace, db=db)
    _audit(
        db=db,
        workspace=workspace,
        user=user,
        event_type="mission_room.monitor.viewed",
        details={
            "zones": len(payload.get("zones") or []),
            "visual_observations": len(payload.get("visual_observations") or []),
            "posture": (payload.get("posture") or {}).get("label"),
        },
    )
    return payload


@router.get("/evidence-graph")
async def evidence_graph(
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    payload = evidence_graph_payload(workspace, db=db)
    _audit(
        db=db,
        workspace=workspace,
        user=user,
        event_type="mission_room.evidence_graph.viewed",
        details={
            "nodes": len(payload.get("nodes") or []),
            "edges": len(payload.get("edges") or []),
            "clusters": len(payload.get("clusters") or []),
            "collection_slug": (payload.get("knowledge") or {}).get("collection_slug"),
        },
    )
    return payload


@router.get("/news")
async def news(
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    payload = news_payload(workspace, db=db)
    source_health = payload.get("source_health") or {}
    _audit(
        db=db,
        workspace=workspace,
        user=user,
        event_type="mission_room.news.synthesized",
        details={
            "signals": len(payload.get("signals") or []),
            "executive_alert_count": len(payload.get("executive_alerts") or []),
            "last_run_id": source_health.get("last_run_id"),
            "live_news_used": bool(source_health.get("live_news_used")),
            "advisory_only": True,
        },
    )
    return payload


@router.post("/actions/draft")
async def draft_action(
    body: DraftInstructionRequest,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    return draft_instruction_payload(
        workspace=workspace,
        actor=_actor(user),
        target_id=body.target_id,
        target_type=body.target_type,
        instruction_type=body.instruction_type,
        db=db,
    )
