"""Concrete execution engine for canonical Runs.

The engine is intentionally pragmatic rather than a full DAG scheduler:
capabilities today express a *sequence* of canonical skills. The engine walks
that sequence, threads each skill's output into the next skill's input using a
shared context bag, records invocations, computes an Outcome, and applies
policy guardrails.

Hooks for Phase 7+ (streaming, parallel fan-out, HITL approval, adaptive
switch-model) are already wired behind the `AdaptivePolicy` consultation.
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

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def schedule_run(run_id: str) -> None:
    """Fire-and-forget entry point used by FastAPI BackgroundTasks.

    Creates its own event loop when called from a sync context so the HTTP
    handler stays non-blocking. Any raised exception is logged and persisted
    on the Run row — it will *never* bubble back into the web request.
    """
    try:
        asyncio.run(execute_run(run_id))
    except RuntimeError:
        # Already inside an event loop (rare for BackgroundTasks): schedule as task.
        loop = asyncio.get_event_loop()
        loop.create_task(execute_run(run_id))
    except Exception as exc:  # noqa: BLE001
        logger.exception("run_engine.schedule_run failed", run_id=run_id, error=str(exc))


async def execute_run(run_id: str) -> Dict[str, Any]:
    """Execute one Run end-to-end. Returns the final Outcome payload."""
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

        ctx: Dict[str, Any] = {
            "system_id": system.id,
            "capability_id": capability.id if capability else None,
            "workspace_id": run.workspace_id,
            "input": run.input_ref or {},
            # System-level defaults exposed to every skill invocation so
            # RAG chains / LLM skills pick them up without the run
            # trigger having to repeat them on each call.
            "default_prompt_type": getattr(system, "default_prompt_type", None),
            "default_model": getattr(system, "default_model", None),
            "retrieval_mode_default": getattr(system, "retrieval_mode_default", None),
        }

        start = time.monotonic()
        invocations_out: List[SkillInvocation] = []
        last_output: Dict[str, Any] = {}
        total_cost = 0.0

        for idx, slug in enumerate(skill_slugs):
            # Hard guardrail: allowed_skills whitelist.
            if control and control.allowed_skills and slug not in control.allowed_skills:
                _log_decision(
                    db,
                    scope="system",
                    target_id=system.id,
                    kind="policy_block",
                    rationale={"skill": slug, "reason": "not_in_allowed_skills"},
                )
                continue

            invocation = SkillInvocation(
                id=str(uuid4()),
                run_id=run.id,
                skill_slug=slug,
                status="running",
                started_at=datetime.utcnow(),
                input_ref=_build_skill_input(slug, run.input_ref or {}, last_output, ctx),
            )
            db.add(invocation)
            db.commit()

            t0 = time.monotonic()
            try:
                fn = resolve_skill(slug)
                output = await fn(invocation.input_ref, ctx)
                invocation.output_ref = output or {}
                invocation.status = "completed"
                last_output = output or {}
            except NotImplementedError as nie:
                invocation.status = "skipped"
                invocation.error = f"unimplemented: {nie}"
                logger.info("run_engine: skill unimplemented", run_id=run.id, skill=slug)
            except Exception as exc:  # noqa: BLE001
                invocation.status = "failed"
                invocation.error = str(exc)[:500]
                logger.warning("run_engine: skill failed", run_id=run.id, skill=slug, error=str(exc))

            latency = (time.monotonic() - t0) * 1000
            invocation.latency_ms = latency
            invocation.completed_at = datetime.utcnow()
            # Cost is the skill's unit price if known.
            invocation.cost = _skill_unit_price(db, slug)
            total_cost += invocation.cost or 0.0
            db.commit()
            invocations_out.append(invocation)

            # Soft hint from AdaptivePolicy — e.g. stop early on latency blow-up.
            if adaptive and adaptive.enabled and _should_stop_adaptive(adaptive, invocation, total_cost):
                _log_decision(
                    db,
                    scope="system",
                    target_id=system.id,
                    kind="adaptive_stop",
                    rationale={
                        "after_skill": slug,
                        "total_cost": total_cost,
                        "latency_ms": latency,
                    },
                )
                break

        duration_ms = (time.monotonic() - start) * 1000

        # ---- Outcome aggregation (canonical derivation service) -----------
        failed = [i for i in invocations_out if i.status == "failed"]
        derived = derive_outcome(
            invocations=invocations_out,
            capability=capability,
            control_hitl_threshold=(
                control.mandatory_hitl_if_confidence_below if control else None
            ),
            duration_ms=duration_ms,
        )
        confidence = derived.confidence
        decision = derived.decision
        value_est = derived.value
        efficiency = derived.efficiency

        run.status = "completed" if not failed or decision != "blocked" else "failed"
        run.completed_at = datetime.utcnow()
        run.duration_ms = duration_ms
        run.decision = decision
        run.confidence = confidence
        run.value_estimated = value_est
        run.cost_internal = derived.cost
        run.efficiency = efficiency
        run.value_source = derived.value_source.value
        run.output_ref = last_output or {}
        if control:
            _apply_control_postchecks(db, system, run, control)
        db.commit()

        logger.info(
            "run_engine: done",
            run_id=run.id,
            status=run.status,
            decision=decision,
            confidence=confidence,
            cost=total_cost,
            value=value_est,
            duration_ms=duration_ms,
        )

        return {
            "id": run.id,
            "status": run.status,
            "outcome": {
                "decision": decision,
                "confidence": confidence,
                "value_estimated": value_est,
                "cost_internal": total_cost,
                "efficiency": efficiency,
            },
            "invocations": len(invocations_out),
        }
    finally:
        db.close()


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
    # Preserve the order of `skill_ids`.
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
# Outcome helpers
# ---------------------------------------------------------------------------
def _build_skill_input(
    slug: str,
    run_input: Dict[str, Any],
    last_output: Dict[str, Any],
    ctx: Dict[str, Any],
) -> Dict[str, Any]:
    """Thread the right fields into each skill's input schema."""
    # Simple heuristic: start from the run's input, merge last_output, let
    # skill-specific fields coming from ctx override.
    payload: Dict[str, Any] = {}
    payload.update(run_input or {})
    payload.update(last_output or {})
    # Eval radar expects an `answer` field — pull it from last rag step if missing.
    if slug.startswith("eval_radar") and "answer" not in payload:
        payload["answer"] = last_output.get("answer")
    if slug.startswith("claim_audit") and "citations" not in payload:
        payload["citations"] = last_output.get("citations", [])
    return payload


def _extract_confidence(invocations: List[SkillInvocation]) -> Optional[float]:
    for inv in invocations:
        out = inv.output_ref or {}
        if "confidence" in out:
            try:
                return float(out["confidence"])
            except (TypeError, ValueError):
                continue
    # No explicit signal — degrade to the success-ratio.
    if not invocations:
        return None
    return round(len(invocations) / max(len(invocations), 1), 3)


def _derive_decision(
    completed: List[SkillInvocation],
    failed: List[SkillInvocation],
    control: Optional[ControlPolicy],
    confidence: Optional[float],
) -> str:
    if not completed and failed:
        return "failed"
    if control and control.mandatory_hitl_if_confidence_below is not None:
        if (confidence or 0) < control.mandatory_hitl_if_confidence_below:
            return "hitl_escalated"
    if failed:
        return "partial"
    return "approved"


def _estimate_value(capability: Optional[Capability], decision: str) -> float:
    if not capability or capability.value_per_outcome is None:
        return 0.0
    if decision in ("failed", "blocked", "hitl_escalated"):
        return 0.0
    if decision == "partial":
        return float(capability.value_per_outcome) * 0.5
    return float(capability.value_per_outcome)


def _compute_efficiency(value: float, cost: float, duration_ms: float) -> Optional[float]:
    if cost <= 0:
        return None
    # Efficiency blends economic yield with speed.
    roi = (value - cost) / cost if cost else 0.0
    speed = 1.0 / (1.0 + duration_ms / 5000.0)  # normalised around 5s budgets
    return round(max(0.0, roi) * speed, 3)


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
) -> None:
    try:
        title_map = {
            "policy_block": "Skill blocked by policy",
            "policy_breach": "Guardrail breached",
            "adaptive_stop": "Run truncated by adaptive policy",
        }
        row = Decision(
            id=str(uuid4()),
            scope=scope,
            target_id=target_id,
            kind=kind,
            status="applied",
            title=title_map.get(kind, kind.replace("_", " ").title()),
            rationale=rationale,
            impact_estimate={},
        )
        db.add(row)
        db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("run_engine: decision log failed", kind=kind, error=str(exc))
        db.rollback()


def _fail(db: DBSession, run: Run, error: str) -> Dict[str, Any]:
    run.status = "failed"
    run.error = error
    run.completed_at = datetime.utcnow()
    db.commit()
    return {"id": run.id, "status": "failed", "error": error}
