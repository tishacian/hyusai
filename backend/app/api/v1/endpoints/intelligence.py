"""Intelligence API — RSS feeds, analysis, dashboard (scoped by workspace)."""
import json
import time
import uuid
from datetime import datetime

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session as DBSession

from app.core.auth import get_current_user, get_current_workspace
from app.core.config import settings
from app.db.base import SessionLocal, get_db
from app.models.capability import Capability
from app.models.intelligence import FeedArticle, FeedSource, SafetyFilter, SemanticTarget
from app.models.run import Run, SkillInvocation
from app.models.system import System
from app.models.user import User
from app.models.workspace import Workspace
from app.services.iam.decision_plane import enforce_action, resolve_action
from app.services.iam.legacy_authority import legacy_object_action_allowed
from app.services.intelligence.batch import get_dashboard_data, run_batch
from app.services.intelligence.feed_manager import get_articles
from app.services.intelligence.knowledge_sync import sync_intelligence_to_knowledge
from app.services.intelligence.profile import workspace_intelligence_profile
from app.services.intelligence.systems import (
    INTELLIGENCE_TEMPLATE_ID,
    intelligence_systems,
    preferred_intelligence_system,
    template_id_of,
)
from app.services.skill_invocation_snapshot import (
    SkillInvocationCostEvidence,
    capture_skill_execution_evidence,
    resolve_skill_invocation_cost,
)
from app.services.system_engine_authorization import enforce_system_engine_run

router = APIRouter()


class FeedCreate(BaseModel):
    name: str
    url: str
    category: str = "general"
    refresh_interval: int = 3600


class TargetCreate(BaseModel):
    name: str
    description: str
    keywords: list[str] = []
    relevance_threshold: float = 0.3


class FilterCreate(BaseModel):
    name: str
    prompt_template: str
    severity: str = "warn"


class AnalyzeRequest(BaseModel):
    system_id: str | None = None
    target_id: str | None = None


def _preferred_intelligence_system(db: DBSession, workspace_id: str, requested_id: str | None = None) -> System | None:
    q = db.query(System).filter(System.workspace_id == workspace_id)
    if requested_id:
        return q.filter(System.id == requested_id).first()
    systems = q.all()
    marked = preferred_intelligence_system(systems)
    if marked is not None:
        return marked
    for system in systems:
        if (system.flow_definition or {}).get("variant") == "intelligence":
            return system
    return None


# ── Feeds ──

@router.post("/feeds")
async def create_feed(
    req: FeedCreate,
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    feed = FeedSource(
        id=str(uuid.uuid4()),
        workspace_id=workspace.id,
        name=req.name,
        url=req.url,
        category=req.category,
        refresh_interval=req.refresh_interval,
    )
    db.add(feed)
    db.commit()
    return {"id": feed.id, "name": feed.name, "status": "created"}


@router.get("/feeds")
async def list_feeds(
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    rows = (
        db.query(FeedSource)
        .filter(FeedSource.workspace_id == workspace.id)
        .order_by(FeedSource.created_at.desc())
        .all()
    )
    return {
        "feeds": [
            {
                "id": f.id, "name": f.name, "url": f.url,
                "category": f.category, "active": f.active,
                "article_count": f.article_count,
                "last_fetched": f.last_fetched.isoformat() if f.last_fetched else None,
            }
            for f in rows
        ]
    }


@router.delete("/feeds/{feed_id}")
async def delete_feed(
    feed_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    feed = db.query(FeedSource).filter(
        FeedSource.id == feed_id,
        FeedSource.workspace_id == workspace.id,
    ).first()
    if feed:
        db.query(FeedArticle).filter(
            FeedArticle.source_id == feed.id,
            FeedArticle.workspace_id == workspace.id,
        ).delete(synchronize_session=False)
        db.delete(feed)
        db.commit()
    return {"deleted": True}


# ── Targets ──

@router.post("/targets")
async def create_target(
    req: TargetCreate,
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    target = SemanticTarget(
        id=str(uuid.uuid4()),
        workspace_id=workspace.id,
        name=req.name,
        description=req.description,
        keywords=req.keywords,
        relevance_threshold=req.relevance_threshold,
    )
    db.add(target)
    db.commit()
    return {"id": target.id, "name": target.name}


@router.get("/targets")
async def list_targets(
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    rows = db.query(SemanticTarget).filter(
        SemanticTarget.active == True,  # noqa: E712
        SemanticTarget.workspace_id == workspace.id,
    ).all()
    return {
        "targets": [
            {"id": t.id, "name": t.name, "description": t.description,
             "keywords": t.keywords, "relevance_threshold": t.relevance_threshold}
            for t in rows
        ]
    }


# ── Safety Filters ──

@router.post("/filters")
async def create_filter(
    req: FilterCreate,
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    f = SafetyFilter(
        id=str(uuid.uuid4()),
        workspace_id=workspace.id,
        name=req.name,
        prompt_template=req.prompt_template,
        severity=req.severity,
    )
    db.add(f)
    db.commit()
    return {"id": f.id, "name": f.name}


@router.get("/filters")
async def list_filters(
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    rows = db.query(SafetyFilter).filter(
        SafetyFilter.active == True,  # noqa: E712
        SafetyFilter.workspace_id == workspace.id,
    ).all()
    return {
        "filters": [
            {"id": f.id, "name": f.name, "prompt_template": f.prompt_template, "severity": f.severity}
            for f in rows
        ]
    }


# ── Articles ──

@router.get("/articles")
async def list_articles(
    source_id: str = None,
    min_relevance: float = 0.0,
    limit: int = 50,
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    articles = get_articles(
        db,
        source_id=source_id,
        min_relevance=min_relevance,
        limit=limit,
        workspace_id=workspace.id,
    )
    return {"articles": articles}


# ── Batch ──

@router.post("/analyze")
async def trigger_batch(
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    body: AnalyzeRequest | None = Body(default=None),
    db: DBSession = Depends(get_db),
):
    body = body or AnalyzeRequest()
    authorized_system = _preferred_intelligence_system(db, workspace.id, body.system_id)
    if authorized_system is not None:
        enforce_system_engine_run(
            db,
            user=user,
            workspace=workspace,
            system=authorized_system,
            source="intelligence.analyze",
        )
    authorized_system_id = authorized_system.id if authorized_system is not None else body.system_id
    collection_slug = workspace_intelligence_profile(workspace).collection_slug

    async def stream():
        db = SessionLocal()
        run: Run | None = None
        invocation: SkillInvocation | None = None
        invocation_cost: SkillInvocationCostEvidence | None = None
        events: list[dict] = []
        started = time.monotonic()
        had_error = False
        try:
            system = _preferred_intelligence_system(db, workspace.id, authorized_system_id)
            if body.system_id and not system:
                event = {
                    "type": "batch_error",
                    "message": "System not found in current workspace",
                    "system_id": body.system_id,
                }
                yield f"data: {json.dumps(event)}\n\n"
                return
            if system:
                run = Run(
                    id=str(uuid.uuid4()),
                    workspace_id=workspace.id,
                    initiated_by_user_id=user.id,
                    system_id=system.id,
                    capability_id=system.capability_id,
                    input_ref={
                        "source": "intelligence.analyze",
                        "target_id": body.target_id,
                        "workspace_slug": workspace.slug,
                    },
                    output_ref={},
                    status="running",
                    started_at=datetime.utcnow(),
                    trigger="manual",
                )
                db.add(run)
                db.commit()
                execution_evidence = capture_skill_execution_evidence(
                    db,
                    workspace_id=workspace.id,
                    skill_slug="intelligence_batch_v1",
                )
                invocation_cost = resolve_skill_invocation_cost(
                    db,
                    workspace_id=workspace.id,
                    skill_id=execution_evidence.skill_id,
                    skill_slug=execution_evidence.skill_slug,
                )
                invocation = SkillInvocation(
                    id=str(uuid.uuid4()),
                    run_id=run.id,
                    skill_id=execution_evidence.skill_id,
                    skill_slug=execution_evidence.skill_slug,
                    execution_snapshot=execution_evidence.execution_snapshot,
                    input_ref={"target_id": body.target_id, "workspace_id": workspace.id},
                    status="running",
                    started_at=datetime.utcnow(),
                    metrics={"cost_evidence": invocation_cost.evidence},
                    cost_measured=False,
                )
                db.add(invocation)
                db.commit()
                yield f"data: {json.dumps({'type': 'run_started', 'run_id': run.id, 'system_id': system.id})}\n\n"

            async for event in run_batch(target_id=body.target_id, workspace_id=workspace.id):
                if run:
                    event = {**event, "run_id": run.id, "system_id": run.system_id}
                events.append(event)
                if event.get("type") == "batch_error":
                    had_error = True
                yield f"data: {json.dumps(event)}\n\n"

            if run and invocation:
                dashboard_payload = get_dashboard_data(db, workspace_id=workspace.id)
                knowledge_sync = {"status": "skipped"}
                sync_started = {
                    "type": "knowledge_sync_started",
                    "collection_slug": collection_slug,
                    "run_id": run.id,
                    "system_id": run.system_id,
                }
                events.append(sync_started)
                yield f"data: {json.dumps(sync_started)}\n\n"
                try:
                    knowledge_sync = await sync_intelligence_to_knowledge(
                        db,
                        workspace,
                        dashboard_payload=dashboard_payload,
                    )
                    sync_event = {
                        "type": "knowledge_sync_completed",
                        "run_id": run.id,
                        "system_id": run.system_id,
                        **knowledge_sync,
                    }
                except Exception as sync_error:  # noqa: BLE001
                    knowledge_sync = {
                        "status": "error",
                        "collection_slug": collection_slug,
                        "error": str(sync_error),
                    }
                    sync_event = {
                        "type": "knowledge_sync_error",
                        "run_id": run.id,
                        "system_id": run.system_id,
                        **knowledge_sync,
                    }
                events.append(sync_event)
                yield f"data: {json.dumps(sync_event)}\n\n"
                duration_ms = (time.monotonic() - started) * 1000
                invocation.status = "failed" if had_error else "completed"
                invocation.output_ref = {
                    "events": events[-25:],
                    "dashboard": {
                        "kpis": dashboard_payload.get("kpis"),
                        "synthesis": dashboard_payload.get("synthesis"),
                    },
                    "knowledge_sync": knowledge_sync,
                }
                invocation.completed_at = datetime.utcnow()
                invocation.latency_ms = duration_ms
                invocation.cost = invocation_cost.cost if invocation_cost else 0.0
                invocation.cost_measured = bool(
                    invocation_cost and invocation_cost.cost_measured
                )
                run.status = "failed" if had_error else "completed"
                run.completed_at = datetime.utcnow()
                run.duration_ms = duration_ms
                run.decision = "needs_review" if had_error else "brief_ready"
                run.confidence = 0.62 if had_error else 0.82
                run.cost_internal = (
                    invocation.cost if invocation.cost_measured is True else None
                )
                run.efficiency = 1.0 if not had_error else 0.0
                run.output_ref = {
                    "rag_context": {
                        "kind": "open_intelligence_rss",
                        "workspace_id": workspace.id,
                        "article_count": (dashboard_payload.get("kpis") or {}).get("total_articles", 0),
                    },
                    "intelligence_dashboard": dashboard_payload,
                    "reference_synthesis": dashboard_payload.get("synthesis"),
                    "knowledge_sync": knowledge_sync,
                    "events": events[-25:],
                }
                if had_error:
                    run.error = "intelligence_batch_error"
                db.commit()
                yield f"data: {json.dumps({'type': 'run_completed', 'run_id': run.id, 'status': run.status, 'progress': 100})}\n\n"
        except Exception as exc:  # noqa: BLE001
            if run:
                run.status = "failed"
                run.completed_at = datetime.utcnow()
                run.duration_ms = (time.monotonic() - started) * 1000
                run.error = str(exc)[:500]
                db.commit()
            yield f"data: {json.dumps({'type': 'batch_error', 'message': str(exc)})}\n\n"
        finally:
            db.close()
            yield "data: [DONE]\n\n"
    return StreamingResponse(stream(), media_type="text/event-stream")


# ── Dashboard ──

@router.get("/dashboard")
async def dashboard(
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    return get_dashboard_data(db, workspace_id=workspace.id)


# ── Scheduler ──

@router.get("/scheduler")
async def scheduler_status(
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    """The scheduler as this workspace sees it.

    Workspace-scoped rather than platform-admin only: every News Lab reader
    needs to know whether its watch refreshes on its own. The process-wide
    part is deployment configuration; the rest is read from this workspace's
    own feeds only.
    """
    from sqlalchemy import func

    from app.services.intelligence.scheduler import is_running

    active_feeds, last_fetched = (
        db.query(func.count(FeedSource.id), func.max(FeedSource.last_fetched))
        .filter(FeedSource.workspace_id == workspace.id, FeedSource.active == True)  # noqa: E712
        .one()
    )
    return {
        "running": is_running(),
        "enabled": settings.intelligence_scheduler_enabled,
        "interval_seconds": settings.intelligence_scheduler_interval_seconds,
        "max_articles": settings.intelligence_batch_max_articles,
        "retry_skipped": settings.intelligence_batch_retry_skipped,
        "safety_check_enabled": settings.intelligence_batch_safety_check_enabled,
        "workspace_active_feeds": int(active_feeds or 0),
        "workspace_last_fetched": last_fetched.isoformat() if last_fetched else None,
    }


# ── Watch Systems ──

def _watch_row(system: System) -> dict:
    return {
        "id": system.id,
        "name": system.name,
        "status": system.status,
        "objective": system.objective,
        "template_id": template_id_of(system),
        "created_at": system.created_at.isoformat() if system.created_at else None,
        "updated_at": system.updated_at.isoformat() if system.updated_at else None,
    }


def _watch_capability(db: DBSession) -> Capability | None:
    from app.services.systems.bootstrap import INTELLIGENCE_CAPABILITY_SLUG

    return db.query(Capability).filter(Capability.slug == INTELLIGENCE_CAPABILITY_SLUG).first()


def _system_admin_legacy(db: DBSession, *, user: User, workspace: Workspace) -> bool:
    return legacy_object_action_allowed(
        db,
        user=user,
        workspace=workspace,
        resource_kind="system",
        action="admin",
    )


@router.get("/watch")
async def list_watch_systems(
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """The workspace's Intelligence Systems, and whether this user may create one.

    Only Systems carrying the intelligence marker (or its legacy template)
    are listed: never a fallback list of unrelated Systems.
    """
    enforce_action(
        db,
        user=user,
        workspace=workspace,
        resource_kind="system",
        action="read",
        legacy_allowed=True,
        resource_attrs={"scope": "collection"},
    )
    systems = (
        db.query(System)
        .filter(System.workspace_id == workspace.id, System.status != "retired")
        .order_by(System.updated_at.desc())
        .all()
    )
    capability = _watch_capability(db)
    can_create = capability is not None and resolve_action(
        db,
        user=user,
        workspace=workspace,
        resource_kind="system",
        action="admin",
        legacy_allowed=_system_admin_legacy(db, user=user, workspace=workspace),
        resource_attrs={"capability_id": capability.id},
        audit_shadow_diff=False,
        audit_shadow_evidence=False,
    ).effective_allowed
    return {
        "systems": [_watch_row(system) for system in intelligence_systems(systems)],
        "can_create": bool(can_create),
        "template_id": INTELLIGENCE_TEMPLATE_ID,
    }


@router.post("/watch")
async def create_watch_system(
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Create the workspace's News Lab System on demand (idempotent).

    Same right as creating any System. A workspace that already has a watch
    gets it back; an earlier unmarked News Lab seed is adopted, not duplicated.
    """
    from app.services.systems.bootstrap import ensure_intelligence_system_default

    capability = _watch_capability(db)
    if capability is None:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "intelligence_capability_missing",
                "message": "The intelligence capability is not in the catalog yet.",
            },
        )
    enforce_action(
        db,
        user=user,
        workspace=workspace,
        resource_kind="system",
        action="admin",
        legacy_allowed=_system_admin_legacy(db, user=user, workspace=workspace),
        resource_attrs={"capability_id": capability.id},
    )
    existing = preferred_intelligence_system(
        db.query(System)
        .filter(System.workspace_id == workspace.id, System.status != "retired")
        .all()
    )
    if existing is not None:
        return {"system": _watch_row(existing), "created": False}
    system = ensure_intelligence_system_default(db, workspace.id)
    if system is None:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "intelligence_capability_missing",
                "message": "The intelligence capability is not in the catalog yet.",
            },
        )
    return {"system": _watch_row(system), "created": True}
