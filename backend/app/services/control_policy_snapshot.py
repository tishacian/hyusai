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


__all__ = [
    "CONTROL_POLICY_EXECUTION_SCHEMA_VERSION",
    "control_policy_execution_contract",
    "validated_control_policy_execution_contract",
]
