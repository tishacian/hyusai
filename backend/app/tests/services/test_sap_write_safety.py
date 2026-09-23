"""Safety properties of the governed SAP write, one test per property.

An audit of the PR -> PO write path found that a payload label was enough to
make a write "attended", that a malformed flag unsealed it, that a timeout or
an unreadable reply could read as success, and that the ledger signed as the
run instead of the person. Each test below pins the corrected behaviour.
"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.models.decision import Decision
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services.connectors.mcp import client as mcp_client
from app.services.connectors.mcp import service as mcp_service
from app.services.connectors.mcp import write as mcp_write
from app.services.connectors.mcp.errors import McpUnreachable
from app.services.skills_registry import wrappers

CREATED = {
    "export": {"EXPHEADER": {"PO_NUMBER": "4500999001"}},
    "tables": {"RETURN": [{"TYPE": "S", "ID": "06", "NUMBER": "017", "MESSAGE": "created"}]},
}
COMMITTED = {"tables": {"RETURN": []}}


def _server() -> dict:
    return {"id": "bapi_po", "url": "http://mock"}


def _transport(monkeypatch, replies: dict) -> list[str]:
    """Answer each tool from ``replies``; an exception value is raised."""

    calls: list[str] = []

    def call_tool(server, *, contract_tool, arguments, timeout_s=None):
        calls.append(contract_tool)
        reply = replies.get(contract_tool, {"tables": {"RETURN": []}})
        if isinstance(reply, Exception):
            raise reply
        return {"ok": True, "result": reply, "server_id": server["id"], "tool": contract_tool}

    monkeypatch.setattr(mcp_client, "call_tool", call_tool)
    return calls


# --- the flag fails closed ---------------------------------------------------


@pytest.mark.parametrize("value", ["true", "false", "0", "off", 1, {"enabled": True}, ["x"], None])
def test_only_a_boolean_true_unseals(value):
    workspace = Workspace(
        id="w", slug="w", name="w", settings={"features": {"sap_write_unsealed": value}}
    )
    assert mcp_write.workspace_write_unsealed(workspace) is False


def test_the_boolean_true_unseals():
    workspace = Workspace(
        id="w", slug="w", name="w", settings={"features": {"sap_write_unsealed": True}}
    )
    assert mcp_write.workspace_write_unsealed(workspace) is True


# --- a write is attended by a settled Decision, not by a label ----------------


def _setup(db_session, monkeypatch):
    workspace = Workspace(
        id=str(uuid4()),
        name="Procurement",
        slug=f"procurement-{uuid4().hex[:6]}",
        settings={"features": {"mcp_connector": True, "sap_write_unsealed": True}},
    )
    db_session.add(workspace)
    db_session.commit()
    monkeypatch.setattr(mcp_service, "is_workspace_enabled", lambda _ws: True)
    monkeypatch.setattr(mcp_service, "resolve_server", lambda _ws, server_id: _server())
    events: list[dict] = []
    import app.services.audit_logger as audit_logger

    monkeypatch.setattr(audit_logger, "emit_audit_event", lambda **kwargs: events.append(kwargs))
    return workspace, events


def _decision(
    db_session,
    workspace,
    run_id,
    *,
    status="accepted",
    approved_by="buyer@example.test",
    confirmed=True,
):
    decision = Decision(
        id=str(uuid4()),
        workspace_id=workspace.id,
        scope="run",
        target_id=run_id,
        kind="hitl_approval",
        status=status,
        title="HITL approval — Approve PO",
        approved_by=approved_by,
        approved_at=datetime.utcnow(),
        human_confirmed_by="user-1" if confirmed else None,
    )
    db_session.add(decision)
    db_session.commit()
    return decision


def _write(db_session, workspace, run_id, decided_by, *, statuses=wrappers._ACCEPTED_DECISION):
    ctx = {"db": db_session, "workspace_id": workspace.id, "run_id": run_id}
    return wrappers._mcp_write(
        {"decided_by": decided_by},
        ctx,
        server_id="bapi_po",
        tool=mcp_write.BAPI_CREATE,
        arguments={"tables": {}},
        commit=True,
        **wrappers._gated_write(
            {"decided_by": decided_by}, ctx, statuses=statuses, pr_id="10000042", pr_item="00010"
        ),
    )


@pytest.mark.parametrize("label", ["buyer@example.test", "run:abc", "system", "scheduler", "None"])
def test_a_label_without_a_decision_stays_sealed(db_session, monkeypatch, label):
    workspace, events = _setup(db_session, monkeypatch)
    calls = _transport(monkeypatch, {})
    out = _write(db_session, workspace, "run-1", label)
    assert out["sealed"] is True and out["reason"] == "unattended"
    assert calls == [] and events == []


def test_a_decision_of_another_person_or_unconfirmed_stays_sealed(db_session, monkeypatch):
    workspace, _events = _setup(db_session, monkeypatch)
    calls = _transport(monkeypatch, {})
    _decision(db_session, workspace, "run-2", approved_by="someone-else@example.test")
    _decision(db_session, workspace, "run-3", confirmed=False)
    assert _write(db_session, workspace, "run-2", "buyer@example.test")["sealed"] is True
    assert _write(db_session, workspace, "run-3", "buyer@example.test")["sealed"] is True
    assert calls == []


def test_an_accepted_decision_goes_live_and_the_ledger_names_the_person(db_session, monkeypatch):
    workspace, events = _setup(db_session, monkeypatch)
    calls = _transport(
        monkeypatch, {mcp_write.BAPI_CREATE: CREATED, mcp_write.BAPI_COMMIT: COMMITTED}
    )
    decision = _decision(db_session, workspace, "run-4")
    out = _write(db_session, workspace, "run-4", "buyer@example.test")
    assert out["committed"] is True and out["po_number"] == "4500999001"
    assert calls == [mcp_write.BAPI_CREATE, mcp_write.BAPI_COMMIT]
    assert {event["actor"] for event in events} == {"buyer@example.test"}
    details = events[0]["details"]
    assert details["decision_id"] == decision.id
    assert details["pr_id"] == "10000042" and details["pr_item"] == "00010"
    assert details["run_actor"] == "run:run-4"


def test_a_rejection_write_needs_a_rejected_decision(db_session, monkeypatch):
    workspace, _events = _setup(db_session, monkeypatch)
    _transport(monkeypatch, {})
    _decision(db_session, workspace, "run-5", status="accepted")
    ctx = {"db": db_session, "workspace_id": workspace.id, "run_id": "run-5"}
    gated = wrappers._gated_write(
        {"decided_by": "buyer@example.test"},
        ctx,
        statuses=wrappers._REJECTED_DECISION,
        pr_id="1",
        pr_item="10",
    )
    assert gated["attended"] is False


# --- an unknown outcome is never a success ------------------------------------


def test_a_create_timeout_is_an_unknown_outcome_on_the_ledger(db_session, monkeypatch):
    workspace, events = _setup(db_session, monkeypatch)
    _transport(monkeypatch, {mcp_write.BAPI_CREATE: McpUnreachable("timed out")})
    _decision(db_session, workspace, "run-6")
    out = _write(db_session, workspace, "run-6", "buyer@example.test")
    assert out["sap_ok"] is False and out["committed"] is False
    assert out["outcome"] == "unknown" and out["needs_reconciliation"] is True
    assert events and events[0]["details"]["outcome"] == "unknown"
    assert events[0]["details"]["needs_reconciliation"] is True


def test_a_commit_timeout_keeps_the_po_number_it_may_have_committed(monkeypatch):
    _transport(
        monkeypatch,
        {mcp_write.BAPI_CREATE: CREATED, mcp_write.BAPI_COMMIT: McpUnreachable("timed out")},
    )
    out = mcp_write.create_and_commit_po(
        _server(), server_id="bapi_po", arguments={"tables": {}}, unsealed=True, attended=True
    )
    assert out["outcome"] == "unknown" and out["needs_reconciliation"] is True
    assert out["po_number"] == "4500999001"
    assert out["committed"] is False and out["sap_ok"] is False


@pytest.mark.parametrize(
    "reply",
    [
        "Gateway says OK",  # not a BAPI payload at all
        {"tables": {"RETURN": [{"TYPE": "A", "MESSAGE": "aborted"}]}},
        {"tables": {"RETURN": [{"TYPE": "X", "MESSAGE": "exit"}]}},
        {"tables": {"RETURN": []}},  # a create that names no PO
    ],
    ids=["text", "abort", "exit", "no-po-number"],
)
def test_an_ambiguous_create_reply_is_a_failure_and_nothing_is_committed(monkeypatch, reply):
    calls = _transport(monkeypatch, {mcp_write.BAPI_CREATE: reply})
    out = mcp_write.create_and_commit_po(
        _server(), server_id="bapi_po", arguments={"tables": {}}, unsealed=True, attended=True
    )
    assert out["sap_ok"] is False
    assert mcp_write.BAPI_COMMIT not in calls


def test_the_low_level_gate_is_unattended_unless_told_otherwise(monkeypatch):
    calls = _transport(monkeypatch, {})
    out = mcp_write.invoke_write_tool(
        _server(), server_id="bapi_po", tool=mcp_write.BAPI_COMMIT, arguments={}, unsealed=True
    )
    assert out["sealed"] is True and out["reason"] == "unattended" and calls == []


# --- the HTTP routes ------------------------------------------------------------


def _client(db_session, workspace, user):
    from app.api.v1.endpoints import mcp as mcp_endpoint
    from app.core.auth import get_current_user, get_current_workspace
    from app.db.base import get_db

    app = FastAPI()
    app.include_router(mcp_endpoint.router, prefix="/mcp")
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_current_workspace] = lambda: workspace
    app.dependency_overrides[get_db] = lambda: db_session
    return TestClient(app)


def _member(db_session, workspace, role):
    user = User(
        id=str(uuid4()),
        username=f"{role}-{uuid4().hex[:4]}",
        email=f"{role}@example.test",
        is_active=True,
    )
    db_session.add(user)
    db_session.add(WorkspaceMember(user_id=user.id, workspace_id=workspace.id, role=role))
    db_session.commit()
    return user


def test_a_member_cannot_repoint_a_server_or_write_live(db_session, monkeypatch):
    workspace, _events = _setup(db_session, monkeypatch)
    calls = _transport(
        monkeypatch, {mcp_write.BAPI_CREATE: CREATED, mcp_write.BAPI_COMMIT: COMMITTED}
    )
    member = _member(db_session, workspace, "member")
    client = _client(db_session, workspace, member)

    assert (
        client.put(
            "/mcp/servers/bapi_po",
            json={"id": "bapi_po", "url": "http://evil", "oauth_token_url": "http://evil/token"},
        ).status_code
        == 403
    )
    out = client.post(
        "/mcp/servers/bapi_po/invoke",
        json={"tool": mcp_write.BAPI_CREATE, "arguments": {"tables": {}}, "commit": True},
    ).json()
    assert out["sealed"] is True and out["reason"] == "unattended"
    assert calls == []


def test_an_admin_invoke_is_attended(db_session, monkeypatch):
    workspace, _events = _setup(db_session, monkeypatch)
    calls = _transport(
        monkeypatch, {mcp_write.BAPI_CREATE: CREATED, mcp_write.BAPI_COMMIT: COMMITTED}
    )
    admin = _member(db_session, workspace, "admin")
    out = (
        _client(db_session, workspace, admin)
        .post(
            "/mcp/servers/bapi_po/invoke",
            json={"tool": mcp_write.BAPI_CREATE, "arguments": {"tables": {}}, "commit": True},
        )
        .json()
    )
    assert out["committed"] is True
    assert calls == [mcp_write.BAPI_CREATE, mcp_write.BAPI_COMMIT]
