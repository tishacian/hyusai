"""Government mission-room demo endpoints.

All payloads are workspace-scoped and advisory-only. The public product shape is
generic (`mission-room`) while SENTINEL-CI is supplied by the seeded demo
workspace and fixtures.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session as DBSession

from app.core.auth import get_current_user, get_current_workspace
from app.db.base import get_db
from app.extensions.registry import MISSION_ROOM_EXTENSION_ID, require_workspace_extension
from app.models.user import User
from app.models.workspace import Workspace
from app.services import generic_mission_room
from app.services.audit_logger import emit_audit_event
from app.services.intelligence.satellite_imagery import (
    get_scene_asset_bytes,
    resolve_satellite_scenes,
)
from app.services.macro_indicators import macro_indicators_payload
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
    present_payload_for_workspace,
    projects_payload,
    search_payload,
    security_monitor_payload,
    timeline_payload,
)
from app.services.workspace_app_manifests import GENERIC_MISSION_ROOM_PROVIDER_KIND
from app.services.workspace_app_runtime import (
    SENTINEL_MISSION_ROOM_APP_ID,
    resolve_mission_room_provider_runtime,
    workspace_app_platform_enabled,
)

router = APIRouter(
    dependencies=[Depends(require_workspace_extension(MISSION_ROOM_EXTENSION_ID))]
)

_SENTINEL_CUSTOMS_RECORD_FILES = frozenset(
    {"proces-verbal-douanes-non-conformite-2026-05-18"}
)
_MISSION_ROOM_AUDIT_UNAVAILABLE = {"code": "mission_room_audit_unavailable"}


class DraftInstructionRequest(BaseModel):
    target_id: str
    target_type: str = "project"
    instruction_type: str = "dircab_instruction"
    tone: str | None = "ministerial"


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
    audit_id = emit_audit_event(
        db=db,
        workspace_id=workspace.id,
        event_type=event_type,
        actor=_actor(user),
        details=details,
    )
    if audit_id is None:
        db.rollback()
        raise HTTPException(
            status_code=503,
            detail=_MISSION_ROOM_AUDIT_UNAVAILABLE,
        )
    _commit_request_audit(db)


def _commit_request_audit(db: DBSession) -> None:
    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=503,
            detail=_MISSION_ROOM_AUDIT_UNAVAILABLE,
        ) from exc


def _present(workspace: Workspace, payload):
    return present_payload_for_workspace(workspace, payload)


def _generic_provider_projection(
    workspace: Workspace,
    db: DBSession,
) -> dict | None:
    if not workspace_app_platform_enabled(workspace):
        return None
    runtime = resolve_mission_room_provider_runtime(workspace, db=db)
    projection = runtime.mission_room
    if (
        isinstance(projection, dict)
        and projection.get("provider_kind") == GENERIC_MISSION_ROOM_PROVIDER_KIND
    ):
        return projection
    return None


@router.get("/overview")
def overview(
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    projection = _generic_provider_projection(workspace, db)
    payload = (
        generic_mission_room.overview_payload(db, workspace, user)
        if projection is not None
        else overview_payload(workspace)
    )
    _audit(db=db, workspace=workspace, user=user, event_type="mission_room.overview.viewed", details={"surface": "overview"})
    return _present(workspace, payload)


@router.get("/navigation")
def navigation(
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    projection = _generic_provider_projection(workspace, db)
    payload = (
        generic_mission_room.navigation_payload(db, workspace, user, projection)
        if projection is not None
        else navigation_payload(db, workspace)
    )
    _audit(
        db=db,
        workspace=workspace,
        user=user,
        event_type="mission_room.navigation.viewed",
        details={"views": len(payload.get("items") or []), "surface": "navigation"},
    )
    return _present(workspace, payload)


@router.get("/cockpit")
def cockpit(
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    projection = _generic_provider_projection(workspace, db)
    payload = (
        generic_mission_room.cockpit_payload(db, workspace, user)
        if projection is not None
        else cockpit_payload(workspace, db=db)
    )
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
    return _present(workspace, payload)


@router.get("/briefing")
def briefing(
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    projection = _generic_provider_projection(workspace, db)
    payload = (
        generic_mission_room.briefing_payload(db, workspace, user)
        if projection is not None
        else briefing_payload(workspace, db=db)
    )
    _audit(
        db=db,
        workspace=workspace,
        user=user,
        event_type="mission_room.briefing.generated",
        details={"sections": len(payload.get("sections") or []), "advisory_only": True},
    )
    return _present(workspace, payload)


@router.get("/timeline")
def timeline(
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    projection = _generic_provider_projection(workspace, db)
    payload = (
        generic_mission_room.timeline_payload(db, workspace, user)
        if projection is not None
        else timeline_payload(workspace, db=db)
    )
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
    return _present(workspace, payload)


@router.get("/projects")
def projects(
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    projection = _generic_provider_projection(workspace, db)
    payload = (
        generic_mission_room.projects_payload(db, workspace, user)
        if projection is not None
        else projects_payload(workspace, db=db)
    )
    _audit(
        db=db,
        workspace=workspace,
        user=user,
        event_type="mission_room.projects.explained",
        details={"projects": len(payload.get("projects") or []), "advisory_only": True},
    )
    return _present(workspace, payload)


@router.get("/decisions")
def decisions(
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    projection = _generic_provider_projection(workspace, db)
    payload = (
        generic_mission_room.decisions_payload(db, workspace, user)
        if projection is not None
        else decisions_payload(workspace, db=db)
    )
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
    return _present(workspace, payload)


@router.get("/library")
def library(
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    projection = _generic_provider_projection(workspace, db)
    payload = (
        generic_mission_room.library_payload(db, workspace, user)
        if projection is not None
        else library_payload(workspace)
    )
    _audit(
        db=db,
        workspace=workspace,
        user=user,
        event_type="mission_room.library.viewed",
        details={"items": len(payload.get("items") or []), "metadata_only": True},
    )
    return _present(workspace, payload)


@router.get("/search")
def search(
    q: str = Query("", max_length=200),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    projection = _generic_provider_projection(workspace, db)
    payload = (
        generic_mission_room.search_payload(db, workspace, user, q)
        if projection is not None
        else search_payload(workspace, q)
    )
    _audit(
        db=db,
        workspace=workspace,
        user=user,
        event_type="mission_room.search.performed",
        details={"query": q, "results": payload.get("total"), "synthetic_scope": True},
    )
    return _present(workspace, payload)


@router.get("/map")
def strategic_map(
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    projection = _generic_provider_projection(workspace, db)
    payload = (
        generic_mission_room.map_payload(db, workspace, user)
        if projection is not None
        else map_payload(workspace, db=db)
    )
    _audit(
        db=db,
        workspace=workspace,
        user=user,
        event_type="mission_room.map.generated",
        details={"zones": len(payload.get("zones") or []), "accuracy": (payload.get("map") or {}).get("accuracy")},
    )
    return _present(workspace, payload)


@router.get("/monitor")
def situation_monitor(
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    projection = _generic_provider_projection(workspace, db)
    payload = (
        generic_mission_room.monitor_payload(db, workspace, user)
        if projection is not None
        else monitor_payload(workspace, db=db)
    )
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
    return _present(workspace, payload)


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
    return _present(workspace, payload)


@router.get("/satellite/scenes")
def satellite_scenes(
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    payload = resolve_satellite_scenes(workspace)
    _audit(
        db=db,
        workspace=workspace,
        user=user,
        event_type="mission_room.satellite.scenes_viewed",
        details={
            "mode": payload.get("mode"),
            "scenes": len(payload.get("scenes") or []),
            "advisory_only": True,
        },
    )
    return _present(workspace, payload)


@router.get("/satellite/proxy")
def satellite_proxy(
    scene_id: str = Query(..., min_length=1, max_length=120),
    variant: str = Query("asset", pattern="^(asset|thumbnail)$"),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    try:
        content, content_type = get_scene_asset_bytes(scene_id, variant=variant)  # type: ignore[arg-type]
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Satellite scene not found") from exc
    _audit(
        db=db,
        workspace=workspace,
        user=user,
        event_type="mission_room.satellite.asset_viewed",
        details={"scene_id": scene_id, "variant": variant, "advisory_only": True},
    )
    return Response(
        content=content,
        media_type=content_type,
        headers={"Cache-Control": "private, max-age=3600"},
    )


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
    return _present(workspace, payload)


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
    return _present(workspace, payload)


@router.get("/customs-records/{document_id}.pdf")
def customs_record_pdf(
    document_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Serve a customs PV PDF (Phase D). Workspace-scoped + audit-logged."""
    owner_app_id: str | None = None
    if workspace_app_platform_enabled(workspace):
        runtime = resolve_mission_room_provider_runtime(workspace, db=db)
        mission_room_runtime = runtime.mission_room or {}
        owner_app_id = str(mission_room_runtime.get("app_id") or "")
        if (
            owner_app_id != SENTINEL_MISSION_ROOM_APP_ID
            or document_id not in _SENTINEL_CUSTOMS_RECORD_FILES
        ):
            # Resource absence and app mismatch intentionally share one result;
            # Octocity/generic callers cannot probe the Sentinel document set.
            raise HTTPException(status_code=404, detail="customs_record_not_found")
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
        details={
            "document_id": document_id,
            "size_bytes": pdf_path.stat().st_size,
            **(
                {
                    "owner_workspace_id": workspace.id,
                    "owner_app_id": owner_app_id,
                    "resource_scope": "workspace_app",
                }
                if owner_app_id
                else {}
            ),
        },
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
    return _present(workspace, payload)


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
    return _present(workspace, payload)


@router.get("/news")
def news(
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    projection = _generic_provider_projection(workspace, db)
    payload = (
        generic_mission_room.news_payload(db, workspace, user)
        if projection is not None
        else news_payload(workspace, db=db)
    )
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
    return _present(workspace, payload)


@router.post("/actions/draft")
def draft_action(
    body: DraftInstructionRequest,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    projection = _generic_provider_projection(workspace, db)
    payload = (
        generic_mission_room.draft_instruction_payload(
            workspace=workspace,
            user=user,
            target_id=body.target_id,
            target_type=body.target_type,
            instruction_type=body.instruction_type,
            db=db,
        )
        if projection is not None
        else draft_instruction_payload(
            workspace=workspace,
            actor=_actor(user),
            target_id=body.target_id,
            target_type=body.target_type,
            instruction_type=body.instruction_type,
            db=db,
            require_audit=True,
        )
    )
    _commit_request_audit(db)
    return _present(workspace, payload)
