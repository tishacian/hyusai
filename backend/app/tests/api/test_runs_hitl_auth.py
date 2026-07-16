"""Authorization and authenticated audit identity for Run HITL decisions."""

from __future__ import annotations

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
from app.models.decision import Decision
from app.models.run import Run
from app.models.system import System
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services.chat_execution_policy import (
    ANDRITZ_MIGRATION_MARKER,
    ANDRITZ_MIGRATION_REVISION,
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
