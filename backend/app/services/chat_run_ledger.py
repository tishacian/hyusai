"""Canonical chat Run enrichment for observability and Hypervisor."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

from sqlalchemy.orm import Session as DBSession

from app.models.capability import Capability
from app.models.run import Run, SkillInvocation
from app.models.skill import Skill
from app.models.system import System
from app.services.outcome.derive import derive_outcome


WORKSPACE_ASSISTANT_CAPABILITY_SLUG = "workspace_assistant"

_RETRIEVAL_TELEMETRY_KEYS = (
    "retrieval_profile",
    "latency_profile",
    "retrieval_latency_profile",
    "retrieval_latency_scope",
    "retrieval_decision_trace",
    "dense_policy",
    "dense_only",
    "sparse_status",
    "sparse_backend",
    "sparse_fallback_reason",
    "cross_encoder_status",
    "cross_encoder_model",
    "cross_encoder_ms",
    "cross_encoder_scored",
    "cross_encoder_filtered",
    "cross_encoder_threshold",
    "cross_encoder_budget_seconds",
    "cross_encoder_error",
    "stage_timings",
    "duration_ms",
    "retrieval_elapsed_ms",
    "fallback_reason",
)

_ANSWER_POLICY_KEYS = (
    "answer_profile",
    "answer_profile_decision",
    "answer_policy_applied",
    "answer_policy_violations",
)


def enrich_chat_run_ledger(
    db: DBSession,
    run: Run,
    *,
    sources: Any = None,
    reasoning_trace: Any = None,
    extra_output: Optional[dict[str, Any]] = None,
    create_invocations_if_missing: bool = True,
) -> dict[str, Any]:
    """Attach capability, minimal SkillInvocation trail and Outcome to a chat Run.

    The enrichment is intentionally best-effort and deterministic: chat remains
    the source of truth for response text/sources, while this ledger makes the
    same turn visible in Runs, Observability and Hypervisor.
    """
    capability = _resolve_capability(db, run)
    if capability and not run.capability_id:
        run.capability_id = capability.id

    invocations = (
        db.query(SkillInvocation)
        .filter(SkillInvocation.run_id == run.id)
        .order_by(SkillInvocation.started_at.asc())
        .all()
    )
    created = 0
    if create_invocations_if_missing and not invocations:
        invocations = _create_chat_invocations(
            db,
            run=run,
            sources=sources,
            reasoning_trace=reasoning_trace,
            extra_output=extra_output or {},
        )
        created = len(invocations)

    if capability and _run_needs_outcome(run):
        derived = derive_outcome(
            invocations=invocations,
            capability=capability,
            duration_ms=float(run.duration_ms or 0.0),
        )
        run.decision = derived.decision
        run.confidence = derived.confidence
        run.cost_internal = derived.cost
        run.value_estimated = derived.value
        run.efficiency = derived.efficiency
        run.value_source = derived.value_source.value

    db.flush()
    return {
        "capability_id": run.capability_id,
        "capability_slug": capability.slug if capability else None,
        "invocations_created": created,
        "invocation_count": len(invocations),
        "value_source": run.value_source,
        "cost_internal": run.cost_internal,
        "value_estimated": run.value_estimated,
    }


def _resolve_capability(db: DBSession, run: Run) -> Optional[Capability]:
    if run.capability_id:
        row = db.query(Capability).filter(Capability.id == run.capability_id).first()
        if row:
            return row
    if run.system_id:
        system = db.query(System).filter(System.id == run.system_id).first()
        if system and system.capability_id:
            row = db.query(Capability).filter(Capability.id == system.capability_id).first()
            if row:
                return row
    return (
        db.query(Capability)
        .filter(Capability.slug == WORKSPACE_ASSISTANT_CAPABILITY_SLUG)
        .first()
    )


def _run_needs_outcome(run: Run) -> bool:
    if (run.value_source or "") == "operator":
        return False
    return any(
        value is None
        for value in (
            run.decision,
            run.cost_internal,
            run.value_estimated,
            run.value_source,
        )
    )


def _create_chat_invocations(
    db: DBSession,
    *,
    run: Run,
    sources: Any,
    reasoning_trace: Any,
    extra_output: dict[str, Any],
) -> list[SkillInvocation]:
    started_at = run.started_at or datetime.utcnow()
    duration_ms = float(run.duration_ms or 0.0)
    completed_at = run.completed_at or started_at + timedelta(milliseconds=max(duration_ms, 1.0))
    confidence = _estimate_chat_confidence(sources, reasoning_trace, extra_output)
    retrieval_telemetry = _retrieval_telemetry(extra_output)

    specs: list[dict[str, Any]] = []
    if _is_trivial(extra_output):
        specs.append(
            {
                "slug": "chat_trivial_bypass_v1",
                "latency_share": 0.25,
                "output_ref": {
                    "confidence": confidence,
                    "mode": "trivial_bypass",
                    "retrieval_decision_trace": retrieval_telemetry.get("retrieval_decision_trace"),
                },
                "metrics": retrieval_telemetry,
            }
        )
    else:
        if _has_retrieval(sources, extra_output):
            specs.append(
                {
                    "slug": "semantic_search_v1",
                    "latency_share": 0.30,
                    "output_ref": {
                        "confidence": confidence,
                        "source_count": len(sources) if isinstance(sources, list) else None,
                        "retrieval_observability": retrieval_telemetry or None,
                    },
                    "metrics": retrieval_telemetry,
                }
            )
        specs.append(
            {
                "slug": "llm_rag_answer_v1",
                "latency_share": 0.55,
                "output_ref": {
                    "confidence": confidence,
                    "response": "completed",
                    **_answer_policy_telemetry(extra_output),
                },
            }
        )
        if extra_output.get("deep_job_id") or extra_output.get("deep_retrieval_recommended"):
            specs.append(
                {
                    "slug": "chain_mixed_hah_v1",
                    "latency_share": 0.05,
                    "output_ref": {
                        "deep_job_id": extra_output.get("deep_job_id"),
                        "recommended": bool(extra_output.get("deep_retrieval_recommended")),
                    },
                }
            )
    specs.append(
        {
            "slug": "audit_log_v1",
            "latency_share": 0.05,
            "output_ref": {"ledger": "chat_run"},
        }
    )

    invocations: list[SkillInvocation] = []
    cursor = started_at
    for spec in specs:
        latency_ms = max(1.0, duration_ms * float(spec["latency_share"]))
        end = min(completed_at, cursor + timedelta(milliseconds=latency_ms))
        invocation = SkillInvocation(
            run_id=run.id,
            skill_slug=spec["slug"],
            status="completed",
            started_at=cursor,
            completed_at=end,
            latency_ms=latency_ms,
            cost=_skill_unit_price(db, str(spec["slug"])),
            input_ref={"run_trigger": run.trigger or "chat"},
            output_ref={k: v for k, v in dict(spec["output_ref"]).items() if v is not None},
            metrics=dict(spec.get("metrics") or {}),
            trace={},
        )
        db.add(invocation)
        invocations.append(invocation)
        cursor = end
    db.flush()
    return invocations


def _retrieval_telemetry(extra_output: dict[str, Any]) -> dict[str, Any]:
    metrics = extra_output.get("retrieval_metrics")
    metrics = metrics if isinstance(metrics, dict) else {}
    out: dict[str, Any] = {}
    for key in _RETRIEVAL_TELEMETRY_KEYS:
        value = extra_output.get(key)
        if value is None:
            value = metrics.get(key)
        if value is not None:
            out[key] = value
    if not out.get("latency_profile"):
        budget = extra_output.get("latency_budget") or metrics.get("latency_budget")
        if isinstance(budget, dict) and budget.get("profile"):
            out["latency_profile"] = str(budget["profile"])
    if out.get("latency_profile") and not out.get("retrieval_latency_profile"):
        out["retrieval_latency_profile"] = out["latency_profile"]
    if out:
        out.setdefault("retrieval_latency_scope", "direct_chat")
    return out


def _answer_policy_telemetry(extra_output: dict[str, Any]) -> dict[str, Any]:
    return {key: extra_output.get(key) for key in _ANSWER_POLICY_KEYS if extra_output.get(key) is not None}


def _skill_unit_price(db: DBSession, slug: str) -> float:
    skill = db.query(Skill).filter(Skill.slug == slug).first()
    pricing = skill.pricing if skill else None
    if not isinstance(pricing, dict):
        return 0.0
    try:
        return round(float(pricing.get("unit_price") or 0.0), 6)
    except (TypeError, ValueError):
        return 0.0


def _estimate_chat_confidence(
    sources: Any,
    reasoning_trace: Any,
    extra_output: dict[str, Any],
) -> float:
    metrics = extra_output.get("retrieval_metrics")
    if isinstance(metrics, dict):
        for key in ("confidence", "answer_confidence", "retrieval_confidence"):
            try:
                raw = metrics.get(key)
                if raw is not None:
                    return max(0.0, min(1.0, float(raw)))
            except (TypeError, ValueError):
                continue
    if _is_trivial(extra_output):
        return 0.95
    if isinstance(sources, list) and sources:
        return 0.86
    if reasoning_trace:
        return 0.72
    return 0.60


def _is_trivial(extra_output: dict[str, Any]) -> bool:
    return bool(extra_output.get("trivial_bypass"))


def _has_retrieval(sources: Any, extra_output: dict[str, Any]) -> bool:
    if isinstance(sources, list) and sources:
        return True
    metrics = extra_output.get("retrieval_metrics")
    return isinstance(metrics, dict) and bool(metrics)
