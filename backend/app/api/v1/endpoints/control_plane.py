"""Canonical /control-plane endpoints — Steering Wheel CRUD + simulate.

ControlPolicy + AdaptivePolicy are mounted here as a single concept.
`POST /simulate` returns the projected impact of a lever change without
persisting anything (used by the Steering cockpit's <300ms preview).
"""
from typing import Any, Dict, List, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session as DBSession

from app.api.v1.endpoints.impact import _aggregate
from app.core.auth import get_current_workspace
from app.db.base import get_db
from app.models.policy import AdaptivePolicy, ControlPolicy
from app.models.workspace import Workspace

router = APIRouter()


# ---- Control policies ----
class ControlPolicyBody(BaseModel):
    name: str = "default"
    scope: str = "system"
    target_id: Optional[str] = None
    max_cost_per_decision: Optional[float] = None
    max_latency_ms: Optional[float] = None
    mandatory_hitl_if_confidence_below: Optional[float] = None
    allowed_models: List[str] = []
    allowed_skills: List[str] = []
    extra: Dict[str, Any] = {}


def _serialize_cp(p: ControlPolicy) -> Dict[str, Any]:
    return {
        "id": p.id,
        "name": p.name,
        "scope": p.scope,
        "target_id": p.target_id,
        "max_cost_per_decision": p.max_cost_per_decision,
        "max_latency_ms": p.max_latency_ms,
        "mandatory_hitl_if_confidence_below": p.mandatory_hitl_if_confidence_below,
        "allowed_models": p.allowed_models or [],
        "allowed_skills": p.allowed_skills or [],
        "extra": p.extra or {},
    }


@router.get("/policies")
async def list_policies(
    scope: Optional[str] = None,
    target_id: Optional[str] = None,
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    q = db.query(ControlPolicy).filter(ControlPolicy.workspace_id == workspace.id)
    if scope:
        q = q.filter(ControlPolicy.scope == scope)
    if target_id:
        q = q.filter(ControlPolicy.target_id == target_id)
    return {"policies": [_serialize_cp(p) for p in q.all()]}


@router.post("/policies")
async def create_policy(
    body: ControlPolicyBody,
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    p = ControlPolicy(id=str(uuid4()), workspace_id=workspace.id, **body.model_dump())
    db.add(p)
    db.commit()
    db.refresh(p)
    return _serialize_cp(p)


@router.patch("/policies/{policy_id}")
async def update_policy(
    policy_id: str,
    body: ControlPolicyBody,
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    p = db.query(ControlPolicy).filter(
        ControlPolicy.id == policy_id, ControlPolicy.workspace_id == workspace.id
    ).first()
    if not p:
        raise HTTPException(404, "Policy not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(p, k, v)
    db.commit()
    db.refresh(p)
    return _serialize_cp(p)


# ---- Adaptive policies ----
class AdaptivePolicyBody(BaseModel):
    name: str = "default"
    enabled: bool = False
    adaptation_level: str = "moderate"
    triggers: Dict[str, Any] = {}
    allowed_actions: List[str] = []
    constraints: Dict[str, Any] = {}


def _serialize_ap(p: AdaptivePolicy) -> Dict[str, Any]:
    return {
        "id": p.id,
        "name": p.name,
        "enabled": bool(p.enabled),
        "adaptation_level": p.adaptation_level,
        "triggers": p.triggers or {},
        "allowed_actions": p.allowed_actions or [],
        "constraints": p.constraints or {},
    }


@router.get("/adaptive")
async def list_adaptive(
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    rows = db.query(AdaptivePolicy).filter(AdaptivePolicy.workspace_id == workspace.id).all()
    return {"policies": [_serialize_ap(p) for p in rows]}


@router.post("/adaptive")
async def create_adaptive(
    body: AdaptivePolicyBody,
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    p = AdaptivePolicy(id=str(uuid4()), workspace_id=workspace.id, **body.model_dump())
    db.add(p)
    db.commit()
    db.refresh(p)
    return _serialize_ap(p)


# ---- Simulate ----
class SimulateBody(BaseModel):
    scope: str = "capability"
    target_id: Optional[str] = None
    levers: Dict[str, float] = {}


@router.post("/simulate")
async def simulate(
    body: SimulateBody,
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    base = _aggregate(db, workspace.id, capability_id=body.target_id, period="rolling_30d")
    resource = float(body.levers.get("resource", 0.5))   # 0=lean, 1=deep
    velocity = float(body.levers.get("velocity", 0.5))   # 0=thorough, 1=rapid
    autonomy = float(body.levers.get("autonomy", 0.5))   # 0=hitl, 1=full

    cost_factor = 0.6 + 0.8 * resource           # lean cuts cost ~40%, deep adds ~40%
    value_factor = 0.85 + 0.30 * resource        # deep increases value
    latency_factor = 1.6 - 1.0 * velocity        # rapid cuts latency
    risk_factor = 0.4 + 0.6 * autonomy           # full autonomy increases risk

    projected_cost = base["total_cost"] * cost_factor
    projected_value = base["estimated_value"] * value_factor
    projected_roi = ((projected_value - projected_cost) / projected_cost) if projected_cost else None
    return {
        "scope": body.scope,
        "target_id": body.target_id,
        "base": base,
        "projected": {
            "total_cost": projected_cost,
            "estimated_value": projected_value,
            "roi": projected_roi,
            "latency_index": latency_factor,
            "risk_index": risk_factor,
        },
    }
