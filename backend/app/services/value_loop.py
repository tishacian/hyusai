"""Authoritative System value loop.

This service is the only writer for the Lot-8 sequence:

    Outcome -> Decision -> Simulate -> Approve -> Act -> Measure

Each public function owns its transaction, locks the scenario before a state
transition, claims a workspace-global idempotency receipt and writes its audit
row in the same transaction.  It intentionally exposes no generic patch
executor: the sole actuator is the bounded ControlPolicy guardrail patch.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any, NoReturn
from uuid import uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession

from app.models.audit import AuditLog
from app.models.decision import Decision
from app.models.policy import ControlPolicy
from app.models.run import Run
from app.models.system import System
from app.models.value_loop import (
    ValueActionExecution,
    ValueLoopOperation,
    ValueMeasurement,
    ValueScenario,
    ValueSimulation,
)
from app.models.workspace import Workspace
from app.services import value_loop_gate
from app.services.control_policy_snapshot import (
    control_policy_execution_contract,
    validated_control_policy_execution_contract,
)
from app.services.membrane.spec import EnforcementMode, MembraneSpec
from app.services.run_outcome_provenance import (
    baseline_run_exclusion_reason,
    is_canary_authored_operator_outcome,
    run_measurement_provenance,
)
from app.services.value_loop_contract import CONTROL_POLICY_GUARDRAILS_PATCH_V1
from app.services.value_loop_gate import record_authorized_policy_transition

PATCH_FIELDS = (
    "max_cost_per_decision",
    "max_latency_ms",
    "mandatory_hitl_if_confidence_below",
)
MEASURED_VALUE_SOURCES = ("auto", "operator")
SIMULATION_CONTRACT_VERSION = 1


class ValueLoopError(RuntimeError):
    """Base error with a stable code suitable for a future HTTP router."""

    code = "value_loop_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code:
            self.code = code


class ValueLoopNotFound(ValueLoopError):  # noqa: N818 - public API
    code = "not_found"


class ValueLoopConflict(ValueLoopError):  # noqa: N818 - public API
    code = "conflict"


class ValueLoopValidationError(ValueLoopError):
    code = "invalid_request"


def _canonical_json(payload: Mapping[str, Any]) -> str:
    try:
        return json.dumps(
            dict(payload),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ValueLoopValidationError("request must be canonical JSON") from exc


def _request_sha256(operation: str, payload: Mapping[str, Any]) -> str:
    body = {"operation": operation, "payload": dict(payload)}
    return hashlib.sha256(_canonical_json(body).encode("utf-8")).hexdigest()


def _required_text(value: Any, name: str, *, maximum: int) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueLoopValidationError(f"{name} is required")
    if len(text) > maximum:
        raise ValueLoopValidationError(f"{name} exceeds {maximum} characters")
    return text


def _find_operation_receipt(
    db: DBSession,
    *,
    workspace_id: str,
    idempotency_key: str,
    operation: str,
    request_sha256: str,
) -> ValueLoopOperation | None:
    key = _required_text(idempotency_key, "idempotency_key", maximum=160)
    existing = (
        db.query(ValueLoopOperation)
        .filter(
            ValueLoopOperation.workspace_id == workspace_id,
            ValueLoopOperation.idempotency_key == key,
        )
        .first()
    )
    if existing is None:
        return None
    if existing.operation != operation or existing.request_sha256 != request_sha256:
        raise ValueLoopConflict(
            "idempotency key was already used for a different request",
            code="idempotency_conflict",
        )
    if not existing.result_type or not existing.result_id:
        raise ValueLoopConflict(
            "idempotent request is still incomplete",
            code="idempotency_incomplete",
        )
    return existing


def _claim_operation_receipt(
    db: DBSession,
    *,
    workspace_id: str,
    idempotency_key: str,
    operation: str,
    request_sha256: str,
) -> ValueLoopOperation:
    """Claim a command only after its complete transition validation."""

    key = _required_text(idempotency_key, "idempotency_key", maximum=160)
    existing = _find_operation_receipt(
        db,
        workspace_id=workspace_id,
        idempotency_key=idempotency_key,
        operation=operation,
        request_sha256=request_sha256,
    )
    if existing is not None:
        # The scenario lock serializes same-scenario transitions.  Reaching
        # this branch means a different aggregate claimed the global key while
        # validation ran, so the caller must retry to consume its result.
        raise ValueLoopConflict(
            "idempotent request completed concurrently",
            code="concurrent_transition",
        )

    receipt = ValueLoopOperation(
        id=str(uuid4()),
        workspace_id=workspace_id,
        idempotency_key=key,
        request_sha256=request_sha256,
        operation=operation,
    )
    db.add(receipt)
    # All transition, ownership and policy checks have completed at this point.
    # The unique constraint is the final authority for concurrent requests.
    db.flush()
    return receipt


def _finish_receipt(
    receipt: ValueLoopOperation,
    *,
    result_type: str,
    result_id: str,
) -> None:
    receipt.result_type = result_type
    receipt.result_id = result_id


def _audit(
    db: DBSession,
    *,
    workspace_id: str,
    event_type: str,
    actor: str,
    details: Mapping[str, Any],
    timestamp: datetime | None = None,
) -> AuditLog:
    """Write a mandatory audit row in the caller's transaction.

    Unlike the application's best-effort audit helper, this deliberately lets
    flush failures propagate.  No value-loop state or actuator mutation can be
    committed without its matching audit event.
    """

    row = AuditLog(
        id=str(uuid4()),
        workspace_id=workspace_id,
        timestamp=timestamp or datetime.utcnow(),
        event_type=event_type,
        actor=_required_text(actor, "actor", maximum=255),
        details=dict(details),
        severity="info",
    )
    db.add(row)
    db.flush()
    return row


def _rollback_and_raise(db: DBSession, exc: Exception) -> NoReturn:
    db.rollback()
    if isinstance(exc, ValueLoopError):
        raise exc
    if isinstance(exc, IntegrityError):
        raise ValueLoopConflict(
            "concurrent value-loop transition conflicted",
            code="concurrent_transition",
        ) from exc
    raise exc


def _workspace_for_update(db: DBSession, workspace_id: str) -> Workspace:
    """Acquire the tenant mutex and replace any stale identity-map state."""

    row = (
        db.query(Workspace)
        .filter(Workspace.id == workspace_id)
        .populate_existing()
        .with_for_update(of=Workspace)
        .one_or_none()
    )
    if row is None:
        raise ValueLoopNotFound("Workspace not found")
    return row


def _system_for_update(db: DBSession, workspace_id: str, system_id: str) -> System:
    row = (
        db.query(System)
        .filter(System.id == system_id, System.workspace_id == workspace_id)
        .populate_existing()
        .with_for_update(of=System)
        .one_or_none()
    )
    if row is None:
        raise ValueLoopNotFound("System not found")
    return row


def _scenario_for_update(
    db: DBSession,
    workspace_id: str,
    scenario_id: str,
) -> ValueScenario:
    row = (
        db.query(ValueScenario)
        .filter(
            ValueScenario.id == scenario_id,
            ValueScenario.workspace_id == workspace_id,
        )
        .populate_existing()
        .with_for_update(of=ValueScenario)
        .one_or_none()
    )
    if row is None:
        raise ValueLoopNotFound("ValueScenario not found")
    return row


def _decision_for_update(
    db: DBSession,
    workspace_id: str,
    scenario_id: str,
) -> Decision:
    row = (
        db.query(Decision)
        .filter(
            Decision.workspace_id == workspace_id,
            Decision.scenario_id == scenario_id,
        )
        .populate_existing()
        .with_for_update(of=Decision)
        .one_or_none()
    )
    if row is None:
        raise ValueLoopConflict("ValueScenario has no authoritative Decision")
    return row


def _run_outcome(db: DBSession, run: Run) -> dict[str, Any]:
    outcome = {
        "source_type": "run",
        "run_id": run.id,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "decision": run.decision,
        "confidence": run.confidence,
        "value": run.value_estimated,
        "cost": run.cost_internal,
        "revenue": run.revenue_allocated,
        "efficiency": run.efficiency,
        "value_source": run.value_source or "unset",
    }
    policy_contract = _run_policy_contract(run)
    if policy_contract is not None:
        outcome["control_policy"] = policy_contract
    measurement_provenance = run_measurement_provenance(run, db=db)
    if measurement_provenance is not None:
        outcome["measurement_provenance"] = measurement_provenance
    return outcome


def _run_policy_contract(run: Run) -> dict[str, Any] | None:
    input_ref = run.input_ref if isinstance(run.input_ref, Mapping) else {}
    execution = input_ref.get("execution")
    if not isinstance(execution, Mapping):
        return None
    return validated_control_policy_execution_contract(execution.get("control_policy"))


def _action_policy_contract(action: ValueActionExecution) -> dict[str, Any]:
    after_state = action.after_state if isinstance(action.after_state, Mapping) else {}
    contract = validated_control_policy_execution_contract(
        after_state.get("_control_policy"),
        policy_id=action.control_policy_id,
    )
    if contract is None:
        raise ValueLoopConflict(
            "action execution has no valid post-actuation ControlPolicy identity"
        )
    return contract


def _finite_number(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise ValueLoopValidationError(f"{name} must be a finite number")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueLoopValidationError(f"{name} must be a finite number") from exc
    if not math.isfinite(parsed):
        raise ValueLoopValidationError(f"{name} must be a finite number")
    return parsed


def _canonical_patch(patch: Mapping[str, Any]) -> dict[str, float]:
    if not isinstance(patch, Mapping) or not patch:
        raise ValueLoopValidationError("guardrail patch must be a non-empty object")
    unknown = sorted(set(str(key) for key in patch) - set(PATCH_FIELDS))
    if unknown:
        raise ValueLoopValidationError(f"unsupported guardrail fields: {', '.join(unknown)}")
    result = {str(field): _finite_number(value, f"patch.{field}") for field, value in patch.items()}
    if any(result[field] < 0 for field in result if field != "mandatory_hitl_if_confidence_below"):
        raise ValueLoopValidationError("cost and latency guardrails must be non-negative")
    threshold = result.get("mandatory_hitl_if_confidence_below")
    if threshold is not None and not 0 <= threshold <= 1:
        raise ValueLoopValidationError("mandatory_hitl_if_confidence_below must be between 0 and 1")
    return result


def _simulation_not_configured(message: str) -> NoReturn:
    raise ValueLoopConflict(message, code="SIMULATION_NOT_CONFIGURED")


def _finite_steering_setting(value: Any, field: str) -> float:
    if isinstance(value, bool):
        _simulation_not_configured(
            f"System steering model has an invalid {field}"
        )
    try:
        result = float(value)
    except (TypeError, ValueError):
        _simulation_not_configured(
            f"System steering model has no valid {field}"
        )
    if not math.isfinite(result):
        _simulation_not_configured(
            f"System steering model has an invalid {field}"
        )
    return result


def _derive_simulation_contract(
    *,
    system: System,
    scenario: ValueScenario,
    canonical_patch: Mapping[str, float],
) -> dict[str, Any]:
    """Derive the only trusted forecast contract from locked server state."""

    settings = system.settings if isinstance(system.settings, Mapping) else {}
    raw_model = settings.get("steering_model")
    model = dict(raw_model) if isinstance(raw_model, Mapping) else {}
    version = str(model.get("version") or "").strip()
    if not version:
        _simulation_not_configured("System steering model is not configured")
    confidence = _finite_steering_setting(model.get("confidence"), "confidence")
    if not 0 <= confidence <= 1:
        _simulation_not_configured("System steering model confidence is invalid")

    forecasts = model.get("forecasts")
    if not isinstance(forecasts, Mapping):
        _simulation_not_configured(
            "System steering model has no patch forecasts"
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
            _simulation_not_configured(
                f"System steering model has no forecast for patch.{field}"
            )
        matches: list[dict[str, Any]] = []
        for index, raw_rule in enumerate(raw_rules):
            if not isinstance(raw_rule, Mapping) or set(raw_rule) != required_rule_fields:
                _simulation_not_configured(
                    f"System steering forecast {field}[{index}] is invalid"
                )
            include_maximum = raw_rule.get("include_maximum")
            if not isinstance(include_maximum, bool):
                _simulation_not_configured(
                    f"System steering forecast {field}[{index}] has invalid bounds"
                )
            minimum = _finite_steering_setting(
                raw_rule.get("minimum"),
                f"forecasts.{field}[{index}].minimum",
            )
            maximum = _finite_steering_setting(
                raw_rule.get("maximum"),
                f"forecasts.{field}[{index}].maximum",
            )
            cost_multiplier = _finite_steering_setting(
                raw_rule.get("cost_multiplier"),
                f"forecasts.{field}[{index}].cost_multiplier",
            )
            value_multiplier = _finite_steering_setting(
                raw_rule.get("value_multiplier"),
                f"forecasts.{field}[{index}].value_multiplier",
            )
            if minimum > maximum or cost_multiplier < 0 or value_multiplier < 0:
                _simulation_not_configured(
                    f"System steering forecast {field}[{index}] has invalid bounds"
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
            _simulation_not_configured(
                f"System steering model must match exactly one forecast for patch.{field}"
            )
        matched = matches[0]
        matched_rules.append(matched)
        aggregate_cost_multiplier *= matched["cost_multiplier"]
        aggregate_value_multiplier *= matched["value_multiplier"]

    canonical_patch_payload = dict(sorted(canonical_patch.items()))
    patch_sha256 = hashlib.sha256(
        _canonical_json(canonical_patch_payload).encode("utf-8")
    ).hexdigest()
    baseline = (
        scenario.baseline_outcome
        if isinstance(scenario.baseline_outcome, Mapping)
        else {}
    )

    def projected(field: str, multiplier: float) -> float | None:
        value = baseline.get(field)
        if value is None or isinstance(value, bool):
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number * multiplier if math.isfinite(number) else None

    measured_value = baseline.get("value_source") in MEASURED_VALUE_SOURCES
    projected_value = (
        projected("value", aggregate_value_multiplier) if measured_value else None
    )
    projected_cost = projected("cost", aggregate_cost_multiplier)
    configured_assumptions = model.get("assumptions")
    if not isinstance(configured_assumptions, list) or any(
        not isinstance(item, str) for item in configured_assumptions
    ):
        configured_assumptions = []
    return {
        "model": f"system-steering:{version}",
        "assumptions": {
            "configured": configured_assumptions,
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
            "evidence_type": "simulation",
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


def _canonical_simulation_snapshot(
    simulation: ValueSimulation,
) -> tuple[dict[str, Any], str]:
    """Return the exact content-addressed ValueSimulation approval contract."""

    if simulation.generated_at is None:
        raise ValueLoopConflict("ValueSimulation has no generation timestamp")
    mappings: dict[str, dict[str, Any]] = {}
    for field in (
        "assumptions",
        "projected_outcome",
        "recommended_action",
        "provenance",
    ):
        value = getattr(simulation, field)
        if not isinstance(value, Mapping):
            raise ValueLoopConflict(f"ValueSimulation {field} is invalid")
        mappings[field] = dict(value)
    confidence = _finite_number(simulation.confidence, "simulation.confidence")
    if not 0 <= confidence <= 1:
        raise ValueLoopConflict("ValueSimulation confidence is invalid")
    contract = {
        "schema_version": SIMULATION_CONTRACT_VERSION,
        "id": simulation.id,
        "workspace_id": simulation.workspace_id,
        "system_id": simulation.system_id,
        "scenario_id": simulation.scenario_id,
        "operation_id": simulation.operation_id,
        "status": simulation.status,
        "evidence_type": "simulation",
        "model": simulation.model,
        "assumptions": mappings["assumptions"],
        "projected_outcome": mappings["projected_outcome"],
        "recommended_action": mappings["recommended_action"],
        "provenance": mappings["provenance"],
        "confidence": confidence,
        "generated_at": simulation.generated_at.isoformat(),
    }
    canonical = _canonical_json(contract)
    snapshot = json.loads(canonical)
    return snapshot, hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _approved_simulation_snapshot(
    scenario: ValueScenario,
    simulation: ValueSimulation,
) -> dict[str, Any]:
    """Verify the approval pin and current simulation are byte-for-byte equal."""

    pinned = scenario.approved_simulation_snapshot
    pinned_sha256 = str(scenario.approved_simulation_content_sha256 or "")
    if not isinstance(pinned, Mapping) or len(pinned_sha256) != 64:
        raise ValueLoopConflict(
            "approved simulation has no immutable contract pin",
            code="approved_simulation_unpinned",
        )
    try:
        int(pinned_sha256, 16)
        pinned_canonical = _canonical_json(pinned)
        pinned_contract_sha256 = hashlib.sha256(
            pinned_canonical.encode("utf-8")
        ).hexdigest()
        current, current_sha256 = _canonical_simulation_snapshot(simulation)
    except (TypeError, ValueError, ValueLoopError) as exc:
        raise ValueLoopConflict(
            "approved simulation contract changed after approval",
            code="approved_simulation_changed",
        ) from exc
    if (
        pinned_sha256 != pinned_contract_sha256
        or pinned_sha256 != current_sha256
        or pinned_canonical != _canonical_json(current)
    ):
        raise ValueLoopConflict(
            "approved simulation contract changed after approval",
            code="approved_simulation_changed",
        )
    return current


def _explicit_membrane_allows(control: ControlPolicy, actuator: str) -> None:
    extra = control.extra if isinstance(control.extra, Mapping) else {}
    raw = extra.get("membrane_spec")
    if not isinstance(raw, Mapping) or int(raw.get("version") or 0) != 2:
        raise ValueLoopConflict(
            "an explicit MembraneSpec v2 is required for value actuation",
            code="actuator_not_configured",
        )
    try:
        parsed = MembraneSpec.from_dict(raw, authoritative=True)
    except (TypeError, ValueError) as exc:
        raise ValueLoopConflict(
            "the explicit MembraneSpec v2 is invalid",
            code="actuator_not_configured",
        ) from exc
    if parsed.effective_mode is not EnforcementMode.ENFORCE:
        raise ValueLoopConflict(
            "value actuation requires MembraneSpec v2 enforce mode",
            code="actuator_not_enforced",
        )
    allowed = parsed.capabilities.allowed_actions
    if actuator not in allowed:
        raise ValueLoopConflict(
            "MembraneSpec does not explicitly allow this actuator",
            code="actuator_not_allowed",
        )


def _configured_bounds(system: System, patch: Mapping[str, float]) -> None:
    settings = system.settings if isinstance(system.settings, Mapping) else {}
    value_loop = settings.get("value_loop")
    actuators = value_loop.get("actuators") if isinstance(value_loop, Mapping) else None
    config = (
        actuators.get(CONTROL_POLICY_GUARDRAILS_PATCH_V1)
        if isinstance(actuators, Mapping)
        else None
    )
    if not isinstance(config, Mapping) or config.get("enabled") is not True:
        raise ValueLoopConflict(
            "System has not explicitly enabled the value actuator",
            code="actuator_not_configured",
        )
    fields = config.get("fields")
    if not isinstance(fields, Mapping):
        raise ValueLoopConflict(
            "System actuator field bounds are not configured",
            code="actuator_not_configured",
        )

    for field, value in patch.items():
        bounds = fields.get(field)
        if not isinstance(bounds, Mapping) or "min" not in bounds or "max" not in bounds:
            raise ValueLoopConflict(
                f"System actuator has no explicit bounds for {field}",
                code="actuator_not_configured",
            )
        minimum = _finite_number(bounds.get("min"), f"fields.{field}.min")
        maximum = _finite_number(bounds.get("max"), f"fields.{field}.max")
        if minimum > maximum:
            raise ValueLoopValidationError(f"invalid configured bounds for {field}")
        if field in {"max_cost_per_decision", "max_latency_ms"} and minimum < 0:
            raise ValueLoopValidationError(f"configured minimum for {field} cannot be negative")
        if field == "mandatory_hitl_if_confidence_below" and not (0 <= minimum <= maximum <= 1):
            raise ValueLoopValidationError(
                "configured HITL confidence bounds must remain between 0 and 1"
            )
        if not minimum <= value <= maximum:
            raise ValueLoopValidationError(f"patch.{field} is outside the System-configured bounds")


def _control_policy_for_update(
    db: DBSession,
    *,
    workspace_id: str,
    system: System,
) -> ControlPolicy | None:
    if not system.control_policy_id:
        return None
    return (
        db.query(ControlPolicy)
        .filter(
            ControlPolicy.id == system.control_policy_id,
            ControlPolicy.workspace_id == workspace_id,
            ControlPolicy.scope == "system",
            ControlPolicy.target_id == system.id,
        )
        .populate_existing()
        .with_for_update(of=ControlPolicy)
        .one_or_none()
    )


def _scenario_system_id(
    db: DBSession,
    *,
    workspace_id: str,
    scenario_id: str,
) -> str:
    """Resolve the aggregate owner without consulting an ORM identity entry.

    The Workspace mutex is acquired before this lookup.  The scalar projection
    deliberately bypasses SQLAlchemy's identity map; the row itself is locked
    only after the stable tenant/System/ControlPolicy authority order.
    """

    row = (
        db.query(ValueScenario.system_id)
        .filter(
            ValueScenario.id == scenario_id,
            ValueScenario.workspace_id == workspace_id,
        )
        .one_or_none()
    )
    if row is None:
        raise ValueLoopNotFound("ValueScenario not found")
    return str(row[0])


def _authority_for_scenario_update(
    db: DBSession,
    *,
    workspace_id: str,
    scenario_id: str,
) -> tuple[Workspace, System, ControlPolicy | None]:
    """Lock mutable authority in one global order before aggregate rows.

    Rollout/admin mutations use the same tenant -> System -> ControlPolicy
    order.  Returning a nullable policy is intentional: a completed command
    may still replay its immutable idempotency receipt after later authority
    removal.  New commands call ``_validate_locked_authority`` and fail closed.
    """

    workspace = _workspace_for_update(db, workspace_id)
    system_id = _scenario_system_id(
        db,
        workspace_id=workspace_id,
        scenario_id=scenario_id,
    )
    system = _system_for_update(db, workspace_id, system_id)
    policy = _control_policy_for_update(
        db,
        workspace_id=workspace_id,
        system=system,
    )
    return workspace, system, policy


def _runtime_gate_is_authoritative(
    *,
    workspace: Workspace,
    system: System,
) -> bool:
    """Identify a rollout that has entered (or left) executable runtime.

    A prepared-only System is deliberately not executable through HTTP, but
    rollout tooling must be able to create its first behavioural proof before
    activation.  Once a proof window, activation or deactivation exists, the
    authoritative gate remains mandatory even when the feature is switched
    off; this prevents a concurrent rollback from being interpreted as an
    unmanaged service call.
    """

    workspace_settings = (
        workspace.settings if isinstance(workspace.settings, Mapping) else {}
    )
    features = workspace_settings.get("features")
    feature_enabled = bool(
        isinstance(features, Mapping)
        and features.get(value_loop_gate.FEATURE_KEY) is True
    )
    system_settings = system.settings if isinstance(system.settings, Mapping) else {}
    state = system_settings.get(value_loop_gate.ROLLOUT_STATE_KEY)
    if not isinstance(state, Mapping):
        return feature_enabled
    return bool(
        feature_enabled
        or isinstance(state.get("proof_window"), Mapping)
        or state.get("activations")
        or state.get("deactivations")
    )


def _validate_locked_authority(
    db: DBSession,
    *,
    workspace: Workspace,
    system: System,
    control: ControlPolicy | None,
    actuator: str,
    patch: Mapping[str, float],
    expected_policy: Mapping[str, Any] | None = None,
) -> None:
    """Revalidate current rollout, binding and actuator while locks are held."""

    if actuator != CONTROL_POLICY_GUARDRAILS_PATCH_V1:
        raise ValueLoopValidationError("unsupported value actuator")
    if control is None:
        raise ValueLoopConflict(
            "System ControlPolicy must be explicitly scoped to this System",
            code="actuator_not_configured",
        )
    if system.control_policy_id != control.id:
        raise ValueLoopConflict(
            "System ControlPolicy binding changed while acquiring authority",
            code="actuator_not_configured",
        )
    _explicit_membrane_allows(control, actuator)
    _configured_bounds(system, patch)
    if _runtime_gate_is_authoritative(
        workspace=workspace,
        system=system,
    ) and not value_loop_gate.value_loop_enabled(
        db,
        workspace=workspace,
        system=system,
    ):
        raise ValueLoopConflict(
            "the authoritative value-loop rollout gate is closed",
            code="value_loop_not_enabled",
        )
    if expected_policy is not None:
        current = control_policy_execution_contract(control)
        expected = validated_control_policy_execution_contract(expected_policy)
        if expected is None or current != expected:
            raise ValueLoopConflict(
                "ControlPolicy changed after the approved action",
                code="control_policy_changed",
            )


def _load_idempotent_result(
    db: DBSession,
    receipt: ValueLoopOperation,
    model: type[Any],
) -> Any:
    expected_types = {
        ValueScenario: "value_scenario",
        ValueSimulation: "value_simulation",
        ValueActionExecution: "value_action_execution",
        ValueMeasurement: "value_measurement",
    }
    if receipt.result_type != expected_types.get(model):
        raise ValueLoopConflict("idempotency receipt has an invalid result type")
    result = (
        db.query(model)
        .filter(
            model.id == receipt.result_id,
            model.workspace_id == receipt.workspace_id,
        )
        .first()
    )
    if result is None:
        raise ValueLoopConflict("idempotency receipt points to a missing result")
    db.commit()
    return result


def create_value_scenario(
    db: DBSession,
    *,
    workspace_id: str,
    system_id: str,
    source_run_id: str,
    objective: str,
    title: str,
    rationale: Mapping[str, Any],
    actor: str,
    idempotency_key: str,
) -> tuple[ValueScenario, Decision]:
    """Capture a real Run Outcome and create its proposed Decision atomically."""

    request = {
        "workspace_id": workspace_id,
        "system_id": system_id,
        "source_run_id": source_run_id,
        "objective": _required_text(objective, "objective", maximum=4000),
        "title": _required_text(title, "title", maximum=255),
        "rationale": dict(rationale),
        "actor": _required_text(actor, "actor", maximum=255),
    }
    request_hash = _request_sha256("scenario.create", request)
    try:
        _workspace_for_update(db, workspace_id)
        _system_for_update(db, workspace_id, system_id)
        source = (
            db.query(Run)
            .filter(
                Run.id == source_run_id,
                Run.workspace_id == workspace_id,
                Run.system_id == system_id,
            )
            .populate_existing()
            .with_for_update(of=Run)
            .one_or_none()
        )
        if source is None:
            raise ValueLoopNotFound("baseline Run not found")
        if source.status != "completed" or source.completed_at is None:
            raise ValueLoopValidationError("baseline Run must be completed")
        exclusion_reason = baseline_run_exclusion_reason(source)
        if exclusion_reason is not None:
            raise ValueLoopValidationError(
                "baseline Run is not independent runtime evidence",
                code=exclusion_reason,
            )
        baseline_provenance = run_measurement_provenance(source, db=db)
        if (
            not isinstance(baseline_provenance, Mapping)
            or baseline_provenance.get("source") != "runtime_auto"
        ):
            raise ValueLoopValidationError(
                "baseline Run must contain server runtime provenance",
                code="baseline_not_measured",
            )
        baseline_outcome = _run_outcome(db, source)
        if not _is_measured_outcome(baseline_outcome):
            raise ValueLoopValidationError(
                "baseline Run must contain a measured value",
                code="baseline_not_measured",
            )

        existing = _find_operation_receipt(
            db,
            workspace_id=workspace_id,
            idempotency_key=idempotency_key,
            operation="scenario.create",
            request_sha256=request_hash,
        )
        if existing is not None:
            scenario = _load_idempotent_result(db, existing, ValueScenario)
            decision = (
                db.query(Decision)
                .filter(
                    Decision.workspace_id == workspace_id,
                    Decision.scenario_id == scenario.id,
                )
                .one()
            )
            return scenario, decision
        receipt = _claim_operation_receipt(
            db,
            workspace_id=workspace_id,
            idempotency_key=idempotency_key,
            operation="scenario.create",
            request_sha256=request_hash,
        )

        scenario = ValueScenario(
            id=str(uuid4()),
            workspace_id=workspace_id,
            system_id=system_id,
            source_run_id=source.id,
            operation_id=receipt.id,
            status="decision_proposed",
            objective=request["objective"],
            baseline_outcome=baseline_outcome,
        )
        db.add(scenario)
        db.flush()
        decision = Decision(
            id=str(uuid4()),
            workspace_id=workspace_id,
            scenario_id=scenario.id,
            scope="system",
            target_id=system_id,
            kind="value_loop",
            status="proposed",
            title=request["title"],
            rationale=request["rationale"],
            impact_estimate={"state": "not_simulated"},
            notes="",
        )
        db.add(decision)
        _finish_receipt(receipt, result_type="value_scenario", result_id=scenario.id)
        _audit(
            db,
            workspace_id=workspace_id,
            event_type="value_loop.scenario.created",
            actor=request["actor"],
            details={
                "scenario_id": scenario.id,
                "decision_id": decision.id,
                "system_id": system_id,
                "source_run_id": source.id,
                "request_sha256": request_hash,
            },
        )
        db.commit()
        db.refresh(scenario)
        db.refresh(decision)
        return scenario, decision
    except Exception as exc:  # noqa: BLE001 - transaction boundary
        _rollback_and_raise(db, exc)


def simulate_value_scenario(
    db: DBSession,
    *,
    workspace_id: str,
    scenario_id: str,
    recommended_patch: Mapping[str, Any],
    actor: str,
    idempotency_key: str,
) -> ValueSimulation:
    """Derive and persist a labelled forecast from locked System state."""

    patch = _canonical_patch(recommended_patch)
    request = {
        "workspace_id": workspace_id,
        "scenario_id": scenario_id,
        "recommended_patch": patch,
        "actor": _required_text(actor, "actor", maximum=255),
    }
    request_hash = _request_sha256("simulate", request)
    try:
        workspace, system, control = _authority_for_scenario_update(
            db,
            workspace_id=workspace_id,
            scenario_id=scenario_id,
        )
        scenario = _scenario_for_update(db, workspace_id, scenario_id)
        if scenario.system_id != system.id:
            raise ValueLoopConflict("ValueScenario changed System while acquiring locks")
        existing = _find_operation_receipt(
            db,
            workspace_id=workspace_id,
            idempotency_key=idempotency_key,
            operation="simulate",
            request_sha256=request_hash,
        )
        if existing is not None:
            return _load_idempotent_result(db, existing, ValueSimulation)
        if scenario.status not in {"decision_proposed", "simulated"}:
            raise ValueLoopConflict(f"cannot simulate a {scenario.status} scenario")
        decision = _decision_for_update(db, workspace_id, scenario.id)
        if decision.status != "proposed":
            raise ValueLoopConflict("authoritative Decision is not proposed")
        _validate_locked_authority(
            db,
            workspace=workspace,
            system=system,
            control=control,
            actuator=CONTROL_POLICY_GUARDRAILS_PATCH_V1,
            patch=patch,
        )
        simulation_contract = _derive_simulation_contract(
            system=system,
            scenario=scenario,
            canonical_patch=patch,
        )
        receipt = _claim_operation_receipt(
            db,
            workspace_id=workspace_id,
            idempotency_key=idempotency_key,
            operation="simulate",
            request_sha256=request_hash,
        )

        simulation = ValueSimulation(
            id=str(uuid4()),
            workspace_id=workspace_id,
            system_id=scenario.system_id,
            scenario_id=scenario.id,
            operation_id=receipt.id,
            status="available",
            model=simulation_contract["model"],
            assumptions=simulation_contract["assumptions"],
            projected_outcome=simulation_contract["projected_outcome"],
            recommended_action={
                "actuator": CONTROL_POLICY_GUARDRAILS_PATCH_V1,
                "patch": patch,
            },
            provenance=simulation_contract["provenance"],
            confidence=simulation_contract["confidence"],
        )
        db.add(simulation)
        scenario.status = "simulated"
        _finish_receipt(receipt, result_type="value_simulation", result_id=simulation.id)
        _audit(
            db,
            workspace_id=workspace_id,
            event_type="value_loop.simulation.created",
            actor=request["actor"],
            details={
                "scenario_id": scenario.id,
                "simulation_id": simulation.id,
                "system_id": scenario.system_id,
                "model": simulation_contract["model"],
                "actuator": CONTROL_POLICY_GUARDRAILS_PATCH_V1,
                "patch_fields": sorted(patch),
                "request_sha256": request_hash,
                "evidence_type": "simulation",
            },
        )
        db.commit()
        db.refresh(simulation)
        return simulation
    except Exception as exc:  # noqa: BLE001 - transaction boundary
        _rollback_and_raise(db, exc)


def approve_value_scenario(
    db: DBSession,
    *,
    workspace_id: str,
    scenario_id: str,
    simulation_id: str,
    actor: str,
    idempotency_key: str,
) -> ValueScenario:
    """Approve one immutable simulation; approval itself performs no action."""

    request = {
        "workspace_id": workspace_id,
        "scenario_id": scenario_id,
        "simulation_id": simulation_id,
        "actor": _required_text(actor, "actor", maximum=255),
    }
    request_hash = _request_sha256("approve", request)
    try:
        workspace, system, control = _authority_for_scenario_update(
            db,
            workspace_id=workspace_id,
            scenario_id=scenario_id,
        )
        scenario = _scenario_for_update(db, workspace_id, scenario_id)
        if scenario.system_id != system.id:
            raise ValueLoopConflict("ValueScenario changed System while acquiring locks")
        existing = _find_operation_receipt(
            db,
            workspace_id=workspace_id,
            idempotency_key=idempotency_key,
            operation="approve",
            request_sha256=request_hash,
        )
        if existing is not None:
            return _load_idempotent_result(db, existing, ValueScenario)
        if scenario.status != "simulated":
            raise ValueLoopConflict(f"cannot approve a {scenario.status} scenario")
        simulation = (
            db.query(ValueSimulation)
            .filter(
                ValueSimulation.id == simulation_id,
                ValueSimulation.workspace_id == workspace_id,
                ValueSimulation.scenario_id == scenario.id,
                ValueSimulation.status == "available",
            )
            .populate_existing()
            .with_for_update(of=ValueSimulation)
            .one_or_none()
        )
        if simulation is None:
            raise ValueLoopNotFound("ValueSimulation not found")
        decision = _decision_for_update(db, workspace_id, scenario.id)
        if decision.status != "proposed":
            raise ValueLoopConflict("authoritative Decision is not proposed")
        recommended = simulation.recommended_action or {}
        actuator = recommended.get("actuator")
        if actuator != CONTROL_POLICY_GUARDRAILS_PATCH_V1:
            raise ValueLoopConflict(
                "ValueSimulation has no supported actuator",
                code="actuator_not_configured",
            )
        simulation_patch = _canonical_patch(recommended.get("patch") or {})
        _validate_locked_authority(
            db,
            workspace=workspace,
            system=system,
            control=control,
            actuator=actuator,
            patch=simulation_patch,
        )
        approved_snapshot, approved_sha256 = _canonical_simulation_snapshot(
            simulation
        )
        receipt = _claim_operation_receipt(
            db,
            workspace_id=workspace_id,
            idempotency_key=idempotency_key,
            operation="approve",
            request_sha256=request_hash,
        )

        now = datetime.utcnow()
        scenario.status = "approved"
        scenario.approved_simulation_id = simulation.id
        scenario.approved_simulation_content_sha256 = approved_sha256
        scenario.approved_simulation_snapshot = approved_snapshot
        scenario.approval_operation_id = receipt.id
        scenario.approved_by = request["actor"]
        scenario.approved_at = now
        decision.status = "accepted"
        decision.approved_by = request["actor"]
        decision.approved_at = now
        decision.impact_estimate = {
            "evidence_type": "simulation",
            "simulation_id": simulation.id,
            "projected_outcome": dict(approved_snapshot["projected_outcome"]),
            "confidence": approved_snapshot["confidence"],
            "simulation_content_sha256": approved_sha256,
        }
        _finish_receipt(receipt, result_type="value_scenario", result_id=scenario.id)
        _audit(
            db,
            workspace_id=workspace_id,
            event_type="value_loop.scenario.approved",
            actor=request["actor"],
            details={
                "scenario_id": scenario.id,
                "decision_id": decision.id,
                "simulation_id": simulation.id,
                "simulation_content_sha256": approved_sha256,
                "system_id": scenario.system_id,
                "request_sha256": request_hash,
            },
        )
        db.commit()
        db.refresh(scenario)
        return scenario
    except Exception as exc:  # noqa: BLE001 - transaction boundary
        _rollback_and_raise(db, exc)


def act_value_scenario(
    db: DBSession,
    *,
    workspace_id: str,
    scenario_id: str,
    actuator: str,
    patch: Mapping[str, Any],
    actor: str,
    idempotency_key: str,
) -> ValueActionExecution:
    """Execute the approved bounded ControlPolicy patch exactly once."""

    canonical_patch = _canonical_patch(patch)
    request = {
        "workspace_id": workspace_id,
        "scenario_id": scenario_id,
        "actuator": actuator,
        "patch": canonical_patch,
        "actor": _required_text(actor, "actor", maximum=255),
    }
    request_hash = _request_sha256("act", request)
    try:
        workspace, system, control = _authority_for_scenario_update(
            db,
            workspace_id=workspace_id,
            scenario_id=scenario_id,
        )
        scenario = _scenario_for_update(db, workspace_id, scenario_id)
        if scenario.system_id != system.id:
            raise ValueLoopConflict("ValueScenario changed System while acquiring locks")
        existing = _find_operation_receipt(
            db,
            workspace_id=workspace_id,
            idempotency_key=idempotency_key,
            operation="act",
            request_sha256=request_hash,
        )
        if existing is not None:
            return _load_idempotent_result(db, existing, ValueActionExecution)
        if scenario.status != "approved" or not scenario.approved_simulation_id:
            raise ValueLoopConflict(f"cannot act on a {scenario.status} scenario")
        simulation = (
            db.query(ValueSimulation)
            .filter(
                ValueSimulation.id == scenario.approved_simulation_id,
                ValueSimulation.workspace_id == workspace_id,
                ValueSimulation.scenario_id == scenario.id,
                ValueSimulation.status == "available",
            )
            .populate_existing()
            .with_for_update(of=ValueSimulation)
            .one_or_none()
        )
        if simulation is None:
            raise ValueLoopConflict("approved simulation is unavailable")
        approved_contract = _approved_simulation_snapshot(scenario, simulation)
        recommended = approved_contract["recommended_action"]
        expected_actuator = recommended.get("actuator")
        expected_patch = _canonical_patch(recommended.get("patch") or {})
        if actuator != expected_actuator or canonical_patch != expected_patch:
            raise ValueLoopConflict(
                "actuation must exactly match the approved simulation",
                code="approved_action_mismatch",
            )
        decision = _decision_for_update(db, workspace_id, scenario.id)
        if decision.status != "accepted":
            raise ValueLoopConflict("authoritative Decision is not accepted")
        _validate_locked_authority(
            db,
            workspace=workspace,
            system=system,
            control=control,
            actuator=actuator,
            patch=canonical_patch,
        )
        assert control is not None  # narrowed by the fail-closed validator
        receipt = _claim_operation_receipt(
            db,
            workspace_id=workspace_id,
            idempotency_key=idempotency_key,
            operation="act",
            request_sha256=request_hash,
        )

        before = {field: getattr(control, field) for field in canonical_patch}
        if all(before[field] == value for field, value in canonical_patch.items()):
            raise ValueLoopConflict(
                "actuation patch does not change the ControlPolicy",
                code="actuation_no_effect",
            )
        before_contract = control_policy_execution_contract(control)
        after = dict(before)
        after.update(canonical_patch)
        for field, value in canonical_patch.items():
            setattr(control, field, value)
        after_contract = control_policy_execution_contract(control)
        now = datetime.utcnow()
        action = ValueActionExecution(
            id=str(uuid4()),
            workspace_id=workspace_id,
            system_id=scenario.system_id,
            scenario_id=scenario.id,
            simulation_id=simulation.id,
            control_policy_id=control.id,
            operation_id=receipt.id,
            actuator=actuator,
            status="succeeded",
            request_sha256=request_hash,
            patch=canonical_patch,
            before_state={**before, "_control_policy": before_contract},
            after_state={**after, "_control_policy": after_contract},
            executed_by=request["actor"],
            executed_at=now,
        )
        db.add(action)
        db.flush()
        scenario.status = "acted"
        scenario.acted_at = now
        decision.status = "applied"
        decision.applied_at = now
        decision.applied_by = request["actor"]
        decision.applied_patch = {
            "actuator": actuator,
            "fields": sorted(canonical_patch),
            "execution_id": action.id,
            "control_policy_revision": after_contract["revision"],
            "control_policy_sha256": after_contract["sha256"],
        }
        _finish_receipt(receipt, result_type="value_action_execution", result_id=action.id)
        action_audit = _audit(
            db,
            workspace_id=workspace_id,
            event_type="value_loop.action.executed",
            actor=request["actor"],
            timestamp=now,
            details={
                "scenario_id": scenario.id,
                "decision_id": decision.id,
                "simulation_id": simulation.id,
                "simulation_content_sha256": (
                    scenario.approved_simulation_content_sha256
                ),
                "action_execution_id": action.id,
                "system_id": scenario.system_id,
                "control_policy_id": control.id,
                "control_policy_revision": after_contract["revision"],
                "control_policy_sha256": after_contract["sha256"],
                "actuator": actuator,
                "changed_fields": sorted(canonical_patch),
                "request_sha256": request_hash,
            },
        )
        record_authorized_policy_transition(
            db,
            system,
            before=before_contract,
            after=after_contract,
            action_execution_id=action.id,
            scenario_id=scenario.id,
            actor=request["actor"],
            audit_id=action_audit.id,
            request_sha256=request_hash,
            transitioned_at=now,
        )
        db.commit()
        db.refresh(action)
        return action
    except Exception as exc:  # noqa: BLE001 - transaction boundary
        _rollback_and_raise(db, exc)


def _valid_observed_run(
    run: Run,
    *,
    workspace_id: str,
    system_id: str,
    acted_at: datetime,
    expected_policy: Mapping[str, Any],
) -> None:
    if run.workspace_id != workspace_id or run.system_id != system_id:
        raise ValueLoopNotFound("post-action Run not found")
    if run.status != "completed" or run.completed_at is None:
        raise ValueLoopValidationError("measurement Run must be completed")
    if run.started_at is None or run.started_at < acted_at or run.completed_at < acted_at:
        raise ValueLoopValidationError("measurement Run must execute after actuation")
    if _run_policy_contract(run) != dict(expected_policy):
        raise ValueLoopValidationError(
            "measurement Run did not execute the post-actuation ControlPolicy"
        )


def _is_measured_outcome(outcome: Mapping[str, Any]) -> bool:
    value_source = outcome.get("value_source")
    expected_provenance = {
        "auto": "runtime_auto",
        "operator": "operator_override",
    }.get(value_source)
    provenance = outcome.get("measurement_provenance")
    if (
        value_source not in MEASURED_VALUE_SOURCES
        or not isinstance(provenance, Mapping)
        or provenance.get("source") != expected_provenance
        or not str(provenance.get("artifact_ref") or "").startswith("sha256:")
    ):
        return False
    value = outcome.get("value")
    if isinstance(value, bool):
        return False
    try:
        return value is not None and math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _measurement_delta(
    baseline: Mapping[str, Any],
    observed: Mapping[str, Any],
) -> dict[str, float]:
    result = {"value": float(observed["value"]) - float(baseline["value"])}
    for key in ("cost", "confidence", "efficiency"):
        left = baseline.get(key)
        right = observed.get(key)
        if left is None or right is None or isinstance(left, bool) or isinstance(right, bool):
            continue
        try:
            left_number = float(left)
            right_number = float(right)
        except (TypeError, ValueError):
            continue
        if math.isfinite(left_number) and math.isfinite(right_number):
            result[key] = right_number - left_number
    return result


def _forecast_evaluation(
    *,
    simulation: ValueSimulation,
    observed: Mapping[str, Any] | None,
    measurement_status: str,
    reason: str | None,
) -> tuple[dict[str, float] | None, str, dict[str, Any]]:
    """Compare observed evidence with the approved forecast without claiming causality.

    The v1 steering model currently forecasts value and cost.  The verdict is
    therefore intentionally directional: value-like metrics must meet or
    exceed the forecast while cost must meet or stay below it.  Qualitative
    assumptions remain attached to the evaluation, but are never represented
    as independently proven by one post-action Run.
    """

    declared = (
        dict(simulation.assumptions)
        if isinstance(simulation.assumptions, Mapping)
        else {}
    )
    projected = (
        simulation.projected_outcome
        if isinstance(simulation.projected_outcome, Mapping)
        else {}
    )
    criteria: list[dict[str, Any]] = []
    forecast_delta: dict[str, float] = {}
    relations = {
        "value": "at_least",
        "revenue": "at_least",
        "confidence": "at_least",
        "efficiency": "at_least",
        "cost": "at_most",
    }
    if measurement_status == "measured" and isinstance(observed, Mapping):
        for metric, relation in relations.items():
            expected = projected.get(metric)
            actual = observed.get(metric)
            if (
                expected is None
                or actual is None
                or isinstance(expected, bool)
                or isinstance(actual, bool)
            ):
                continue
            try:
                expected_number = float(expected)
                actual_number = float(actual)
            except (TypeError, ValueError):
                continue
            if not (math.isfinite(expected_number) and math.isfinite(actual_number)):
                continue
            delta = actual_number - expected_number
            forecast_delta[metric] = delta
            met = (
                actual_number >= expected_number
                if relation == "at_least"
                else actual_number <= expected_number
            )
            criteria.append(
                {
                    "metric": metric,
                    "relation": relation,
                    "forecast": expected_number,
                    "observed": actual_number,
                    "delta": delta,
                    "met": met,
                }
            )

    if not criteria:
        verdict = "not_evaluable"
    elif all(item["met"] for item in criteria):
        verdict = "confirmed"
    elif any(item["met"] for item in criteria):
        verdict = "partially_confirmed"
    else:
        verdict = "not_confirmed"
    evaluation = {
        "schema_version": 1,
        "method": "directional_forecast_v1",
        "verdict": verdict,
        "causality": "not_established",
        "declared_assumptions": declared,
        "criteria": criteria,
        "reason": reason if verdict == "not_evaluable" else None,
    }
    return (forecast_delta or None), verdict, evaluation


def measure_value_scenario(
    db: DBSession,
    *,
    workspace_id: str,
    scenario_id: str,
    actor: str,
    idempotency_key: str,
    source_run_id: str | None = None,
    source_run_is_authorized: Callable[[Run], bool] | None = None,
) -> ValueMeasurement:
    """Measure from a completed post-actuation Run, or persist not_measured.

    When no comparable sample exists, the explicit ``not_measured`` record is
    returned and the scenario remains ``acted``.  A later command with a new
    idempotency key may measure a subsequently completed Run.
    """

    request = {
        "workspace_id": workspace_id,
        "scenario_id": scenario_id,
        "source_run_id": source_run_id,
        "actor": _required_text(actor, "actor", maximum=255),
    }
    request_hash = _request_sha256("measure", request)
    try:
        workspace, system, control = _authority_for_scenario_update(
            db,
            workspace_id=workspace_id,
            scenario_id=scenario_id,
        )
        scenario = _scenario_for_update(db, workspace_id, scenario_id)
        if scenario.system_id != system.id:
            raise ValueLoopConflict("ValueScenario changed System while acquiring locks")
        existing = _find_operation_receipt(
            db,
            workspace_id=workspace_id,
            idempotency_key=idempotency_key,
            operation="measure",
            request_sha256=request_hash,
        )
        if existing is not None:
            return _load_idempotent_result(db, existing, ValueMeasurement)
        if scenario.status != "acted" or scenario.acted_at is None:
            raise ValueLoopConflict(f"cannot measure a {scenario.status} scenario")
        action = (
            db.query(ValueActionExecution)
            .filter(
                ValueActionExecution.workspace_id == workspace_id,
                ValueActionExecution.scenario_id == scenario.id,
                ValueActionExecution.status == "succeeded",
            )
            .populate_existing()
            .with_for_update(of=ValueActionExecution)
            .one_or_none()
        )
        if action is None:
            raise ValueLoopConflict("acted scenario has no action execution")
        simulation = (
            db.query(ValueSimulation)
            .filter(
                ValueSimulation.id == action.simulation_id,
                ValueSimulation.workspace_id == workspace_id,
                ValueSimulation.system_id == scenario.system_id,
                ValueSimulation.scenario_id == scenario.id,
                ValueSimulation.status == "available",
            )
            .populate_existing()
            .with_for_update(of=ValueSimulation)
            .one_or_none()
        )
        if (
            simulation is None
            or scenario.approved_simulation_id != simulation.id
        ):
            raise ValueLoopConflict(
                "acted scenario is not bound to its approved simulation"
            )
        expected_policy = _action_policy_contract(action)
        action_patch = _canonical_patch(action.patch or {})
        _validate_locked_authority(
            db,
            workspace=workspace,
            system=system,
            control=control,
            actuator=action.actuator,
            patch=action_patch,
            expected_policy=expected_policy,
        )

        source: Run | None
        policy_mismatch_seen = False
        provenance_unavailable_seen = False
        canary_authored_seen = False
        if source_run_id:
            # Scope before reading or locking.  Looking up a guessed foreign
            # tenant id and rejecting it afterwards would still create a
            # cross-tenant read/lock side channel.
            source = (
                db.query(Run)
                .filter(
                    Run.id == source_run_id,
                    Run.workspace_id == workspace_id,
                    Run.system_id == scenario.system_id,
                )
                .populate_existing()
                .with_for_update(of=Run)
                .one_or_none()
            )
            if source is None:
                raise ValueLoopNotFound("post-action Run not found")
            if source_run_is_authorized is not None and not source_run_is_authorized(source):
                # A denied Run is deliberately indistinguishable from an
                # unknown, cross-System or cross-tenant source identifier.
                raise ValueLoopNotFound("post-action Run not found")
            _valid_observed_run(
                source,
                workspace_id=workspace_id,
                system_id=scenario.system_id,
                acted_at=action.executed_at,
                expected_policy=expected_policy,
            )
        else:
            candidates = (
                db.query(Run)
                .filter(
                    Run.workspace_id == workspace_id,
                    Run.system_id == scenario.system_id,
                    Run.status == "completed",
                    Run.started_at >= action.executed_at,
                    Run.completed_at >= action.executed_at,
                    Run.value_source.in_(MEASURED_VALUE_SOURCES),
                    Run.value_estimated.isnot(None),
                )
                .order_by(Run.completed_at.desc(), Run.id.desc())
                .populate_existing()
                .with_for_update(of=Run)
                .all()
            )
            source = None
            for candidate in candidates:
                if (
                    source_run_is_authorized is not None
                    and not source_run_is_authorized(candidate)
                ):
                    continue
                if _run_policy_contract(candidate) != expected_policy:
                    policy_mismatch_seen = True
                    continue
                if is_canary_authored_operator_outcome(candidate):
                    canary_authored_seen = True
                    continue
                if run_measurement_provenance(candidate, db=db) is None:
                    provenance_unavailable_seen = True
                    continue
                source = candidate
                break

        receipt = _claim_operation_receipt(
            db,
            workspace_id=workspace_id,
            idempotency_key=idempotency_key,
            operation="measure",
            request_sha256=request_hash,
        )

        baseline = dict(scenario.baseline_outcome or {})
        observed = _run_outcome(db, source) if source is not None else None
        if not _is_measured_outcome(baseline):
            status = "not_measured"
            reason = "baseline_value_not_measured"
        elif observed is None:
            status = "not_measured"
            if canary_authored_seen:
                reason = "canary_authored_outcome_is_not_independent"
            elif provenance_unavailable_seen:
                reason = "post_action_measurement_provenance_unavailable"
            elif policy_mismatch_seen:
                reason = "no_post_action_run_with_applied_policy"
            else:
                reason = "no_comparable_post_action_run"
        elif source is not None and is_canary_authored_operator_outcome(source):
            status = "not_measured"
            reason = "canary_authored_outcome_is_not_independent"
        elif (
            observed.get("value_source") in MEASURED_VALUE_SOURCES
            and not isinstance(observed.get("measurement_provenance"), Mapping)
        ):
            status = "not_measured"
            reason = "post_action_measurement_provenance_unavailable"
        elif not _is_measured_outcome(observed):
            # In particular, ``value_source=unset`` can never promote a
            # scenario to measured, even when the Run has a numeric default;
            # a provenance source must also match the declared value source.
            status = "not_measured"
            reason = "post_action_value_not_measured"
        else:
            status = "measured"
            reason = None

        forecast_delta, assumption_verdict, assumption_evaluation = (
            _forecast_evaluation(
                simulation=simulation,
                observed=observed,
                measurement_status=status,
                reason=reason,
            )
        )

        now = datetime.utcnow()
        measurement = ValueMeasurement(
            id=str(uuid4()),
            workspace_id=workspace_id,
            system_id=scenario.system_id,
            scenario_id=scenario.id,
            action_execution_id=action.id,
            simulation_id=simulation.id,
            source_run_id=source.id if source is not None else None,
            operation_id=receipt.id,
            status=status,
            reason=reason,
            baseline_outcome=baseline,
            observed_outcome=observed,
            delta=(
                _measurement_delta(baseline, observed)
                if status == "measured" and observed is not None
                else None
            ),
            forecast_delta=forecast_delta,
            assumption_verdict=assumption_verdict,
            assumption_evaluation=assumption_evaluation,
            measured_at=now,
        )
        db.add(measurement)
        if status == "measured":
            scenario.status = "measured"
            scenario.measured_at = now
        _finish_receipt(receipt, result_type="value_measurement", result_id=measurement.id)
        _audit(
            db,
            workspace_id=workspace_id,
            event_type=f"value_loop.measurement.{status}",
            actor=request["actor"],
            details={
                "scenario_id": scenario.id,
                "simulation_id": simulation.id,
                "action_execution_id": action.id,
                "measurement_id": measurement.id,
                "system_id": scenario.system_id,
                "source_run_id": source.id if source is not None else None,
                "status": status,
                "reason": reason,
                "assumption_verdict": assumption_verdict,
                "forecast_metrics": sorted(forecast_delta or {}),
                "request_sha256": request_hash,
                "evidence_type": "run" if observed is not None else None,
            },
        )
        db.commit()
        db.refresh(measurement)
        return measurement
    except Exception as exc:  # noqa: BLE001 - transaction boundary
        _rollback_and_raise(db, exc)


__all__ = [
    "CONTROL_POLICY_GUARDRAILS_PATCH_V1",
    "ValueLoopConflict",
    "ValueLoopError",
    "ValueLoopNotFound",
    "ValueLoopValidationError",
    "act_value_scenario",
    "approve_value_scenario",
    "create_value_scenario",
    "measure_value_scenario",
    "simulate_value_scenario",
]
