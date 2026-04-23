"""Concrete execution engine for canonical Runs.

Historically this walker assumed a *sequence* of canonical skills. From Wave C6
onward the authoring layer can also produce a **DAG** (decision/fork/join/
retry/subflow/hitl/loop nodes) — that variant is served by ``dag.py``.

This module still owns the sequential walker (``execute_run``) plus the two
shared helpers both walkers rely on:

* ``_execute_task_node`` — resolve/invoke/persist one SkillInvocation with
  latency, cost, error handling and ControlPolicy guardrail.
* ``_finalize_run`` — derive the Outcome block, apply post-checks and persist
  the terminal Run state.

Keeping the per-node and finalization logic in one place guarantees the DAG
walker behaves *identically* on task semantics: same cost model, same error
capture, same Outcome derivation, same Decision side-effects.
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4

from sqlalchemy.orm import Session as DBSession

from app.core.logging import get_logger
from app.db.base import SessionLocal
from app.models.capability import Capability
from app.models.decision import Decision
from app.models.policy import AdaptivePolicy, ControlPolicy
from app.models.run import Run, SkillInvocation
from app.models.skill import Skill
from app.models.system import System
from app.services.outcome.derive import derive_outcome
from app.services.skills_registry import resolve as resolve_skill

from .events import bus as event_bus
from .streaming import flush_token_sink, make_token_sink

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def schedule_run(run_id: str) -> None:
    """Fire-and-forget entry point used by FastAPI BackgroundTasks.

    Dispatches to either the sequential walker (``execute_run``) or the DAG
    walker (``execute_run_dag``) based on the System's ``flow_definition``.

    Creates its own event loop when called from a sync context so the HTTP
    handler stays non-blocking. Any raised exception is logged and persisted
    on the Run row — it will *never* bubble back into the web request.
    """
    # Local import avoids a circular dependency at module load time
    # (``dag`` imports the shared helpers from this module).
    from .dag import execute_run_dag, should_use_dag  # noqa: WPS433

    async def _entry() -> None:
        use_dag = False
        db = SessionLocal()
        try:
            run = db.query(Run).filter(Run.id == run_id).first()
            if run:
                system = db.query(System).filter(System.id == run.system_id).first()
                use_dag = bool(system and should_use_dag(system))
        finally:
            db.close()
        if use_dag:
            await execute_run_dag(run_id)
        else:
            await execute_run(run_id)

    try:
        asyncio.run(_entry())
    except RuntimeError:
        loop = asyncio.get_event_loop()
        loop.create_task(_entry())
    except Exception as exc:  # noqa: BLE001
        logger.exception("run_engine.schedule_run failed", run_id=run_id, error=str(exc))


async def execute_run(run_id: str) -> Dict[str, Any]:
    """Sequential walker — executes skill_ids in order, threading outputs.

    Behaviorally identical to pre-C6; now delegates per-node work to
    ``_execute_task_node`` and finalization to ``_finalize_run``.
    """
    db: DBSession = SessionLocal()
    try:
        run = db.query(Run).filter(Run.id == run_id).first()
        if not run:
            logger.warning("run_engine: unknown run_id", run_id=run_id)
            return {"error": "run_not_found"}

        system = db.query(System).filter(System.id == run.system_id).first()
        if not system:
            return _fail(db, run, "system_not_found")

        capability = (
            db.query(Capability).filter(Capability.id == system.capability_id).first()
            if system.capability_id
            else None
        )
        control = _load_control_policy(db, system)
        adaptive = _load_adaptive_policy(db, system)

        skill_slugs = _resolve_skill_sequence(db, system, capability)
        if not skill_slugs:
            return _fail(db, run, "no_skills_bound")

        logger.info(
            "run_engine: start",
            run_id=run.id,
            system_id=system.id,
            capability=capability.slug if capability else None,
            skills=skill_slugs,
        )
        run.status = "running"
        run.started_at = run.started_at or datetime.utcnow()
        db.commit()

        ctx = _build_initial_ctx(run, system, capability)

        start = time.monotonic()
        invocations_out: List[SkillInvocation] = []
        last_output: Dict[str, Any] = {}
        total_cost = 0.0

        for slug in skill_slugs:
            invocation = await _execute_task_node(
                db,
                run,
                ctx,
                slug,
                control=control,
                last_output=last_output,
            )
            if invocation is None:
                continue
            invocations_out.append(invocation)
            total_cost += invocation.cost or 0.0
            if invocation.status == "completed":
                last_output = invocation.output_ref or {}

            if adaptive and adaptive.enabled and _should_stop_adaptive(
                adaptive, invocation, total_cost
            ):
                _log_decision(
                    db,
                    scope="system",
                    target_id=system.id,
                    kind="adaptive_stop",
                    rationale={
                        "after_skill": slug,
                        "total_cost": total_cost,
                        "latency_ms": invocation.latency_ms,
                    },
                )
                break

        duration_ms = (time.monotonic() - start) * 1000
        summary = _finalize_run(
            db,
            run,
            system=system,
            capability=capability,
            control=control,
            invocations=invocations_out,
            duration_ms=duration_ms,
            last_output=last_output,
        )
        logger.info(
            "run_engine: done",
            run_id=run.id,
            status=summary["status"],
            decision=summary.get("outcome", {}).get("decision"),
            confidence=summary.get("outcome", {}).get("confidence"),
            cost=total_cost,
            value=summary.get("outcome", {}).get("value_estimated"),
            duration_ms=duration_ms,
        )
        return summary
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Shared helpers (reused by dag.py)
# ---------------------------------------------------------------------------
def _build_initial_ctx(
    run: Run, system: System, capability: Optional[Capability]
) -> Dict[str, Any]:
    """Build the shared context bag exposed to every skill invocation.

    System-level defaults (prompt type, model, retrieval mode) are propagated
    here so RAG chains and LLM skills pick them up without each trigger having
    to repeat them.
    """
    return {
        "system_id": system.id,
        "capability_id": capability.id if capability else None,
        "workspace_id": run.workspace_id,
        "input": run.input_ref or {},
        "default_prompt_type": getattr(system, "default_prompt_type", None),
        "default_model": getattr(system, "default_model", None),
        "retrieval_mode_default": getattr(system, "retrieval_mode_default", None),
    }


async def _execute_task_node(
    db: DBSession,
    run: Run,
    ctx: Dict[str, Any],
    slug: str,
    *,
    control: Optional[ControlPolicy],
    last_output: Dict[str, Any],
    node_id: Optional[str] = None,
) -> Optional[SkillInvocation]:
    """Invoke one Skill and persist its SkillInvocation ledger row.

    Side-effects:
    * writes an invocation row in ``running`` state, then updates it to
      ``completed`` / ``failed`` / ``skipped`` once the skill returns.
    * on allowed_skills block: emits a ``policy_block`` Decision and returns
      ``None`` (caller decides whether to continue or abort).

    ``node_id`` (optional) attaches a DAG node identifier into the invocation
    ``trace`` so the UI can correlate per-node timing in the Run detail view.
    """
    if control and control.allowed_skills and slug not in control.allowed_skills:
        _log_decision(
            db,
            scope="system",
            target_id=ctx.get("system_id"),
            kind="policy_block",
            rationale={"skill": slug, "reason": "not_in_allowed_skills"},
        )
        return None

    invocation = SkillInvocation(
        id=str(uuid4()),
        run_id=run.id,
        skill_slug=slug,
        status="running",
        started_at=datetime.utcnow(),
        input_ref=_build_skill_input(slug, run.input_ref or {}, last_output, ctx),
        trace={"node_id": node_id} if node_id else {},
    )
    db.add(invocation)
    db.commit()

    # Wire a token sink into ctx iff someone is actually listening on the
    # run's live bus. Skills that don't know about streaming simply
    # ignore the extra key; streaming-capable ones (see
    # ``_azure_llm_v1`` / ``_llm_rag_answer_v1``) dispatch deltas to it
    # token-by-token. We build a shallow copy so sibling DAG branches
    # don't pick up each other's sinks through a shared ctx reference.
    skill_ctx: Dict[str, Any] = dict(ctx) if ctx is not None else {}
    token_sink = None
    if event_bus.is_live(run.id):
        token_sink = make_token_sink(run.id, node_id, invocation.id)
        skill_ctx["token_sink"] = token_sink

    t0 = time.monotonic()
    try:
        fn = resolve_skill(slug)
        output = await fn(invocation.input_ref, skill_ctx)
        invocation.output_ref = output or {}
        invocation.status = "completed"
    except NotImplementedError as nie:
        invocation.status = "skipped"
        invocation.error = f"unimplemented: {nie}"
        logger.info("run_engine: skill unimplemented", run_id=run.id, skill=slug)
    except Exception as exc:  # noqa: BLE001
        invocation.status = "failed"
        invocation.error = str(exc)[:500]
        logger.warning(
            "run_engine: skill failed", run_id=run.id, skill=slug, error=str(exc)
        )
    finally:
        # Drain whatever small residual burst is still in the sink's
        # coalescing buffer so the SSE client sees the tail of the
        # completion before `node_end` lands.
        flush_token_sink(token_sink)

    invocation.latency_ms = (time.monotonic() - t0) * 1000
    invocation.completed_at = datetime.utcnow()
    invocation.cost = _skill_unit_price(db, slug)
    db.commit()
    return invocation


def _finalize_run(
    db: DBSession,
    run: Run,
    *,
    system: System,
    capability: Optional[Capability],
    control: Optional[ControlPolicy],
    invocations: List[SkillInvocation],
    duration_ms: float,
    last_output: Dict[str, Any],
) -> Dict[str, Any]:
    """Derive the canonical Outcome block, apply post-checks, persist."""
    failed = [i for i in invocations if i.status == "failed"]
    derived = derive_outcome(
        invocations=invocations,
        capability=capability,
        control_hitl_threshold=(
            control.mandatory_hitl_if_confidence_below if control else None
        ),
        duration_ms=duration_ms,
    )
    run.status = "completed" if not failed or derived.decision != "blocked" else "failed"
    run.completed_at = datetime.utcnow()
    run.duration_ms = duration_ms
    run.decision = derived.decision
    run.confidence = derived.confidence
    run.value_estimated = derived.value
    run.cost_internal = derived.cost
    run.efficiency = derived.efficiency
    run.value_source = derived.value_source.value
    run.output_ref = last_output or {}
    if control:
        _apply_control_postchecks(db, system, run, control)
    db.commit()

    # Vague E / E1 — schedule post-run auto-evaluation. Fire-and-forget,
    # swallows its own exceptions, runs on its own DB session so we're
    # safe whether this _finalize_run was called from the async engine,
    # the DAG walker, or a sync test harness.
    if run.status == "completed":
        try:
            from app.services.evaluation.auto_eval import schedule_eval

            schedule_eval(run.id)
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "auto_eval: failed to schedule",
                run_id=run.id,
                error=str(exc),
            )

    return {
        "id": run.id,
        "status": run.status,
        "outcome": {
            "decision": derived.decision,
            "confidence": derived.confidence,
            "value_estimated": derived.value,
            "cost_internal": derived.cost,
            "efficiency": derived.efficiency,
        },
        "invocations": len(invocations),
    }


# ---------------------------------------------------------------------------
# Resolution helpers
# ---------------------------------------------------------------------------
def _resolve_skill_sequence(
    db: DBSession, system: System, capability: Optional[Capability]
) -> List[str]:
    """Return the ordered list of skill slugs to invoke for this System."""
    skill_ids: List[str] = list(system.skill_ids or [])
    if not skill_ids and capability:
        skill_ids = list(capability.skill_ids or [])
    if not skill_ids:
        return []
    rows = db.query(Skill).filter(Skill.id.in_(skill_ids)).all()
    by_id = {s.id: s for s in rows}
    return [by_id[i].slug for i in skill_ids if i in by_id]


def _load_control_policy(db: DBSession, system: System) -> Optional[ControlPolicy]:
    if system.control_policy_id:
        return (
            db.query(ControlPolicy)
            .filter(ControlPolicy.id == system.control_policy_id)
            .first()
        )
    return (
        db.query(ControlPolicy)
        .filter(ControlPolicy.scope == "system", ControlPolicy.target_id == system.id)
        .order_by(ControlPolicy.updated_at.desc())
        .first()
    )


def _load_adaptive_policy(db: DBSession, system: System) -> Optional[AdaptivePolicy]:
    if system.adaptive_policy_id:
        return (
            db.query(AdaptivePolicy)
            .filter(AdaptivePolicy.id == system.adaptive_policy_id)
            .first()
        )
    return (
        db.query(AdaptivePolicy)
        .filter(AdaptivePolicy.enabled.is_(True))
        .order_by(AdaptivePolicy.updated_at.desc())
        .first()
    )


def _skill_unit_price(db: DBSession, slug: str) -> float:
    sk = db.query(Skill).filter(Skill.slug == slug).first()
    if not sk:
        return 0.0
    return float((sk.pricing or {}).get("unit_price", 0.0))


# ---------------------------------------------------------------------------
# Skill I/O helpers
# ---------------------------------------------------------------------------
def _build_skill_input(
    slug: str,
    run_input: Dict[str, Any],
    last_output: Dict[str, Any],
    ctx: Dict[str, Any],
) -> Dict[str, Any]:
    """Thread the right fields into each skill's input schema.

    Simple heuristic: start from the run's input, merge last_output, let
    skill-specific conventions override.
    """
    payload: Dict[str, Any] = {}
    payload.update(run_input or {})
    payload.update(last_output or {})
    if slug.startswith("eval_radar") and "answer" not in payload:
        payload["answer"] = last_output.get("answer")
    if slug.startswith("claim_audit") and "citations" not in payload:
        payload["citations"] = last_output.get("citations", [])
    return payload


def _should_stop_adaptive(
    adaptive: AdaptivePolicy, last: SkillInvocation, total_cost: float
) -> bool:
    triggers = adaptive.triggers or {}
    lat_cap = triggers.get("latency_above_ms")
    cost_cap = triggers.get("cost_above")
    if lat_cap is not None and (last.latency_ms or 0) > float(lat_cap):
        return True
    if cost_cap is not None and total_cost > float(cost_cap):
        return True
    return False


def _apply_control_postchecks(
    db: DBSession, system: System, run: Run, control: ControlPolicy
) -> None:
    """Annotate the run when a hard guardrail was breached."""
    breaches: List[str] = []
    if control.max_cost_per_decision is not None and (run.cost_internal or 0) > float(
        control.max_cost_per_decision
    ):
        breaches.append("max_cost_per_decision")
    if control.max_latency_ms is not None and (run.duration_ms or 0) > float(
        control.max_latency_ms
    ):
        breaches.append("max_latency_ms")
    if not breaches:
        return
    _log_decision(
        db,
        scope="system",
        target_id=system.id,
        kind="policy_breach",
        rationale={"breaches": breaches, "run_id": run.id},
    )


def _log_decision(
    db: DBSession,
    *,
    scope: str,
    target_id: Optional[str],
    kind: str,
    rationale: Dict[str, Any],
    status: str = "applied",
    title: Optional[str] = None,
) -> Optional[Decision]:
    """Persist a Decision row. Returns the row so callers can link it
    (e.g. HITL pause stores the decision id in the run checkpoint).
    """
    try:
        title_map = {
            "policy_block": "Skill blocked by policy",
            "policy_breach": "Guardrail breached",
            "adaptive_stop": "Run truncated by adaptive policy",
            "hitl_approval": "Human approval required",
        }
        row = Decision(
            id=str(uuid4()),
            scope=scope,
            target_id=target_id,
            kind=kind,
            status=status,
            title=title or title_map.get(kind, kind.replace("_", " ").title()),
            rationale=rationale,
            impact_estimate={},
        )
        db.add(row)
        db.commit()
        return row
    except Exception as exc:  # noqa: BLE001
        logger.warning("run_engine: decision log failed", kind=kind, error=str(exc))
        db.rollback()
        return None


def _fail(db: DBSession, run: Run, error: str) -> Dict[str, Any]:
    run.status = "failed"
    run.error = error
    run.completed_at = datetime.utcnow()
    db.commit()
    return {"id": run.id, "status": "failed", "error": error}
