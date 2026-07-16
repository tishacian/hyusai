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
import hashlib
import json
import time
from copy import deepcopy
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
from app.models.workspace import Workspace
from app.services.membrane.spec import MembraneSpec, resolve_membrane_spec
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


def run_subflow_child(child_run_id: str) -> Dict[str, Any]:
    """Synchronous entry point to execute a delegated child run (P4).

    Used by the ``agentium.subflow_run`` Celery task. Picks the DAG or
    sequential walker for the child System and drives it on its own event loop,
    mirroring :func:`schedule_run`.
    """
    from .dag import execute_run_dag, should_use_dag  # noqa: WPS433

    async def _entry() -> Dict[str, Any]:
        use_dag = False
        db = SessionLocal()
        try:
            run = db.query(Run).filter(Run.id == child_run_id).first()
            if run:
                system = db.query(System).filter(System.id == run.system_id).first()
                use_dag = bool(system and should_use_dag(system))
        finally:
            db.close()
        if use_dag:
            return await execute_run_dag(child_run_id)
        return await execute_run(child_run_id)

    return asyncio.run(_entry())


def schedule_subflow_run(child_run_id: str) -> Optional[str]:
    """Dispatch a delegated child run.

    Prefers the Celery task (``agentium.subflow_run``) for true fan-out; if
    Celery is unavailable (no broker, eager tests) it falls back to executing
    the child in-process. Returns the Celery task id when queued, else ``None``.
    The synchronous subflow node merges output via the in-process path; this
    helper exists for asynchronous fan-out delegation.
    """
    try:
        from app.workers.tasks import subflow_run as subflow_task  # noqa: WPS433

        async_result = subflow_task.delay(child_run_id)
        return getattr(async_result, "id", None)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "run_engine.schedule_subflow_run: celery dispatch failed, running in-process",
            child_run_id=child_run_id,
            error=str(exc),
        )
        try:
            run_subflow_child(child_run_id)
        except Exception as inner:  # noqa: BLE001
            logger.exception(
                "run_engine.schedule_subflow_run: in-process fallback failed",
                child_run_id=child_run_id,
                error=str(inner),
            )
        return None


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
        _snapshot_run_flow(db, run, system)
        db.commit()

        ctx = _build_initial_ctx(db, run, system, capability)

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

            if (
                adaptive
                and adaptive.enabled
                and _should_stop_adaptive(adaptive, invocation, total_cost)
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
    db: DBSession,
    run: Run,
    system: System,
    capability: Optional[Capability],
) -> Dict[str, Any]:
    """Build the shared context bag exposed to every skill invocation.

    System-level defaults (prompt type, model, retrieval mode) are propagated
    here so RAG chains and LLM skills pick them up without each trigger having
    to repeat them.
    """
    input_ref = run.input_ref if isinstance(run.input_ref, dict) else {}
    workspace_slug = db.query(Workspace.slug).filter(Workspace.id == run.workspace_id).scalar()
    return {
        "system_id": system.id,
        "capability_id": capability.id if capability else None,
        "workspace_id": run.workspace_id,
        "input": input_ref,
        # Tenant identity is server-owned. ``Run.input_ref`` is caller input
        # on the public Systems API and must never select a physical corpus.
        "workspace_slug": workspace_slug,
        "session_id": input_ref.get("session_id"),
        "user_id": run.initiated_by_user_id,
        "knowledge_scope": input_ref.get("knowledge_scope"),
        "source_policy": input_ref.get("source_policy"),
        # ``_snapshot_run_flow`` replaces caller input with the System-owned
        # contract on first execution, then preserves that immutable snapshot.
        "retrieval_contract": input_ref.get("retrieval_contract") or {},
        "default_prompt_type": getattr(system, "default_prompt_type", None),
        "default_model": getattr(system, "default_model", None),
        "retrieval_mode_default": getattr(system, "retrieval_mode_default", None),
    }


def _snapshot_run_flow(db: DBSession, run: Run, system: System) -> None:
    """Freeze the exact executable graph and its identity on first start."""

    flow = system.flow_definition if isinstance(system.flow_definition, dict) else {}
    first_execution = run.flow_snapshot is None
    if run.flow_snapshot is None:
        run.flow_snapshot = deepcopy(flow)
    input_ref = deepcopy(run.input_ref) if isinstance(run.input_ref, dict) else {}
    if system.workspace_id and run.workspace_id and system.workspace_id != run.workspace_id:
        raise RuntimeError("run_system_workspace_mismatch")
    canonical_workspace_id = system.workspace_id or run.workspace_id
    run.workspace_id = canonical_workspace_id
    workspace_slug = None
    if canonical_workspace_id:
        workspace_slug = (
            db.query(Workspace.slug).filter(Workspace.id == canonical_workspace_id).scalar()
        )
        if not workspace_slug:
            raise RuntimeError("run_workspace_not_found")
    # Canonical tenant and actor fields always win over caller-supplied input.
    input_ref["workspace_id"] = canonical_workspace_id
    if workspace_slug:
        input_ref["workspace_slug"] = workspace_slug
    else:
        input_ref.pop("workspace_slug", None)
    input_ref["user_id"] = run.initiated_by_user_id
    if first_execution:
        system_settings = system.settings if isinstance(system.settings, dict) else {}
        input_ref["retrieval_contract"] = deepcopy(system_settings.get("retrieval_contract") or {})
    execution = dict(input_ref.get("execution") or {})
    if "flow_sha256" not in execution:
        encoded = json.dumps(
            run.flow_snapshot or {},
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        execution["flow_sha256"] = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    system_settings = system.settings if isinstance(system.settings, dict) else {}
    if system_settings.get("flow_revision") is not None:
        execution.setdefault("flow_revision", system_settings.get("flow_revision"))
    execution.setdefault("system_id", system.id)
    input_ref["execution"] = execution
    run.input_ref = input_ref


async def _execute_task_node(
    db: DBSession,
    run: Run,
    ctx: Dict[str, Any],
    slug: str,
    *,
    control: Optional[ControlPolicy],
    last_output: Dict[str, Any],
    node_id: Optional[str] = None,
    resolved_input: Optional[Dict[str, Any]] = None,
) -> Optional[SkillInvocation]:
    """Invoke one Skill and persist its SkillInvocation ledger row.

    Side-effects:
    * writes an invocation row in ``running`` state, then updates it to
      ``completed`` / ``failed`` / ``skipped`` once the skill returns.
    * on allowed_skills block: emits a ``policy_block`` Decision and returns
      ``None`` (caller decides whether to continue or abort).

    ``node_id`` (optional) attaches a DAG node identifier into the invocation
    ``trace`` so the UI can correlate per-node timing in the Run detail view.

    ``resolved_input`` (P1, optional) is an explicit skill input the DAG walker
    already resolved against the typed :class:`VariablePool` (a node carrying an
    ``inputs_map``). When supplied it is used verbatim; otherwise we fall back to
    the legacy merge heuristic via :func:`_build_skill_input` — the path the
    sequential walker (and DAG nodes with no maps) always takes, so behaviour is
    unchanged for them.
    """
    # Membrane capability facet (P3). The effective allow-list is read through
    # the membrane: when no explicit ``membrane_spec`` exists it mirrors
    # ``control.allowed_skills`` exactly (byte-identical to the pre-membrane
    # block); an authoritative spec may tighten it. Fail-soft — a malformed
    # spec degrades to the legacy control check, never crashing the run.
    blocked, membrane_authoritative = _membrane_skill_blocked(control, slug)
    if blocked:
        _log_decision(
            db,
            scope="system",
            target_id=ctx.get("system_id"),
            kind="policy_block",
            rationale={
                "run_id": run.id,
                "skill": slug,
                "reason": "not_in_allowed_skills",
                "membrane": membrane_authoritative,
            },
        )
        marker = {
            "kind": "policy_block",
            "t": datetime.utcnow().isoformat(),
            "node_id": node_id,
            "skill_slug": slug,
            "error": f"policy_blocked_skill:{slug}",
        }
        run.error = run.error or marker["error"]
        run.checkpoints = [*(run.checkpoints or []), marker]
        db.commit()
        try:
            event_bus.publish(run.id, marker)
        except Exception:  # noqa: BLE001 - persisted marker is authoritative.
            pass
        return None

    skill_input = (
        dict(resolved_input)
        if resolved_input is not None
        else _build_skill_input(slug, run.input_ref or {}, last_output, ctx)
    )
    invocation = SkillInvocation(
        id=str(uuid4()),
        run_id=run.id,
        skill_slug=slug,
        status="running",
        started_at=datetime.utcnow(),
        input_ref=skill_input,
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
    except asyncio.CancelledError:
        invocation.status = "cancelled"
        invocation.error = "execution_cancelled"
        invocation.latency_ms = (time.monotonic() - t0) * 1000
        invocation.completed_at = datetime.utcnow()
        invocation.cost = _skill_unit_price(db, slug)
        db.commit()
        raise
    except NotImplementedError as nie:
        invocation.status = "skipped"
        invocation.error = f"unimplemented: {nie}"
        logger.info("run_engine: skill unimplemented", run_id=run.id, skill=slug)
    except Exception as exc:  # noqa: BLE001
        invocation.status = "failed"
        invocation.error = str(exc)[:500]
        logger.warning("run_engine: skill failed", run_id=run.id, skill=slug, error=str(exc))
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
        control_hitl_threshold=(control.mandatory_hitl_if_confidence_below if control else None),
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
    # Chat-Agentic Runs are finalized by the surface adapter after it has
    # enforced citations/collection policy and attached normalized sources.
    # Scheduling here would race the evaluator against that canonical output.
    if run.status == "completed" and run.trigger != "chat_agentic":
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
            .filter(
                ControlPolicy.id == system.control_policy_id,
                ControlPolicy.workspace_id == system.workspace_id,
                ControlPolicy.scope == "system",
                ControlPolicy.target_id == system.id,
            )
            .first()
        )
    return (
        db.query(ControlPolicy)
        .filter(
            ControlPolicy.workspace_id == system.workspace_id,
            ControlPolicy.scope == "system",
            ControlPolicy.target_id == system.id,
        )
        .order_by(ControlPolicy.updated_at.desc())
        .first()
    )


def _load_adaptive_policy(db: DBSession, system: System) -> Optional[AdaptivePolicy]:
    if not system.adaptive_policy_id:
        return None
    policy = (
        db.query(AdaptivePolicy)
        .filter(
            AdaptivePolicy.id == system.adaptive_policy_id,
            AdaptivePolicy.enabled.is_(True),
            AdaptivePolicy.workspace_id == system.workspace_id,
        )
        .first()
    )
    if policy is None:
        return None
    scope = str(policy.scope or "").lower()
    if scope == "system" and policy.target_id != system.id:
        return None
    if scope == "capability" and policy.target_id != system.capability_id:
        return None
    if scope == "portfolio" and policy.target_id not in {None, system.workspace_id}:
        return None
    if scope not in {"", "system", "capability", "portfolio"}:
        return None
    return policy


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


def _safe_membrane(control: Optional[ControlPolicy]) -> MembraneSpec:
    """Resolve the membrane, degrading to an empty derived spec on error.

    Read-through by default: with no explicit ``membrane_spec`` the returned
    spec mirrors ``control``'s own fields, so callers see identical values.
    """
    try:
        return resolve_membrane_spec(control=control)
    except Exception as exc:  # noqa: BLE001
        logger.warning("membrane: resolve failed, using empty spec", error=str(exc))
        return MembraneSpec()


def _membrane_skill_blocked(control: Optional[ControlPolicy], slug: str) -> tuple[bool, bool]:
    """Return ``(blocked, authoritative)`` for the membrane capability facet.

    Effective allow-list = ``spec.capabilities.allowed_skills`` which equals
    ``control.allowed_skills`` when the spec is derived — so the block is
    byte-identical to the legacy ``allowed_skills`` gate unless an authoritative
    spec tightened the list.
    """
    spec = _safe_membrane(control)
    allowed = spec.capabilities.allowed_skills
    return (bool(allowed) and slug not in allowed, spec.authoritative)


def _apply_control_postchecks(
    db: DBSession, system: System, run: Run, control: ControlPolicy
) -> None:
    """Annotate (or, opt-in, abort) the run when a hard guardrail was breached.

    Valve thresholds are read through the membrane: derived specs mirror
    ``control``'s ``max_cost_per_decision`` / ``max_latency_ms`` exactly, so
    breach detection is unchanged. The membrane *valves* facet adds an opt-in
    ``hard_abort`` upgrade — when an authoritative spec sets it, a breach fails
    the run instead of merely logging a ``policy_breach`` Decision. Default
    (``hard_abort=False``) behaviour is byte-identical to before.
    """
    valves = _safe_membrane(control).valves
    breaches: List[str] = []
    if valves.max_cost_per_decision is not None and (run.cost_internal or 0) > float(
        valves.max_cost_per_decision
    ):
        breaches.append("max_cost_per_decision")
    if valves.max_latency_ms is not None and (run.duration_ms or 0) > float(valves.max_latency_ms):
        breaches.append("max_latency_ms")
    if not breaches:
        return
    hard_abort = bool(valves.hard_abort)
    _log_decision(
        db,
        scope="system",
        target_id=system.id,
        kind="policy_breach",
        rationale={"breaches": breaches, "run_id": run.id, "hard_abort": hard_abort},
    )
    if hard_abort:
        run.status = "failed"
        run.error = run.error or f"membrane_valve_breach:{','.join(breaches)}"


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
    checkpoint = {
        "kind": "run_end",
        "t": datetime.utcnow().isoformat(),
        "status": "failed",
        "error": error,
    }
    run.checkpoints = [*(run.checkpoints or []), checkpoint]
    db.commit()
    try:
        event_bus.publish(run.id, checkpoint)
        event_bus.close(run.id)
    except Exception:  # noqa: BLE001 - persisted terminal state is authoritative.
        pass
    return {"id": run.id, "status": "failed", "error": error}
