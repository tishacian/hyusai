"""Canonical /impact endpoints — aggregates for the Hypervisor.

Aggregates are computed live from `runs` if no precomputed `impacts` row
is found. The cockpit hits these to render the Balance Sheet hero, the
Capability portfolio table and the per-System ROI tiles.
"""
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session as DBSession

from app.core.auth import get_current_workspace
from app.db.base import get_db
from app.models.capability import Capability
from app.models.run import Run
from app.models.system import System
from app.models.workspace import Workspace
from app.services.catalog_visibility import visible_capabilities, workspace_catalog_policy

router = APIRouter()


def _period_start(period: str) -> Optional[datetime]:
    now = datetime.utcnow()
    if period == "qtd":
        q = (now.month - 1) // 3
        return datetime(now.year, q * 3 + 1, 1)
    if period == "mtd":
        return datetime(now.year, now.month, 1)
    if period == "wtd":
        return now - timedelta(days=now.weekday())
    if period == "rolling_30d":
        return now - timedelta(days=30)
    if period == "rolling_90d":
        return now - timedelta(days=90)
    return None


def _aggregate(db: DBSession, workspace_id: str, *, system_id: Optional[str] = None, capability_id: Optional[str] = None, period: str = "qtd") -> Dict[str, Any]:
    q = db.query(
        func.count(Run.id),
        func.sum(Run.cost_internal),
        func.sum(Run.value_estimated),
        func.sum(Run.revenue_allocated),
        func.avg(Run.confidence),
        func.avg(Run.efficiency),
    ).filter(Run.workspace_id == workspace_id, Run.status == "completed")

    start = _period_start(period)
    if start:
        q = q.filter(Run.completed_at >= start)
    if system_id:
        q = q.filter(Run.system_id == system_id)
    if capability_id:
        q = q.filter(Run.capability_id == capability_id)

    count, cost, value, revenue, confidence, efficiency = q.one()

    cost_v = float(cost or 0)
    value_v = float(value or 0)
    revenue_v = float(revenue or 0)
    roi = ((value_v - cost_v) / cost_v) if cost_v else None
    return {
        "runs_count": int(count or 0),
        "total_cost": cost_v,
        "estimated_value": value_v,
        "total_revenue": revenue_v,
        "roi": roi,
        "avg_confidence": float(confidence) if confidence is not None else None,
        "avg_efficiency": float(efficiency) if efficiency is not None else None,
    }


@router.get("/portfolio")
async def portfolio_impact(
    period: str = Query("qtd"),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    return {
        "scope": "portfolio",
        "period": period,
        **_aggregate(db, workspace.id, period=period),
    }


@router.get("/by-capability")
async def by_capability(
    period: str = Query("qtd"),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    caps: List[Capability] = (
        db.query(Capability)
        .filter((Capability.workspace_id == workspace.id) | (Capability.workspace_id.is_(None)))
        .all()
    )
    policy = workspace_catalog_policy(workspace)
    caps = visible_capabilities(caps, workspace, policy)
    rows = []
    for c in caps:
        agg = _aggregate(db, workspace.id, capability_id=c.id, period=period)
        if agg["runs_count"] == 0:
            continue
        rows.append({
            "capability_id": c.id,
            "slug": c.slug,
            "name": c.name,
            "tier": c.tier,
            **agg,
        })
    return {"period": period, "items": rows}


@router.get("/by-system")
async def by_system(
    period: str = Query("qtd"),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    systems = db.query(System).filter(System.workspace_id == workspace.id).all()
    rows = []
    for s in systems:
        agg = _aggregate(db, workspace.id, system_id=s.id, period=period)
        rows.append({
            "system_id": s.id,
            "name": s.name,
            "status": s.status,
            "capability_id": s.capability_id,
            **agg,
        })
    return {"period": period, "items": rows}
