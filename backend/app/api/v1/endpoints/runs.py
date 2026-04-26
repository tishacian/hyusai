"""Canonical /runs endpoints — supersede /traces.

A Run carries the Outcome block. Detail view exposes the SkillInvocation
ledger so the cockpit can drill from the Run timeline down to individual
skill calls.
"""
import asyncio
import json
from typing import Any, AsyncIterator, Dict, List, Literal, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DBSession

from app.core.auth import get_current_workspace
from app.core.logging import get_logger
from app.db.base import SessionLocal, get_db
from app.models.decision import Decision
from app.models.run import Run, SkillInvocation
from app.models.workspace import Workspace
from app.services.decisions import (
    InvalidTransition,
    accept as accept_decision,
    reject as reject_decision,
)
from app.services.outcome.derive import apply_operator_override
from app.services.run_engine.dag import resume_run_dag, resume_run_dag_debug
from app.services.run_engine.events import bus as event_bus

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
        "input_ref": r.input_ref or {},
        "output_ref": r.output_ref or {},
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


def _pending_debug_checkpoint(r: Run) -> Optional[Dict[str, Any]]:
    """Return the last ``debug_pause`` checkpoint when the Run is paused
    in the step debugger."""
    if (r.status or "") != "debug_pending":
        return None
    for cp in reversed(list(r.checkpoints or [])):
        if isinstance(cp, dict) and cp.get("kind") == "debug_pause":
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
    debug_cp = _pending_debug_checkpoint(r)
    if debug_cp:
        payload["debug"] = {
            "node_id": debug_cp.get("node_id"),
            "debug_mode": debug_cp.get("debug_mode"),
            "breakpoints": debug_cp.get("breakpoints") or [],
            "ctx_snapshot": debug_cp.get("ctx_snapshot") or {},
            "last_output": debug_cp.get("last_output") or {},
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


# ---------------------------------------------------------------------------
# Step debugger — /runs/{id}/step
# ---------------------------------------------------------------------------
class DebugStep(BaseModel):
    action: Literal["step", "continue", "stop"]
    breakpoints: Optional[List[str]] = Field(
        default=None,
        description="Optional replacement breakpoint set applied before resume.",
    )


@router.post("/{run_id}/step")
async def step_run(
    run_id: str,
    body: DebugStep,
    background_tasks: BackgroundTasks,
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    """Advance a Run paused by the step debugger.

    Action semantics:
        * ``step``     — run until the next non-source/sink node settles.
        * ``continue`` — run until a breakpoint fires or the DAG ends.
        * ``stop``     — cancel the Run here; outcome = ``debugger_stopped``.

    Returns 409 when the Run is not currently in ``debug_pending``.
    """
    r = db.query(Run).filter(Run.id == run_id, Run.workspace_id == workspace.id).first()
    if not r:
        raise HTTPException(404, "Run not found")
    if r.status != "debug_pending":
        raise HTTPException(409, f"Run is not in debugger pause (status={r.status!r})")
    background_tasks.add_task(
        _step_wrapper, r.id, body.action, body.breakpoints or None
    )
    logger.info(
        "runs.debug: dispatched step", run_id=r.id, action=body.action
    )
    return {"id": r.id, "status": r.status, "action": body.action}


def _step_wrapper(run_id: str, action: str, breakpoints: Optional[List[str]]) -> None:
    """Background shim mirroring :func:`_resume_wrapper` for step resume."""
    import asyncio

    try:
        asyncio.run(
            resume_run_dag_debug(run_id, action=action, breakpoints=breakpoints)
        )
    except RuntimeError:
        loop = asyncio.get_event_loop()
        loop.create_task(
            resume_run_dag_debug(run_id, action=action, breakpoints=breakpoints)
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "runs.debug: step failed", run_id=run_id, action=action, error=str(exc)
        )


# ---------------------------------------------------------------------------
# Live SSE stream — /runs/{id}/stream
# ---------------------------------------------------------------------------
_TERMINAL_STATUSES = {"completed", "failed", "cancelled"}


def _sse_format(event: str, payload: Dict[str, Any]) -> str:
    """Serialize one payload as a single SSE frame."""
    return f"event: {event}\ndata: {json.dumps(payload, default=str)}\n\n"


async def _run_event_stream(
    run_id: str, request: Request, workspace_id: Optional[str]
) -> AsyncIterator[str]:
    """Yield SSE frames for a single Run.

    1. Subscribe to the live bus *before* touching the DB so any event
       emitted by the walker during the replay phase lands in our queue.
    2. Replay every checkpoint already persisted, remembering their
       timestamps so we can dedupe them against the buffered live events.
    3. Emit a ``snapshot`` meta event carrying the current outcome so
       the UI can rebuild state without a second HTTP round-trip.
    4. Forward live events until the bus closes, the Run reaches a
       terminal state, or the HTTP client disconnects.
    """
    subscriber = event_bus.subscribe(run_id)
    replayed_ts: set[str] = set()
    try:
        db = SessionLocal()
        try:
            run = db.query(Run).filter(Run.id == run_id).first()
            if not run or (workspace_id and run.workspace_id != workspace_id):
                yield _sse_format("error", {"code": "not_found", "run_id": run_id})
                return

            checkpoints = list(run.checkpoints or [])
            for cp in checkpoints:
                ts = cp.get("t")
                if isinstance(ts, str):
                    replayed_ts.add(ts)
                yield _sse_format(cp.get("kind", "checkpoint"), cp)

            yield _sse_format(
                "snapshot",
                {
                    "status": run.status,
                    "outcome": {
                        "decision": run.decision,
                        "confidence": run.confidence,
                        "value_estimated": run.value_estimated,
                        "cost_internal": run.cost_internal,
                        "efficiency": run.efficiency,
                    },
                    "checkpoints_emitted": len(checkpoints),
                },
            )

            if run.status in _TERMINAL_STATUSES or run.status in (
                "hitl_pending",
                "debug_pending",
            ):
                yield _sse_format(
                    "close", {"reason": "run_not_live", "status": run.status}
                )
                return
        finally:
            db.close()

        consumer_task: Optional[asyncio.Task[Optional[Dict[str, Any]]]] = None
        while True:
            if await request.is_disconnected():
                return
            if consumer_task is None:
                consumer_task = asyncio.create_task(subscriber.next_event())
            done, _ = await asyncio.wait(
                {consumer_task}, timeout=15.0, return_when=asyncio.FIRST_COMPLETED
            )
            if consumer_task in done:
                event = consumer_task.result()
                consumer_task = None
                if event is None:
                    # Bus closed cleanly.
                    break
                ts = event.get("t")
                if isinstance(ts, str) and ts in replayed_ts:
                    # This event landed during replay and is already on
                    # the wire via the checkpoint replay loop.
                    continue
                yield _sse_format(event.get("kind", "event"), event)
                if event.get("kind") in ("run_end", "hitl_pause", "debug_pause"):
                    break
            else:
                # 15s tick with no events. Two responsibilities here:
                #   1. Keep the connection warm so proxies (Nginx) don't
                #      close idle streams.
                #   2. Short-circuit when the Run finished through a
                #      path that bypasses the live bus (e.g. sequential
                #      walker that doesn't publish events).
                db = SessionLocal()
                try:
                    status = (
                        db.query(Run.status).filter(Run.id == run_id).scalar()
                    )
                finally:
                    db.close()
                if status in _TERMINAL_STATUSES or status in (
                    "hitl_pending",
                    "debug_pending",
                ):
                    yield _sse_format(
                        "close", {"reason": "polled_terminal", "status": status}
                    )
                    break
                yield ": keep-alive\n\n"
        if consumer_task is not None:
            consumer_task.cancel()
    finally:
        await subscriber.aclose()
        yield _sse_format("close", {"reason": "stream_closed"})


@router.get("/{run_id}/stream")
async def stream_run(
    run_id: str,
    request: Request,
    workspace: Workspace = Depends(get_current_workspace),
):
    """Server-Sent Events stream of a Run's lifecycle.

    Each frame is shaped as::

        event: <kind>
        data: <json>

    Known ``kind`` values mirror the walker checkpoints: ``run_start``,
    ``node_start``, ``node_end``, ``hitl_pause``, ``hitl_resume``,
    ``run_end``, plus two meta events the HTTP layer injects:
    ``snapshot`` (initial state dump on connect) and ``close`` (terminal
    signal so the client can unsubscribe without inspecting ``status``).
    """
    return StreamingResponse(
        _run_event_stream(run_id, request, workspace.id if workspace else None),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # disable buffering on Nginx
        },
    )


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


# ---------------------------------------------------------------------------
# E1.5.2 — Replay with override
# ---------------------------------------------------------------------------


class ReplayRequest(BaseModel):
    overrides: Dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Override fields for the replay. Recognised keys: "
            "`query`, `rag_pipeline_mode`, `model`, `provider`, "
            "`system_prompt`, `temperature`, `max_tokens`, `top_k`, "
            "`similarity_threshold`, `prompt_type`. Unknown keys are "
            "forwarded into `agent_preferences.custom_overrides` so the "
            "API stays stable as the orchestrator gains options."
        ),
    )
    actor: Optional[str] = Field(
        default=None,
        description="Operator handle (Keycloak sub or display name).",
    )
    source_decision_id: Optional[str] = Field(
        default=None,
        description=(
            "When the replay was triggered from a review-queue Decision, "
            "the Decision id — captured in the audit trail so we can "
            "answer 'how many replays did the queue actually drive?'"
        ),
    )
    source_feedback_id: Optional[str] = Field(
        default=None,
        description=(
            "When the replay followed a feedback row (E1.5.1), the "
            "feedback id. Lets us correlate corrected_output against "
            "what a replay produced for the same parent."
        ),
    )


@router.post("/{run_id}/replay")
async def replay_run(
    run_id: str,
    body: ReplayRequest,
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    """Re-run a settled chat-style Run with operator overrides applied.

    Returns the new Run id (status is whatever the synchronous
    orchestrator pass produced — typically ``completed``). The
    front-end can then poll ``/evaluation/by-run/{new_run_id}`` to
    surface the eval delta against the parent.

    System-engine runs (DAG executions) are NOT yet supported and
    return 400 with a clear message — see ``replay_service`` docs.
    """
    from app.services.runs.replay_service import (
        ReplayError,
        replay_run_async,
    )

    parent = (
        db.query(Run)
        .filter(Run.id == run_id, Run.workspace_id == workspace.id)
        .first()
    )
    if not parent:
        raise HTTPException(404, "Run not found")

    try:
        new_run, response_text = await replay_run_async(
            db=db,
            parent=parent,
            workspace_slug=workspace.slug,
            overrides=body.overrides or {},
            actor=body.actor,
            source_decision_id=body.source_decision_id,
            source_feedback_id=body.source_feedback_id,
        )
    except ReplayError as exc:
        raise HTTPException(400, str(exc))
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("runs.replay: unhandled error", run_id=run_id)
        raise HTTPException(500, f"replay failed: {exc!r}")

    return {
        "run_id": new_run.id,
        "parent_run_id": parent.id,
        "status": new_run.status,
        "trigger": new_run.trigger,
        "started_at": new_run.started_at.isoformat() if new_run.started_at else None,
        "completed_at": (
            new_run.completed_at.isoformat() if new_run.completed_at else None
        ),
        "duration_ms": new_run.duration_ms,
        "replay_overrides": new_run.replay_overrides or {},
        "response_preview": (response_text[:500] if response_text else ""),
        "eval_pending": True,
    }


@router.get("/{run_id}/replays")
async def list_run_replays(
    run_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    """List runs that were replayed from this run as parent.

    Newest first. Used by the run-detail view to render a "Replays"
    sub-list and by the review queue to indicate when a Decision's
    breached run already has follow-up replays the reviewer can
    compare against.
    """
    parent = (
        db.query(Run)
        .filter(Run.id == run_id, Run.workspace_id == workspace.id)
        .first()
    )
    if not parent:
        raise HTTPException(404, "Run not found")

    children = (
        db.query(Run)
        .filter(
            Run.parent_run_id == run_id,
            Run.workspace_id == workspace.id,
        )
        .order_by(Run.started_at.desc())
        .all()
    )
    return {
        "parent_run_id": run_id,
        "items": [
            {
                **_row(r),
                "replay_overrides": r.replay_overrides or {},
                "evaluation_scores": r.evaluation_scores,
            }
            for r in children
        ],
    }
