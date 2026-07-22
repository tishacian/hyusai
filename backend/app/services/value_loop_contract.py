"""Read-only authority for the bounded Lot 8 actuator contract."""
from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session as DBSession

from app.models.policy import ControlPolicy
from app.models.system import System
from app.services.membrane.spec import EnforcementMode, MembraneSpec

CONTROL_POLICY_GUARDRAILS_PATCH_V1 = "control_policy.guardrails.patch.v1"
VALUE_LOOP_ACTUATOR_BOUNDS = {
    "max_cost_per_decision": {"min": 0, "max": 50},
    "max_latency_ms": {"min": 100, "max": 30_000},
    "mandatory_hitl_if_confidence_below": {"min": 0, "max": 1},
}


@dataclass(frozen=True)
class ValueLoopActuatorContract:
    valid: bool
    reason: str
    policy: ControlPolicy | None = None


def canonical_value_loop_actuator_config() -> dict[str, Any]:
    return {
        "enabled": True,
        "fields": copy.deepcopy(VALUE_LOOP_ACTUATOR_BOUNDS),
    }


def _actuator_config(system: System) -> dict[str, Any] | None:
    settings = system.settings if isinstance(system.settings, Mapping) else {}
    value_loop = settings.get("value_loop")
    if not isinstance(value_loop, Mapping):
        return None
    actuators = value_loop.get("actuators")
    if not isinstance(actuators, Mapping):
        return None
    config = actuators.get(CONTROL_POLICY_GUARDRAILS_PATCH_V1)
    return copy.deepcopy(dict(config)) if isinstance(config, Mapping) else None


def validate_value_loop_actuator_objects(
    *,
    system: System,
    policy: ControlPolicy | None,
    require_enforce: bool,
) -> ValueLoopActuatorContract:
    """Validate current objects without mutating or trusting rollout history."""

    if _actuator_config(system) != canonical_value_loop_actuator_config():
        return ValueLoopActuatorContract(False, "actuator_config_missing_or_different")
    if policy is None:
        return ValueLoopActuatorContract(False, "control_policy_missing")
    if (
        policy.id != system.control_policy_id
        or policy.workspace_id != system.workspace_id
        or policy.scope != "system"
        or policy.target_id != system.id
    ):
        return ValueLoopActuatorContract(False, "control_policy_scope_mismatch")
    extra = policy.extra if isinstance(policy.extra, Mapping) else {}
    raw = extra.get("membrane_spec")
    if not isinstance(raw, Mapping) or raw.get("version") != 2:
        return ValueLoopActuatorContract(False, "membrane_v2_missing")
    try:
        membrane = MembraneSpec.from_dict(raw, authoritative=True)
    except (TypeError, ValueError):
        return ValueLoopActuatorContract(False, "membrane_v2_invalid")
    if CONTROL_POLICY_GUARDRAILS_PATCH_V1 not in membrane.capabilities.allowed_actions:
        return ValueLoopActuatorContract(False, "membrane_action_missing")
    if require_enforce and membrane.effective_mode is not EnforcementMode.ENFORCE:
        return ValueLoopActuatorContract(False, "membrane_not_enforced")
    return ValueLoopActuatorContract(True, "ready", policy)


def validate_value_loop_runtime_contract(
    db: DBSession,
    *,
    workspace_id: str,
    system: System,
) -> ValueLoopActuatorContract:
    """Resolve and validate the effective current runtime contract fail-closed."""

    if not system.control_policy_id:
        return ValueLoopActuatorContract(False, "control_policy_missing")
    policy = (
        db.query(ControlPolicy)
        .filter(
            ControlPolicy.id == system.control_policy_id,
            ControlPolicy.workspace_id == workspace_id,
        )
        .populate_existing()
        .one_or_none()
    )
    return validate_value_loop_actuator_objects(
        system=system,
        policy=policy,
        require_enforce=True,
    )


__all__ = [
    "CONTROL_POLICY_GUARDRAILS_PATCH_V1",
    "VALUE_LOOP_ACTUATOR_BOUNDS",
    "ValueLoopActuatorContract",
    "canonical_value_loop_actuator_config",
    "validate_value_loop_actuator_objects",
    "validate_value_loop_runtime_contract",
]
