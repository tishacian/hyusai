"""System 360 read model: four honest projections over one canonical System.

The service deliberately aggregates only workspace-scoped, persisted rows. It
never substitutes process-wide metrics and never turns an absent measurement
into zero.  The UI can therefore switch lenses without changing object
identity while retaining explicit ``not_measured``/``not_configured`` states.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta
from typing import Any, Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session as DBSession

from app.core.iam.dependencies import current_membership, evaluate_permission
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
from app.models.value_loop import (
    ValueActionExecution,
    ValueMeasurement,
    ValueScenario,
    ValueSimulation,
)
from app.models.workspace import Workspace
from app.models.workspace_job import WorkspaceJob
from app.services.audit_access import readable_audit_logs
from app.services.chat_execution_policy import migration_059_system_id
from app.services.decision_access import readable_decisions
from app.services.iam.config_service import is_iam_enforced_for_workspace
from app.services.iam.decision_plane import resolve_action
from app.services.iam.legacy_authority import legacy_object_action_allowed
from app.services.membrane.enforcement import evaluate_capability
from app.services.membrane.spec import MembraneSpec, resolve_membrane_spec
from app.services.projection_integrity import (
    canonical_run_provenance,
    measured_costs_by_run,
    measured_roi_cohort,
    scrub_projection_mapping,
)
from app.services.run_access import (
    readable_runs,
    readable_skill_invocations_for_runs,
)
from app.services.value_loop_contract import (
    CONTROL_POLICY_GUARDRAILS_PATCH_V1,
    validate_value_loop_runtime_contract,
)
from app.services.value_loop_gate import value_loop_requested
from app.services.value_scenario_access import readable_value_scenarios

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
    runs = readable_runs(
        db,
        runs=runs,
        user=user,
        workspace=workspace,
    )
    run_ids = [run.id for run in runs]
    invocations = (
        db.query(SkillInvocation)
        .filter(SkillInvocation.run_id.in_(run_ids))
        .all()
        if run_ids
        else []
    )
    invocations = readable_skill_invocations_for_runs(
        db,
        invocations=invocations,
        runs=runs,
        user=user,
        workspace=workspace,
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
    decisions = _decisions(
        db,
        workspace=workspace,
        user=user,
        system_id=system.id,
        run_ids=run_ids,
        since=since,
        visible_runs=runs,
    )
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
    raw_audits = _system_audits(db, workspace.id, system.id, run_ids, since)
    audits, audits_restricted = readable_audit_logs(
        db,
        logs=raw_audits,
        user=user,
        workspace=workspace,
    )
    value_loop = _value_loop_projection(
        db,
        workspace=workspace,
        user=user,
        system=system,
        since=since,
    )

    latest_version = versions[0] if versions else None
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
        "audits_restricted": audits_restricted,
        "since": since,
        "generated_at": generated_at,
        "value_loop": value_loop,
    }
    all_facets = {
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
    }
    identity = {
        "workspace_id": workspace.id,
        "capability_id": system.capability_id,
        "system_id": system.id,
        "version_id": latest_version.id if latest_version else None,
        "name": system.name,
    }
    snapshot_id = _snapshot_id(
        workspace_id=workspace.id,
        system_id=system.id,
        window=window,
        identity=identity,
        header=header,
        all_facets=all_facets,
        generated_at=generated_at,
    )

    return {
        "schema_version": 1,
        "snapshot_id": snapshot_id,
        "generated_at": generated_at,
        "window": window,
        "identity": identity,
        "header": header,
        "lens": lens,
        "facets": all_facets[lens],
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
    cost_evidence = measured_costs_by_run(invocations)
    costs = [cost_evidence[run.id][0] for run in completed if run.id in cost_evidence]
    cost_sample_count = sum(
        cost_evidence[run.id][1] for run in completed if run.id in cost_evidence
    )
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
                _fact("cost", "Measured cost", sum(costs) if costs else None, measured=bool(costs), source="skill_invocations.cost,cost_measured", sample_count=cost_sample_count or None),
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
    invocations: list[SkillInvocation] = data["invocations"]
    decisions: list[Decision] = data["decisions"]
    control: Optional[ControlPolicy] = data["control"]
    adaptive: Optional[AdaptivePolicy] = data["adaptive"]
    completed = [run for run in runs if run.status == "completed"]
    cost_evidence = measured_costs_by_run(invocations)
    costs = [cost_evidence[run.id][0] for run in completed if run.id in cost_evidence]
    cost_sample_count = sum(
        cost_evidence[run.id][1] for run in completed if run.id in cost_evidence
    )
    values = [
        float(run.value_estimated)
        for run in completed
        if run.value_estimated is not None
        and str(run.value_source or "unset") in {"auto", "operator"}
    ]
    total_cost = sum(costs) if costs else None
    total_value = sum(values) if values else None
    roi_cohort = measured_roi_cohort(completed, cost_evidence)
    model = _steering_model(system)
    value_loop = data.get("value_loop")
    simulation = _simulation_preview(value_loop)
    overview_blocks = [
        _block("outcomes", "Measured outcomes", [
            _fact("value", "Estimated value", total_value, measured=bool(values), source="runs.value_estimated", sample_count=len(values) if values else None),
            _fact("cost", "Internal cost", total_cost, measured=bool(costs), source="skill_invocations.cost,cost_measured", sample_count=cost_sample_count or None),
            _fact("roi", "ROI", roi_cohort.roi_percent, measured=roi_cohort.roi_percent is not None, unit="%", source="derived:runs.value_estimated,skill_invocations.cost,cost_measured", sample_count=roi_cohort.run_count if roi_cohort.roi_percent is not None else None),
        ]),
        _block("recommendations", "Recommendations", [
            _fact("decisions", "Open decisions", [_decision_value(item) for item in decisions if item.status in {"proposed", "accepted"}], measured=bool(decisions), source="decisions", sample_count=len(decisions) if decisions else None),
        ]),
    ]
    design_blocks = [
        _block("policies", "Steering policies", [
            _fact("control", "Control policy", _policy_value(control), configured=control is not None, source="control_policies"),
            _fact("adaptive", "Adaptive policy", _adaptive_value(adaptive), configured=adaptive is not None, source="adaptive_policies"),
        ]),
        _block("simulation", "Impact preview", [
            _fact("model", "Model", model, configured=model is not None, source="systems.settings.steering_model"),
            _fact("preview", "Modelled preview", simulation, configured=simulation is not None, source="value_simulations:simulation:not_measurement", sample_count=1 if simulation is not None else None),
        ]),
    ]
    if isinstance(value_loop, Mapping):
        scenarios = value_loop.get("scenarios")
        scenario_rows = scenarios if isinstance(scenarios, list) else []
        value_loop_restricted = value_loop.get("state") == "restricted"
        actuator_configured = value_loop.get("actuator_configured") is True
        overview_blocks.append(
            _block("value-loop", "Outcome → Decision → Act → Measure", [
                _fact(
                    "lifecycle",
                    "Authoritative lifecycle",
                    value_loop.get("latest_status"),
                    restricted=value_loop_restricted,
                    configured=True,
                    source="value_scenarios.status",
                    as_of=value_loop.get("as_of"),
                ),
                _fact(
                    "scenarios",
                    "Governed scenarios",
                    scenario_rows,
                    restricted=value_loop_restricted,
                    measured=True,
                    source="value_scenarios,value_simulations,value_action_executions,value_measurements",
                    as_of=value_loop.get("as_of"),
                    sample_count=len(scenario_rows),
                ),
                _fact(
                    "observed_measurements",
                    "Observed measurements",
                    value_loop.get("measured_count"),
                    restricted=value_loop_restricted,
                    measured=True,
                    source="value_measurements.status",
                    as_of=value_loop.get("as_of"),
                    sample_count=value_loop.get("measurement_count"),
                ),
            ]),
        )
        design_blocks.append(
            _block("value-actuator", "Configured value actuator", [
                _fact(
                    "actuator",
                    "Actuator",
                    value_loop.get("actuator"),
                    restricted=value_loop_restricted,
                    configured=actuator_configured,
                    source="systems.settings.value_loop.actuators",
                ),
                _fact(
                    "fields",
                    "Allowed fields",
                    value_loop.get("actuator_fields"),
                    restricted=value_loop_restricted,
                    configured=actuator_configured,
                    source="systems.settings.value_loop.actuators.fields",
                ),
            ]),
        )
    return _facets(
        overview=overview_blocks,
        runs=[
            _block("outcome-distribution", "Outcome distribution", [
                _fact("confidence", "Average confidence", _average([run.confidence for run in completed]), measured=any(run.confidence is not None for run in completed), source="runs.confidence", sample_count=len([run for run in completed if run.confidence is not None]) or None),
                _fact("efficiency", "Average efficiency", _average([run.efficiency for run in completed]), measured=any(run.efficiency is not None for run in completed), source="runs.efficiency", sample_count=len([run for run in completed if run.efficiency is not None]) or None),
            ]),
        ],
        design=design_blocks,
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
    legacy_read_allowed = bool(membership) and (
        read_decision.allowed or not iam_enforced
    )
    legacy_engine_allowed = bool(membership) and (
        iam_decision.allowed or not iam_enforced
    )
    read_resolution = resolve_action(
        db,
        user=user,
        workspace=workspace,
        membership=membership,
        resource_kind="system",
        action="read",
        legacy_allowed=legacy_read_allowed,
        resource_attrs=resource_attrs,
        audit_shadow_diff=False,
    )
    engine_resolution = resolve_action(
        db,
        user=user,
        workspace=workspace,
        membership=membership,
        resource_kind="system",
        action="engine.run",
        legacy_allowed=legacy_engine_allowed,
        resource_attrs=resource_attrs,
        audit_shadow_diff=False,
    )
    admin_resolution = resolve_action(
        db,
        user=user,
        workspace=workspace,
        membership=membership,
        resource_kind="system",
        action="admin",
        legacy_allowed=legacy_object_action_allowed(
            db,
            user=user,
            workspace=workspace,
            resource_kind="system",
            action="admin",
            resource_attrs={
                "managed_system": migration_059_system_id(workspace) == system.id,
            },
        ),
        resource_attrs=resource_attrs,
        audit_shadow_diff=False,
    )
    engine_allowed = (
        engine_resolution.effective_allowed and membrane_decision.allowed
    )
    access = {
        "system.read": {
            **read_resolution.to_dict(),
            "allowed": read_resolution.effective_allowed,
        },
        "system.engine.run": {
            **engine_resolution.to_dict(),
            "allowed": engine_allowed,
            "membrane_mode": membrane.effective_mode.value,
            "membrane_violations": list(membrane_decision.violations),
        },
        "system.admin": {
            **admin_resolution.to_dict(),
            "allowed": admin_resolution.effective_allowed,
        },
    }
    facet_states = _membrane_states(membrane, data["decisions"])
    admin_allowed = admin_resolution.effective_allowed
    audits_restricted = bool(data.get("audits_restricted"))
    version_value = [_version_value(item) for item in versions] if admin_allowed else None
    audit_value = [_audit_value(item) for item in audits]
    provenance_rows = _provenance_rows(runs, data["invocations"])
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
                _fact("events", "System events", audit_value, restricted=audits_restricted, measured=bool(audits), source="audit_logs", sample_count=len(audits) if audits else None),
            ]),
        ],
        design=[
            _block("versions", "Versions", [
                _fact("history", "Version history", version_value, restricted=not admin_allowed, measured=bool(versions), source="system_versions", sample_count=len(versions) if versions and admin_allowed else None),
            ]),
            _block("change-history", "Change history", [
                _fact("changes", "Audited changes", audit_value, restricted=audits_restricted, measured=bool(audits), source="audit_logs", sample_count=len(audits) if audits else None),
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
                _fact("artifacts", "Corroborated artifact references", provenance_rows, measured=bool(provenance_rows), source="runs.output_ref._membrane_provenance + runs.checkpoints[kind=membrane_provenance] + skill_invocations.trace.membrane_provenance", sample_count=len(provenance_rows) if provenance_rows else None),
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
    *,
    workspace: Workspace,
    user: User,
    system_id: str,
    run_ids: list[str],
    since: datetime,
    visible_runs: Iterable[Run],
) -> list[Decision]:
    targets = [system_id, *run_ids]
    rows = (
        db.query(Decision)
        .filter(
            Decision.workspace_id == workspace.id,
            Decision.target_id.in_(targets),
            Decision.created_at >= since,
        )
        .order_by(Decision.created_at.desc())
        .limit(50)
        .all()
    )
    rows = [item for item in rows if not _is_showcase_seed_payload(item.rationale)]
    return readable_decisions(
        db,
        decisions=rows,
        user=user,
        workspace=workspace,
        visible_runs=visible_runs,
    )


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


def _value_loop_projection(
    db: DBSession,
    *,
    workspace: Workspace,
    user: User,
    system: System,
    since: datetime,
) -> Optional[dict[str, Any]]:
    """Return a secret-free value-loop read model only behind the Lot 8 gate."""

    if not value_loop_requested(db, workspace=workspace, system=system):
        return None
    actuator_contract = validate_value_loop_runtime_contract(
        db,
        workspace_id=workspace.id,
        system=system,
    )
    raw_scenarios = (
        db.query(ValueScenario)
        .filter(
            ValueScenario.workspace_id == workspace.id,
            ValueScenario.system_id == system.id,
            ValueScenario.created_at >= since,
        )
        .order_by(ValueScenario.created_at.desc(), ValueScenario.id.desc())
        .limit(20)
        .all()
    )
    scenarios = readable_value_scenarios(
        db,
        scenarios=raw_scenarios,
        user=user,
        workspace=workspace,
    )
    if raw_scenarios and not scenarios:
        return {
            "state": "restricted",
            "latest_status": None,
            "scenarios": [],
            "measurement_count": None,
            "measured_count": None,
            "actuator": None,
            "actuator_fields": [],
            "actuator_configured": False,
            "actuator_reason": "value_scenario_read_denied",
            "as_of": _iso(datetime.utcnow()),
        }
    scenario_ids = [row.id for row in scenarios]
    simulations = (
        db.query(ValueSimulation)
        .filter(
            ValueSimulation.workspace_id == workspace.id,
            ValueSimulation.system_id == system.id,
            ValueSimulation.scenario_id.in_(scenario_ids),
        )
        .order_by(ValueSimulation.generated_at.desc(), ValueSimulation.id.desc())
        .all()
        if scenario_ids
        else []
    )
    actions = (
        db.query(ValueActionExecution)
        .filter(
            ValueActionExecution.workspace_id == workspace.id,
            ValueActionExecution.system_id == system.id,
            ValueActionExecution.scenario_id.in_(scenario_ids),
        )
        .all()
        if scenario_ids
        else []
    )
    measurements = (
        db.query(ValueMeasurement)
        .filter(
            ValueMeasurement.workspace_id == workspace.id,
            ValueMeasurement.system_id == system.id,
            ValueMeasurement.scenario_id.in_(scenario_ids),
        )
        .order_by(ValueMeasurement.measured_at.desc(), ValueMeasurement.id.desc())
        .all()
        if scenario_ids
        else []
    )
    simulation_by_scenario: dict[str, ValueSimulation] = {}
    for row in simulations:
        simulation_by_scenario.setdefault(row.scenario_id, row)
    action_by_scenario = {row.scenario_id: row for row in actions}
    measurement_by_scenario: dict[str, ValueMeasurement] = {}
    for row in measurements:
        measurement_by_scenario.setdefault(row.scenario_id, row)

    scenario_values: list[dict[str, Any]] = []
    for row in scenarios:
        simulation = simulation_by_scenario.get(row.id)
        action = action_by_scenario.get(row.id)
        measurement = measurement_by_scenario.get(row.id)
        scenario_values.append(
            {
                "id": row.id,
                "status": row.status,
                "source_run_id": row.source_run_id,
                "created_at": _iso(row.created_at),
                "simulation": (
                    {
                        "id": simulation.id,
                        "evidence_type": "simulation",
                        "model": simulation.model,
                        "confidence": simulation.confidence,
                        "assumptions": _safe_mapping(simulation.assumptions or {}),
                        "projected_outcome": _safe_mapping(
                            simulation.projected_outcome or {}
                        ),
                        "recommended_action": _safe_mapping(
                            simulation.recommended_action or {}
                        ),
                        "provenance": _safe_mapping(simulation.provenance or {}),
                    }
                    if simulation is not None
                    else None
                ),
                "action": (
                    {
                        "id": action.id,
                        "actuator": action.actuator,
                        "status": action.status,
                        "changed_fields": sorted((action.patch or {}).keys()),
                        "executed_at": _iso(action.executed_at),
                    }
                    if action is not None
                    else None
                ),
                "measurement": (
                    {
                        "id": measurement.id,
                        "status": measurement.status,
                        "reason": measurement.reason,
                        "simulation_id": measurement.simulation_id,
                        "source_run_id": measurement.source_run_id,
                        "evidence_type": "run" if measurement.source_run_id else None,
                        "forecast_delta": _safe_mapping(
                            measurement.forecast_delta or {}
                        ) if measurement.forecast_delta is not None else None,
                        "assumption_verdict": measurement.assumption_verdict,
                        "assumption_evaluation": _safe_mapping(
                            measurement.assumption_evaluation or {}
                        ),
                        "measured_at": _iso(measurement.measured_at),
                    }
                    if measurement is not None
                    else None
                ),
            }
        )

    settings = system.settings if isinstance(system.settings, Mapping) else {}
    value_settings = settings.get("value_loop")
    actuators = value_settings.get("actuators") if isinstance(value_settings, Mapping) else {}
    actuator = CONTROL_POLICY_GUARDRAILS_PATCH_V1
    actuator_config = actuators.get(actuator) if isinstance(actuators, Mapping) else {}
    fields = actuator_config.get("fields") if isinstance(actuator_config, Mapping) else {}
    return {
        "state": "available" if scenarios else "not_configured",
        "latest_status": scenarios[0].status if scenarios else "not_started",
        "scenarios": scenario_values,
        "measurement_count": len(measurements),
        "measured_count": len([row for row in measurements if row.status == "measured"]),
        "actuator": actuator,
        "actuator_fields": sorted(fields) if isinstance(fields, Mapping) else [],
        "actuator_configured": actuator_contract.valid,
        "actuator_reason": actuator_contract.reason,
        "as_of": _iso(datetime.utcnow()),
    }


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
    allowed = {"version", "confidence", "assumptions", "forecasts"}
    return scrub_projection_mapping(
        {key: value for key, value in raw.items() if key in allowed}
    )


def _simulation_preview(
    value_loop: Any,
) -> Optional[dict[str, Any]]:
    if not isinstance(value_loop, Mapping):
        return None
    scenarios = value_loop.get("scenarios")
    if not isinstance(scenarios, list):
        return None
    for scenario in scenarios:
        if not isinstance(scenario, Mapping):
            continue
        simulation = scenario.get("simulation")
        if not isinstance(simulation, Mapping):
            continue
        projected_outcome = simulation.get("projected_outcome")
        recommended_action = simulation.get("recommended_action")
        provenance = simulation.get("provenance")
        if not isinstance(projected_outcome, Mapping):
            continue
        if projected_outcome.get("evidence_type") != "simulation":
            continue
        return {
            "kind": "simulation",
            "measured": False,
            "model": simulation.get("model"),
            "projected_outcome": _safe_mapping(projected_outcome),
            "recommended_action": (
                _safe_mapping(recommended_action)
                if isinstance(recommended_action, Mapping)
                else None
            ),
            "confidence": simulation.get("confidence"),
            "assumptions": _safe_mapping(simulation.get("assumptions") or {}),
            "provenance": (
                _safe_mapping(provenance)
                if isinstance(provenance, Mapping)
                else {}
            ),
        }
    return None


def _is_showcase_seed_payload(value: Any) -> bool:
    """Identify explicitly labelled demo fixtures, never heuristic business data."""

    if not isinstance(value, Mapping):
        return False
    return value.get("showcase_seed") is True or value.get("source") == "showcase_seed"


def _provenance_rows(
    runs: Iterable[Run],
    invocations: Iterable[SkillInvocation],
) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    invocation_rows = list(invocations)
    for run in runs:
        found.extend(
            {"run_id": run.id, **row}
            for row in canonical_run_provenance(run, invocation_rows)
        )
    return found[:20]


def _snapshot_id(
    *,
    workspace_id: str,
    system_id: str,
    window: str,
    identity: Mapping[str, Any],
    header: Mapping[str, Any],
    all_facets: Mapping[str, Any],
    generated_at: str,
) -> str:
    """Fingerprint all four projections while ignoring request-clock noise."""

    def stable(value: Any) -> Any:
        if isinstance(value, Mapping):
            return {str(key): stable(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [stable(item) for item in value]
        if value == generated_at:
            return "<generated_at>"
        return value

    raw = json.dumps(
        {
            "workspace_id": workspace_id,
            "system_id": system_id,
            "window": window,
            "identity": stable(identity),
            "header": stable(header),
            "facets": stable(all_facets),
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )
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
    return _jsonable(scrub_projection_mapping(value))


def _safe_execution_profile(value: Any) -> Optional[dict[str, Any]]:
    if not isinstance(value, Mapping):
        return None
    allowed = {"latency_target_ms", "max_runtime_ms", "durable", "pricing_profile", "timeout_ms"}
    result = scrub_projection_mapping(
        {key: item for key, item in value.items() if key in allowed}
    )
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
    safe_details = scrub_projection_mapping(
        {
            key: item
            for key, item in details.items()
            if key in {"system_id", "run_id", "fields", "outcome", "reason", "policy_id"}
        }
    )
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
