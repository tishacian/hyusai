"""Keyed MCP read: write tools never run; justification advertise-then-call."""

from __future__ import annotations

import threading
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.services.connectors.mcp import preview as mcp_preview
from app.services.connectors.mcp import read as mcp_read
from app.services.connectors.mcp.errors import McpToolUnknown
from app.services.connectors.mcp.fixture import STATE, serve
from app.services.skills_registry import wrappers


@contextmanager
def _fixture_http():
    STATE.reset()
    httpd = serve("127.0.0.1", 0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    host, port = httpd.server_address[:2]
    try:
        yield f"http://{host}:{port}"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=2)
        STATE.reset()


def _server(url: str, server_id: str) -> dict:
    return {
        "id": server_id,
        "url": url,
        "token": "",
        "tool_aliases": {},
        "credential_source": "workspace",
    }


def test_preview_still_skips_item_by_key():
    assert not mcp_preview.is_preview_safe(
        {
            "name": mcp_read.LIVE_PR_ITEM_BY_KEY,
            "input_schema": {
                "type": "object",
                "properties": {
                    "PurchaseRequisition": {},
                    "PurchaseRequisitionItem": {},
                    "expand": {},
                },
            },
        }
    )


def test_pick_justification_prefers_live_item_by_key():
    tool, arguments = mcp_read.pick_justification_tool(
        ["get_justification", mcp_read.LIVE_PR_ITEM_BY_KEY],
        pr_id="2000276450",
    )
    assert tool == mcp_read.LIVE_PR_ITEM_BY_KEY
    assert arguments == {
        "PurchaseRequisition": "2000276450",
        "PurchaseRequisitionItem": "10",
        "expand": "to_PurchaseReqnItemText",
    }


def test_pick_justification_uses_payload_item():
    _tool, arguments = mcp_read.pick_justification_tool(
        [mcp_read.LIVE_PR_ITEM_BY_KEY],
        pr_id="2000276450",
        item="20",
    )
    assert arguments["PurchaseRequisitionItem"] == "20"


def test_pick_justification_falls_back_to_fixture():
    tool, arguments = mcp_read.pick_justification_tool(
        ["get_justification", "list_approved_prs"],
        pr_id="PR-4402",
    )
    assert tool == "get_justification"
    assert arguments == {"pr_id": "PR-4402"}


def test_pick_justification_fails_closed_when_unknown():
    with pytest.raises(McpToolUnknown, match="mcp_tool_unknown"):
        mcp_read.pick_justification_tool(["list_approved_prs"], pr_id="PR-4402")


def test_extract_justification_from_item_text_and_fixture():
    assert (
        mcp_read.extract_justification_text({"justification": "Finance laptops are past refresh."})
        == "Finance laptops are past refresh."
    )
    odata = {
        "status": 200,
        "data": {
            "PurchaseRequisition": "2000276450",
            "to_PurchaseReqnItemText": {
                "results": [
                    {"TextObjectType": "B01", "Note": "Need 40 warehouse scanners."},
                ]
            },
        },
    }
    assert mcp_read.extract_justification_text(odata) == "Need 40 warehouse scanners."
    sap = {
        "d": {
            "to_PurchaseReqnItemText": {
                "results": [{"PlainLongText": "Replace failing handhelds."}],
            }
        }
    }
    assert mcp_read.extract_justification_text(sap) == "Replace failing handhelds."
    hikma = {
        "status": 200,
        "data": {
            "PurchaseRequisition": "2000276450",
            "PurchaseRequisitionItem": "10",
            "PurchaseRequisitionItemText": " LORX  FURNITURE CLEANER  - 650 ML - GRE",
            "to_PurchaseReqnItemText": {
                "results": [
                    {
                        "DocumentText": "B01",
                        "NoteDescription": " LORX  FURNITURE CLEANER  - 650 ML - GREEN",
                    }
                ]
            },
        },
    }
    assert (
        mcp_read.extract_justification_text(hikma)
        == "LORX  FURNITURE CLEANER  - 650 ML - GREEN"
    )


def test_read_tool_rejects_writes_without_calling():
    with pytest.raises(ValueError, match="not a read"):
        mcp_read.read_tool({"id": "sap"}, tool="create_po", arguments={"pr_id": "1"})
    with pytest.raises(ValueError, match="not a read"):
        mcp_read.read_tool({"id": "sap"}, tool="reject_pr", arguments={"pr_id": "1"})
    with pytest.raises(ValueError, match="not a read"):
        mcp_read.read_tool({"id": "sap"}, tool="post_A_PurchaseOrder", arguments={})
    with pytest.raises(ValueError, match="not a read"):
        mcp_read.read_tool({"id": "sap"}, tool="handle_rejection", arguments={})


def test_read_tool_accepts_fixture_justification():
    with _fixture_http() as base:
        sap = _server(f"{base}/sap", "sap")
        out = mcp_read.read_tool(
            sap,
            tool="get_justification",
            arguments={"pr_id": "PR-4402"},
        )
        assert out["ok"] is True
        assert out["kind"] == "read"
        assert out["tool"] == "get_justification"
        assert "laptops" in out["text"].lower()
        assert out["result"]["pr_id"] == "PR-4402"


def test_read_tool_unknown_live_name_on_fixture():
    with _fixture_http() as base:
        sap = _server(f"{base}/sap", "sap")
        with pytest.raises(McpToolUnknown, match="mcp_tool_unknown"):
            mcp_read.read_tool(
                sap,
                tool=mcp_read.LIVE_PR_ITEM_BY_KEY,
                arguments=mcp_read.live_justification_arguments("2000276450"),
            )


def test_call_justification_uses_fixture_when_live_absent():
    with _fixture_http() as base:
        sap = _server(f"{base}/sap", "sap")
        out = mcp_read.call_justification(sap, pr_id="PR-4402")
        assert out["tool"] == "get_justification"
        assert out["contract_tool"] == "get_justification"
        assert "laptops" in out["result"]["justification"].lower()
        assert out["result"]["pr_id"] == "PR-4402"


def test_call_justification_fails_closed_on_hikma():
    with _fixture_http() as base:
        hikma = _server(f"{base}/hikma", "hikma")
        with pytest.raises(McpToolUnknown, match="mcp_tool_unknown"):
            mcp_read.call_justification(hikma, pr_id="PR-4402")


def _named_ctx(monkeypatch):
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
    return {"db": db, "workspace_id": "ws-1"}


@pytest.mark.asyncio
async def test_wrapper_calls_live_item_by_key_when_advertised(monkeypatch):
    ctx = _named_ctx(monkeypatch)
    from app.services.connectors.mcp import client as mcp_client

    captured: list[dict] = []

    monkeypatch.setattr(
        mcp_client,
        "list_tools",
        lambda server, **kwargs: {
            "tools": [
                {"name": mcp_read.LIVE_PR_ITEM_BY_KEY},
                {"name": "get_justification"},
            ],
            "session_id": "s1",
        },
    )

    def fake_call(server, **kwargs):
        captured.append(kwargs)
        return {
            "ok": True,
            "result": {
                "to_PurchaseReqnItemText": {
                    "results": [{"Note": "Need 40 warehouse scanners."}],
                }
            },
            "server_id": "sap",
            "tool": kwargs["contract_tool"],
            "contract_tool": kwargs["contract_tool"],
            "credential_source": "workspace",
            "duration_ms": 9,
        }

    monkeypatch.setattr(mcp_client, "call_tool", fake_call)
    result = await wrappers._sap_get_justification_v1(
        {"pr_id": "2000276450"},
        ctx,
    )
    assert captured[-1]["contract_tool"] == mcp_read.LIVE_PR_ITEM_BY_KEY
    assert captured[-1]["arguments"] == {
        "PurchaseRequisition": "2000276450",
        "PurchaseRequisitionItem": "10",
        "expand": "to_PurchaseReqnItemText",
    }
    assert result["justification"] == "Need 40 warehouse scanners."
    assert result["pr_id"] == "2000276450"
    assert result["tool"] == mcp_read.LIVE_PR_ITEM_BY_KEY
    assert result["server_id"] == "sap"


@pytest.mark.asyncio
async def test_wrapper_keeps_fixture_get_justification(monkeypatch):
    ctx = _named_ctx(monkeypatch)
    from app.services.connectors.mcp import client as mcp_client

    captured: list[dict] = []
    monkeypatch.setattr(
        mcp_client,
        "list_tools",
        lambda server, **kwargs: {"tools": [{"name": "get_justification"}], "session_id": "s1"},
    )

    def fake_call(server, **kwargs):
        captured.append(kwargs)
        return {
            "ok": True,
            "result": {
                "pr_id": "PR-4402",
                "justification": "Finance laptops are past refresh.",
            },
            "server_id": "sap",
            "tool": "get_justification",
            "contract_tool": "get_justification",
            "credential_source": "workspace",
            "duration_ms": 3,
        }

    monkeypatch.setattr(mcp_client, "call_tool", fake_call)
    result = await wrappers._sap_get_justification_v1({"pr_id": "PR-4402"}, ctx)
    assert captured[-1]["contract_tool"] == "get_justification"
    assert captured[-1]["arguments"] == {"pr_id": "PR-4402"}
    assert result["justification"] == "Finance laptops are past refresh."


@pytest.mark.asyncio
async def test_wrapper_unknown_tools_fail_closed(monkeypatch):
    ctx = _named_ctx(monkeypatch)
    from app.services.connectors.mcp import client as mcp_client

    monkeypatch.setattr(
        mcp_client,
        "list_tools",
        lambda server, **kwargs: {"tools": [{"name": "list_approved_prs"}], "session_id": "s1"},
    )
    with pytest.raises(McpToolUnknown, match="mcp_tool_unknown"):
        await wrappers._sap_get_justification_v1({"pr_id": "PR-4402"}, ctx)
