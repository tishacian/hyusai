"""System-scoped API for the authoritative Lot 8 value loop."""
from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session as DBSession

from app.core.auth import get_current_user, get_current_workspace
from app.core.iam.roles import (
    WORKSPACE_ADMIN,
    WORKSPACE_CONTRIBUTOR,
    WORKSPACE_OWNER,
    WORKSPACE_REVIEWER,
    WORKSPACE_VIEWER,
    normalize_role_template,
)
from app.db.base import get_db
from app.models.decision import Decision
from app.models.run import Run
from app.models.system import System
from app.models.user import User
from app.models.value_loop import (
    ValueActionExecution,
    ValueMeasurement,
    ValueScenario,
    ValueSimulation,
)
from app.models.workspace import Workspace, WorkspaceMember
from app.services.decision_access import readable_decisions
from app.services.iam.decision_plane import enforce_action
from app.services.projection_integrity import scrub_projection_mapping
from app.services.run_access import resolve_run_read, run_is_visible
from app.services.value_loop import (
    CONTROL_POLICY_GUARDRAILS_PATCH_V1,
    ValueLoopConflict,
    ValueLoopError,
    ValueLoopNotFound,
    ValueLoopValidationError,
    act_value_scenario,
    approve_value_scenario,
    canonicalize_value_loop_patch,
    create_value_scenario,
    measure_value_scenario,
    simulate_value_scenario,
)
from app.services.value_loop_gate import value_loop_enabled
from app.services.value_scenario_access import readable_value_scenarios

router = APIRouter()

ALL_MEMBER_ROLES = {
    WORKSPACE_VIEWER,
    WORKSPACE_CONTRIBUTOR,
    WORKSPACE_REVIEWER,
    WORKSPACE_ADMIN,
    WORKSPACE_OWNER,
}
CREATE_ROLES = {WORKSPACE_CONTRIBUTOR, WORKSPACE_ADMIN, WORKSPACE_OWNER}
SIMULATE_ROLES = CREATE_ROLES
APPROVE_ROLES = {WORKSPACE_REVIEWER, WORKSPACE_ADMIN, WORKSPACE_OWNER}
ACT_ROLES = {WORKSPACE_ADMIN, WORKSPACE_OWNER}
MEASURE_ROLES = {
    WORKSPACE_CONTRIBUTOR,
    WORKSPACE_REVIEWER,
    WORKSPACE_ADMIN,
    WORKSPACE_OWNER,
}


class ScenarioCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_run_id: str = Field(min_length=1, max_length=36)
    objective: str = Field(min_length=1, max_length=4000)
    title: str = Field(min_length=1, max_length=255)
    rationale: dict[str, Any] = Field(default_factory=dict)


class SimulationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recommended_patch: dict[str, Any]


class ScenarioApproval(BaseModel):
    model_config = ConfigDict(extra="forbid")

    simulation_id: str = Field(min_length=1, max_length=36)


class ScenarioActuation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actuator: Literal["control_policy.guardrails.patch.v1"]
    patch: dict[str, Any]


class ScenarioMeasurement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_run_id: str | None = Field(default=None, min_length=1, max_length=36)


def _actor(user: User) -> str:
    for field in ("email", "username", "id"):
        value = str(getattr(user, field, "") or "").strip()
        if value:
            return value
    raise HTTPException(status_code=401, detail="Authenticated actor is unavailable")


def _system_or_404(db: DBSession, workspace: Workspace, system_id: str) -> System:
    system = (
        db.query(System)
        .filter(System.id == system_id, System.workspace_id == workspace.id)
        .first()
    )
    if system is None:
        raise HTTPException(status_code=404, detail="System not found")
    if not value_loop_enabled(db, workspace=workspace, system=system):
        raise HTTPException(
            status_code=404,
            detail={
                "code": "VALUE_LOOP_NOT_CONFIGURED",
                "message": "The authoritative value loop is not enabled for this System",
            },
        )
    return system


def _workspace_for_mutation(
    db: DBSession,
    workspace: Workspace,
) -> Workspace:
    """Serialize value-loop writes with membership and workspace governance.

    Membership mutations already use the Workspace row as their tenant mutex.
    Taking that same lock before resolving the System and refreshing authority
    prevents a revoked role from acting on a stale ORM membership while a
    privileged value-loop transition is waiting to start.
    """

    locked = (
        db.query(Workspace)
        .filter(Workspace.id == workspace.id)
        .with_for_update(of=Workspace)
        .populate_existing()
        .one_or_none()
    )
    if locked is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return locked


def _membership_or_403(
    db: DBSession,
    *,
    workspace: Workspace,
    user: User,
) -> tuple[WorkspaceMember, str]:
    membership = (
        db.query(WorkspaceMember)
        .filter(
            WorkspaceMember.workspace_id == workspace.id,
            WorkspaceMember.user_id == user.id,
        )
        .populate_existing()
        .first()
    )
    if membership is None:
        raise HTTPException(status_code=403, detail="Workspace membership required")
    role = normalize_role_template(membership.role_template, membership.role)
    return membership, role


def _authorize(
    db: DBSession,
    *,
    workspace: Workspace,
    system: System,
    user: User,
    action: str,
    legacy_roles: set[str],
    scenario_id: str | None = None,
) -> None:
    membership, role = _membership_or_403(db, workspace=workspace, user=user)
    # Every scenario operation is subordinate to its System. Independent
    # action rollout must not let a value-loop route bypass ``system.read``.
    enforce_action(
        db,
        user=user,
        workspace=workspace,
        membership=membership,
        resource_kind="system",
        action="read",
        legacy_allowed=True,
        resource_attrs={
            "system_id": system.id,
            "capability_id": system.capability_id,
            "scope": "value_loop",
        },
    )
    enforce_action(
        db,
        user=user,
        workspace=workspace,
        membership=membership,
        resource_kind="value_scenario",
        action=action,
        legacy_allowed=role in legacy_roles,
        resource_attrs={
            "system_id": system.id,
            "capability_id": system.capability_id,
            "scenario_id": scenario_id,
        },
    )


def _scenario_or_404(
    db: DBSession,
    *,
    workspace_id: str,
    system_id: str,
    scenario_id: str,
) -> ValueScenario:
    scenario = (
        db.query(ValueScenario)
        .filter(
            ValueScenario.id == scenario_id,
            ValueScenario.workspace_id == workspace_id,
            ValueScenario.system_id == system_id,
        )
        .first()
    )
    if scenario is None:
        raise HTTPException(status_code=404, detail="ValueScenario not found")
    return scenario


def _source_run_is_readable(
    db: DBSession,
    *,
    run: Run,
    workspace: Workspace,
    user: User,
) -> bool:
    """Apply the canonical legacy + granular Run read boundary.

    A value scenario consumes a Run's outcome as evidence. That is a read of
    the Run even though the payload is not returned directly, so it must use
    exactly the same visibility and authorization rollout as the Run APIs.
    The legacy private-run boundary remains a prerequisite in every mode;
    shadow only compares the granular candidate after that boundary succeeds.
    """

    if not run_is_visible(db, run=run, user=user, workspace=workspace):
        return False
    return resolve_run_read(
        db,
        run=run,
        user=user,
        workspace=workspace,
        legacy_allowed=True,
    ).effective_allowed


def _source_run_or_404(
    db: DBSession,
    *,
    run_id: str,
    workspace: Workspace,
    system: System,
    user: User,
) -> Run:
    """Resolve source evidence without disclosing hidden or foreign Runs."""

    run = (
        db.query(Run)
        .filter(
            Run.id == run_id,
            Run.workspace_id == workspace.id,
            Run.system_id == system.id,
        )
        .first()
    )
    if run is None or not _source_run_is_readable(
        db,
        run=run,
        workspace=workspace,
        user=user,
    ):
        raise HTTPException(status_code=404, detail="Run not found")
    return run


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def _finite_setting(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "SIMULATION_NOT_CONFIGURED",
                "message": f"System steering model has an invalid {field}",
            },
        )
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "SIMULATION_NOT_CONFIGURED",
                "message": f"System steering model has no valid {field}",
            },
        ) from exc
    if not math.isfinite(result):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "SIMULATION_NOT_CONFIGURED",
                "message": f"System steering model has an invalid {field}",
            },
        )
    return result


def _server_simulation_contract(
    *,
    system: System,
    scenario: ValueScenario,
    canonical_patch: Mapping[str, float],
) -> dict[str, Any]:
    """Derive a labelled forecast from persisted System configuration.

    The client may choose the bounded action it wants to preview, but cannot
    submit a model identity, confidence, projected result or provenance and
    have Agentium present those values as a server simulation.
    """

    settings = system.settings if isinstance(system.settings, Mapping) else {}
    raw_model = settings.get("steering_model")
    model = dict(raw_model) if isinstance(raw_model, Mapping) else {}
    version = str(model.get("version") or "").strip()
    if not version:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "SIMULATION_NOT_CONFIGURED",
                "message": "System steering model is not configured",
            },
        )
    confidence = _finite_setting(model.get("confidence"), "confidence")
    if not 0 <= confidence <= 1:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "SIMULATION_NOT_CONFIGURED",
                "message": "System steering model confidence is invalid",
            },
        )

    forecasts = model.get("forecasts")
    if not isinstance(forecasts, Mapping):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "SIMULATION_NOT_CONFIGURED",
                "message": "System steering model has no patch forecasts",
            },
        )

    required_rule_fields = {
        "minimum",
        "maximum",
        "include_maximum",
        "cost_multiplier",
        "value_multiplier",
    }
    matched_rules: list[dict[str, Any]] = []
    aggregate_cost_multiplier = 1.0
    aggregate_value_multiplier = 1.0
    for field, patch_value in sorted(canonical_patch.items()):
        raw_rules = forecasts.get(field)
        if not isinstance(raw_rules, list) or not raw_rules:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "SIMULATION_NOT_CONFIGURED",
                    "message": f"System steering model has no forecast for patch.{field}",
                },
            )
        matches: list[dict[str, Any]] = []
        for index, raw_rule in enumerate(raw_rules):
            if not isinstance(raw_rule, Mapping) or set(raw_rule) != required_rule_fields:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "SIMULATION_NOT_CONFIGURED",
                        "message": f"System steering forecast {field}[{index}] is invalid",
                    },
                )
            include_maximum = raw_rule.get("include_maximum")
            if not isinstance(include_maximum, bool):
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "SIMULATION_NOT_CONFIGURED",
                        "message": f"System steering forecast {field}[{index}] has invalid bounds",
                    },
                )
            minimum = _finite_setting(raw_rule.get("minimum"), f"forecasts.{field}[{index}].minimum")
            maximum = _finite_setting(raw_rule.get("maximum"), f"forecasts.{field}[{index}].maximum")
            cost_multiplier = _finite_setting(
                raw_rule.get("cost_multiplier"),
                f"forecasts.{field}[{index}].cost_multiplier",
            )
            value_multiplier = _finite_setting(
                raw_rule.get("value_multiplier"),
                f"forecasts.{field}[{index}].value_multiplier",
            )
            if (
                minimum > maximum
                or cost_multiplier < 0
                or value_multiplier < 0
            ):
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "SIMULATION_NOT_CONFIGURED",
                        "message": f"System steering forecast {field}[{index}] has invalid bounds",
                    },
                )
            in_bounds = minimum <= patch_value < maximum
            if include_maximum and patch_value == maximum:
                in_bounds = True
            if in_bounds:
                matches.append(
                    {
                        "field": field,
                        "minimum": minimum,
                        "maximum": maximum,
                        "include_maximum": include_maximum,
                        "cost_multiplier": cost_multiplier,
                        "value_multiplier": value_multiplier,
                    }
                )
        if len(matches) != 1:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "SIMULATION_NOT_CONFIGURED",
                    "message": (
                        f"System steering model must match exactly one forecast for patch.{field}"
                    ),
                },
            )
        matched = matches[0]
        matched_rules.append(matched)
        aggregate_cost_multiplier *= matched["cost_multiplier"]
        aggregate_value_multiplier *= matched["value_multiplier"]

    canonical_patch_payload = dict(sorted(canonical_patch.items()))
    patch_sha256 = hashlib.sha256(
        json.dumps(
            canonical_patch_payload,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()

    baseline = scenario.baseline_outcome if isinstance(scenario.baseline_outcome, Mapping) else {}

    def projected(field: str, multiplier: float) -> float | None:
        value = baseline.get(field)
        if value is None or isinstance(value, bool):
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number * multiplier if math.isfinite(number) else None

    measured_value = baseline.get("value_source") in {"auto", "operator"}
    projected_value = (
        projected("value", aggregate_value_multiplier) if measured_value else None
    )
    projected_cost = projected("cost", aggregate_cost_multiplier)
    assumptions = model.get("assumptions")
    if not isinstance(assumptions, list) or any(not isinstance(item, str) for item in assumptions):
        assumptions = []
    return {
        "model": f"system-steering:{version}",
        "assumptions": {
            "configured": assumptions,
            "canonical_patch": canonical_patch_payload,
            "patch_sha256": patch_sha256,
            "matched_forecasts": matched_rules,
            "aggregate_cost_multiplier": aggregate_cost_multiplier,
            "aggregate_value_multiplier": aggregate_value_multiplier,
        },
        "projected_outcome": {
            "value": projected_value,
            "value_state": "available" if projected_value is not None else "not_measured",
            "cost": projected_cost,
            "cost_state": "available" if projected_cost is not None else "not_measured",
        },
        "provenance": {
            "scope": "system",
            "system_id": system.id,
            "source_run_id": scenario.source_run_id,
            "model_source": "systems.settings.steering_model",
            "model_version": version,
            "canonical_patch": canonical_patch_payload,
            "patch_sha256": patch_sha256,
            "matched_forecasts": matched_rules,
        },
        "confidence": confidence,
    }


def _serialize_simulation(row: ValueSimulation) -> dict[str, Any]:
    return {
        "id": row.id,
        "scenario_id": row.scenario_id,
        "system_id": row.system_id,
        "status": row.status,
        "evidence_type": "simulation",
        "model": row.model,
        "assumptions": scrub_projection_mapping(row.assumptions or {}),
        "projected_outcome": scrub_projection_mapping(row.projected_outcome or {}),
        "recommended_action": row.recommended_action or {},
        "provenance": scrub_projection_mapping(row.provenance or {}),
        "confidence": row.confidence,
        "generated_at": _iso(row.generated_at),
    }


def _serialize_action(row: ValueActionExecution) -> dict[str, Any]:
    return {
        "id": row.id,
        "scenario_id": row.scenario_id,
        "system_id": row.system_id,
        "simulation_id": row.simulation_id,
        "actuator": row.actuator,
        "status": row.status,
        "changed_fields": sorted((row.patch or {}).keys()),
        "executed_by": row.executed_by,
        "executed_at": _iso(row.executed_at),
    }


def _serialize_measurement(row: ValueMeasurement) -> dict[str, Any]:
    return {
        "id": row.id,
        "scenario_id": row.scenario_id,
        "system_id": row.system_id,
        "action_execution_id": row.action_execution_id,
        "simulation_id": row.simulation_id,
        "source_run_id": row.source_run_id,
        "status": row.status,
        "reason": row.reason,
        "evidence_type": "run" if row.source_run_id else None,
        "baseline_outcome": scrub_projection_mapping(row.baseline_outcome or {}),
        "observed_outcome": (
            scrub_projection_mapping(row.observed_outcome)
            if isinstance(row.observed_outcome, Mapping)
            else None
        ),
        "delta": (
            scrub_projection_mapping(row.delta) if isinstance(row.delta, Mapping) else None
        ),
        "forecast_delta": (
            scrub_projection_mapping(row.forecast_delta)
            if isinstance(row.forecast_delta, Mapping)
            else None
        ),
        "assumption_verdict": row.assumption_verdict,
        "assumption_evaluation": scrub_projection_mapping(
            row.assumption_evaluation or {}
        ),
        "measured_at": _iso(row.measured_at),
    }


_DECISION_UNSET = object()


def _serialize_scenario(
    db: DBSession,
    row: ValueScenario,
    *,
    decision_override: Decision | None | object = _DECISION_UNSET,
    decision_state: str | None = None,
) -> dict[str, Any]:
    decision = (
        db.query(Decision)
        .filter(Decision.workspace_id == row.workspace_id, Decision.scenario_id == row.id)
        .first()
        if decision_override is _DECISION_UNSET
        else decision_override
    )
    simulations = (
        db.query(ValueSimulation)
        .filter(
            ValueSimulation.workspace_id == row.workspace_id,
            ValueSimulation.scenario_id == row.id,
        )
        .order_by(ValueSimulation.generated_at.asc(), ValueSimulation.id.asc())
        .all()
    )
    action = (
        db.query(ValueActionExecution)
        .filter(
            ValueActionExecution.workspace_id == row.workspace_id,
            ValueActionExecution.scenario_id == row.id,
        )
        .first()
    )
    measurements = (
        db.query(ValueMeasurement)
        .filter(
            ValueMeasurement.workspace_id == row.workspace_id,
            ValueMeasurement.scenario_id == row.id,
        )
        .order_by(ValueMeasurement.measured_at.asc(), ValueMeasurement.id.asc())
        .all()
    )
    payload = {
        "id": row.id,
        "workspace_id": row.workspace_id,
        "system_id": row.system_id,
        "source_run_id": row.source_run_id,
        "status": row.status,
        "objective": row.objective,
        "baseline_outcome": scrub_projection_mapping(row.baseline_outcome or {}),
        "approved_simulation_id": row.approved_simulation_id,
        "approved_by": row.approved_by,
        "approved_at": _iso(row.approved_at),
        "acted_at": _iso(row.acted_at),
        "measured_at": _iso(row.measured_at),
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
        "decision": (
            {
                "id": decision.id,
                "status": decision.status,
                "title": decision.title,
                "rationale": scrub_projection_mapping(decision.rationale or {}),
            }
            if decision is not None
            else None
        ),
        "simulations": [_serialize_simulation(item) for item in simulations],
        "action": _serialize_action(action) if action is not None else None,
        "measurements": [_serialize_measurement(item) for item in measurements],
    }
    if decision_state is not None:
        payload["decision_state"] = decision_state
    return payload


def _raise_value_loop_error(exc: ValueLoopError) -> None:
    if isinstance(exc, ValueLoopNotFound):
        status = 404
    elif isinstance(exc, ValueLoopConflict):
        status = 409
    elif isinstance(exc, ValueLoopValidationError):
        status = 422
    else:
        status = 500
    raise HTTPException(
        status_code=status,
        detail={"code": exc.code, "message": str(exc)},
    ) from exc


@router.get("/{system_id}/value-loop")
async def get_system_value_loop(
    system_id: str,
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
) -> dict[str, Any]:
    system = _system_or_404(db, workspace, system_id)
    _authorize(
        db,
        workspace=workspace,
        system=system,
        user=user,
        action="read",
        legacy_roles=ALL_MEMBER_ROLES,
    )
    raw_rows = (
        db.query(ValueScenario)
        .filter(
            ValueScenario.workspace_id == workspace.id,
            ValueScenario.system_id == system.id,
        )
        .order_by(ValueScenario.created_at.desc(), ValueScenario.id.desc())
        .all()
    )
    rows = readable_value_scenarios(
        db,
        scenarios=raw_rows,
        user=user,
        workspace=workspace,
    )
    scenario_ids = [row.id for row in rows]
    raw_decisions = (
        db.query(Decision)
        .filter(
            Decision.workspace_id == workspace.id,
            Decision.scenario_id.in_(scenario_ids),
        )
        .order_by(Decision.created_at.desc(), Decision.id.desc())
        .all()
        if scenario_ids
        else []
    )
    visible_decisions = readable_decisions(
        db,
        decisions=raw_decisions,
        user=user,
        workspace=workspace,
    )
    raw_by_scenario = {
        row.scenario_id: row for row in raw_decisions if row.scenario_id
    }
    visible_by_scenario = {
        row.scenario_id: row for row in visible_decisions if row.scenario_id
    }
    return {
        "schema_version": 1,
        "system_id": system.id,
        "actuator": CONTROL_POLICY_GUARDRAILS_PATCH_V1,
        "state": (
            "restricted" if raw_rows and not rows else "available" if rows else "not_configured"
        ),
        "items": [
            _serialize_scenario(
                db,
                row,
                decision_override=visible_by_scenario.get(row.id),
                decision_state=(
                    "available"
                    if row.id in visible_by_scenario
                    else "restricted"
                    if row.id in raw_by_scenario
                    else "not_configured"
                ),
            )
            for row in rows
        ],
    }


@router.post("/{system_id}/value-loop/scenarios", status_code=201)
async def create_system_value_scenario(
    system_id: str,
    body: ScenarioCreate,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=1, max_length=160),
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
) -> dict[str, Any]:
    workspace = _workspace_for_mutation(db, workspace)
    system = _system_or_404(db, workspace, system_id)
    _authorize(
        db,
        workspace=workspace,
        system=system,
        user=user,
        action="create",
        legacy_roles=CREATE_ROLES,
    )
    _source_run_or_404(
        db,
        run_id=body.source_run_id,
        workspace=workspace,
        system=system,
        user=user,
    )
    try:
        scenario, _decision = create_value_scenario(
            db,
            workspace_id=workspace.id,
            system_id=system.id,
            source_run_id=body.source_run_id,
            objective=body.objective,
            title=body.title,
            rationale=body.rationale,
            actor=_actor(user),
            idempotency_key=idempotency_key,
        )
    except ValueLoopError as exc:
        _raise_value_loop_error(exc)
    return _serialize_scenario(db, scenario)


@router.post("/{system_id}/value-loop/scenarios/{scenario_id}/simulate", status_code=201)
async def simulate_system_value_scenario(
    system_id: str,
    scenario_id: str,
    body: SimulationCreate,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=1, max_length=160),
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
) -> dict[str, Any]:
    workspace = _workspace_for_mutation(db, workspace)
    system = _system_or_404(db, workspace, system_id)
    scenario = _scenario_or_404(
        db,
        workspace_id=workspace.id,
        system_id=system.id,
        scenario_id=scenario_id,
    )
    _authorize(
        db,
        workspace=workspace,
        system=system,
        user=user,
        action="simulate",
        legacy_roles=SIMULATE_ROLES,
        scenario_id=scenario_id,
    )
    try:
        canonical_patch = canonicalize_value_loop_patch(body.recommended_patch)
        simulation_contract = _server_simulation_contract(
            system=system,
            scenario=scenario,
            canonical_patch=canonical_patch,
        )
        simulation = simulate_value_scenario(
            db,
            workspace_id=workspace.id,
            scenario_id=scenario_id,
            model=simulation_contract["model"],
            assumptions=simulation_contract["assumptions"],
            projected_outcome=simulation_contract["projected_outcome"],
            provenance=simulation_contract["provenance"],
            confidence=simulation_contract["confidence"],
            recommended_patch=canonical_patch,
            actor=_actor(user),
            idempotency_key=idempotency_key,
        )
    except ValueLoopError as exc:
        _raise_value_loop_error(exc)
    return _serialize_simulation(simulation)


@router.post("/{system_id}/value-loop/scenarios/{scenario_id}/approve")
async def approve_system_value_scenario(
    system_id: str,
    scenario_id: str,
    body: ScenarioApproval,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=1, max_length=160),
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
) -> dict[str, Any]:
    workspace = _workspace_for_mutation(db, workspace)
    system = _system_or_404(db, workspace, system_id)
    _scenario_or_404(
        db,
        workspace_id=workspace.id,
        system_id=system.id,
        scenario_id=scenario_id,
    )
    _authorize(
        db,
        workspace=workspace,
        system=system,
        user=user,
        action="approve",
        legacy_roles=APPROVE_ROLES,
        scenario_id=scenario_id,
    )
    try:
        scenario = approve_value_scenario(
            db,
            workspace_id=workspace.id,
            scenario_id=scenario_id,
            simulation_id=body.simulation_id,
            actor=_actor(user),
            idempotency_key=idempotency_key,
        )
    except ValueLoopError as exc:
        _raise_value_loop_error(exc)
    return _serialize_scenario(db, scenario)


@router.post("/{system_id}/value-loop/scenarios/{scenario_id}/act", status_code=201)
async def act_on_system_value_scenario(
    system_id: str,
    scenario_id: str,
    body: ScenarioActuation,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=1, max_length=160),
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
) -> dict[str, Any]:
    workspace = _workspace_for_mutation(db, workspace)
    system = _system_or_404(db, workspace, system_id)
    _scenario_or_404(
        db,
        workspace_id=workspace.id,
        system_id=system.id,
        scenario_id=scenario_id,
    )
    _authorize(
        db,
        workspace=workspace,
        system=system,
        user=user,
        action="act",
        legacy_roles=ACT_ROLES,
        scenario_id=scenario_id,
    )
    try:
        action = act_value_scenario(
            db,
            workspace_id=workspace.id,
            scenario_id=scenario_id,
            actuator=body.actuator,
            patch=body.patch,
            actor=_actor(user),
            idempotency_key=idempotency_key,
        )
    except ValueLoopError as exc:
        _raise_value_loop_error(exc)
    return _serialize_action(action)


@router.post("/{system_id}/value-loop/scenarios/{scenario_id}/measure", status_code=201)
async def measure_system_value_scenario(
    system_id: str,
    scenario_id: str,
    body: ScenarioMeasurement,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=1, max_length=160),
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
) -> dict[str, Any]:
    workspace = _workspace_for_mutation(db, workspace)
    system = _system_or_404(db, workspace, system_id)
    _scenario_or_404(
        db,
        workspace_id=workspace.id,
        system_id=system.id,
        scenario_id=scenario_id,
    )
    _authorize(
        db,
        workspace=workspace,
        system=system,
        user=user,
        action="measure",
        legacy_roles=MEASURE_ROLES,
        scenario_id=scenario_id,
    )
    authorized_source_run_id: str | None = None
    if body.source_run_id is not None:
        authorized_source_run_id = _source_run_or_404(
            db,
            run_id=body.source_run_id,
            workspace=workspace,
            system=system,
            user=user,
        ).id
    try:
        measurement = measure_value_scenario(
            db,
            workspace_id=workspace.id,
            scenario_id=scenario_id,
            source_run_id=body.source_run_id,
            actor=_actor(user),
            idempotency_key=idempotency_key,
            source_run_is_authorized=(
                (lambda run: run.id == authorized_source_run_id)
                if authorized_source_run_id is not None
                else lambda run: _source_run_is_readable(
                    db,
                    run=run,
                    workspace=workspace,
                    user=user,
                )
            ),
        )
    except ValueLoopError as exc:
        _raise_value_loop_error(exc)
    return _serialize_measurement(measurement)


__all__ = ["router"]
