"""Server-verifiable provenance for measured Run outcomes."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session as DBSession

from app.models.audit import AuditLog
from app.models.policy import ControlPolicy
from app.models.run import Run
from app.models.system import System
from app.services.control_policy_snapshot import (
    control_policy_execution_contract,
    validated_control_policy_execution_contract,
)
from app.services.run_engine.execution_contract import WORKBENCH_EXECUTION_SURFACES

RUN_OUTCOME_PROVENANCE_SCHEMA_VERSION = 1
RUN_OPERATOR_OVERRIDE_RECEIPT_SCHEMA_VERSION = 2
RUN_OUTCOME_OVERRIDE_AUDIT_EVENT = "run.outcome.operator_override.recorded"
RUN_RUNTIME_AUTO_RECEIPT_SCHEMA_VERSION = 1
RUN_RUNTIME_AUTO_AUDIT_EVENT = "run.outcome.runtime_auto.recorded"
RUN_RUNTIME_AUTO_ACTOR = "run_engine"

_RUNTIME_REVISION = re.compile(r"[0-9a-z][0-9a-z._:+/-]{0,254}")


def _canonical_sha256(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        dict(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _finite(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _parse_utc(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def _sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _sensitive_sha256(
    *,
    audit_id: str,
    run_id: str,
    field: str,
    value: Any,
) -> str:
    """Content-address a sensitive field without copying it into evidence."""

    encoded = json.dumps(
        {
            "audit_id": audit_id,
            "run_id": run_id,
            "field": field,
            "value": value,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _operator_audit_details(receipt: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "receipt_schema_version": receipt["schema_version"],
        "source": receipt["source"],
        "run_id": receipt["run_id"],
        "previous_value_sha256": receipt["previous_value_sha256"],
        "value_sha256": receipt["value_sha256"],
        "note_sha256": receipt["note_sha256"],
        "artifact_ref": receipt["artifact_ref"],
    }


def _runtime_auto_audit_details(receipt: Mapping[str, Any]) -> dict[str, Any]:
    """Return the exact, closed audit document for one runtime receipt."""

    return {
        "schema_version": 1,
        "receipt_schema_version": receipt["schema_version"],
        "source": receipt["source"],
        "run_id": receipt["run_id"],
        "workspace_id": receipt["workspace_id"],
        "system_id": receipt["system_id"],
        "flow_sha256": receipt["flow_sha256"],
        "runtime_revision": receipt["runtime_revision"],
        "control_policy": receipt["control_policy"],
        "value_sha256": receipt["value_sha256"],
        "completed_at": receipt["completed_at"],
        "artifact_ref": receipt["artifact_ref"],
    }


def _runtime_revision(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    candidate = value.strip().lower()
    if candidate != value or _RUNTIME_REVISION.fullmatch(candidate) is None:
        return None
    return candidate


def _runtime_execution(run: Run) -> tuple[dict[str, Any], dict[str, Any]] | None:
    input_ref = run.input_ref if isinstance(run.input_ref, Mapping) else {}
    execution = input_ref.get("execution")
    if not isinstance(execution, Mapping):
        return None
    flow_sha256 = execution.get("flow_sha256")
    runtime_revision = _runtime_revision(execution.get("runtime_revision"))
    policy = validated_control_policy_execution_contract(
        execution.get("control_policy")
    )
    if not _sha256(flow_sha256) or runtime_revision is None or policy is None:
        return None
    return dict(execution), {
        "flow_sha256": flow_sha256,
        "runtime_revision": runtime_revision,
        "control_policy": policy,
    }


def record_runtime_auto_outcome(
    run: Run,
    *,
    db: DBSession,
) -> dict[str, Any]:
    """Persist server-owned runtime measurement evidence in this transaction.

    The receipt is embedded in the immutable execution envelope and bound to a
    mandatory AuditLog row.  Callers own the surrounding commit; any failed
    validation or flush therefore prevents a partially evidenced completion.
    """

    value = _finite(run.value_estimated)
    identity = _runtime_execution(run)
    if (
        run.status != "completed"
        or run.value_source != "auto"
        or run.completed_at is None
        or value is None
        or not str(run.id or "").strip()
        or not str(run.workspace_id or "").strip()
        or not str(run.system_id or "").strip()
        or identity is None
    ):
        raise ValueError("runtime-auto outcome provenance is incomplete")
    execution, evidence = identity
    if execution.get("outcome_receipt") is not None:
        existing = _validated_runtime_auto_receipt(run, db=db)
        if existing is None:
            raise ValueError("runtime-auto outcome receipt already exists but is invalid")
        return existing
    workspace_id = str(run.workspace_id)
    system_id = str(run.system_id)
    policy_contract = evidence["control_policy"]

    # Author the receipt only for a persisted Run whose tenant, System and
    # actually executed policy all agree at the completion boundary.
    persisted_run = (
        db.query(Run)
        .filter(
            Run.id == run.id,
            Run.workspace_id == workspace_id,
            Run.system_id == system_id,
        )
        .one_or_none()
    )
    system = (
        db.query(System)
        .filter(System.id == system_id, System.workspace_id == workspace_id)
        .one_or_none()
    )
    policy = (
        db.query(ControlPolicy)
        .filter(
            ControlPolicy.id == policy_contract["policy_id"],
            ControlPolicy.workspace_id == workspace_id,
            ControlPolicy.scope == "system",
            ControlPolicy.target_id == system_id,
        )
        .one_or_none()
    )
    if (
        persisted_run is None
        or system is None
        or policy is None
        or (
            system.control_policy_id is not None
            and system.control_policy_id != policy.id
        )
        or control_policy_execution_contract(policy) != policy_contract
    ):
        raise ValueError("runtime-auto execution authority is inconsistent")

    completed_at = _utc(run.completed_at)
    timestamp = completed_at.isoformat()
    audit_id = str(uuid4())
    payload = {
        "schema_version": RUN_RUNTIME_AUTO_RECEIPT_SCHEMA_VERSION,
        "source": "runtime_auto",
        "audit_id": audit_id,
        "run_id": str(run.id),
        "workspace_id": workspace_id,
        "system_id": system_id,
        "actor": RUN_RUNTIME_AUTO_ACTOR,
        "recorded_at": timestamp,
        "completed_at": timestamp,
        "flow_sha256": evidence["flow_sha256"],
        "runtime_revision": evidence["runtime_revision"],
        "control_policy": policy_contract,
        "value_sha256": _sensitive_sha256(
            audit_id=audit_id,
            run_id=str(run.id),
            field="value",
            value=value,
        ),
    }
    receipt = {**payload, "artifact_ref": f"sha256:{_canonical_sha256(payload)}"}
    audit = AuditLog(
        id=audit_id,
        workspace_id=workspace_id,
        timestamp=completed_at.replace(tzinfo=None),
        event_type=RUN_RUNTIME_AUTO_AUDIT_EVENT,
        actor=RUN_RUNTIME_AUTO_ACTOR,
        details=_runtime_auto_audit_details(receipt),
        severity="info",
    )
    execution["outcome_receipt"] = receipt
    input_ref = copy.deepcopy(run.input_ref) if isinstance(run.input_ref, Mapping) else {}
    input_ref["execution"] = execution
    run.input_ref = input_ref
    db.add(audit)
    db.flush()
    return receipt


def record_operator_outcome_override(
    run: Run,
    *,
    db: DBSession,
    actor: str,
    previous_value: Any,
    note: str | None,
    recorded_at: datetime | None = None,
) -> dict[str, Any]:
    """Append an AuditLog-bound receipt in the caller's transaction.

    The audit row and the embedded receipt deliberately contain only hashes of
    the business value and operator note.  ``flush`` is mandatory: callers
    must roll the whole transaction back if the audit authority is unavailable.
    """

    actor_value = str(actor or "").strip()
    current_value = _finite(run.value_estimated)
    if not actor_value or len(actor_value) > 255 or current_value is None:
        raise ValueError("operator outcome override provenance is incomplete")
    if not str(run.id or "").strip() or not str(run.workspace_id or "").strip():
        raise ValueError("operator outcome override tenant identity is incomplete")
    timestamp = _utc(recorded_at or datetime.now(UTC))
    audit_id = str(uuid4())
    stored_note = str(run.operator_value_note or "")
    expected_note = f"override: {current_value:.2f} (was {previous_value}) — {note or ''}".strip()[
        :1000
    ]
    if stored_note != expected_note:
        raise ValueError("operator outcome override note does not match the Run")
    payload = {
        "schema_version": RUN_OPERATOR_OVERRIDE_RECEIPT_SCHEMA_VERSION,
        "source": "operator_override",
        "audit_id": audit_id,
        "run_id": run.id,
        "actor": actor_value,
        "recorded_at": timestamp.isoformat(),
        "previous_value_sha256": _sensitive_sha256(
            audit_id=audit_id,
            run_id=run.id,
            field="previous_value",
            value=_finite(previous_value),
        ),
        "value_sha256": _sensitive_sha256(
            audit_id=audit_id,
            run_id=run.id,
            field="value",
            value=current_value,
        ),
        "note_sha256": _sensitive_sha256(
            audit_id=audit_id,
            run_id=run.id,
            field="operator_value_note",
            value=stored_note,
        ),
    }
    receipt = {**payload, "artifact_ref": f"sha256:{_canonical_sha256(payload)}"}
    audit = AuditLog(
        id=audit_id,
        workspace_id=run.workspace_id,
        timestamp=timestamp.replace(tzinfo=None),
        event_type=RUN_OUTCOME_OVERRIDE_AUDIT_EVENT,
        actor=actor_value,
        details=_operator_audit_details(receipt),
        severity="info",
    )
    db.add(audit)
    db.flush()
    output_ref = copy.deepcopy(run.output_ref) if isinstance(run.output_ref, Mapping) else {}
    history = output_ref.get("operator_value_overrides")
    rows = list(history) if isinstance(history, list) else []
    rows.append(receipt)
    output_ref["operator_value_overrides"] = rows
    run.output_ref = output_ref
    return receipt


def _validated_operator_receipt(
    run: Run,
    *,
    db: DBSession | None,
) -> dict[str, Any] | None:
    if db is None:
        # Embedded evidence is never self-authenticating; both sources require
        # their exact persisted audit authority.
        return None
    output_ref = run.output_ref if isinstance(run.output_ref, Mapping) else {}
    history = output_ref.get("operator_value_overrides")
    if not isinstance(history, list) or not history:
        return None
    row = history[-1]
    expected = {
        "schema_version",
        "source",
        "audit_id",
        "run_id",
        "actor",
        "recorded_at",
        "previous_value_sha256",
        "value_sha256",
        "note_sha256",
        "artifact_ref",
    }
    if not isinstance(row, Mapping) or set(row) != expected:
        return None
    payload = {key: row.get(key) for key in expected - {"artifact_ref"}}
    if (
        payload["schema_version"] != RUN_OPERATOR_OVERRIDE_RECEIPT_SCHEMA_VERSION
        or payload["source"] != "operator_override"
        or payload["run_id"] != run.id
        or not str(payload["audit_id"] or "").strip()
        or not isinstance(payload["actor"], str)
        or not payload["actor"].strip()
        or len(payload["actor"]) > 255
        or not _sha256(payload["previous_value_sha256"])
        or not _sha256(payload["value_sha256"])
        or not _sha256(payload["note_sha256"])
        or row.get("artifact_ref") != f"sha256:{_canonical_sha256(payload)}"
    ):
        return None
    recorded_at = _parse_utc(payload["recorded_at"])
    if recorded_at is None:
        return None
    current_value = _finite(run.value_estimated)
    if current_value is None:
        return None
    if payload["value_sha256"] != _sensitive_sha256(
        audit_id=payload["audit_id"],
        run_id=run.id,
        field="value",
        value=current_value,
    ):
        return None
    if payload["note_sha256"] != _sensitive_sha256(
        audit_id=payload["audit_id"],
        run_id=run.id,
        field="operator_value_note",
        value=str(run.operator_value_note or ""),
    ):
        return None
    with db.no_autoflush:
        audit = (
            db.query(AuditLog)
            .filter(
                AuditLog.id == payload["audit_id"],
                AuditLog.workspace_id == run.workspace_id,
            )
            .populate_existing()
            .one_or_none()
        )
    if audit is None:
        return None
    if not isinstance(audit.timestamp, datetime):
        return None
    audit_timestamp = _utc(audit.timestamp)
    if (
        audit.event_type != RUN_OUTCOME_OVERRIDE_AUDIT_EVENT
        or audit.actor != payload["actor"]
        or audit_timestamp != recorded_at
        or audit.details != _operator_audit_details(row)
        or audit.trace_id is not None
        or audit.agent_id is not None
        or audit.severity != "info"
    ):
        return None
    return dict(row)


def _validated_runtime_auto_receipt(
    run: Run,
    *,
    db: DBSession | None,
) -> dict[str, Any] | None:
    """Validate both halves of a runtime receipt without trusting Run JSON."""

    if db is None or run.status != "completed" or run.completed_at is None:
        return None
    value = _finite(run.value_estimated)
    identity = _runtime_execution(run)
    if value is None or identity is None:
        return None
    execution, evidence = identity
    row = execution.get("outcome_receipt")
    expected = {
        "schema_version",
        "source",
        "audit_id",
        "run_id",
        "workspace_id",
        "system_id",
        "actor",
        "recorded_at",
        "completed_at",
        "flow_sha256",
        "runtime_revision",
        "control_policy",
        "value_sha256",
        "artifact_ref",
    }
    if not isinstance(row, Mapping) or set(row) != expected:
        return None
    payload = {key: row.get(key) for key in expected - {"artifact_ref"}}
    if (
        payload["schema_version"] != RUN_RUNTIME_AUTO_RECEIPT_SCHEMA_VERSION
        or payload["source"] != "runtime_auto"
        or payload["run_id"] != run.id
        or payload["workspace_id"] != run.workspace_id
        or payload["system_id"] != run.system_id
        or payload["actor"] != RUN_RUNTIME_AUTO_ACTOR
        or payload["recorded_at"] != payload["completed_at"]
        or payload["flow_sha256"] != evidence["flow_sha256"]
        or payload["runtime_revision"] != evidence["runtime_revision"]
        or payload["control_policy"] != evidence["control_policy"]
        or not str(payload["audit_id"] or "").strip()
        or not _sha256(payload["value_sha256"])
        or row.get("artifact_ref") != f"sha256:{_canonical_sha256(payload)}"
    ):
        return None
    canonical_completed_at = _utc(run.completed_at).isoformat()
    recorded_at = _parse_utc(payload["recorded_at"])
    if (
        recorded_at is None
        or payload["completed_at"] != canonical_completed_at
        or recorded_at != _utc(run.completed_at)
    ):
        return None
    if payload["value_sha256"] != _sensitive_sha256(
        audit_id=payload["audit_id"],
        run_id=str(run.id),
        field="value",
        value=value,
    ):
        return None

    with db.no_autoflush:
        persisted_run = (
            db.query(Run)
            .filter(
                Run.id == run.id,
                Run.workspace_id == run.workspace_id,
                Run.system_id == run.system_id,
            )
            .populate_existing()
            .one_or_none()
        )
        system = (
            db.query(System)
            .filter(
                System.id == run.system_id,
                System.workspace_id == run.workspace_id,
            )
            .one_or_none()
        )
        audit = (
            db.query(AuditLog)
            .filter(
                AuditLog.id == payload["audit_id"],
                AuditLog.workspace_id == run.workspace_id,
            )
            .populate_existing()
            .one_or_none()
        )
    if persisted_run is None or system is None or audit is None:
        return None
    persisted_identity = _runtime_execution(persisted_run)
    if persisted_identity is None:
        return None
    persisted_receipt = persisted_identity[0].get("outcome_receipt")
    if not isinstance(persisted_receipt, Mapping) or dict(persisted_receipt) != dict(row):
        return None
    if not isinstance(audit.timestamp, datetime):
        return None
    if (
        persisted_run.status != "completed"
        or persisted_run.value_source != "auto"
        or _finite(persisted_run.value_estimated) != value
        or persisted_run.completed_at is None
        or _utc(persisted_run.completed_at) != recorded_at
        or audit.event_type != RUN_RUNTIME_AUTO_AUDIT_EVENT
        or audit.actor != RUN_RUNTIME_AUTO_ACTOR
        or _utc(audit.timestamp) != recorded_at
        or audit.details != _runtime_auto_audit_details(row)
        or audit.trace_id is not None
        or audit.agent_id is not None
        or audit.severity != "info"
    ):
        return None
    return dict(row)


def run_measurement_provenance(
    run: Run,
    *,
    db: DBSession | None = None,
) -> dict[str, Any] | None:
    """Return independently checkable provenance for the current Run value."""

    if run.value_source == "operator":
        receipt = _validated_operator_receipt(run, db=db)
        if receipt is None:
            return None
        return {
            "schema_version": RUN_OUTCOME_PROVENANCE_SCHEMA_VERSION,
            "source": "operator_override",
            "audit_id": receipt["audit_id"],
            "actor": receipt["actor"],
            "recorded_at": receipt["recorded_at"],
            "artifact_ref": receipt["artifact_ref"],
        }
    if run.value_source != "auto":
        return None
    receipt = _validated_runtime_auto_receipt(run, db=db)
    if receipt is None:
        return None
    return {
        "schema_version": RUN_OUTCOME_PROVENANCE_SCHEMA_VERSION,
        "source": "runtime_auto",
        "audit_id": receipt["audit_id"],
        "actor": receipt["actor"],
        "recorded_at": receipt["recorded_at"],
        "artifact_ref": receipt["artifact_ref"],
    }


def is_canary_authored_operator_outcome(run: Run) -> bool:
    input_ref = run.input_ref if isinstance(run.input_ref, Mapping) else {}
    return run.value_source == "operator" and input_ref.get("lot8_value_loop_canary") is True


def baseline_run_exclusion_reason(run: Run) -> str | None:
    """Reject authoring previews, fixtures and canary Runs as a baseline.

    The value loop may only start from ordinary runtime evidence. Workbench
    executions, showcase fixtures and Runs created by the mutating Lot 8
    canary are useful for authoring, demonstrations and post-action liveness,
    but none is an independent pre-action observation.
    """

    input_ref = run.input_ref if isinstance(run.input_ref, Mapping) else {}
    output_ref = run.output_ref if isinstance(run.output_ref, Mapping) else {}
    if (
        str(run.execution_surface or "").strip().lower()
        in WORKBENCH_EXECUTION_SURFACES
        or str(run.trigger or "").strip().lower()
        in WORKBENCH_EXECUTION_SURFACES
    ):
        return "baseline_run_is_flow_workbench"
    if (
        input_ref.get("showcase_seed") is True
        or output_ref.get("showcase_seed") is True
        or str(input_ref.get("evidence_kind") or "").strip().lower() == "synthetic_demo"
    ):
        return "baseline_run_is_synthetic_demo"
    if (
        input_ref.get("lot8_value_loop_canary") is True
        or str(run.trigger or "").strip().lower() == "lot8_value_loop_canary"
    ):
        return "baseline_run_is_canary_authored"
    return None


__all__ = [
    "RUN_OUTCOME_PROVENANCE_SCHEMA_VERSION",
    "RUN_OPERATOR_OVERRIDE_RECEIPT_SCHEMA_VERSION",
    "RUN_OUTCOME_OVERRIDE_AUDIT_EVENT",
    "RUN_RUNTIME_AUTO_ACTOR",
    "RUN_RUNTIME_AUTO_AUDIT_EVENT",
    "RUN_RUNTIME_AUTO_RECEIPT_SCHEMA_VERSION",
    "baseline_run_exclusion_reason",
    "is_canary_authored_operator_outcome",
    "record_operator_outcome_override",
    "record_runtime_auto_outcome",
    "run_measurement_provenance",
]
