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
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session as DBSession

from app.core.auth import get_current_workspace
from app.db.base import get_db
from app.models.decision import Decision
from app.models.evaluation import EvaluationScore
from app.models.run import Run
from app.models.workspace import Workspace
from app.services.evaluation.judge import get_judge_service, DIMENSION_LABELS
from app.services.evaluation_preset_service import (
    DEFAULT_EVAL_CONFIG,
    get_evaluation_preset_service,
)

router = APIRouter()


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
    )

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
        claim_audit=result["claim_audit"],
        created_at=datetime.utcnow(),
    )
    db.add(row)
    db.commit()

    return result


@router.get("/history")
async def evaluation_history(
    agent_id: Optional[str] = None,
    limit: int = 20,
    since: Optional[str] = None,
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    """Return recent evaluation scores for the workspace.

    ``since`` accepts a relative-time shorthand: ``7d``, ``24h``,
    ``90m``. Unknown values fall back to the default ``limit``-only
    behaviour for backward compat with the existing quality dashboard.
    """
    q = db.query(EvaluationScore).filter(EvaluationScore.workspace_id == workspace.id)

    if agent_id:
        q = q.filter(EvaluationScore.agent_id == agent_id)

    if since:
        delta = _parse_since(since)
        if delta is not None:
            q = q.filter(EvaluationScore.created_at >= datetime.utcnow() - delta)

    rows = q.order_by(EvaluationScore.created_at.desc()).limit(limit).all()

    return {
        "evaluations": [
            {
                "id": r.id,
                "run_id": r.run_id,
                "session_id": r.session_id,
                "agent_id": r.agent_id,
                "turn_number": r.turn_number,
                "scores": r.scores,
                "composite_score": r.composite_score,
                "hallucination_rate": r.hallucination_rate,
                "drift_rate": r.drift_rate,
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
):
    q = db.query(EvaluationScore).filter(
        EvaluationScore.workspace_id == workspace.id
    ).order_by(EvaluationScore.created_at.desc())
    if agent_id:
        q = q.filter(EvaluationScore.agent_id == agent_id)
    row = q.first()
    if not row:
        return {"evaluation": None}
    return {
        "evaluation": {
            "id": row.id,
            "run_id": row.run_id,
            "scores": row.scores,
            "composite_score": row.composite_score,
            "hallucination_rate": row.hallucination_rate,
            "drift_rate": row.drift_rate,
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
# Vague E / E1 — review queue
# ---------------------------------------------------------------------------


@router.get("/review-queue")
async def review_queue(
    status: str = Query(default="proposed", pattern="^(proposed|accepted|rejected|applied|all)$"),
    limit: int = Query(default=50, ge=1, le=200),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    """List ``review_required`` decisions + their linked run context.

    Joined with Run so the UI can show composite score + breach
    reasons without a second fetch. Ordered by newest first.
    """
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
    decisions = q.limit(limit).all()

    run_ids = [d.target_id for d in decisions if d.target_id]
    runs_by_id: Dict[str, Run] = {}
    if run_ids:
        rows = db.query(Run).filter(Run.id.in_(run_ids)).all()
        runs_by_id = {r.id: r for r in rows}

    items: List[Dict[str, Any]] = []
    for decision in decisions:
        run = runs_by_id.get(decision.target_id) if decision.target_id else None
        items.append(
            {
                "decision": {
                    "id": decision.id,
                    "kind": decision.kind,
                    "status": decision.status,
                    "title": decision.title,
                    "rationale": decision.rationale,
                    "created_at": decision.created_at.isoformat()
                    if decision.created_at
                    else None,
                    "approved_by": decision.approved_by,
                    "approved_at": decision.approved_at.isoformat()
                    if decision.approved_at
                    else None,
                },
                "run": _serialize_run_for_queue(run) if run else None,
            }
        )
    return {"items": items, "count": len(items)}


@router.get("/trend")
async def eval_trend(
    since: str = Query(default="7d"),
    group_by: str = Query(default="day", pattern="^(day|capability|system)$"),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    """Aggregated scores for the observability dashboard.

    Two grouping modes:

    - ``group_by=day`` — daily mean composite + hallucination rate,
      with counts above/below the current workspace thresholds.
    - ``group_by=capability|system`` — per-entity means + breach
      counts over the window.
    """
    delta = _parse_since(since) or timedelta(days=7)
    cutoff = datetime.utcnow() - delta

    q = db.query(EvaluationScore).filter(
        EvaluationScore.workspace_id == workspace.id,
        EvaluationScore.created_at >= cutoff,
    )

    service = get_evaluation_preset_service()
    config = service.resolve(db, workspace_id=workspace.id)
    composite_min = float(config.get("composite_min", 0.0))
    hallucination_max = float(config.get("hallucination_max", 1.0))

    if group_by == "day":
        date_fn = func.date(EvaluationScore.created_at)
        rows = (
            q.with_entities(
                date_fn.label("day"),
                func.count(EvaluationScore.id).label("count"),
                func.avg(EvaluationScore.composite_score).label("avg_composite"),
                func.avg(EvaluationScore.hallucination_rate).label("avg_hallucination"),
            )
            .group_by(date_fn)
            .order_by(date_fn.asc())
            .all()
        )
        series = [
            {
                "bucket": str(row.day),
                "count": int(row.count or 0),
                "avg_composite": float(row.avg_composite or 0.0),
                "avg_hallucination": float(row.avg_hallucination or 0.0),
            }
            for row in rows
        ]
    else:
        group_col = EvaluationScore.agent_id
        rows = (
            q.with_entities(
                group_col.label("bucket"),
                func.count(EvaluationScore.id).label("count"),
                func.avg(EvaluationScore.composite_score).label("avg_composite"),
                func.avg(EvaluationScore.hallucination_rate).label("avg_hallucination"),
            )
            .group_by(group_col)
            .order_by(func.count(EvaluationScore.id).desc())
            .all()
        )
        series = [
            {
                "bucket": row.bucket or "(unknown)",
                "count": int(row.count or 0),
                "avg_composite": float(row.avg_composite or 0.0),
                "avg_hallucination": float(row.avg_hallucination or 0.0),
            }
            for row in rows
        ]

    breach_count = (
        q.filter(
            (EvaluationScore.composite_score < composite_min)
            | (EvaluationScore.hallucination_rate > hallucination_max)
        ).count()
    )
    total = q.count()

    return {
        "since": since,
        "group_by": group_by,
        "thresholds": {
            "composite_min": composite_min,
            "hallucination_max": hallucination_max,
        },
        "totals": {
            "runs_evaluated": total,
            "breaches": breach_count,
            "breach_rate": (breach_count / total) if total else 0.0,
        },
        "series": series,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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
        "evaluation_scores": run.evaluation_scores,
        # Keep input_ref + output_ref for preview — UI will trim.
        "input_ref": run.input_ref,
        "output_ref": run.output_ref,
    }
