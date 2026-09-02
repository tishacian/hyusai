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
async def test_free_write_tool_unsealed_is_audited_with_the_run(monkeypatch):
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
    monkeypatch.setattr(
        mcp_client,
        "call_tool",
        lambda server, **kwargs: {
            "ok": True,
            "result": {"tables": {"RETURN": []}},
            "server_id": server["id"],
            "tool": kwargs["contract_tool"],
            "contract_tool": kwargs["contract_tool"],
            "credential_source": "workspace",
            "duration_ms": 3,
        },
    )
    events: list[dict] = []
    monkeypatch.setattr(audit_logger, "emit_audit_event", lambda **kwargs: events.append(kwargs))
    out = await wrappers._mcp_call_v1(
        {"server_id": "bapi_po", "tool": "BAPI_TRANSACTION_COMMIT", "arguments": {"import": {"WAIT": "X"}}},
        {"db": db, "workspace_id": "ws-1", "run_id": "run-9"},
    )
    assert out["called"] is True
    assert out["sap_ok"] is True
    assert events[0]["actor"] == "run:run-9"
    assert events[0]["details"]["run_id"] == "run-9"


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
