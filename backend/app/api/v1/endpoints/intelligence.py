"""Intelligence API — RSS feeds, analysis, dashboard (scoped by workspace)."""
import json
import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session as DBSession

from app.core.auth import get_current_workspace
from app.db.base import get_db
from app.models.intelligence import FeedSource, SemanticTarget, SafetyFilter
from app.models.workspace import Workspace
from app.services.intelligence.feed_manager import get_articles
from app.services.intelligence.batch import run_batch, get_dashboard_data

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
):
    async def stream():
        async for event in run_batch(workspace_id=workspace.id):
            yield f"data: {json.dumps(event)}\n\n"
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
    return {"running": is_running(), "interval_seconds": 3600}
