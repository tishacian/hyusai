"""Evaluation API — LLM-as-Judge scoring, history, presets and review queue.

Three concerns share this router:

1. **Manual scoring** (``POST /score``) — pre-E1, kept for backward
   compat: the chat panel's "Fact-check" button and any external
   caller that wants a one-shot judge run.
2. **History / dashboard feeds** (``GET /history``, ``GET /latest``,
   ``GET /dimensions``, ``GET /trend``) — read-side for the
   observability pages.
3. **Vague E / E1 additions** — presets CRUD and the review queue:
   - ``GET/PUT /presets`` — workspace threshold config.
   - ``GET /review-queue`` — runs that the auto-eval loop flagged as
     ``review_required``, newest first. Paired with the global
     ``POST /decisions/{id}/status`` endpoint for accept/reject
     actions (no new mutation endpoint here — we reuse Decisions).
"""
from datetime import datetime, timedelta
from collections import Counter
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session as DBSession

from app.core.auth import get_current_user, get_current_workspace
from app.core.iam.roles import WORKSPACE_REVIEWER, is_admin_template, normalize_role_template
from app.db.base import get_db
from app.models.canonical_answer import CanonicalAnswer
from app.models.decision import Decision
from app.models.evaluation import EvaluationScore
from app.models.evaluation_feedback import EvaluationFeedback
from app.models.run import Run, SkillInvocation
from app.services.evaluation.lifecycle import require_readable_run, visible_evaluation_query, enqueue_run_evaluation
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services.audit_logger import emit_audit_event
from app.services.evaluation.canonical_answer_service import (
    CanonicalAnswerError,
    create_canonical_answer,
    serialize_canonical_answer,
)
from app.services.evaluation.feedback_service import serialize_feedback
from app.services.evaluation.judge import DIMENSION_LABELS, get_judge_service
from app.services.evaluation.rag_components import (
    QUESTION_TYPE_LABELS,
    RAG_COMPONENT_LABELS,
    component_health,
    heuristic_question_type,
    infer_failed_components,
    targeted_components,
)
from app.services.evaluation_preset_service import (
    DEFAULT_EVAL_CONFIG,
    get_evaluation_preset_service,
)

router = APIRouter()


def _require_review_queue_access(
    db: DBSession,
    *,
    workspace: Workspace,
    user: User,
) -> None:
    """Keep full Run evidence in the governed reviewer/admin surface."""

    if getattr(user, "role", None) == "admin":
        return
    membership = (
        db.query(WorkspaceMember)
        .filter(
            WorkspaceMember.user_id == user.id,
            WorkspaceMember.workspace_id == workspace.id,
        )
        .first()
    )
    role = (
        normalize_role_template(membership.role_template, membership.role)
        if membership is not None
        else None
    )
    if membership is None or not (
        is_admin_template(membership.role_template, membership.role) or role == WORKSPACE_REVIEWER
    ):
        raise HTTPException(403, "Reviewer/admin access required for the review queue")


def _authenticated_actor(user: User) -> str:
    return str(
        getattr(user, "email", None)
        or getattr(user, "username", None)
        or getattr(user, "keycloak_sub", None)
        or user.id
    )


# ---------------------------------------------------------------------------
# Manual scoring (pre-E1, preserved)
# ---------------------------------------------------------------------------


class EvalRequest(BaseModel):
    query: str
    response: str
    system_prompt: str = ""
    context_chunks: list[str] = []
    turn_number: int = 1
    session_id: str = None
    agent_id: str = None


@router.post("/score")
async def score_response(
    req: EvalRequest,
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    judge = get_judge_service()
    result = await judge.evaluate(
        query=req.query,
        response=req.response,
        system_prompt=req.system_prompt,
        context_chunks=req.context_chunks,
        turn_number=req.turn_number,
        session_id=req.session_id,
        agent_id=req.agent_id,
        workspace=workspace,
    )
    topic = result.get("topic") if isinstance(result.get("topic"), str) else None

    row = EvaluationScore(
        id=result["id"],
        workspace_id=workspace.id,
        session_id=result["session_id"],
        agent_id=result["agent_id"],
        turn_number=result["turn_number"],
        query=result["query"],
        scores=result["scores"],
        composite_score=result["composite_score"],
        hallucination_rate=result["hallucination_rate"],
        drift_rate=result["drift_rate"],
        question_type=result.get("question_type"),
        failed_components=result.get("failed_components") or [],
        topic=topic[:200] if topic else None,
        claim_audit=result["claim_audit"],
        metadata_={**(result.get("metadata") or {}), "status": result.get("status"), "reason": result.get("reason"), "created_by_user_id": user.id},
        created_at=datetime.utcnow(),
    )
    db.add(row)
    db.flush()
    from sqlalchemy import update
    db.execute(update(EvaluationScore).where(EvaluationScore.id == row.id).values(composite_score=result.get("composite_score"), hallucination_rate=result.get("hallucination_rate"), drift_rate=result.get("drift_rate")))
    db.commit()

    return result


@router.get("/history")
async def evaluation_history(
    agent_id: Optional[str] = None,
    limit: int = 20,
    since: Optional[str] = None,
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
    system_id: Optional[str] = None,
):
    """Return authorized evaluation records in the common System/time scope."""
    q = _evaluation_scope_query(db, workspace, system_id=system_id, since=since, agent_id=agent_id)
    q = visible_evaluation_query(db, q, user, workspace)
    rows = q.order_by(EvaluationScore.created_at.desc()).limit(max(1, min(limit, 200))).all()

    totals = _evaluation_scope_totals(q.all())
    run_systems = {r.id: r.system_id for r in db.query(Run).filter(Run.workspace_id == workspace.id, Run.id.in_([row.run_id for row in rows])).all()}
    return {
        "scope": {"system_id": system_id, "since": since or "7d"},
        **totals,
        "evaluations": [
            {
                "id": r.id,
                "run_id": r.run_id,
                "system_id": run_systems.get(r.run_id),
                "status": (r.metadata_ or {}).get("status", "historical"),
                "method": (r.metadata_ or {}).get("method"),
                "threshold_breach": ((r.metadata_ or {}).get("threshold_outcome") or {}).get("breach"),
                "session_id": r.session_id,
                "agent_id": r.agent_id,
                "turn_number": r.turn_number,
                "scores": r.scores,
                "composite_score": r.composite_score,
                "hallucination_rate": r.hallucination_rate,
                "drift_rate": r.drift_rate,
                "question_type": r.question_type,
                "failed_components": r.failed_components or [],
                "topic": r.topic,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
    }


@router.get("/dimensions")
async def get_dimensions():
    return {"dimensions": DIMENSION_LABELS}


@router.get("/latest")
async def latest_evaluation(
    agent_id: Optional[str] = None,
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
    system_id: Optional[str] = None,
    since: Optional[str] = "7d",
):
    q = _evaluation_scope_query(db, workspace, system_id=system_id, since=since, agent_id=agent_id).order_by(EvaluationScore.created_at.desc())
    q = visible_evaluation_query(db, q, user, workspace)
    rows = q.all()
    totals = _evaluation_scope_totals(rows)
    row = rows[0] if rows else None
    scope = {"system_id": system_id, "since": since or "7d"}
    if not row:
        return {"evaluation": None, "scope": scope, **totals}
    run = db.query(Run).filter(Run.id == row.run_id, Run.workspace_id == workspace.id).first()
    return {
        "scope": scope, **totals,
        "evaluation": {
            "id": row.id,
            "run_id": row.run_id,
            "system_id": run.system_id if run else None,
            "status": (row.metadata_ or {}).get("status", "historical"),
            "threshold_breach": ((row.metadata_ or {}).get("threshold_outcome") or {}).get("breach"),
            "scores": row.scores,
            "composite_score": row.composite_score,
            "hallucination_rate": row.hallucination_rate,
            "drift_rate": row.drift_rate,
            "question_type": row.question_type,
            "failed_components": row.failed_components or [],
            "topic": row.topic,
            "claim_audit": row.claim_audit,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
    }


# ---------------------------------------------------------------------------
# Vague E / E1 — presets
# ---------------------------------------------------------------------------


class EvalPresetIn(BaseModel):
    """Shape of the threshold config PUT'd by ``/settings/evaluation``.

    All fields optional — unset keys fall through to the built-in
    defaults at resolve-time. The field set mirrors
    :data:`~app.services.evaluation_preset_service.DEFAULT_EVAL_CONFIG`
    exactly.
    """

    enabled: Optional[bool] = None
    composite_min: Optional[float] = Field(default=None, ge=0, le=100)
    hallucination_max: Optional[float] = Field(default=None, ge=0, le=1)
    dimension_min: Optional[Dict[str, float]] = None
    sample_rate: Optional[float] = Field(default=None, ge=0, le=1)
    name: Optional[str] = None


class CanonicalAnswerIn(BaseModel):
    question: str
    answer: str
    source_decision_id: Optional[str] = None
    source_feedback_id: Optional[str] = None
    source_run_id: Optional[str] = None
    similarity_threshold: float = Field(default=0.9, ge=0.5, le=1.0)
    actor: Optional[str] = None


@router.get("/presets")
async def get_effective_preset(
    capability_id: Optional[str] = None,
    system_id: Optional[str] = None,
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    """Resolve the effective threshold config for the given scope.

    Returns both the resolved config (with defaults merged in) and the
    raw workspace-level config (if any) so the settings UI can
    distinguish "inherited from defaults" from "workspace override".
    """
    service = get_evaluation_preset_service()
    effective = service.resolve(
        db,
        workspace_id=workspace.id,
        capability_id=capability_id,
        system_id=system_id,
    )
    workspace_preset = service.get_workspace_preset(db, workspace.id)
    return {
        "defaults": DEFAULT_EVAL_CONFIG,
        "workspace": {
            "id": workspace_preset.id if workspace_preset else None,
            "name": workspace_preset.name if workspace_preset else None,
            "config": workspace_preset.config if workspace_preset else None,
        },
        "effective": effective,
    }


@router.put("/presets")
async def upsert_workspace_preset(
    payload: EvalPresetIn,
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    """Upsert the workspace-scoped threshold config.

    The body is partial — only the keys the UI wants to set are
    forwarded; missing keys retain their previously-persisted value
    (or fall through to defaults at resolve-time if never set).
    """
    service = get_evaluation_preset_service()
    current = service.get_workspace_preset(db, workspace.id)
    base = dict(current.config) if current else {}

    data = payload.model_dump(exclude_unset=True, exclude_none=True)
    name = data.pop("name", None)
    base.update(data)

    row = service.upsert_workspace_preset(
        db,
        workspace_id=workspace.id,
        config=base,
        name=name or (current.name if current else "Workspace default"),
    )
    return {
        "id": row.id,
        "name": row.name,
        "config": row.config,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


# ---------------------------------------------------------------------------
# Vague E / E1 — per-run eval lookup (chat toast polling)
# ---------------------------------------------------------------------------


@router.get("/by-run/{run_id}")
async def evaluation_by_run(
    run_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Return persisted evaluation lifecycle and authorized evidence.

    An older Run without a lifecycle is unavailable, never inferred pending
    from today's preset. A new explicit command can evaluate its output.
    """
    run = db.query(Run).filter(Run.id == run_id, Run.workspace_id == workspace.id).first()
    require_readable_run(db, run, user, workspace)
    snap = run.evaluation_scores or {}
    if not snap:
        return {"status": "unavailable", "run_id": run.id, "reason": "no_persisted_evaluation"}
    from app.services.evaluation.lifecycle import public_evaluation_snapshot
    snap = public_evaluation_snapshot(db, snap, workspace=workspace, user=user, run=run)
    return {**snap, "status": snap.get("status", "historical"), "run_id": run.id, "breach": bool(snap.get("threshold_breach"))}


class RunEvaluationRequest(BaseModel):
    idempotency_key: str = Field(min_length=1, max_length=128)
    invocation_id: Optional[str] = None


@router.post("/by-run/{run_id}/score", status_code=202)
async def score_run(
    run_id: str,
    req: RunEvaluationRequest,
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    run = db.query(Run).filter(Run.id == run_id, Run.workspace_id == workspace.id).first()
    require_readable_run(db, run, user, workspace)
    if req.invocation_id:
        invocation = db.query(SkillInvocation).filter(SkillInvocation.id == req.invocation_id, SkillInvocation.run_id == run.id).first()
        from app.services.run_access import resolve_skill_invocation_read
        if invocation is None or not resolve_skill_invocation_read(db, invocation=invocation, run=run, user=user, workspace=workspace).effective_allowed:
            raise HTTPException(404, "Invocation not found")
    job = enqueue_run_evaluation(db, run, user=user, idempotency_key=req.idempotency_key, invocation_id=req.invocation_id)
    return {"job_id": job.id, "status": job.status, "run_id": run.id, "poll_url": f"/evaluation/by-run/{run.id}"}


# ---------------------------------------------------------------------------
# Vague E / E1 — review queue
# ---------------------------------------------------------------------------


@router.get("/review-queue")
async def review_queue(
    status: str = Query(default="proposed", pattern="^(proposed|accepted|rejected|applied|all)$"),
    component: Optional[str] = Query(
        default=None,
        description="Filter to decisions whose eval attribution includes this RAG component.",
    ),
    limit: int = Query(default=50, ge=1, le=200),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
    system_id: Optional[str] = None,
    since: Optional[str] = None,
):
    """List ``review_required`` decisions + their linked run context.

    Joined with Run so the UI can show composite score + breach
    reasons without a second fetch. Ordered by newest first.
    """
    _require_review_queue_access(db, workspace=workspace, user=user)
    q = (
        db.query(Decision)
        .filter(
            Decision.workspace_id == workspace.id,
            Decision.kind == "review_required",
        )
        .order_by(Decision.created_at.desc())
    )
    if status != "all":
        q = q.filter(Decision.status == status)
    if system_id:
        q = q.filter(Decision.target_id.in_(db.query(Run.id).filter(Run.workspace_id == workspace.id, Run.system_id == system_id)))
    if since:
        q = q.filter(Decision.created_at >= datetime.utcnow() - _scope_delta(since))
    decisions = q.all()

    run_ids = [d.target_id for d in decisions if d.target_id]
    runs_by_id: Dict[str, Run] = {}
    if run_ids:
        rows = db.query(Run).filter(Run.id.in_(run_ids), Run.workspace_id == workspace.id).all()
        from app.services.run_access import readable_runs
        runs_by_id = {r.id: r for r in readable_runs(db, runs=rows, user=user, workspace=workspace)}

    items: List[Dict[str, Any]] = []
    wanted_component = (
        component.strip().lower().replace("-", "_").replace(" ", "_") if component else None
    )
    if wanted_component and wanted_component not in RAG_COMPONENT_LABELS:
        raise HTTPException(status_code=400, detail=f"Unknown RAG component: {component}")
    for decision in decisions:
        run = runs_by_id.get(decision.target_id) if decision.target_id else None
        if run is None:
            continue
        if wanted_component:
            rationale = decision.rationale or {}
            failed = rationale.get("failed_components")
            if not failed and run and isinstance(run.evaluation_scores, dict):
                failed = run.evaluation_scores.get("failed_components")
            if wanted_component not in (failed or []):
                continue
        items.append(
            {
                "decision": {
                    "id": decision.id,
                    "kind": decision.kind,
                    "status": decision.status,
                    "title": decision.title,
                    "rationale": decision.rationale,
                    "created_at": decision.created_at.isoformat() if decision.created_at else None,
                    "approved_by": decision.approved_by,
                    "approved_at": decision.approved_at.isoformat()
                    if decision.approved_at
                    else None,
                },
                "run": _serialize_run_for_queue(run) if run else None,
            }
        )
    return {"items": items[:limit], "count": len(items)}


@router.get("/trend")
async def eval_trend(
    since: str = Query(default="7d"),
    group_by: str = Query(default="day", pattern="^(day|capability|system)$"),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
    system_id: Optional[str] = None,
):
    """Aggregated scores for the observability dashboard.

    Two grouping modes:

    - ``group_by=day`` — daily mean composite + hallucination rate,
      with counts above/below the current workspace thresholds.
    - ``group_by=capability|system`` — per-entity means + breach
      counts over the window.
    """
    q = _evaluation_scope_query(db, workspace, system_id=system_id, since=since)
    q = visible_evaluation_query(db, q, user, workspace)
    rows = q.order_by(EvaluationScore.created_at.asc()).all()
    runs = {r.id: r for r in db.query(Run).filter(Run.workspace_id == workspace.id, Run.id.in_([row.run_id for row in rows])).all()}
    buckets = {}
    for row in rows:
        bucket = str(row.created_at.date()) if group_by == "day" else (runs.get(row.run_id).capability_id if group_by == "capability" and runs.get(row.run_id) else runs.get(row.run_id).system_id if runs.get(row.run_id) else None)
        buckets.setdefault(bucket or "(unknown)", []).append(row)
    def mean(items, attr):
        values = [getattr(row, attr) for row in items if getattr(row, attr) is not None]
        return sum(values) / len(values) if values else None
    known = [row for row in rows if isinstance((row.metadata_ or {}).get("threshold_outcome"), dict)]
    breaches = sum(bool(row.metadata_["threshold_outcome"].get("breach")) for row in known)
    return {
        "scope": {"system_id": system_id, "since": since or "7d"},
        **_evaluation_scope_totals(rows),
        "since": since, "group_by": group_by,
        "thresholds": None, "threshold_basis": "persisted_per_evaluation",
        "totals": {
            "runs_evaluated": len(rows), "breaches": breaches,
            "breach_rate": breaches / len(known) if known else None,
            "threshold_coverage": len(known),
            "incomplete": sum((row.metadata_ or {}).get("status") in {"failed", "partial"} for row in rows),
        },
        "series": [{"bucket": bucket, "count": len(items), "avg_composite": mean(items, "composite_score"), "avg_hallucination": mean(items, "hallucination_rate"),
            "observed_composite_count": sum(row.composite_score is not None for row in items),
            "observed_hallucination_count": sum(row.hallucination_rate is not None for row in items),
            "threshold_coverage": sum(isinstance((row.metadata_ or {}).get("threshold_outcome"), dict) for row in items),
            "breaches": sum(bool(((row.metadata_ or {}).get("threshold_outcome") or {}).get("breach")) for row in items),
            "incomplete": sum((row.metadata_ or {}).get("status") in {"partial", "failed"} for row in items),
        } for bucket, items in buckets.items()],
    }


# ---------------------------------------------------------------------------
# E1.5.3 — Giskard-inspired RAG component analytics
# ---------------------------------------------------------------------------


@router.get("/component-health")
async def eval_component_health(
    since: str = Query(default="7d"),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
    system_id: Optional[str] = None,
):
    """Aggregate breached evaluations by RAG component.

    The component taxonomy follows Giskard RAGET, but the aggregation is
    native to Agentium's persisted ``evaluation_scores`` so the dashboard
    works without importing Giskard in the API process.
    """
    query = _evaluation_scope_query(db, workspace, system_id=system_id, since=since)
    rows = visible_evaluation_query(db, query, user, workspace).order_by(EvaluationScore.created_at.desc()).all()
    scope_totals = _evaluation_scope_totals(rows)
    service = get_evaluation_preset_service()
    config = service.resolve(db, workspace_id=workspace.id)
    composite_min = float(config.get("composite_min", 0.0))
    hallucination_max = float(config.get("hallucination_max", 1.0))
    excluded = sum(r.composite_score is None or r.hallucination_rate is None for r in rows)
    rows = [r for r in rows if r.composite_score is not None and r.hallucination_rate is not None]
    payload = component_health(
        rows,
        composite_min=composite_min,
        hallucination_max=hallucination_max,
    )
    for item in payload["components"]:
        if not item["evaluated"]:
            item.update(avg_composite=None, avg_hallucination=None, breach_rate=None)
    payload.update(
        {
            "scope": {"system_id": system_id, "since": since or "7d"},
            **scope_totals,
            "since": since,
            "excluded_incomplete": excluded,
            "attribution_kind": "diagnostic_hypothesis",
            "thresholds": {
                "composite_min": composite_min,
                "hallucination_max": hallucination_max,
            },
            "totals": {
                "evaluations": scope_totals["total"],
                "applicable_evaluations": len(rows),
                "breaches": sum(1 for r in rows if r.failed_components),
            },
        }
    )
    return payload


@router.get("/taxonomy")
async def evaluation_taxonomy():
    """Expose the eval taxonomy for UI labels and future Giskard adapters."""
    return {
        "components": RAG_COMPONENT_LABELS,
        "question_types": QUESTION_TYPE_LABELS,
        "question_type_components": {key: targeted_components(key) for key in QUESTION_TYPE_LABELS},
    }


# ---------------------------------------------------------------------------
# E1.5.5 — Canonical answers (Dify-style annotation reply)
# ---------------------------------------------------------------------------


@router.get("/canonical-answers")
async def list_canonical_answers(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    _require_review_queue_access(db, workspace=workspace, user=user)
    q = db.query(CanonicalAnswer).filter(CanonicalAnswer.workspace_id == workspace.id)
    total = q.count()
    rows = q.order_by(CanonicalAnswer.updated_at.desc()).offset(offset).limit(limit).all()
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [serialize_canonical_answer(row) for row in rows],
    }


@router.post("/canonical-answers", status_code=201)
async def create_canonical_answer_endpoint(
    body: CanonicalAnswerIn,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    _require_review_queue_access(db, workspace=workspace, user=user)
    try:
        row = create_canonical_answer(
            db,
            workspace_id=workspace.id,
            question=body.question,
            answer=body.answer,
            actor=_authenticated_actor(user),
            source_decision_id=body.source_decision_id,
            source_feedback_id=body.source_feedback_id,
            source_run_id=body.source_run_id,
            similarity_threshold=body.similarity_threshold,
        )
    except CanonicalAnswerError as exc:
        raise HTTPException(400, str(exc)) from exc
    db.commit()
    return serialize_canonical_answer(row)


@router.delete("/canonical-answers/{answer_id}", status_code=204)
async def delete_canonical_answer_endpoint(
    answer_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    _require_review_queue_access(db, workspace=workspace, user=user)
    row = (
        db.query(CanonicalAnswer)
        .filter(CanonicalAnswer.id == answer_id, CanonicalAnswer.workspace_id == workspace.id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Canonical answer not found")
    emit_audit_event(
        workspace_id=workspace.id,
        event_type="canonical_answer.deleted",
        actor=_authenticated_actor(user),
        details={"canonical_answer_id": row.id},
        db=db,
    )
    db.delete(row)
    db.commit()
    return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _scope_delta(since):
    try:
        delta = _parse_since(since or "7d")
    except (OverflowError, ValueError):
        delta = None
    if delta is None or not timedelta(minutes=1) <= delta <= timedelta(days=365):
        raise HTTPException(422, "since must be between 1 minute and 365 days (Nd, Nh or Nm)")
    return delta


def _evaluation_scope_query(db, workspace, *, system_id=None, since=None, agent_id=None):
    delta = _scope_delta(since)
    query = db.query(EvaluationScore).filter(EvaluationScore.workspace_id == workspace.id,
        EvaluationScore.created_at >= datetime.utcnow() - delta)
    if system_id:
        query = query.filter(EvaluationScore.run_id.in_(db.query(Run.id).filter(Run.workspace_id == workspace.id, Run.system_id == system_id)))
    if agent_id:
        query = query.filter(EvaluationScore.agent_id == agent_id)
    return query


def _evaluation_scope_totals(rows):
    return {"total": len(rows), "distinct_runs": len({row.run_id for row in rows if row.run_id}), "state_counts": dict(Counter((row.metadata_ or {}).get("status") or "historical" for row in rows)), "state_count_basis": "evaluation_records"}


def _parse_since(since: str) -> Optional[timedelta]:
    """Parse ``Nd``/``Nh``/``Nm`` shorthands into timedelta. ``None`` if malformed."""
    if not since or len(since) < 2:
        return None
    try:
        amount = int(since[:-1])
        unit = since[-1].lower()
    except (ValueError, IndexError):
        return None
    if amount < 0:
        return None
    if unit == "d":
        return timedelta(days=amount)
    if unit == "h":
        return timedelta(hours=amount)
    if unit == "m":
        return timedelta(minutes=amount)
    return None


def _serialize_run_for_queue(run: Run) -> Dict[str, Any]:
    return {
        "id": run.id,
        "system_id": run.system_id,
        "capability_id": run.capability_id,
        "status": run.status,
        "decision": run.decision,
        "confidence": run.confidence,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "evaluation_scores": {k: v for k, v in (run.evaluation_scores or {}).items() if k not in {"metadata", "claim_audit"}},
        # Keep input_ref + output_ref for preview — UI will trim.
        "input_ref": run.input_ref,
        "output_ref": run.output_ref,
    }


# ---------------------------------------------------------------------------
# E1.5.1 — Evaluation feedback (review-queue verdicts)
# ---------------------------------------------------------------------------


@router.get("/feedback")
async def list_feedback(
    run_id: Optional[str] = Query(default=None),
    decision_id: Optional[str] = Query(default=None),
    label: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List feedback rows for the current workspace.

    Filters compose with AND. Returned newest-first. The endpoint is
    intentionally read-only here — feedback is *written* through the
    Decision accept/reject flow (single transactional write path).
    """
    q = (
        db.query(EvaluationFeedback)
        .filter(EvaluationFeedback.workspace_id == workspace.id)
        .order_by(EvaluationFeedback.created_at.desc())
    )
    if run_id:
        q = q.filter(EvaluationFeedback.run_id == run_id)
    if decision_id:
        q = q.filter(EvaluationFeedback.decision_id == decision_id)
    if label:
        q = q.filter(EvaluationFeedback.label == label)
    from app.services.run_access import readable_runs
    accessible = readable_runs(db, runs=db.query(Run).filter(Run.workspace_id == workspace.id).all(), user=user, workspace=workspace)
    q = q.filter(EvaluationFeedback.run_id.in_([r.id for r in accessible]))
    total = q.count()
    rows = q.offset(offset).limit(limit).all()
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [serialize_feedback(r) for r in rows],
    }
