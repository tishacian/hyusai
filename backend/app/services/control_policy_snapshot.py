"""Canonical, server-owned execution identity for a ControlPolicy.

The value loop may only measure a Run against an actuation when that Run
actually executed the exact post-actuation policy.  Database timestamps are
not sufficient evidence: this contract hashes every policy field consumed by
the runtime and is frozen into the Run at its first real start.
"""
from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from collections.abc import Mapping
from typing import Any

from app.models.policy import ControlPolicy

CONTROL_POLICY_EXECUTION_SCHEMA_VERSION = 1
_DIGEST = re.compile(r"[0-9a-f]{64}")
_REVISION = re.compile(r"control-policy-v1:[0-9a-f]{64}")


def _canonical_payload(policy: ControlPolicy) -> dict[str, Any]:
    return {
        "schema_version": CONTROL_POLICY_EXECUTION_SCHEMA_VERSION,
        "policy_id": str(policy.id),
        "workspace_id": str(policy.workspace_id) if policy.workspace_id else None,
        "scope": policy.scope,
        "target_id": str(policy.target_id) if policy.target_id else None,
        "max_cost_per_decision": policy.max_cost_per_decision,
        "max_latency_ms": policy.max_latency_ms,
        "mandatory_hitl_if_confidence_below": (
            policy.mandatory_hitl_if_confidence_below
        ),
        "allowed_models": list(policy.allowed_models or []),
        "allowed_skills": list(policy.allowed_skills or []),
        "extra": dict(policy.extra or {}),
    }


def control_policy_execution_contract(policy: ControlPolicy) -> dict[str, Any]:
    """Return the compact identity of the policy's effective runtime state."""

    payload = _canonical_payload(policy)
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    return {
        "schema_version": CONTROL_POLICY_EXECUTION_SCHEMA_VERSION,
        "policy_id": str(policy.id),
        "revision": f"control-policy-v1:{digest}",
        "sha256": digest,
    }


def validated_control_policy_execution_contract(
    value: Any,
    *,
    policy_id: str | None = None,
) -> dict[str, Any] | None:
    """Return an exact canonical contract, or ``None`` for malformed input."""

    if not isinstance(value, Mapping) or set(value) != {
        "schema_version",
        "policy_id",
        "revision",
        "sha256",
    }:
        return None
    candidate = {
        "schema_version": value.get("schema_version"),
        "policy_id": value.get("policy_id"),
        "revision": value.get("revision"),
        "sha256": value.get("sha256"),
    }
    if candidate["schema_version"] != CONTROL_POLICY_EXECUTION_SCHEMA_VERSION:
        return None
    if not isinstance(candidate["policy_id"], str) or not candidate["policy_id"]:
        return None
    if policy_id is not None and candidate["policy_id"] != policy_id:
        return None
    if _DIGEST.fullmatch(str(candidate["sha256"] or "")) is None:
        return None
    if _REVISION.fullmatch(str(candidate["revision"] or "")) is None:
        return None
    if candidate["revision"] != f"control-policy-v1:{candidate['sha256']}":
        return None
    return candidate


def freeze_control_policy(
    policy: ControlPolicy | None, *, workspace_id: str | None, system_id: str,
) -> dict[str, Any]:
    """Freeze runtime content, including an explicit absence, at publication.

    This envelope is server-owned and belongs in the immutable executable
    contract, never in caller-provided Run input or a mutable policy reference.
    """
    value = {
        "schema_version": 1,
        "state": "configured" if policy is not None else "not_configured",
        "workspace_id": workspace_id,
        "system_id": system_id,
        "policy": _canonical_payload(policy) if policy is not None else None,
    }
    value["sha256"] = _snapshot_digest(value)
    return validate_frozen_control_policy(value, workspace_id=workspace_id, system_id=system_id)


def _snapshot_digest(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")).hexdigest()


def validate_frozen_control_policy(
    value: Any, *, workspace_id: str | None = None, system_id: str | None = None,
) -> dict[str, Any]:
    """Validate content and tenant binding; present but invalid never falls back."""
    if not isinstance(value, Mapping) or set(value) != {
        "schema_version", "state", "workspace_id", "system_id", "policy", "sha256",
    }:
        raise ValueError("control_policy_snapshot_invalid_shape")
    result = deepcopy(dict(value))
    if (result["schema_version"] != 1
            or result["state"] not in {"configured", "not_configured"}
            or not isinstance(result["system_id"], str) or not result["system_id"]
            or result["workspace_id"] is not None and not isinstance(result["workspace_id"], str)):
        raise ValueError("control_policy_snapshot_invalid_identity")
    if ((workspace_id is not None and result["workspace_id"] != workspace_id)
            or (system_id is not None and result["system_id"] != system_id)):
        raise ValueError("control_policy_snapshot_scope_mismatch")
    digest = result.pop("sha256")
    if not isinstance(digest, str) or _DIGEST.fullmatch(digest) is None or digest != _snapshot_digest(result):
        raise ValueError("control_policy_snapshot_hash_mismatch")
    result["sha256"] = digest
    payload = result["policy"]
    if result["state"] == "not_configured":
        if payload is not None:
            raise ValueError("control_policy_snapshot_unexpected_policy")
        return result
    if not isinstance(payload, dict) or set(payload) != {
        "schema_version", "policy_id", "workspace_id", "scope", "target_id",
        "max_cost_per_decision", "max_latency_ms", "mandatory_hitl_if_confidence_below",
        "allowed_models", "allowed_skills", "extra",
    }:
        raise ValueError("control_policy_snapshot_invalid_policy")
    if (payload["schema_version"] != CONTROL_POLICY_EXECUTION_SCHEMA_VERSION
            or not isinstance(payload["policy_id"], str) or not payload["policy_id"]
            or payload["workspace_id"] != result["workspace_id"]
            or payload["scope"] != "system" or payload["target_id"] != result["system_id"]
            or not isinstance(payload["extra"], dict)):
        raise ValueError("control_policy_snapshot_policy_scope_mismatch")
    for field in ("allowed_models", "allowed_skills"):
        if not isinstance(payload[field], list) or any(not isinstance(item, str) for item in payload[field]):
            raise ValueError("control_policy_snapshot_invalid_allowlist")
    for field in ("max_cost_per_decision", "max_latency_ms", "mandatory_hitl_if_confidence_below"):
        if payload[field] is not None and (isinstance(payload[field], bool) or not isinstance(payload[field], (int, float))):
            raise ValueError("control_policy_snapshot_invalid_threshold")
    return result


def thaw_control_policy(
    value: Any, *, workspace_id: str | None, system_id: str,
) -> ControlPolicy | None:
    """Build an unattached read-only runtime value; never load the mutable row."""
    snapshot = validate_frozen_control_policy(value, workspace_id=workspace_id, system_id=system_id)
    if snapshot["workspace_id"] != workspace_id:
        raise ValueError("control_policy_snapshot_scope_mismatch")
    payload = snapshot["policy"]
    if payload is None:
        return None
    fields = {key: deepcopy(item) for key, item in payload.items() if key not in {"schema_version", "policy_id"}}
    return ControlPolicy(id=payload["policy_id"], name="Frozen execution policy", **fields)


__all__ = [
    "CONTROL_POLICY_EXECUTION_SCHEMA_VERSION",
    "control_policy_execution_contract",
    "validated_control_policy_execution_contract",
    "freeze_control_policy",
    "validate_frozen_control_policy",
    "thaw_control_policy",
]
