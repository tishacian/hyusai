#!/usr/bin/env python3
"""Structural, attested rollout for the Lot 8 System value loop.

The default target is selected only through persisted experience markers.  No
slug, name or code-owned fixed identifier participates in discovery.  An
operator may pass a runtime-discovered System ID to target a tenant-scoped
rollout or rollback explicitly.  Every mutating command is a dry-run unless
``--apply`` is passed explicitly.

``prepare`` installs the bounded actuator contract and its Membrane allow-list
entry, but deliberately leaves the Workspace feature disabled.  ``activate``
accepts only fresh, content-addressed behaviour evidence produced by the exact
runtime revision and enables the Workspace feature in the same transaction as
the reduced evidence and audit row.  ``deactivate`` is the rollback switch: it
turns the feature off while preserving all additive configuration and records.
"""
from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import json
import re
import sys
import xml.etree.ElementTree as ElementTree
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session as DBSession

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.config import settings  # noqa: E402
from app.db.base import SessionLocal  # noqa: E402
from app.models.audit import AuditLog  # noqa: E402
from app.models.decision import Decision  # noqa: E402
from app.models.policy import ControlPolicy  # noqa: E402
from app.models.run import Run  # noqa: E402
from app.models.system import System  # noqa: E402
from app.models.value_loop import (  # noqa: E402
    ValueActionExecution,
    ValueLoopOperation,
    ValueMeasurement,
    ValueScenario,
    ValueSimulation,
)
from app.models.workspace import Workspace  # noqa: E402
from app.services.audit_logger import emit_audit_event  # noqa: E402
from app.services.control_policy_snapshot import (  # noqa: E402
    control_policy_execution_contract,
    validated_control_policy_execution_contract,
)
from app.services.membrane.spec import EnforcementMode, MembraneSpec  # noqa: E402
from app.services.value_loop_authorization import (  # noqa: E402
    REQUIRED_VALUE_LOOP_AUTHORIZATION_ACTIONS,
    value_loop_authorization_modes,
)
from app.services.value_loop_contract import (  # noqa: E402
    CONTROL_POLICY_GUARDRAILS_PATCH_V1,
    VALUE_LOOP_ACTUATOR_BOUNDS,
    canonical_value_loop_actuator_config,
    validate_value_loop_actuator_objects,
)
from app.services.value_loop_gate import (  # noqa: E402
    CANARY_MARKER_KEY,
    CANARY_MARKER_VALUE,
    FEATURE_KEY,
    ROLLOUT_SCHEMA_VERSION,
    ROLLOUT_STATE_KEY,
    value_loop_enabled,
    value_loop_policy_chain_reference,
    value_loop_requested,
)
from scripts.rollout_authorization_v2 import (  # noqa: E402
    AuthorizationPromotionError,
    _trusted_runner_from_ci,
    _trusted_runner_metadata,
)

SYSTEM360_MARKER_KEY = "system_360_canary"
EVIDENCE_SCHEMA_VERSION = 3
EVIDENCE_KIND = "lot8_value_loop_behavior"
EVIDENCE_MAX_AGE = timedelta(hours=24)
EVIDENCE_FUTURE_TOLERANCE = timedelta(minutes=5)
EVIDENCE_ARTIFACT_MAX_BYTES = 256 * 1024
EVIDENCE_SUITE = "lot8-value-loop-canary"
CANARY_WINDOW_DURATION = timedelta(hours=2)
REQUIRED_CHECKS = (
    "create",
    "simulate",
    "approve",
    "act",
    "measure",
    "idempotency",
    "tenant_isolation",
    "simulation_not_measurement",
)
REQUIRED_RECORDS = (
    "scenario_id",
    "decision_id",
    "simulation_id",
    "action_execution_id",
    "measurement_id",
)
ACTUATOR_BOUNDS = VALUE_LOOP_ACTUATOR_BOUNDS


class ValueLoopRolloutError(ValueError):
    """Fail-closed rollout contract violation."""


def _require_authorization_enforce(
    db: DBSession,
    *,
    workspace: Workspace,
    lock: bool,
) -> dict[str, str]:
    modes = value_loop_authorization_modes(
        db,
        workspace_id=workspace.id,
        lock=lock,
    )
    missing = [
        f"{action}={modes.get(action, 'compat')}"
        for action in REQUIRED_VALUE_LOOP_AUTHORIZATION_ACTIONS
        if modes.get(action) != "enforce"
    ]
    if missing:
        raise ValueLoopRolloutError(
            "Lot 8 requires exact attested authorization-v2 enforce: "
            + ", ".join(missing)
        )
    return modes


def _record(value: Any) -> dict[str, Any]:
    return copy.deepcopy(dict(value)) if isinstance(value, Mapping) else {}


def _canonical_sha256(value: Any) -> str:
    canonical = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _experience(system: System) -> dict[str, Any]:
    return _record(_record(system.settings).get("experience"))


def _features(workspace: Workspace) -> tuple[dict[str, Any], dict[str, Any]]:
    workspace_settings = _record(workspace.settings)
    raw = workspace_settings.get("features")
    if raw is not None and not isinstance(raw, Mapping):
        raise ValueLoopRolloutError("workspace settings.features must be an object")
    return workspace_settings, _record(raw)


def _feature_enabled(workspace: Workspace) -> bool:
    _, features = _features(workspace)
    return features.get(FEATURE_KEY) is True


def _set_feature(workspace: Workspace, enabled: bool) -> None:
    workspace_settings, features = _features(workspace)
    features[FEATURE_KEY] = bool(enabled)
    workspace_settings["features"] = features
    workspace.settings = workspace_settings


def _state(system: System) -> dict[str, Any]:
    state = _record(_record(system.settings).get(ROLLOUT_STATE_KEY))
    if not state:
        return {
            "schema_version": ROLLOUT_SCHEMA_VERSION,
            "prepared": None,
            "proof_window": None,
            "activations": [],
            "deactivations": [],
            "policy_transitions": [],
        }
    if state.get("schema_version") != ROLLOUT_SCHEMA_VERSION:
        raise ValueLoopRolloutError("unsupported Lot 8 rollout state")
    for field in ("activations", "deactivations", "policy_transitions"):
        rows = state.get(field, [])
        if not isinstance(rows, list) or any(not isinstance(row, Mapping) for row in rows):
            raise ValueLoopRolloutError(f"invalid Lot 8 rollout {field}")
        state[field] = [dict(row) for row in rows]
    prepared = state.get("prepared")
    if prepared is not None and not isinstance(prepared, Mapping):
        raise ValueLoopRolloutError("invalid Lot 8 prepared state")
    state["prepared"] = dict(prepared) if isinstance(prepared, Mapping) else None
    proof_window = state.get("proof_window")
    if proof_window is not None and not isinstance(proof_window, Mapping):
        raise ValueLoopRolloutError("invalid Lot 8 proof window")
    state["proof_window"] = (
        dict(proof_window) if isinstance(proof_window, Mapping) else None
    )
    state.setdefault("policy_transitions", [])
    return state


def _save_state(system: System, state: Mapping[str, Any]) -> None:
    system_settings = _record(system.settings)
    system_settings[ROLLOUT_STATE_KEY] = copy.deepcopy(dict(state))
    system.settings = system_settings


def _runtime_revision() -> str:
    revision = str(settings.agentium_image_revision or "").strip().lower()
    if re.fullmatch(r"[0-9a-f]{40}", revision) is None:
        raise ValueLoopRolloutError(
            "the deployed runtime must expose its exact 40-character Git SHA"
        )
    return revision


def _parse_utc(value: Any, *, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueLoopRolloutError(f"{field} is required")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueLoopRolloutError(f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ValueLoopRolloutError(f"{field} must include a timezone")
    return parsed.astimezone(UTC)


def _active_proof_window(
    state: Mapping[str, Any],
    *,
    system_id: str,
    revision: str,
    now: datetime | None = None,
) -> Mapping[str, Any] | None:
    raw = state.get("proof_window")
    if not isinstance(raw, Mapping):
        return None
    expected = {
        "audit_id",
        "system_id",
        "revision",
        "contract_sha256",
        "opened_at",
        "expires_at",
        "opened_by",
        "policy_chain_ref",
        "control_policy",
    }
    if set(raw) != expected:
        raise ValueLoopRolloutError("Lot 8 proof window fields differ from the contract")
    if (
        raw.get("system_id") != system_id
        or raw.get("revision") != revision
        or raw.get("contract_sha256") != _prepared_contract_sha256()
        or not str(raw.get("audit_id") or "").strip()
        or not str(raw.get("opened_by") or "").strip()
        or re.fullmatch(r"sha256:[0-9a-f]{64}", str(raw.get("policy_chain_ref") or ""))
        is None
        or validated_control_policy_execution_contract(raw.get("control_policy"))
        is None
    ):
        return None
    opened_at = _parse_utc(raw.get("opened_at"), field="proof_window.opened_at")
    expires_at = _parse_utc(raw.get("expires_at"), field="proof_window.expires_at")
    current = now or datetime.now(UTC)
    if expires_at <= opened_at or current < opened_at or current >= expires_at:
        return None
    return dict(raw)


def _workspace_open_proof_window_system_ids(
    db: DBSession,
    *,
    workspace: Workspace,
) -> list[str]:
    """Find every currently open proof window, failing on malformed state."""

    now = datetime.now(UTC)
    owners: list[str] = []
    systems = (
        db.query(System)
        .filter(System.workspace_id == workspace.id, System.status == "active")
        .order_by(System.id.asc())
        .all()
    )
    for candidate in systems:
        raw = _state(candidate).get("proof_window")
        if raw is None:
            continue
        if not isinstance(raw, Mapping):  # Defensive; _state already checks.
            raise ValueLoopRolloutError("invalid Lot 8 proof window")
        opened_at = _parse_utc(
            raw.get("opened_at"),
            field="proof_window.opened_at",
        )
        expires_at = _parse_utc(
            raw.get("expires_at"),
            field="proof_window.expires_at",
        )
        if expires_at <= opened_at:
            raise ValueLoopRolloutError("Lot 8 proof window has an invalid duration")
        if opened_at <= now < expires_at:
            owners.append(str(candidate.id))
    return owners


def _require_actor(actor: str) -> str:
    value = str(actor or "").strip()
    if not value:
        raise ValueLoopRolloutError("--apply requires a non-empty actor")
    return value


def _marker_matches(system: System, marker: str) -> bool:
    return _experience(system).get(marker) == CANARY_MARKER_VALUE


def discover_target(
    db: DBSession,
    *,
    workspace_id: str,
    system_id: str | None = None,
    lock: bool = False,
    allow_system360_fallback: bool = True,
    require_canary_marker: bool = False,
) -> tuple[Workspace, System, bool]:
    """Resolve one active, tenant-scoped target without business identity.

    Without ``system_id``, selection remains marker-only and ambiguous marker
    sets fail closed.  ``system_id`` is an explicit operator target, never a
    slug/name lookup or code-owned constant.  The boolean return value says
    whether ``prepare`` must move/derive the unique Lot 8 canary marker.
    """

    scoped_workspace_id = str(workspace_id or "").strip()
    scoped_system_id = str(system_id or "").strip() or None
    if not scoped_workspace_id:
        raise ValueLoopRolloutError("workspace_id is required")
    workspace_query = db.query(Workspace).filter(
        Workspace.id == scoped_workspace_id,
        Workspace.is_active.is_(True),
        Workspace.deleted_at.is_(None),
    )
    workspace = workspace_query.one_or_none()
    if workspace is None:
        raise ValueLoopRolloutError("the target Workspace is missing or inactive")

    def select(candidates: list[System]) -> tuple[System, bool]:
        marked = [
            row for row in candidates if _marker_matches(row, CANARY_MARKER_KEY)
        ]
        if scoped_system_id is not None:
            selected = [row for row in candidates if row.id == scoped_system_id]
            if len(selected) != 1:
                raise ValueLoopRolloutError(
                    "the target System is missing, inactive, or outside the Workspace"
                )
            target = selected[0]
            has_marker = _marker_matches(target, CANARY_MARKER_KEY)
            if require_canary_marker and not has_marker:
                raise ValueLoopRolloutError(
                    "the explicitly targeted System is not the current Lot 8 canary"
                )
            return target, not (has_marker and len(marked) == 1)

        if len(marked) > 1:
            raise ValueLoopRolloutError(
                f"expected at most one active {CANARY_MARKER_KEY} marker, "
                f"found {len(marked)}"
            )
        if marked:
            return marked[0], False
        if not allow_system360_fallback:
            raise ValueLoopRolloutError("the Workspace has no Lot 8 canary marker")
        system360 = [
            row for row in candidates if _marker_matches(row, SYSTEM360_MARKER_KEY)
        ]
        if len(system360) != 1:
            raise ValueLoopRolloutError(
                "expected exactly one active System 360 marker to derive the Lot 8 "
                f"canary, found {len(system360)}"
            )
        return system360[0], True

    candidates = (
        db.query(System)
        .filter(System.workspace_id == workspace.id, System.status == "active")
        .order_by(System.id.asc())
        .all()
    )
    system, derived = select(candidates)
    selected_system_id = system.id

    if lock:
        workspace = (
            db.query(Workspace)
            .populate_existing()
            .filter(
                Workspace.id == workspace.id,
                Workspace.is_active.is_(True),
                Workspace.deleted_at.is_(None),
            )
            .with_for_update(of=Workspace)
            .one_or_none()
        )
        candidates = (
            db.query(System)
            .populate_existing()
            .filter(
                System.workspace_id == scoped_workspace_id,
                System.status == "active",
            )
            .order_by(System.id.asc())
            .with_for_update(of=System)
            .all()
        )
        if workspace is None:
            raise ValueLoopRolloutError("the rollout target changed while acquiring locks")
        system, locked_derived = select(candidates)
        if system.id != selected_system_id or locked_derived != derived:
            raise ValueLoopRolloutError("the structural target changed while locking")
        derived = locked_derived
    return workspace, system, derived


def _control_policy(
    db: DBSession,
    *,
    workspace: Workspace,
    system: System,
    lock: bool,
) -> ControlPolicy:
    if not system.control_policy_id:
        raise ValueLoopRolloutError("the canary System has no ControlPolicy")
    query = db.query(ControlPolicy).filter(
        ControlPolicy.id == system.control_policy_id,
        ControlPolicy.workspace_id == workspace.id,
        ControlPolicy.scope == "system",
        ControlPolicy.target_id == system.id,
    )
    if lock:
        query = query.populate_existing().with_for_update(of=ControlPolicy)
    policy = query.one_or_none()
    if policy is None:
        raise ValueLoopRolloutError(
            "the canary ControlPolicy must be explicitly scoped to its System"
        )
    return policy


def _membrane(policy: ControlPolicy) -> tuple[dict[str, Any], MembraneSpec]:
    extra = _record(policy.extra)
    raw = extra.get("membrane_spec")
    if not isinstance(raw, Mapping) or raw.get("version") != 2:
        raise ValueLoopRolloutError("an explicit MembraneSpec v2 is required")
    try:
        parsed = MembraneSpec.from_dict(raw, authoritative=True)
    except (TypeError, ValueError) as exc:
        raise ValueLoopRolloutError("the explicit MembraneSpec v2 is invalid") from exc
    return copy.deepcopy(dict(raw)), parsed


def _actuator_config(system: System) -> dict[str, Any] | None:
    value_loop = _record(_record(system.settings).get("value_loop"))
    actuators = _record(value_loop.get("actuators"))
    raw = actuators.get(CONTROL_POLICY_GUARDRAILS_PATCH_V1)
    return copy.deepcopy(dict(raw)) if isinstance(raw, Mapping) else None


def _canonical_actuator_config() -> dict[str, Any]:
    return canonical_value_loop_actuator_config()


def _prepared_contract_sha256() -> str:
    """Address only the bounded fields owned by this preparation step.

    The Membrane enforcement mode is intentionally excluded: moving from
    shadow to enforce is a separate gate between prepare and activate and must
    not make an otherwise identical preparation look stale.
    """

    return _canonical_sha256(
        {
            "actuator": {
                "name": CONTROL_POLICY_GUARDRAILS_PATCH_V1,
                "config": _canonical_actuator_config(),
            },
            "membrane_allowed_action": CONTROL_POLICY_GUARDRAILS_PATCH_V1,
        }
    )


def _prepared_contract(policy: ControlPolicy, system: System) -> tuple[bool, str]:
    result = validate_value_loop_actuator_objects(
        system=system,
        policy=policy,
        require_enforce=False,
    )
    return result.valid, result.reason


def _set_marker(system: System) -> None:
    system_settings = _record(system.settings)
    experience = _record(system_settings.get("experience"))
    experience[CANARY_MARKER_KEY] = CANARY_MARKER_VALUE
    system_settings["experience"] = experience
    system.settings = system_settings


def _clear_marker(system: System) -> None:
    system_settings = _record(system.settings)
    experience = _record(system_settings.get("experience"))
    experience.pop(CANARY_MARKER_KEY, None)
    system_settings["experience"] = experience
    system.settings = system_settings


def _select_exclusive_canary_marker(
    db: DBSession,
    *,
    workspace: Workspace,
    system: System,
) -> list[str]:
    """Move the proof marker without changing any activation authority."""

    owners = _workspace_open_proof_window_system_ids(
        db,
        workspace=workspace,
    )
    if owners and owners != [system.id]:
        raise ValueLoopRolloutError(
            "cannot move the Lot 8 canary while another proof window is open"
        )
    systems = (
        db.query(System)
        .filter(System.workspace_id == workspace.id, System.status == "active")
        .order_by(System.id.asc())
        .all()
    )
    previous = [
        str(row.id)
        for row in systems
        if row.id != system.id and _marker_matches(row, CANARY_MARKER_KEY)
    ]
    for row in systems:
        if row.id == system.id:
            _set_marker(row)
        elif _marker_matches(row, CANARY_MARKER_KEY):
            _clear_marker(row)
    return previous


def _install_actuator(system: System) -> None:
    system_settings = _record(system.settings)
    value_loop = _record(system_settings.get("value_loop"))
    actuators = _record(value_loop.get("actuators"))
    existing = actuators.get(CONTROL_POLICY_GUARDRAILS_PATCH_V1)
    canonical = _canonical_actuator_config()
    if existing is not None and existing != canonical:
        raise ValueLoopRolloutError(
            "the existing value-loop actuator contract differs from the bounded v1 contract"
        )
    actuators[CONTROL_POLICY_GUARDRAILS_PATCH_V1] = canonical
    value_loop["actuators"] = actuators
    system_settings["value_loop"] = value_loop
    system.settings = system_settings


def _allow_actuator(policy: ControlPolicy) -> None:
    raw, _parsed = _membrane(policy)
    capabilities = _record(raw.get("capabilities"))
    allowed = capabilities.get("allowed_actions", [])
    if not isinstance(allowed, list) or any(not isinstance(item, str) for item in allowed):
        raise ValueLoopRolloutError(
            "membrane_spec.capabilities.allowed_actions must be a string list"
        )
    capabilities["allowed_actions"] = list(dict.fromkeys([*allowed, CONTROL_POLICY_GUARDRAILS_PATCH_V1]))
    raw["capabilities"] = capabilities
    extra = _record(policy.extra)
    extra["membrane_spec"] = raw
    policy.extra = extra


def _emit_required_audit(
    db: DBSession,
    *,
    workspace: Workspace,
    system: System,
    event_type: str,
    actor: str,
    details: Mapping[str, Any],
) -> str:
    audit_id = emit_audit_event(
        workspace_id=workspace.id,
        event_type=event_type,
        actor=actor,
        agent_id=system.id,
        details=dict(details),
        db=db,
    )
    if audit_id is None:
        raise ValueLoopRolloutError("the mandatory rollout audit could not be persisted")
    return audit_id


def status(
    db: DBSession,
    *,
    workspace_id: str,
    system_id: str | None = None,
) -> dict[str, Any]:
    workspace, system, derived = discover_target(
        db,
        workspace_id=workspace_id,
        system_id=system_id,
        allow_system360_fallback=True,
    )
    policy = _control_policy(db, workspace=workspace, system=system, lock=False)
    state = _state(system)
    try:
        prepared, preparation_reason = _prepared_contract(policy, system)
        _raw, parsed = _membrane(policy)
        membrane_mode = parsed.effective_mode.value
        action_allowed = (
            CONTROL_POLICY_GUARDRAILS_PATCH_V1 in parsed.capabilities.allowed_actions
        )
    except ValueLoopRolloutError as exc:
        prepared = False
        preparation_reason = str(exc)
        membrane_mode = "invalid"
        action_allowed = False
    authorization_modes = value_loop_authorization_modes(
        db,
        workspace_id=workspace.id,
    )
    return {
        "schema_version": 1,
        "workspace_id": workspace.id,
        "system_id": system.id,
        "marker": {
            "present": _marker_matches(system, CANARY_MARKER_KEY),
            "exclusive": not derived,
            "requires_selection": derived,
            "derivable_from_system_360": (
                derived and _marker_matches(system, SYSTEM360_MARKER_KEY)
            ),
        },
        "prepared": prepared,
        "preparation_reason": preparation_reason,
        "feature_enabled": _feature_enabled(workspace),
        "membrane_mode": membrane_mode,
        "membrane_action_allowed": action_allowed,
        "authorization_ready": all(
            mode == "enforce" for mode in authorization_modes.values()
        ),
        "authorization_modes": authorization_modes,
        "activation_count": len(state["activations"]),
        "deactivation_count": len(state["deactivations"]),
        "proof_window": state.get("proof_window"),
        "latest_activation": state["activations"][-1] if state["activations"] else None,
        "policy_transition_count": len(state["policy_transitions"]),
        "runtime_gate_open": value_loop_enabled(
            db,
            workspace=workspace,
            system=system,
        ),
    }


def prepare(
    db: DBSession,
    *,
    workspace_id: str,
    system_id: str | None = None,
    apply: bool,
    actor: str,
) -> dict[str, Any]:
    workspace, system, derived = discover_target(
        db,
        workspace_id=workspace_id,
        system_id=system_id,
        lock=apply,
        allow_system360_fallback=True,
    )
    policy = _control_policy(db, workspace=workspace, system=system, lock=apply)
    existing_config = _actuator_config(system)
    if existing_config is not None and existing_config != _canonical_actuator_config():
        raise ValueLoopRolloutError(
            "the existing value-loop actuator contract differs from the bounded v1 contract"
        )
    _raw, parsed = _membrane(policy)
    allowed = parsed.capabilities.allowed_actions
    changed_fields = []
    if derived:
        changed_fields.append(f"system.settings.experience.{CANARY_MARKER_KEY}")
        proof_owners = _workspace_open_proof_window_system_ids(
            db,
            workspace=workspace,
        )
        if proof_owners and proof_owners != [system.id]:
            raise ValueLoopRolloutError(
                "cannot prepare a new Lot 8 canary while another proof window is open"
            )
    if existing_config is None:
        changed_fields.append("system.settings.value_loop.actuators")
    if CONTROL_POLICY_GUARDRAILS_PATCH_V1 not in allowed:
        changed_fields.append("control_policy.extra.membrane_spec.capabilities.allowed_actions")

    state = _state(system)
    contract_digest = _prepared_contract_sha256()
    already_prepared = (
        not changed_fields
        and isinstance(state.get("prepared"), Mapping)
        and state["prepared"].get("contract_sha256") == contract_digest
        and state["prepared"].get("system_id") == system.id
    )
    if not isinstance(state.get("prepared"), Mapping):
        changed_fields.append(f"system.settings.{ROLLOUT_STATE_KEY}")
    previous_marker_system_ids = [
        str(row.id)
        for row in db.query(System)
        .filter(System.workspace_id == workspace.id, System.status == "active")
        .all()
        if row.id != system.id and _marker_matches(row, CANARY_MARKER_KEY)
    ]
    report = {
        "schema_version": 1,
        "operation": "apply" if apply else "dry_run",
        "direction": "prepare",
        "workspace_id": workspace.id,
        "system_id": system.id,
        "changed": not already_prepared,
        "changed_fields": changed_fields,
        "feature_enabled": _feature_enabled(workspace),
        "previous_canary_system_ids": previous_marker_system_ids,
        "contract_sha256": contract_digest,
        "membrane_mode": parsed.effective_mode.value,
    }
    if not apply or already_prepared:
        return report

    actor_value = _require_actor(actor)
    try:
        applied_previous_marker_system_ids: list[str] = []
        if derived:
            applied_previous_marker_system_ids = _select_exclusive_canary_marker(
                db,
                workspace=workspace,
                system=system,
            )
        _install_actuator(system)
        _allow_actuator(policy)
        now = datetime.now(UTC).isoformat()
        state["prepared"] = {
            "system_id": system.id,
            "contract_sha256": contract_digest,
            "prepared_at": now,
            "prepared_by": actor_value,
        }
        _save_state(system, state)
        _emit_required_audit(
            db,
            workspace=workspace,
            system=system,
            event_type="lot8.value_loop.prepared",
            actor=actor_value,
            details={
                "system_id": system.id,
                "contract_sha256": contract_digest,
                "changed_fields": changed_fields,
                "feature_enabled": _feature_enabled(workspace),
                "previous_canary_system_ids": applied_previous_marker_system_ids,
            },
        )
        db.commit()
        return report
    except Exception:
        db.rollback()
        raise


def open_canary_window(
    db: DBSession,
    *,
    workspace_id: str,
    system_id: str | None = None,
    apply: bool,
    actor: str,
) -> dict[str, Any]:
    """Open a short, SHA-bound gate solely for generating behaviour proof."""

    workspace, system, derived = discover_target(
        db,
        workspace_id=workspace_id,
        system_id=system_id,
        lock=apply,
        allow_system360_fallback=False,
        require_canary_marker=True,
    )
    if derived:  # Defensive: fallback is disabled above.
        raise ValueLoopRolloutError("prepare must persist the Lot 8 marker first")
    policy = _control_policy(db, workspace=workspace, system=system, lock=apply)
    prepared, reason = _prepared_contract(policy, system)
    if not prepared:
        raise ValueLoopRolloutError(f"Lot 8 actuator is not prepared: {reason}")
    _raw, parsed = _membrane(policy)
    if parsed.effective_mode is not EnforcementMode.ENFORCE:
        raise ValueLoopRolloutError("canary window requires MembraneSpec v2 enforce")
    _require_authorization_enforce(
        db,
        workspace=workspace,
        lock=apply,
    )
    state = _state(system)
    prepared_state = state.get("prepared")
    if (
        not isinstance(prepared_state, Mapping)
        or prepared_state.get("system_id") != system.id
        or prepared_state.get("contract_sha256") != _prepared_contract_sha256()
    ):
        raise ValueLoopRolloutError("prepare must persist the Lot 8 rollout contract first")
    revision = _runtime_revision()
    active = _active_proof_window(
        state,
        system_id=system.id,
        revision=revision,
    )
    proof_owners = _workspace_open_proof_window_system_ids(
        db,
        workspace=workspace,
    )
    if len(proof_owners) > 1 or (
        proof_owners and proof_owners != [system.id]
    ):
        raise ValueLoopRolloutError(
            "another System already owns the Workspace Lot 8 proof window"
        )
    if active is not None and not value_loop_enabled(
        db,
        workspace=workspace,
        system=system,
    ):
        raise ValueLoopRolloutError(
            "the active canary window no longer matches the ControlPolicy chain"
        )
    report = {
        "schema_version": 1,
        "operation": "apply" if apply else "dry_run",
        "direction": "open_canary",
        "workspace_id": workspace.id,
        "system_id": system.id,
        "revision": revision,
        "changed": active is None,
        "proof_window": active,
    }
    if not apply or active is not None:
        return report
    actor_value = _require_actor(actor)
    try:
        opened_at = datetime.now(UTC)
        policy_reference = control_policy_execution_contract(policy)
        policy_chain_ref = value_loop_policy_chain_reference(
            system_id=system.id,
            revision=revision,
            created_at=opened_at.isoformat(),
            control_policy=policy_reference,
        )
        if policy_chain_ref is None:  # Defensive: inputs are validated above.
            raise ValueLoopRolloutError("could not content-address the policy root")
        proof_window = {
            "system_id": system.id,
            "revision": revision,
            "contract_sha256": _prepared_contract_sha256(),
            "opened_at": opened_at.isoformat(),
            "expires_at": (opened_at + CANARY_WINDOW_DURATION).isoformat(),
            "opened_by": actor_value,
            "policy_chain_ref": policy_chain_ref,
            "control_policy": policy_reference,
        }
        _set_feature(workspace, True)
        audit_id = _emit_required_audit(
            db,
            workspace=workspace,
            system=system,
            event_type="lot8.value_loop.canary_window.opened",
            actor=actor_value,
            details={
                "system_id": system.id,
                "revision": revision,
                "expires_at": proof_window["expires_at"],
                "feature": FEATURE_KEY,
                "claim_promoted": False,
                "policy_chain_ref": proof_window["policy_chain_ref"],
                "control_policy_revision": policy_reference["revision"],
                "control_policy_sha256": policy_reference["sha256"],
            },
        )
        proof_window["audit_id"] = audit_id
        state["proof_window"] = proof_window
        _save_state(system, state)
        db.commit()
        report["proof_window"] = proof_window
        return report
    except Exception:
        db.rollback()
        raise


def _exact_keys(value: Mapping[str, Any], expected: set[str], *, field: str) -> None:
    actual = set(value)
    if actual != expected:
        raise ValueLoopRolloutError(
            f"{field} fields differ from the contract; "
            f"missing={sorted(expected - actual)} extra={sorted(actual - expected)}"
        )


def _validated_trusted_runner(
    value: Mapping[str, Any] | None,
    *,
    revision: str,
) -> dict[str, Any]:
    try:
        return _trusted_runner_metadata(value, revision=revision)
    except AuthorizationPromotionError as exc:
        raise ValueLoopRolloutError(f"untrusted Lot 8 runner: {exc}") from exc


def _current_trusted_runner(*, token_env: str, audience: str | None) -> dict[str, Any]:
    try:
        return _trusted_runner_from_ci(token_env=token_env, audience=audience)
    except AuthorizationPromotionError as exc:
        raise ValueLoopRolloutError(str(exc)) from exc


def _require_same_trusted_runner(
    producer: Mapping[str, Any],
    current: Mapping[str, Any] | None,
    *,
    revision: str,
) -> dict[str, Any]:
    current_runner = _validated_trusted_runner(current, revision=revision)
    if current_runner != dict(producer):
        raise ValueLoopRolloutError(
            "--apply activation must run in the same protected GitLab job that "
            "produced the evidence"
        )
    return current_runner


def _source_junit(payload: Mapping[str, Any]) -> dict[str, str]:
    source = _record(payload.get("source_junit"))
    _exact_keys(
        source,
        {"media_type", "sha256", "artifact_ref"},
        field="source_junit",
    )
    digest = str(source.get("sha256") or "").strip().lower()
    artifact_ref = str(source.get("artifact_ref") or "").strip().lower()
    if (
        source.get("media_type") != "application/junit+xml"
        or re.fullmatch(r"[0-9a-f]{64}", digest) is None
        or artifact_ref != f"sha256:{digest}"
    ):
        raise ValueLoopRolloutError("source_junit must be a content-addressed JUnit artifact")
    return {
        "media_type": "application/junit+xml",
        "sha256": digest,
        "artifact_ref": artifact_ref,
    }


def _runner_artifact(payload: Mapping[str, Any], *, expected: Mapping[str, str]) -> dict[str, Any]:
    artifact = _record(payload.get("runner_artifact"))
    _exact_keys(
        artifact,
        {"format", "content_base64", "artifact_ref"},
        field="runner_artifact",
    )
    if artifact.get("format") != "junit_xml":
        raise ValueLoopRolloutError("runner_artifact.format must be junit_xml")
    encoded = artifact.get("content_base64")
    if not isinstance(encoded, str) or not encoded:
        raise ValueLoopRolloutError("runner_artifact.content_base64 is required")
    if len(encoded) > ((EVIDENCE_ARTIFACT_MAX_BYTES + 2) // 3) * 4:
        raise ValueLoopRolloutError("runner_artifact has an invalid size")
    try:
        content = base64.b64decode(encoded, validate=True)
    except (TypeError, ValueError) as exc:
        raise ValueLoopRolloutError("runner_artifact is not valid base64") from exc
    if not content or len(content) > EVIDENCE_ARTIFACT_MAX_BYTES:
        raise ValueLoopRolloutError("runner_artifact has an invalid size")
    artifact_ref = f"sha256:{hashlib.sha256(content).hexdigest()}"
    if artifact.get("artifact_ref") != artifact_ref:
        raise ValueLoopRolloutError("runner_artifact.artifact_ref differs from its bytes")
    if b"<!DOCTYPE" in content.upper() or b"<!ENTITY" in content.upper():
        raise ValueLoopRolloutError("runner_artifact XML declarations are forbidden")
    try:
        root = ElementTree.fromstring(content)
    except ElementTree.ParseError as exc:
        raise ValueLoopRolloutError("runner_artifact is not valid XML") from exc
    if root.tag != "testsuite" or root.get("name") != EVIDENCE_SUITE:
        raise ValueLoopRolloutError(f"runner_artifact must use suite {EVIDENCE_SUITE}")
    try:
        counts = {
            name: int(root.get(name, ""))
            for name in ("tests", "failures", "errors", "skipped")
        }
    except ValueError as exc:
        raise ValueLoopRolloutError("runner_artifact counters must be integers") from exc
    cases = root.findall("./testcase")
    names = {str(case.get("name") or "") for case in cases}
    if (
        counts != {"tests": len(REQUIRED_CHECKS), "failures": 0, "errors": 0, "skipped": 0}
        or len(cases) != len(REQUIRED_CHECKS)
        or names != set(REQUIRED_CHECKS)
        or any(
            case.find("failure") is not None
            or case.find("error") is not None
            or case.find("skipped") is not None
            for case in cases
        )
    ):
        raise ValueLoopRolloutError(
            "runner_artifact must pass exactly the eight required behaviour checks"
        )
    properties_node = root.find("./properties")
    properties = {}
    if properties_node is not None:
        nodes = properties_node.findall("property")
        names = [str(node.get("name") or "") for node in nodes]
        if "" in names or len(names) != len(set(names)):
            raise ValueLoopRolloutError("runner_artifact has duplicate properties")
        properties = {
            name: str(node.get("value") or "")
            for name, node in zip(names, nodes, strict=True)
        }
    if properties != dict(expected):
        raise ValueLoopRolloutError("runner_artifact properties differ from the target")
    return {"artifact_ref": artifact_ref, "test_count": len(cases)}


def _validated_records(
    db: DBSession,
    *,
    workspace: Workspace,
    system: System,
    records: Mapping[str, Any],
    lock: bool,
) -> dict[str, str]:
    normalized = {name: str(records.get(name) or "").strip() for name in REQUIRED_RECORDS}
    if any(not value for value in normalized.values()):
        raise ValueLoopRolloutError("all value-loop record identifiers are required")
    if len(set(normalized.values())) != len(normalized):
        raise ValueLoopRolloutError("value-loop record identifiers must be distinct")

    def one(model: type[Any], identifier: str) -> Any:
        query = db.query(model).filter(
            model.id == identifier,
            model.workspace_id == workspace.id,
        )
        if lock:
            query = query.populate_existing().with_for_update(of=model)
        row = query.one_or_none()
        if row is None:
            raise ValueLoopRolloutError(
                f"evidence record {model.__name__} does not belong to the Workspace"
            )
        return row

    scenario = one(ValueScenario, normalized["scenario_id"])
    decision = one(Decision, normalized["decision_id"])
    simulation = one(ValueSimulation, normalized["simulation_id"])
    action = one(ValueActionExecution, normalized["action_execution_id"])
    measurement = one(ValueMeasurement, normalized["measurement_id"])
    if scenario.system_id != system.id or scenario.status != "measured":
        raise ValueLoopRolloutError("evidence scenario is not measured on the canary System")
    if (
        decision.scenario_id != scenario.id
        or decision.target_id != system.id
        or decision.scope != "system"
        or decision.kind != "value_loop"
        or decision.status != "applied"
    ):
        raise ValueLoopRolloutError("evidence Decision is not the applied System Decision")
    if (
        simulation.scenario_id != scenario.id
        or simulation.system_id != system.id
        or simulation.status != "available"
        or _record(simulation.projected_outcome).get("evidence_type") != "simulation"
    ):
        raise ValueLoopRolloutError("evidence simulation is not a labelled forecast")
    if (
        scenario.approved_simulation_id != simulation.id
        or action.scenario_id != scenario.id
        or action.simulation_id != simulation.id
        or action.system_id != system.id
        or action.status != "succeeded"
        or action.actuator != CONTROL_POLICY_GUARDRAILS_PATCH_V1
    ):
        raise ValueLoopRolloutError("evidence action does not match the approved simulation")
    if (
        measurement.scenario_id != scenario.id
        or measurement.action_execution_id != action.id
        or measurement.simulation_id != simulation.id
        or measurement.system_id != system.id
        or measurement.status != "measured"
        or not measurement.source_run_id
        or not isinstance(measurement.observed_outcome, Mapping)
        or measurement.observed_outcome.get("source_type") != "run"
        or not isinstance(measurement.forecast_delta, Mapping)
        or measurement.assumption_verdict
        not in {"confirmed", "partially_confirmed", "not_confirmed"}
        or not isinstance(measurement.assumption_evaluation, Mapping)
        or measurement.assumption_evaluation.get("verdict")
        != measurement.assumption_verdict
        or measurement.assumption_evaluation.get("causality")
        != "not_established"
    ):
        raise ValueLoopRolloutError("evidence measurement is not a real post-action outcome")
    if measurement.observed_outcome == simulation.projected_outcome:
        raise ValueLoopRolloutError("simulation and measurement evidence are conflated")
    if action.control_policy_id != system.control_policy_id:
        raise ValueLoopRolloutError("evidence action did not mutate the canary ControlPolicy")
    control = _control_policy(
        db,
        workspace=workspace,
        system=system,
        lock=lock,
    )
    action_after = _record(action.after_state).get("_control_policy")
    validated_after = validated_control_policy_execution_contract(
        action_after,
        policy_id=control.id,
    )
    if (
        validated_after is None
        or validated_after != control_policy_execution_contract(control)
    ):
        raise ValueLoopRolloutError(
            "the current ControlPolicy differs from the evidenced post-Act state"
        )

    def evidence_run(identifier: str | None) -> Run | None:
        query = db.query(Run).filter(
            Run.id == identifier,
            Run.workspace_id == workspace.id,
            Run.system_id == system.id,
            Run.status == "completed",
        )
        if lock:
            query = query.populate_existing().with_for_update(of=Run)
        return query.one_or_none()

    baseline = evidence_run(scenario.source_run_id)
    observed = evidence_run(measurement.source_run_id)
    if (
        baseline is None
        or observed is None
        or _record(scenario.baseline_outcome).get("run_id") != baseline.id
        or _record(measurement.observed_outcome).get("run_id") != observed.id
        or observed.started_at is None
        or observed.completed_at is None
        or observed.started_at < action.executed_at
        or observed.completed_at < action.executed_at
    ):
        raise ValueLoopRolloutError(
            "evidence baseline and measurement Runs are not tenant-scoped post-action facts"
        )

    expected_operations = {
        scenario.operation_id: ("scenario.create", "value_scenario", scenario.id),
        simulation.operation_id: ("simulate", "value_simulation", simulation.id),
        scenario.approval_operation_id: ("approve", "value_scenario", scenario.id),
        action.operation_id: ("act", "value_action_execution", action.id),
        measurement.operation_id: ("measure", "value_measurement", measurement.id),
    }
    if None in expected_operations or len(expected_operations) != 5:
        raise ValueLoopRolloutError("value-loop operation receipts are incomplete")
    receipts = db.query(ValueLoopOperation).filter(
        ValueLoopOperation.workspace_id == workspace.id,
        ValueLoopOperation.id.in_(list(expected_operations)),
    ).all()
    if len(receipts) != 5 or any(
        (row.operation, row.result_type, row.result_id) != expected_operations[row.id]
        for row in receipts
    ):
        raise ValueLoopRolloutError("value-loop idempotency receipts are inconsistent")

    audit_contracts = {
        "value_loop.scenario.created": {
            "scenario_id": scenario.id,
            "decision_id": decision.id,
        },
        "value_loop.simulation.created": {
            "scenario_id": scenario.id,
            "simulation_id": simulation.id,
        },
        "value_loop.scenario.approved": {
            "scenario_id": scenario.id,
            "simulation_id": simulation.id,
        },
        "value_loop.action.executed": {
            "scenario_id": scenario.id,
            "action_execution_id": action.id,
        },
        "value_loop.measurement.measured": {
            "scenario_id": scenario.id,
            "measurement_id": measurement.id,
        },
    }
    audits = db.query(AuditLog).filter(
        AuditLog.workspace_id == workspace.id,
        AuditLog.event_type.in_(list(audit_contracts)),
    ).all()
    for event_type, expected_details in audit_contracts.items():
        if not any(
            row.event_type == event_type
            and isinstance(row.details, Mapping)
            and all(row.details.get(key) == value for key, value in expected_details.items())
            for row in audits
        ):
            raise ValueLoopRolloutError(f"authoritative audit is missing for {event_type}")
    return normalized


def validate_evidence(
    db: DBSession,
    evidence: Mapping[str, Any],
    *,
    workspace: Workspace,
    system: System,
    revision: str,
    lock_records: bool,
) -> dict[str, Any]:
    payload = _record(evidence)
    _exact_keys(
        payload,
        {
            "schema_version",
            "kind",
            "revision",
            "validated_at",
            "validated_by",
            "observation_ref",
            "subject",
            "records",
            "checks",
            "trusted_runner",
            "source_junit",
            "runner_artifact",
        },
        field="evidence",
    )
    if payload.get("schema_version") != EVIDENCE_SCHEMA_VERSION:
        raise ValueLoopRolloutError(
            f"evidence schema_version must be {EVIDENCE_SCHEMA_VERSION}"
        )
    if payload.get("kind") != EVIDENCE_KIND:
        raise ValueLoopRolloutError(f"evidence kind must be {EVIDENCE_KIND}")
    if payload.get("revision") != revision:
        raise ValueLoopRolloutError("evidence revision differs from the runtime revision")
    validated_by = str(payload.get("validated_by") or "").strip()
    if not validated_by:
        raise ValueLoopRolloutError("evidence validated_by is required")
    validated_at = _parse_utc(payload.get("validated_at"), field="validated_at")
    now = datetime.now(UTC)
    if validated_at > now + EVIDENCE_FUTURE_TOLERANCE:
        raise ValueLoopRolloutError("evidence is dated in the future")
    if now - validated_at > EVIDENCE_MAX_AGE:
        raise ValueLoopRolloutError("evidence is older than 24 hours")
    observation_ref = str(payload.get("observation_ref") or "")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", observation_ref):
        raise ValueLoopRolloutError("evidence observation_ref must be content-addressed")

    producer = _validated_trusted_runner(
        payload.get("trusted_runner"),
        revision=revision,
    )
    source_junit = _source_junit(payload)

    subject = _record(payload.get("subject"))
    expected_subject = {"workspace_id": workspace.id, "system_id": system.id}
    _exact_keys(subject, set(expected_subject), field="evidence subject")
    if subject != expected_subject:
        raise ValueLoopRolloutError("evidence subject differs from the rollout target")
    checks = _record(payload.get("checks"))
    _exact_keys(checks, set(REQUIRED_CHECKS), field="evidence checks")
    if any(checks.get(name) is not True for name in REQUIRED_CHECKS):
        raise ValueLoopRolloutError("every required value-loop behaviour check must pass")
    records = _record(payload.get("records"))
    _exact_keys(records, set(REQUIRED_RECORDS), field="evidence records")
    normalized_records = _validated_records(
        db,
        workspace=workspace,
        system=system,
        records=records,
        lock=lock_records,
    )
    artifact = _runner_artifact(
        payload,
        expected={
            "revision": revision,
            "workspace_id": workspace.id,
            "system_id": system.id,
            "observation_ref": observation_ref,
            "source_junit_ref": source_junit["artifact_ref"],
        },
    )
    return {
        "evidence_ref": f"sha256:{_canonical_sha256(payload)}",
        "artifact_ref": artifact["artifact_ref"],
        "runner_test_count": artifact["test_count"],
        "revision": revision,
        "validated_at": validated_at.isoformat(),
        "validated_by": validated_by,
        "observation_ref": observation_ref,
        "trusted_runner": producer,
        "source_junit_ref": source_junit["artifact_ref"],
        "records": normalized_records,
        "checks": {name: True for name in REQUIRED_CHECKS},
    }


def activate(
    db: DBSession,
    *,
    workspace_id: str,
    system_id: str | None = None,
    evidence: Mapping[str, Any] | None,
    apply: bool,
    actor: str,
    trusted_runner: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    workspace, system, derived = discover_target(
        db,
        workspace_id=workspace_id,
        system_id=system_id,
        lock=apply,
        allow_system360_fallback=False,
    )
    if derived and system_id is None:  # Defensive for marker-only discovery.
        raise ValueLoopRolloutError("prepare must persist the Lot 8 marker first")
    policy = _control_policy(db, workspace=workspace, system=system, lock=apply)
    prepared, reason = _prepared_contract(policy, system)
    if not prepared:
        raise ValueLoopRolloutError(f"Lot 8 actuator is not prepared: {reason}")
    _raw, parsed = _membrane(policy)
    if parsed.effective_mode is not EnforcementMode.ENFORCE:
        raise ValueLoopRolloutError("activation requires MembraneSpec v2 enforce")
    _require_authorization_enforce(
        db,
        workspace=workspace,
        lock=apply,
    )
    state = _state(system)
    prepared_state = state.get("prepared")
    if (
        not isinstance(prepared_state, Mapping)
        or prepared_state.get("system_id") != system.id
        or prepared_state.get("contract_sha256") != _prepared_contract_sha256()
    ):
        raise ValueLoopRolloutError("prepare must persist the Lot 8 rollout contract first")
    revision = _runtime_revision()
    metadata = None
    if evidence is not None:
        metadata = validate_evidence(
            db,
            evidence,
            workspace=workspace,
            system=system,
            revision=revision,
            lock_records=apply,
        )
    if apply:
        if metadata is None:
            raise ValueLoopRolloutError("--apply requires content-addressed behaviour evidence")
        _require_same_trusted_runner(
            metadata["trusted_runner"],
            trusted_runner,
            revision=revision,
        )
    latest = state["activations"][-1] if state["activations"] else None
    proof_window = _active_proof_window(
        state,
        system_id=system.id,
        revision=revision,
    )
    already_active = bool(
        _feature_enabled(workspace)
        and isinstance(latest, Mapping)
        and metadata is not None
        and latest.get("evidence_ref") == metadata.get("evidence_ref")
        and latest.get("revision") == revision
        and value_loop_enabled(db, workspace=workspace, system=system)
    )
    report = {
        "schema_version": 1,
        "operation": "apply" if apply else "dry_run",
        "direction": "activate",
        "workspace_id": workspace.id,
        "system_id": system.id,
        "revision": revision,
        "evidence_required": metadata is None,
        "changed": not already_active,
        "validation": metadata,
    }
    if not apply or already_active:
        return report
    if metadata is None:  # Defensive: apply is rejected above and dry-runs returned.
        raise ValueLoopRolloutError("--apply requires content-addressed behaviour evidence")
    actor_value = _require_actor(actor)
    try:
        if proof_window is not None:
            if not value_loop_enabled(db, workspace=workspace, system=system):
                raise ValueLoopRolloutError(
                    "the canary ControlPolicy differs from its authorized policy chain"
                )
            policy_chain_ref = str(proof_window["policy_chain_ref"])
            policy_reference = dict(proof_window["control_policy"])
            policy_chain_created_at = str(proof_window["opened_at"])
        else:
            policy_reference = control_policy_execution_contract(policy)
            policy_chain_created_at = datetime.now(UTC).isoformat()
            policy_chain_ref = value_loop_policy_chain_reference(
                system_id=system.id,
                revision=revision,
                created_at=policy_chain_created_at,
                control_policy=policy_reference,
            )
            if policy_chain_ref is None:  # Defensive: inputs are validated above.
                raise ValueLoopRolloutError("could not content-address the policy root")
        activated_at = datetime.now(UTC).isoformat()
        activation = {
            **metadata,
            "system_id": system.id,
            "activated_at": activated_at,
            "activated_by": actor_value,
            "policy_chain_ref": policy_chain_ref,
            "policy_chain_created_at": policy_chain_created_at,
            "control_policy": policy_reference,
        }
        _set_feature(workspace, True)
        state["proof_window"] = None
        audit_id = _emit_required_audit(
            db,
            workspace=workspace,
            system=system,
            event_type="lot8.value_loop.activated",
            actor=actor_value,
            details={
                "system_id": system.id,
                "revision": revision,
                "evidence_ref": metadata["evidence_ref"],
                "artifact_ref": metadata["artifact_ref"],
                "source_junit_ref": metadata["source_junit_ref"],
                "observation_ref": metadata["observation_ref"],
                "record_ids": metadata["records"],
                "checks": metadata["checks"],
                "runner_test_count": metadata["runner_test_count"],
                "validated_at": metadata["validated_at"],
                "validated_by": metadata["validated_by"],
                "activated_at": activated_at,
                "trusted_runner": metadata["trusted_runner"],
                "feature": FEATURE_KEY,
                "policy_chain_ref": policy_chain_ref,
                "policy_chain_created_at": policy_chain_created_at,
                "control_policy_revision": policy_reference["revision"],
                "control_policy_sha256": policy_reference["sha256"],
                "claim_promoted": True,
            },
        )
        activation["audit_id"] = audit_id
        state["activations"].append(activation)
        _save_state(system, state)
        db.commit()
        return report
    except Exception:
        db.rollback()
        raise


def _rollout_state_engaged(state: Mapping[str, Any]) -> bool:
    if state.get("proof_window") is not None:
        return True
    activations = state.get("activations")
    deactivations = state.get("deactivations")
    if not isinstance(activations, list) or not isinstance(deactivations, list):
        raise ValueLoopRolloutError("invalid Lot 8 activation history")
    try:
        activated_at = max(
            (
                _parse_utc(row.get("activated_at"), field="activation.activated_at")
                for row in activations
            ),
            default=None,
        )
        deactivated_at = max(
            (
                _parse_utc(
                    row.get("deactivated_at"),
                    field="deactivation.deactivated_at",
                )
                for row in deactivations
            ),
            default=None,
        )
    except AttributeError as exc:  # Defensive; _state validates row mappings.
        raise ValueLoopRolloutError("invalid Lot 8 activation history") from exc
    return bool(
        activated_at is not None
        and (deactivated_at is None or activated_at > deactivated_at)
    )


def _other_requested_system_ids(
    db: DBSession,
    *,
    workspace: Workspace,
    excluded_system_id: str,
) -> list[str]:
    systems = (
        db.query(System)
        .filter(
            System.workspace_id == workspace.id,
            System.status == "active",
            System.id != excluded_system_id,
        )
        .order_by(System.id.asc())
        .all()
    )
    return [
        str(system.id)
        for system in systems
        if value_loop_requested(db, workspace=workspace, system=system)
    ]


def deactivate(
    db: DBSession,
    *,
    workspace_id: str,
    system_id: str | None = None,
    apply: bool,
    actor: str,
) -> dict[str, Any]:
    workspace, system, _derived = discover_target(
        db,
        workspace_id=workspace_id,
        system_id=system_id,
        lock=apply,
        allow_system360_fallback=False,
    )
    state = _state(system)
    engaged = _rollout_state_engaged(state)
    other_requested_ids = _other_requested_system_ids(
        db,
        workspace=workspace,
        excluded_system_id=system.id,
    )
    report = {
        "schema_version": 1,
        "operation": "apply" if apply else "dry_run",
        "direction": "deactivate",
        "workspace_id": workspace.id,
        "system_id": system.id,
        "changed": engaged,
        "workspace_feature_remains_enabled": bool(other_requested_ids),
        "other_requested_system_ids": other_requested_ids,
        "preserved": [
            "system marker",
            "actuator configuration",
            "Membrane allow-list",
            "value-loop records",
            "activation evidence",
        ],
    }
    if not apply or not engaged:
        return report
    actor_value = _require_actor(actor)
    try:
        state["proof_window"] = None
        deactivation = {
            "system_id": system.id,
            "deactivated_at": datetime.now(UTC).isoformat(),
            "deactivated_by": actor_value,
            "activation_ref": (
                state["activations"][-1].get("evidence_ref")
                if state["activations"]
                else None
            ),
        }
        state["deactivations"].append(deactivation)
        _save_state(system, state)
        other_requested_ids = _other_requested_system_ids(
            db,
            workspace=workspace,
            excluded_system_id=system.id,
        )
        _set_feature(workspace, bool(other_requested_ids))
        _emit_required_audit(
            db,
            workspace=workspace,
            system=system,
            event_type="lot8.value_loop.deactivated",
            actor=actor_value,
            details={
                "system_id": system.id,
                "feature": FEATURE_KEY,
                "workspace_feature_enabled": bool(other_requested_ids),
                "other_requested_system_ids": other_requested_ids,
                "preserved_additive_state": True,
            },
        )
        db.commit()
        return report
    except Exception:
        db.rollback()
        raise


def _load_evidence(path: str | None) -> Mapping[str, Any] | None:
    if path is None:
        return None
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueLoopRolloutError(f"cannot load evidence: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise ValueLoopRolloutError("evidence root must be an object")
    return payload


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("status", "prepare", "open-canary", "activate", "deactivate"):
        child = subparsers.add_parser(command)
        child.add_argument("--workspace-id", required=True)
        child.add_argument(
            "--system-id",
            help="runtime-discovered tenant-scoped target; never a code-owned ID",
        )
        if command != "status":
            child.add_argument("--apply", action="store_true")
            child.add_argument("--actor", default="")
        if command == "activate":
            child.add_argument("--evidence")
            child.add_argument(
                "--oidc-token-env",
                default="AGENTIUM_ATTESTATION_ID_TOKEN",
            )
            child.add_argument("--oidc-audience")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        with SessionLocal() as db:
            if args.command == "status":
                result = status(
                    db,
                    workspace_id=args.workspace_id,
                    system_id=args.system_id,
                )
            elif args.command == "prepare":
                result = prepare(
                    db,
                    workspace_id=args.workspace_id,
                    system_id=args.system_id,
                    apply=args.apply,
                    actor=args.actor,
                )
            elif args.command == "open-canary":
                result = open_canary_window(
                    db,
                    workspace_id=args.workspace_id,
                    system_id=args.system_id,
                    apply=args.apply,
                    actor=args.actor,
                )
            elif args.command == "activate":
                trusted_runner = (
                    _current_trusted_runner(
                        token_env=args.oidc_token_env,
                        audience=args.oidc_audience,
                    )
                    if args.apply
                    else None
                )
                result = activate(
                    db,
                    workspace_id=args.workspace_id,
                    system_id=args.system_id,
                    evidence=_load_evidence(args.evidence),
                    apply=args.apply,
                    actor=args.actor,
                    trusted_runner=trusted_runner,
                )
            else:
                result = deactivate(
                    db,
                    workspace_id=args.workspace_id,
                    system_id=args.system_id,
                    apply=args.apply,
                    actor=args.actor,
                )
        print(json.dumps(result, sort_keys=True, indent=2, default=str))
        return 0
    except ValueLoopRolloutError as exc:
        print(json.dumps({"error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover - CLI boundary
    raise SystemExit(main())
