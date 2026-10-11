"""Structural, fail-closed gate for the Lot 8 System value loop.

The feature is never selected by workspace slug, System name or a fixed ID.
An operator must explicitly enable the workspace feature.  The canary marker
selects exactly one preparation/proof target at a time; a promoted System is
then selected by its own persisted activation receipt, independently of where
the canary marker moves next.  Seed code may prepare the marker and actuator
contract while leaving the workspace feature disabled.
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
from app.models.decision import Decision
from app.models.system import System
from app.models.value_loop import (
    ValueActionExecution,
    ValueMeasurement,
    ValueScenario,
    ValueSimulation,
)
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
_SHA256 = re.compile(r"[0-9a-f]{64}")
_SHA256_REF = re.compile(r"sha256:[0-9a-f]{64}")
_ACTIVATION_CHECKS = frozenset(
    {
        "create",
        "simulate",
        "approve",
        "act",
        "measure",
        "idempotency",
        "tenant_isolation",
        "simulation_not_measurement",
    }
)
_ACTIVATION_RECORDS = frozenset(
    {
        "scenario_id",
        "decision_id",
        "simulation_id",
        "action_execution_id",
        "measurement_id",
    }
)
_ACTIVATION_FIELDS = frozenset(
    {
        "evidence_ref",
        "artifact_ref",
        "runner_test_count",
        "revision",
        "validated_at",
        "validated_by",
        "observation_ref",
        "trusted_runner",
        "source_junit_ref",
        "records",
        "checks",
        "system_id",
        "activated_at",
        "activated_by",
        "policy_chain_ref",
        "policy_chain_created_at",
        "control_policy",
        "audit_id",
    }
)


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
        "audit_id",
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
        or not str(proof_window.get("audit_id") or "").strip()
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
    db: Any,
    state: Mapping[str, Any],
    *,
    chain_ref: str,
    root: Mapping[str, Any],
    system: System,
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
        "audit_id",
        "request_sha256",
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
            or not str(row.get("audit_id") or "").strip()
            or _SHA256.fullmatch(str(row.get("request_sha256") or "")) is None
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
        action = (
            db.query(ValueActionExecution)
            .filter(
                ValueActionExecution.id == str(row["action_execution_id"]),
                ValueActionExecution.workspace_id == system.workspace_id,
                ValueActionExecution.system_id == system.id,
                ValueActionExecution.scenario_id == str(row["scenario_id"]),
                ValueActionExecution.status == "succeeded",
            )
            .one_or_none()
        )
        if action is None or action.executed_by != str(row["actor"]):
            return None
        persisted_before = validated_control_policy_execution_contract(
            _settings(action.before_state).get("_control_policy")
        )
        persisted_after = validated_control_policy_execution_contract(
            _settings(action.after_state).get("_control_policy")
        )
        action_timestamp = action.executed_at
        if isinstance(action_timestamp, datetime) and action_timestamp.tzinfo is None:
            action_timestamp = action_timestamp.replace(tzinfo=UTC)
        elif isinstance(action_timestamp, datetime):
            action_timestamp = action_timestamp.astimezone(UTC)
        if (
            persisted_before != before
            or persisted_after != after
            or action.request_sha256 != str(row["request_sha256"])
            or action.control_policy_id != after["policy_id"]
            or action_timestamp != transitioned_at.astimezone(UTC)
        ):
            return None
        scenario = (
            db.query(ValueScenario)
            .filter(
                ValueScenario.id == str(row["scenario_id"]),
                ValueScenario.workspace_id == system.workspace_id,
                ValueScenario.system_id == system.id,
                ValueScenario.approved_simulation_id == action.simulation_id,
            )
            .one_or_none()
        )
        decision = (
            db.query(Decision)
            .filter(
                Decision.workspace_id == system.workspace_id,
                Decision.scenario_id == str(row["scenario_id"]),
                Decision.target_id == system.id,
                Decision.scope == "system",
                Decision.kind == "value_loop",
            )
            .one_or_none()
        )
        if scenario is None or decision is None or not isinstance(action.patch, Mapping):
            return None
        expected_audit_details = {
            "scenario_id": scenario.id,
            "decision_id": decision.id,
            "simulation_id": action.simulation_id,
            "simulation_content_sha256": (
                scenario.approved_simulation_content_sha256
            ),
            "action_execution_id": action.id,
            "system_id": system.id,
            "control_policy_id": action.control_policy_id,
            "control_policy_revision": after["revision"],
            "control_policy_sha256": after["sha256"],
            "actuator": action.actuator,
            "changed_fields": sorted(action.patch),
            "request_sha256": action.request_sha256,
        }
        audit = (
            db.query(AuditLog)
            .filter(
                AuditLog.id == str(row["audit_id"]),
                AuditLog.workspace_id == system.workspace_id,
            )
            .one_or_none()
        )
        audit_timestamp = getattr(audit, "timestamp", None)
        if isinstance(audit_timestamp, datetime) and audit_timestamp.tzinfo is None:
            audit_timestamp = audit_timestamp.replace(tzinfo=UTC)
        elif isinstance(audit_timestamp, datetime):
            audit_timestamp = audit_timestamp.astimezone(UTC)
        if (
            audit is None
            or audit.event_type != "value_loop.action.executed"
            or audit.actor != str(row["actor"])
            or audit_timestamp != transitioned_at.astimezone(UTC)
            or audit.details != expected_audit_details
            or audit.trace_id is not None
            or audit.agent_id is not None
            or audit.severity != "info"
        ):
            return None
        expected = after
    return expected


def _policy_reference_matches(
    db: Any,
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
    tip = _policy_chain_tip(
        db,
        state,
        chain_ref=chain_ref,
        root=root,
        system=system,
    )
    return tip == control_policy_execution_contract(policy)


def record_authorized_policy_transition(
    db: Any,
    system: System,
    *,
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    action_execution_id: str,
    scenario_id: str,
    actor: str,
    audit_id: str,
    request_sha256: str,
    transitioned_at: datetime,
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
    tip = _policy_chain_tip(
        db,
        state,
        chain_ref=chain_ref,
        root=root,
        system=system,
    )
    canonical_before = validated_control_policy_execution_contract(before)
    canonical_after = validated_control_policy_execution_contract(after)
    if tip is None or canonical_before != tip or canonical_after is None:
        raise RuntimeError("ControlPolicy drifted outside the authorized value-loop Act")
    rows = state.get("policy_transitions", [])
    selected_count = len(
        [row for row in rows if row.get("policy_chain_ref") == chain_ref]
    )
    timestamp = transitioned_at
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    else:
        timestamp = timestamp.astimezone(UTC)
    candidate = {
        "policy_chain_ref": chain_ref,
        "sequence": selected_count + 1,
        "action_execution_id": str(action_execution_id),
        "scenario_id": str(scenario_id),
        "audit_id": str(audit_id),
        "request_sha256": str(request_sha256),
        "from": canonical_before,
        "to": canonical_after,
        "transitioned_at": timestamp.isoformat(),
        "actor": str(actor),
    }
    # Validate the newly written action/audit authority before publishing the
    # candidate into the append-only chain.  The same validation is repeated
    # on every future read by ``_policy_chain_tip``.
    candidate_state = {**state, "policy_transitions": [*rows, candidate]}
    if (
        _policy_chain_tip(
            db,
            candidate_state,
            chain_ref=chain_ref,
            root=root,
            system=system,
        )
        != canonical_after
    ):
        raise RuntimeError("value-loop policy transition audit is invalid")
    rows.append(candidate)
    state["policy_transitions"] = rows
    settings_payload[ROLLOUT_STATE_KEY] = state
    system.settings = settings_payload
    return True


def _trusted_activation_runner(value: Any, *, revision: str) -> bool:
    """Revalidate persisted runner identity against the current trust anchors."""

    if not isinstance(value, Mapping):
        return False
    expected = {
        "issuer",
        "project_id",
        "pipeline_id",
        "job_id",
        "commit_sha",
        "ref",
        "ref_protected",
    }
    if set(value) != expected:
        return False
    issuer = str(value.get("issuer") or "").rstrip("/")
    trusted_issuer = str(
        settings.authorization_v2_trusted_oidc_issuer or ""
    ).rstrip("/")
    trusted_project = str(settings.authorization_v2_trusted_project_id or "").strip()
    trusted_ref = str(settings.authorization_v2_trusted_ref or "").strip()
    return bool(
        issuer.startswith("https://")
        and trusted_issuer.startswith("https://")
        and issuer == trusted_issuer
        and trusted_project
        and str(value.get("project_id")) == trusted_project
        and trusted_ref
        and str(value.get("ref")) == trusted_ref
        and str(value.get("commit_sha") or "").lower() == revision
        and value.get("ref_protected") is True
        and str(value.get("pipeline_id") or "").strip()
        and str(value.get("job_id") or "").strip()
    )


def _activation_receipt_valid(
    db: Any,
    *,
    workspace_id: str,
    system: System,
    activation: Mapping[str, Any],
    revision: str,
) -> bool:
    """Bind an activation to persisted value facts and its exact server audit."""

    records = activation.get("records")
    checks = activation.get("checks")
    record_ids = (
        [str(records.get(key) or "").strip() for key in _ACTIVATION_RECORDS]
        if isinstance(records, Mapping)
        else []
    )
    if (
        set(activation) != _ACTIVATION_FIELDS
        or not isinstance(records, Mapping)
        or set(records) != _ACTIVATION_RECORDS
        or any(not identifier for identifier in record_ids)
        or len(set(record_ids)) != len(record_ids)
        or not isinstance(checks, Mapping)
        or set(checks) != _ACTIVATION_CHECKS
        or any(checks.get(key) is not True for key in _ACTIVATION_CHECKS)
        or not _trusted_activation_runner(
            activation.get("trusted_runner"),
            revision=revision,
        )
        or _SHA256_REF.fullmatch(str(activation.get("source_junit_ref") or ""))
        is None
        or _SHA256_REF.fullmatch(str(activation.get("observation_ref") or ""))
        is None
        or not isinstance(activation.get("runner_test_count"), int)
        or isinstance(activation.get("runner_test_count"), bool)
        or int(activation["runner_test_count"]) != len(_ACTIVATION_CHECKS)
        or not str(activation.get("audit_id") or "").strip()
        or not str(activation.get("activated_by") or "").strip()
        or not str(activation.get("validated_by") or "").strip()
    ):
        return False

    scenario = (
        db.query(ValueScenario)
        .filter(
            ValueScenario.id == str(records["scenario_id"]),
            ValueScenario.workspace_id == workspace_id,
            ValueScenario.system_id == system.id,
            ValueScenario.status == "measured",
        )
        .one_or_none()
    )
    decision = (
        db.query(Decision)
        .filter(
            Decision.id == str(records["decision_id"]),
            Decision.workspace_id == workspace_id,
            Decision.scenario_id == str(records["scenario_id"]),
            Decision.target_id == system.id,
            Decision.scope == "system",
            Decision.kind == "value_loop",
            Decision.status == "applied",
        )
        .one_or_none()
    )
    simulation = (
        db.query(ValueSimulation)
        .filter(
            ValueSimulation.id == str(records["simulation_id"]),
            ValueSimulation.workspace_id == workspace_id,
            ValueSimulation.system_id == system.id,
            ValueSimulation.scenario_id == str(records["scenario_id"]),
            ValueSimulation.status == "available",
        )
        .one_or_none()
    )
    action = (
        db.query(ValueActionExecution)
        .filter(
            ValueActionExecution.id == str(records["action_execution_id"]),
            ValueActionExecution.workspace_id == workspace_id,
            ValueActionExecution.system_id == system.id,
            ValueActionExecution.scenario_id == str(records["scenario_id"]),
            ValueActionExecution.simulation_id == str(records["simulation_id"]),
            ValueActionExecution.status == "succeeded",
        )
        .one_or_none()
    )
    measurement = (
        db.query(ValueMeasurement)
        .filter(
            ValueMeasurement.id == str(records["measurement_id"]),
            ValueMeasurement.workspace_id == workspace_id,
            ValueMeasurement.system_id == system.id,
            ValueMeasurement.scenario_id == str(records["scenario_id"]),
            ValueMeasurement.action_execution_id
            == str(records["action_execution_id"]),
            ValueMeasurement.simulation_id == str(records["simulation_id"]),
            ValueMeasurement.status == "measured",
        )
        .one_or_none()
    )
    if any(
        row is None
        for row in (scenario, decision, simulation, action, measurement)
    ):
        return False
    if (
        scenario.approved_simulation_id != simulation.id
        or action.control_policy_id != system.control_policy_id
        or measurement.source_run_id is None
        or measurement.observed_outcome == simulation.projected_outcome
    ):
        return False

    audit = (
        db.query(AuditLog)
        .filter(
            AuditLog.id == str(activation["audit_id"]),
            AuditLog.workspace_id == workspace_id,
            AuditLog.event_type == "lot8.value_loop.activated",
            AuditLog.agent_id == system.id,
            AuditLog.actor == str(activation.get("activated_by") or ""),
        )
        .one_or_none()
    )
    details = _settings(getattr(audit, "details", None)) if audit is not None else {}
    return bool(
        audit is not None
        and details.get("system_id") == system.id
        and details.get("revision") == revision
        and details.get("evidence_ref") == activation.get("evidence_ref")
        and details.get("artifact_ref") == activation.get("artifact_ref")
        and details.get("source_junit_ref") == activation.get("source_junit_ref")
        and details.get("observation_ref") == activation.get("observation_ref")
        and details.get("record_ids") == dict(records)
        and details.get("checks") == dict(checks)
        and details.get("runner_test_count") == activation.get("runner_test_count")
        and details.get("validated_at") == activation.get("validated_at")
        and details.get("validated_by") == activation.get("validated_by")
        and details.get("activated_at") == activation.get("activated_at")
        and details.get("trusted_runner")
        == dict(activation.get("trusted_runner") or {})
        and details.get("policy_chain_ref") == activation.get("policy_chain_ref")
        and details.get("policy_chain_created_at")
        == activation.get("policy_chain_created_at")
        and details.get("control_policy_revision")
        == _settings(activation.get("control_policy")).get("revision")
        and details.get("control_policy_sha256")
        == _settings(activation.get("control_policy")).get("sha256")
        and details.get("feature") == FEATURE_KEY
        and details.get("claim_promoted") is True
    )


def _workspace_proof_window_candidates(
    db: Any,
    *,
    workspace_id: str,
) -> list[str] | None:
    """Return currently open proof-window owners, or ``None`` on ambiguity.

    Every active System in the tenant participates.  An invalid active-looking
    window is not ignored: it makes proof selection ambiguous and closes every
    proof-only gate.  It does not revoke a different System whose full
    activation receipt has already been validated.
    """

    now = datetime.now(UTC)
    owners: list[str] = []
    systems = (
        db.query(System)
        .filter(System.workspace_id == workspace_id, System.status == "active")
        .all()
    )
    for candidate in systems:
        state = _settings(
            _settings(getattr(candidate, "settings", None)).get(ROLLOUT_STATE_KEY)
        )
        raw = state.get("proof_window")
        if raw is None:
            continue
        if not isinstance(raw, Mapping):
            return None
        try:
            opened_at = datetime.fromisoformat(
                str(raw.get("opened_at")).replace("Z", "+00:00")
            )
            expires_at = datetime.fromisoformat(
                str(raw.get("expires_at")).replace("Z", "+00:00")
            )
            if opened_at.tzinfo is None or expires_at.tzinfo is None:
                return None
            opened_at = opened_at.astimezone(UTC)
            expires_at = expires_at.astimezone(UTC)
        except (TypeError, ValueError):
            return None
        if expires_at <= opened_at:
            return None
        if opened_at <= now < expires_at:
            owners.append(str(candidate.id))
    return owners


def value_loop_requested(
    db: Any,
    *,
    workspace: Any,
    system: System,
) -> bool:
    """Return true when this System owns a valid proof or activation receipt.

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
    # The feature is rollout-owned, but the runtime also binds it to the
    # attestation persisted on each promoted System.  This closes two otherwise
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
            and _activation_receipt_valid(
                db,
                workspace_id=workspace_id,
                system=system,
                activation=latest,
                revision=revision,
            )
        ):
            return True

    # Before an activation, an operator may open a short, audited
    # proof window. It is bound to the exact runtime revision and prepared
    # contract, and expires closed. This breaks the otherwise circular gate
    # (behaviour proof requires the API that the proof will later activate)
    # without treating the window itself as activation evidence.
    if not system_has_value_loop_marker(system):
        return False
    marked_system_ids = [
        str(row.id)
        for row in db.query(System)
        .filter(System.workspace_id == workspace_id, System.status == "active")
        .all()
        if system_has_value_loop_marker(row)
    ]
    if marked_system_ids != [system.id]:
        return False
    proof_owners = _workspace_proof_window_candidates(
        db,
        workspace_id=workspace_id,
    )
    if proof_owners is None or proof_owners != [system.id]:
        return False

    proof_window = state.get("proof_window")
    prepared = state.get("prepared")
    if not isinstance(proof_window, Mapping) or not isinstance(prepared, Mapping):
        return False
    if set(proof_window) != {
        "audit_id",
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
        or not str(proof_window.get("audit_id") or "").strip()
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
    audit = (
        db.query(AuditLog)
        .filter(
            AuditLog.id == str(proof_window.get("audit_id")),
            AuditLog.workspace_id == workspace_id,
            AuditLog.event_type == "lot8.value_loop.canary_window.opened",
            AuditLog.agent_id == system.id,
            AuditLog.actor == str(proof_window.get("opened_by")),
        )
        .one_or_none()
    )
    return bool(
        audit is not None
        and isinstance(audit.details, Mapping)
        and audit.details.get("system_id") == system.id
        and audit.details.get("revision") == revision
        and audit.details.get("expires_at") == proof_window.get("expires_at")
        and audit.details.get("feature") == FEATURE_KEY
        and audit.details.get("claim_promoted") is False
        and audit.details.get("policy_chain_ref")
        == proof_window.get("policy_chain_ref")
        and audit.details.get("control_policy_revision")
        == _settings(proof_window.get("control_policy")).get("revision")
        and audit.details.get("control_policy_sha256")
        == _settings(proof_window.get("control_policy")).get("sha256")
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
        and _policy_reference_matches(
            db,
            system=system,
            policy=contract.policy,
        )
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
