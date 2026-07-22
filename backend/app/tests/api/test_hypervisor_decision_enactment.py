"""Atomicity and tenant-boundary tests for generic Decision enactment."""
from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.v1.endpoints import hypervisor
from app.models.audit import AuditLog
from app.models.decision import Decision
from app.models.system import System
from app.models.user import User
from app.models.workspace import Workspace
from app.services import audit_logger


def _seed(db, *, status: str = "accepted", action: str = "pause"):
    workspace = Workspace(
        id=str(uuid4()),
        slug=f"decision-{uuid4()}",
        name="Decision workspace",
    )
    user = User(
        id=str(uuid4()),
        username=f"operator-{uuid4()}",
        email=f"operator-{uuid4()}@example.test",
        is_active=True,
    )
    system = System(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name="Governed System",
        objective="Atomic Decision test",
        status="active",
    )
    decision = Decision(
        id=str(uuid4()),
        workspace_id=workspace.id,
        scope="system",
        target_id=system.id,
        kind="recommendation",
        status=status,
        title="Pause the System",
        rationale={"action": action},
    )
    db.add_all([workspace, user, system, decision])
    db.commit()
    return workspace, user, system, decision


def _apply(db, workspace, user, decision, body=None):
    return asyncio.run(
        hypervisor.apply_decision_endpoint(
            decision.id,
            body=body,
            workspace=workspace,
            user=user,
            db=db,
        )
    )


@pytest.fixture(autouse=True)
def _allow_authorized_actor(monkeypatch):
    monkeypatch.setattr(hypervisor, "enforce_action", lambda *_args, **_kwargs: None)


def test_legacy_apply_is_disabled_in_favour_of_the_value_loop(db_session):
    workspace, user, system, decision = _seed(db_session)

    with pytest.raises(HTTPException) as caught:
        _apply(db_session, workspace, user, decision)

    assert caught.value.status_code == 409
    assert caught.value.detail["code"] == "LEGACY_DECISION_ACTUATOR_DISABLED"
    assert caught.value.detail["state"] == "not_configured"
    db_session.refresh(system)
    db_session.refresh(decision)
    assert system.status == "active"
    assert decision.status == "accepted"
    assert decision.applied_by is None
    assert db_session.query(AuditLog).filter_by(
        workspace_id=workspace.id,
        event_type="decision.actuation.applied",
    ).count() == 0


def test_proposed_decision_cannot_mutate_before_transition_validation(db_session):
    workspace, user, system, decision = _seed(db_session, status="proposed")

    with pytest.raises(HTTPException) as caught:
        _apply(db_session, workspace, user, decision)

    assert caught.value.status_code == 409
    db_session.refresh(system)
    db_session.refresh(decision)
    assert system.status == "active"
    assert decision.status == "proposed"


def test_unsupported_action_is_not_recorded_as_applied(db_session):
    workspace, user, system, decision = _seed(db_session, action="decorative-noop")

    with pytest.raises(HTTPException) as caught:
        _apply(db_session, workspace, user, decision)

    assert caught.value.status_code == 409
    db_session.refresh(system)
    db_session.refresh(decision)
    assert system.status == "active"
    assert decision.status == "accepted"
    assert decision.applied_patch is None


def test_cross_workspace_target_is_never_enacted(db_session):
    workspace, user, system, decision = _seed(db_session)
    other = Workspace(
        id=str(uuid4()),
        slug=f"other-{uuid4()}",
        name="Other workspace",
    )
    other_system = System(
        id=str(uuid4()),
        workspace_id=other.id,
        name="Foreign System",
        objective="Must remain isolated",
        status="active",
    )
    db_session.add_all([other, other_system])
    decision.target_id = other_system.id
    db_session.commit()

    with pytest.raises(HTTPException) as caught:
        _apply(db_session, workspace, user, decision)

    assert caught.value.status_code == 409
    db_session.refresh(other_system)
    db_session.refresh(decision)
    assert other_system.status == "active"
    assert decision.status == "accepted"
    assert system.status == "active"


def test_client_patch_or_no_enactment_cannot_forge_applied_state(db_session):
    workspace, user, system, decision = _seed(db_session)

    for body in (
        hypervisor.DecisionApplyRequest(patch={"status": "pretend"}),
        hypervisor.DecisionApplyRequest(enact=False),
    ):
        with pytest.raises(HTTPException) as caught:
            _apply(db_session, workspace, user, decision, body)
        assert caught.value.status_code == 400

    db_session.refresh(system)
    db_session.refresh(decision)
    assert system.status == "active"
    assert decision.status == "accepted"


def test_disabled_actuator_does_not_attempt_an_audit_write(db_session, monkeypatch):
    workspace, user, system, decision = _seed(db_session)

    def _unexpected_audit(**_kwargs):
        raise AssertionError("retired actuator must not attempt an audit write")

    monkeypatch.setattr(audit_logger, "emit_audit_event", _unexpected_audit)

    with pytest.raises(HTTPException) as caught:
        _apply(db_session, workspace, user, decision)

    assert caught.value.status_code == 409
    db_session.refresh(system)
    db_session.refresh(decision)
    assert system.status == "active"
    assert decision.status == "accepted"
    assert decision.applied_at is None
