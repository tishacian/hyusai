"""Lens-aware read models for Capability, Run and SkillInvocation.

Lot 7 extends the System 360 contract without collapsing catalog Skills and
runtime SkillInvocations into the same object.  Every projector is deliberately
read-only, workspace scoped, and honest about missing data: absent observations
are emitted as ``not_measured`` or ``not_configured`` instead of zero.

The three response shapes share the same envelope but keep object-specific,
stable facets.  This lets the frontend preserve the selected object, header and
tabs while only the blocks inside a facet change with the active lens.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta
from typing import Any, Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session as DBSession

from app.core.config import settings
from app.models.audit import AuditLog
from app.models.capability import Capability
from app.models.decision import Decision
from app.models.evaluation import EvaluationScore
from app.models.policy import AdaptivePolicy, ControlPolicy
from app.models.run import Run, SkillInvocation
from app.models.system import System
from app.models.system_version import SystemVersion
from app.models.user import User
from app.models.workspace import Workspace
from app.services.audit_access import readable_audit_logs
from app.services.capability_access import resolve_capability_read
from app.services.catalog_visibility import capability_is_visible
from app.services.decision_access import readable_decisions
from app.services.iam.decision_plane import (
    resolve_action as resolve_authorized_action,
)
from app.services.iam.legacy_authority import legacy_object_action_allowed
from app.services.membrane.spec import resolve_membrane_spec
from app.services.projection_gate import authoritative_projection_enabled
from app.services.projection_integrity import (
    canonical_run_provenance,
    invocation_cost_is_measured,
    measured_cost_summary,
    measured_costs_by_run,
    measured_roi_cohort,
    scrub_projection_mapping,
    scrub_projection_value,
)
from app.services.run_access import (
    readable_runs,
    readable_skill_invocations,
    readable_skill_invocations_for_runs,
    resolve_run_read,
    resolve_skill_invocation_read,
)
from app.services.system_access import (
    readable_systems as authorized_systems,
)
from app.services.system_access import (
    resolve_system_read,
)

OBJECT_LENSES = ("build", "operate", "steer", "govern")
WINDOW_DAYS = {"7d": 7, "30d": 30, "90d": 90}
FACT_STATES = {
    "available",
    "not_measured",
    "not_configured",
    "restricted",
    "unavailable",
}


def projection_feature_enabled(
    db: DBSession,
    workspace: Workspace,
    object_type: str,
) -> bool:
    """Return the attested per-workspace Lot 7 gate for an object type.

    A bare feature boolean is intentionally insufficient: the rollout service
    must also have bound validation evidence into the server-owned Workspace
    gate.  There is no slug/global fallback.
    """

    return authoritative_projection_enabled(
        db,
        workspace,
        object_type,
        runtime_revision=str(settings.agentium_image_revision or "").strip().lower(),
    )


def build_capability_perspective(
    db: DBSession,
    *,
    workspace: Workspace,
    user: User,
    capability: Capability,
    lens: str,
    window: str = "30d",
) -> dict[str, Any]:
    since = _validate(lens, window)
    systems = (
        db.query(System)
        .filter(System.workspace_id == workspace.id, System.capability_id == capability.id)
        .order_by(System.updated_at.desc())
        .all()
    )
    systems = _readable_systems(
        db,
        systems=systems,
        workspace=workspace,
        user=user,
    )
    system_ids = [item.id for item in systems]
    run_query = db.query(Run).filter(
        Run.workspace_id == workspace.id,
        Run.started_at >= since,
    )
    if system_ids:
        run_query = run_query.filter(
            or_(
                Run.system_id.in_(system_ids),
                (Run.system_id.is_(None)) & (Run.capability_id == capability.id),
            )
        )
    else:
        run_query = run_query.filter(
            Run.system_id.is_(None),
            Run.capability_id == capability.id,
        )
    runs = readable_runs(
        db,
        runs=run_query.order_by(Run.started_at.desc()).all(),
        user=user,
        workspace=workspace,
    )
    runs = _exclude_seed_runs(runs)
    run_ids = [item.id for item in runs]
    invocations = (
        db.query(SkillInvocation)
        .filter(SkillInvocation.run_id.in_(run_ids))
        .order_by(SkillInvocation.started_at.desc())
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
    decisions, decisions_restricted = _decisions(
        db,
        workspace=workspace,
        user=user,
        targets=[capability.id, *system_ids, *run_ids],
        since=since,
        visible_runs=runs,
    )
    control = _policies(db, ControlPolicy, workspace.id, "capability", capability.id)
    adaptive = _policies(db, AdaptivePolicy, workspace.id, "capability", capability.id)
    raw_audits = _audits(
        db,
        workspace.id,
        ids={capability.id, *system_ids, *run_ids},
        since=since,
    )
    audits, audits_restricted = readable_audit_logs(
        db,
        logs=raw_audits,
        user=user,
        workspace=workspace,
    )
    generated_at = _iso(datetime.utcnow())
    header = _capability_header(capability, systems, runs, invocations)
    common = {
        "db": db,
        "workspace": workspace,
        "user": user,
        "capability": capability,
        "systems": systems,
        "runs": runs,
        "invocations": invocations,
        "decisions": decisions,
        "decisions_restricted": decisions_restricted,
        "control": control,
        "adaptive": adaptive,
        "audits": audits,
        "audits_restricted": audits_restricted,
        "generated_at": generated_at,
    }
    all_facets = {
        "build": _capability_build(**common),
        "operate": _capability_operate(**common),
        "steer": _capability_steer(**common),
        "govern": _capability_govern(**common),
    }
    identity = {
        "name": capability.name,
        "capability_id": capability.id,
        "capability_slug": capability.slug,
    }
    return _envelope(
        workspace=workspace,
        object_type="capability",
        object_id=capability.id,
        name=capability.name,
        lens=lens,
        window=window,
        generated_at=generated_at,
        snapshot_values=(_projection_state_digest(identity, header, all_facets),),
        identity=identity,
        header=header,
        facets=all_facets[lens],
    )


def build_run_perspective(
    db: DBSession,
    *,
    workspace: Workspace,
    user: User,
    run: Run,
    lens: str,
    window: str = "30d",
) -> dict[str, Any]:
    since = _validate(lens, window)
    system, capability = _visible_run_parents(
        db,
        workspace=workspace,
        user=user,
        run=run,
    )
    system_version = _run_system_version(
        db,
        workspace=workspace,
        run=run,
        system=system,
    )
    payload_visible = resolve_run_read(
        db,
        run=run,
        user=user,
        workspace=workspace,
        audit_shadow_diff=False,
        audit_shadow_evidence=False,
    ).effective_allowed
    invocations = (
        db.query(SkillInvocation)
        .filter(SkillInvocation.run_id == run.id)
        .order_by(SkillInvocation.started_at.asc())
        .all()
    )
    invocations = readable_skill_invocations(
        db,
        invocations=invocations,
        run=run,
        user=user,
        workspace=workspace,
    )
    decisions, decisions_restricted = _decisions(
        db,
        workspace=workspace,
        user=user,
        targets=[run.id],
        since=since,
        visible_runs=[run] if payload_visible else [],
    )
    evaluations = (
        db.query(EvaluationScore)
        .filter(EvaluationScore.workspace_id == workspace.id, EvaluationScore.run_id == run.id)
        .order_by(EvaluationScore.created_at.desc())
        .all()
    )
    raw_audits = _audits(
        db,
        workspace.id,
        ids={run.id, *([system.id] if system else [])},
        since=since,
    )
    audits, audits_restricted = readable_audit_logs(
        db,
        logs=raw_audits,
        user=user,
        workspace=workspace,
    )
    # Never project the current System policy as if it governed this historical
    # Run. A future execution-policy snapshot can replace this explicit absence.
    membrane = resolve_membrane_spec(control=None)
    generated_at = _iso(datetime.utcnow())
    common = {
        "db": db,
        "workspace": workspace,
        "user": user,
        "run": run,
        "system": system,
        "capability": capability,
        "system_version": system_version,
        "invocations": invocations,
        "decisions": decisions,
        "decisions_restricted": decisions_restricted,
        "evaluations": evaluations,
        "audits": audits,
        "audits_restricted": audits_restricted,
        "membrane": membrane,
        "payload_visible": payload_visible,
    }
    all_facets = {
        "build": _run_build(**common),
        "operate": _run_operate(**common),
        "steer": _run_steer(**common),
        "govern": _run_govern(**common),
    }
    identity = {
        "name": f"Run {run.id[:12]}",
        "capability_id": capability.id if capability is not None else None,
        "system_id": system.id if system is not None else None,
        "run_id": run.id,
    }
    header = _run_header(run, invocations)
    return _envelope(
        workspace=workspace,
        object_type="run",
        object_id=run.id,
        name=f"Run {run.id[:12]}",
        lens=lens,
        window=window,
        generated_at=generated_at,
        snapshot_values=(_projection_state_digest(identity, header, all_facets),),
        identity=identity,
        header=header,
        facets=all_facets[lens],
    )


def build_skill_invocation_perspective(
    db: DBSession,
    *,
    workspace: Workspace,
    user: User,
    run: Run,
    invocation: SkillInvocation,
    lens: str,
    window: str = "30d",
) -> dict[str, Any]:
    since = _validate(lens, window)
    system, capability = _visible_run_parents(
        db,
        workspace=workspace,
        user=user,
        run=run,
    )
    # The current System policy is not execution evidence. Historical
    # invocations without a persisted membrane snapshot stay explicitly
    # unconfigured instead of being recoloured by today's ControlPolicy.
    membrane = resolve_membrane_spec(control=None)
    raw_audits = _audits(
        db,
        workspace.id,
        ids={run.id, invocation.id},
        since=since,
    )
    audits, audits_restricted = readable_audit_logs(
        db,
        logs=raw_audits,
        user=user,
        workspace=workspace,
    )
    payload_visible = bool(
        resolve_run_read(
            db,
            run=run,
            user=user,
            workspace=workspace,
            audit_shadow_diff=False,
            audit_shadow_evidence=False,
        ).effective_allowed
        and resolve_skill_invocation_read(
            db,
            invocation=invocation,
            run=run,
            user=user,
            workspace=workspace,
            audit_shadow_diff=False,
            audit_shadow_evidence=False,
        ).effective_allowed
    )
    generated_at = _iso(datetime.utcnow())
    common = {
        "db": db,
        "workspace": workspace,
        "user": user,
        "run": run,
        "invocation": invocation,
        "system": system,
        "capability": capability,
        "membrane": membrane,
        "audits": audits,
        "audits_restricted": audits_restricted,
        "payload_visible": payload_visible,
    }
    all_facets = {
        "build": _invocation_build(**common),
        "operate": _invocation_operate(**common),
        "steer": _invocation_steer(**common),
        "govern": _invocation_govern(**common),
    }
    snapshot_skill = _invocation_snapshot_skill(invocation)
    # Historical mutable columns are not an immutable execution contract and
    # have no tenant constraint.  Only the validated execution snapshot may
    # identify the catalog component in a projection.
    display_name = snapshot_skill.get("slug") or "Skill invocation"
    identity = {
        "name": display_name,
        "capability_id": capability.id if capability is not None else None,
        "system_id": system.id if system is not None else None,
        "run_id": run.id,
        "skill_id": snapshot_skill.get("id"),
        "skill_slug": snapshot_skill.get("slug"),
        "skill_version": snapshot_skill.get("version"),
        "skill_provider": snapshot_skill.get("provider"),
        "skill_certification_level": snapshot_skill.get("certification_level"),
        "execution_digests": _invocation_snapshot_digests(invocation) or None,
        "execution_snapshot_state": _invocation_snapshot_state(invocation),
        "skill_invocation_id": invocation.id,
    }
    header = _invocation_header(invocation)
    return _envelope(
        workspace=workspace,
        object_type="skill_invocation",
        object_id=invocation.id,
        name=display_name,
        lens=lens,
        window=window,
        generated_at=generated_at,
        snapshot_values=(_projection_state_digest(identity, header, all_facets),),
        identity=identity,
        header=header,
        facets=all_facets[lens],
    )


# Capability projections ----------------------------------------------------


def _capability_build(**data: Any) -> dict[str, Any]:
    capability: Capability = data["capability"]
    systems: list[System] = data["systems"]
    control: list[ControlPolicy] = data["control"]
    adaptive: list[AdaptivePolicy] = data["adaptive"]
    return _facets(
        ("overview", "systems", "outcomes", "policies"),
        overview=[
            _block(
                "promise",
                "Outcome promise",
                [
                    _fact(
                        "description",
                        "Purpose",
                        capability.description or None,
                        configured=bool(capability.description),
                        source="capabilities.description",
                    ),
                    _fact(
                        "input_unit",
                        "Input unit",
                        capability.input_unit,
                        source="capabilities.input_unit",
                    ),
                    _fact(
                        "output_unit",
                        "Output unit",
                        capability.output_unit,
                        source="capabilities.output_unit",
                    ),
                    _fact("tier", "Tier", capability.tier, source="capabilities.tier"),
                ],
            ),
            _block(
                "composition",
                "Composition",
                [
                    _fact(
                        "skills",
                        "Catalog Skills",
                        list(capability.skill_ids or []),
                        configured=bool(capability.skill_ids),
                        source="capabilities.skill_ids",
                        sample_count=len(capability.skill_ids or []) or None,
                    ),
                ],
            ),
        ],
        systems=[
            _block(
                "implementations",
                "System implementations",
                [
                    _fact(
                        "systems",
                        "Systems",
                        [_system_value(item) for item in systems],
                        configured=bool(systems),
                        source="systems.capability_id",
                        sample_count=len(systems) or None,
                    ),
                    _fact(
                        "execution_modes",
                        "Execution modes",
                        sorted({item.execution_mode for item in systems}),
                        configured=bool(systems),
                        source="systems.execution_mode",
                        sample_count=len(systems) or None,
                    ),
                ],
            ),
        ],
        outcomes=[
            _block(
                "outcome-contract",
                "Configured outcome",
                [
                    _fact(
                        "value_per_outcome",
                        "Value per outcome",
                        capability.value_per_outcome,
                        configured=capability.value_per_outcome is not None,
                        source="capabilities.value_per_outcome",
                    ),
                    _fact(
                        "confidence_threshold",
                        "Confidence threshold",
                        capability.confidence_threshold,
                        configured=capability.confidence_threshold is not None,
                        source="capabilities.confidence_threshold",
                    ),
                    _fact(
                        "roi_model",
                        "ROI model",
                        _safe_mapping(capability.roi_model),
                        configured=bool(capability.roi_model),
                        source="capabilities.roi_model",
                    ),
                ],
            ),
        ],
        policies=[
            _block(
                "policy-bindings",
                "Policy bindings",
                [
                    _fact(
                        "control",
                        "Control policies",
                        [_control_value(item) for item in control],
                        configured=bool(control),
                        source="control_policies",
                        sample_count=len(control) or None,
                    ),
                    _fact(
                        "adaptive",
                        "Adaptive policies",
                        [_adaptive_value(item) for item in adaptive],
                        configured=bool(adaptive),
                        source="adaptive_policies",
                        sample_count=len(adaptive) or None,
                    ),
                    _fact(
                        "sla",
                        "SLA",
                        _safe_mapping(capability.sla),
                        configured=bool(capability.sla),
                        source="capabilities.sla",
                    ),
                ],
            ),
        ],
    )


def _capability_operate(**data: Any) -> dict[str, Any]:
    systems: list[System] = data["systems"]
    runs: list[Run] = data["runs"]
    invocations: list[SkillInvocation] = data["invocations"]
    terminal = [item for item in runs if item.status in {"completed", "failed", "cancelled"}]
    completed = [item for item in terminal if item.status == "completed"]
    failures = [item for item in runs if item.status == "failed" or item.error]
    durations = sorted(
        float(item.duration_ms) for item in completed if item.duration_ms is not None
    )
    success = (len(completed) / len(terminal) * 100.0) if terminal else None
    return _facets(
        ("overview", "systems", "outcomes", "policies"),
        overview=[
            _block(
                "runtime-health",
                "Runtime health",
                [
                    _fact(
                        "runs",
                        "Runs",
                        len(runs) if runs else None,
                        measured=bool(runs),
                        source="runs",
                        sample_count=len(runs) or None,
                    ),
                    _fact(
                        "success_rate",
                        "Success rate",
                        success,
                        measured=bool(terminal),
                        unit="%",
                        source="runs.status",
                        sample_count=len(terminal) or None,
                    ),
                    _fact(
                        "p95_latency",
                        "p95 latency",
                        _percentile(durations, 0.95),
                        measured=bool(durations),
                        unit="ms",
                        source="runs.duration_ms",
                        sample_count=len(durations) or None,
                    ),
                    _fact(
                        "errors",
                        "Failed Runs",
                        len(failures) if runs else None,
                        measured=bool(runs),
                        source="runs.status,error",
                        sample_count=len(runs) or None,
                    ),
                ],
            ),
        ],
        systems=[
            _block(
                "system-health",
                "System health",
                [
                    _fact(
                        "systems",
                        "Implementations",
                        [_system_runtime_value(item, runs) for item in systems],
                        measured=bool(systems),
                        source="systems+runs",
                        sample_count=len(systems) or None,
                    ),
                ],
            ),
        ],
        outcomes=[
            _block(
                "runtime-outcomes",
                "Observed outcomes",
                [
                    _fact(
                        "decisions",
                        "Recorded decisions",
                        len([item for item in completed if item.decision]) or None,
                        measured=bool(completed),
                        source="runs.decision",
                        sample_count=len(completed) or None,
                    ),
                    _fact(
                        "invocations",
                        "Skill invocations",
                        len(invocations) if invocations else None,
                        measured=bool(invocations),
                        source="skill_invocations",
                        sample_count=len(invocations) or None,
                    ),
                ],
            ),
        ],
        policies=[
            _block(
                "sla-observation",
                "SLA observation",
                [
                    _fact(
                        "target",
                        "Configured SLA",
                        _safe_mapping(data["capability"].sla),
                        configured=bool(data["capability"].sla),
                        source="capabilities.sla",
                    ),
                    _fact(
                        "observed_success",
                        "Observed success",
                        success,
                        measured=bool(terminal),
                        unit="%",
                        source="runs.status",
                        sample_count=len(terminal) or None,
                    ),
                ],
            ),
        ],
    )


def _capability_steer(**data: Any) -> dict[str, Any]:
    capability: Capability = data["capability"]
    runs: list[Run] = data["runs"]
    invocations: list[SkillInvocation] = data["invocations"]
    decisions: list[Decision] = data["decisions"]
    completed = [item for item in runs if item.status == "completed"]
    cost_evidence = measured_costs_by_run(invocations)
    costs = [cost_evidence[item.id][0] for item in completed if item.id in cost_evidence]
    cost_sample_count = sum(
        cost_evidence[item.id][1] for item in completed if item.id in cost_evidence
    )
    values = [
        float(item.value_estimated)
        for item in completed
        if item.value_estimated is not None
        and str(item.value_source or "unset") in {"auto", "operator"}
    ]
    total_cost = sum(costs) if costs else None
    total_value = sum(values) if values else None
    roi_cohort = measured_roi_cohort(completed, cost_evidence)
    return _facets(
        ("overview", "systems", "outcomes", "policies"),
        overview=[
            _block(
                "value",
                "Capability value",
                [
                    _fact(
                        "value",
                        "Estimated value",
                        total_value,
                        measured=bool(values),
                        source="runs.value_estimated",
                        sample_count=len(values) or None,
                    ),
                    _fact(
                        "cost",
                        "Internal cost",
                        total_cost,
                        measured=bool(costs),
                        source="skill_invocations.cost,cost_measured",
                        sample_count=cost_sample_count or None,
                    ),
                    _fact(
                        "roi",
                        "ROI",
                        roi_cohort.roi_percent,
                        measured=roi_cohort.roi_percent is not None,
                        unit="%",
                        source=(
                            "derived:runs.value_estimated,"
                            "skill_invocations.cost,cost_measured"
                        ),
                        sample_count=(
                            roi_cohort.run_count
                            if roi_cohort.roi_percent is not None
                            else None
                        ),
                        description=(
                            "Computed only across Runs with both estimated value and "
                            "explicitly measured invocation cost."
                        ),
                    ),
                ],
            ),
        ],
        systems=[
            _block(
                "value-by-system",
                "Value by System",
                [
                    _fact(
                        "systems",
                        "System contributions",
                        _system_value_rollup(data["systems"], runs, invocations),
                        measured=bool(runs),
                        source=(
                            "runs.value_estimated,"
                            "skill_invocations.cost,cost_measured"
                        ),
                        sample_count=len(runs) or None,
                    ),
                ],
            ),
        ],
        outcomes=[
            _block(
                "outcomes",
                "Outcome evidence",
                [
                    _fact(
                        "confidence",
                        "Average confidence",
                        _average(item.confidence for item in completed),
                        measured=any(item.confidence is not None for item in completed),
                        source="runs.confidence",
                        sample_count=len(
                            [item for item in completed if item.confidence is not None]
                        )
                        or None,
                    ),
                    _fact(
                        "efficiency",
                        "Average efficiency",
                        _average(item.efficiency for item in completed),
                        measured=any(item.efficiency is not None for item in completed),
                        source="runs.efficiency",
                        sample_count=len(
                            [item for item in completed if item.efficiency is not None]
                        )
                        or None,
                    ),
                    _fact(
                        "open_decisions",
                        "Open decisions",
                        [_decision_value(item) for item in decisions if item.status == "proposed"],
                        measured=bool(decisions),
                        source="decisions",
                        sample_count=len(decisions) or None,
                    ),
                ],
            ),
        ],
        policies=[
            _block(
                "steering-contract",
                "Steering contract",
                [
                    _fact(
                        "roi_model",
                        "ROI model",
                        _safe_mapping(capability.roi_model),
                        configured=bool(capability.roi_model),
                        source="capabilities.roi_model",
                    ),
                    _fact(
                        "simulation",
                        "Simulation",
                        None,
                        configured=False,
                        source="value_scenarios",
                        description=None,
                    ),
                ],
            ),
        ],
    )


def _capability_govern(**data: Any) -> dict[str, Any]:
    db: DBSession = data["db"]
    workspace: Workspace = data["workspace"]
    user: User = data["user"]
    capability: Capability = data["capability"]
    actions = _effective_actions(
        db,
        workspace,
        user,
        "capability",
        capability.id,
        ("read", "admin"),
        capability=capability.slug,
    )
    return _facets(
        ("overview", "systems", "outcomes", "policies"),
        overview=[
            _block(
                "authorization",
                "Effective authorization",
                [
                    _fact("actions", "Resolved actions", actions, source="iam.resolver"),
                ],
            )
        ],
        systems=[
            _block(
                "ownership",
                "Implementation ownership",
                [
                    _fact(
                        "systems",
                        "Governed Systems",
                        [_system_value(item) for item in data["systems"]],
                        configured=bool(data["systems"]),
                        source="systems.capability_id",
                        sample_count=len(data["systems"]) or None,
                    ),
                ],
            )
        ],
        outcomes=[
            _block(
                "decision-audit",
                "Decision audit",
                [
                    _fact(
                        "decisions",
                        "Decisions",
                        [_decision_value(item) for item in data["decisions"]],
                        restricted=bool(data["decisions_restricted"]),
                        measured=bool(data["decisions"]),
                        source="decisions",
                        sample_count=len(data["decisions"]) or None,
                    ),
                ],
            )
        ],
        policies=[
            _block(
                "policy-governance",
                "Policy governance",
                [
                    _fact(
                        "control",
                        "Control policies",
                        [_control_value(item) for item in data["control"]],
                        configured=bool(data["control"]),
                        source="control_policies",
                        sample_count=len(data["control"]) or None,
                    ),
                    _fact(
                        "adaptive",
                        "Adaptive policies",
                        [_adaptive_value(item) for item in data["adaptive"]],
                        configured=bool(data["adaptive"]),
                        source="adaptive_policies",
                        sample_count=len(data["adaptive"]) or None,
                    ),
                    _fact(
                        "audit",
                        "Audit events",
                        [_audit_value(item) for item in data["audits"]],
                        restricted=bool(data["audits_restricted"]),
                        measured=bool(data["audits"]),
                        source="audit_logs",
                        sample_count=len(data["audits"]) or None,
                    ),
                ],
            ),
        ],
    )


# Run projections -----------------------------------------------------------


def _run_build(**data: Any) -> dict[str, Any]:
    run: Run = data["run"]
    system: Optional[System] = data["system"]
    capability: Optional[Capability] = data["capability"]
    system_version: Optional[SystemVersion] = data["system_version"]
    payload_visible: bool = data["payload_visible"]
    snapshot = _mapping(run.flow_snapshot)
    nodes = [item for item in snapshot.get("nodes", []) if isinstance(item, Mapping)]
    return _facets(
        ("overview", "invocations", "payloads", "checkpoints"),
        overview=[
            _block(
                "execution-evidence",
                "Execution evidence",
                [
                    _fact(
                        "system",
                        "System reference captured on Run",
                        {"id": run.system_id} if system is not None and run.system_id else None,
                        configured=system is not None and bool(run.system_id),
                        source="runs.system_id",
                        as_of=_iso(run.started_at),
                        description="Current mutable System metadata is not execution evidence.",
                    ),
                    _fact(
                        "capability",
                        "Capability reference captured on Run",
                        {"id": run.capability_id}
                        if capability is not None and run.capability_id
                        else None,
                        configured=capability is not None and bool(run.capability_id),
                        restricted=bool(run.capability_id) and capability is None,
                        source="runs.capability_id",
                        as_of=_iso(run.started_at),
                        description="No current Capability metadata is projected as historical.",
                    ),
                    _fact(
                        "flow_snapshot",
                        "Executed flow snapshot",
                        _safe_flow_snapshot(snapshot),
                        configured=bool(snapshot),
                        source="runs.flow_snapshot",
                        as_of=_iso(run.started_at),
                    ),
                    _fact(
                        "flow_version",
                        "Flow version reference",
                        run.flow_version_id,
                        configured=bool(run.flow_version_id),
                        source="runs.flow_version_id",
                        as_of=_iso(run.started_at),
                    ),
                    _fact(
                        "configuration_snapshot",
                        "Versioned configuration snapshot",
                        _configuration_snapshot_value(system_version),
                        configured=bool(
                            system_version and system_version.configuration_snapshot
                        ),
                        source="system_versions.configuration_snapshot",
                        as_of=_iso(system_version.created_at) if system_version else None,
                    ),
                    _fact("trigger", "Trigger", run.trigger, source="runs.trigger"),
                ],
                description=(
                    "Run-persisted references and immutable snapshots only; current catalog "
                    "objects are intentionally not presented as the executed contract."
                ),
            )
        ],
        invocations=[
            _block(
                "planned-flow",
                "Executed composition",
                [
                    _fact(
                        "nodes",
                        "Snapshot nodes",
                        len(nodes) if snapshot else None,
                        configured=bool(snapshot),
                        source="runs.flow_snapshot.nodes",
                        sample_count=len(nodes) if snapshot else None,
                    ),
                    _fact(
                        "invocations",
                        "Invocation ledger",
                        [_invocation_value(item) for item in data["invocations"]],
                        measured=bool(data["invocations"]),
                        source="skill_invocations",
                        sample_count=len(data["invocations"]) or None,
                    ),
                ],
            )
        ],
        payloads=[
            _block(
                "typed-io",
                "Typed input/output",
                [
                    _fact(
                        "input",
                        "Input",
                        _safe_payload(run.input_ref),
                        restricted=not payload_visible,
                        configured=bool(run.input_ref),
                        source="runs.input_ref",
                    ),
                    _fact(
                        "output",
                        "Output",
                        _safe_payload(run.output_ref),
                        restricted=not payload_visible,
                        measured=bool(run.output_ref),
                        source="runs.output_ref",
                    ),
                ],
            )
        ],
        checkpoints=[
            _block(
                "replayability",
                "Replayability",
                [
                    _fact(
                        "snapshot",
                        "Flow snapshot",
                        _safe_flow_snapshot(snapshot),
                        restricted=not payload_visible,
                        configured=bool(snapshot),
                        source="runs.flow_snapshot",
                    ),
                    _fact(
                        "parent_run",
                        "Parent Run",
                        run.parent_run_id,
                        configured=bool(run.parent_run_id),
                        source="runs.parent_run_id",
                    ),
                    _fact(
                        "overrides",
                        "Replay overrides",
                        _safe_mapping(run.replay_overrides),
                        restricted=not payload_visible,
                        configured=bool(run.replay_overrides),
                        source="runs.replay_overrides",
                    ),
                ],
            )
        ],
    )


def _run_operate(**data: Any) -> dict[str, Any]:
    run: Run = data["run"]
    invocations: list[SkillInvocation] = data["invocations"]
    failures = [item for item in invocations if item.status == "failed" or item.error]
    measured_costs = [
        float(item.cost) for item in invocations if _invocation_cost_is_measured(item)
    ]
    total_cost = sum(measured_costs) if measured_costs else None
    return _facets(
        ("overview", "invocations", "payloads", "checkpoints"),
        overview=[
            _block(
                "runtime",
                "Runtime",
                [
                    _fact(
                        "status",
                        "Status",
                        run.status,
                        source="runs.status",
                        as_of=_iso(run.completed_at or run.started_at),
                    ),
                    _fact(
                        "duration",
                        "Duration",
                        run.duration_ms,
                        measured=run.duration_ms is not None,
                        unit="ms",
                        source="runs.duration_ms",
                        sample_count=1 if run.duration_ms is not None else None,
                    ),
                    _fact(
                        "retries",
                        "Retries",
                        run.retries,
                        measured=True,
                        source="runs.retries",
                        sample_count=1,
                    ),
                    _fact(
                        "error",
                        "Run error",
                        _safe_error_summary(run.error),
                        measured=bool(run.error),
                        source="runs.error",
                    ),
                ],
            )
        ],
        invocations=[
            _block(
                "invocation-runtime",
                "Invocation runtime",
                [
                    _fact(
                        "invocations",
                        "Invocations",
                        [_invocation_value(item) for item in invocations],
                        measured=bool(invocations),
                        source="skill_invocations",
                        sample_count=len(invocations) or None,
                    ),
                    _fact(
                        "failures",
                        "Invocation failures",
                        len(failures) if invocations else None,
                        measured=bool(invocations),
                        source="skill_invocations.status,error",
                        sample_count=len(invocations) or None,
                    ),
                    _fact(
                        "cost",
                        "Invocation cost",
                        total_cost,
                        measured=bool(measured_costs),
                        source="skill_invocations.cost,cost_measured",
                        sample_count=len(measured_costs) or None,
                    ),
                ],
            )
        ],
        payloads=[
            _block(
                "evaluation",
                "Runtime evaluation",
                [
                    _fact(
                        "latest",
                        "Latest evaluation",
                        _evaluation_value(data["evaluations"][0]) if data["evaluations"] else None,
                        measured=bool(data["evaluations"]),
                        source="evaluation_scores",
                        sample_count=len(data["evaluations"]) or None,
                    ),
                    _fact(
                        "result_held",
                        "Result held",
                        _result_held(run),
                        measured=True,
                        source="runs.status,checkpoints",
                        sample_count=1,
                    ),
                ],
            )
        ],
        checkpoints=[
            _block(
                "runtime-state",
                "Runtime state",
                [
                    _fact(
                        "checkpoints",
                        "Checkpoints",
                        _checkpoint_summaries(run.checkpoints),
                        measured=bool(run.checkpoints),
                        source="runs.checkpoints",
                        sample_count=len(run.checkpoints or []) or None,
                    ),
                    _fact(
                        "waiting_subflows",
                        "Waiting subflows",
                        _safe_waiting_subflows(run.waiting_subflows),
                        measured=bool(run.waiting_subflows),
                        source="runs.waiting_subflows",
                    ),
                ],
            )
        ],
    )


def _run_steer(**data: Any) -> dict[str, Any]:
    run: Run = data["run"]
    invocations: list[SkillInvocation] = data["invocations"]
    measured_cost, cost_sample_count = measured_cost_summary(invocations)
    value_available = (
        run.value_estimated is not None
        and str(run.value_source or "unset") in {"auto", "operator"}
    )
    outcome = {
        "decision": run.decision,
        "confidence": run.confidence,
        "value_estimated": run.value_estimated if value_available else None,
        "value_estimated_state": "available" if value_available else "not_measured",
        "cost_internal": measured_cost,
        "cost_internal_state": "available" if cost_sample_count else "not_measured",
        "cost_internal_sample_count": cost_sample_count,
        "revenue_allocated": run.revenue_allocated,
        "efficiency": run.efficiency,
        "value_source": run.value_source,
    }
    roi = (
        (float(run.value_estimated) - measured_cost) / measured_cost * 100.0
        if value_available and measured_cost
        else None
    )
    return _facets(
        ("overview", "invocations", "payloads", "checkpoints"),
        overview=[
            _block(
                "outcome",
                "Measured outcome",
                [
                    _fact(
                        "outcome",
                        "Outcome",
                        outcome,
                        measured=any(
                            outcome[key] is not None
                            for key in (
                                "decision",
                                "confidence",
                                "value_estimated",
                                "cost_internal",
                                "revenue_allocated",
                                "efficiency",
                            )
                        ),
                        source=(
                            "runs.outcome + "
                            "skill_invocations.cost,cost_measured"
                        ),
                    ),
                    _fact(
                        "roi",
                        "Run ROI",
                        roi,
                        measured=roi is not None,
                        unit="%",
                        source=(
                            "derived:runs.value_estimated,"
                            "skill_invocations.cost,cost_measured"
                        ),
                        sample_count=cost_sample_count if roi is not None else None,
                    ),
                ],
            )
        ],
        invocations=[
            _block(
                "cost-contribution",
                "Invocation contribution",
                [
                    _fact(
                        "costs",
                        "Per-Skill cost",
                        [_invocation_cost_value(item) for item in invocations],
                        measured=bool(cost_sample_count),
                        source="skill_invocations.cost,cost_measured",
                        sample_count=cost_sample_count or None,
                    ),
                ],
            )
        ],
        payloads=[
            _block(
                "decisions",
                "Decisions",
                [
                    _fact(
                        "decisions",
                        "Decision trail",
                        [_decision_value(item) for item in data["decisions"]],
                        measured=bool(data["decisions"]),
                        source="decisions",
                        sample_count=len(data["decisions"]) or None,
                    ),
                ],
            )
        ],
        checkpoints=[
            _block(
                "next-action",
                "Next action",
                [
                    _fact(
                        "pending_approval",
                        "Pending approval",
                        run.status == "hitl_pending",
                        measured=True,
                        source="runs.status",
                        sample_count=1,
                    ),
                    _fact(
                        "simulation", "Simulation", None, configured=False, source="value_scenarios"
                    ),
                ],
            )
        ],
    )


def _run_govern(**data: Any) -> dict[str, Any]:
    db: DBSession = data["db"]
    workspace: Workspace = data["workspace"]
    user: User = data["user"]
    run: Run = data["run"]
    system: Optional[System] = data["system"]
    membrane = data["membrane"]
    provenance = canonical_run_provenance(run, data["invocations"])
    actions = _effective_actions(
        db,
        workspace,
        user,
        "run",
        run.id,
        ("read", "approve", "admin"),
        owner_user_id=run.initiated_by_user_id,
        system_id=system.id if system is not None else None,
        legacy_runs=(run,),
    )
    return _facets(
        ("overview", "invocations", "payloads", "checkpoints"),
        overview=[
            _block(
                "authorization",
                "Effective authorization",
                [
                    _fact("actions", "Resolved actions", actions, source="iam.resolver"),
                ],
            )
        ],
        invocations=[
            _block(
                "runtime-policy",
                "Runtime policy",
                [
                    _fact(
                        "membrane",
                        "Membrane facets",
                        membrane.facet_states(),
                        configured=bool(membrane.configured_facets()),
                        source="control_policies.extra.membrane_spec",
                    ),
                ],
            )
        ],
        payloads=[
            _block(
                "provenance",
                "Provenance",
                [
                    _fact(
                        "artifacts",
                        "Corroborated artifact references",
                        provenance,
                        measured=bool(provenance),
                        source=(
                            "runs.output_ref._membrane_provenance + "
                            "runs.checkpoints[kind=membrane_provenance] + "
                            "skill_invocations.trace.membrane_provenance"
                        ),
                        sample_count=len(provenance) or None,
                        description=(
                            "Runtime markers agree; object bytes are not revalidated "
                            "by this read projection."
                        ),
                    ),
                ],
            )
        ],
        checkpoints=[
            _block(
                "audit",
                "Audit and approvals",
                [
                    _fact(
                        "decisions",
                        "Decisions",
                        [_decision_value(item) for item in data["decisions"]],
                        restricted=bool(data["decisions_restricted"]),
                        measured=bool(data["decisions"]),
                        source="decisions",
                        sample_count=len(data["decisions"]) or None,
                    ),
                    _fact(
                        "events",
                        "Audit events",
                        [_audit_value(item) for item in data["audits"]],
                        restricted=bool(data["audits_restricted"]),
                        measured=bool(data["audits"]),
                        source="audit_logs",
                        sample_count=len(data["audits"]) or None,
                    ),
                ],
            )
        ],
    )


# SkillInvocation projections ----------------------------------------------


def _invocation_build(**data: Any) -> dict[str, Any]:
    invocation: SkillInvocation = data["invocation"]
    skill = _invocation_snapshot_skill(invocation)
    digests = _invocation_snapshot_digests(invocation)
    snapshot_state = _invocation_snapshot_state(invocation)
    unavailable = snapshot_state == "unavailable"
    measured = snapshot_state == "available"
    return _facets(
        ("overview", "io", "runtime", "governance"),
        overview=[
            _block(
                "component",
                "Catalog component",
                [
                    _fact(
                        "skill",
                        "Executed Skill",
                        skill or None,
                        measured=measured,
                        unavailable=unavailable,
                        source="skill_invocations.execution_snapshot.skill",
                    ),
                    _fact("invocation", "Invocation", invocation.id, source="skill_invocations.id"),
                    _fact("run", "Parent Run", data["run"].id, source="skill_invocations.run_id"),
                ],
            )
        ],
        io=[
            _block(
                "contract",
                "I/O contract",
                [
                    _fact(
                        "input_contract_sha256",
                        "Input contract digest",
                        digests.get("input_contract_sha256"),
                        measured=measured,
                        unavailable=unavailable,
                        source="skill_invocations.execution_snapshot.digests",
                    ),
                    _fact(
                        "output_contract_sha256",
                        "Output contract digest",
                        digests.get("output_contract_sha256"),
                        measured=measured,
                        unavailable=unavailable,
                        source="skill_invocations.execution_snapshot.digests",
                    ),
                ],
            )
        ],
        runtime=[
            _block(
                "execution",
                "Execution contract",
                [
                    _fact(
                        "execution_sha256",
                        "Execution digest",
                        digests.get("execution_sha256"),
                        measured=measured,
                        unavailable=unavailable,
                        source="skill_invocations.execution_snapshot.digests",
                    ),
                    _fact(
                        "provider",
                        "Executed provider",
                        skill.get("provider"),
                        measured=measured,
                        unavailable=unavailable,
                        source="skill_invocations.execution_snapshot.skill.provider",
                    ),
                ],
            )
        ],
        governance=[
            _block(
                "certification",
                "Certification",
                [
                    _fact(
                        "level",
                        "Execution certification",
                        skill.get("certification_level"),
                        measured=measured,
                        unavailable=unavailable,
                        source="skill_invocations.execution_snapshot.skill.certification_level",
                    ),
                    _fact(
                        "version",
                        "Executed Skill version",
                        skill.get("version"),
                        measured=measured,
                        unavailable=unavailable,
                        source="skill_invocations.execution_snapshot.skill.version",
                    ),
                ],
            )
        ],
    )


def _invocation_operate(**data: Any) -> dict[str, Any]:
    invocation: SkillInvocation = data["invocation"]
    payload_visible: bool = data["payload_visible"]
    return _facets(
        ("overview", "io", "runtime", "governance"),
        overview=[
            _block(
                "status",
                "Invocation status",
                [
                    _fact(
                        "status",
                        "Status",
                        invocation.status,
                        source="skill_invocations.status",
                        as_of=_iso(invocation.completed_at or invocation.started_at),
                    ),
                    _fact(
                        "latency",
                        "Latency",
                        invocation.latency_ms,
                        measured=invocation.latency_ms is not None,
                        unit="ms",
                        source="skill_invocations.latency_ms",
                        sample_count=1 if invocation.latency_ms is not None else None,
                    ),
                    _fact(
                        "cost",
                        "Cost",
                        invocation.cost,
                        measured=_invocation_cost_is_measured(invocation),
                        source="skill_invocations.cost,cost_measured",
                        sample_count=1 if _invocation_cost_is_measured(invocation) else None,
                    ),
                    _fact(
                        "error",
                        "Error",
                        _safe_error_summary(invocation.error),
                        measured=bool(invocation.error),
                        source="skill_invocations.error",
                    ),
                ],
            )
        ],
        io=[
            _block(
                "observed-io",
                "Observed I/O",
                [
                    _fact(
                        "input",
                        "Input",
                        _safe_payload(invocation.input_ref),
                        restricted=not payload_visible,
                        measured=bool(invocation.input_ref),
                        source="skill_invocations.input_ref",
                    ),
                    _fact(
                        "output",
                        "Output",
                        _safe_payload(invocation.output_ref),
                        restricted=not payload_visible,
                        measured=bool(invocation.output_ref),
                        source="skill_invocations.output_ref",
                    ),
                ],
            )
        ],
        runtime=[
            _block(
                "telemetry",
                "Runtime telemetry",
                [
                    _fact(
                        "metrics",
                        "Metrics",
                        _safe_mapping(invocation.metrics),
                        measured=bool(invocation.metrics),
                        source="skill_invocations.metrics",
                    ),
                    _fact(
                        "trace",
                        "Trace",
                        _safe_trace(invocation.trace),
                        restricted=not payload_visible,
                        measured=bool(invocation.trace),
                        source="skill_invocations.trace",
                    ),
                ],
            )
        ],
        governance=[
            _block(
                "lineage",
                "Lineage",
                [
                    _fact("run", "Parent Run", data["run"].id, source="runs.id"),
                    _fact(
                        "system",
                        "System",
                        data["system"].id if data["system"] is not None else None,
                        configured=data["system"] is not None,
                        restricted=(
                            bool(data["run"].system_id)
                            and data["system"] is None
                        ),
                        source="runs.system_id",
                    ),
                ],
            )
        ],
    )


def _invocation_steer(**data: Any) -> dict[str, Any]:
    invocation: SkillInvocation = data["invocation"]
    metrics = _mapping(invocation.metrics)
    contribution = metrics.get("value_contribution")
    return _facets(
        ("overview", "io", "runtime", "governance"),
        overview=[
            _block(
                "contribution",
                "Outcome contribution",
                [
                    _fact(
                        "value",
                        "Value contribution",
                        contribution,
                        measured=contribution is not None,
                        source="skill_invocations.metrics.value_contribution",
                        sample_count=1 if contribution is not None else None,
                    ),
                    _fact(
                        "cost",
                        "Invocation cost",
                        invocation.cost,
                        measured=_invocation_cost_is_measured(invocation),
                        source="skill_invocations.cost,cost_measured",
                        sample_count=1 if _invocation_cost_is_measured(invocation) else None,
                    ),
                ],
            )
        ],
        io=[
            _block(
                "quality",
                "Output quality",
                [
                    _fact(
                        "quality",
                        "Quality",
                        metrics.get("quality"),
                        measured=metrics.get("quality") is not None,
                        source="skill_invocations.metrics.quality",
                        sample_count=1 if metrics.get("quality") is not None else None,
                    ),
                    _fact(
                        "confidence",
                        "Confidence",
                        metrics.get("confidence"),
                        measured=metrics.get("confidence") is not None,
                        source="skill_invocations.metrics.confidence",
                        sample_count=1 if metrics.get("confidence") is not None else None,
                    ),
                ],
            )
        ],
        runtime=[
            _block(
                "optimization",
                "Optimization evidence",
                [
                    _fact(
                        "latency",
                        "Latency",
                        invocation.latency_ms,
                        measured=invocation.latency_ms is not None,
                        unit="ms",
                        source="skill_invocations.latency_ms",
                        sample_count=1 if invocation.latency_ms is not None else None,
                    ),
                    _fact(
                        "recommendation", "Recommendation", None, measured=False, source="decisions"
                    ),
                ],
            )
        ],
        governance=[
            _block(
                "simulation",
                "Simulation",
                [
                    _fact("scenario", "Scenario", None, configured=False, source="value_scenarios"),
                ],
            )
        ],
    )


def _invocation_govern(**data: Any) -> dict[str, Any]:
    db: DBSession = data["db"]
    workspace: Workspace = data["workspace"]
    user: User = data["user"]
    invocation: SkillInvocation = data["invocation"]
    membrane = data["membrane"]
    payload_visible: bool = data["payload_visible"]
    actions = _effective_actions(
        db,
        workspace,
        user,
        "skill_invocation",
        invocation.id,
        ("read",),
        owner_user_id=data["run"].initiated_by_user_id,
    )
    return _facets(
        ("overview", "io", "runtime", "governance"),
        overview=[
            _block(
                "authorization",
                "Effective authorization",
                [
                    _fact("actions", "Resolved actions", actions, source="iam.resolver"),
                ],
            )
        ],
        io=[
            _block(
                "data-boundary",
                "Data boundary",
                [
                    _fact(
                        "input",
                        "Input visibility",
                        "visible" if payload_visible else None,
                        restricted=not payload_visible,
                        source="iam.resolver",
                    ),
                    _fact(
                        "output",
                        "Output visibility",
                        "visible" if payload_visible else None,
                        restricted=not payload_visible,
                        source="iam.resolver",
                    ),
                ],
            )
        ],
        runtime=[
            _block(
                "membrane",
                "Membrane",
                [
                    _fact(
                        "facets",
                        "Facet states",
                        membrane.facet_states(),
                        configured=bool(membrane.configured_facets()),
                        source="control_policies.extra.membrane_spec",
                    ),
                ],
            )
        ],
        governance=[
            _block(
                "audit",
                "Audit and provenance",
                [
                    _fact(
                        "provenance",
                        "Provenance",
                        _trace_provenance(invocation.trace),
                        measured=bool(_trace_provenance(invocation.trace)),
                        source="skill_invocations.trace.membrane_provenance",
                    ),
                    _fact(
                        "events",
                        "Audit events",
                        [_audit_value(item) for item in data["audits"]],
                        restricted=bool(data["audits_restricted"]),
                        measured=bool(data["audits"]),
                        source="audit_logs",
                        sample_count=len(data["audits"]) or None,
                    ),
                ],
            )
        ],
    )


# Shared helpers ------------------------------------------------------------


def _validate(lens: str, window: str) -> datetime:
    if lens not in OBJECT_LENSES:
        raise ValueError("lens must be build, operate, steer or govern")
    if window not in WINDOW_DAYS:
        raise ValueError("window must be 7d, 30d or 90d")
    return datetime.utcnow() - timedelta(days=WINDOW_DAYS[window])


def _projection_state_digest(
    identity: Mapping[str, Any],
    header: Mapping[str, Any],
    all_facets: Mapping[str, Any],
) -> str:
    """Fingerprint every value exposed by any lens, not sparse watermarks."""

    payload = json.dumps(
        {"identity": identity, "header": header, "facets": all_facets},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _envelope(
    *,
    workspace: Workspace,
    object_type: str,
    object_id: str,
    name: str,
    lens: str,
    window: str,
    generated_at: str,
    snapshot_values: Iterable[Any],
    identity: dict[str, Any],
    header: dict[str, Any],
    facets: dict[str, Any],
) -> dict[str, Any]:
    raw = "|".join(
        [
            workspace.id,
            object_type,
            object_id,
            window,
            *[str(value or "") for value in snapshot_values],
        ]
    )
    return {
        "schema_version": 1,
        "snapshot_id": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
        "generated_at": generated_at,
        "window": window,
        "identity": {
            "workspace_id": workspace.id,
            "object_type": object_type,
            "object_id": object_id,
            "name": name,
            **identity,
        },
        "header": header,
        "lens": lens,
        "facets": facets,
    }


def _facets(names: Iterable[str], **values: list[dict[str, Any]]) -> dict[str, Any]:
    return {name: {"blocks": values.get(name, [])} for name in names}


def _block(
    block_id: str,
    title: str,
    facts: list[dict[str, Any]],
    description: Optional[str] = None,
) -> dict[str, Any]:
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
    description: Optional[str] = None,
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
        **({"description": description} if description else {}),
    }


def _capability_header(
    capability: Capability,
    systems: list[System],
    runs: list[Run],
    invocations: list[SkillInvocation],
) -> dict[str, Any]:
    terminal = [item for item in runs if item.status in {"completed", "failed", "cancelled"}]
    completed = [item for item in terminal if item.status == "completed"]
    cost_evidence = measured_costs_by_run(invocations)
    roi_cohort = measured_roi_cohort(completed, cost_evidence)
    return {
        "tier": _fact("tier", "Tier", capability.tier, source="capabilities.tier"),
        "system_count": _fact(
            "system_count",
            "Systems",
            len(systems) if systems else None,
            configured=bool(systems),
            source="systems.capability_id",
            sample_count=len(systems) or None,
        ),
        "success_rate": _fact(
            "success_rate",
            "Success",
            len(completed) / len(terminal) * 100.0 if terminal else None,
            measured=bool(terminal),
            unit="%",
            source="runs.status",
            sample_count=len(terminal) or None,
        ),
        "roi": _fact(
            "roi",
            "ROI",
            roi_cohort.roi_percent,
            measured=roi_cohort.roi_percent is not None,
            unit="%",
            source=(
                "derived:runs.value_estimated,skill_invocations.cost,cost_measured"
            ),
            sample_count=(
                roi_cohort.run_count if roi_cohort.roi_percent is not None else None
            ),
            description=(
                "Computed only across Runs with both estimated value and explicitly "
                "measured invocation cost."
            ),
        ),
    }


def _run_header(run: Run, invocations: list[SkillInvocation]) -> dict[str, Any]:
    return {
        "status": _fact(
            "status",
            "Status",
            run.status,
            source="runs.status",
            as_of=_iso(run.completed_at or run.started_at),
        ),
        "duration": _fact(
            "duration",
            "Duration",
            run.duration_ms,
            measured=run.duration_ms is not None,
            unit="ms",
            source="runs.duration_ms",
            sample_count=1 if run.duration_ms is not None else None,
        ),
        "invocation_count": _fact(
            "invocation_count",
            "Invocations",
            len(invocations),
            measured=True,
            source="skill_invocations",
            sample_count=len(invocations),
        ),
        "confidence": _fact(
            "confidence",
            "Confidence",
            run.confidence,
            measured=run.confidence is not None,
            source="runs.confidence",
            sample_count=1 if run.confidence is not None else None,
        ),
    }


def _invocation_header(invocation: SkillInvocation) -> dict[str, Any]:
    skill = _invocation_snapshot_skill(invocation)
    snapshot_state = _invocation_snapshot_state(invocation)
    return {
        "status": _fact(
            "status",
            "Status",
            invocation.status,
            source="skill_invocations.status",
            as_of=_iso(invocation.completed_at or invocation.started_at),
        ),
        "latency": _fact(
            "latency",
            "Latency",
            invocation.latency_ms,
            measured=invocation.latency_ms is not None,
            unit="ms",
            source="skill_invocations.latency_ms",
            sample_count=1 if invocation.latency_ms is not None else None,
        ),
        "cost": _fact(
            "cost",
            "Cost",
            invocation.cost,
            measured=_invocation_cost_is_measured(invocation),
            source="skill_invocations.cost,cost_measured",
            sample_count=1 if _invocation_cost_is_measured(invocation) else None,
        ),
        "skill_version": _fact(
            "skill_version",
            "Executed Skill version",
            skill.get("version"),
            measured=snapshot_state == "available",
            unavailable=snapshot_state == "unavailable",
            source="skill_invocations.execution_snapshot.skill.version",
        ),
    }


def _visible_capability(
    db: DBSession, workspace: Workspace, capability_id: Optional[str]
) -> Optional[Capability]:
    if not capability_id:
        return None
    capability = (
        db.query(Capability)
        .filter(
            Capability.id == capability_id,
            or_(
                Capability.workspace_id == workspace.id,
                Capability.workspace_id.is_(None),
            ),
        )
        .first()
    )
    if capability is None or not capability_is_visible(capability, workspace):
        return None
    return capability


def _visible_run_parents(
    db: DBSession,
    *,
    workspace: Workspace,
    user: User,
    run: Run,
) -> tuple[Optional[System], Optional[Capability]]:
    """Resolve parent references only inside the current authorization scope."""

    system = (
        db.query(System)
        .filter(System.id == run.system_id, System.workspace_id == workspace.id)
        .first()
        if run.system_id
        else None
    )
    if system is not None and not resolve_system_read(
        db,
        system=system,
        user=user,
        workspace=workspace,
        audit_shadow_diff=False,
        audit_shadow_evidence=False,
    ).effective_allowed:
        system = None

    # ``Run.capability_id`` is the only historical capability reference. A
    # fallback through today's mutable System would silently rewrite history.
    capability = _visible_capability(db, workspace, run.capability_id)
    if capability is not None and not resolve_capability_read(
        db,
        capability=capability,
        user=user,
        workspace=workspace,
        audit_shadow_diff=False,
        audit_shadow_evidence=False,
    ).effective_allowed:
        capability = None
    return system, capability


def _run_system_version(
    db: DBSession,
    *,
    workspace: Workspace,
    run: Run,
    system: Optional[System],
) -> Optional[SystemVersion]:
    """Resolve only the immutable version explicitly linked by the Run."""

    if system is None or not run.flow_version_id:
        return None
    return (
        db.query(SystemVersion)
        .filter(
            SystemVersion.id == run.flow_version_id,
            SystemVersion.system_id == system.id,
            or_(
                SystemVersion.workspace_id == workspace.id,
                SystemVersion.workspace_id.is_(None),
            ),
        )
        .first()
    )


def _readable_systems(
    db: DBSession,
    *,
    systems: list[System],
    workspace: Workspace,
    user: User,
) -> list[System]:
    return authorized_systems(
        db,
        systems=systems,
        user=user,
        workspace=workspace,
    )


def _policies(
    db: DBSession, model: Any, workspace_id: str, scope: str, target_id: str
) -> list[Any]:
    return (
        db.query(model)
        .filter(
            model.workspace_id == workspace_id,
            model.scope == scope,
            model.target_id == target_id,
        )
        .order_by(model.updated_at.desc())
        .all()
    )


def _decisions(
    db: DBSession,
    *,
    workspace: Workspace,
    user: User,
    targets: list[str],
    since: datetime,
    visible_runs: Iterable[Run] | None = None,
) -> tuple[list[Decision], bool]:
    if not targets:
        return []
    rows = (
        db.query(Decision)
        .filter(
            Decision.workspace_id == workspace.id,
            Decision.target_id.in_(targets),
            Decision.created_at >= since,
        )
        .order_by(Decision.created_at.desc())
        .limit(100)
        .all()
    )
    visible = readable_decisions(
        db,
        decisions=rows,
        user=user,
        workspace=workspace,
        visible_runs=visible_runs,
    )
    return visible, len(visible) < len(rows)


def _audits(
    db: DBSession,
    workspace_id: str,
    *,
    ids: set[str],
    since: datetime,
) -> list[AuditLog]:
    candidates = (
        db.query(AuditLog)
        .filter(
            AuditLog.workspace_id == workspace_id,
            AuditLog.timestamp >= since,
        )
        .order_by(AuditLog.timestamp.desc())
        .limit(500)
        .all()
    )
    rows: list[AuditLog] = []
    for item in candidates:
        details = _mapping(item.details)
        if (
            item.agent_id in ids
            or item.trace_id in ids
            or any(
                str(details.get(key) or "") in ids
                for key in (
                    "capability_id",
                    "system_id",
                    "run_id",
                    "skill_invocation_id",
                    "target_id",
                )
            )
        ):
            rows.append(item)
        if len(rows) >= 50:
            break
    return rows


def _effective_actions(
    db: DBSession,
    workspace: Workspace,
    user: User,
    resource_kind: str,
    resource_id: str,
    actions: Iterable[str],
    legacy_runs: Iterable[Run] = (),
    **attrs: Any,
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for action in actions:
        resource_attrs = {
            f"{resource_kind}_id": resource_id,
            **attrs,
        }
        resolution = resolve_authorized_action(
            db,
            user=user,
            workspace=workspace,
            resource_kind=resource_kind,
            action=action,
            legacy_allowed=legacy_object_action_allowed(
                db,
                workspace=workspace,
                user=user,
                resource_kind=resource_kind,
                action=action,
                resource_attrs=resource_attrs,
                runs=legacy_runs,
            ),
            resource_attrs=resource_attrs,
            audit_shadow_diff=False,
            audit_shadow_evidence=False,
        )
        result[action] = resolution.to_dict()
    return result


def _exclude_seed_runs(runs: list[Run]) -> list[Run]:
    return [
        item
        for item in runs
        if not _is_seed_payload(item.input_ref) and not _is_seed_payload(item.output_ref)
    ]


def _is_seed_payload(value: Any) -> bool:
    return isinstance(value, Mapping) and (
        value.get("showcase_seed") is True or value.get("source") == "showcase_seed"
    )


def _system_value(system: Optional[System]) -> Optional[dict[str, Any]]:
    if system is None:
        return None
    return {
        "id": system.id,
        "name": system.name,
        "status": system.status,
        "execution_mode": system.execution_mode,
    }


def _configuration_snapshot_value(
    version: Optional[SystemVersion],
) -> Optional[dict[str, Any]]:
    if version is None or not isinstance(version.configuration_snapshot, Mapping):
        return None
    return {
        "system_version_id": version.id,
        "version_number": version.version_number,
        "configuration": scrub_projection_mapping(version.configuration_snapshot),
    }


def _system_runtime_value(system: System, runs: list[Run]) -> dict[str, Any]:
    rows = [item for item in runs if item.system_id == system.id]
    terminal = [item for item in rows if item.status in {"completed", "failed", "cancelled"}]
    completed = [item for item in terminal if item.status == "completed"]
    return {
        **(_system_value(system) or {}),
        "runs": len(rows) if rows else None,
        "success_rate": len(completed) / len(terminal) * 100.0 if terminal else None,
        "last_run_at": _iso(rows[0].started_at) if rows else None,
    }


def _system_value_rollup(
    systems: list[System],
    runs: list[Run],
    invocations: list[SkillInvocation],
) -> list[dict[str, Any]]:
    rows = []
    cost_evidence = measured_costs_by_run(invocations)
    for system in systems:
        scoped = [
            item for item in runs if item.system_id == system.id and item.status == "completed"
        ]
        costs = [cost_evidence[item.id][0] for item in scoped if item.id in cost_evidence]
        cost_sample_count = sum(
            cost_evidence[item.id][1] for item in scoped if item.id in cost_evidence
        )
        cost_run_count = len([item for item in scoped if item.id in cost_evidence])
        values = [
            float(item.value_estimated)
            for item in scoped
            if item.value_estimated is not None
            and str(item.value_source or "unset") in {"auto", "operator"}
        ]
        roi_run_count = len(
            [
                item
                for item in scoped
                if item.id in cost_evidence
                and item.value_estimated is not None
                and str(item.value_source or "unset") in {"auto", "operator"}
            ]
        )
        rows.append(
            {
                "system_id": system.id,
                "name": system.name,
                "run_count": len(scoped),
                "cost": sum(costs) if costs else None,
                "cost_sample_count": cost_sample_count,
                "cost_measured_run_count": cost_run_count,
                "cost_coverage_percent": (
                    cost_run_count / len(scoped) * 100.0 if scoped else None
                ),
                "value": sum(values) if values else None,
                "value_run_count": len(values),
                "roi_eligible_run_count": roi_run_count,
            }
        )
    return rows


def _capability_value(capability: Optional[Capability]) -> Optional[dict[str, Any]]:
    if capability is None:
        return None
    return {
        "id": capability.id,
        "slug": capability.slug,
        "name": capability.name,
        "tier": capability.tier,
    }


def _invocation_value(invocation: SkillInvocation) -> dict[str, Any]:
    cost_measured = _invocation_cost_is_measured(invocation)
    skill = _invocation_snapshot_skill(invocation)
    return {
        "id": invocation.id,
        "skill_id": skill.get("id"),
        "skill_slug": skill.get("slug"),
        "status": invocation.status,
        "latency_ms": invocation.latency_ms,
        "cost": invocation.cost if cost_measured else None,
        "cost_state": "available" if cost_measured else "not_measured",
        "execution_snapshot_state": _invocation_snapshot_state(invocation),
        "started_at": _iso(invocation.started_at),
    }


def _invocation_cost_value(invocation: SkillInvocation) -> dict[str, Any]:
    cost_measured = _invocation_cost_is_measured(invocation)
    skill = _invocation_snapshot_skill(invocation)
    return {
        "invocation_id": invocation.id,
        "skill_slug": skill.get("slug"),
        "cost": invocation.cost if cost_measured else None,
        "cost_state": "available" if cost_measured else "not_measured",
        "latency_ms": invocation.latency_ms,
    }


def _invocation_execution_snapshot(invocation: SkillInvocation) -> dict[str, Any]:
    return _mapping(getattr(invocation, "execution_snapshot", None))


def _invocation_snapshot_state(invocation: SkillInvocation) -> str:
    snapshot = _invocation_execution_snapshot(invocation)
    if not snapshot:
        return "not_measured"
    return "available" if snapshot.get("resolution") == "resolved" else "unavailable"


def _invocation_snapshot_skill(invocation: SkillInvocation) -> dict[str, Any]:
    snapshot = _invocation_execution_snapshot(invocation)
    if snapshot.get("resolution") != "resolved":
        return {}
    return _mapping(snapshot.get("skill"))


def _invocation_snapshot_digests(invocation: SkillInvocation) -> dict[str, Any]:
    snapshot = _invocation_execution_snapshot(invocation)
    if snapshot.get("resolution") != "resolved":
        return {}
    return _mapping(snapshot.get("digests"))


def _invocation_cost_is_measured(invocation: SkillInvocation) -> bool:
    return invocation_cost_is_measured(invocation)


def _decision_value(decision: Decision) -> dict[str, Any]:
    return {
        "id": decision.id,
        "scope": decision.scope,
        "target_id": decision.target_id,
        "kind": decision.kind,
        "status": decision.status,
        "title": decision.title,
        "created_at": _iso(decision.created_at),
        "approved_by": decision.approved_by,
        "approved_at": _iso(decision.approved_at),
    }


def _control_value(policy: ControlPolicy) -> dict[str, Any]:
    spec = resolve_membrane_spec(control=policy)
    return {
        "id": policy.id,
        "name": policy.name,
        "scope": policy.scope,
        "target_id": policy.target_id,
        "membrane_mode": spec.effective_mode.value,
        "membrane_facets": spec.facet_states(),
    }


def _adaptive_value(policy: AdaptivePolicy) -> dict[str, Any]:
    return {
        "id": policy.id,
        "name": policy.name,
        "enabled": bool(policy.enabled),
        "scope": policy.scope,
        "target_id": policy.target_id,
        "allowed_actions": list(policy.allowed_actions or []),
    }


def _evaluation_value(value: EvaluationScore) -> dict[str, Any]:
    return {
        "id": value.id,
        "composite_score": value.composite_score,
        "hallucination_rate": value.hallucination_rate,
        "drift_rate": value.drift_rate,
        "created_at": _iso(value.created_at),
    }


def _audit_value(value: AuditLog) -> dict[str, Any]:
    details = _mapping(value.details)
    safe = scrub_projection_mapping(
        {
            key: item
            for key, item in details.items()
            if key
            in {
                "capability_id",
                "system_id",
                "run_id",
                "skill_invocation_id",
                "fields",
                "outcome",
                "reason",
                "policy_id",
            }
        }
    )
    return {
        "id": value.id,
        "event_type": value.event_type,
        "actor": value.actor,
        "timestamp": _iso(value.timestamp),
        "severity": value.severity,
        "details": safe,
    }


def _checkpoint_summaries(value: Any) -> list[dict[str, Any]]:
    rows = []
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, Mapping):
            continue
        rows.append(
            {
                key: _jsonable(item.get(key))
                for key in ("kind", "t", "node_id", "decision_id", "decision_status", "plane")
                if item.get(key) is not None
            }
        )
    return rows


def _safe_waiting_subflows(value: Any) -> Optional[dict[str, Any]]:
    payload = _mapping(value)
    if not payload:
        return None
    allowed = {"join", "status", "pending", "completed", "failed", "cancelled", "updated_at"}
    return scrub_projection_mapping(
        {key: item for key, item in payload.items() if key in allowed}
    )


def _safe_flow_snapshot(value: Mapping[str, Any]) -> Optional[dict[str, Any]]:
    if not value:
        return None
    nodes = [item for item in value.get("nodes", []) if isinstance(item, Mapping)]
    edges = [item for item in value.get("edges", []) if isinstance(item, Mapping)]
    return {
        "schema_version": value.get("schema_version"),
        "io_mode": value.get("io_mode"),
        "node_ids": [item.get("id") for item in nodes if item.get("id")],
        "edge_count": len(edges),
        "variable_namespaces": list(value.get("variable_namespaces") or []),
    }


def _safe_payload(value: Any) -> Optional[dict[str, Any]]:
    payload = _mapping(value)
    if not payload:
        return None
    return _secret_safe_mapping(payload)


def _safe_error_summary(value: Any) -> Optional[str]:
    """Expose error presence without replaying provider payloads or secrets."""

    return "Runtime error recorded; details are restricted." if value else None


def _safe_trace(value: Any) -> Optional[dict[str, Any]]:
    trace = _mapping(value)
    if not trace:
        return None
    allowed = {
        "model",
        "provider",
        "tokens",
        "input_tokens",
        "output_tokens",
        "attempt",
        "membrane",
        "membrane_provenance",
        "retrieval_decision_trace",
    }
    return {key: _secret_safe_value(item) for key, item in trace.items() if key in allowed}


def _trace_provenance(value: Any) -> Optional[dict[str, Any]]:
    trace = _mapping(value)
    provenance = _mapping(trace.get("membrane_provenance"))
    if not provenance:
        legacy = _mapping(trace.get("membrane"))
        provenance = _mapping(legacy.get("artifact")) or legacy
    if not provenance:
        return None
    allowed = {"uri", "sha256", "size_bytes", "created_at", "enforcement_mode", "membrane_version"}
    return scrub_projection_mapping(
        {key: item for key, item in provenance.items() if key in allowed}
    )


def _result_held(run: Run) -> bool:
    return run.status == "hitl_pending" and any(
        isinstance(item, Mapping)
        and item.get("kind") == "hitl_pause"
        and item.get("membrane_egress") is True
        for item in (run.checkpoints or [])
    )


def _safe_mapping(value: Any) -> Optional[dict[str, Any]]:
    payload = _mapping(value)
    if not payload:
        return None
    return _secret_safe_mapping(payload)


def _secret_safe_mapping(value: Mapping[Any, Any]) -> dict[str, Any]:
    return scrub_projection_mapping(value)


def _secret_safe_value(value: Any) -> Any:
    return _jsonable(scrub_projection_value(value))


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _percentile(values: list[float], quantile: float) -> Optional[float]:
    if not values:
        return None
    index = max(0, min(len(values) - 1, int(round((len(values) - 1) * quantile))))
    return round(values[index], 2)


def _average(values: Iterable[Optional[float]]) -> Optional[float]:
    rows = [float(value) for value in values if value is not None]
    return round(sum(rows) / len(rows), 4) if rows else None


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
