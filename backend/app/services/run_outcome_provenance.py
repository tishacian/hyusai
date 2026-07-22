"""Server-verifiable provenance for measured Run outcomes."""
from __future__ import annotations

import copy
import hashlib
import json
import math
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from app.models.run import Run
from app.services.control_policy_snapshot import (
    validated_control_policy_execution_contract,
)

RUN_OUTCOME_PROVENANCE_SCHEMA_VERSION = 1


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


def record_operator_outcome_override(
    run: Run,
    *,
    actor: str,
    previous_value: Any,
    note: str | None,
    recorded_at: datetime | None = None,
) -> dict[str, Any]:
    """Append a server-owned receipt after an authenticated override."""

    actor_value = str(actor or "").strip()
    current_value = _finite(run.value_estimated)
    if not actor_value or current_value is None:
        raise ValueError("operator outcome override provenance is incomplete")
    timestamp = recorded_at or datetime.now(UTC)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    payload = {
        "schema_version": RUN_OUTCOME_PROVENANCE_SCHEMA_VERSION,
        "source": "operator_override",
        "run_id": run.id,
        "actor": actor_value,
        "recorded_at": timestamp.astimezone(UTC).isoformat(),
        "previous_value": _finite(previous_value),
        "value": current_value,
        "note_sha256": hashlib.sha256(str(note or "").encode("utf-8")).hexdigest(),
    }
    receipt = {**payload, "artifact_ref": f"sha256:{_canonical_sha256(payload)}"}
    output_ref = copy.deepcopy(run.output_ref) if isinstance(run.output_ref, Mapping) else {}
    history = output_ref.get("operator_value_overrides")
    rows = list(history) if isinstance(history, list) else []
    rows.append(receipt)
    output_ref["operator_value_overrides"] = rows
    run.output_ref = output_ref
    return receipt


def _validated_operator_receipt(run: Run) -> dict[str, Any] | None:
    output_ref = run.output_ref if isinstance(run.output_ref, Mapping) else {}
    history = output_ref.get("operator_value_overrides")
    if not isinstance(history, list) or not history:
        return None
    row = history[-1]
    expected = {
        "schema_version",
        "source",
        "run_id",
        "actor",
        "recorded_at",
        "previous_value",
        "value",
        "note_sha256",
        "artifact_ref",
    }
    if not isinstance(row, Mapping) or set(row) != expected:
        return None
    payload = {key: row.get(key) for key in expected - {"artifact_ref"}}
    if (
        payload["schema_version"] != RUN_OUTCOME_PROVENANCE_SCHEMA_VERSION
        or payload["source"] != "operator_override"
        or payload["run_id"] != run.id
        or not str(payload["actor"] or "").strip()
        or _finite(payload["value"]) != _finite(run.value_estimated)
        or row.get("artifact_ref") != f"sha256:{_canonical_sha256(payload)}"
    ):
        return None
    try:
        recorded_at = datetime.fromisoformat(
            str(payload["recorded_at"]).replace("Z", "+00:00")
        )
    except (TypeError, ValueError):
        return None
    if recorded_at.tzinfo is None:
        return None
    return dict(row)


def run_measurement_provenance(run: Run) -> dict[str, Any] | None:
    """Return independently checkable provenance for the current Run value."""

    if run.value_source == "operator":
        receipt = _validated_operator_receipt(run)
        if receipt is None:
            return None
        return {
            "schema_version": RUN_OUTCOME_PROVENANCE_SCHEMA_VERSION,
            "source": "operator_override",
            "actor": receipt["actor"],
            "recorded_at": receipt["recorded_at"],
            "artifact_ref": receipt["artifact_ref"],
        }
    if run.value_source != "auto" or run.completed_at is None:
        return None
    input_ref = run.input_ref if isinstance(run.input_ref, Mapping) else {}
    execution = input_ref.get("execution")
    if not isinstance(execution, Mapping):
        return None
    policy = validated_control_policy_execution_contract(execution.get("control_policy"))
    if policy is None:
        return None
    completed_at = run.completed_at
    if completed_at.tzinfo is None:
        completed_at = completed_at.replace(tzinfo=UTC)
    payload = {
        "schema_version": RUN_OUTCOME_PROVENANCE_SCHEMA_VERSION,
        "source": "runtime_auto",
        "run_id": run.id,
        "system_id": run.system_id,
        "actor": "run_engine",
        "recorded_at": completed_at.astimezone(UTC).isoformat(),
        "value": _finite(run.value_estimated),
        "value_source": run.value_source,
        "control_policy": policy,
        "flow_sha256": execution.get("flow_sha256"),
        "runtime_revision": execution.get("runtime_revision"),
    }
    if payload["value"] is None:
        return None
    return {
        "schema_version": RUN_OUTCOME_PROVENANCE_SCHEMA_VERSION,
        "source": "runtime_auto",
        "actor": "run_engine",
        "recorded_at": payload["recorded_at"],
        "artifact_ref": f"sha256:{_canonical_sha256(payload)}",
    }


def is_canary_authored_operator_outcome(run: Run) -> bool:
    input_ref = run.input_ref if isinstance(run.input_ref, Mapping) else {}
    return run.value_source == "operator" and input_ref.get("lot8_value_loop_canary") is True


__all__ = [
    "RUN_OUTCOME_PROVENANCE_SCHEMA_VERSION",
    "is_canary_authored_operator_outcome",
    "record_operator_outcome_override",
    "run_measurement_provenance",
]
