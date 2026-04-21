"""Canonical /runs endpoints — supersede /traces.

A Run carries the Outcome block. Detail view exposes the SkillInvocation
ledger so the cockpit can drill from the Run timeline down to individual
skill calls.
"""
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DBSession

from app.core.auth import get_current_workspace
from app.core.logging import get_logger
from app.db.base import get_db
from app.models.decision import Decision
from app.models.run import Run, SkillInvocation
from app.models.workspace import Workspace
from app.services.decisions import (
    InvalidTransition,
    accept as accept_decision,
    reject as reject_decision,
)
from app.services.outcome.derive import apply_operator_override
from app.services.run_engine.dag import resume_run_dag

logger = get_logger(__name__)
router = APIRouter()


def _row(r: Run) -> Dict[str, Any]:
    return {
        "id": r.id,
        "system_id": r.system_id,
        "capability_id": r.capability_id,
        "status": r.status,
        "trigger": r.trigger,
        "started_at": r.started_at.isoformat() if r.started_at else None,
        "completed_at": r.completed_at.isoformat() if r.completed_at else None,
        "duration_ms": r.duration_ms,
        "outcome": {
            "decision": r.decision,
            "confidence": r.confidence,
            "value_estimated": r.value_estimated,
            "cost_internal": r.cost_internal,
            "revenue_allocated": r.revenue_allocated,
            "efficiency": r.efficiency,
            "value_source": getattr(r, "value_source", None) or "unset",
            "operator_value_note": getattr(r, "operator_value_note", None),
        },
        "retries": r.retries,
        "error": r.error,
        "checkpoints": r.checkpoints or [],
    }


def _pending_hitl_checkpoint(r: Run) -> Optional[Dict[str, Any]]:
    """Return the last ``hitl_pause`` checkpoint when the Run is awaiting
    operator input, ``None`` otherwise."""
    if (r.status or "") != "hitl_pending":
        return None
    for cp in reversed(list(r.checkpoints or [])):
        if isinstance(cp, dict) and cp.get("kind") == "hitl_pause":
            return cp
    return None


def _invocation(i: SkillInvocation) -> Dict[str, Any]:
    return {
        "id": i.id,
        "skill_slug": i.skill_slug,
        "status": i.status,
        "started_at": i.started_at.isoformat() if i.started_at else None,
        "completed_at": i.completed_at.isoformat() if i.completed_at else None,
        "latency_ms": i.latency_ms,
        "cost": i.cost,
        "metrics": i.metrics or {},
        "error": i.error,
    }


@router.get("")
async def list_runs(
    system_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100,
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    q = db.query(Run).filter(Run.workspace_id == workspace.id)
    if system_id:
        q = q.filter(Run.system_id == system_id)
    if status:
        q = q.filter(Run.status == status)
    rows = q.order_by(Run.started_at.desc()).limit(limit).all()
    return {"runs": [_row(r) for r in rows]}


@router.get("/{run_id}")
async def get_run(
    run_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    r = db.query(Run).filter(Run.id == run_id, Run.workspace_id == workspace.id).first()
    if not r:
        raise HTTPException(404, "Run not found")
    invocations = db.query(SkillInvocation).filter(SkillInvocation.run_id == r.id).order_by(SkillInvocation.started_at.asc()).all()
    payload: Dict[str, Any] = {
        **_row(r),
        "invocations": [_invocation(i) for i in invocations],
    }
    pending_cp = _pending_hitl_checkpoint(r)
    if pending_cp:
        decision_id = pending_cp.get("decision_id")
        decision: Optional[Decision] = None
        if decision_id:
            decision = db.query(Decision).filter(Decision.id == decision_id).first()
        payload["hitl"] = {
            "node_id": pending_cp.get("node_id"),
            "prompt": pending_cp.get("prompt"),
            "decision_id": decision_id,
            "decision_status": decision.status if decision else None,
            "decision_title": decision.title if decision else None,
        }
    return payload


class HitlResolve(BaseModel):
    action: Literal["accept", "reject"]
    actor: Optional[str] = Field(default=None, description="Operator id / email.")
    note: Optional[str] = Field(default=None, description="Audit trail note.")


@router.post("/{run_id}/hitl")
async def resolve_run_hitl(
    run_id: str,
    body: HitlResolve,
    background_tasks: BackgroundTasks,
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    """Operator accepts or rejects the pending HITL Decision and the DAG
    walker resumes in the background. The call is idempotent: a second
    request on a Run no longer paused returns 409.
    """
    r = db.query(Run).filter(Run.id == run_id, Run.workspace_id == workspace.id).first()
    if not r:
        raise HTTPException(404, "Run not found")
    pending_cp = _pending_hitl_checkpoint(r)
    if not pending_cp:
        raise HTTPException(409, f"Run is not awaiting HITL (status={r.status!r})")
    decision_id = pending_cp.get("decision_id")
    if not decision_id:
        raise HTTPException(500, "HITL checkpoint is missing its decision_id")
    decision = db.query(Decision).filter(Decision.id == decision_id).first()
    if not decision:
        raise HTTPException(404, "HITL decision not found")

    try:
        if body.action == "accept":
            accept_decision(db, decision, actor=body.actor, note=body.note)
        else:
            reject_decision(db, decision, actor=body.actor, note=body.note)
    except InvalidTransition as exc:
        raise HTTPException(409, str(exc)) from exc

    background_tasks.add_task(_resume_wrapper, r.id, decision.id)
    logger.info(
        "runs.hitl: dispatched resume",
        run_id=r.id,
        decision_id=decision.id,
        action=body.action,
    )
    return {
        "id": r.id,
        "status": r.status,
        "decision": {
            "id": decision.id,
            "status": decision.status,
        },
    }


def _resume_wrapper(run_id: str, decision_id: str) -> None:
    """Background shim so the FastAPI request returns immediately; the
    walker owns its own event loop via ``resume_run_dag``.
    """
    import asyncio

    try:
        asyncio.run(resume_run_dag(run_id, decision_id=decision_id))
    except RuntimeError:
        loop = asyncio.get_event_loop()
        loop.create_task(resume_run_dag(run_id, decision_id=decision_id))
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "runs.hitl: resume failed", run_id=run_id, decision_id=decision_id, error=str(exc)
        )


class OutcomeOverride(BaseModel):
    value: float = Field(..., description="Operator-declared business value.")
    note: Optional[str] = Field(
        default=None,
        description="Audit trail — why the auto-derivation was overridden.",
    )


@router.patch("/{run_id}/outcome")
async def override_run_outcome(
    run_id: str,
    body: OutcomeOverride,
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    """Operator override for the Outcome's `value`. Cost, confidence and
    efficiency are re-computed against the new value; `value_source` flips
    to `operator`. The previous value is preserved in `operator_value_note`
    so the audit is lossless.
    """
    r = db.query(Run).filter(Run.id == run_id, Run.workspace_id == workspace.id).first()
    if not r:
        raise HTTPException(404, "Run not found")
    if r.status not in ("completed", "failed"):
        raise HTTPException(
            409,
            f"Run is still {r.status!r}; operator overrides require a settled run.",
        )
    apply_operator_override(r, value=body.value, note=body.note)
    db.commit()
    return _row(r)
