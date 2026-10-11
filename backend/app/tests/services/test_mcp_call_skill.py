"""Unit tests for mcp_call_v1 and the seven named MCP aliases."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.services.connectors.mcp.contract import WRITE_SKILL_SLUGS
from app.services.run_engine.agent_loop import WRITE_SKILLS
from app.services.skills_registry import wrappers


@pytest.mark.asyncio
async def test_mcp_wrappers_are_bound():
    for slug in (
        "mcp_call_v1",
        "sap_list_approved_prs_v1",
        "sap_check_budget_v1",
        "sap_get_justification_v1",
        "sap_reject_pr_v1",
        "hikma_list_pos_by_type_v1",
        "sap_create_po_v1",
        "sap_handle_rejection_v1",
    ):
        assert wrappers.runtime_status(slug) == "bound"


def test_write_skills_are_only_the_three_named_writes():
    assert WRITE_SKILL_SLUGS == {
        "sap_reject_pr_v1",
        "sap_create_po_v1",
        "sap_handle_rejection_v1",
    }
    assert WRITE_SKILL_SLUGS <= WRITE_SKILLS
    assert "mcp_call_v1" not in WRITE_SKILLS
    assert "sap_list_approved_prs_v1" not in WRITE_SKILLS
    assert "sap_hana_query_v1" not in WRITE_SKILL_SLUGS


@pytest.mark.asyncio
async def test_named_skills_reject_free_tool_sql_and_server_id(monkeypatch):
    workspace = SimpleNamespace(
        id="ws-1",
        slug="nawa",
        settings={"features": {"mcp_connector": True}},
    )
    db = MagicMock()
    monkeypatch.setattr(
        wrappers,
        "_calendar_db_and_workspace",
        lambda payload, ctx=None: (db, workspace),
    )
    with pytest.raises(ValueError, match="named MCP skills"):
        await wrappers._sap_list_approved_prs_v1(
            {"tool": "list_approved_prs"},
            {"db": db, "workspace_id": "ws-1"},
        )
    with pytest.raises(ValueError, match="named MCP skills"):
        await wrappers._sap_check_budget_v1(
            {"pr_id": "PR-1", "sql": "SELECT 1"},
            {"db": db, "workspace_id": "ws-1"},
        )
    with pytest.raises(ValueError, match="named MCP skills"):
        await wrappers._sap_create_po_v1(
            {"pr_id": "PR-1", "server_id": "hana"},
            {"db": db, "workspace_id": "ws-1"},
        )


@pytest.mark.asyncio
async def test_side_effect_payload_is_rejected(monkeypatch):
    workspace = SimpleNamespace(id="ws-1", slug="nawa", settings={})
    db = MagicMock()
    monkeypatch.setattr(
        wrappers,
        "_calendar_db_and_workspace",
        lambda payload, ctx=None: (db, workspace),
    )
    with pytest.raises(ValueError, match="_side_effect"):
        await wrappers._mcp_call_v1(
            {"server_id": "sap", "tool": "reject_pr", "_side_effect": "write"},
            {"db": db, "workspace_id": "ws-1"},
        )
    with pytest.raises(ValueError, match="named MCP skills"):
        await wrappers._sap_reject_pr_v1(
            {"pr_id": "PR-1", "_side_effect": "write"},
            {"db": db, "workspace_id": "ws-1"},
        )


@pytest.mark.asyncio
async def test_unconfigured_workspace_fails_closed(monkeypatch):
    workspace = SimpleNamespace(
        id="ws-1",
        slug="nawa",
        settings={"features": {"mcp_connector": False}},
    )
    db = MagicMock()
    monkeypatch.setattr(
        wrappers,
        "_calendar_db_and_workspace",
        lambda payload, ctx=None: (db, workspace),
    )
    from app.services.connectors.mcp import service as mcp_service

    monkeypatch.setattr(mcp_service, "is_workspace_enabled", lambda _ws: False)
    with pytest.raises(ValueError, match="mcp_unconfigured"):
        await wrappers._mcp_call_v1(
            {"server_id": "sap", "tool": "list_approved_prs"},
            {"db": db, "workspace_id": "ws-1"},
        )


def _enabled_workspace(**features) -> SimpleNamespace:
    return SimpleNamespace(
        id="ws-1",
        slug="nawa",
        settings={"features": {"mcp_connector": True, **features}},
    )


@pytest.mark.asyncio
async def test_free_write_tool_rides_the_gate_not_the_transport(monkeypatch):
    """H0: ``mcp_call_v1`` cannot bypass the write allow-list or the flag."""
    workspace = _enabled_workspace()
    db = MagicMock()
    monkeypatch.setattr(
        wrappers, "_calendar_db_and_workspace", lambda payload, ctx=None: (db, workspace)
    )
    from app.services.connectors.mcp import client as mcp_client
    from app.services.connectors.mcp import service as mcp_service

    monkeypatch.setattr(mcp_service, "is_workspace_enabled", lambda _ws: True)

    def boom(*_args, **_kwargs):
        raise AssertionError("a write must not reach the transport with the flag off")

    monkeypatch.setattr(mcp_client, "call_tool", boom)
    sealed = await wrappers._mcp_call_v1(
        {"server_id": "bapi_po", "tool": "BAPI_TRANSACTION_COMMIT", "arguments": {"import": {"WAIT": "X"}}},
        {"db": db, "workspace_id": "ws-1"},
    )
    assert sealed["sealed"] is True
    assert sealed["called"] is False
    # Off the allow-list: refused before any flag or socket question.
    with pytest.raises(ValueError, match="allow-list"):
        await wrappers._mcp_call_v1(
            {"server_id": "bapi_po", "tool": "BAPI_PO_CHANGE", "arguments": {}},
            {"db": db, "workspace_id": "ws-1"},
        )
    with pytest.raises(ValueError, match="TESTRUN"):
        await wrappers._mcp_call_v1(
            {"server_id": "bapi_po", "tool": "BAPI_PO_CREATE1", "arguments": {"import": {"TESTRUN": "X"}}},
            {"db": db, "workspace_id": "ws-1"},
        )


@pytest.mark.asyncio
async def test_free_write_tool_stays_sealed_even_with_the_flag_on(monkeypatch):
    """No approval gate stands behind a free ``mcp_call_v1``: it never goes live."""
    workspace = _enabled_workspace(sap_write_unsealed=True)
    db = MagicMock()
    monkeypatch.setattr(
        wrappers, "_calendar_db_and_workspace", lambda payload, ctx=None: (db, workspace)
    )
    from app.services.connectors.mcp import client as mcp_client
    from app.services.connectors.mcp import service as mcp_service
    import app.services.audit_logger as audit_logger

    monkeypatch.setattr(mcp_service, "is_workspace_enabled", lambda _ws: True)
    monkeypatch.setattr(
        mcp_service, "resolve_server", lambda _ws, server_id: {"id": server_id, "url": "http://mock"}
    )
    def _no_socket(server, **kwargs):
        raise AssertionError("a free write must not reach SAP")

    monkeypatch.setattr(mcp_client, "call_tool", _no_socket)
    events: list[dict] = []
    monkeypatch.setattr(audit_logger, "emit_audit_event", lambda **kwargs: events.append(kwargs))
    out = await wrappers._mcp_call_v1(
        {"server_id": "bapi_po", "tool": "BAPI_TRANSACTION_COMMIT", "arguments": {"import": {"WAIT": "X"}}},
        {"db": db, "workspace_id": "ws-1", "run_id": "run-9"},
    )
    assert out["called"] is False
    assert out["sealed"] is True
    assert out["reason"] == "unattended"
    assert events == []  # nothing left the platform, so nothing to ledger


def _unsealed_transport(monkeypatch) -> list[str]:
    """Flag on, server resolvable, transport recording every tool it is asked."""
    from app.services.connectors.mcp import client as mcp_client
    from app.services.connectors.mcp import service as mcp_service

    called: list[str] = []
    monkeypatch.setattr(mcp_service, "is_workspace_enabled", lambda _ws: True)
    monkeypatch.setattr(
        mcp_service, "resolve_server", lambda _ws, server_id: {"id": server_id, "url": "http://mock"}
    )

    def fake_call(server, **kwargs):
        called.append(kwargs["contract_tool"])
        return {
            "ok": True,
            "result": {"tables": {"RETURN": []}, "export": {"EXPHEADER": {"PO_NUMBER": "4500382599"}}},
            "server_id": server["id"],
            "tool": kwargs["contract_tool"],
            "contract_tool": kwargs["contract_tool"],
            "credential_source": "workspace",
            "duration_ms": 3,
        }

    monkeypatch.setattr(mcp_client, "call_tool", fake_call)
    return called


_ZNPR_CREATE = {
    "pr_id": "2000276449",
    "supplier": "1000000018",
    "pr_type": "ZNPR",
    "pr": {
        "PurchaseRequisition": "2000276449",
        "PurchaseRequisitionItem": "10",
        "Plant": "1000",
        "PurReqnItemCurrency": "QAR",
        "PurchaseRequisitionPrice": "4.50",
        "PurchaseRequisitionType": "ZNPR",
    },
    "proposed_po": {"purch_group": "013", "payment_terms": "ZAPS", "incoterms": "DDP"},
}


@pytest.mark.asyncio
async def test_dag_writes_leave_only_when_a_person_decided(monkeypatch, db_session):
    """Flag on: the person who settled the run's gate unseals create and discard;
    a TTL expiry (``system:gate_ttl``) or a snapshot without ``decided_by``
    composes the same envelope, sealed. The budget branch is never attended.

    Real rows, not a mock session: attendance is a settled Decision of the run
    and a create claims a PR-item intent, and a mock answers every query."""
    from datetime import datetime

    from app.models.decision import Decision
    from app.models.workspace import Workspace

    workspace = Workspace(
        id="ws-1",
        slug="nawa-dag",
        name="NAWA",
        settings={"features": {"mcp_connector": True, "sap_write_unsealed": True}},
    )
    db_session.add(workspace)
    for decision_id, status in (("dec-accept", "accepted"), ("dec-reject", "rejected")):
        db_session.add(
            Decision(
                id=decision_id,
                workspace_id="ws-1",
                scope="run",
                target_id="run-1" if status == "accepted" else "run-2",
                kind="hitl_approval",
                status=status,
                title="HITL approval",
                approved_by="buyer@nawa.test",
                approved_at=datetime.utcnow(),
                human_confirmed_by="user-buyer",
            )
        )
    db_session.commit()
    called = _unsealed_transport(monkeypatch)
    ctx = {"db": db_session, "workspace_id": "ws-1", "run_id": "run-1"}

    human = await wrappers._sap_create_po_v1({**_ZNPR_CREATE, "decided_by": "buyer@nawa.test"}, ctx)
    assert human["called"] is True
    assert human["committed"] is True
    assert human["po_number"] == "4500382599"
    assert called == ["BAPI_PO_CREATE1", "BAPI_TRANSACTION_COMMIT"]

    called.clear()
    for decided_by in ("system:gate_ttl", None):
        payload = dict(_ZNPR_CREATE)
        if decided_by is not None:
            payload["decided_by"] = decided_by
        expired = await wrappers._sap_create_po_v1(payload, ctx)
        assert expired["sealed"] is True, decided_by
        assert expired["called"] is False
        assert expired["reason"] == "unattended"
        assert expired["arguments"]["import"]["POHEADER"]["DOC_TYPE"] == "ZLPO"
    assert called == []

    reject_ctx = {**ctx, "run_id": "run-2"}
    rejected = await wrappers._sap_handle_rejection_v1(
        {"pr_id": "2000276449", "decided_by": "buyer@nawa.test"}, reject_ctx
    )
    assert rejected["called"] is True
    assert called == ["fi_DiscardFromPurchasing"]
    called.clear()
    expired_reject = await wrappers._sap_handle_rejection_v1(
        {"pr_id": "2000276449", "decided_by": "system:gate_ttl"}, reject_ctx
    )
    assert expired_reject["sealed"] is True
    assert expired_reject["reason"] == "unattended"
    budget = await wrappers._sap_reject_pr_v1(
        {"pr_id": "2000276449", "reason": "over budget", "decided_by": "buyer@nawa.test"}, ctx
    )
    assert budget["sealed"] is True
    assert budget["reason"] == "unattended"
    assert budget["tool"] == "fi_DiscardFromPurchasing"
    assert called == []


@pytest.mark.asyncio
async def test_named_skills_ignore_the_upstream_trace_in_overlay_mode(monkeypatch):
    """The walker merges the previous MCP node output into the payload: its
    ``tool``/``server_id`` are provenance, not a free-tool override."""
    workspace = _enabled_workspace()
    db = MagicMock()
    monkeypatch.setattr(
        wrappers, "_calendar_db_and_workspace", lambda payload, ctx=None: (db, workspace)
    )
    from app.services.connectors.mcp import client as mcp_client
    from app.services.connectors.mcp import service as mcp_service

    monkeypatch.setattr(mcp_service, "is_workspace_enabled", lambda _ws: True)
    monkeypatch.setattr(
        mcp_service, "resolve_server", lambda _ws, server_id: {"id": server_id, "url": "http://mock"}
    )
    monkeypatch.setattr(
        mcp_client, "list_tools", lambda server, **kwargs: {"tools": [{"name": "get_justification"}]}
    )
    monkeypatch.setattr(
        mcp_client,
        "call_tool",
        lambda server, **kwargs: {
            "ok": True,
            "result": {"justification": "Finance laptops are past refresh."},
            "server_id": "sap",
            "tool": "get_justification",
            "contract_tool": "get_justification",
            "credential_source": "workspace",
            "duration_ms": 3,
        },
    )
    upstream_budget_trace = {
        "pr_id": "2000276559",
        "budget_ok": True,
        "ok": True,
        "server_id": "sap",
        "tool": "fi_Validate",
        "contract_tool": "fi_Validate",
        "credential_source": "workspace",
        "duration_ms": 763,
    }
    out = await wrappers._sap_get_justification_v1(
        upstream_budget_trace, {"db": db, "workspace_id": "ws-1"}
    )
    assert out["justification"] == "Finance laptops are past refresh."
    # A bare free ``tool`` (no trace signature) is still refused.
    with pytest.raises(ValueError, match="named MCP skills"):
        await wrappers._sap_get_justification_v1(
            {"pr_id": "1", "tool": "delete_everything"}, {"db": db, "workspace_id": "ws-1"}
        )


@pytest.mark.asyncio
async def test_named_skill_flattens_trace(monkeypatch):
    workspace = SimpleNamespace(
        id="ws-1",
        slug="nawa",
        settings={"features": {"mcp_connector": True}},
    )
    db = MagicMock()
    monkeypatch.setattr(
        wrappers,
        "_calendar_db_and_workspace",
        lambda payload, ctx=None: (db, workspace),
    )
    from app.services.connectors.mcp import client as mcp_client
    from app.services.connectors.mcp import service as mcp_service

    monkeypatch.setattr(mcp_service, "is_workspace_enabled", lambda _ws: True)
    monkeypatch.setattr(
        mcp_service,
        "resolve_server",
        lambda _ws, server_id: {
            "id": server_id,
            "url": "http://mock",
            "token": "",
            "credential_source": "workspace",
            "tool_aliases": {},
            "configured": True,
            "enabled": True,
        },
    )
    captured: dict = {}

    monkeypatch.setattr(
        mcp_client,
        "list_tools",
        lambda server, **kwargs: {"tools": [{"name": "list_approved_prs"}], "session_id": "s1"},
    )

    def fake_call(server, **kwargs):
        captured["server"] = server
        captured["kwargs"] = kwargs
        return {
            "ok": True,
            "result": {"prs": [{"pr_id": "PR-4402"}], "count": 1},
            "server_id": "sap",
            "tool": "list_approved_prs",
            "contract_tool": "list_approved_prs",
            "credential_source": "workspace",
            "duration_ms": 4,
        }

    monkeypatch.setattr(mcp_client, "call_tool", fake_call)
    result = await wrappers._sap_list_approved_prs_v1({}, {"db": db, "workspace_id": "ws-1"})
    assert result["prs"][0]["pr_id"] == "PR-4402"
    assert result["server_id"] == "sap"
    assert result["tool"] == "list_approved_prs"
    assert result["contract_tool"] == "list_approved_prs"
    assert result["credential_source"] == "workspace"
    assert captured["kwargs"]["contract_tool"] == "list_approved_prs"
    assert captured["server"]["id"] == "sap"
