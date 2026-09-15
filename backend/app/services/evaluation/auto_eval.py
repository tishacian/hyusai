"""Post-run auto-evaluation loop (Vague E / E1).

Hooked at the end of :func:`app.services.run_engine.engine._finalize_run`
for runs that completed successfully. Contract:

- Loads the effective :class:`EvaluationPreset` for the run's triplet
  (system > capability > workspace > built-in defaults).
- If ``enabled`` is False or ``sample_rate`` excludes the run, returns
  a persisted skipped state.
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
from app.services.evaluation.rag_components import (
    heuristic_question_type,
    infer_failed_components,
    normalize_question_type,
)
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


def _context_evidence(run: Run, invocations: List[SkillInvocation]) -> List[dict]:
    for payload, invocation_id in [(run.input_ref or {}, None), (run.output_ref or {}, None), *[(payload or {}, i.id) for i in invocations for payload in (i.input_ref, i.output_ref)]]:
        # Chat persists the actual synthesis context here, separately from its
        # shortened display sources. Use the recorded context, never re-retrieve.
        if isinstance(payload.get("rag_context"), dict) and isinstance(payload["rag_context"].get("chunks"), list) and payload["rag_context"]["chunks"]:
            payload = payload["rag_context"]
        for key in _CONTEXT_KEYS:
            values = payload.get(key)
            if not isinstance(values, list):
                continue
            metadata = payload.get("metadatas")
            aligned = isinstance(metadata, list) and len(metadata) == len(values)
            rows = []
            for index, chunk in enumerate(values):
                if isinstance(chunk, str) and aligned and isinstance(metadata[index], dict):
                    chunk = {"text": chunk, "metadata": metadata[index]}
                text = chunk if isinstance(chunk, str) else (chunk.get("text") or chunk.get("content") or chunk.get("snippet")) if isinstance(chunk, dict) else None
                if not isinstance(text, str) or not text.strip():
                    continue
                ref = {k: chunk[k] for k in ("document_id", "document_ref", "source_id", "collection_id", "collection", "page", "chunk_id", "filename") if k in chunk} if isinstance(chunk, dict) else {}
                if isinstance(chunk, dict) and isinstance(chunk.get("metadata"), dict):
                    ref = {**{k: v for k, v in chunk["metadata"].items() if k in ("document_id", "source_id", "collection_id", "collection", "page", "filename")}, **ref}
                if isinstance(chunk, dict) and isinstance(chunk.get("metadata"), dict):
                    meta = chunk["metadata"]
                    if "filename" not in ref and meta.get("document_filename"):
                        ref["filename"] = meta["document_filename"]
                    if "chunk_id" not in ref and meta.get("chunk_id"):
                        ref["chunk_id"] = meta["chunk_id"]
                rows.append({"text": text, "invocation_id": invocation_id, **ref})
            if rows:
                return rows
    return []


def _extract_context(run: Run, invocations: List[SkillInvocation]) -> List[str]:
    return [r["text"] for r in _context_evidence(run, invocations)[:8]]


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
    if composite_score is not None and composite_score < composite_min:
        reasons.append(
            {
                "metric": "composite_score",
                "observed": composite_score,
                "threshold": composite_min,
                "direction": "below",
            }
        )

    hallucination_max = float(config.get("hallucination_max", 1.0))
    if hallucination_rate is not None and hallucination_rate > hallucination_max:
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
    invocation_id: Optional[str] = None,
    job_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Evaluate a completed run, persist the result, trigger review if needed.

    Runs on the durable WorkspaceJob worker. Judge failures are persisted
    independently of the already finished business Run.

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

        def finish_state(status, reason):
            run.evaluation_scores = {"job_id": job_id, "status": status, "reason": reason, "preset": config, "evaluated_at": datetime.utcnow().isoformat()}
            db.commit()
            return run.evaluation_scores

        if not config.get("enabled"):
            logger.debug(
                "auto_eval: disabled for scope",
                run_id=run_id,
                workspace_id=run.workspace_id,
            )
            return finish_state("skipped", "preset_disabled")

        sample_rate = float(config.get("sample_rate", 1.0))
        if sample_rate < 1.0 and random.random() > sample_rate:
            logger.debug(
                "auto_eval: skipped by sample_rate",
                run_id=run_id,
                sample_rate=sample_rate,
            )
            return finish_state("skipped", "sampling_excluded")

        invocations = (
            db.query(SkillInvocation)
            .filter(SkillInvocation.run_id == run_id)
            .order_by(SkillInvocation.started_at.asc())
            .all()
        )

        if invocation_id:
            invocations = [i for i in invocations if i.id == invocation_id]
            if not invocations:
                return finish_state("failed", "invocation_unavailable")

        query = (_first_string(invocations[0].input_ref, _QUERY_KEYS) if invocation_id else None) or _first_string(run.input_ref, _QUERY_KEYS) or ""
        response = _first_string(invocations[0].output_ref if invocation_id else run.output_ref, _RESPONSE_KEYS) or ""
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
            return finish_state("skipped", "output_not_evaluable")

        context_chunks = _extract_context(run, invocations)

        system_prompt = ""
        if system is not None:
            system_prompt = (
                getattr(system, "default_system_prompt", None)
                or getattr(system, "system_prompt", None)
                or ""
            )

        run.evaluation_scores = {"status": "running", "job_id": job_id, "preset": config, "started_at": datetime.utcnow().isoformat()}
        db.commit()
        from app.models.workspace import Workspace
        workspace = db.query(Workspace).filter(Workspace.id == run.workspace_id).first()
        from app.services.evaluation.lifecycle import evaluation_model_context
        model_context = evaluation_model_context(db, run, system, invocations)
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
                workspace=workspace,
                model_context=model_context,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "auto_eval: judge failed",
                run_id=run_id,
                error=str(exc),
            )
            return finish_state("failed", "judge_unavailable")

        metadata = dict(result.get("metadata") or {})
        evidence = _context_evidence(run, invocations)
        metadata["excerpts"] = [
            {**{k: v for k, v in evidence[index].items() if k != "text"}, **excerpt}
            for index, excerpt in enumerate(metadata.get("excerpts") or []) if index < len(evidence)
        ]
        metadata["context_count_available"] = len(evidence)
        metadata["context_truncated"] = len(evidence) > len(metadata["excerpts"]) or any(e.get("truncated") for e in metadata["excerpts"])
        result["metadata"] = metadata
        scores: Dict[str, float] = result.get("scores") or {}
        composite_score = result.get("composite_score")
        hallucination_rate = result.get("hallucination_rate")

        threshold_outcome = _check_thresholds(
            scores=scores,
            composite_score=composite_score,
            hallucination_rate=hallucination_rate,
            config=config,
        )
        question_type = normalize_question_type(
            result.get("question_type") or heuristic_question_type(query)
        )
        failed_components = infer_failed_components(
            question_type=question_type,
            scores=scores,
            composite_score=composite_score if composite_score is not None else 100,
            hallucination_rate=hallucination_rate or 0,
            threshold_breach=threshold_outcome["breach"],
        )
        topic = result.get("topic") if isinstance(result.get("topic"), str) else None

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
            drift_rate=result.get("drift_rate"),
            question_type=question_type,
            failed_components=failed_components,
            topic=topic[:200] if topic else None,
            claim_audit=result.get("claim_audit") or {},
            metadata_={**(result.get("metadata") or {}), "status": result.get("status", "completed"), "reason": result.get("reason"), "preset": config, "invocation_id": invocation_id, "threshold_outcome": threshold_outcome},
            created_at=datetime.utcnow(),
        )
        db.add(eval_row)
        db.flush()
        from sqlalchemy import update
        db.execute(update(EvaluationScore).where(EvaluationScore.id == eval_row.id).values(
            composite_score=composite_score, hallucination_rate=hallucination_rate,
            drift_rate=result.get("drift_rate")))

        run.evaluation_scores = {
            "job_id": job_id,
            "status": result.get("status", "completed"),
            "reason": result.get("reason"),
            "metadata": eval_row.metadata_,
            "claim_audit": eval_row.claim_audit,
            "composite_score": composite_score,
            "hallucination_rate": hallucination_rate,
            "scores": scores,
            "threshold_breach": threshold_outcome["breach"],
            "reasons": threshold_outcome["reasons"],
            "question_type": question_type,
            "failed_components": failed_components,
            "topic": topic,
            "evaluation_id": eval_row.id,
            "evaluated_at": eval_row.created_at.isoformat(),
        }
        if threshold_outcome["breach"] and composite_score is not None and hallucination_rate is not None:
            # Corrections are requested from the inspected evidence and reviewed
            # against a draft. Do not generate legacy executable rerun/answer
            # suggestions as a side effect of scoring.
            active_suggestion = {}
            _file_review_decision(
                db,
                run=run,
                composite_score=composite_score,
                hallucination_rate=hallucination_rate,
                reasons=threshold_outcome["reasons"],
                evaluation_id=eval_row.id,
                question_type=question_type,
                failed_components=failed_components,
                topic=topic,
                active_suggestion=active_suggestion,
            )

        db.commit()
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
    question_type: str,
    failed_components: List[str],
    topic: Optional[str],
    active_suggestion: Optional[Dict[str, Any]] = None,
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
        "question_type": question_type,
        "failed_components": failed_components,
        "topic": topic,
        "active_suggestion": active_suggestion or {},
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
    """Persist auto evaluation before dispatching to the durable worker."""
    from app.services.evaluation.lifecycle import enqueue_run_evaluation
    db = SessionLocal()
    try:
        run = db.query(Run).filter(Run.id == run_id).first()
        if run:
            enqueue_run_evaluation(db, run, user=None, idempotency_key="auto")
    except Exception:
        db.rollback()
        logger.exception("auto_eval dispatch failed", run_id=run_id)
    finally:
        db.close()
