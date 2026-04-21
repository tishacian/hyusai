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
from app.services.decisions import (
    InvalidTransition,
    accept as sm_accept,
    apply_decision as sm_apply,
    enact_decision,
    reject as sm_reject,
)

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

    # Accept both the canonical 4-lever mental model (resource/velocity/autonomy/risk_tolerance)
    # and the raw factor shortcuts (cost_factor/value_factor/latency_factor) so
    # downstream tools can call this endpoint without knowing the cockpit's
    # lever semantics.
    resource = _as_float(levers.get("resource"), default=None)
    velocity = _as_float(levers.get("velocity"), default=None)
    autonomy = _as_float(levers.get("autonomy"), default=None)
    risk_tol = _as_float(levers.get("risk_tolerance"), default=None)

    cost_mult = _as_float(levers.get("cost_factor"), default=None)
    value_mult = _as_float(levers.get("value_factor"), default=None)
    latency_mult = _as_float(levers.get("latency_factor"), default=None)

    # Derive factors from the canonical levers when no explicit factor is sent.
    # Deep resources add cost but deliver more value; rapid velocity cuts latency
    # at a slight quality cost; high autonomy trims cost (fewer HITL loops) but
    # only when risk tolerance allows for it.
    if cost_mult is None:
        base_cost = 1.0
        if resource is not None:
            base_cost *= 0.65 + 0.75 * resource        # lean -40% → deep +40%
        if autonomy is not None:
            base_cost *= 1.05 - 0.20 * autonomy        # HITL +5% → full −15%
        cost_mult = base_cost

    if value_mult is None:
        base_value = 1.0
        if resource is not None:
            base_value *= 0.85 + 0.35 * resource       # deep +35%
        if risk_tol is not None:
            base_value *= 0.95 + 0.15 * risk_tol       # bolder +15%
        value_mult = base_value

    if latency_mult is None:
        base_latency = 1.0
        if velocity is not None:
            base_latency = 1.55 - 1.10 * velocity      # thorough 1.55× → rapid 0.45×
        value_mult *= 0.95 + 0.05 * (velocity or 0.5) if velocity is not None else 1.0
        latency_mult = max(0.1, base_latency)

    projected_cost = base["total_cost"] * cost_mult
    projected_value = base["estimated_value"] * value_mult
    projected_roi = (
        ((projected_value - projected_cost) / projected_cost) if projected_cost else None
    )
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


def _as_float(v: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if v is None:
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def _serialize_decision(d: Decision, *, full: bool = False) -> dict:
    base = {
        "id": d.id,
        "scope": d.scope,
        "target_id": d.target_id,
        "kind": d.kind,
        "status": d.status,
        "title": d.title,
        "created_at": d.created_at.isoformat() if d.created_at else None,
        "approved_by": d.approved_by,
        "applied_at": d.applied_at.isoformat() if getattr(d, "applied_at", None) else None,
    }
    if full:
        base.update({
            "rationale": d.rationale or {},
            "impact_estimate": d.impact_estimate or {},
            "notes": d.notes or "",
            "approved_at": d.approved_at.isoformat() if d.approved_at else None,
            "applied_by": getattr(d, "applied_by", None),
            "applied_patch": getattr(d, "applied_patch", None) or {},
        })
    return base


class DecisionTransition(BaseModel):
    note: Optional[str] = None
    actor: Optional[str] = None


class DecisionApplyRequest(BaseModel):
    actor: Optional[str] = None
    enact: bool = True
    patch: Optional[Dict[str, Any]] = None


class DecisionCreate(BaseModel):
    scope: str = "capability"
    target_id: Optional[str] = None
    kind: str = "recommendation"
    title: str
    status: str = "proposed"
    rationale: Dict[str, Any] = {}
    impact_estimate: Dict[str, Any] = {}
    notes: Optional[str] = None


@router.get("/decisions")
async def list_decisions(
    status: Optional[str] = None,
    scope: Optional[str] = None,
    kind: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    """Paginated feed of decisions, newest first.

    The Hypervisor cockpit uses this to render the Decisions stream.
    `limit` is clamped to 200 and `offset` supports incremental paging.
    """
    limit = max(1, min(int(limit or 50), 200))
    offset = max(0, int(offset or 0))
    q = db.query(Decision).filter(Decision.workspace_id == workspace.id)
    if status:
        q = q.filter(Decision.status == status)
    if scope:
        q = q.filter(Decision.scope == scope)
    if kind:
        q = q.filter(Decision.kind == kind)
    total = q.count()
    rows = q.order_by(Decision.created_at.desc()).offset(offset).limit(limit).all()
    return {
        "items": [_serialize_decision(d) for d in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.post("/decisions", status_code=201)
async def create_decision(
    body: DecisionCreate,
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    """Create a Decision record — used by cockpit CTAs (Scale, Adjust, …)
    to surface a proposal that an operator can then Accept/Reject/Apply.
    """
    row = Decision(
        id=str(uuid4()),
        workspace_id=workspace.id,
        scope=body.scope,
        target_id=body.target_id,
        kind=body.kind,
        status=body.status or "proposed",
        title=body.title,
        rationale=body.rationale or {},
        impact_estimate=body.impact_estimate or {},
        notes=body.notes or "",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _serialize_decision(row, full=True)


@router.get("/decisions/{decision_id}")
async def get_decision(
    decision_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    d = (
        db.query(Decision)
        .filter(Decision.id == decision_id, Decision.workspace_id == workspace.id)
        .first()
    )
    if not d:
        from fastapi import HTTPException
        raise HTTPException(404, "Decision not found")
    return _serialize_decision(d, full=True)


def _get_decision_or_404(db: DBSession, workspace_id: str, decision_id: str) -> Decision:
    from fastapi import HTTPException
    d = (
        db.query(Decision)
        .filter(Decision.id == decision_id, Decision.workspace_id == workspace_id)
        .first()
    )
    if not d:
        raise HTTPException(404, "Decision not found")
    return d


@router.post("/decisions/{decision_id}/accept")
async def accept_decision(
    decision_id: str,
    body: Optional[DecisionTransition] = None,
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    from fastapi import HTTPException
    d = _get_decision_or_404(db, workspace.id, decision_id)
    try:
        sm_accept(db, d, actor=(body.actor if body else None), note=(body.note if body else None))
    except InvalidTransition as exc:
        raise HTTPException(409, str(exc))
    return _serialize_decision(d, full=True)


@router.post("/decisions/{decision_id}/reject")
async def reject_decision(
    decision_id: str,
    body: Optional[DecisionTransition] = None,
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    from fastapi import HTTPException
    d = _get_decision_or_404(db, workspace.id, decision_id)
    try:
        sm_reject(db, d, actor=(body.actor if body else None), note=(body.note if body else None))
    except InvalidTransition as exc:
        raise HTTPException(409, str(exc))
    return _serialize_decision(d, full=True)


@router.post("/decisions/{decision_id}/apply")
async def apply_decision_endpoint(
    decision_id: str,
    body: Optional[DecisionApplyRequest] = None,
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    from fastapi import HTTPException
    d = _get_decision_or_404(db, workspace.id, decision_id)
    actor = body.actor if body else None
    patch: Dict[str, Any] = {}
    if body and body.patch:
        patch = body.patch
    elif body is None or body.enact:
        patch = enact_decision(db, d)
    try:
        sm_apply(db, d, actor=actor, patch=patch)
    except InvalidTransition as exc:
        raise HTTPException(409, str(exc))
    return _serialize_decision(d, full=True)
