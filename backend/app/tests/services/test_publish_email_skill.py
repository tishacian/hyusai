from __future__ import annotations

import pytest

from app.models.user import User
from app.models.decision import Decision
from app.models.workspace import Workspace, WorkspaceMember
from app.services.run_engine.dag import execute_run_dag, resume_run_dag
from app.services.skills_registry import wrappers
from app.tests.services.test_run_engine_dag_e2e import (
    _mk_run,
    _mk_skill,
    _mk_system,
)


def _member_workspace(db_session):
    workspace = Workspace(id="ws-publish-email", slug="publish-email", name="Publish email")
    user = User(
        id="user-publish-email",
        username="publisher",
        email="member@example.test",
    )
    db_session.add_all(
        [
            workspace,
            user,
            WorkspaceMember(user_id=user.id, workspace_id=workspace.id),
        ]
    )
    db_session.commit()
    return workspace, user


async def test_publish_email_is_held_without_human_approval(db_session, monkeypatch):
    workspace, _user = _member_workspace(db_session)
    calls = []

    async def fake_send(*args):
        calls.append(args)
        return True

    monkeypatch.setattr("app.services.email.send_email", fake_send)

    result = await wrappers._publish_email_v1(
        {
            "recipients": ["member@example.test"],
            "subject": "Approved report",
            "body_text": "Ready",
        },
        {"db": db_session, "workspace_id": workspace.id, "hitl_approved": False},
    )

    assert result == {
        "status": "held",
        "sent": False,
        "recipients": ["member@example.test"],
    }
    assert calls == []


async def test_publish_email_sends_to_member_after_approval(db_session, monkeypatch):
    workspace, _user = _member_workspace(db_session)
    calls = []

    async def fake_send(to, subject, html, text):
        calls.append((to, subject, html, text))
        return True

    monkeypatch.setattr("app.services.email.send_email", fake_send)

    result = await wrappers._publish_email_v1(
        {
            "recipients": ["member@example.test"],
            "subject": "Approved report",
            "body_text": "Ready\n<script>alert(1)</script>",
        },
        {"db": db_session, "workspace_id": workspace.id, "hitl_approved": True},
    )

    assert result["status"] == "sent"
    assert calls[0][0] == "member@example.test"
    assert "<script>" not in calls[0][2]
    assert "&lt;script&gt;" in calls[0][2]


async def test_publish_email_rejects_non_member(db_session):
    workspace, _user = _member_workspace(db_session)

    with pytest.raises(ValueError, match="not a workspace member"):
        await wrappers._publish_email_v1(
            {
                "recipients": ["outside@example.test"],
                "subject": "No",
                "body_text": "No",
            },
            {"db": db_session, "workspace_id": workspace.id, "hitl_approved": True},
        )


async def test_role_agent_returns_strict_json_object(monkeypatch):
    async def fake_llm(payload, ctx):
        assert "Role: Buyer analyst" in payload["prompt"]
        assert "summary" in payload["prompt"]
        return {"completion": '```json\n{"summary":"ok","recommendation":"buy"}\n```'}

    monkeypatch.setattr(wrappers, "_workspace_llm_v1", fake_llm)

    result = await wrappers._role_agent_v1(
        {
            "role": "Buyer analyst",
            "instruction": "Assess the purchase request.",
            "body": "PR-42",
            "output_contract": {
                "type": "object",
                "required": ["summary"],
                "properties": {"summary": {"type": "string"}},
            },
        }
    )

    assert result == {"summary": "ok", "recommendation": "buy"}


async def test_publish_email_waits_for_human_gate_in_a_real_run(
    db_session, monkeypatch
):
    workspace = Workspace(id="ws-email-run", slug="email-run", name="Email run")
    user = User(id="user-email-run", username="approver", email="run@example.test")
    db_session.add_all(
        [
            workspace,
            user,
            WorkspaceMember(user_id=user.id, workspace_id=workspace.id),
        ]
    )
    db_session.commit()
    _mk_skill(db_session, "publish_email_v1")
    flow = {
        "schema_version": 2,
        "nodes": [
            {"id": "source", "kind": "source"},
            {"id": "gate", "kind": "hitl", "config": {"prompt": "Send?"}},
            {
                "id": "email",
                "kind": "task",
                "config": {"skill_slug": "publish_email_v1"},
            },
            {"id": "sink", "kind": "sink"},
        ],
        "edges": [
            {"from": "source", "to": "gate"},
            {"from": "gate", "to": "email"},
            {"from": "email", "to": "sink"},
        ],
    }
    system = _mk_system(db_session, flow=flow)
    system.workspace_id = workspace.id
    run = _mk_run(
        db_session,
        system,
        input_ref={
            "recipients": ["run@example.test"],
            "subject": "Approved report",
            "body_text": "Ready",
        },
    )
    run.workspace_id = workspace.id
    db_session.commit()
    calls = []

    async def fake_send(*args):
        calls.append(args)
        return True

    monkeypatch.setattr("app.services.email.send_email", fake_send)

    paused = await execute_run_dag(run.id)
    assert paused["status"] == "hitl_pending"
    assert calls == []

    decision = db_session.get(Decision, paused["awaiting_decision"])
    decision.status = "accepted"
    db_session.commit()
    completed = await resume_run_dag(run.id, decision_id=decision.id)

    assert completed["status"] == "completed"
    assert calls[0][0] == "run@example.test"
