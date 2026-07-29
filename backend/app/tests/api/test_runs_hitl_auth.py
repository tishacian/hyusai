"""Authorization and authenticated audit identity for Run HITL decisions."""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import runs
from app.core.iam.roles import (
    WORKSPACE_ADMIN,
    WORKSPACE_CONTRIBUTOR,
    WORKSPACE_REVIEWER,
)
from app.models.audit import AuditLog
from app.models.decision import Decision
from app.models.run import Run
from app.models.run_dispatch_outbox import RunDispatchOutbox
from app.models.system import System
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceIAMConfig, WorkspaceMember
from app.services.chat_execution_policy import (
    ANDRITZ_MIGRATION_MARKER,
    ANDRITZ_MIGRATION_REVISION,
)


@pytest.fixture(autouse=True)
def _stub_durable_ordinary_hitl_resume(monkeypatch):
    from app.services.run_engine import dispatch_outbox, engine

    monkeypatch.setattr(
        engine,
        "schedule_run_hitl_resume",
        lambda _run_id, *, decision_id: f"ordinary-resume-{decision_id}",
    )
    monkeypatch.setattr(runs, "_postgres_hitl_coordination_supported", lambda: True)
    monkeypatch.setattr(runs, "_durable_run_hitl_enabled", lambda _system: True)
    # API tests assert the durable DB handoff. RabbitMQ publication is covered
    # separately by the outbox unit tests and the real broker gate.
    monkeypatch.setattr(
        dispatch_outbox,
        "reconcile_dispatch_outbox",
        lambda **_kwargs: {"claimed": 0, "published": 0},
    )


def _client(db_session, workspace: Workspace, user: User) -> TestClient:
    app = FastAPI()
    app.include_router(runs.router, prefix="/runs")
    app.dependency_overrides[runs.get_current_workspace] = lambda: workspace
    app.dependency_overrides[runs.get_current_user] = lambda: user
    app.dependency_overrides[runs.get_db] = lambda: db_session
    return TestClient(app)


def _user(db_session, label: str) -> User:
    token = uuid4().hex[:8]
    user = User(
        id=str(uuid4()),
        username=f"{label}-{token}",
        email=f"{label}-{token}@example.invalid",
        role="user",
    )
    db_session.add(user)
    db_session.flush()
    return user


def _seed_pending_run(
    db_session,
    *,
    managed: bool = False,
) -> tuple[Workspace, User, User, WorkspaceMember, System, Run, Decision]:
    workspace = Workspace(
        id=str(uuid4()),
        name="HITL auth",
        slug=f"hitl-auth-{uuid4().hex[:8]}",
        settings={"family": "andritz" if managed else "generic"},
    )
    db_session.add(workspace)
    db_session.flush()
    initiator = _user(db_session, "initiator")
    other_member = _user(db_session, "other")
    initiator_membership = WorkspaceMember(
        user_id=initiator.id,
        workspace_id=workspace.id,
        role="member",
        role_template=WORKSPACE_CONTRIBUTOR,
    )
    other_membership = WorkspaceMember(
        user_id=other_member.id,
        workspace_id=workspace.id,
        role="member",
        role_template=WORKSPACE_CONTRIBUTOR,
    )
    system = System(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name="Managed Agentic chat" if managed else "Ordinary workflow",
        objective="test",
        status="active",
        settings={"system_type": "chat_agentic"} if managed else {},
        flow_definition=({"variant": "chat_agentic_thinking_v1", "nodes": []} if managed else {}),
    )
    if managed:
        workspace.settings = {
            "family": "andritz",
            ANDRITZ_MIGRATION_MARKER: {
                "revision": ANDRITZ_MIGRATION_REVISION,
                "schema": 1,
                "system_id": system.id,
            },
        }
    db_session.add(system)
    db_session.flush()
    run = Run(
        id=str(uuid4()),
        workspace_id=workspace.id,
        system_id=system.id,
        initiated_by_user_id=initiator.id,
        status="hitl_pending",
    )
    decision = Decision(
        id=str(uuid4()),
        workspace_id=workspace.id,
        scope="run",
        target_id=run.id,
        kind="hitl_approval",
        status="proposed",
        title="Human approval required",
    )
    run.checkpoints = [
        {
            "kind": "hitl_pause",
            "node_id": "approve",
            "decision_id": decision.id,
        }
    ]
    db_session.add_all(
        [
            workspace,
            initiator_membership,
            other_membership,
            system,
            run,
            decision,
        ]
    )
    db_session.commit()
    return (
        workspace,
        initiator,
        other_member,
        initiator_membership,
        system,
        run,
        decision,
    )


def _set_run_approve_mode(
    db_session,
    *,
    workspace: Workspace,
    user: User,
    mode: str,
) -> WorkspaceIAMConfig:
    config = WorkspaceIAMConfig(
        workspace_id=workspace.id,
        version=1,
        role_flags={},
        capability_overrides={
            "authorization_v2": {
                "policy_version": 2,
                "default_mode": "compat",
                "modes": {"run.approve": mode},
            }
        },
        updated_by_user_id=user.id,
    )
    db_session.add(config)
    db_session.commit()
    return config


def test_ordinary_hitl_rejects_non_owner_workspace_member(db_session, monkeypatch):
    workspace, _initiator, other, _membership, _system, run, decision = _seed_pending_run(
        db_session
    )
    monkeypatch.setattr(runs, "_resume_wrapper", lambda *_args: None)

    response = _client(db_session, workspace, other).post(
        f"/runs/{run.id}/hitl",
        json={"action": "accept", "actor": "spoofed-admin@example.invalid"},
    )

    assert response.status_code == 403
    db_session.refresh(decision)
    assert decision.status == "proposed"
    assert decision.approved_by is None


def test_ordinary_hitl_owner_uses_authenticated_actor_not_body(db_session, monkeypatch):
    workspace, initiator, _other, _membership, _system, run, decision = _seed_pending_run(
        db_session
    )
    monkeypatch.setattr(runs, "_resume_wrapper", lambda *_args: None)

    response = _client(db_session, workspace, initiator).post(
        f"/runs/{run.id}/hitl",
        json={
            "action": "accept",
            "actor": "spoofed-admin@example.invalid",
            "note": "reviewed",
        },
    )

    assert response.status_code == 200
    db_session.refresh(decision)
    assert decision.status == "accepted"
    assert decision.approved_by == initiator.email
    assert decision.approved_by != "spoofed-admin@example.invalid"
    assert decision.notes == "reviewed"


def test_hitl_run_approve_shadow_preserves_legacy_and_enforce_uses_candidate(
    db_session,
    monkeypatch,
    attest_authorization_v2,
):
    workspace, initiator, _other, _membership, _system, run, decision = _seed_pending_run(
        db_session
    )
    _set_run_approve_mode(
        db_session,
        workspace=workspace,
        user=initiator,
        mode="shadow",
    )
    monkeypatch.setattr(runs, "_resume_wrapper", lambda *_args: None)

    shadow_response = _client(db_session, workspace, initiator).post(
        f"/runs/{run.id}/hitl",
        json={"action": "accept", "actor": "spoofed-admin@example.invalid"},
    )

    assert shadow_response.status_code == 200
    db_session.refresh(decision)
    assert decision.status == "accepted"
    assert decision.approved_by == initiator.email
    shadow = db_session.query(AuditLog).filter(
        AuditLog.workspace_id == workspace.id,
        AuditLog.event_type == "iam.shadow.diff",
    ).one()
    assert shadow.details["resource"]["kind"] == "run"
    assert shadow.details["action"] == "run.approve"
    assert shadow.details["legacy_allowed"] is True
    assert shadow.details["candidate_allowed"] is False

    enforced_workspace, enforced_initiator, _other, _membership, _system, enforced_run, enforced_decision = (
        _seed_pending_run(db_session)
    )
    enforced_config = _set_run_approve_mode(
        db_session,
        workspace=enforced_workspace,
        user=enforced_initiator,
        mode="enforce",
    )
    attest_authorization_v2(enforced_config, ["run.approve"])
    db_session.commit()

    enforce_response = _client(db_session, enforced_workspace, enforced_initiator).post(
        f"/runs/{enforced_run.id}/hitl",
        json={"action": "accept"},
    )

    assert enforce_response.status_code == 403
    assert enforce_response.json()["detail"]["mode"] == "enforce"
    db_session.refresh(enforced_decision)
    assert enforced_decision.status == "proposed"
    assert enforced_decision.approved_by is None


def test_ordinary_hitl_idempotent_retry_republishes_same_durable_task(
    db_session,
    monkeypatch,
):
    workspace, initiator, _other, _membership, _system, run, decision = _seed_pending_run(
        db_session
    )
    client = _client(db_session, workspace, initiator)

    first = client.post(f"/runs/{run.id}/hitl", json={"action": "accept"})
    retry = client.post(f"/runs/{run.id}/hitl", json={"action": "accept"})

    assert first.status_code == 200
    assert retry.status_code == 200
    event = db_session.query(RunDispatchOutbox).one()
    assert event.event_type == "run_hitl_resume"
    assert (event.run_id, event.decision_id) == (run.id, decision.id)
    assert first.json()["resume_task_id"] == event.task_id
    assert retry.json()["resume_task_id"] == event.task_id
    assert db_session.query(RunDispatchOutbox).count() == 1


def test_in_process_child_and_parent_routes_share_outermost_resume_owner(
    db_session,
    monkeypatch,
):
    workspace, initiator, _other, _membership, system, child, decision = _seed_pending_run(
        db_session
    )
    parent = Run(
        id=str(uuid4()),
        workspace_id=workspace.id,
        system_id=system.id,
        parent_run_id=None,
        status="hitl_pending",
    )
    outer = Run(
        id=str(uuid4()),
        workspace_id=workspace.id,
        system_id=system.id,
        status="hitl_pending",
    )
    parent.parent_run_id = outer.id
    child.parent_run_id = parent.id
    parent.checkpoints = [
        {"kind": "hitl_pause", "node_id": "parent-subflow", "decision_id": decision.id}
    ]
    outer.checkpoints = [
        {"kind": "hitl_pause", "node_id": "outer-subflow", "decision_id": decision.id}
    ]
    db_session.add_all([outer, parent])
    db_session.commit()

    client = _client(db_session, workspace, initiator)

    child_response = client.post(f"/runs/{child.id}/hitl", json={"action": "accept"})
    parent_retry = client.post(f"/runs/{parent.id}/hitl", json={"action": "accept"})

    assert child_response.status_code == 200
    assert child_response.json()["id"] == child.id
    assert parent_retry.status_code == 200
    assert parent_retry.json()["id"] == parent.id
    assert child_response.json()["resume_task_id"] == parent_retry.json()["resume_task_id"]
    event = db_session.query(RunDispatchOutbox).one()
    assert event.event_type == "run_hitl_resume"
    assert (event.run_id, event.decision_id) == (outer.id, decision.id)
    assert event.task_id == child_response.json()["resume_task_id"]
    db_session.refresh(outer)
    dispatch_checkpoints = [
        checkpoint
        for checkpoint in outer.checkpoints or []
        if checkpoint.get("kind") == "hitl_resume_dispatch"
    ]
    assert dispatch_checkpoints == [
        {
            "kind": "hitl_resume_dispatch",
            "t": dispatch_checkpoints[0]["t"],
            "decision_id": decision.id,
            "plane": "run_celery",
        }
    ]


def test_run_hitl_celery_flag_off_keeps_inline_background_path(
    db_session,
    monkeypatch,
):
    workspace, initiator, _other, _membership, _system, run, decision = _seed_pending_run(
        db_session
    )
    from app.services.run_engine import engine

    inline_calls = []
    monkeypatch.setattr(runs, "_durable_run_hitl_enabled", lambda _system: False)
    monkeypatch.setattr(
        engine,
        "schedule_run_hitl_resume",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("Celery dispatch must stay off")
        ),
    )
    monkeypatch.setattr(
        runs,
        "_resume_wrapper",
        lambda run_id, decision_id: inline_calls.append((run_id, decision_id)),
    )

    response = _client(db_session, workspace, initiator).post(
        f"/runs/{run.id}/hitl",
        json={"action": "accept"},
    )

    assert response.status_code == 200
    assert response.json()["resume_task_id"] is None
    assert inline_calls == [(run.id, decision.id)]
    db_session.refresh(run)
    assert any(
        checkpoint.get("kind") == "hitl_resume_dispatch"
        and checkpoint.get("decision_id") == decision.id
        and checkpoint.get("plane") == "inline"
        for checkpoint in run.checkpoints or []
    )


def test_nested_in_process_descendant_under_celery_child_uses_p4_resume(
    db_session,
    monkeypatch,
):
    workspace, initiator, _other, _membership, system, leaf, decision = _seed_pending_run(
        db_session
    )
    broker_parent = Run(
        id=str(uuid4()),
        workspace_id=workspace.id,
        system_id=system.id,
        status="waiting_subflows",
    )
    outer_child = Run(
        id=str(uuid4()),
        workspace_id=workspace.id,
        system_id=system.id,
        parent_run_id=broker_parent.id,
        status="hitl_pending",
        delegation_key="b" * 64,
        delegation_node_id="broker-node",
        delegation_branch="legal",
        input_ref={
            "_delegation": {
                "parent_run_id": broker_parent.id,
                "delegation_node_id": "broker-node",
                "branch": "legal",
                "execution_plane": "celery",
            }
        },
        checkpoints=[
            {"kind": "hitl_pause", "node_id": "outer-subflow", "decision_id": decision.id}
        ],
    )
    middle = Run(
        id=str(uuid4()),
        workspace_id=workspace.id,
        system_id=system.id,
        parent_run_id=outer_child.id,
        status="hitl_pending",
        checkpoints=[
            {"kind": "hitl_pause", "node_id": "middle-subflow", "decision_id": decision.id}
        ],
    )
    leaf.parent_run_id = middle.id
    broker_parent.waiting_subflows = {
        "_meta": {
            "strategy": "all",
            "state": "waiting",
            "wave_id": 1,
            "execution_plane": "celery",
        },
        outer_child.delegation_key: {
            "child_run_id": outer_child.id,
            "node_id": outer_child.delegation_node_id,
            "branch": outer_child.delegation_branch,
            "status": "hitl_pending",
            "wave_id": 1,
        },
    }
    db_session.add_all([broker_parent, outer_child, middle])
    db_session.commit()

    response = _client(db_session, workspace, initiator).post(
        f"/runs/{leaf.id}/hitl",
        json={"action": "accept"},
    )

    assert response.status_code == 200
    assert response.json()["id"] == leaf.id
    event = db_session.query(RunDispatchOutbox).one()
    assert event.event_type == "subflow_hitl_resume"
    assert (event.run_id, event.decision_id) == (outer_child.id, decision.id)
    assert response.json()["resume_task_id"] == event.task_id
    db_session.refresh(outer_child)
    assert any(
        checkpoint.get("kind") == "hitl_resume_dispatch"
        and checkpoint.get("decision_id") == decision.id
        and checkpoint.get("plane") == "subflow_celery"
        for checkpoint in outer_child.checkpoints or []
    )


def test_delegated_hitl_queues_durable_child_resume(db_session, monkeypatch):
    workspace, initiator, _other, _membership, system, child, decision = _seed_pending_run(
        db_session
    )
    parent = Run(
        id=str(uuid4()),
        workspace_id=workspace.id,
        system_id=system.id,
        status="waiting_subflows",
    )
    node_id = "delegate-review"
    branch = "legal"
    child.parent_run_id = parent.id
    child.delegation_key = "a" * 64
    child.delegation_node_id = node_id
    child.delegation_branch = branch
    child.celery_task_id = None  # delivery metadata is not execution-plane identity
    child.input_ref = {
        "_delegation": {
            "parent_run_id": parent.id,
            "delegation_node_id": node_id,
            "branch": branch,
            "execution_plane": "celery",
        }
    }
    parent.waiting_subflows = {
        "_meta": {
            "strategy": "all",
            "state": "waiting",
            "wave_id": 1,
            "execution_plane": "celery",
        },
        child.delegation_key: {
            "child_run_id": child.id,
            "node_id": node_id,
            "branch": branch,
            "status": "hitl_pending",
            "wave_id": 1,
        },
    }
    db_session.add(parent)
    db_session.commit()
    monkeypatch.setattr(
        runs,
        "_resume_wrapper",
        lambda *_args: (_ for _ in ()).throw(AssertionError("inline resume is forbidden")),
    )

    response = _client(db_session, workspace, initiator).post(
        f"/runs/{child.id}/hitl",
        json={"action": "accept"},
    )

    assert response.status_code == 200
    event = db_session.query(RunDispatchOutbox).one()
    assert event.event_type == "subflow_hitl_resume"
    assert (event.run_id, event.decision_id) == (child.id, decision.id)
    assert response.json()["resume_task_id"] == event.task_id
    db_session.refresh(decision)
    assert decision.status == "accepted"

    idempotent_retry = _client(db_session, workspace, initiator).post(
        f"/runs/{child.id}/hitl",
        json={"action": "accept"},
    )
    assert idempotent_retry.status_code == 200
    assert idempotent_retry.json()["resume_task_id"] == event.task_id
    assert db_session.query(RunDispatchOutbox).count() == 1

    conflicting = _client(db_session, workspace, initiator).post(
        f"/runs/{child.id}/hitl",
        json={"action": "reject"},
    )
    assert conflicting.status_code == 409
    assert db_session.query(RunDispatchOutbox).count() == 1

    stale_decision = Decision(
        id=str(uuid4()),
        workspace_id=workspace.id,
        scope="run",
        target_id=child.id,
        kind="hitl_approval",
        status="proposed",
        title="Stale wave approval",
    )
    child.checkpoints = [
        {
            "kind": "hitl_pause",
            "node_id": "approve-stale",
            "decision_id": stale_decision.id,
        }
    ]
    waiting = dict(parent.waiting_subflows)
    waiting["_meta"] = {**waiting["_meta"], "wave_id": 2}
    parent.waiting_subflows = waiting
    db_session.add(stale_decision)
    db_session.commit()

    stale = _client(db_session, workspace, initiator).post(
        f"/runs/{child.id}/hitl",
        json={"action": "accept"},
    )
    assert stale.status_code == 409
    db_session.refresh(stale_decision)
    assert stale_decision.status == "proposed"
    assert db_session.query(RunDispatchOutbox).count() == 1


def test_delegated_hitl_rejects_a_first_resolution_after_its_deadline(
    db_session,
):
    workspace, initiator, _other, _membership, system, child, decision = _seed_pending_run(
        db_session
    )
    parent = Run(
        id=str(uuid4()),
        workspace_id=workspace.id,
        system_id=system.id,
        status="waiting_subflows",
    )
    deadline = datetime.utcnow() - timedelta(seconds=1)
    child.parent_run_id = parent.id
    child.delegation_key = "c" * 64
    child.delegation_node_id = "deadline-review"
    child.delegation_branch = "legal"
    child.delegation_deadline_at = deadline
    child.input_ref = {
        "_delegation": {
            "parent_run_id": parent.id,
            "delegation_node_id": child.delegation_node_id,
            "branch": child.delegation_branch,
            "execution_plane": "celery",
            "deadline_at": deadline.isoformat(),
        }
    }
    parent.waiting_subflows = {
        "_meta": {
            "strategy": "all",
            "state": "waiting",
            "wave_id": 1,
            "execution_plane": "celery",
        },
        child.delegation_key: {
            "child_run_id": child.id,
            "node_id": child.delegation_node_id,
            "branch": child.delegation_branch,
            "status": "hitl_pending",
            "deadline_at": deadline.isoformat(),
            "wave_id": 1,
        },
    }
    db_session.add(parent)
    db_session.commit()

    response = _client(db_session, workspace, initiator).post(
        f"/runs/{child.id}/hitl",
        json={"action": "accept"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Delegated HITL deadline has expired"
    db_session.refresh(decision)
    assert decision.status == "proposed"
    assert db_session.query(RunDispatchOutbox).count() == 0


def test_delegated_hitl_rolls_back_when_transition_timestamp_crosses_deadline(
    db_session,
    monkeypatch,
):
    workspace, initiator, _other, _membership, system, child, decision = _seed_pending_run(
        db_session
    )
    parent = Run(
        id=str(uuid4()),
        workspace_id=workspace.id,
        system_id=system.id,
        status="waiting_subflows",
    )
    deadline = datetime.utcnow() + timedelta(minutes=1)
    child.parent_run_id = parent.id
    child.delegation_key = "f" * 64
    child.delegation_node_id = "deadline-lock"
    child.delegation_branch = "legal"
    child.delegation_deadline_at = deadline
    child.input_ref = {
        "_delegation": {
            "parent_run_id": parent.id,
            "delegation_node_id": child.delegation_node_id,
            "branch": child.delegation_branch,
            "execution_plane": "celery",
            "deadline_at": deadline.isoformat(),
        }
    }
    parent.waiting_subflows = {
        "_meta": {
            "strategy": "all",
            "state": "waiting",
            "wave_id": 1,
            "execution_plane": "celery",
        },
        child.delegation_key: {
            "child_run_id": child.id,
            "node_id": child.delegation_node_id,
            "branch": child.delegation_branch,
            "status": "hitl_pending",
            "deadline_at": deadline.isoformat(),
            "wave_id": 1,
        },
    }
    db_session.add(parent)
    db_session.commit()

    def transition_after_deadline(db, current, *, actor, note, commit):
        assert commit is False
        current.status = "accepted"
        current.approved_by = actor
        current.approved_at = deadline + timedelta(microseconds=1)
        db.flush()
        return current

    monkeypatch.setattr(runs, "accept_decision", transition_after_deadline)
    response = _client(db_session, workspace, initiator).post(
        f"/runs/{child.id}/hitl",
        json={"action": "accept"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Delegated HITL deadline has expired"
    db_session.expire_all()
    persisted = db_session.query(Decision).filter(Decision.id == decision.id).one()
    assert persisted.status == "proposed"
    assert persisted.approved_at is None
    assert db_session.query(RunDispatchOutbox).count() == 0


def test_managed_agentic_hitl_requires_admin_even_for_run_initiator(
    db_session,
    monkeypatch,
):
    workspace, initiator, _other, membership, _system, run, decision = _seed_pending_run(
        db_session,
        managed=True,
    )
    monkeypatch.setattr(runs, "_resume_wrapper", lambda *_args: None)
    client = _client(db_session, workspace, initiator)

    forbidden = client.post(
        f"/runs/{run.id}/hitl",
        json={"action": "accept", "actor": "spoofed-admin@example.invalid"},
    )
    assert forbidden.status_code == 403
    db_session.refresh(decision)
    assert decision.status == "proposed"

    membership.role = "admin"
    membership.role_template = WORKSPACE_ADMIN
    db_session.commit()
    accepted = client.post(
        f"/runs/{run.id}/hitl",
        json={"action": "accept", "actor": "spoofed-admin@example.invalid"},
    )

    assert accepted.status_code == 200
    db_session.refresh(decision)
    assert decision.status == "accepted"
    assert decision.approved_by == initiator.email


def test_managed_hitl_admin_floor_cannot_be_widened_by_v2_enforce(
    db_session,
    monkeypatch,
    attest_authorization_v2,
):
    workspace, initiator, reviewer, _membership, _system, run, decision = _seed_pending_run(
        db_session,
        managed=True,
    )
    reviewer_membership = (
        db_session.query(WorkspaceMember)
        .filter(
            WorkspaceMember.workspace_id == workspace.id,
            WorkspaceMember.user_id == reviewer.id,
        )
        .one()
    )
    reviewer_membership.role_template = WORKSPACE_REVIEWER
    config = _set_run_approve_mode(
        db_session,
        workspace=workspace,
        user=initiator,
        mode="enforce",
    )
    attest_authorization_v2(config, ["run.approve"])
    db_session.commit()
    monkeypatch.setattr(runs, "_resume_wrapper", lambda *_args: None)

    response = _client(db_session, workspace, reviewer).post(
        f"/runs/{run.id}/hitl",
        json={"action": "accept"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Managed Run HITL requires workspace admin"
    db_session.refresh(decision)
    assert decision.status == "proposed"
    assert decision.approved_by is None
    assert db_session.query(RunDispatchOutbox).count() == 0


def test_family_drift_does_not_release_managed_hitl_or_draft(db_session, monkeypatch):
    workspace, initiator, _other, _membership, _system, run, decision = _seed_pending_run(
        db_session,
        managed=True,
    )
    drifted = dict(workspace.settings)
    drifted["family"] = "generic"
    workspace.settings = drifted
    db_session.commit()
    monkeypatch.setattr(runs, "_resume_wrapper", lambda *_args: None)
    client = _client(db_session, workspace, initiator)

    assert client.get(f"/runs/{run.id}").status_code == 404
    response = client.post(
        f"/runs/{run.id}/hitl",
        json={"action": "accept"},
    )

    assert response.status_code == 403
    db_session.refresh(decision)
    assert decision.status == "proposed"


def test_agentic_run_payload_is_private_to_initiator_admin_or_reviewer(db_session):
    workspace, initiator, other, _membership, _system, run, _decision = _seed_pending_run(
        db_session,
        managed=True,
    )
    run.trigger = "chat_agentic"
    run.status = "completed"
    run.input_ref = {"query": "private project question"}
    run.output_ref = {"answer": "private draft answer"}
    db_session.commit()

    contributor_client = _client(db_session, workspace, other)
    contributor_list = contributor_client.get("/runs")
    assert contributor_list.status_code == 200
    assert contributor_list.json()["runs"] == []
    assert contributor_client.get(f"/runs/{run.id}").status_code == 404

    owner_client = _client(db_session, workspace, initiator)
    owner_detail = owner_client.get(f"/runs/{run.id}")
    assert owner_detail.status_code == 200
    assert owner_detail.json()["input_ref"]["query"] == "private project question"

    reviewer_membership = (
        db_session.query(WorkspaceMember)
        .filter(
            WorkspaceMember.user_id == other.id,
            WorkspaceMember.workspace_id == workspace.id,
        )
        .one()
    )
    reviewer_membership.role_template = WORKSPACE_REVIEWER
    db_session.commit()
    reviewer_detail = contributor_client.get(f"/runs/{run.id}")
    assert reviewer_detail.status_code == 200
    assert reviewer_detail.json()["output_ref"]["answer"] == "private draft answer"


def test_managed_hitl_draft_is_hidden_from_initiator_and_workspace_reviewer(db_session):
    workspace, initiator, reviewer, _membership, _system, run, _decision = _seed_pending_run(
        db_session,
        managed=True,
    )
    run.trigger = "chat_agentic"
    run.input_ref = {"query": "gated question"}
    run.output_ref = {"draft": "must stay hidden before approval"}
    reviewer_membership = (
        db_session.query(WorkspaceMember)
        .filter(
            WorkspaceMember.user_id == reviewer.id,
            WorkspaceMember.workspace_id == workspace.id,
        )
        .one()
    )
    reviewer_membership.role_template = WORKSPACE_REVIEWER
    db_session.commit()

    initiator_client = _client(db_session, workspace, initiator)
    assert initiator_client.get("/runs").json()["runs"] == []
    assert initiator_client.get(f"/runs/{run.id}").status_code == 404
    assert initiator_client.get(f"/runs/{run.id}/stream").status_code == 404

    reviewer_client = _client(db_session, workspace, reviewer)
    assert reviewer_client.get(f"/runs/{run.id}").status_code == 404

    reviewer_membership.role = "admin"
    reviewer_membership.role_template = WORKSPACE_ADMIN
    db_session.commit()
    admin_detail = reviewer_client.get(f"/runs/{run.id}")
    assert admin_detail.status_code == 200
    assert admin_detail.json()["output_ref"]["draft"] == "must stay hidden before approval"


def test_managed_running_run_cannot_be_opened_or_streamed_by_initiator(db_session):
    workspace, initiator, _other, membership, _system, run, _decision = _seed_pending_run(
        db_session,
        managed=True,
    )
    run.trigger = "chat_agentic"
    run.status = "running"
    run.output_ref = {"draft": "still being generated"}
    db_session.commit()
    client = _client(db_session, workspace, initiator)

    assert client.get("/runs").json()["runs"] == []
    assert client.get(f"/runs/{run.id}").status_code == 404
    assert client.get(f"/runs/{run.id}/stream").status_code == 404

    membership.role = "admin"
    membership.role_template = WORKSPACE_ADMIN
    db_session.commit()
    assert client.get(f"/runs/{run.id}").status_code == 200


@pytest.mark.parametrize("proof", ["output", "checkpoint"])
def test_rejected_managed_run_stays_admin_only_after_completion(db_session, proof):
    workspace, initiator, _other, membership, _system, run, _decision = _seed_pending_run(
        db_session,
        managed=True,
    )
    run.trigger = "chat_agentic"
    run.status = "completed"
    run.output_ref = {
        "answer": "rejected draft must never become readable",
        **({"hitl_decision": "rejected"} if proof == "output" else {}),
    }
    run.checkpoints = (
        [{"kind": "hitl_resume", "decision_status": "rejected"}] if proof == "checkpoint" else []
    )
    db_session.commit()
    client = _client(db_session, workspace, initiator)

    assert client.get("/runs").json()["runs"] == []
    assert client.get(f"/runs/{run.id}").status_code == 404
    assert client.get(f"/runs/{run.id}/stream").status_code == 404

    membership.role = "admin"
    membership.role_template = WORKSPACE_ADMIN
    db_session.commit()
    admin_detail = client.get(f"/runs/{run.id}")
    assert admin_detail.status_code == 200
    assert "rejected draft" in admin_detail.json()["output_ref"]["answer"]


def test_global_admin_can_resolve_managed_hitl_without_membership(db_session, monkeypatch):
    workspace, _initiator, _other, _membership, _system, run, decision = _seed_pending_run(
        db_session,
        managed=True,
    )
    global_admin = _user(db_session, "organization-admin")
    global_admin.role = "admin"
    db_session.commit()
    monkeypatch.setattr(runs, "_resume_wrapper", lambda *_args: None)

    response = _client(db_session, workspace, global_admin).post(
        f"/runs/{run.id}/hitl",
        json={"action": "accept", "actor": "spoofed-admin@example.invalid"},
    )

    assert response.status_code == 200
    db_session.refresh(decision)
    assert decision.approved_by == global_admin.email


def test_non_agentic_runs_remain_workspace_visible(db_session):
    workspace, _initiator, other, _membership, _system, run, _decision = _seed_pending_run(
        db_session
    )
    run.trigger = "manual"
    db_session.commit()

    client = _client(db_session, workspace, other)
    assert [row["id"] for row in client.get("/runs").json()["runs"]] == [run.id]
    assert client.get(f"/runs/{run.id}").status_code == 200


def test_agentic_sensitive_routes_reject_non_owner_before_data_or_mutation(db_session):
    workspace, _initiator, other, _membership, _system, run, _decision = _seed_pending_run(
        db_session,
        managed=True,
    )
    run.trigger = "chat_agentic"
    run.status = "completed"
    run.input_ref = {"query": "private"}
    run.output_ref = {"answer": "private"}
    db_session.commit()
    client = _client(db_session, workspace, other)

    assert client.get(f"/runs/{run.id}/stream").status_code == 404
    assert client.post(f"/runs/{run.id}/replay", json={"overrides": {}}).status_code == 404
    assert client.get(f"/runs/{run.id}/replays").status_code == 404
    assert client.patch(f"/runs/{run.id}/outcome", json={"value": 42}).status_code == 404

    run.status = "debug_pending"
    db_session.commit()
    assert client.post(f"/runs/{run.id}/step", json={"action": "continue"}).status_code == 404
