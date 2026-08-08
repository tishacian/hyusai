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
import json
import math
import time
from collections.abc import Mapping
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional
from uuid import NAMESPACE_URL, uuid4, uuid5

from sqlalchemy.orm import Session as DBSession

from app.core.config import settings
from app.core.logging import get_logger
from app.db.base import SessionLocal
from app.models.capability import Capability
from app.models.decision import Decision
from app.models.policy import AdaptivePolicy, ControlPolicy
from app.models.run import Run, SkillInvocation
from app.models.skill import Skill
from app.models.system import System
from app.models.system_version import SystemVersion
from app.models.workspace import Workspace
from app.services.chains.version_service import (
    ConfigurationSnapshotError,
    normalize_configuration_snapshot,
)
from app.services.control_policy_snapshot import control_policy_execution_contract
from app.services.membrane.enforcement import (
    MembraneEnforcementError,
    ValveUsage,
    collect_valve_usage,
    evaluate_capability,
    evaluate_valves,
    token_measurement_from_payload,
)
from app.services.membrane.spec import MembraneSpec, resolve_membrane_spec
from app.services.outcome.derive import derive_outcome
from app.services.run_outcome_provenance import record_runtime_auto_outcome
from app.services.skill_invocation_snapshot import (
    capture_skill_execution_evidence,
    resolve_skill_invocation_cost,
)
from app.services.skills_registry import resolve as resolve_skill
from app.services.skills_registry import workspace_skill_callable
from app.services.system_catalog_bindings import (
    SystemCatalogBindingError,
    resolve_run_system_catalog_bindings,
)

from .events import bus as event_bus
from .execution_contract import (
    WORKBENCH_EXECUTION_SURFACES,
    canonical_flow_sha256,
    execution_runtime_mode,
    resolve_flow_execution,
    resolve_run_flow_execution,
)
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
    from .dag import execute_run_dag  # noqa: WPS433

    async def _entry() -> None:
        use_dag = False
        db = SessionLocal()
        try:
            run = db.query(Run).filter(Run.id == run_id).first()
            if run:
                system = (
                    db.query(System)
                    .filter(
                        System.id == run.system_id,
                        System.workspace_id == run.workspace_id,
                    )
                    .first()
                )
                workspace = (
                    db.query(Workspace)
                    .filter(Workspace.id == run.workspace_id)
                    .first()
                    if system and run.workspace_id
                    else None
                )
                use_dag = bool(
                    system
                    and resolve_run_flow_execution(run, system, workspace).uses_dag
                )
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
    from .dag import execute_run_dag  # noqa: WPS433

    async def _entry() -> Dict[str, Any]:
        use_dag = False
        scoped_error: Optional[str] = None
        db = SessionLocal()
        try:
            run = db.query(Run).filter(Run.id == child_run_id).first()
            if run is None:
                return {"id": child_run_id, "status": "missing", "error": "run_not_found"}
            if run:
                system = (
                    db.query(System)
                    .filter(
                        System.id == run.system_id,
                        System.workspace_id == run.workspace_id,
                    )
                    .first()
                )
                if system is None:
                    scoped_error = "delegated_system_scope_mismatch"
                workspace = (
                    db.query(Workspace)
                    .filter(Workspace.id == (system.workspace_id or run.workspace_id))
                    .first()
                    if system and (system.workspace_id or run.workspace_id)
                    else None
                )
                if system is not None and run.workspace_id and workspace is None:
                    scoped_error = "delegated_workspace_missing"
                use_dag = bool(
                    system
                    and resolve_run_flow_execution(run, system, workspace).uses_dag
                )
                if scoped_error:
                    run.status = "failed"
                    run.error = scoped_error
                    run.completed_at = datetime.utcnow()
                    db.commit()
        finally:
            db.close()
        if scoped_error:
            return {
                "id": child_run_id,
                "status": "failed",
                "error": scoped_error,
            }
        if use_dag:
            return await execute_run_dag(child_run_id)
        return await execute_run(child_run_id)

    return asyncio.run(_entry())


def schedule_subflow_run(child_run_id: str, *, task_id: Optional[str] = None) -> str:
    """Dispatch a delegated child run.

    Dispatch is deliberately fail-closed.  A broker error is ambiguous (the
    message may already have been accepted), therefore executing in-process
    would risk a duplicate side effect.  Callers persist the child first and
    retry this function with the same child id / delegation key.
    """
    try:
        from app.workers.tasks import subflow_run as subflow_task  # noqa: WPS433

        task_id = task_id or str(
            uuid5(NAMESPACE_URL, f"agentium:subflow-run:{child_run_id}")
        )
        remaining = _subflow_deadline_remaining(child_run_id)
        if remaining is None:
            async_result = subflow_task.apply_async(
                args=[child_run_id],
                task_id=task_id,
            )
        else:
            # The absolute deadline is persisted with the child before this
            # publication. Redeliveries therefore consume the same budget
            # instead of receiving a fresh timeout window.
            soft_limit = max(1, int(math.ceil(remaining)))
            async_result = subflow_task.apply_async(
                args=[child_run_id],
                task_id=task_id,
                soft_time_limit=soft_limit,
                time_limit=soft_limit + 5,
            )
        task_id = getattr(async_result, "id", None)
        if not task_id:
            raise RuntimeError("subflow dispatch returned no task id")
        return str(task_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "run_engine.schedule_subflow_run: celery dispatch is ambiguous",
            child_run_id=child_run_id,
            error=str(exc),
        )
        raise RuntimeError(f"ambiguous subflow dispatch for {child_run_id}") from exc


def _subflow_deadline_remaining(child_run_id: str) -> Optional[float]:
    """Return seconds left on the child's persisted delegation deadline."""

    with SessionLocal() as db:
        child = db.query(Run).filter(Run.id == child_run_id).first()
        delegation = (
            ((child.input_ref or {}).get("_delegation") or {})
            if child is not None and isinstance(child.input_ref, dict)
            else {}
        )
        raw_deadline = delegation.get("deadline_at") if isinstance(delegation, dict) else None
    if not raw_deadline:
        return None
    try:
        deadline = datetime.fromisoformat(str(raw_deadline).replace("Z", "+00:00"))
        now = datetime.now(deadline.tzinfo) if deadline.tzinfo else datetime.utcnow()
        return max(0.0, (deadline - now).total_seconds())
    except (TypeError, ValueError):
        # A malformed persisted deadline must fail in the worker rather than
        # silently granting an unlimited execution window.
        return 0.0


def schedule_subflow_parent_resume(
    parent_run_id: str,
    *,
    source_id: str,
    task_id: Optional[str] = None,
) -> str:
    """Publish an idempotent, durable parent-resume task."""

    try:
        from app.workers.tasks import subflow_parent_resume  # noqa: WPS433

        task_id = task_id or str(
            uuid5(NAMESPACE_URL, f"agentium:subflow-parent:{parent_run_id}:{source_id}")
        )
        result = subflow_parent_resume.apply_async(args=[parent_run_id], task_id=task_id)
        if not getattr(result, "id", None):
            raise RuntimeError("parent resume dispatch returned no task id")
        return str(result.id)
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "run_engine.schedule_subflow_parent_resume: celery dispatch is ambiguous",
            parent_run_id=parent_run_id,
            source_id=source_id,
            error=str(exc),
        )
        raise RuntimeError(f"ambiguous parent resume dispatch for {parent_run_id}") from exc


def schedule_subflow_hitl_resume(
    child_run_id: str,
    *,
    decision_id: str,
    task_id: Optional[str] = None,
) -> str:
    """Publish a delegated child HITL continuation using identifiers only."""

    try:
        from app.workers.tasks import subflow_hitl_resume  # noqa: WPS433

        task_id = task_id or str(
            uuid5(NAMESPACE_URL, f"agentium:subflow-hitl:{child_run_id}:{decision_id}")
        )
        result = subflow_hitl_resume.apply_async(
            args=[child_run_id, decision_id],
            task_id=task_id,
        )
        if not getattr(result, "id", None):
            raise RuntimeError("subflow HITL dispatch returned no task id")
        return str(result.id)
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "run_engine.schedule_subflow_hitl_resume: celery dispatch is ambiguous",
            child_run_id=child_run_id,
            decision_id=decision_id,
            error=str(exc),
        )
        raise RuntimeError(f"ambiguous subflow HITL dispatch for {child_run_id}") from exc


def schedule_run_hitl_resume(
    run_id: str,
    *,
    decision_id: str,
    task_id: Optional[str] = None,
) -> str:
    """Durably publish an ordinary HITL continuation.

    The deterministic task id makes an HTTP retry safe after an ambiguous
    broker acknowledgement. The worker's PostgreSQL lease, not the task id,
    is the execution mutex because brokers may carry duplicate messages with
    the same identifier.
    """

    try:
        from app.workers.tasks import run_hitl_resume  # noqa: WPS433

        task_id = task_id or str(
            uuid5(NAMESPACE_URL, f"agentium:run-hitl:{run_id}:{decision_id}")
        )
        result = run_hitl_resume.apply_async(
            args=[run_id, decision_id],
            task_id=task_id,
        )
        if not getattr(result, "id", None):
            raise RuntimeError("Run HITL dispatch returned no task id")
        return str(result.id)
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "run_engine.schedule_run_hitl_resume: celery dispatch is ambiguous",
            run_id=run_id,
            decision_id=decision_id,
            error=str(exc),
        )
        raise RuntimeError(f"ambiguous Run HITL dispatch for {run_id}") from exc


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

        system = (
            db.query(System)
            .filter(
                System.id == run.system_id,
                System.workspace_id == run.workspace_id,
            )
            .first()
        )
        if not system:
            return _fail(db, run, "system_not_found")

        workspace = (
            db.query(Workspace).filter(Workspace.id == run.workspace_id).first()
            if run.workspace_id
            else None
        )
        if run.workspace_id and workspace is None:
            return _fail(db, run, "system_catalog_binding_invalid:workspace_not_found")
        debug_config = (
            run.input_ref.get("_debug")
            if isinstance(run.input_ref, dict)
            else None
        )
        if (
            debug_config is not None
            and not resolve_run_flow_execution(run, system, workspace).debug_supported
        ):
            return _fail(db, run, "debug_runtime_unsupported:sequential_legacy")
        try:
            catalog_bindings = resolve_run_system_catalog_bindings(
                db,
                workspace=workspace,
                system=system,
                run=run,
            )
        except SystemCatalogBindingError as exc:
            return _fail(db, run, f"system_catalog_binding_invalid:{exc.code}")
        if run.capability_id is None:
            run.capability_id = system.capability_id
        capability = catalog_bindings.capability
        control = _load_control_policy(db, system)
        adaptive = (
            catalog_bindings.adaptive_policy
            if catalog_bindings.adaptive_policy is not None
            and catalog_bindings.adaptive_policy.enabled
            else None
        )

        run_gate = _evaluate_run_capability(control, system)
        if not run_gate.allowed:
            _record_capability_block(
                db,
                run,
                system_id=system.id,
                violations=list(run_gate.violations),
            )
            return _fail(db, run, "membrane_capability_block:system.engine.run")
        if run_gate.would_block and run_gate.mode == "shadow":
            _record_capability_shadow(
                db,
                run,
                system_id=system.id,
                violations=list(run_gate.violations),
                action="system.engine.run",
            )

        skill_slugs = [skill.slug for skill in catalog_bindings.skills]
        if not skill_slugs:
            return _fail(db, run, "no_skills_bound")

        logger.info(
            "run_engine: start",
            run_id=run.id,
            system_id=system.id,
            capability=capability.slug if capability else None,
            skills=skill_slugs,
        )
        first_start = run.status == "pending"
        run.status = "running"
        run.started_at = run.started_at or datetime.utcnow()
        _snapshot_run_flow(
            db,
            run,
            system,
            first_start=first_start,
            control=control,
        )
        db.commit()

        ctx = _build_initial_ctx(db, run, system, capability)
        _attach_authoritative_membrane(ctx, control)

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

            if _runtime_valves_blocked(db, run, control):
                return _fail(db, run, run.error or "membrane_valve_breach")

            if (
                adaptive
                and adaptive.enabled
                and _should_stop_adaptive(adaptive, invocation, total_cost)
            ):
                _log_decision(
                    db,
                    workspace_id=run.workspace_id,
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
    execution_profile = (
        system.execution_profile if isinstance(system.execution_profile, dict) else {}
    )
    try:
        max_runtime_s = float(execution_profile.get("max_runtime_s") or 40.0)
    except (TypeError, ValueError):
        max_runtime_s = 40.0
    max_runtime_s = max(1.0, min(44.0, max_runtime_s))
    run_deadline_monotonic = time.monotonic() + max_runtime_s
    workspace_slug = db.query(Workspace.slug).filter(Workspace.id == run.workspace_id).scalar()
    return {
        "system_id": system.id,
        "capability_id": capability.id if capability else None,
        "workspace_id": run.workspace_id,
        # Lets a skill tie what it writes back to the run that caused it —
        # the audit wrapper files it as the row's trace_id.
        "run_id": run.id,
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
        # In-process optional stages can reserve enough time for the terminal
        # DAG nodes instead of being cancelled by the outer Agentic membrane.
        # A monotonic value is deliberately ephemeral and never persisted.
        "_run_deadline_monotonic": run_deadline_monotonic,
    }


_VERSION_BINDING_FIELDS = (
    "control_policy_id",
    "adaptive_policy_id",
    "context_id",
)


def _flow_snapshots_equal(left: Any, right: Any) -> bool:
    """Return exact structural equality for persisted JSON flow snapshots."""

    try:
        return json.dumps(
            left,
            sort_keys=True,
            separators=(",", ":"),
        ) == json.dumps(
            right,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError):
        return False


def _version_configuration_matches_system(
    version: SystemVersion,
    system: System,
) -> bool:
    """Fail closed when a version claims bindings unlike those executed.

    Flow-only versions remain valid historical evidence.  When configuration
    evidence is present, however, every allowlisted binding it declares must
    match the System resolved by the engine at this start/resume boundary.
    """

    if version.configuration_snapshot is None:
        return True
    try:
        snapshot = normalize_configuration_snapshot(version.configuration_snapshot)
    except ConfigurationSnapshotError:
        return False
    bindings = snapshot["bindings"]
    return all(
        bindings[field] == getattr(system, field)
        for field in _VERSION_BINDING_FIELDS
        if field in bindings
    )


def _parse_snapshot_boundary(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(UTC).replace(tzinfo=None)
    return parsed


def validated_existing_run_flow_version_id(
    db: DBSession,
    run: Run,
    system: System,
    *,
    workspace_id: str | None,
) -> str | None:
    """Validate an already-bound Run version without consulting mutable bindings.

    This is used both for engine retry/HITL boundaries and by the terminal chat
    replay producer, which does not enter either walker.  It never searches for
    a replacement version: a missing or invalid historical reference remains
    unbound.
    """

    if not run.flow_version_id or run.flow_snapshot is None:
        return None
    execution = (
        run.input_ref.get("execution")
        if isinstance(run.input_ref, dict)
        and isinstance(run.input_ref.get("execution"), Mapping)
        else {}
    )
    snapshot_at = _parse_snapshot_boundary(execution.get("snapshot_at"))
    if snapshot_at is None:
        snapshot_at = run.started_at
    if snapshot_at is None:
        return None
    version = (
        db.query(SystemVersion)
        .filter(
            SystemVersion.id == run.flow_version_id,
            SystemVersion.system_id == system.id,
            SystemVersion.workspace_id == workspace_id,
            SystemVersion.created_at <= snapshot_at,
        )
        .one_or_none()
    )
    if version is None or not _flow_snapshots_equal(
        version.flow_definition,
        run.flow_snapshot,
    ):
        return None
    return version.id


def _bind_run_flow_version(
    db: DBSession,
    run: Run,
    system: System,
    *,
    workspace_id: str | None,
    snapshot_at: datetime | None,
    initial_binding: bool,
) -> None:
    """Link a Run only to an exact, already-existing execution version.

    The Run snapshot remains the primary immutable execution contract.  This
    optional reference is attached only when a version for the same System and
    workspace already existed at the server-owned snapshot boundary, contains
    the exact same flow, and does not claim incompatible configuration
    bindings.  A retry or HITL resume revalidates the same conditions; it never
    creates a version or substitutes an approximate match.
    """

    if snapshot_at is None or run.flow_snapshot is None:
        run.flow_version_id = None
        return

    candidates = (
        db.query(SystemVersion)
        .filter(
            SystemVersion.system_id == system.id,
            SystemVersion.workspace_id == workspace_id,
            SystemVersion.created_at <= snapshot_at,
        )
        .order_by(
            SystemVersion.version_number.desc(),
            SystemVersion.created_at.desc(),
        )
        .all()
    )
    exact_versions = [
        version
        for version in candidates
        if _flow_snapshots_equal(version.flow_definition, run.flow_snapshot)
    ]

    if run.flow_version_id:
        # Revalidating the existing id prevents a forged/cross-tenant/future
        # reference from being silently replaced by a different historical
        # row.  Mutable current bindings are deliberately irrelevant here:
        # they cannot rewrite evidence fixed at the first execution boundary.
        run.flow_version_id = validated_existing_run_flow_version_id(
            db,
            run,
            system,
            workspace_id=workspace_id,
        )
        return

    if not initial_binding or not exact_versions:
        run.flow_version_id = None
        return

    # Configuration is part of the latest exact execution contract.  If that
    # row is incompatible we must not fall back to an older flow-only row and
    # make the Run appear better evidenced than it really is.
    latest_exact = exact_versions[0]
    run.flow_version_id = (
        latest_exact.id
        if _version_configuration_matches_system(latest_exact, system)
        else None
    )


def _snapshot_run_flow(
    db: DBSession,
    run: Run,
    system: System,
    *,
    first_start: bool | None = None,
    control: ControlPolicy | None = None,
) -> None:
    """Freeze the exact executable graph and its identity on first start."""

    if run.system_id != system.id:
        raise RuntimeError("run_system_identity_mismatch")
    if first_start is None:
        first_start = run.status == "pending"
    flow = system.flow_definition if isinstance(system.flow_definition, dict) else {}
    flow_was_frozen = isinstance(run.flow_snapshot, dict)
    if run.flow_snapshot is None:
        run.flow_snapshot = deepcopy(flow)
    input_ref = deepcopy(run.input_ref) if isinstance(run.input_ref, dict) else {}
    if system.workspace_id and run.workspace_id and system.workspace_id != run.workspace_id:
        raise RuntimeError("run_system_workspace_mismatch")
    canonical_workspace_id = system.workspace_id or run.workspace_id
    run.workspace_id = canonical_workspace_id
    workspace = None
    workspace_slug = None
    if canonical_workspace_id:
        workspace = (
            db.query(Workspace).filter(Workspace.id == canonical_workspace_id).one_or_none()
        )
        if workspace is None:
            raise RuntimeError("run_workspace_not_found")
        workspace_slug = workspace.slug
    # Canonical tenant and actor fields always win over caller-supplied input.
    input_ref["workspace_id"] = canonical_workspace_id
    if workspace_slug:
        input_ref["workspace_slug"] = workspace_slug
    else:
        input_ref.pop("workspace_slug", None)
    input_ref["user_id"] = run.initiated_by_user_id
    if first_start:
        system_settings = system.settings if isinstance(system.settings, dict) else {}
        input_ref["retrieval_contract"] = deepcopy(
            system_settings.get("retrieval_contract") or {}
        )
    execution = dict(input_ref.get("execution") or {})
    if first_start:
        snapshot_at = datetime.now(UTC).replace(tzinfo=None)
        execution["snapshot_at"] = snapshot_at.isoformat(timespec="microseconds") + "Z"
        execution["runtime_revision"] = str(
            settings.agentium_image_revision or "development"
        ).strip().lower()
        # This field is server-owned.  A caller cannot manufacture causal
        # evidence by sending a policy digest in Run.input_ref before start.
        execution["control_policy"] = (
            control_policy_execution_contract(control)
            if control is not None
            else {"schema_version": 1, "state": "not_configured"}
        )
    else:
        snapshot_at = _parse_snapshot_boundary(execution.get("snapshot_at"))
        # Runs started before the server-owned boundary was introduced retain
        # their existing history without manufacturing a new execution time.
        if snapshot_at is None and run.flow_version_id:
            snapshot_at = run.started_at
    pinned_runtime_mode = (
        execution_runtime_mode(input_ref) if flow_was_frozen else None
    )
    execution_resolution = resolve_flow_execution(
        run.flow_snapshot,
        workspace,
        pinned_runtime_mode=pinned_runtime_mode,
    )
    execution["flow_sha256"] = canonical_flow_sha256(run.flow_snapshot)
    execution["runtime_mode"] = execution_resolution.runtime_mode
    execution.setdefault("runtime_mode_reason", execution_resolution.reason)
    system_settings = system.settings if isinstance(system.settings, dict) else {}
    if system_settings.get("flow_revision") is not None:
        execution.setdefault("flow_revision", system_settings.get("flow_revision"))
    execution.setdefault("system_id", system.id)
    input_ref["execution"] = execution
    run.input_ref = input_ref
    if run.execution_surface in WORKBENCH_EXECUTION_SURFACES:
        # A Builder workbench Run is durable execution evidence for an
        # ephemeral graph, never evidence that this graph was versioned or
        # published. Keep the linkage empty even if identical JSON happens to
        # exist in historical SystemVersion rows.
        run.flow_version_id = None
    else:
        _bind_run_flow_version(
            db,
            run,
            system,
            workspace_id=canonical_workspace_id,
            snapshot_at=snapshot_at,
            initial_binding=bool(first_start),
        )


def _frozen_node_executor(run: Run, node_id: Optional[str]) -> Optional[Dict[str, Any]]:
    """The authored runtime this node's contract pinned, if it pinned one.

    Absent for seeded Skills, and absent from contracts compiled before authored
    runtimes were frozen; both keep resolving the live row, which is what they
    have always done.
    """

    if not node_id:
        return None
    contract = run.execution_contract if isinstance(run.execution_contract, dict) else None
    nodes = contract.get("nodes") if contract is not None else None
    node = nodes.get(node_id) if isinstance(nodes, dict) else None
    executor = node.get("executor") if isinstance(node, dict) else None
    return executor if isinstance(executor, dict) else None


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
    attempt_kind: Optional[str] = None,
    attempt_index: Optional[int] = None,
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
    # block); an authoritative spec may tighten it. Malformed v1/derived data
    # remains compatible, while an explicit v2+ contract fails closed before
    # any invocation ledger row or Skill side effect is created.
    model = _effective_invocation_model(
        ctx,
        resolved_input if resolved_input is not None else last_output,
    )
    membrane_spec = _safe_membrane(control)
    capability_gate = evaluate_capability(membrane_spec, skill=slug, model=model)
    legacy_shadow_block = bool(
        membrane_spec.shadow_active
        and control is not None
        and control.allowed_skills
        and slug not in control.allowed_skills
    )
    if not capability_gate.allowed or legacy_shadow_block:
        if membrane_spec.enforcement_active:
            _record_capability_block(
                db,
                run,
                system_id=ctx.get("system_id"),
                violations=list(capability_gate.violations),
                skill=slug,
                model=model,
            )
            marker_error = f"membrane_capability_block:{','.join(capability_gate.violations)}"
        else:
            # v1/derived (and the baseline under v2 shadow) preserve the exact
            # legacy decision/error contract.
            _log_decision(
                db,
                workspace_id=run.workspace_id,
                scope="system",
                target_id=ctx.get("system_id"),
                kind="policy_block",
                rationale={
                    "run_id": run.id,
                    "skill": slug,
                    "reason": "not_in_allowed_skills",
                    "membrane": membrane_spec.authoritative,
                },
            )
            marker_error = f"policy_blocked_skill:{slug}"
        marker = {
            "kind": "policy_block",
            "t": datetime.utcnow().isoformat(),
            "node_id": node_id,
            "skill_slug": slug,
            "error": marker_error,
        }
        run.error = run.error or marker["error"]
        run.checkpoints = [*(run.checkpoints or []), marker]
        db.commit()
        try:
            event_bus.publish(run.id, marker)
        except Exception:  # noqa: BLE001 - persisted marker is authoritative.
            pass
        return None
    if capability_gate.would_block and capability_gate.mode == "shadow":
        _record_capability_shadow(
            db,
            run,
            system_id=ctx.get("system_id"),
            violations=list(capability_gate.violations),
            skill=slug,
            model=model,
        )

    skill_input = (
        dict(resolved_input)
        if resolved_input is not None
        else _build_skill_input(slug, run.input_ref or {}, last_output, ctx)
    )
    execution_evidence = capture_skill_execution_evidence(
        db,
        workspace_id=run.workspace_id,
        skill_slug=slug,
    )
    cost_evidence = resolve_skill_invocation_cost(
        db,
        workspace_id=run.workspace_id,
        skill_id=execution_evidence.skill_id,
        skill_slug=execution_evidence.skill_slug,
    )
    invocation = SkillInvocation(
        id=str(uuid4()),
        run_id=run.id,
        skill_id=execution_evidence.skill_id,
        skill_slug=execution_evidence.skill_slug,
        execution_snapshot=execution_evidence.execution_snapshot,
        status="running",
        started_at=datetime.utcnow(),
        cost_measured=False,
        metrics={"cost_evidence": cost_evidence.evidence},
        input_ref=skill_input,
        trace={
            **({"node_id": node_id} if node_id else {}),
            **({"membrane_attempt_kind": attempt_kind} if attempt_kind else {}),
            **({"membrane_attempt_index": attempt_index} if attempt_index is not None else {}),
            "effective_model": model,
        },
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
        # A workspace-defined Skill carries its runtime on its own row, so the
        # namespace in the slug decides which resolver answers. Seeded slugs
        # short-circuit on the string alone and pay no extra query.
        authored = workspace_skill_callable(
            db,
            workspace_id=run.workspace_id,
            slug=slug,
            frozen_executor=_frozen_node_executor(run, node_id),
        )
        fn = resolve_skill(slug) if authored is None else authored
        output = await fn(invocation.input_ref, skill_ctx)
        # A Skill output is arbitrary JSON.  Falsy values (``False``, ``0``
        # and ``""``) are valid contract outputs and must not be rewritten to
        # an empty object before the DAG validates or publishes them.
        invocation.output_ref = output if output is not None else {}
        invocation.status = "completed"
    except asyncio.CancelledError:
        invocation.status = "cancelled"
        invocation.error = "execution_cancelled"
        invocation.latency_ms = (time.monotonic() - t0) * 1000
        invocation.completed_at = datetime.utcnow()
        invocation.cost = cost_evidence.cost
        invocation.cost_measured = cost_evidence.cost_measured
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
    invocation.cost = cost_evidence.cost
    invocation.cost_measured = cost_evidence.cost_measured
    metrics = dict(invocation.metrics or {})
    output_tokens, output_tokens_reported = token_measurement_from_payload(
        invocation.output_ref or {}
    )
    metric_tokens, metric_tokens_reported = token_measurement_from_payload(metrics)
    if output_tokens_reported or metric_tokens_reported:
        metrics["total_tokens"] = max(
            output_tokens,
            metric_tokens,
        )
        output_usage = (
            invocation.output_ref.get("usage")
            if isinstance(invocation.output_ref, dict)
            and isinstance(invocation.output_ref.get("usage"), Mapping)
            else {}
        )
        metrics["token_evidence"] = {
            "measurement_coverage": "complete",
            "measurement_source": output_usage.get("measurement_source")
            or "reported_payload",
            "provider_calls": output_usage.get("provider_calls"),
        }
    elif isinstance(invocation.output_ref, dict) and isinstance(
        invocation.output_ref.get("provider_usage"), Mapping
    ):
        # Preserve reported partial totals for diagnosis, but deliberately do
        # not mirror them to ``total_tokens``.  Membrane's existing parser then
        # keeps this invocation unavailable instead of treating a partial LLM
        # trace as a complete measurement.
        provider_evidence = dict(invocation.output_ref["provider_usage"])
        metrics["token_evidence"] = {
            "measurement_coverage": provider_evidence.get("measurement_coverage")
            or "unavailable",
            "provider_calls": provider_evidence.get("provider_calls"),
            "reported_calls": provider_evidence.get("reported_calls"),
            "unreported_calls": provider_evidence.get("unreported_calls"),
            "reported_total": provider_evidence.get("reported_total"),
            "providers": provider_evidence.get("providers") or [],
        }
    invocation.metrics = metrics
    trace = dict(invocation.trace or {})
    if "self_correct" in slug or (
        isinstance(invocation.output_ref, dict)
        and invocation.output_ref.get("action_taken")
    ):
        trace["membrane_autocorrections"] = max(
            1,
            int(trace.get("membrane_autocorrections") or 0),
        )
    invocation.trace = trace
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
    last_output: Any,
) -> Dict[str, Any]:
    """Derive the canonical Outcome block, apply post-checks, persist."""
    # A race/any join (or parent cancellation) may cancel this child from a
    # different worker while its final node is still unwinding. Refresh before
    # publish so a late completion can never overwrite the authoritative
    # cancellation persisted by the coordinator.
    locked = (
        db.query(Run)
        .filter(Run.id == run.id)
        .populate_existing()
        .with_for_update()
        .first()
    )
    if locked is not None:
        run = locked
    if run.status in {"cancelled", "failed"}:
        return {
            "id": run.id,
            "status": run.status,
            "outcome": {
                "decision": run.decision,
                "confidence": run.confidence,
                "value_estimated": run.value_estimated,
                "cost_internal": run.cost_internal,
                "efficiency": run.efficiency,
            },
        }
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
    # Preserve the exact JSON value accepted by the frozen execution
    # contract.  The caller supplies ``{}`` when there is genuinely no
    # terminal value, so truthiness is never a valid absence test here.
    run.output_ref = last_output
    if control:
        postcheck_blocked = _apply_control_postchecks(db, system, run, control)
        if postcheck_blocked and _safe_membrane(control).enforcement_active:
            # A v2 enforce valve is a publication boundary, not merely a
            # failed status annotation.  Legacy/v1 keeps its historical output.
            run.output_ref = {}
    if run.status == "completed" and run.value_source == "auto" and control is not None:
        record_runtime_auto_outcome(run, db=db)
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
    """Resolve the membrane without ever failing open for an explicit v2 spec.

    Read-through by default: with no explicit ``membrane_spec`` the returned
    spec mirrors ``control``'s own fields, so callers see identical values.
    A malformed legacy/derived contract remains on the compatibility path.  An
    explicit v2+ mapping is an enforcement boundary, however: silently
    replacing it with an empty spec would turn a typo into allow-all.  Surface
    a typed error before the run-level capability gate can create any
    :class:`SkillInvocation`.
    """
    try:
        return resolve_membrane_spec(control=control)
    except Exception as exc:  # noqa: BLE001
        extra = getattr(control, "extra", None)
        raw = extra.get("membrane_spec") if isinstance(extra, Mapping) else None
        raw_version = raw.get("version") if isinstance(raw, Mapping) else None
        try:
            is_v2_or_later = int(raw_version) >= 2
        except (TypeError, ValueError):
            is_v2_or_later = False
        if is_v2_or_later:
            raise MembraneEnforcementError(
                f"membrane_spec_invalid:{str(exc)[:240]}"
            ) from exc
        logger.warning(
            "membrane: compat resolve failed, using empty spec",
            error=str(exc),
        )
        return MembraneSpec()


def _attach_authoritative_membrane(
    ctx: Dict[str, Any], control: Optional[ControlPolicy]
) -> None:
    """Expose the server-owned v2 contract to RAG, never caller policy.

    This is deliberately limited to explicit ControlPolicy specs.  Existing
    source policies keep their byte-identical v1/derived path.
    """

    spec = _safe_membrane(control)
    if not spec.authoritative:
        return
    source_policy = (
        dict(ctx.get("source_policy"))
        if isinstance(ctx.get("source_policy"), dict)
        else {}
    )
    source_policy["membrane_spec"] = spec.to_dict()
    ctx["source_policy"] = source_policy


def _effective_invocation_model(ctx: Dict[str, Any], payload: Any) -> Optional[str]:
    payload = payload if isinstance(payload, dict) else {}
    value = payload.get("model") or payload.get("model_name") or ctx.get("default_model")
    return str(value).strip() if value else None


def _evaluate_run_capability(control: Optional[ControlPolicy], system: System):
    return evaluate_capability(
        _safe_membrane(control),
        model=getattr(system, "default_model", None),
        action="system.engine.run",
    )


def _record_capability_block(
    db: DBSession,
    run: Run,
    *,
    system_id: Optional[str],
    violations: List[str],
    skill: Optional[str] = None,
    model: Optional[str] = None,
) -> None:
    _log_decision(
        db,
        workspace_id=run.workspace_id,
        scope="system",
        target_id=system_id,
        kind="policy_block",
        rationale={
            "run_id": run.id,
            "skill": skill,
            "model": model,
            "action": "system.engine.run" if skill is None else None,
            "violations": violations,
            "membrane": True,
        },
    )


def _record_capability_shadow(
    db: DBSession,
    run: Run,
    *,
    system_id: Optional[str],
    violations: List[str],
    skill: Optional[str] = None,
    model: Optional[str] = None,
    action: Optional[str] = None,
) -> None:
    _log_decision(
        db,
        workspace_id=run.workspace_id,
        scope="system",
        target_id=system_id,
        kind="policy_shadow",
        rationale={
            "run_id": run.id,
            "skill": skill,
            "model": model,
            "action": action,
            "violations": violations,
            "mode": "shadow",
        },
    )


def _runtime_valves_blocked(
    db: DBSession,
    run: Run,
    control: Optional[ControlPolicy],
) -> bool:
    """Stop an enforce-v2 run as soon as a persisted valve is breached."""

    spec = _safe_membrane(control)
    if not spec.enforcement_active:
        return False
    invocations, measurement_gaps = _valve_invocation_ledger(db, run)
    measured_latencies = [
        float(item.latency_ms)
        for item in invocations
        if item.latency_ms is not None
    ]
    duration_ms = (
        sum(measured_latencies)
        if len(measured_latencies) == len(invocations) and measurement_gaps == 0
        else None
    )
    usage = collect_valve_usage(
        invocations,
        duration_ms=duration_ms,
        measurement_gaps=measurement_gaps,
    )
    decision = evaluate_valves(spec, usage)
    if decision.allowed:
        return False
    error = f"membrane_valve_breach:{','.join(decision.breaches)}"
    if not any(
        cp.get("kind") == "membrane_valve_breach"
        for cp in (run.checkpoints or [])
        if isinstance(cp, dict)
    ):
        _log_decision(
            db,
            workspace_id=run.workspace_id,
            scope="system",
            target_id=run.system_id,
            kind="policy_breach",
            rationale={
                "run_id": run.id,
                "breaches": list(decision.breaches),
                "mode": decision.mode,
                "usage": _valve_usage_payload(usage),
            },
        )
        run.checkpoints = [
            *(run.checkpoints or []),
            {
                "kind": "membrane_valve_breach",
                "t": datetime.utcnow().isoformat(),
                "breaches": list(decision.breaches),
            },
        ]
    run.error = error
    db.commit()
    return True


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
) -> bool:
    """Annotate (or, opt-in, abort) the run when a hard guardrail was breached.

    Valve thresholds are read through the membrane: derived specs mirror
    ``control``'s ``max_cost_per_decision`` / ``max_latency_ms`` exactly, so
    breach detection is unchanged. The membrane *valves* facet adds an opt-in
    ``hard_abort`` upgrade — when an authoritative spec sets it, a breach fails
    the run instead of merely logging a ``policy_breach`` Decision. Default
    (``hard_abort=False``) behaviour is byte-identical to before.
    """
    spec = _safe_membrane(control)
    invocations, measurement_gaps = _valve_invocation_ledger(db, run)
    usage = collect_valve_usage(
        invocations,
        duration_ms=float(run.duration_ms) if run.duration_ms is not None else None,
        measurement_gaps=measurement_gaps,
    )
    decision = evaluate_valves(spec, usage)
    if not decision.would_block:
        return False
    hard_abort = not decision.allowed
    _log_decision(
        db,
        workspace_id=system.workspace_id,
        scope="system",
        target_id=system.id,
        kind="policy_breach",
        rationale={
            "breaches": list(decision.breaches),
            "run_id": run.id,
            "hard_abort": hard_abort,
            "mode": decision.mode,
            "usage": _valve_usage_payload(usage),
        },
    )
    if hard_abort:
        run.status = "failed"
        run.error = run.error or f"membrane_valve_breach:{','.join(decision.breaches)}"
    return hard_abort


def _valve_invocation_ledger(
    db: DBSession,
    run: Run,
) -> tuple[list[SkillInvocation], int]:
    """Load a Run's valve ledger, including durable subflow descendants.

    A child with no invocation ledger is an explicit measurement gap.  It is
    never silently represented as a zero-cost/zero-token delegation.
    """

    run_ids = [str(run.id)]
    descendants: list[str] = []
    frontier = [str(run.id)]
    seen = {str(run.id)}
    while frontier:
        batch = frontier[:500]
        frontier = frontier[500:]
        child_ids = [
            str(row[0])
            for row in (
                db.query(Run.id)
                .filter(
                    Run.parent_run_id.in_(batch),
                    Run.trigger == "subflow",
                    Run.workspace_id == run.workspace_id,
                )
                .all()
            )
            if str(row[0]) not in seen
        ]
        seen.update(child_ids)
        descendants.extend(child_ids)
        run_ids.extend(child_ids)
        frontier.extend(child_ids)

    invocations: list[SkillInvocation] = []
    for offset in range(0, len(run_ids), 500):
        invocations.extend(
            db.query(SkillInvocation)
            .filter(SkillInvocation.run_id.in_(run_ids[offset : offset + 500]))
            .order_by(SkillInvocation.started_at.asc())
            .all()
        )
    invocation_run_ids = {str(item.run_id) for item in invocations}
    measurement_gaps = sum(
        1 for child_run_id in descendants if child_run_id not in invocation_run_ids
    )
    return invocations, measurement_gaps


def _valve_usage_payload(usage: ValveUsage) -> dict[str, Any]:
    return {
        "cost": usage.cost,
        "legacy_unverified_cost": usage.legacy_unverified_cost,
        "latency_ms": usage.latency_ms,
        "tokens": usage.tokens,
        "coverage": {
            "cost": usage.cost_coverage.value,
            "tokens": usage.token_coverage.value,
            "latency": usage.latency_coverage.value,
            "invocations": usage.invocation_count,
            "measurement_gaps": usage.measurement_gap_count,
            "cost_measurements": usage.cost_measurement_count,
            "token_measurements": usage.token_measurement_count,
            "latency_measurements": usage.latency_measurement_count,
        },
        "failures": usage.failures,
        "retries": usage.retries,
        "loops": usage.loops,
        "autocorrections": usage.autocorrections,
        "attempts": usage.attempts,
    }


def _log_decision(
    db: DBSession,
    *,
    workspace_id: Optional[str],
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
            workspace_id=workspace_id,
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
    locked = (
        db.query(Run)
        .filter(Run.id == run.id)
        .populate_existing()
        .with_for_update()
        .first()
    )
    if locked is not None:
        run = locked
    if run.status in {"completed", "cancelled"}:
        return {"id": run.id, "status": run.status, "error": run.error}
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
