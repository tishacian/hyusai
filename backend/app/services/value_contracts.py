"""Governed value contracts of automations (ADR 0003 lot 3).

A contract names the owner, the indicator and its unit, the target, the
period, the convention (what one business unit is worth) and the source. It
reaches the Work, Hypervisor and Flow cards only once the owner it names has
approved it: proposing is a System administration act, like the operational
objective; approving belongs to the owner, even when they proposed it.

The gap is measured, never typed in: the operational measure of the indicator
over the contract period, minus the target, once the period is over and the
evidence complete. During the period the card shows progress. It is never
converted into money: the convention is named, and economic impact stays the
value loop's to attest.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime, time
from typing import Any

from sqlalchemy.orm import Session as DBSession

from app.models.capability import Capability
from app.models.system import System
from app.models.user import User
from app.models.value_contract import (
    APPROVED,
    PROPOSED,
    REJECTED,
    SUPERSEDED,
    WITHDRAWN,
    ValueContract,
)
from app.models.workspace import WorkspaceMember
from app.schemas.operational_objective import UNITS
from app.schemas.value_contract import INDICATORS, ValueContractProposal, ValueContractTerms

HISTORY_LIMIT = 20


class ValueContractError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 409):
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def terms_of(contract: ValueContract) -> dict[str, Any]:
    return {
        "owner_user_id": contract.owner_user_id,
        "indicator": contract.indicator,
        "unit": contract.unit,
        "target": contract.target,
        "period_start": contract.period_start.isoformat(),
        "period_end": contract.period_end.isoformat(),
        "convention": dict(contract.convention or {}),
        "source": dict(contract.source or {}),
    }


def content_sha256(terms: Mapping[str, Any]) -> str:
    encoded = json.dumps(dict(terms), sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _terms_from(proposal: ValueContractTerms) -> dict[str, Any]:
    return {
        "owner_user_id": proposal.owner_user_id,
        "indicator": proposal.indicator,
        "unit": UNITS[proposal.indicator],
        "target": float(proposal.target),
        "period_start": proposal.period_start.isoformat(),
        "period_end": proposal.period_end.isoformat(),
        "convention": proposal.convention.model_dump(mode="json"),
        "source": proposal.source.model_dump(mode="json"),
    }


def revisions(db: DBSession, system_id: str) -> list[ValueContract]:
    return (
        db.query(ValueContract)
        .filter(ValueContract.system_id == system_id)
        .order_by(ValueContract.revision.desc())
        .all()
    )


def approved(db: DBSession, system_id: str) -> ValueContract | None:
    return (
        db.query(ValueContract)
        .filter(ValueContract.system_id == system_id, ValueContract.status == APPROVED)
        .order_by(ValueContract.revision.desc())
        .first()
    )


def pending(db: DBSession, system_id: str) -> ValueContract | None:
    return (
        db.query(ValueContract)
        .filter(ValueContract.system_id == system_id, ValueContract.status == PROPOSED)
        .order_by(ValueContract.revision.desc())
        .first()
    )


def owner_options(db: DBSession, workspace: Any) -> list[dict[str, str]]:
    """Active members of the workspace: the people a contract may name."""

    rows = (
        db.query(User)
        .join(WorkspaceMember, WorkspaceMember.user_id == User.id)
        .filter(WorkspaceMember.workspace_id == workspace.id, User.is_active.is_(True))
        .order_by(User.email.asc(), User.username.asc())
        .all()
    )
    return [{"user_id": row.id, "label": user_label(row)} for row in rows]


def user_label(user: User | None) -> str:
    if user is None:
        return ""
    return str(user.email or user.username or user.id)


def _is_active_member(db: DBSession, workspace: Any, user_id: str) -> bool:
    return (
        db.query(WorkspaceMember)
        .join(User, User.id == WorkspaceMember.user_id)
        .filter(
            WorkspaceMember.workspace_id == workspace.id,
            WorkspaceMember.user_id == user_id,
            User.is_active.is_(True),
        )
        .first()
        is not None
    )


def propose(
    db: DBSession,
    *,
    workspace: Any,
    system: System,
    user: User,
    proposal: ValueContractProposal,
    now: datetime | None = None,
) -> ValueContract:
    """A new revision, written against the latest one. A pending one is withdrawn."""

    now = now or datetime.utcnow()
    locked = (
        db.query(System)
        .filter(System.id == system.id, System.workspace_id == workspace.id)
        .populate_existing()
        .with_for_update(of=System)
        .one()
    )
    history = revisions(db, locked.id)
    latest = history[0].revision if history else 0
    if proposal.expected_revision != latest:
        raise ValueContractError(
            "value_contract_stale",
            f"The contract moved to revision {latest}; read it again before proposing",
        )
    if not _is_active_member(db, workspace, proposal.owner_user_id):
        raise ValueContractError(
            "value_contract_owner_not_member",
            "The owner must be an active member of this workspace",
            422,
        )
    terms = _terms_from(proposal)
    for row in history:
        if row.status == PROPOSED:
            row.status = WITHDRAWN
            row.decided_at = now
            row.decided_by_user_id = user.id
            row.decision_note = f"withdrawn by revision {latest + 1}"
    contract = ValueContract(
        workspace_id=workspace.id,
        system_id=locked.id,
        revision=latest + 1,
        status=PROPOSED,
        owner_user_id=terms["owner_user_id"],
        indicator=terms["indicator"],
        unit=terms["unit"],
        target=terms["target"],
        period_start=proposal.period_start,
        period_end=proposal.period_end,
        convention=terms["convention"],
        source=terms["source"],
        content_sha256=content_sha256(terms),
        proposed_by_user_id=user.id,
        proposed_at=now,
    )
    db.add(contract)
    db.flush()
    from app.services.audit_logger import emit_audit_event

    emit_audit_event(
        db=db,
        workspace_id=workspace.id,
        event_type="value_contract.proposed",
        actor=user.id,
        details={
            "system_id": locked.id,
            "revision": contract.revision,
            "owner_user_id": contract.owner_user_id,
            "indicator": contract.indicator,
            "content_sha256": contract.content_sha256,
        },
    )
    db.commit()
    db.refresh(contract)
    return contract


def decide(
    db: DBSession,
    *,
    workspace: Any,
    system: System,
    user: User,
    revision: int,
    content_sha: str,
    approve: bool,
    note: str | None = None,
    now: datetime | None = None,
) -> ValueContract:
    """The owner approves or rejects exactly the terms they read."""

    now = now or datetime.utcnow()
    contract = (
        db.query(ValueContract)
        .filter(
            ValueContract.system_id == system.id,
            ValueContract.workspace_id == workspace.id,
            ValueContract.revision == revision,
        )
        .populate_existing()
        .with_for_update()
        .one_or_none()
    )
    if contract is None:
        raise ValueContractError("value_contract_not_found", "No such contract revision", 404)
    if contract.status != PROPOSED:
        raise ValueContractError(
            "value_contract_not_pending", f"Revision {revision} is {contract.status}, not proposed"
        )
    if contract.owner_user_id != user.id:
        raise ValueContractError(
            "value_contract_owner_only", "Only the owner the contract names can decide on it", 403
        )
    if contract.content_sha256 != content_sha:
        raise ValueContractError(
            "value_contract_changed", "The terms changed after they were read; read them again"
        )
    if approve:
        for row in revisions(db, system.id):
            if row.status == APPROVED:
                row.status = SUPERSEDED
    contract.status = APPROVED if approve else REJECTED
    contract.decided_by_user_id = user.id
    contract.decided_at = now
    contract.decision_note = note
    from app.services.audit_logger import emit_audit_event

    emit_audit_event(
        db=db,
        workspace_id=workspace.id,
        event_type="value_contract.approved" if approve else "value_contract.rejected",
        actor=user.id,
        details={
            "system_id": system.id,
            "revision": contract.revision,
            "content_sha256": contract.content_sha256,
        },
    )
    db.commit()
    db.refresh(contract)
    return contract


def public(db: DBSession, contract: ValueContract | None) -> dict[str, Any] | None:
    if contract is None:
        return None
    ids = {contract.owner_user_id, contract.proposed_by_user_id, contract.decided_by_user_id} - {
        None
    }
    users = {row.id: row for row in db.query(User).filter(User.id.in_(ids)).all()} if ids else {}
    return {
        "revision": contract.revision,
        "status": contract.status,
        **terms_of(contract),
        "owner": user_label(users.get(contract.owner_user_id)),
        "content_sha256": contract.content_sha256,
        "proposed_by": user_label(users.get(contract.proposed_by_user_id)),
        "proposed_at": contract.proposed_at.isoformat() if contract.proposed_at else None,
        "decided_by": user_label(users.get(contract.decided_by_user_id)) or None,
        "decided_at": contract.decided_at.isoformat() if contract.decided_at else None,
        "decision_note": contract.decision_note,
    }


def prefill(db: DBSession, system: System) -> dict[str, Any]:
    """A first proposal drawn from the operational objective and the value basis."""

    draft: dict[str, Any] = {}
    objective = (system.settings or {}).get("operational_objective")
    if isinstance(objective, Mapping):
        if objective.get("metric") in INDICATORS:
            draft["indicator"] = objective.get("metric")
            draft["target"] = objective.get("target")
        for key in ("period_start", "period_end"):
            if objective.get(key):
                draft[key] = objective.get(key)
        if objective.get("comparison_reference"):
            draft["source"] = {
                "kind": "document",
                "reference": objective.get("comparison_reference"),
            }
    capability = (
        db.query(Capability).filter(Capability.id == system.capability_id).one_or_none()
        if system.capability_id
        else None
    )
    basis = capability.value_basis if capability is not None else None
    if isinstance(basis, Mapping) and basis.get("value_per_unit") is not None:
        draft["convention"] = {
            "value_per_unit": basis.get("value_per_unit"),
            "currency": basis.get("currency") or "EUR",
            "unit": basis.get("unit")
            or (capability.output_unit if capability is not None else "")
            or "",
        }
    return draft


def card_convention(db: DBSession, contract: ValueContract | None) -> dict[str, Any]:
    """The convention line of a card: the approved contract, else absent."""

    if contract is None:
        return {"status": "absent"}
    shown = public(db, contract) or {}
    convention = shown.get("convention") or {}
    return {
        "status": "approved",
        "unit": convention.get("unit"),
        "currency": convention.get("currency"),
        "value_per_unit": convention.get("value_per_unit"),
        "declared_by": shown.get("owner"),
        "declared_at": shown.get("decided_at"),
        "contract": {
            "revision": contract.revision,
            "content_sha256": contract.content_sha256,
            "owner": shown.get("owner"),
            "indicator": contract.indicator,
            "indicator_unit": contract.unit,
            "target": contract.target,
            "period_start": contract.period_start.isoformat(),
            "period_end": contract.period_end.isoformat(),
            "source": dict(contract.source or {}),
        },
    }


def measured_gap(
    db: DBSession,
    *,
    user: Any,
    workspace: Any,
    system: System,
    contract: ValueContract | None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """The indicator against the target over the contract period."""

    if contract is None or user is None:
        return {"status": "absent"}
    from app.services.operational_metrics import operational_metrics

    now = now or datetime.utcnow()
    start = datetime.combine(contract.period_start, time.min)
    end = datetime.combine(contract.period_end, time.min)
    base = {
        "indicator": contract.indicator,
        "unit": contract.unit,
        "target": contract.target,
        "period_start": contract.period_start.isoformat(),
        "period_end": contract.period_end.isoformat(),
        "contract_revision": contract.revision,
    }
    if now < start:
        return {"status": "not_started", **base}
    measured = operational_metrics(
        db,
        user=user,
        workspace=workspace,
        system=system,
        objective={
            "metric": contract.indicator,
            "target": contract.target,
            "period_start": contract.period_start.isoformat(),
            "period_end": contract.period_end.isoformat(),
            "owner": contract.owner_user_id,
            "comparison_reference": str(
                (contract.source or {}).get("reference") or "value contract"
            ),
        },
        now=now,
    )
    fact = next(item for item in measured["metrics"] if item["metric"] == contract.indicator)
    value = fact.get("value")
    if fact.get("delta") is not None:
        return {"status": "measured", **base, "value": value, "delta": fact["delta"]}
    if now < end:
        return {"status": "in_progress", **base, "value": value}
    return {
        "status": "not_comparable",
        **base,
        "value": value,
        "reason": "incomplete" if not fact.get("complete") else "not_measured",
    }


def card_value(
    db: DBSession, *, user: Any, workspace: Any, system: System, now: datetime | None = None
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Convention and gap of the approved contract, for every card and export."""

    contract = approved(db, system.id)
    return (
        card_convention(db, contract),
        measured_gap(db, user=user, workspace=workspace, system=system, contract=contract, now=now),
    )
