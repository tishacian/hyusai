"""Canonical /hypervisor endpoints — Balance Sheet, Recommendations, What-If.

Composes data from `impact`, `runs`, `capabilities` and `decisions` to feed
the executive cockpit. Designed to be a single roundtrip per surface.
"""
from typing import Any, Dict, List, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session as DBSession

from app.api.v1.endpoints.impact import _aggregate
from app.core.auth import get_current_workspace
from app.db.base import get_db
from app.models.capability import Capability
from app.models.decision import Decision
from app.models.run import Run
from app.models.workspace import Workspace

router = APIRouter()


@router.get("/balance-sheet")
async def balance_sheet(
    period: str = Query("qtd"),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    portfolio = _aggregate(db, workspace.id, period=period)

    caps: List[Capability] = (
        db.query(Capability)
        .filter((Capability.workspace_id == workspace.id) | (Capability.workspace_id.is_(None)))
        .order_by(Capability.tier, Capability.name)
        .all()
    )
    capability_rows = []
    for c in caps:
        agg = _aggregate(db, workspace.id, capability_id=c.id, period=period)
        if agg["runs_count"] == 0:
            continue
        capability_rows.append({
            "capability_id": c.id,
            "slug": c.slug,
            "name": c.name,
            "tier": c.tier,
            "trend": [],  # Phase 3 wires real sparkline values from Impact rows.
            **agg,
        })

    return {
        "period": period,
        "portfolio": portfolio,
        "capabilities": capability_rows,
        "signals": _signals(db, workspace.id),
    }


def _signals(db: DBSession, workspace_id: str) -> List[Dict[str, Any]]:
    recent_runs = (
        db.query(Run)
        .filter(Run.workspace_id == workspace_id)
        .order_by(Run.started_at.desc())
        .limit(20)
        .all()
    )
    out: List[Dict[str, Any]] = []
    for r in recent_runs:
        tone = "neutral"
        if r.status == "failed":
            tone = "neg"
        elif r.confidence is not None and r.confidence < 0.6:
            tone = "warn"
        elif r.value_estimated and r.cost_internal and r.value_estimated > 2 * r.cost_internal:
            tone = "pos"
        out.append({
            "id": r.id,
            "tone": tone,
            "kind": r.status,
            "system_id": r.system_id,
            "timestamp": r.started_at.isoformat() if r.started_at else None,
            "label": _signal_label(r),
        })
    return out


def _signal_label(r: Run) -> str:
    if r.status == "failed":
        return f"Run failed · {r.error or 'unknown error'}"
    if r.status == "completed":
        if r.value_estimated and r.cost_internal:
            roi = (r.value_estimated - r.cost_internal) / r.cost_internal if r.cost_internal else None
            if roi is not None and roi > 1.5:
                return f"High-yield outcome · ROI {roi:.1%}"
        return f"Run completed · decision {r.decision or '—'}"
    return f"Run {r.status}"


# ---- Recommendations + What-If ----
class WhatIfRequest(BaseModel):
    scope: str = "capability"
    target_id: Optional[str] = None
    levers: Dict[str, Any] = {}


@router.get("/recommendations")
async def list_recommendations(
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    rows = (
        db.query(Decision)
        .filter(Decision.workspace_id == workspace.id, Decision.kind == "recommendation")
        .order_by(Decision.created_at.desc())
        .limit(50)
        .all()
    )
    return {"items": [{
        "id": d.id,
        "scope": d.scope,
        "target_id": d.target_id,
        "title": d.title,
        "rationale": d.rationale or {},
        "impact_estimate": d.impact_estimate or {},
        "status": d.status,
        "created_at": d.created_at.isoformat() if d.created_at else None,
    } for d in rows]}


@router.post("/what-if")
async def simulate_what_if(
    body: WhatIfRequest,
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    """Deterministic client-side feel: we compute a delta-projection from the
    current aggregates without touching the runtime. Phase 4 will route the
    same payload through the real adaptive policy simulator."""
    base = _aggregate(db, workspace.id, capability_id=body.target_id, period="qtd")
    levers = body.levers or {}
    cost_mult = float(levers.get("cost_factor", 1.0))
    value_mult = float(levers.get("value_factor", 1.0))
    latency_mult = float(levers.get("latency_factor", 1.0))

    projected_cost = base["total_cost"] * cost_mult
    projected_value = base["estimated_value"] * value_mult
    projected_roi = ((projected_value - projected_cost) / projected_cost) if projected_cost else None
    return {
        "scope": body.scope,
        "target_id": body.target_id,
        "base": base,
        "projected": {
            "total_cost": projected_cost,
            "estimated_value": projected_value,
            "roi": projected_roi,
            "latency_index": latency_mult,
        },
    }


@router.get("/decisions")
async def list_decisions(
    status: Optional[str] = None,
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    q = db.query(Decision).filter(Decision.workspace_id == workspace.id)
    if status:
        q = q.filter(Decision.status == status)
    rows = q.order_by(Decision.created_at.desc()).limit(100).all()
    return {"items": [{
        "id": d.id,
        "scope": d.scope,
        "target_id": d.target_id,
        "kind": d.kind,
        "status": d.status,
        "title": d.title,
        "created_at": d.created_at.isoformat() if d.created_at else None,
        "approved_by": d.approved_by,
    } for d in rows]}
