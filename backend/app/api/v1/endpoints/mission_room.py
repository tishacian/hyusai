"""Government mission-room demo endpoints.

All payloads are workspace-scoped and advisory-only. The public product shape is
generic (`mission-room`) while SENTINEL-CI is supplied by the seeded demo
workspace and fixtures.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session as DBSession

from app.core.auth import get_current_user, get_current_workspace
from app.db.base import get_db
from app.models.user import User
from app.models.workspace import Workspace
from app.services.audit_logger import emit_audit_event
from app.services.mission_room import (
    briefing_payload,
    cedeao_index_payload_for_workspace,
    cockpit_payload,
    decisions_payload,
    draft_instruction_payload,
    evidence_graph_payload,
    evidence_graph_trace,
    library_payload,
    map_payload,
    monitor_payload,
    navigation_payload,
    news_payload,
    overview_payload,
    projects_payload,
    search_payload,
    security_monitor_payload,
    timeline_payload,
)
from app.services.macro_indicators import macro_indicators_payload

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
def overview(
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    payload = overview_payload(workspace)
    _audit(db=db, workspace=workspace, user=user, event_type="mission_room.overview.viewed", details={"surface": "overview"})
    return payload


@router.get("/navigation")
def navigation(
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
def cockpit(
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
def briefing(
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
def timeline(
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
def projects(
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
def decisions(
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
def library(
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
def search(
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
def strategic_map(
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
def situation_monitor(
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


@router.get("/security-monitor")
def security_monitor(
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    payload = security_monitor_payload(workspace, db=db)
    _audit(
        db=db,
        workspace=workspace,
        user=user,
        event_type="mission_room.security_monitor.viewed",
        details={
            "tracks": len((payload.get("theater_sahel") or {}).get("tracks") or []),
            "social": len((payload.get("social_signals") or {}).get("tweets") or []),
            "posture": (payload.get("security_posture") or {}).get("summary"),
        },
    )
    return payload


@router.get("/evidence-graph")
def evidence_graph(
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


@router.get("/evidence-graph/trace")
def evidence_graph_trace_route(
    from_: str = Query(..., alias="from", min_length=1, max_length=160),
    relation: str = Query("caused_by", max_length=64),
    depth: int = Query(4, ge=1, le=8),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    payload = evidence_graph_trace(workspace, from_node=from_, relation=relation, depth=depth, db=db)
    _audit(
        db=db,
        workspace=workspace,
        user=user,
        event_type="mission_room.evidence_graph.trace",
        details={
            "from": from_,
            "relation": relation,
            "depth": depth,
            "path_len": len(payload.get("path") or []),
        },
    )
    return payload


@router.get("/customs-records/{document_id}.pdf")
def customs_record_pdf(
    document_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Serve a customs PV PDF (Phase D). Workspace-scoped + audit-logged."""
    if "/" in document_id or "\\" in document_id or ".." in document_id:
        raise HTTPException(status_code=400, detail="invalid_document_id")
    pdf_root = Path(__file__).resolve().parents[3] / "resources" / "sentinel_ci_customs"
    pdf_path = pdf_root / f"{document_id}.pdf"
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="customs_record_not_found")
    _audit(
        db=db,
        workspace=workspace,
        user=user,
        event_type="mission_room.customs_record.downloaded",
        details={"document_id": document_id, "size_bytes": pdf_path.stat().st_size},
    )
    return Response(
        content=pdf_path.read_bytes(),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{document_id}.pdf"'},
    )


@router.get("/reports/{workspace_slug}/{report_id}.pdf")
def report_pdf(
    workspace_slug: str,
    report_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Serve a strategic report PDF (Phase F + G) via the object store."""
    from app.services.object_store import get_object_store
    from app.services.sentinel_ci_reports import STRATEGIC_REPORTS_PREFIX

    if workspace.slug != workspace_slug:
        raise HTTPException(status_code=403, detail="workspace_mismatch")
    if "/" in report_id or "\\" in report_id or ".." in report_id:
        raise HTTPException(status_code=400, detail="invalid_report_id")
    # The FastAPI path template captures ``{report_id}`` without the trailing
    # ``.pdf``, but reports are persisted to the object store with the
    # ``.pdf`` suffix (see ``generate_strategic_report`` /
    # ``ensure_prefet_report_in_object_store``). Re-append it before lookup.
    object_key = f"{STRATEGIC_REPORTS_PREFIX}/{workspace.id}/{report_id}.pdf"
    store = get_object_store()
    if not store.exists(object_key):
        raise HTTPException(status_code=404, detail="report_not_found")
    body = store.read_bytes(object_key)
    _audit(
        db=db,
        workspace=workspace,
        user=user,
        event_type="mission_room.report.downloaded",
        details={"object_key": object_key, "size_bytes": len(body)},
    )
    return Response(
        content=body,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{report_id}.pdf"'},
    )


@router.get("/macro-indicators")
def macro_indicators(
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    payload = macro_indicators_payload(db, workspace)
    _audit(
        db=db,
        workspace=workspace,
        user=user,
        event_type="mission_room.macro_indicators.viewed",
        details={
            "indicators": len(payload.get("indicators") or []),
            "source": payload.get("source"),
            "fetched_at": payload.get("fetched_at"),
        },
    )
    return payload


@router.get("/cedeao-index")
def cedeao_index(
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    payload = cedeao_index_payload_for_workspace(workspace)
    _audit(
        db=db,
        workspace=workspace,
        user=user,
        event_type="mission_room.cedeao_index.viewed",
        details={
            "score": payload.get("score"),
            "live": bool(payload.get("live")),
            "source_badge": payload.get("source_badge"),
            "advisory_only": True,
        },
    )
    return payload


@router.get("/news")
def news(
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
def draft_action(
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
