"""Canonical /runs endpoints — supersede /traces.

A Run carries the Outcome block. Detail view exposes the SkillInvocation
ledger so the cockpit can drill from the Run timeline down to individual
skill calls.
"""
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DBSession

from app.core.auth import get_current_workspace
from app.db.base import get_db
from app.models.run import Run, SkillInvocation
from app.models.workspace import Workspace
from app.services.outcome.derive import apply_operator_override

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
    }


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
    return {**_row(r), "invocations": [_invocation(i) for i in invocations]}


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
