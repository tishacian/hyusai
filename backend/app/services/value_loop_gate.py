"""Structural, fail-closed gate for the Lot 8 System value loop.

The feature is never selected by workspace slug, System name or a fixed ID.
An operator must explicitly enable the workspace feature and exactly one
System must carry the canary marker.  Seed code may prepare the marker and the
actuator contract while leaving the workspace feature disabled.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from app.core.config import settings
from app.models.audit import AuditLog
from app.models.system import System
from app.services.control_policy_snapshot import (
    control_policy_execution_contract,
    validated_control_policy_execution_contract,
)
from app.services.value_loop_authorization import value_loop_authorization_ready
from app.services.value_loop_contract import validate_value_loop_runtime_contract

FEATURE_KEY = "value_loop_v1"
CANARY_MARKER_KEY = "value_loop_canary"
CANARY_MARKER_VALUE = "v1"
ROLLOUT_STATE_KEY = "_lot8_value_loop_rollout_v1"
ROLLOUT_SCHEMA_VERSION = 1

_GIT_SHA = re.compile(r"[0-9a-f]{40}")
_SHA256_REF = re.compile(r"sha256:[0-9a-f]{64}")


def _settings(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def system_has_value_loop_marker(system: System | Any) -> bool:
    settings = _settings(getattr(system, "settings", None))
    experience = _settings(settings.get("experience"))
    return experience.get(CANARY_MARKER_KEY) == CANARY_MARKER_VALUE


def value_loop_policy_chain_reference(
    *,
    system_id: str,
    revision: str,
    created_at: str,
    control_policy: Mapping[str, Any],
) -> str | None:
    """Content-address a chain root so settings edits cannot re-bless drift."""

    policy = validated_control_policy_execution_contract(control_policy)
    if (
        not str(system_id or "").strip()
        or _GIT_SHA.fullmatch(str(revision or "").strip().lower()) is None
        or policy is None
    ):
        return None
    try:
        timestamp = datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            return None
        normalized_timestamp = timestamp.astimezone(UTC).isoformat()
    except (TypeError, ValueError):
        return None
    payload = {
        "system_id": str(system_id),
        "revision": str(revision).lower(),
        "created_at": normalized_timestamp,
        "control_policy": policy,
    }
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


def _timestamped_history(
    value: Any,
    *,
    field: str,
) -> list[tuple[datetime, Mapping[str, Any]]] | None:
    """Parse the complete append-only history, failing closed on any row."""

    if not isinstance(value, list):
        return None
    result: list[tuple[datetime, Mapping[str, Any]]] = []
    for row in value:
        if not isinstance(row, Mapping):
            return None
        try:
            timestamp = datetime.fromisoformat(str(row.get(field)).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
        if timestamp.tzinfo is None:
            return None
        result.append((timestamp.astimezone(UTC), row))
    return result


def _policy_chain_descriptor(
    state: Mapping[str, Any],
    *,
    system_id: str,
    revision: str,
) -> tuple[str, dict[str, Any]] | None:
    """Resolve the active attested policy root without trusting mutable values."""

    activations = _timestamped_history(state.get("activations"), field="activated_at")
    deactivations = _timestamped_history(
        state.get("deactivations"),
        field="deactivated_at",
    )
    if activations is None or deactivations is None:
        return None
    if activations:
        activated_at, latest = max(activations, key=lambda item: item[0])
        latest_deactivation = (
            max(timestamp for timestamp, _row in deactivations)
            if deactivations
            else None
        )
        reference = validated_control_policy_execution_contract(
            latest.get("control_policy")
        )
        chain_ref = str(latest.get("policy_chain_ref") or "")
        chain_created_at = str(latest.get("policy_chain_created_at") or "")
        if (
            (latest_deactivation is None or activated_at > latest_deactivation)
            and latest.get("system_id") == system_id
            and latest.get("revision") == revision
            and _SHA256_REF.fullmatch(str(latest.get("evidence_ref") or ""))
            is not None
            and _SHA256_REF.fullmatch(str(latest.get("artifact_ref") or ""))
            is not None
            and _SHA256_REF.fullmatch(chain_ref) is not None
            and reference is not None
            and value_loop_policy_chain_reference(
                system_id=system_id,
                revision=revision,
                created_at=chain_created_at,
                control_policy=reference,
            )
            == chain_ref
        ):
            return chain_ref, reference

    proof_window = state.get("proof_window")
    prepared = state.get("prepared")
    if not isinstance(proof_window, Mapping) or not isinstance(prepared, Mapping):
        return None
    if set(proof_window) != {
        "system_id",
        "revision",
        "contract_sha256",
        "opened_at",
        "expires_at",
        "opened_by",
        "policy_chain_ref",
        "control_policy",
    }:
        return None
    reference = validated_control_policy_execution_contract(
        proof_window.get("control_policy")
    )
    chain_ref = str(proof_window.get("policy_chain_ref") or "")
    if (
        proof_window.get("system_id") != system_id
        or proof_window.get("revision") != revision
        or prepared.get("system_id") != system_id
        or proof_window.get("contract_sha256") != prepared.get("contract_sha256")
        or re.fullmatch(
            r"[0-9a-f]{64}", str(proof_window.get("contract_sha256") or "")
        )
        is None
        or _SHA256_REF.fullmatch(chain_ref) is None
        or reference is None
        or value_loop_policy_chain_reference(
            system_id=system_id,
            revision=revision,
            created_at=str(proof_window.get("opened_at") or ""),
            control_policy=reference or {},
        )
        != chain_ref
        or not str(proof_window.get("opened_by") or "").strip()
    ):
        return None
    try:
        opened_at = datetime.fromisoformat(
            str(proof_window.get("opened_at")).replace("Z", "+00:00")
        )
        expires_at = datetime.fromisoformat(
            str(proof_window.get("expires_at")).replace("Z", "+00:00")
        )
        if opened_at.tzinfo is None or expires_at.tzinfo is None:
            return None
        now = datetime.now(UTC)
        opened_at = opened_at.astimezone(UTC)
        expires_at = expires_at.astimezone(UTC)
    except (TypeError, ValueError):
        return None
    if not (opened_at <= now < expires_at and expires_at > opened_at):
        return None
    return chain_ref, reference


def _policy_chain_tip(
    state: Mapping[str, Any],
    *,
    chain_ref: str,
    root: Mapping[str, Any],
) -> dict[str, Any] | None:
    rows = state.get("policy_transitions", [])
    if not isinstance(rows, list) or any(not isinstance(row, Mapping) for row in rows):
        return None
    selected = [dict(row) for row in rows if row.get("policy_chain_ref") == chain_ref]
    try:
        selected.sort(key=lambda row: int(row.get("sequence")))
    except (TypeError, ValueError):
        return None
    expected = dict(root)
    expected_fields = {
        "policy_chain_ref",
        "sequence",
        "action_execution_id",
        "scenario_id",
        "from",
        "to",
        "transitioned_at",
        "actor",
    }
    for index, row in enumerate(selected, start=1):
        if set(row) != expected_fields or row.get("sequence") != index:
            return None
        before = validated_control_policy_execution_contract(row.get("from"))
        after = validated_control_policy_execution_contract(row.get("to"))
        if (
            before != expected
            or after is None
            or not str(row.get("action_execution_id") or "").strip()
            or not str(row.get("scenario_id") or "").strip()
            or not str(row.get("actor") or "").strip()
        ):
            return None
        try:
            transitioned_at = datetime.fromisoformat(
                str(row.get("transitioned_at")).replace("Z", "+00:00")
            )
            if transitioned_at.tzinfo is None:
                return None
        except (TypeError, ValueError):
            return None
        expected = after
    return expected


def _policy_reference_matches(
    *,
    system: System,
    policy: Any,
) -> bool:
    state = _settings(_settings(system.settings).get(ROLLOUT_STATE_KEY))
    revision = str(settings.agentium_image_revision or "").strip().lower()
    descriptor = _policy_chain_descriptor(
        state,
        system_id=system.id,
        revision=revision,
    )
    if descriptor is None:
        return False
    chain_ref, root = descriptor
    if root.get("policy_id") != policy.id:
        return False
    tip = _policy_chain_tip(state, chain_ref=chain_ref, root=root)
    return tip == control_policy_execution_contract(policy)


def record_authorized_policy_transition(
    system: System,
    *,
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    action_execution_id: str,
    scenario_id: str,
    actor: str,
) -> bool:
    """Append the sole accepted policy-reference movement during an Act.

    The caller holds both the System and ControlPolicy locks and commits this
    state in the same transaction as the actuator and its audit row.
    """

    settings_payload = copy.deepcopy(dict(_settings(system.settings)))
    state = copy.deepcopy(dict(_settings(settings_payload.get(ROLLOUT_STATE_KEY))))
    if not state:
        return False
    activations = _timestamped_history(state.get("activations"), field="activated_at")
    deactivations = _timestamped_history(
        state.get("deactivations"),
        field="deactivated_at",
    )
    if activations is None or deactivations is None:
        raise RuntimeError("value-loop policy history is invalid")
    latest_activation = max(activations, key=lambda item: item[0]) if activations else None
    latest_deactivation = (
        max(timestamp for timestamp, _row in deactivations)
        if deactivations
        else None
    )
    active_activation = bool(
        latest_activation is not None
        and (
            latest_deactivation is None
            or latest_activation[0] > latest_deactivation
        )
    )
    if not active_activation and not isinstance(state.get("proof_window"), Mapping):
        # ``prepare`` is additive and does not yet own policy movement. Direct
        # service tests and disabled rollouts therefore remain legitimate.
        return False
    revision = str(settings.agentium_image_revision or "").strip().lower()
    descriptor = _policy_chain_descriptor(
        state,
        system_id=system.id,
        revision=revision,
    )
    if descriptor is None:
        raise RuntimeError("active value-loop policy reference is invalid")
    chain_ref, root = descriptor
    tip = _policy_chain_tip(state, chain_ref=chain_ref, root=root)
    canonical_before = validated_control_policy_execution_contract(before)
    canonical_after = validated_control_policy_execution_contract(after)
    if tip is None or canonical_before != tip or canonical_after is None:
        raise RuntimeError("ControlPolicy drifted outside the authorized value-loop Act")
    rows = state.get("policy_transitions", [])
    selected_count = len(
        [row for row in rows if row.get("policy_chain_ref") == chain_ref]
    )
    rows.append(
        {
            "policy_chain_ref": chain_ref,
            "sequence": selected_count + 1,
            "action_execution_id": str(action_execution_id),
            "scenario_id": str(scenario_id),
            "from": canonical_before,
            "to": canonical_after,
            "transitioned_at": datetime.now(UTC).isoformat(),
            "actor": str(actor),
        }
    )
    state["policy_transitions"] = rows
    settings_payload[ROLLOUT_STATE_KEY] = state
    system.settings = settings_payload
    return True


def value_loop_requested(
    db: Any,
    *,
    workspace: Any,
    system: System,
) -> bool:
    """Return true when the attested rollout selects this unique System.

    This selection deliberately does not validate the actuator objects.  Read
    projections use it to expose an explicit ``not_configured`` actuator when
    the rollout remains selected but its current contract has drifted.  All
    executable endpoints continue to use :func:`value_loop_enabled` and thus
    fail closed.
    """

    workspace_settings = _settings(getattr(workspace, "settings", None))
    features = _settings(workspace_settings.get("features"))
    if features.get(FEATURE_KEY) is not True:
        return False
    workspace_id = str(getattr(workspace, "id", "") or "")
    if not workspace_id or getattr(system, "workspace_id", None) != workspace_id:
        return False
    if not system_has_value_loop_marker(system):
        return False

    marked = [
        row
        for row in db.query(System)
        .filter(System.workspace_id == workspace_id, System.status == "active")
        .all()
        if system_has_value_loop_marker(row)
    ]
    if len(marked) != 1 or marked[0].id != system.id:
        return False
    # The feature is rollout-owned, but the runtime also binds it to the
    # attestation persisted on the unique canary.  This closes two otherwise
    # silent failure modes: a generic settings write enabling the feature, and
    # an old behavioural proof remaining authoritative after a new deploy.
    system_settings = _settings(getattr(system, "settings", None))
    state = _settings(system_settings.get(ROLLOUT_STATE_KEY))
    if state.get("schema_version") != ROLLOUT_SCHEMA_VERSION:
        return False
    revision = str(settings.agentium_image_revision or "").strip().lower()
    if _GIT_SHA.fullmatch(revision) is None:
        return False
    activations = _timestamped_history(
        state.get("activations"),
        field="activated_at",
    )
    deactivations = _timestamped_history(
        state.get("deactivations"),
        field="deactivated_at",
    )
    if activations is None or deactivations is None:
        return False
    descriptor = _policy_chain_descriptor(
        state,
        system_id=system.id,
        revision=revision,
    )
    if descriptor is None:
        return False
    if activations:
        activated_at, latest = max(activations, key=lambda item: item[0])
        latest_deactivation = (
            max(timestamp for timestamp, _row in deactivations)
            if deactivations
            else None
        )
        if (
            (latest_deactivation is None or activated_at > latest_deactivation)
            and latest.get("system_id") == system.id
            and latest.get("revision") == revision
            and _SHA256_REF.fullmatch(str(latest.get("evidence_ref") or ""))
            is not None
            and _SHA256_REF.fullmatch(str(latest.get("artifact_ref") or ""))
            is not None
            and latest.get("policy_chain_ref") == descriptor[0]
            and validated_control_policy_execution_contract(
                latest.get("control_policy")
            )
            == descriptor[1]
        ):
            return True

    # Before the first activation, an operator may open a short, audited
    # proof window. It is bound to the exact runtime revision and prepared
    # contract, and expires closed. This breaks the otherwise circular gate
    # (behaviour proof requires the API that the proof will later activate)
    # without treating the window itself as activation evidence.
    proof_window = state.get("proof_window")
    prepared = state.get("prepared")
    if not isinstance(proof_window, Mapping) or not isinstance(prepared, Mapping):
        return False
    if set(proof_window) != {
        "system_id",
        "revision",
        "contract_sha256",
        "opened_at",
        "expires_at",
        "opened_by",
        "policy_chain_ref",
        "control_policy",
    }:
        return False
    if (
        proof_window.get("system_id") != system.id
        or proof_window.get("revision") != revision
        or prepared.get("system_id") != system.id
        or proof_window.get("contract_sha256") != prepared.get("contract_sha256")
        or re.fullmatch(
            r"[0-9a-f]{64}", str(proof_window.get("contract_sha256") or "")
        )
        is None
        or not str(proof_window.get("opened_by") or "").strip()
        or proof_window.get("policy_chain_ref") != descriptor[0]
        or validated_control_policy_execution_contract(
            proof_window.get("control_policy")
        )
        != descriptor[1]
    ):
        return False
    try:
        opened_at = datetime.fromisoformat(
            str(proof_window.get("opened_at")).replace("Z", "+00:00")
        )
        expires_at = datetime.fromisoformat(
            str(proof_window.get("expires_at")).replace("Z", "+00:00")
        )
        if opened_at.tzinfo is None or expires_at.tzinfo is None:
            return False
        now = datetime.now(UTC)
        opened_at = opened_at.astimezone(UTC)
        expires_at = expires_at.astimezone(UTC)
    except (TypeError, ValueError):
        return False
    if not (opened_at <= now < expires_at and expires_at > opened_at):
        return False
    audits = db.query(AuditLog).filter(
        AuditLog.workspace_id == workspace_id,
        AuditLog.event_type == "lot8.value_loop.canary_window.opened",
        AuditLog.agent_id == system.id,
        AuditLog.actor == str(proof_window.get("opened_by")),
    ).all()
    return any(
        isinstance(row.details, Mapping)
        and row.details.get("system_id") == system.id
        and row.details.get("revision") == revision
        and row.details.get("expires_at") == proof_window.get("expires_at")
        and row.details.get("claim_promoted") is False
        for row in audits
    )


def value_loop_enabled(
    db: Any,
    *,
    workspace: Any,
    system: System,
) -> bool:
    """Return true only when rollout selection and actuator authority agree."""

    if not value_loop_requested(db, workspace=workspace, system=system):
        return False
    workspace_id = str(getattr(workspace, "id", "") or "")
    if not value_loop_authorization_ready(db, workspace_id=workspace_id):
        return False
    contract = validate_value_loop_runtime_contract(
        db,
        workspace_id=workspace_id,
        system=system,
    )
    return bool(
        contract.valid
        and contract.policy is not None
        and _policy_reference_matches(system=system, policy=contract.policy)
    )


__all__ = [
    "CANARY_MARKER_KEY",
    "CANARY_MARKER_VALUE",
    "FEATURE_KEY",
    "ROLLOUT_SCHEMA_VERSION",
    "ROLLOUT_STATE_KEY",
    "system_has_value_loop_marker",
    "record_authorized_policy_transition",
    "value_loop_policy_chain_reference",
    "value_loop_enabled",
    "value_loop_requested",
]
