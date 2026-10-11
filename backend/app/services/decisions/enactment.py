"""Decision → Policy enactment.

A Decision record carries the *intent* (e.g. "scale capability X by 1.5×")
but the actual policy write lives in ControlPolicy / AdaptivePolicy /
System. This module knows how to translate a decision's ``rationale`` +
``impact_estimate`` payload into concrete updates.

Supported actions (declared via ``decision.rationale.action``):

- ``scale``    : raise a capability's ``value_per_outcome`` and/or relax
                  an AdaptivePolicy trigger. Patch: {target: capability_id, factor: float}
- ``reduce``   : the inverse — lower caps, tighten triggers.
- ``adjust``   : update one or several ControlPolicy fields
                  (max_cost_per_decision, max_latency_ms, hitl threshold).
- ``pause``    : set System.status = 'paused' for scope=system decisions.
- ``deploy``   : set System.status = 'active' (or clone a draft to active).

The enactment returns a patch dict that is written onto
``Decision.applied_patch`` by the state machine ``apply`` call.  It never
commits: the caller owns the transaction that also records the state
transition and its audit row.  Missing targets, unsupported actions and empty
patches fail closed; an ``applied`` Decision must always correspond to a real
workspace-scoped mutation.
"""
from __future__ import annotations

import math
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session as DBSession

from app.models.capability import Capability
from app.models.decision import Decision
from app.models.policy import AdaptivePolicy, ControlPolicy
from app.models.system import System


class DecisionEnactmentError(ValueError):
    """Raised before a Decision can be marked applied without a real act."""


def enact_decision(db: DBSession, decision: Decision) -> Dict[str, Any]:
    """Translate the decision into concrete policy/system writes.

    Returns a patch dict (stored on ``Decision.applied_patch``) describing
    what was mutated.  The function flushes but never commits.
    """
    rationale: Dict[str, Any] = decision.rationale or {}
    action = (rationale.get("action") or decision.kind or "").lower()

    if action in ("scale", "reduce"):
        patch = _enact_scale(db, decision, rationale, reduce=(action == "reduce"))
    elif action == "adjust":
        patch = _enact_adjust(db, decision, rationale)
    elif action == "pause":
        patch = _enact_status(db, decision, "paused")
    elif action == "deploy":
        patch = _enact_status(db, decision, "active")
    else:
        raise DecisionEnactmentError(f"unsupported decision action: {action!r}")
    db.flush()
    return patch


# ---------------------------------------------------------------------------
# Action handlers
# ---------------------------------------------------------------------------
def _enact_scale(
    db: DBSession,
    decision: Decision,
    rationale: Dict[str, Any],
    *,
    reduce: bool,
) -> Dict[str, Any]:
    factor = _as_float(rationale.get("factor"), default=(0.85 if reduce else 1.15))
    if not math.isfinite(factor) or factor <= 0:
        raise DecisionEnactmentError("scale factor must be a positive finite number")
    if reduce:
        factor = min(factor, 1.0) if factor < 1.0 else 1.0 / factor

    cap = _resolve_capability(db, decision)
    if cap is None:
        raise DecisionEnactmentError("capability target was not found in the workspace")

    patch: Dict[str, Any] = {
        "action": "scale" if not reduce else "reduce",
        "capability_id": cap.id,
        "factor": factor,
        "changes": {},
    }

    before = cap.value_per_outcome
    if before is not None:
        cap.value_per_outcome = max(0.0, float(before) * factor)
        patch["changes"]["value_per_outcome"] = {
            "before": before,
            "after": cap.value_per_outcome,
        }

    roi_before = cap.roi_model or {}
    if isinstance(roi_before, dict) and roi_before.get("value_per_outcome") is not None:
        new_roi = dict(roi_before)
        new_roi["value_per_outcome"] = max(
            0.0, float(roi_before["value_per_outcome"]) * factor
        )
        cap.roi_model = new_roi
        patch["changes"]["roi_model.value_per_outcome"] = {
            "before": roi_before.get("value_per_outcome"),
            "after": new_roi["value_per_outcome"],
        }

    if not patch["changes"]:
        raise DecisionEnactmentError("scale action has no configured value to mutate")
    return patch


def _enact_adjust(
    db: DBSession,
    decision: Decision,
    rationale: Dict[str, Any],
) -> Dict[str, Any]:
    updates: Dict[str, Any] = rationale.get("policy_updates") or {}
    if not updates:
        raise DecisionEnactmentError("adjust action requires policy_updates")

    target_scope = decision.scope or "system"
    target_id = decision.target_id

    _validate_scoped_target(db, decision)
    policy = (
        db.query(ControlPolicy)
        .filter(
            ControlPolicy.workspace_id == decision.workspace_id,
            ControlPolicy.scope == target_scope,
            ControlPolicy.target_id == target_id,
        )
        .order_by(ControlPolicy.updated_at.desc())
        .first()
    )
    if policy is None:
        policy = ControlPolicy(
            workspace_id=decision.workspace_id,
            scope=target_scope,
            target_id=target_id,
            name=f"auto-{decision.id[:8]}",
        )
        db.add(policy)

    applied: Dict[str, Dict[str, Any]] = {}
    editable = {
        "max_cost_per_decision",
        "max_latency_ms",
        "mandatory_hitl_if_confidence_below",
        "allowed_models",
        "allowed_skills",
    }
    for key, value in updates.items():
        if key not in editable:
            continue
        value = _validated_policy_value(key, value)
        before = getattr(policy, key)
        setattr(policy, key, value)
        applied[key] = {"before": before, "after": value}

    # AdaptivePolicy trigger updates are accepted under the same umbrella.
    triggers: Dict[str, Any] = rationale.get("adaptive_triggers") or {}
    if not isinstance(triggers, dict):
        raise DecisionEnactmentError("adaptive_triggers must be an object")
    if triggers:
        adaptive = (
            db.query(AdaptivePolicy)
            .filter(
                AdaptivePolicy.workspace_id == decision.workspace_id,
                AdaptivePolicy.scope == target_scope,
                AdaptivePolicy.target_id == target_id,
            )
            .order_by(AdaptivePolicy.updated_at.desc())
            .first()
        )
        if adaptive is None:
            adaptive = AdaptivePolicy(
                workspace_id=decision.workspace_id,
                scope=target_scope,
                target_id=target_id,
                name=f"auto-{decision.id[:8]}",
                enabled=True,
            )
            db.add(adaptive)
        before_triggers = dict(adaptive.triggers or {})
        merged = {**before_triggers, **triggers}
        adaptive.triggers = merged
        applied["adaptive_triggers"] = {"before": before_triggers, "after": merged}

    if not applied:
        raise DecisionEnactmentError("adjust action contains no supported policy mutation")
    return {
        "action": "adjust",
        "scope": target_scope,
        "target_id": target_id,
        "policy_id": policy.id,
        "changes": applied,
    }


def _enact_status(db: DBSession, decision: Decision, status: str) -> Dict[str, Any]:
    if (decision.scope or "") != "system" or not decision.target_id:
        raise DecisionEnactmentError("status action requires a System target")
    sys_row = (
        db.query(System)
        .filter(
            System.id == decision.target_id,
            System.workspace_id == decision.workspace_id,
        )
        .first()
    )
    if sys_row is None:
        raise DecisionEnactmentError("system target was not found in the workspace")
    before = sys_row.status
    sys_row.status = status
    return {
        "action": "pause" if status == "paused" else "deploy",
        "system_id": sys_row.id,
        "changes": {"status": {"before": before, "after": status}},
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _resolve_capability(db: DBSession, decision: Decision) -> Optional[Capability]:
    if decision.scope == "capability" and decision.target_id:
        return (
            db.query(Capability)
            .filter(
                Capability.id == decision.target_id,
                Capability.workspace_id == decision.workspace_id,
            )
            .first()
        )
    rationale = decision.rationale or {}
    cap_id = rationale.get("capability_id")
    if cap_id:
        return (
            db.query(Capability)
            .filter(
                Capability.id == cap_id,
                Capability.workspace_id == decision.workspace_id,
            )
            .first()
        )
    return None


def _validate_scoped_target(db: DBSession, decision: Decision) -> None:
    if decision.scope == "system" and decision.target_id:
        exists = (
            db.query(System.id)
            .filter(
                System.id == decision.target_id,
                System.workspace_id == decision.workspace_id,
            )
            .first()
        )
    elif decision.scope == "capability" and decision.target_id:
        exists = (
            db.query(Capability.id)
            .filter(
                Capability.id == decision.target_id,
                Capability.workspace_id == decision.workspace_id,
            )
            .first()
        )
    else:
        raise DecisionEnactmentError("adjust action requires a System or Capability target")
    if exists is None:
        raise DecisionEnactmentError("decision target was not found in the workspace")


def _validated_policy_value(key: str, value: Any) -> Any:
    if key in {"max_cost_per_decision", "max_latency_ms"}:
        parsed = _as_float(value, default=-1.0)
        if not math.isfinite(parsed) or parsed < 0:
            raise DecisionEnactmentError(f"{key} must be a non-negative number")
        return parsed
    if key == "mandatory_hitl_if_confidence_below":
        parsed = _as_float(value, default=-1.0)
        if not math.isfinite(parsed) or not 0.0 <= parsed <= 1.0:
            raise DecisionEnactmentError(f"{key} must be between 0 and 1")
        return parsed
    if key in {"allowed_models", "allowed_skills"}:
        if not isinstance(value, list) or any(
            not isinstance(item, str) or not item.strip() for item in value
        ):
            raise DecisionEnactmentError(f"{key} must be a list of non-empty strings")
        return list(dict.fromkeys(item.strip() for item in value))
    raise DecisionEnactmentError(f"unsupported policy field: {key}")


def _as_float(v: Any, default: float) -> float:
    try:
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default
