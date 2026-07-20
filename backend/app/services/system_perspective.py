"""System 360 read model: four honest projections over one canonical System.

The service deliberately aggregates only workspace-scoped, persisted rows. It
never substitutes process-wide metrics and never turns an absent measurement
into zero.  The UI can therefore switch lenses without changing object
identity while retaining explicit ``not_measured``/``not_configured`` states.
"""
from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta
from typing import Any, Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session as DBSession

from app.core.iam.dependencies import current_membership, evaluate_permission
from app.core.iam.roles import is_admin_template
from app.models.audit import AuditLog
from app.models.capability import Capability
from app.models.context import Context
from app.models.decision import Decision
from app.models.evaluation import EvaluationScore
from app.models.policy import AdaptivePolicy, ControlPolicy
from app.models.run import Run, SkillInvocation
from app.models.skill import Skill
from app.models.system import System
from app.models.system_version import SystemVersion
from app.models.task import Task
from app.models.user import User
from app.models.workspace import Workspace
from app.models.workspace_job import WorkspaceJob
from app.services.iam.config_service import is_iam_enforced_for_workspace
from app.services.membrane.enforcement import evaluate_capability
from app.services.membrane.spec import MembraneSpec, resolve_membrane_spec

OBJECT_LENSES = ("build", "operate", "steer", "govern")
FACETS = ("overview", "runs", "design", "context")
FACT_STATES = {
    "available",
    "not_measured",
    "not_configured",
    "restricted",
    "unavailable",
}
WINDOW_DAYS = {"7d": 7, "30d": 30, "90d": 90}


def build_system_perspective(
    db: DBSession,
    *,
    workspace: Workspace,
    user: User,
    system: System,
    lens: str,
    window: str = "30d",
) -> dict[str, Any]:
    if lens not in OBJECT_LENSES:
        raise ValueError("lens must be build, operate, steer or govern")
    if window not in WINDOW_DAYS:
        raise ValueError("window must be 7d, 30d or 90d")

    since = datetime.utcnow() - timedelta(days=WINDOW_DAYS[window])
    capability = _capability(db, workspace.id, system.capability_id)
    runs = (
        db.query(Run)
        .filter(
            Run.workspace_id == workspace.id,
            Run.system_id == system.id,
            Run.started_at >= since,
        )
        .order_by(Run.started_at.desc())
        .all()
    )
    run_ids = [run.id for run in runs]
    invocations = (
        db.query(SkillInvocation)
        .filter(SkillInvocation.run_id.in_(run_ids))
        .all()
        if run_ids
        else []
    )
    evaluations = (
        db.query(EvaluationScore)
        .filter(
            EvaluationScore.workspace_id == workspace.id,
            or_(
                EvaluationScore.run_id.in_(run_ids) if run_ids else False,
                EvaluationScore.agent_id == system.id,
            ),
            EvaluationScore.created_at >= since,
        )
        .order_by(EvaluationScore.created_at.desc())
        .all()
    )
    # Showcase fixture rows are useful for demos but are not observations.
    # Only explicit seed labels are excluded; business data is never guessed
    # from a name, slug or value.
    synthetic_run_ids = {
        run.id
        for run in runs
        if _is_showcase_seed_payload(run.input_ref)
        or _is_showcase_seed_payload(run.output_ref)
    }
    synthetic_run_ids.update(
        item.run_id
        for item in invocations
        if _is_showcase_seed_payload(item.metrics)
        or _is_showcase_seed_payload(item.trace)
        or _is_showcase_seed_payload(item.output_ref)
    )
    synthetic_run_ids.update(
        item.run_id
        for item in evaluations
        if item.run_id and _is_showcase_seed_payload(item.metadata_)
    )
    if synthetic_run_ids:
        runs = [run for run in runs if run.id not in synthetic_run_ids]
        run_ids = [run.id for run in runs]
        invocations = [item for item in invocations if item.run_id not in synthetic_run_ids]
        evaluations = [
            item
            for item in evaluations
            if item.run_id not in synthetic_run_ids
            and not _is_showcase_seed_payload(item.metadata_)
        ]
    contexts = _contexts(db, workspace.id, system)
    skills = _skills(db, workspace.id, list(system.skill_ids or []))
    control = _control_policy(db, workspace.id, system)
    adaptive = _adaptive_policy(db, workspace.id, system)
    membrane = resolve_membrane_spec(control=control)
    decisions = _decisions(db, workspace.id, system.id, run_ids, since)
    versions = (
        db.query(SystemVersion)
        .filter(
            SystemVersion.workspace_id == workspace.id,
            SystemVersion.system_id == system.id,
        )
        .order_by(SystemVersion.version_number.desc())
        .limit(20)
        .all()
    )
    jobs = (
        db.query(WorkspaceJob)
        .filter(
            WorkspaceJob.workspace_id == workspace.id,
            WorkspaceJob.system_id == system.id,
            WorkspaceJob.created_at >= since,
        )
        .order_by(WorkspaceJob.created_at.desc())
        .limit(20)
        .all()
    )
    jobs = [
        item
        for item in jobs
        if not _is_showcase_seed_payload(item.input_ref)
        and not _is_showcase_seed_payload(item.result)
    ]
    tasks = (
        db.query(Task)
        .filter(
            Task.workspace_id == workspace.id,
            Task.agent_id == system.id,
            Task.created_at >= since,
        )
        .order_by(Task.created_at.desc())
        .limit(20)
        .all()
    )
    tasks = [item for item in tasks if item.created_by != "showcase-seed"]
    audits = _system_audits(db, workspace.id, system.id, run_ids, since)

    latest_version = versions[0] if versions else None
    latest_run = runs[0] if runs else None
    snapshot_id = _snapshot_id(system, latest_version, latest_run, window)
    generated_at = _iso(datetime.utcnow())
    header = _header(system, runs)
    common = {
        "capability": capability,
        "runs": runs,
        "invocations": invocations,
        "evaluations": evaluations,
        "contexts": contexts,
        "skills": skills,
        "control": control,
        "adaptive": adaptive,
        "membrane": membrane,
        "decisions": decisions,
        "versions": versions,
        "jobs": jobs,
        "tasks": tasks,
        "audits": audits,
        "since": since,
        "generated_at": generated_at,
    }
    facets = {
        "build": _build_projection(system, **common),
        "operate": _operate_projection(system, **common),
        "steer": _steer_projection(system, **common),
        "govern": _govern_projection(
            db,
            workspace=workspace,
            user=user,
            system=system,
            **common,
        ),
    }[lens]

    return {
        "schema_version": 1,
        "snapshot_id": snapshot_id,
        "generated_at": generated_at,
        "window": window,
        "identity": {
            "workspace_id": workspace.id,
            "capability_id": system.capability_id,
            "system_id": system.id,
            "version_id": latest_version.id if latest_version else None,
            "name": system.name,
        },
        "header": header,
        "lens": lens,
        "facets": facets,
    }


def _build_projection(system: System, **data: Any) -> dict[str, Any]:
    capability: Optional[Capability] = data["capability"]
    skills: list[Skill] = data["skills"]
    contexts: list[Context] = data["contexts"]
    flow = system.flow_definition if isinstance(system.flow_definition, Mapping) else {}
    nodes = [item for item in flow.get("nodes", []) if isinstance(item, Mapping)]
    edges = [item for item in flow.get("edges", []) if isinstance(item, Mapping)]
    configured = bool(nodes)
    return _facets(
        overview=[
            _block("composition", "Composition", [
                _fact("objective", "Objective", system.objective or None, configured=bool(system.objective), source="systems.objective"),
                _fact("capability", "Capability", _capability_value(capability), configured=capability is not None, source="capabilities"),
                _fact("coordination", "Coordination", system.coordination_pattern, source="systems.coordination_pattern"),
            ]),
        ],
        runs=[
            _block("execution-contract", "Execution contract", [
                _fact("io_mode", "I/O mode", flow.get("io_mode"), configured="io_mode" in flow, source="systems.flow_definition.io_mode"),
                _fact("namespaces", "Variable namespaces", flow.get("variable_namespaces"), configured=bool(flow.get("variable_namespaces")), source="systems.flow_definition.variable_namespaces"),
                _fact("execution_mode", "Execution mode", system.execution_mode, source="systems.execution_mode"),
            ]),
        ],
        design=[
            _block("flow", "Flow", [
                _fact("schema_version", "Schema", flow.get("schema_version"), configured=bool(flow), source="systems.flow_definition"),
                _fact("io_mode", "I/O mode", flow.get("io_mode"), configured="io_mode" in flow, source="systems.flow_definition.io_mode"),
                _fact("nodes", "Nodes", len(nodes) if configured else None, measured=configured, source="systems.flow_definition.nodes", sample_count=len(nodes) if configured else None),
                _fact("edges", "Edges", len(edges) if configured else None, measured=configured, source="systems.flow_definition.edges", sample_count=len(edges) if configured else None),
            ]),
            _block("skills", "Skills", [
                _fact("configured_skills", "Configured Skills", [_skill_value(skill) for skill in skills], configured=bool(skills), source="skills"),
            ]),
            _block("configuration", "Effective configuration", [
                _fact("model", "Default model", system.default_model, configured=bool(system.default_model), source="systems.default_model"),
                _fact("retrieval_mode", "Retrieval mode", system.retrieval_mode_default, configured=bool(system.retrieval_mode_default), source="systems.retrieval_mode_default"),
            ]),
        ],
        context=[
            _block("context", "Context bindings", [
                _fact("contexts", "Contexts", [_context_value(item) for item in contexts], configured=bool(contexts), source="contexts"),
                _fact("data_refs", "Data references", sum(len(item.data_refs or []) for item in contexts) if contexts else None, measured=bool(contexts), source="contexts.data_refs", sample_count=len(contexts) if contexts else None),
                _fact("memory_refs", "Memory references", sum(len(item.memory_refs or []) for item in contexts) if contexts else None, measured=bool(contexts), source="contexts.memory_refs", sample_count=len(contexts) if contexts else None),
            ]),
        ],
    )


def _operate_projection(system: System, **data: Any) -> dict[str, Any]:
    runs: list[Run] = data["runs"]
    invocations: list[SkillInvocation] = data["invocations"]
    evaluations: list[EvaluationScore] = data["evaluations"]
    capability: Optional[Capability] = data["capability"]
    jobs: list[WorkspaceJob] = data["jobs"]
    tasks: list[Task] = data["tasks"]
    terminal = [run for run in runs if run.status in {"completed", "failed", "cancelled"}]
    completed = [run for run in terminal if run.status == "completed"]
    failed = [run for run in runs if run.status == "failed" or bool(run.error)]
    durations = sorted(float(run.duration_ms) for run in completed if run.duration_ms is not None)
    costs = [float(run.cost_internal) for run in completed if run.cost_internal is not None]
    success_rate = (len(completed) / len(terminal) * 100.0) if terminal else None
    sla = capability.sla if capability and isinstance(capability.sla, Mapping) else {}
    success_target = _sla_success_target(sla)
    health = None
    if success_rate is not None and success_target is not None:
        health = "within_sla" if success_rate >= success_target else "below_sla"
    return _facets(
        overview=[
            _block("health", "Runtime health", [
                _fact("health", "Health", health, configured=success_target is not None, measured=bool(terminal), source="derived:runs.success_rate,capabilities.sla", sample_count=len(terminal) if terminal else None),
                _fact("success_rate", "Success rate", success_rate, measured=bool(terminal), unit="%", source="runs.status", sample_count=len(terminal) if terminal else None),
                _fact("quality", "Latest quality", evaluations[0].composite_score if evaluations else None, measured=bool(evaluations), unit="/100", source="evaluation_scores.composite_score", as_of=_iso(evaluations[0].created_at) if evaluations else None, sample_count=len(evaluations) if evaluations else None),
            ]),
            _block("sla", "SLA", [
                _fact("target", "Configured target", _safe_mapping(sla), configured=bool(sla), source="capabilities.sla"),
                _fact("p95_latency", "Observed p95 latency", _percentile(durations, 0.95), measured=bool(durations), unit="ms", source="runs.duration_ms", sample_count=len(durations) if durations else None),
            ]),
        ],
        runs=[
            _block("runs", "Runs", [
                _fact("recent_runs", "Recent Runs", [_run_value(run) for run in runs[:10]], measured=bool(runs), source="runs", sample_count=len(runs) if runs else None),
                _fact("p50_latency", "p50 latency", _percentile(durations, 0.5), measured=bool(durations), unit="ms", source="runs.duration_ms", sample_count=len(durations) if durations else None),
                _fact("cost", "Measured cost", sum(costs) if costs else None, measured=bool(costs), source="runs.cost_internal", sample_count=len(costs) if costs else None),
            ]),
            _block("errors", "Errors", [
                _fact("failed_runs", "Failed Runs", len(failed) if runs else None, measured=bool(runs), source="runs.status,error", sample_count=len(runs) if runs else None),
                _fact("invocation_errors", "Invocation errors", len([item for item in invocations if item.error]) if invocations else None, measured=bool(invocations), source="skill_invocations.error", sample_count=len(invocations) if invocations else None),
            ]),
            _block("work-items", "Work items", [
                _fact("jobs", "Workspace jobs", [_job_value(item) for item in jobs], measured=bool(jobs), source="workspace_jobs", sample_count=len(jobs) if jobs else None),
                _fact("tasks", "Tasks", [_task_value(item) for item in tasks], measured=bool(tasks), source="tasks", sample_count=len(tasks) if tasks else None),
                _fact("hitl", "HITL waits", len([run for run in runs if run.status == "hitl_pending"]) if runs else None, measured=bool(runs), source="runs.status", sample_count=len(runs) if runs else None),
            ]),
        ],
        design=[
            _block("deployed-configuration", "Deployed execution", [
                _fact("execution_mode", "Execution mode", system.execution_mode, source="systems.execution_mode"),
                _fact("profile", "Execution profile", _safe_execution_profile(system.execution_profile), configured=bool(system.execution_profile), source="systems.execution_profile"),
            ]),
        ],
        context=[
            _block("runtime-context", "Runtime context use", [
                _fact("invocations", "Skill invocations", len(invocations) if invocations else None, measured=bool(invocations), source="skill_invocations", sample_count=len(invocations) if invocations else None),
                _fact("retrieval_calls", "Retrieval calls", len([item for item in invocations if "search" in str(item.skill_slug or "") or "retriev" in str(item.skill_slug or "")]) if invocations else None, measured=bool(invocations), source="skill_invocations.skill_slug", sample_count=len(invocations) if invocations else None),
            ]),
        ],
    )


def _steer_projection(system: System, **data: Any) -> dict[str, Any]:
    runs: list[Run] = data["runs"]
    decisions: list[Decision] = data["decisions"]
    control: Optional[ControlPolicy] = data["control"]
    adaptive: Optional[AdaptivePolicy] = data["adaptive"]
    completed = [run for run in runs if run.status == "completed"]
    costs = [float(run.cost_internal) for run in completed if run.cost_internal is not None]
    values = [float(run.value_estimated) for run in completed if run.value_estimated is not None]
    total_cost = sum(costs) if costs else None
    total_value = sum(values) if values else None
    roi = (
        ((total_value - total_cost) / total_cost) * 100.0
        if total_cost and total_value is not None
        else None
    )
    model = _steering_model(system)
    simulation = _simulation_preview(
        system.id,
        total_cost,
        total_value,
        model,
        as_of=data["generated_at"],
    )
    return _facets(
        overview=[
            _block("outcomes", "Measured outcomes", [
                _fact("value", "Estimated value", total_value, measured=bool(values), source="runs.value_estimated", sample_count=len(values) if values else None),
                _fact("cost", "Internal cost", total_cost, measured=bool(costs), source="runs.cost_internal", sample_count=len(costs) if costs else None),
                _fact("roi", "ROI", roi, measured=roi is not None, unit="%", source="derived:runs.value_estimated,cost_internal", sample_count=len(completed) if roi is not None else None),
            ]),
            _block("recommendations", "Recommendations", [
                _fact("decisions", "Open decisions", [_decision_value(item) for item in decisions if item.status in {"proposed", "accepted"}], measured=bool(decisions), source="decisions", sample_count=len(decisions) if decisions else None),
            ]),
        ],
        runs=[
            _block("outcome-distribution", "Outcome distribution", [
                _fact("confidence", "Average confidence", _average([run.confidence for run in completed]), measured=any(run.confidence is not None for run in completed), source="runs.confidence", sample_count=len([run for run in completed if run.confidence is not None]) or None),
                _fact("efficiency", "Average efficiency", _average([run.efficiency for run in completed]), measured=any(run.efficiency is not None for run in completed), source="runs.efficiency", sample_count=len([run for run in completed if run.efficiency is not None]) or None),
            ]),
        ],
        design=[
            _block("policies", "Steering policies", [
                _fact("control", "Control policy", _policy_value(control), configured=control is not None, source="control_policies"),
                _fact("adaptive", "Adaptive policy", _adaptive_value(adaptive), configured=adaptive is not None, source="adaptive_policies"),
            ]),
            _block("simulation", "Impact preview", [
                _fact("model", "Model", model, configured=model is not None, source="systems.settings.steering_model"),
                _fact("preview", "Modelled preview", simulation, measured=simulation is not None, source="simulation:not_measurement", sample_count=len(completed) if simulation is not None else None),
            ]),
        ],
        context=[
            _block("assumptions", "Decision assumptions", [
                _fact("window", "Evidence window", "current perspective window", source="request.window"),
                _fact("simulation_assumptions", "Simulation assumptions", model.get("assumptions") if model else None, configured=model is not None, source="systems.settings.steering_model.assumptions"),
            ]),
        ],
    )


def _govern_projection(
    db: DBSession,
    *,
    workspace: Workspace,
    user: User,
    system: System,
    **data: Any,
) -> dict[str, Any]:
    capability: Optional[Capability] = data["capability"]
    membrane: MembraneSpec = data["membrane"]
    control: Optional[ControlPolicy] = data["control"]
    audits: list[AuditLog] = data["audits"]
    versions: list[SystemVersion] = data["versions"]
    runs: list[Run] = data["runs"]
    membership = current_membership(db, user, workspace)
    role = getattr(membership, "role_template", None) or getattr(membership, "role", None)
    privileged = bool(
        getattr(user, "role", None) == "admin"
        or (membership and is_admin_template(membership.role_template, membership.role))
    )
    resource_attrs = {
        "iam_manifest": "system_engine",
        "system_id": system.id,
        "capability_id": system.capability_id,
        "capability": capability.slug if capability else None,
    }
    read_decision = evaluate_permission(
        db,
        user=user,
        workspace=workspace,
        membership=membership,
        resource_kind="system",
        action="read",
        resource_attrs=resource_attrs,
        audit_prefix="system",
        audit_denials=False,
    )
    iam_decision = evaluate_permission(
        db,
        user=user,
        workspace=workspace,
        membership=membership,
        resource_kind="system",
        action="engine.run",
        resource_attrs=resource_attrs,
        audit_prefix="system",
        audit_denials=False,
    )
    iam_enforced = is_iam_enforced_for_workspace(workspace)
    membrane_decision = evaluate_capability(
        membrane,
        model=system.default_model,
        action="system.engine.run",
    )
    engine_allowed = (iam_decision.allowed or not iam_enforced) and membrane_decision.allowed
    access = {
        "system.read": {
            "allowed": bool(membership) and (read_decision.allowed or not iam_enforced),
            "iam_enforced": iam_enforced,
            "iam_reason": read_decision.reason,
            "iam_policy_id": read_decision.policy_id,
        },
        "system.engine.run": {
            "allowed": engine_allowed,
            "iam_enforced": iam_enforced,
            "iam_reason": iam_decision.reason,
            "iam_policy_id": iam_decision.policy_id,
            "membrane_mode": membrane.effective_mode.value,
            "membrane_violations": list(membrane_decision.violations),
        },
    }
    facet_states = _membrane_states(membrane, data["decisions"])
    version_value = [_version_value(item) for item in versions] if privileged else None
    audit_value = [_audit_value(item) for item in audits] if privileged else None
    provenance_rows = _provenance_rows(runs)
    return _facets(
        overview=[
            _block("effective-access", "Effective access", [
                _fact("role", "Workspace role", role, configured=bool(role), source="workspace_members"),
                _fact("actions", "Effective actions", access, source="iam+membrane"),
            ]),
            _block("constraints", "Enforced constraints", [
                _fact("membrane", "Membrane facets", facet_states, configured=bool(membrane.configured_facets()), source="control_policies.extra.membrane_spec"),
                _fact("control", "Control policy", _policy_value(control), configured=control is not None, source="control_policies"),
            ]),
        ],
        runs=[
            _block("execution-audit", "Execution audit", [
                _fact("events", "System events", audit_value, restricted=not privileged, measured=bool(audits), source="audit_logs", sample_count=len(audits) if audits and privileged else None),
            ]),
        ],
        design=[
            _block("versions", "Versions", [
                _fact("history", "Version history", version_value, restricted=not privileged, measured=bool(versions), source="system_versions", sample_count=len(versions) if versions and privileged else None),
            ]),
            _block("change-history", "Change history", [
                _fact("changes", "Audited changes", audit_value, restricted=not privileged, measured=bool(audits), source="audit_logs", sample_count=len(audits) if audits and privileged else None),
                _fact(
                    "sensitive_values",
                    "Sensitive field values",
                    restricted=True,
                    source="audit_logs.details",
                ),
            ]),
        ],
        context=[
            _block("data-governance", "Data governance", [
                _fact("inbound", "Inbound state", facet_states.get("inbound"), configured="inbound" in membrane.configured_facets(), source="membrane.inbound"),
                _fact("outbound", "Outbound state", facet_states.get("outbound"), configured="outbound" in membrane.configured_facets(), source="membrane.outbound"),
            ]),
            _block("provenance", "Provenance", [
                _fact("policy", "Provenance state", facet_states.get("provenance"), configured="provenance" in membrane.configured_facets(), source="membrane.provenance"),
                _fact("artifacts", "Persisted artifacts", provenance_rows, measured=bool(provenance_rows), source="runs.output_ref/checkpoints", sample_count=len(provenance_rows) if provenance_rows else None),
            ]),
        ],
    )


def _header(system: System, runs: list[Run]) -> dict[str, Any]:
    terminal = [run for run in runs if run.status in {"completed", "failed", "cancelled"}]
    completed = [run for run in terminal if run.status == "completed"]
    success_rate = (len(completed) / len(terminal) * 100.0) if terminal else None
    latest = runs[0] if runs else None
    runtime_as_of = _iso(latest.started_at) if latest else None
    return {
        "status": _fact("status", "Status", system.status, source="systems.status", as_of=_iso(system.updated_at)),
        "last_run_at": _fact("last_run_at", "Last run", runtime_as_of, measured=latest is not None, source="runs.started_at", as_of=runtime_as_of, sample_count=1 if latest else None),
        "run_count": _fact("run_count", "Runs", len(runs) if runs else None, measured=bool(runs), source="runs", as_of=runtime_as_of, sample_count=len(runs) if runs else None),
        "success_rate": _fact("success_rate", "Success", success_rate, measured=bool(terminal), unit="%", source="runs.status", as_of=runtime_as_of, sample_count=len(terminal) if terminal else None),
    }


def _sla_success_target(sla: Mapping[str, Any]) -> Optional[float]:
    """Read an explicitly configured success target as a percentage."""

    raw = sla.get("success_rate")
    if raw is None:
        raw = sla.get("success_rate_target")
    if raw is None:
        return None
    try:
        target = float(raw)
    except (TypeError, ValueError):
        return None
    if not 0 <= target <= 100:
        return None
    return target * 100.0 if target <= 1 else target


def _facets(**values: list[dict[str, Any]]) -> dict[str, Any]:
    return {facet: {"blocks": values.get(facet, [])} for facet in FACETS}


def _block(block_id: str, title: str, facts: list[dict[str, Any]], description: Optional[str] = None) -> dict[str, Any]:
    return {"id": block_id, "title": title, "description": description, "facts": facts}


def _fact(
    key: str,
    label: str,
    value: Any = None,
    *,
    measured: Optional[bool] = None,
    configured: Optional[bool] = None,
    restricted: bool = False,
    unavailable: bool = False,
    unit: Optional[str] = None,
    source: Optional[str] = None,
    as_of: Optional[str] = None,
    sample_count: Optional[int] = None,
) -> dict[str, Any]:
    if restricted:
        state = "restricted"
        value = None
    elif unavailable:
        state = "unavailable"
        value = None
    elif configured is False:
        state = "not_configured"
        value = None
    elif measured is False:
        state = "not_measured"
        value = None
    elif value is None:
        state = "not_measured" if measured is not None else "not_configured"
    else:
        state = "available"
    assert state in FACT_STATES
    return {
        "key": key,
        "label": label,
        "state": state,
        "value": _jsonable(value),
        "unit": unit,
        "source": source,
        "as_of": as_of,
        "sample_count": sample_count,
    }


def _capability(db: DBSession, workspace_id: str, capability_id: Optional[str]) -> Optional[Capability]:
    if not capability_id:
        return None
    return (
        db.query(Capability)
        .filter(
            Capability.id == capability_id,
            or_(Capability.workspace_id == workspace_id, Capability.workspace_id.is_(None)),
        )
        .first()
    )


def _contexts(db: DBSession, workspace_id: str, system: System) -> list[Context]:
    query = db.query(Context).filter(Context.workspace_id == workspace_id)
    if system.context_id:
        query = query.filter(or_(Context.id == system.context_id, Context.system_id == system.id))
    else:
        query = query.filter(Context.system_id == system.id)
    return query.order_by(Context.updated_at.desc()).all()


def _skills(db: DBSession, workspace_id: str, identifiers: list[str]) -> list[Skill]:
    if not identifiers:
        return []
    rows = (
        db.query(Skill)
        .filter(
            or_(Skill.workspace_id == workspace_id, Skill.workspace_id.is_(None)),
            or_(Skill.id.in_(identifiers), Skill.slug.in_(identifiers)),
        )
        .all()
    )
    order = {value: index for index, value in enumerate(identifiers)}
    return sorted(rows, key=lambda row: min(order.get(row.id, 10_000), order.get(row.slug, 10_000)))


def _control_policy(db: DBSession, workspace_id: str, system: System) -> Optional[ControlPolicy]:
    query = db.query(ControlPolicy).filter(ControlPolicy.workspace_id == workspace_id)
    if system.control_policy_id:
        row = query.filter(ControlPolicy.id == system.control_policy_id).first()
        if row:
            return row
    return (
        query.filter(ControlPolicy.scope == "system", ControlPolicy.target_id == system.id)
        .order_by(ControlPolicy.updated_at.desc())
        .first()
    )


def _adaptive_policy(db: DBSession, workspace_id: str, system: System) -> Optional[AdaptivePolicy]:
    query = db.query(AdaptivePolicy).filter(AdaptivePolicy.workspace_id == workspace_id)
    if system.adaptive_policy_id:
        row = query.filter(AdaptivePolicy.id == system.adaptive_policy_id).first()
        if row:
            return row
    return (
        query.filter(AdaptivePolicy.scope == "system", AdaptivePolicy.target_id == system.id)
        .order_by(AdaptivePolicy.updated_at.desc())
        .first()
    )


def _decisions(
    db: DBSession,
    workspace_id: str,
    system_id: str,
    run_ids: list[str],
    since: datetime,
) -> list[Decision]:
    targets = [system_id, *run_ids]
    rows = (
        db.query(Decision)
        .filter(
            Decision.workspace_id == workspace_id,
            Decision.target_id.in_(targets),
            Decision.created_at >= since,
        )
        .order_by(Decision.created_at.desc())
        .limit(50)
        .all()
    )
    return [item for item in rows if not _is_showcase_seed_payload(item.rationale)]


def _system_audits(
    db: DBSession,
    workspace_id: str,
    system_id: str,
    run_ids: list[str],
    since: datetime,
) -> list[AuditLog]:
    candidates = (
        db.query(AuditLog)
        .filter(AuditLog.workspace_id == workspace_id, AuditLog.timestamp >= since)
        .order_by(AuditLog.timestamp.desc())
        .limit(500)
        .all()
    )
    run_set = set(run_ids)
    rows: list[AuditLog] = []
    for item in candidates:
        details = item.details if isinstance(item.details, Mapping) else {}
        if _is_showcase_seed_payload(details):
            continue
        if (
            item.agent_id == system_id
            or details.get("system_id") == system_id
            or details.get("run_id") in run_set
            or item.trace_id in run_set
        ):
            rows.append(item)
        if len(rows) >= 50:
            break
    return rows


def _membrane_states(spec: MembraneSpec, decisions: list[Decision]) -> dict[str, str]:
    configured = spec.configured_facets()
    breached = {
        str((item.rationale or {}).get("facet"))
        for item in decisions
        if item.kind == "policy_breach" and isinstance(item.rationale, Mapping)
    }
    states: dict[str, str] = {}
    for facet in ("inbound", "outbound", "capabilities", "provenance", "valves"):
        if facet in breached:
            states[facet] = "breached"
        elif facet not in configured:
            states[facet] = "not_configured"
        elif spec.effective_mode.value == "enforce":
            states[facet] = "enforced"
        elif spec.effective_mode.value == "shadow":
            states[facet] = "shadow"
        else:
            states[facet] = "configured"
    return states


def _steering_model(system: System) -> Optional[dict[str, Any]]:
    settings = system.settings if isinstance(system.settings, Mapping) else {}
    raw = settings.get("steering_model")
    if not isinstance(raw, Mapping):
        return None
    allowed = {"version", "cost_multiplier", "value_multiplier", "confidence", "assumptions"}
    return {key: _jsonable(value) for key, value in raw.items() if key in allowed}


def _simulation_preview(
    system_id: str,
    total_cost: Optional[float],
    total_value: Optional[float],
    model: Optional[Mapping[str, Any]],
    *,
    as_of: str,
) -> Optional[dict[str, Any]]:
    if total_cost is None or total_value is None or not model:
        return None
    try:
        cost_multiplier = float(model["cost_multiplier"])
        value_multiplier = float(model["value_multiplier"])
    except (KeyError, TypeError, ValueError):
        return None
    projected_cost = total_cost * cost_multiplier
    projected_value = total_value * value_multiplier
    return {
        "kind": "simulation",
        "measured": False,
        "model_version": model.get("version"),
        "baseline": {"cost": total_cost, "value": total_value},
        "projected": {"cost": projected_cost, "value": projected_value},
        "delta": {"cost": projected_cost - total_cost, "value": projected_value - total_value},
        "confidence": model.get("confidence"),
        "assumptions": model.get("assumptions") or [],
        "provenance": {
            "scope": "system",
            "system_id": system_id,
            "source": "runs.value_estimated,cost_internal",
            "as_of": as_of,
        },
    }


def _is_showcase_seed_payload(value: Any) -> bool:
    """Identify explicitly labelled demo fixtures, never heuristic business data."""

    if not isinstance(value, Mapping):
        return False
    return value.get("showcase_seed") is True or value.get("source") == "showcase_seed"


def _provenance_rows(runs: Iterable[Run]) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for run in runs:
        for value in _walk_values({"output_ref": run.output_ref, "checkpoints": run.checkpoints}):
            if isinstance(value, Mapping) and value.get("uri") and value.get("sha256"):
                found.append({
                    "run_id": run.id,
                    "uri": value.get("uri"),
                    "sha256": value.get("sha256"),
                })
    return found[:20]


def _walk_values(value: Any) -> Iterable[Any]:
    yield value
    if isinstance(value, Mapping):
        for item in value.values():
            yield from _walk_values(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_values(item)


def _snapshot_id(
    system: System,
    version: Optional[SystemVersion],
    run: Optional[Run],
    window: str,
) -> str:
    raw = "|".join([
        str(system.workspace_id or ""),
        system.id,
        str(version.id if version else ""),
        str(run.id if run else ""),
        window,
        _iso(system.updated_at) or "",
    ])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _percentile(values: list[float], quantile: float) -> Optional[float]:
    if not values:
        return None
    index = max(0, min(len(values) - 1, int(round((len(values) - 1) * quantile))))
    return round(values[index], 2)


def _average(values: Iterable[Optional[float]]) -> Optional[float]:
    rows = [float(value) for value in values if value is not None]
    return round(sum(rows) / len(rows), 4) if rows else None


def _safe_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key): _jsonable(item) for key, item in value.items() if "secret" not in str(key).lower() and "token" not in str(key).lower()}


def _safe_execution_profile(value: Any) -> Optional[dict[str, Any]]:
    if not isinstance(value, Mapping):
        return None
    allowed = {"latency_target_ms", "max_runtime_ms", "durable", "pricing_profile", "timeout_ms"}
    result = {key: _jsonable(item) for key, item in value.items() if key in allowed}
    return result or None


def _capability_value(value: Optional[Capability]) -> Optional[dict[str, Any]]:
    return None if value is None else {"id": value.id, "slug": value.slug, "name": value.name, "tier": value.tier}


def _skill_value(value: Skill) -> dict[str, Any]:
    return {"id": value.id, "slug": value.slug, "name": value.name, "version": value.version, "certification": value.certification_level}


def _context_value(value: Context) -> dict[str, Any]:
    return {"id": value.id, "name": value.name, "version": value.version, "ephemeral": bool(value.ephemeral)}


def _run_value(value: Run) -> dict[str, Any]:
    return {"id": value.id, "status": value.status, "started_at": _iso(value.started_at), "duration_ms": value.duration_ms, "decision": value.decision}


def _job_value(value: WorkspaceJob) -> dict[str, Any]:
    return {"id": value.id, "kind": value.kind, "title": value.title, "status": value.status, "progress": value.progress}


def _task_value(value: Task) -> dict[str, Any]:
    return {"id": value.id, "title": value.title, "status": value.status, "progress": value.progress}


def _decision_value(value: Decision) -> dict[str, Any]:
    return {"id": value.id, "scope": value.scope, "kind": value.kind, "status": value.status, "title": value.title, "created_at": _iso(value.created_at)}


def _policy_value(value: Optional[ControlPolicy]) -> Optional[dict[str, Any]]:
    if value is None:
        return None
    return {"id": value.id, "name": value.name, "scope": value.scope, "target_id": value.target_id}


def _adaptive_value(value: Optional[AdaptivePolicy]) -> Optional[dict[str, Any]]:
    if value is None:
        return None
    return {"id": value.id, "name": value.name, "enabled": bool(value.enabled), "scope": value.scope, "target_id": value.target_id}


def _version_value(value: SystemVersion) -> dict[str, Any]:
    return {"id": value.id, "version": value.version_number, "message": value.message, "created_by": value.created_by, "created_at": _iso(value.created_at), "rolled_back_from_id": value.rolled_back_from_id}


def _audit_value(value: AuditLog) -> dict[str, Any]:
    details = value.details if isinstance(value.details, Mapping) else {}
    safe_details = {key: _jsonable(item) for key, item in details.items() if key in {"system_id", "run_id", "fields", "outcome", "reason", "policy_id"}}
    return {"id": value.id, "event_type": value.event_type, "actor": value.actor, "timestamp": _iso(value.timestamp), "severity": value.severity, "details": safe_details}


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return _iso(value)
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    return str(value)


def _iso(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    return value.isoformat(timespec="milliseconds") + ("Z" if value.tzinfo is None else "")
