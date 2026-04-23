"""Post-run auto-evaluation loop (Vague E / E1).

Hooked at the end of :func:`app.services.run_engine.engine._finalize_run`
for runs that completed successfully. Contract:

- Loads the effective :class:`EvaluationPreset` for the run's triplet
  (system > capability > workspace > built-in defaults).
- If ``enabled`` is False or ``sample_rate`` excludes the run, returns
  a no-op summary — the hook is cheap and always safe to call.
- Otherwise, extracts ``(query, response, context_chunks)`` from the
  run's ``input_ref`` / ``output_ref`` / invocation trail, invokes
  :class:`~app.services.evaluation.judge.JudgeService`, persists a row
  in ``evaluation_scores`` linked to the run, writes the summary back
  to ``run.evaluation_scores``, and — if any threshold is breached —
  files a :class:`Decision` of kind ``review_required`` so the Steer
  review queue can surface it.

The whole pass runs on its **own DB session**: the caller in
``_finalize_run`` has already committed the run, and we don't want to
hold a request-scoped session open while the LLM judge (5-15 s) is in
flight. A failure of the eval loop **must never** fail the run — any
exception is logged and swallowed.
"""
from __future__ import annotations

import asyncio
import random
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4

from sqlalchemy.orm import Session as DBSession

from app.core.logging import get_logger
from app.db.base import SessionLocal
from app.models.decision import Decision
from app.models.evaluation import EvaluationScore
from app.models.run import Run, SkillInvocation
from app.models.system import System
from app.services.evaluation.judge import get_judge_service
from app.services.evaluation_preset_service import get_evaluation_preset_service

logger = get_logger(__name__)


# Keys we try (in order) when extracting the user query / model response
# from the run's input_ref / output_ref. Skills set these under
# different naming conventions historically; we pick the first hit.
_QUERY_KEYS = ("query", "question", "prompt", "input", "user_query", "text")
_RESPONSE_KEYS = ("answer", "response", "output", "text", "completion", "summary")
_CONTEXT_KEYS = ("chunks", "context_chunks", "sources", "passages", "retrieved")


def _first_string(d: Optional[Dict[str, Any]], keys: tuple[str, ...]) -> Optional[str]:
    if not isinstance(d, dict):
        return None
    for k in keys:
        v = d.get(k)
        if isinstance(v, str) and v.strip():
            return v
    return None


def _extract_context(run: Run, invocations: List[SkillInvocation]) -> List[str]:
    """Best-effort collection of context chunks to ground the judge on.

    Checks the run's input_ref first (user may have passed context
    explicitly), then walks invocations looking for RAG-style outputs
    that exposed ``chunks`` / ``sources`` in their output_ref. Returns
    at most 8 chunks, each trimmed to 1000 chars so we stay within the
    judge's prompt budget.
    """
    collected: List[str] = []
    input_ref = run.input_ref or {}
    for key in _CONTEXT_KEYS:
        val = input_ref.get(key)
        if isinstance(val, list):
            for chunk in val:
                if isinstance(chunk, str):
                    collected.append(chunk)
                elif isinstance(chunk, dict):
                    text = chunk.get("text") or chunk.get("content") or chunk.get("snippet")
                    if isinstance(text, str):
                        collected.append(text)
            if collected:
                break

    if not collected:
        for inv in invocations:
            out = inv.output_ref or {}
            for key in _CONTEXT_KEYS:
                val = out.get(key)
                if isinstance(val, list):
                    for chunk in val:
                        if isinstance(chunk, str):
                            collected.append(chunk)
                        elif isinstance(chunk, dict):
                            text = (
                                chunk.get("text")
                                or chunk.get("content")
                                or chunk.get("snippet")
                            )
                            if isinstance(text, str):
                                collected.append(text)
                    if collected:
                        break
            if collected:
                break

    return [c[:1000] for c in collected[:8] if c and c.strip()]


def _check_thresholds(
    scores: Dict[str, float],
    composite_score: float,
    hallucination_rate: float,
    config: Dict[str, Any],
) -> Dict[str, Any]:
    """Return ``{"breach": bool, "reasons": [...]}`` given a config.

    Reasons are machine-readable tuples (metric, observed, threshold,
    direction) so the Decision payload can render them verbatim and
    the UI can filter/sort on them.
    """
    reasons: List[Dict[str, Any]] = []
    composite_min = float(config.get("composite_min", 0.0))
    if composite_score < composite_min:
        reasons.append(
            {
                "metric": "composite_score",
                "observed": composite_score,
                "threshold": composite_min,
                "direction": "below",
            }
        )

    hallucination_max = float(config.get("hallucination_max", 1.0))
    if hallucination_rate > hallucination_max:
        reasons.append(
            {
                "metric": "hallucination_rate",
                "observed": hallucination_rate,
                "threshold": hallucination_max,
                "direction": "above",
            }
        )

    dimension_min = config.get("dimension_min") or {}
    for dimension, floor in dimension_min.items():
        observed = scores.get(dimension)
        if observed is None:
            continue
        if float(observed) < float(floor):
            reasons.append(
                {
                    "metric": f"dimension.{dimension}",
                    "observed": float(observed),
                    "threshold": float(floor),
                    "direction": "below",
                }
            )

    return {"breach": bool(reasons), "reasons": reasons}


async def evaluate_run_async(
    run_id: str,
    *,
    preset_override: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Evaluate a completed run, persist the result, trigger review if needed.

    Always returns — swallows every exception. Caller just fires and
    forgets (typically via ``asyncio.create_task``).

    ``preset_override`` is for tests: bypass the preset resolver and
    use the given config directly.
    """
    db: DBSession = SessionLocal()
    try:
        run = db.query(Run).filter(Run.id == run_id).first()
        if not run:
            logger.warning("auto_eval: run not found", run_id=run_id)
            return None

        if run.status != "completed":
            logger.debug(
                "auto_eval: skipping non-completed run",
                run_id=run_id,
                status=run.status,
            )
            return None

        system = (
            db.query(System).filter(System.id == run.system_id).first()
            if run.system_id
            else None
        )

        if preset_override is not None:
            config = preset_override
        else:
            service = get_evaluation_preset_service()
            config = service.resolve(
                db,
                workspace_id=run.workspace_id,
                capability_id=run.capability_id,
                system_id=run.system_id,
            )

        if not config.get("enabled"):
            logger.debug(
                "auto_eval: disabled for scope",
                run_id=run_id,
                workspace_id=run.workspace_id,
            )
            return None

        sample_rate = float(config.get("sample_rate", 1.0))
        if sample_rate < 1.0 and random.random() > sample_rate:
            logger.debug(
                "auto_eval: skipped by sample_rate",
                run_id=run_id,
                sample_rate=sample_rate,
            )
            return None

        invocations = (
            db.query(SkillInvocation)
            .filter(SkillInvocation.run_id == run_id)
            .order_by(SkillInvocation.started_at.asc())
            .all()
        )

        query = _first_string(run.input_ref, _QUERY_KEYS) or ""
        response = _first_string(run.output_ref, _RESPONSE_KEYS) or ""
        if not response and invocations:
            # Fall back on the terminal skill's output_ref text (common
            # shape: {"answer": "..."} or {"text": "..."}).
            last_output = invocations[-1].output_ref or {}
            response = _first_string(last_output, _RESPONSE_KEYS) or ""

        if not query or not response:
            logger.info(
                "auto_eval: no query/response extractable, skipping",
                run_id=run_id,
                has_query=bool(query),
                has_response=bool(response),
            )
            return None

        context_chunks = _extract_context(run, invocations)

        system_prompt = ""
        if system is not None:
            system_prompt = (
                getattr(system, "default_system_prompt", None)
                or getattr(system, "system_prompt", None)
                or ""
            )

        judge = get_judge_service()
        try:
            result = await judge.evaluate(
                query=query,
                response=response,
                system_prompt=system_prompt,
                context_chunks=context_chunks,
                turn_number=1,
                session_id=run_id,
                agent_id=run.system_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "auto_eval: judge failed",
                run_id=run_id,
                error=str(exc),
            )
            return None

        scores: Dict[str, float] = result.get("scores") or {}
        composite_score = float(result.get("composite_score") or 0.0)
        hallucination_rate = float(result.get("hallucination_rate") or 0.0)

        threshold_outcome = _check_thresholds(
            scores=scores,
            composite_score=composite_score,
            hallucination_rate=hallucination_rate,
            config=config,
        )

        eval_row = EvaluationScore(
            id=result.get("id") or str(uuid4()),
            workspace_id=run.workspace_id,
            run_id=run_id,
            session_id=run_id,
            agent_id=run.system_id,
            turn_number=1,
            query=query[:2000] if query else None,
            scores=scores,
            composite_score=composite_score,
            hallucination_rate=hallucination_rate,
            drift_rate=float(result.get("drift_rate") or 0.0),
            claim_audit=result.get("claim_audit") or {},
            created_at=datetime.utcnow(),
        )
        db.add(eval_row)

        run.evaluation_scores = {
            "composite_score": composite_score,
            "hallucination_rate": hallucination_rate,
            "scores": scores,
            "threshold_breach": threshold_outcome["breach"],
            "reasons": threshold_outcome["reasons"],
            "evaluation_id": eval_row.id,
            "evaluated_at": eval_row.created_at.isoformat(),
        }
        db.commit()

        if threshold_outcome["breach"]:
            _file_review_decision(
                db,
                run=run,
                composite_score=composite_score,
                hallucination_rate=hallucination_rate,
                reasons=threshold_outcome["reasons"],
                evaluation_id=eval_row.id,
            )

        logger.info(
            "auto_eval: done",
            run_id=run_id,
            composite_score=composite_score,
            hallucination_rate=hallucination_rate,
            breach=threshold_outcome["breach"],
            reasons_count=len(threshold_outcome["reasons"]),
        )
        return run.evaluation_scores
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "auto_eval: unexpected error",
            run_id=run_id,
            error=str(exc),
        )
        return None
    finally:
        db.close()


def _file_review_decision(
    db: DBSession,
    *,
    run: Run,
    composite_score: float,
    hallucination_rate: float,
    reasons: List[Dict[str, Any]],
    evaluation_id: str,
) -> Decision:
    """Persist a Decision(kind="review_required") pointing at the run.

    The Decision is filed under ``scope="run"`` so the Steer UI can
    present a flat queue; downstream aggregators (E5 proactive
    recommendations) can roll these up by ``capability_id`` via the
    run join.
    """
    title = _build_review_title(composite_score, hallucination_rate, reasons)
    rationale = {
        "run_id": run.id,
        "system_id": run.system_id,
        "capability_id": run.capability_id,
        "composite_score": composite_score,
        "hallucination_rate": hallucination_rate,
        "reasons": reasons,
        "evaluation_id": evaluation_id,
        "suggestion": _suggest_action(reasons),
    }
    decision = Decision(
        id=str(uuid4()),
        workspace_id=run.workspace_id,
        scope="run",
        target_id=run.id,
        kind="review_required",
        status="proposed",
        title=title,
        rationale=rationale,
    )
    db.add(decision)
    db.commit()
    logger.info(
        "auto_eval: filed review decision",
        run_id=run.id,
        decision_id=decision.id,
        composite_score=composite_score,
    )
    return decision


def _build_review_title(
    composite_score: float,
    hallucination_rate: float,
    reasons: List[Dict[str, Any]],
) -> str:
    if not reasons:
        return "Run flagged for review"
    head = reasons[0]
    metric = head["metric"]
    if metric == "composite_score":
        return f"Run below composite threshold ({composite_score:.0f}/100)"
    if metric == "hallucination_rate":
        return f"Run has high hallucination rate ({hallucination_rate:.1%})"
    if metric.startswith("dimension."):
        dim = metric.split(".", 1)[1]
        return f"Run below {dim} floor ({head['observed']:.0f})"
    return "Run flagged for review"


def _suggest_action(reasons: List[Dict[str, Any]]) -> str:
    """One-line suggestion for the operator, based on the breach shape.

    Kept lexical (no LLM call) on purpose — we already paid for a judge
    call; we don't want to chain a second round-trip just to produce a
    tooltip.
    """
    metrics = [r["metric"] for r in reasons]
    if any(m == "hallucination_rate" for m in metrics) or any(
        m == "dimension.hallucination" for m in metrics
    ):
        return (
            "Tighten the retrieval context or lower the generation "
            "temperature; the model likely answered beyond the sources."
        )
    if any(m == "dimension.safety" for m in metrics):
        return "Review for unsafe content — escalate to policy owner."
    if any(m == "composite_score" for m in metrics):
        return (
            "Inspect the reasoning trail, re-prompt with clearer "
            "instructions, or rerun with an override."
        )
    return "Inspect the response and mark as false positive if acceptable."


def schedule_eval(run_id: str) -> None:
    """Fire-and-forget scheduler used by ``_finalize_run``.

    Creates an asyncio task on the running loop (the engine walkers
    already run inside one); if no loop is active — e.g. a sync test
    harness directly invoking ``_finalize_run`` — we spin a one-shot
    loop via :func:`asyncio.run` on a worker thread so we don't block
    the caller.

    This is intentionally symmetric with
    :func:`app.services.run_engine.engine.schedule_run`: same safe-from-
    sync-context pattern, same no-raise contract.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    coro = evaluate_run_async(run_id)
    if loop and loop.is_running():
        loop.create_task(coro)
        return

    # Sync caller — offload to a thread so we don't block.
    import threading

    def _runner() -> None:
        try:
            asyncio.run(coro)
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "auto_eval: background runner failed",
                run_id=run_id,
                error=str(exc),
            )

    threading.Thread(target=_runner, name=f"auto_eval-{run_id}", daemon=True).start()
