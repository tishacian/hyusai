"""Canonical /impact endpoints — aggregates for the Hypervisor.

Aggregates are computed live from `runs` if no precomputed `impacts` row
is found. The cockpit hits these to render the Balance Sheet hero, the
Capability portfolio table and the per-System ROI tiles.
"""
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func
from sqlalchemy.orm import Session as DBSession

from app.core.auth import get_current_user, get_current_workspace
from app.db.base import get_db
from app.models.capability import Capability
from app.models.run import Run
from app.models.system import System
from app.models.user import User
from app.models.workspace import Workspace
from app.services.catalog_visibility import visible_capabilities, workspace_catalog_policy
from app.services.capability_access import readable_capabilities
from app.services.run_access import readable_runs
from app.services.system_access import readable_systems

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
    evidenced_value = case(
        (
            Run.value_source.in_(("auto", "operator")),
            Run.value_estimated,
        ),
        else_=None,
    )
    q = db.query(
        func.count(Run.id),
        func.sum(Run.cost_internal),
        func.sum(evidenced_value),
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

    capability_count_q = db.query(func.count(func.distinct(Run.capability_id))).filter(
        Run.workspace_id == workspace_id,
        Run.status == "completed",
        Run.capability_id.isnot(None),
    )
    if start:
        capability_count_q = capability_count_q.filter(Run.completed_at >= start)
    if system_id:
        capability_count_q = capability_count_q.filter(Run.system_id == system_id)
    if capability_id:
        capability_count_q = capability_count_q.filter(Run.capability_id == capability_id)
    capabilities_count = int(capability_count_q.scalar() or 0)

    cost_v = float(cost) if cost is not None else None
    value_v = float(value) if value is not None else None
    revenue_v = float(revenue) if revenue is not None else None
    roi = (
        (value_v - cost_v) / cost_v
        if cost_v not in {None, 0.0} and value_v is not None
        else None
    )
    return {
        "runs_count": int(count or 0),
        "capabilities_count": capabilities_count,
        "total_cost": cost_v,
        "estimated_value": value_v,
        "total_revenue": revenue_v,
        "roi": roi,
        "avg_confidence": float(confidence) if confidence is not None else None,
        "avg_efficiency": float(efficiency) if efficiency is not None else None,
        "measurement_states": {
            "total_cost": "available" if cost_v is not None else "not_measured",
            "estimated_value": "available" if value_v is not None else "not_measured",
            "total_revenue": "available" if revenue_v is not None else "not_measured",
        },
    }


def _aggregate_for_scope(
    db: DBSession,
    workspace_id: str,
    *,
    scope: str,
    target_id: Optional[str],
    period: str,
) -> Dict[str, Any]:
    """Route one aggregate to the identifier owned by its declared scope.

    Keeping this conversion in one place prevents a System id from being
    silently applied to ``Run.capability_id`` by simulation endpoints.
    """

    if scope == "system":
        return _aggregate(
            db,
            workspace_id,
            system_id=target_id,
            period=period,
        )
    if scope == "capability":
        return _aggregate(
            db,
            workspace_id,
            capability_id=target_id,
            period=period,
        )
    if scope == "portfolio":
        return _aggregate(db, workspace_id, period=period)
    raise ValueError("scope must be portfolio, capability or system")


def _aggregate_visible_runs(runs: List[Run]) -> Dict[str, Any]:
    """Compute impact only after canonical object authorization."""

    def _sum_or_none(values: list[float]) -> Optional[float]:
        return sum(values) if values else None

    costs = [float(row.cost_internal) for row in runs if row.cost_internal is not None]
    values = [
        float(row.value_estimated)
        for row in runs
        if row.value_source in {"auto", "operator"}
        and row.value_estimated is not None
    ]
    revenues = [
        float(row.revenue_allocated)
        for row in runs
        if row.revenue_allocated is not None
    ]
    confidences = [float(row.confidence) for row in runs if row.confidence is not None]
    efficiencies = [float(row.efficiency) for row in runs if row.efficiency is not None]
    cost = _sum_or_none(costs)
    value = _sum_or_none(values)
    revenue = _sum_or_none(revenues)
    roi = (
        (value - cost) / cost
        if cost not in {None, 0.0} and value is not None
        else None
    )
    return {
        "runs_count": len(runs),
        "capabilities_count": len({row.capability_id for row in runs if row.capability_id}),
        "total_cost": cost,
        "estimated_value": value,
        "total_revenue": revenue,
        "roi": roi,
        "avg_confidence": sum(confidences) / len(confidences) if confidences else None,
        "avg_efficiency": sum(efficiencies) / len(efficiencies) if efficiencies else None,
        "measurement_states": {
            "total_cost": "available" if cost is not None else "not_measured",
            "estimated_value": "available" if value is not None else "not_measured",
            "total_revenue": "available" if revenue is not None else "not_measured",
        },
    }


def _readable_completed_runs(
    db: DBSession,
    *,
    workspace: Workspace,
    user: User,
    period: str,
) -> List[Run]:
    query = db.query(Run).filter(
        Run.workspace_id == workspace.id,
        Run.status == "completed",
    )
    start = _period_start(period)
    if start is not None:
        query = query.filter(Run.completed_at >= start)
    return readable_runs(
        db,
        runs=query.order_by(Run.completed_at.desc(), Run.id.asc()).all(),
        user=user,
        workspace=workspace,
    )


@router.get("/portfolio")
async def portfolio_impact(
    period: str = Query("qtd"),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    runs = _readable_completed_runs(db, workspace=workspace, user=user, period=period)
    return {
        "scope": "portfolio",
        "period": period,
        **_aggregate_visible_runs(runs),
    }


@router.get("/by-capability")
async def by_capability(
    period: str = Query("qtd"),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    caps: List[Capability] = (
        db.query(Capability)
        .filter((Capability.workspace_id == workspace.id) | (Capability.workspace_id.is_(None)))
        .all()
    )
    policy = workspace_catalog_policy(workspace)
    caps = visible_capabilities(caps, workspace, policy)
    caps = readable_capabilities(
        db,
        capabilities=caps,
        user=user,
        workspace=workspace,
    )
    runs = _readable_completed_runs(db, workspace=workspace, user=user, period=period)
    rows = []
    for c in caps:
        agg = _aggregate_visible_runs([row for row in runs if row.capability_id == c.id])
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
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    systems = db.query(System).filter(System.workspace_id == workspace.id).all()
    systems = readable_systems(
        db,
        systems=systems,
        user=user,
        workspace=workspace,
    )
    runs = _readable_completed_runs(db, workspace=workspace, user=user, period=period)
    rows = []
    for s in systems:
        agg = _aggregate_visible_runs([row for row in runs if row.system_id == s.id])
        rows.append({
            "system_id": s.id,
            "name": s.name,
            "status": s.status,
            "capability_id": s.capability_id,
            **agg,
        })
    return {"period": period, "items": rows}
