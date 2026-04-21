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
``Decision.applied_patch`` by the state machine ``apply`` call. The
function is intentionally *forgiving*: when the rationale is incomplete
or the target no longer exists, it records a ``noop`` patch rather than
raising, so the operator UI can still mark the decision as handled.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from sqlalchemy.orm import Session as DBSession

from app.models.capability import Capability
from app.models.decision import Decision
from app.models.policy import AdaptivePolicy, ControlPolicy
from app.models.system import System


def enact_decision(db: DBSession, decision: Decision) -> Dict[str, Any]:
    """Translate the decision into concrete policy/system writes.

    Returns a patch dict (stored on ``Decision.applied_patch``) describing
    what was mutated. On failure, the patch carries ``{"status": "noop"}``
    plus a reason string.
    """
    rationale: Dict[str, Any] = decision.rationale or {}
    action = (rationale.get("action") or decision.kind or "").lower()

    try:
        if action in ("scale", "reduce"):
            return _enact_scale(db, decision, rationale, reduce=(action == "reduce"))
        if action == "adjust":
            return _enact_adjust(db, decision, rationale)
        if action == "pause":
            return _enact_status(db, decision, "paused")
        if action == "deploy":
            return _enact_status(db, decision, "active")
    except Exception as exc:  # noqa: BLE001
        return {"status": "noop", "reason": f"enactment_error: {exc!r}"}

    return {"status": "noop", "reason": f"unsupported_action: {action!r}"}


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
    if reduce:
        factor = min(factor, 1.0) if factor < 1.0 else 1.0 / factor

    cap = _resolve_capability(db, decision)
    if cap is None:
        return {"status": "noop", "reason": "capability_not_found"}

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

    db.commit()
    return patch


def _enact_adjust(
    db: DBSession,
    decision: Decision,
    rationale: Dict[str, Any],
) -> Dict[str, Any]:
    updates: Dict[str, Any] = rationale.get("policy_updates") or {}
    if not updates:
        return {"status": "noop", "reason": "empty_policy_updates"}

    target_scope = decision.scope or "system"
    target_id = decision.target_id

    policy = (
        db.query(ControlPolicy)
        .filter(ControlPolicy.scope == target_scope, ControlPolicy.target_id == target_id)
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
        before = getattr(policy, key)
        setattr(policy, key, value)
        applied[key] = {"before": before, "after": value}

    # AdaptivePolicy trigger updates are accepted under the same umbrella.
    triggers: Dict[str, Any] = rationale.get("adaptive_triggers") or {}
    if triggers:
        adaptive = (
            db.query(AdaptivePolicy)
            .filter(AdaptivePolicy.scope == target_scope, AdaptivePolicy.target_id == target_id)
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

    db.commit()
    return {
        "action": "adjust",
        "scope": target_scope,
        "target_id": target_id,
        "policy_id": policy.id,
        "changes": applied,
    }


def _enact_status(db: DBSession, decision: Decision, status: str) -> Dict[str, Any]:
    if (decision.scope or "") != "system" or not decision.target_id:
        return {"status": "noop", "reason": "status_action_requires_system_scope"}
    sys_row = db.query(System).filter(System.id == decision.target_id).first()
    if sys_row is None:
        return {"status": "noop", "reason": "system_not_found"}
    before = sys_row.status
    sys_row.status = status
    db.commit()
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
        return db.query(Capability).filter(Capability.id == decision.target_id).first()
    rationale = decision.rationale or {}
    cap_id = rationale.get("capability_id")
    if cap_id:
        return db.query(Capability).filter(Capability.id == cap_id).first()
    return None


def _as_float(v: Any, default: float) -> float:
    try:
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default
