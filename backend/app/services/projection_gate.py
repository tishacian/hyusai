"""Fail-closed runtime gate for the ordered Lot 7 object projections."""
from __future__ import annotations

import copy
import hashlib
import json
import re
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.config import settings
from app.models.audit import AuditLog
from app.models.system import System

PROJECTION_ORDER = ("capability", "run", "skill_invocation")
FEATURE_BY_PROJECTION = {
    "capability": "capability_360_projection_v1",
    "run": "run_360_projection_v1",
    "skill_invocation": "skill_invocation_360_projection_v1",
}
WORKSPACE_GATE_KEY = "_lot7_projection_gate_v1"
WORKSPACE_GATE_SCHEMA_VERSION = 1
SYSTEM_CANARY_MARKER = "v1"
SYSTEM_ROLLOUT_STATE_KEY = "_lot7_projection_rollout_v1"
PROJECTION_FINALIZATION_AUDIT_EVENT = "lot7.projection.probation_finalized"
PROJECTION_ACTIVATION_RECEIPT_SCHEMA_VERSION = 1

_SHA256 = re.compile(r"[0-9a-f]{64}")
_GIT_SHA = re.compile(r"[0-9a-f]{40}")
PROBATION_MAX_LEASE = timedelta(minutes=30)
_TRUSTED_RUNNER_FIELDS = frozenset(
    {
        "issuer",
        "project_id",
        "pipeline_id",
        "job_id",
        "commit_sha",
        "ref",
        "ref_protected",
    }
)


class ProjectionGateError(ValueError):
    """Raised when rollout code would persist an incoherent gate."""


def projection_activation_sha256(activation: Mapping[str, Any]) -> str:
    """Content-address one activation without its receipt or server audit id.

    The final AuditLog id cannot be part of the digest that the same AuditLog
    records. Excluding only those two server-generated receipt fields keeps the
    rest of the persisted activation immutable without introducing a circular
    hash dependency.
    """

    payload = {
        key: copy.deepcopy(value)
        for key, value in activation.items()
        if key not in {"activation_sha256", "audit_id"}
    }
    try:
        canonical = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ProjectionGateError("Lot 7 activation is not canonical JSON") from exc
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def projection_activation_audit_details(
    activation: Mapping[str, Any],
) -> dict[str, Any]:
    """Build the exact, non-secret server receipt persisted in AuditLog."""

    pilot = activation.get("pilot_observation")
    runner = activation.get("trusted_runner")
    if not isinstance(pilot, Mapping) or not isinstance(runner, Mapping):
        raise ProjectionGateError("Lot 7 activation needs pilot and trusted runner receipts")
    activation_sha256 = str(activation.get("activation_sha256") or "")
    if _SHA256.fullmatch(activation_sha256) is None:
        raise ProjectionGateError("Lot 7 activation receipt digest is invalid")
    return {
        "schema_version": PROJECTION_ACTIVATION_RECEIPT_SCHEMA_VERSION,
        "system_id": activation.get("system_id"),
        "capability_id": activation.get("capability_id"),
        "projection": activation.get("projection"),
        "feature": activation.get("feature"),
        "revision": activation.get("revision"),
        "evidence_sha256": activation.get("evidence_sha256"),
        "activation_sha256": activation_sha256,
        "activated_at": activation.get("activated_at"),
        "probation_lease_id": activation.get("probation_lease_id"),
        "pilot_observation_ref": pilot.get("observation_ref"),
        "pilot_observation_audit_id": pilot.get("audit_id"),
        "pilot_participant_ref": pilot.get("participant_ref"),
        "pilot_profile": pilot.get("profile"),
        "trusted_runner": copy.deepcopy(dict(runner)),
    }


def _trusted_activation_runner(value: Any, *, revision: str) -> bool:
    """Revalidate persisted runner identity against current trust anchors."""

    if not isinstance(value, Mapping) or set(value) != _TRUSTED_RUNNER_FIELDS:
        return False
    issuer = str(value.get("issuer") or "").rstrip("/")
    trusted_issuer = str(settings.authorization_v2_trusted_oidc_issuer or "").rstrip("/")
    trusted_project = str(settings.authorization_v2_trusted_project_id or "").strip()
    trusted_ref = str(settings.authorization_v2_trusted_ref or "").strip()
    return bool(
        _GIT_SHA.fullmatch(revision)
        and issuer.startswith("https://")
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
    """Bind one verified activation to its exact server AuditLog receipt."""

    if not _trusted_activation_runner(
        activation.get("trusted_runner"),
        revision=revision,
    ):
        return False
    audit_id = str(activation.get("audit_id") or "").strip()
    try:
        uuid.UUID(audit_id)
    except ValueError:
        return False
    receipt_digest = str(activation.get("activation_sha256") or "")
    if _SHA256.fullmatch(receipt_digest) is None:
        return False
    try:
        if projection_activation_sha256(activation) != receipt_digest:
            return False
        expected_details = projection_activation_audit_details(activation)
    except ProjectionGateError:
        return False
    audit = (
        db.query(AuditLog)
        .filter(
            AuditLog.id == audit_id,
            AuditLog.workspace_id == workspace_id,
            AuditLog.event_type == PROJECTION_FINALIZATION_AUDIT_EVENT,
            AuditLog.agent_id == system.id,
            AuditLog.actor == str(activation.get("activated_by") or ""),
        )
        .one_or_none()
    )
    return bool(
        audit is not None
        and isinstance(audit.details, Mapping)
        and dict(audit.details) == expected_details
    )


def projection_enabled(
    settings: Any,
    projection: str,
    *,
    runtime_revision: str | None = None,
    at: datetime | None = None,
) -> bool:
    """Require both the ordinary flag and a usable server-owned gate.

    A verified row remains readable across additive deployments; the rollout
    status still reports whether its behavioural proof matches the current
    runtime.  A probation row is deliberately stricter: it only opens the
    projector for a short canary window on the exact staged runtime SHA.
    """
    if projection not in PROJECTION_ORDER or not isinstance(settings, Mapping):
        return False
    features = settings.get("features")
    gate = settings.get(WORKSPACE_GATE_KEY)
    if not isinstance(features, Mapping) or not isinstance(gate, Mapping):
        return False
    if features.get(FEATURE_BY_PROJECTION[projection]) is not True:
        return False
    try:
        rows = validated_gate_rows(gate)
    except ProjectionGateError:
        return False
    row = rows.get(projection)
    if row is None:
        return False
    revision = str(runtime_revision or "").strip().lower()
    if _GIT_SHA.fullmatch(revision) is None or row.get("revision") != revision:
        return False
    if gate_row_phase(row) != "probation":
        return True
    expires_at = _parse_gate_datetime(row.get("expires_at"), field="expires_at")
    current = (at or datetime.now(UTC)).astimezone(UTC)
    return current < expires_at


def authoritative_projection_enabled(
    db: Any,
    workspace: Any,
    projection: str,
    *,
    runtime_revision: str,
    at: datetime | None = None,
) -> bool:
    """Bind the Workspace gate to the unique marked System rollout state.

    Structural validation alone catches malformed or out-of-order gates.  This
    second boundary also catches accidental/content drift between the
    Workspace summary and the evidence/probation persisted on the canary
    System.  Any ambiguity fails closed.
    """

    revision = str(runtime_revision or "").strip().lower()
    workspace_settings = getattr(workspace, "settings", None)
    if not projection_enabled(
        workspace_settings,
        projection,
        runtime_revision=revision,
        at=at,
    ):
        return False
    workspace_id = str(getattr(workspace, "id", "") or "")
    if not workspace_id:
        return False
    marked = [
        system
        for system in db.query(System)
        .filter(System.workspace_id == workspace_id, System.status == "active")
        .all()
        if _system_canary_marker(system) == SYSTEM_CANARY_MARKER
    ]
    if len(marked) != 1:
        return False
    system = marked[0]
    settings = system.settings if isinstance(system.settings, Mapping) else {}
    state = settings.get(SYSTEM_ROLLOUT_STATE_KEY)
    if not isinstance(state, Mapping) or state.get("schema_version") != 1:
        return False
    activations = _unique_rollout_rows(state.get("activations"))
    probations = _unique_rollout_rows(state.get("probations", []))
    if activations is None or probations is None:
        return False
    gate = (
        workspace_settings.get(WORKSPACE_GATE_KEY)
        if isinstance(workspace_settings, Mapping)
        else None
    )
    if not isinstance(gate, Mapping):
        return False
    try:
        gate_rows = validated_gate_rows(gate)
    except ProjectionGateError:
        return False
    if set(activations) | set(probations) != set(gate_rows):
        return False
    for name, row in gate_rows.items():
        phase = gate_row_phase(row)
        persisted = probations.get(name) if phase == "probation" else activations.get(name)
        if persisted is None:
            return False
        expected = {
            "projection": name,
            "feature": FEATURE_BY_PROJECTION[name],
            "revision": row.get("revision"),
            "system_id": system.id,
            "capability_id": system.capability_id,
        }
        if any(persisted.get(field) != value for field, value in expected.items()):
            return False
        if phase == "verified":
            if persisted.get("evidence_sha256") != row.get("evidence_sha256"):
                return False
            if not _activation_receipt_valid(
                db,
                workspace_id=workspace_id,
                system=system,
                activation=persisted,
                revision=revision,
            ):
                return False
        else:
            for field in ("lease_id", "staged_at", "expires_at"):
                if persisted.get(field) != row.get(field):
                    return False
    return True


def _system_canary_marker(system: System) -> Any:
    settings = system.settings if isinstance(system.settings, Mapping) else {}
    experience = settings.get("experience")
    return experience.get("system_360_canary") if isinstance(experience, Mapping) else None


def _unique_rollout_rows(value: Any) -> dict[str, dict[str, Any]] | None:
    if not isinstance(value, list):
        return None
    rows: dict[str, dict[str, Any]] = {}
    for raw in value:
        if not isinstance(raw, Mapping):
            return None
        projection = raw.get("projection")
        if projection not in PROJECTION_ORDER or projection in rows:
            return None
        rows[str(projection)] = dict(raw)
    return rows


def validated_gate_rows(gate: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Validate and normalize the persisted ordered activation summary."""
    if gate.get("schema_version") != WORKSPACE_GATE_SCHEMA_VERSION:
        raise ProjectionGateError("unsupported Lot 7 Workspace gate schema")
    raw_rows = gate.get("activations")
    if not isinstance(raw_rows, list):
        raise ProjectionGateError("Lot 7 Workspace gate activations must be an array")
    rows: dict[str, dict[str, Any]] = {}
    observed_order: list[str] = []
    probation_seen = False
    for raw in raw_rows:
        if not isinstance(raw, Mapping):
            raise ProjectionGateError("invalid Lot 7 Workspace gate activation")
        row = copy.deepcopy(dict(raw))
        projection = row.get("projection")
        if projection not in PROJECTION_ORDER or projection in rows:
            raise ProjectionGateError("duplicate or unknown Lot 7 Workspace gate projection")
        if row.get("feature") != FEATURE_BY_PROJECTION[projection]:
            raise ProjectionGateError("Lot 7 Workspace gate feature mismatch")
        if _GIT_SHA.fullmatch(str(row.get("revision") or "")) is None:
            raise ProjectionGateError("invalid Lot 7 Workspace gate revision")
        for field in ("system_id", "capability_id"):
            if not str(row.get(field) or "").strip():
                raise ProjectionGateError(f"Lot 7 Workspace gate {field} is missing")
        phase = gate_row_phase(row)
        if probation_seen:
            raise ProjectionGateError("Lot 7 Workspace gate probation must be the active tail")
        if phase == "probation":
            probation_seen = True
            if row.get("evidence_sha256") is not None:
                raise ProjectionGateError("Lot 7 probation cannot carry validation evidence")
            staged_at = _parse_gate_datetime(row.get("staged_at"), field="staged_at")
            expires_at = _parse_gate_datetime(row.get("expires_at"), field="expires_at")
            try:
                uuid.UUID(str(row.get("lease_id") or ""))
            except ValueError as exc:
                raise ProjectionGateError("Lot 7 probation lease_id must be a UUID") from exc
            lease = expires_at - staged_at
            if lease <= timedelta(0) or lease > PROBATION_MAX_LEASE:
                raise ProjectionGateError("Lot 7 probation lease must be within 30 minutes")
        elif _SHA256.fullmatch(str(row.get("evidence_sha256") or "")) is None:
            raise ProjectionGateError("invalid Lot 7 Workspace gate evidence digest")
        observed_order.append(projection)
        rows[projection] = row
    if observed_order != list(PROJECTION_ORDER[: len(observed_order)]):
        raise ProjectionGateError("Lot 7 Workspace gate is not a contiguous activation prefix")
    return rows


def gate_row_phase(row: Mapping[str, Any]) -> str:
    """Return the normalized gate phase, accepting legacy verified rows."""

    phase = row.get("phase", "verified")
    if phase not in {"probation", "verified"}:
        raise ProjectionGateError("invalid Lot 7 Workspace gate phase")
    return str(phase)


def _parse_gate_datetime(value: Any, *, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ProjectionGateError(f"Lot 7 Workspace gate {field} is missing")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProjectionGateError(f"Lot 7 Workspace gate {field} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ProjectionGateError(f"Lot 7 Workspace gate {field} needs a timezone")
    return parsed.astimezone(UTC)


def with_projection_probation(
    settings: Any,
    *,
    projection: str,
    revision: str,
    system_id: str,
    capability_id: str,
    staged_at: datetime,
    expires_at: datetime,
    lease_id: str,
) -> dict[str, Any]:
    """Open the next projector for one short, SHA-bound canary lease."""

    if projection not in PROJECTION_ORDER:
        raise ProjectionGateError(f"unknown projection: {projection}")
    result = copy.deepcopy(dict(settings)) if isinstance(settings, Mapping) else {}
    raw_gate = result.get(WORKSPACE_GATE_KEY)
    if raw_gate is None:
        rows: dict[str, dict[str, Any]] = {}
    elif isinstance(raw_gate, Mapping):
        rows = validated_gate_rows(raw_gate)
    else:
        raise ProjectionGateError("Lot 7 Workspace gate must be an object")
    if projection in rows:
        raise ProjectionGateError("Lot 7 Workspace gate projection is already present")
    expected_next = PROJECTION_ORDER[len(rows)] if len(rows) < len(PROJECTION_ORDER) else None
    if projection != expected_next:
        raise ProjectionGateError(f"next Workspace gate projection must be {expected_next}")
    row = {
        "projection": projection,
        "feature": FEATURE_BY_PROJECTION[projection],
        "phase": "probation",
        "revision": str(revision).strip().lower(),
        "system_id": system_id,
        "capability_id": capability_id,
        "staged_at": staged_at.astimezone(UTC).isoformat(),
        "expires_at": expires_at.astimezone(UTC).isoformat(),
        "lease_id": lease_id,
    }
    # Reuse the authoritative validator before persisting anything.
    candidate_rows = [rows[name] for name in PROJECTION_ORDER if name in rows] + [row]
    validated_gate_rows(
        {"schema_version": WORKSPACE_GATE_SCHEMA_VERSION, "activations": candidate_rows}
    )
    result[WORKSPACE_GATE_KEY] = {
        "schema_version": WORKSPACE_GATE_SCHEMA_VERSION,
        "activations": candidate_rows,
    }
    features = copy.deepcopy(dict(result.get("features") or {}))
    features[FEATURE_BY_PROJECTION[projection]] = True
    result["features"] = features
    return result


def with_projection_activation(
    settings: Any,
    *,
    projection: str,
    evidence_sha256: str,
    revision: str,
    system_id: str,
    capability_id: str,
) -> dict[str, Any]:
    """Return Workspace settings with one next, content-bound activation."""
    if projection not in PROJECTION_ORDER:
        raise ProjectionGateError(f"unknown projection: {projection}")
    result = copy.deepcopy(dict(settings)) if isinstance(settings, Mapping) else {}
    raw_gate = result.get(WORKSPACE_GATE_KEY)
    if raw_gate is None:
        rows: dict[str, dict[str, Any]] = {}
    elif isinstance(raw_gate, Mapping):
        rows = validated_gate_rows(raw_gate)
    else:
        raise ProjectionGateError("Lot 7 Workspace gate must be an object")
    expected = {
        "projection": projection,
        "feature": FEATURE_BY_PROJECTION[projection],
        "phase": "verified",
        "evidence_sha256": evidence_sha256,
        "revision": revision,
        "system_id": system_id,
        "capability_id": capability_id,
    }
    if projection in rows:
        current = rows[projection]
        if gate_row_phase(current) == "verified":
            legacy_expected = dict(expected)
            legacy_expected.pop("phase")
            if current != expected and current != legacy_expected:
                raise ProjectionGateError("Lot 7 Workspace gate activation drift")
            return result
        if current.get("revision") != expected["revision"]:
            raise ProjectionGateError("Lot 7 probation revision differs from validation")
        for field in ("system_id", "capability_id", "feature"):
            if current.get(field) != expected[field]:
                raise ProjectionGateError("Lot 7 probation subject differs from validation")
        rows[projection] = expected
        result[WORKSPACE_GATE_KEY] = {
            "schema_version": WORKSPACE_GATE_SCHEMA_VERSION,
            "activations": [rows[name] for name in PROJECTION_ORDER if name in rows],
        }
        return result
    expected_next = PROJECTION_ORDER[len(rows)] if len(rows) < len(PROJECTION_ORDER) else None
    if projection != expected_next:
        raise ProjectionGateError(f"next Workspace gate projection must be {expected_next}")
    rows[projection] = expected
    result[WORKSPACE_GATE_KEY] = {
        "schema_version": WORKSPACE_GATE_SCHEMA_VERSION,
        "activations": [rows[name] for name in PROJECTION_ORDER if name in rows],
    }
    features = copy.deepcopy(dict(result.get("features") or {}))
    features[FEATURE_BY_PROJECTION[projection]] = True
    result["features"] = features
    return result


def without_projection_activation(settings: Any, *, projection: str) -> dict[str, Any]:
    """Return Workspace settings after removing exactly the active tail."""
    result = copy.deepcopy(dict(settings)) if isinstance(settings, Mapping) else {}
    gate = result.get(WORKSPACE_GATE_KEY)
    if not isinstance(gate, Mapping):
        raise ProjectionGateError("Lot 7 Workspace gate is missing")
    rows = validated_gate_rows(gate)
    if not rows or projection != PROJECTION_ORDER[len(rows) - 1]:
        raise ProjectionGateError("only the active Workspace gate tail can be removed")
    rows.pop(projection)
    result[WORKSPACE_GATE_KEY] = {
        "schema_version": WORKSPACE_GATE_SCHEMA_VERSION,
        "activations": [rows[name] for name in PROJECTION_ORDER if name in rows],
    }
    features = copy.deepcopy(dict(result.get("features") or {}))
    features[FEATURE_BY_PROJECTION[projection]] = False
    result["features"] = features
    return result
