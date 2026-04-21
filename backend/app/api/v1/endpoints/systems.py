"""Canonical /systems endpoints — supersede /agents.

A System is the deployable composition (Objective + Capability + Context +
Skills + Policies). `POST /systems/{id}/runs` enqueues a Run; the actual
execution loop lives in `app.services.run_engine`.
"""
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session as DBSession

from app.core.auth import get_current_workspace
from app.db.base import get_db
from app.models.run import Run
from app.models.system import System
from app.models.workspace import Workspace
from app.services.run_engine import schedule_run

router = APIRouter()


# ---------------- Pydantic ----------------
class SystemCreate(BaseModel):
    name: str
    objective: str = ""
    capability_id: Optional[str] = None
    skill_ids: List[str] = []
    flow_definition: Dict[str, Any] = {}
    execution_mode: str = "real_time_decision"
    execution_profile: Optional[Dict[str, Any]] = None
    coordination_pattern: str = "single_agent"
    control_policy_id: Optional[str] = None
    adaptive_policy_id: Optional[str] = None
    context_id: Optional[str] = None
    status: str = "draft"
    default_prompt_type: Optional[str] = None
    default_model: Optional[str] = None
    retrieval_mode_default: Optional[str] = None


class SystemUpdate(BaseModel):
    name: Optional[str] = None
    objective: Optional[str] = None
    capability_id: Optional[str] = None
    skill_ids: Optional[List[str]] = None
    flow_definition: Optional[Dict[str, Any]] = None
    execution_mode: Optional[str] = None
    execution_profile: Optional[Dict[str, Any]] = None
    coordination_pattern: Optional[str] = None
    control_policy_id: Optional[str] = None
    adaptive_policy_id: Optional[str] = None
    context_id: Optional[str] = None
    status: Optional[str] = None
    default_prompt_type: Optional[str] = None
    default_model: Optional[str] = None
    retrieval_mode_default: Optional[str] = None


class RunCreate(BaseModel):
    input_ref: Dict[str, Any] = {}
    trigger: str = "manual"


# ---------------- Helpers ----------------
def _serialize(s: System) -> Dict[str, Any]:
    return {
        "id": s.id,
        "workspace_id": s.workspace_id,
        "name": s.name,
        "objective": s.objective,
        "capability_id": s.capability_id,
        "skill_ids": s.skill_ids or [],
        "flow_definition": s.flow_definition or {},
        "execution_mode": s.execution_mode,
        "execution_profile": getattr(s, "execution_profile", None) or {},
        "coordination_pattern": s.coordination_pattern,
        "control_policy_id": s.control_policy_id,
        "adaptive_policy_id": s.adaptive_policy_id,
        "context_id": s.context_id,
        "status": s.status,
        "default_prompt_type": getattr(s, "default_prompt_type", None),
        "default_model": getattr(s, "default_model", None),
        "retrieval_mode_default": getattr(s, "retrieval_mode_default", None),
        "created_by": s.created_by,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "updated_at": s.updated_at.isoformat() if s.updated_at else None,
    }


# ---------------- CRUD ----------------
@router.get("")
async def list_systems(
    status: Optional[str] = None,
    limit: int = 100,
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    q = db.query(System).filter(System.workspace_id == workspace.id)
    if status:
        q = q.filter(System.status == status)
    rows = q.order_by(System.updated_at.desc()).limit(limit).all()
    return {"systems": [_serialize(s) for s in rows]}


@router.post("")
async def create_system(
    body: SystemCreate,
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    s = System(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name=body.name,
        objective=body.objective,
        capability_id=body.capability_id,
        skill_ids=body.skill_ids,
        flow_definition=body.flow_definition,
        execution_mode=body.execution_mode,
        execution_profile=body.execution_profile or None,
        coordination_pattern=body.coordination_pattern,
        control_policy_id=body.control_policy_id,
        adaptive_policy_id=body.adaptive_policy_id,
        context_id=body.context_id,
        status=body.status,
        default_prompt_type=body.default_prompt_type,
        default_model=body.default_model,
        retrieval_mode_default=body.retrieval_mode_default or "auto",
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return _serialize(s)


@router.get("/{system_id}")
async def get_system(
    system_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    s = db.query(System).filter(System.id == system_id, System.workspace_id == workspace.id).first()
    if not s:
        raise HTTPException(404, "System not found")
    return _serialize(s)


@router.patch("/{system_id}")
async def update_system(
    system_id: str,
    body: SystemUpdate,
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    s = db.query(System).filter(System.id == system_id, System.workspace_id == workspace.id).first()
    if not s:
        raise HTTPException(404, "System not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(s, k, v)
    db.commit()
    db.refresh(s)
    return _serialize(s)


@router.delete("/{system_id}", status_code=204)
async def delete_system(
    system_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    s = db.query(System).filter(System.id == system_id, System.workspace_id == workspace.id).first()
    if not s:
        raise HTTPException(404, "System not found")
    db.delete(s)
    db.commit()
    return None


# ---------------- Runs ----------------
@router.post("/{system_id}/runs")
async def trigger_run(
    system_id: str,
    body: RunCreate,
    background_tasks: BackgroundTasks,
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    s = db.query(System).filter(System.id == system_id, System.workspace_id == workspace.id).first()
    if not s:
        raise HTTPException(404, "System not found")

    run = Run(
        id=str(uuid4()),
        workspace_id=workspace.id,
        system_id=s.id,
        capability_id=s.capability_id,
        input_ref=body.input_ref,
        status="pending",
        started_at=datetime.utcnow(),
        trigger=body.trigger,
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    # Hand the actual execution to the canonical run_engine (Phase 6).
    background_tasks.add_task(schedule_run, run.id)
    return {"id": run.id, "status": run.status, "system_id": s.id, "trigger": body.trigger}


@router.get("/{system_id}/runs")
async def list_system_runs(
    system_id: str,
    limit: int = 50,
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    rows = (
        db.query(Run)
        .filter(Run.workspace_id == workspace.id, Run.system_id == system_id)
        .order_by(Run.started_at.desc())
        .limit(limit)
        .all()
    )
    return {
        "runs": [
            {
                "id": r.id,
                "status": r.status,
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "completed_at": r.completed_at.isoformat() if r.completed_at else None,
                "duration_ms": r.duration_ms,
                "decision": r.decision,
                "confidence": r.confidence,
                "value_estimated": r.value_estimated,
                "cost_internal": r.cost_internal,
                "efficiency": r.efficiency,
                "trigger": r.trigger,
            }
            for r in rows
        ]
    }
