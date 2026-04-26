"""Canonical /hypervisor endpoints — Balance Sheet, Recommendations, What-If.

Composes data from `impact`, `runs`, `capabilities` and `decisions` to feed
the executive cockpit. Designed to be a single roundtrip per surface.
"""
from typing import Any, Dict, List, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, Query
from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session as DBSession

from app.api.v1.endpoints.impact import _aggregate
from app.core.auth import get_current_workspace
from app.db.base import get_db
from app.models.capability import Capability
from app.models.decision import Decision
from app.models.evaluation import EvaluationScore
from app.models.evaluation_feedback import FEEDBACK_LABELS
from app.models.run import Run
from app.models.workspace import Workspace
from app.services.decisions import (
    InvalidTransition,
    accept as sm_accept,
    apply_decision as sm_apply,
    enact_decision,
    reject as sm_reject,
)
from app.services.evaluation.feedback_service import (
    InvalidFeedback,
    record_feedback,
    serialize_feedback,
)
from app.services.recommendations.proactive_service import (
    generate_proactive_recommendations,
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


class ProactiveRecommendationRequest(BaseModel):
    since_days: int = 7
    min_evaluations: int = 3
    min_breaches: int = 2
    min_breach_rate: float = 0.5
    dry_run: bool = False
    actor: Optional[str] = None


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


@router.post("/recommendations/generate")
async def generate_recommendations(
    body: Optional[ProactiveRecommendationRequest] = None,
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    """E5 — Generate proactive Decisions from aggregated E1 eval signals."""
    body = body or ProactiveRecommendationRequest()
    return generate_proactive_recommendations(
        db,
        workspace_id=workspace.id,
        since_days=body.since_days,
        min_evaluations=body.min_evaluations,
        min_breaches=body.min_breaches,
        min_breach_rate=body.min_breach_rate,
        actor=body.actor or "system",
        dry_run=body.dry_run,
    )


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
    # E1.5.1 — when the Decision is a `review_required` filed by the
    # auto-eval loop, accept/reject can carry the reviewer's verdict
    # so we persist a row in `evaluation_feedback`. All three fields
    # are optional: the existing UI (which doesn't ship feedback yet)
    # keeps working unchanged.
    feedback_label: Optional[str] = None
    feedback_corrected_output: Optional[Dict[str, Any]] = None


class DecisionApplyRequest(BaseModel):
    actor: Optional[str] = None
    enact: bool = True
    patch: Optional[Dict[str, Any]] = None


class ActiveSuggestionApplyRequest(BaseModel):
    actor: Optional[str] = None


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


def _maybe_record_eval_feedback(
    db: DBSession,
    *,
    decision: Decision,
    body: Optional[DecisionTransition],
    default_label: str,
) -> Optional[Dict[str, Any]]:
    """Persist an `EvaluationFeedback` row when the Decision is a
    review-queue triage item.

    Returns the serialized feedback row when written, ``None`` otherwise.
    Silently no-op for non-eval Decisions (no scope=run, no target_id,
    or kind != review_required) so generic Hypervisor recommendations
    keep their existing accept/reject semantics.

    Default label maps the reviewer's transition to a feedback verdict
    (accept = "false_positive", reject = "true_breach"). An explicit
    ``body.feedback_label`` overrides — useful for the
    ``correct_with_fix`` case once the UI ships a correction textarea.
    """
    if decision.kind != "review_required":
        return None
    if (decision.scope or "") != "run":
        return None
    run_id = decision.target_id
    if not run_id:
        return None

    label = (body.feedback_label if body else None) or default_label
    if label not in FEEDBACK_LABELS:
        from fastapi import HTTPException
        raise HTTPException(
            400,
            f"unknown feedback_label {label!r}; expected one of {list(FEEDBACK_LABELS)}",
        )

    score = (
        db.query(EvaluationScore)
        .filter(
            EvaluationScore.run_id == run_id,
            EvaluationScore.workspace_id == decision.workspace_id,
        )
        .order_by(EvaluationScore.created_at.desc())
        .first()
    )

    try:
        fb = record_feedback(
            db,
            workspace_id=decision.workspace_id,
            run_id=run_id,
            label=label,
            decision_id=decision.id,
            evaluation_score_id=score.id if score else None,
            notes=(body.note if body else None),
            corrected_output=(body.feedback_corrected_output if body else None),
            actor=(body.actor if body else None),
        )
    except InvalidFeedback as exc:
        from fastapi import HTTPException
        raise HTTPException(400, str(exc))
    return serialize_feedback(fb)


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
    feedback = _maybe_record_eval_feedback(
        db, decision=d, body=body, default_label="false_positive"
    )
    db.commit()
    payload = _serialize_decision(d, full=True)
    if feedback:
        payload["feedback"] = feedback
    return payload


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
    feedback = _maybe_record_eval_feedback(
        db, decision=d, body=body, default_label="true_breach"
    )
    db.commit()
    payload = _serialize_decision(d, full=True)
    if feedback:
        payload["feedback"] = feedback
    return payload


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


@router.post("/decisions/{decision_id}/apply-active-suggestion")
async def apply_active_suggestion(
    decision_id: str,
    body: Optional[ActiveSuggestionApplyRequest] = None,
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    """Apply the concrete E1.5.5 suggestion stored on a review Decision.

    MVP action: ``rerun_with_overrides``. Applying it creates a replay run
    from the breached parent run, then records the Decision as applied with
    the replay lineage in ``applied_patch``.
    """
    d = _get_decision_or_404(db, workspace.id, decision_id)
    if d.kind != "review_required" or d.scope != "run" or not d.target_id:
        raise HTTPException(400, "active suggestions are only available for run review decisions")
    rationale = d.rationale or {}
    suggestion = rationale.get("active_suggestion") or {}
    if not isinstance(suggestion, dict) or not suggestion:
        raise HTTPException(400, "decision has no active_suggestion")
    action_type = suggestion.get("action_type")
    if action_type != "rerun_with_overrides":
        raise HTTPException(400, f"unsupported active suggestion action {action_type!r}")

    parent = (
        db.query(Run)
        .filter(Run.id == d.target_id, Run.workspace_id == workspace.id)
        .first()
    )
    if not parent:
        raise HTTPException(404, "Parent run not found")

    from app.services.runs.replay_service import ReplayError, replay_run_async

    try:
        new_run, response_text = await replay_run_async(
            db=db,
            parent=parent,
            workspace_slug=workspace.slug,
            overrides=suggestion.get("overrides") or {},
            actor=(body.actor if body else None),
            source_decision_id=d.id,
        )
    except ReplayError as exc:
        raise HTTPException(400, str(exc)) from exc

    actor = body.actor if body else None
    try:
        if (d.status or "proposed") == "proposed":
            sm_accept(db, d, actor=actor, note="Accepted by applying active suggestion.")
        if (d.status or "") == "accepted":
            sm_apply(
                db,
                d,
                actor=actor,
                patch={
                    "action_type": action_type,
                    "suggestion": suggestion,
                    "new_run_id": new_run.id,
                    "parent_run_id": parent.id,
                    "status": new_run.status,
                },
            )
    except InvalidTransition as exc:
        raise HTTPException(409, str(exc)) from exc

    payload = _serialize_decision(d, full=True)
    payload["replay"] = {
        "run_id": new_run.id,
        "parent_run_id": parent.id,
        "status": new_run.status,
        "duration_ms": new_run.duration_ms,
        "response_preview": (response_text[:500] if response_text else ""),
        "eval_pending": new_run.status == "completed",
    }
    return payload
