"""Canonical Decision state machine.

Transitions:

    proposed -> accepted
    proposed -> rejected
    accepted -> applied

Any other transition raises :class:`InvalidTransition`.

Operators can accept/reject a `proposed` recommendation, then enact it
(transition to `applied`) either synchronously or later. The enactment
payload is captured in ``applied_patch``.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session as DBSession

from app.models.decision import Decision
from app.schemas.canonical import DecisionState


class InvalidTransition(ValueError):
    """Raised when a decision state transition is not allowed."""


_ALLOWED = {
    DecisionState.proposed.value: {DecisionState.accepted.value, DecisionState.rejected.value},
    DecisionState.accepted.value: {DecisionState.applied.value},
    DecisionState.rejected.value: set(),
    DecisionState.applied.value: set(),
}


def _transition(
    db: DBSession,
    decision: Decision,
    *,
    target: DecisionState,
    actor: Optional[str],
    note: Optional[str] = None,
) -> Decision:
    current = decision.status or DecisionState.proposed.value
    if target.value not in _ALLOWED.get(current, set()):
        raise InvalidTransition(
            f"cannot transition decision from {current!r} to {target.value!r}"
        )
    decision.status = target.value
    if target in (DecisionState.accepted, DecisionState.rejected):
        decision.approved_by = actor
        decision.approved_at = datetime.utcnow()
    if note:
        decision.notes = (decision.notes or "") + ("\n" if decision.notes else "") + note
    db.commit()
    return decision


def accept(
    db: DBSession,
    decision: Decision,
    *,
    actor: Optional[str] = None,
    note: Optional[str] = None,
) -> Decision:
    return _transition(db, decision, target=DecisionState.accepted, actor=actor, note=note)


def reject(
    db: DBSession,
    decision: Decision,
    *,
    actor: Optional[str] = None,
    note: Optional[str] = None,
) -> Decision:
    return _transition(db, decision, target=DecisionState.rejected, actor=actor, note=note)


def apply(
    db: DBSession,
    decision: Decision,
    *,
    actor: Optional[str] = None,
    patch: Optional[Dict[str, Any]] = None,
) -> Decision:
    current = decision.status or DecisionState.proposed.value
    if current != DecisionState.accepted.value:
        raise InvalidTransition(
            f"cannot apply decision in state {current!r}: must be 'accepted' first"
        )
    decision.status = DecisionState.applied.value
    decision.applied_at = datetime.utcnow()
    decision.applied_by = actor
    decision.applied_patch = patch or {}
    db.commit()
    return decision
