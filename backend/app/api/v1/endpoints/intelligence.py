"""Intelligence API — RSS feeds, analysis, dashboard (scoped by workspace)."""
import json
import time
import uuid
from datetime import datetime

from fastapi import APIRouter, Body, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session as DBSession

from app.core.auth import get_current_user, get_current_workspace
from app.core.config import settings
from app.db.base import SessionLocal, get_db
from app.models.intelligence import FeedSource, SafetyFilter, SemanticTarget
from app.models.run import Run, SkillInvocation
from app.models.system import System
from app.models.user import User
from app.models.workspace import Workspace
from app.services.intelligence.batch import get_dashboard_data, run_batch
from app.services.intelligence.feed_manager import get_articles
from app.services.intelligence.knowledge_sync import sync_intelligence_to_knowledge
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
    for system in systems:
        flow = system.flow_definition or {}
        if flow.get("template_id") == "sentinel-ci-intelligence":
            return system
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
                    "collection_slug": "sentinel-ci-open-intelligence",
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
                        "collection_slug": "sentinel-ci-open-intelligence",
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
async def scheduler_status():
    from app.services.intelligence.scheduler import is_running
    return {
        "running": is_running(),
        "enabled": settings.intelligence_scheduler_enabled,
        "interval_seconds": settings.intelligence_scheduler_interval_seconds,
        "max_articles": settings.intelligence_batch_max_articles,
        "retry_skipped": settings.intelligence_batch_retry_skipped,
        "safety_check_enabled": settings.intelligence_batch_safety_check_enabled,
    }
