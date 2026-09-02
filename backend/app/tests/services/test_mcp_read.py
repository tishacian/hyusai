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
    with pytest.raises(ValueError, match="not a read"):
        mcp_read.read_tool({"id": "bapi_po"}, tool="BAPI_PO_CREATE1", arguments={})
    with pytest.raises(ValueError, match="not a read"):
        mcp_read.read_tool({"id": "bapi_po"}, tool="BAPI_TRANSACTION_COMMIT", arguments={})


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


def test_approved_pr_arguments_use_pdf_filter_and_string_top():
    args = mcp_read.approved_pr_item_arguments()
    assert args["top"] == "50"
    assert isinstance(args["top"], str)
    assert "IsClosed eq false" in args["filter"]
    assert "IsClosed eq 'false'" not in args["filter"]
    assert "PurchaseRequisitionStatus eq 'X'" in args["filter"]
    assert "PurchaseRequisitionType eq 'ZNPR'" in args["filter"]
    assert args["inlinecount"] == "allpages"
    assert mcp_read.inbox_list_arguments()["top"] == 50
    assert isinstance(mcp_read.inbox_list_arguments()["top"], int)


def test_pick_read_tools_prefer_live_then_fixture():
    tool, arguments = mcp_read.pick_approved_pr_tool(
        [mcp_read.LIVE_PR_ITEM, "list_approved_prs"]
    )
    assert tool == mcp_read.LIVE_PR_ITEM
    assert arguments["top"] == "50"
    tool, arguments = mcp_read.pick_approved_pr_tool(["list_approved_prs"])
    assert tool == "list_approved_prs"
    assert arguments == {}
    tool, arguments = mcp_read.pick_budget_tool(
        [mcp_read.LIVE_BUDGET, "check_budget"], pr_id="2000276450"
    )
    assert tool == mcp_read.LIVE_BUDGET
    assert arguments == {"PurchaseRequisition": "2000276450"}
    tool, arguments = mcp_read.pick_budget_tool(["check_budget"], pr_id="PR-4402")
    assert tool == "check_budget"
    assert arguments == {"pr_id": "PR-4402"}
    tool, arguments = mcp_read.pick_po_item_tool(
        [mcp_read.LIVE_PO_ITEM, "list_pos_by_type"],
        material_group="L001",
        pr_type="IT_HARDWARE",
    )
    assert tool == mcp_read.LIVE_PO_ITEM
    assert arguments["top"] == "200"
    assert arguments["filter"] == "MaterialGroup eq 'L001'"
    tool, arguments = mcp_read.pick_po_item_tool(
        ["list_pos_by_type"], material_group="L001", pr_type="IT_HARDWARE"
    )
    assert tool == "list_pos_by_type"
    assert arguments == {"pr_type": "IT_HARDWARE"}
    tool, arguments = mcp_read.pick_recent_pos_tool(
        [mcp_read.LIVE_PO_HEADER], plant="1000"
    )
    assert tool == mcp_read.LIVE_PO_HEADER
    assert arguments["filter"] == "PurchasingOrganization eq '1000'"
    assert arguments["orderby"] == "PurchaseOrderDate desc"
    assert arguments["top"] == "20"


def test_budget_ok_from_payload_empty_pass_type_e_fail():
    assert mcp_read.budget_ok_from_payload([]) == (True, "ok")
    assert mcp_read.budget_ok_from_payload({"d": {"results": []}}) == (True, "ok")
    assert mcp_read.budget_ok_from_payload([{"Type": "W", "Message": "warn"}]) == (True, "ok")
    ok, reason = mcp_read.budget_ok_from_payload([{"Type": "E", "Message": "over"}])
    assert ok is False
    assert reason == "over"


def test_read_tool_rejects_pdf_writes_without_calling():
    with pytest.raises(ValueError, match="not a read"):
        mcp_read.read_tool({"id": "hikma"}, tool="post_A_PurchaseOrder", arguments={})
    with pytest.raises(ValueError, match="not a read"):
        mcp_read.read_tool({"id": "sap"}, tool="fi_DiscardFromPurchasing", arguments={})
    with pytest.raises(ValueError, match="not a read"):
        mcp_read.read_tool({"id": "sap"}, tool="fi_EnableForPurchasing", arguments={})


def test_compose_write_sealed_never_calls_the_tool(monkeypatch):
    from app.services.connectors.mcp import client as mcp_client

    def boom(*_args, **_kwargs):
        raise AssertionError("write tools must not be called")

    monkeypatch.setattr(mcp_client, "call_tool", boom)
    composed = mcp_read.compose_write_sealed(
        server_id="hikma",
        tool=mcp_read.LIVE_CREATE_PO,
        arguments={"requestBody": mcp_read.create_po_request_body(pr_id="2000276450")},
        sap_block=mcp_read.HIKMA_CREATE_BLOCK,
    )
    assert composed["sealed"] is True
    assert composed["called"] is False
    assert composed["result"]["called"] is False
    assert composed["result"]["arguments"]["requestBody"]["PurchaseOrderType"] == "NB"
    assert "PurchaseOrderItemCategory" in composed["result"]["arguments"]["requestBody"]["to_PurchaseOrderItem"][0]


@pytest.mark.asyncio
async def test_write_wrappers_compose_without_call_tool(monkeypatch):
    ctx = _named_ctx(monkeypatch)
    from app.services.connectors.mcp import client as mcp_client
    from app.services.connectors.mcp import service as mcp_service

    seen: list[str] = []

    def resolve(_ws, server_id):
        seen.append(server_id)
        return {
            "id": server_id,
            "url": "http://mock",
            "token": "",
            "credential_source": "workspace",
            "tool_aliases": {},
            "configured": True,
            "enabled": True,
        }

    monkeypatch.setattr(mcp_service, "resolve_server", resolve)
    monkeypatch.setattr(
        mcp_client,
        "list_tools",
        lambda server, **kwargs: {
            "tools": [
                {"name": mcp_read.LIVE_DISCARD},
                {"name": mcp_read.LIVE_CREATE_PO},
            ],
            "session_id": "s1",
        },
    )

    def boom(*_args, **_kwargs):
        raise AssertionError("named write skills must not call_tool")

    monkeypatch.setattr(mcp_client, "call_tool", boom)
    rejected = await wrappers._sap_reject_pr_v1({"pr_id": "2000276450"}, ctx)
    assert rejected["sealed"] is True
    assert rejected["called"] is False
    assert rejected["tool"] == mcp_read.LIVE_DISCARD
    assert rejected["server_id"] == "sap"
    created = await wrappers._sap_create_po_v1(
        {"pr_id": "2000276450", "supplier": "100012"},
        ctx,
    )
    assert created["sealed"] is True
    assert created["called"] is False
    assert created["tool"] == mcp_read.LIVE_CREATE_PO
    assert created["server_id"] == "hikma"
    assert created["arguments"]["requestBody"]["PurchaseOrderType"] == "NB"
    assert "NB number range" in created["sap_block"]
    handled = await wrappers._sap_handle_rejection_v1({"pr_id": "2000276450"}, ctx)
    assert handled["sealed"] is True
    assert handled["called"] is False
    assert handled["tool"] == mcp_read.LIVE_DISCARD
    # Flag off: the gate seals before it ever needs a server, so no resolve.
    assert seen == []


@pytest.mark.asyncio
async def test_znpr_create_composes_bapi_without_call_tool(monkeypatch):
    ctx = _named_ctx(monkeypatch)
    from app.services.connectors.mcp import client as mcp_client

    def boom(*_args, **_kwargs):
        raise AssertionError("named write skills must not call_tool")

    monkeypatch.setattr(mcp_client, "call_tool", boom)
    monkeypatch.setattr(mcp_client, "list_tools", boom)
    created = await wrappers._sap_create_po_v1(
        {
            "pr_id": "2000276449",
            "supplier": "1000000018",
            "pr_type": "ZNPR",
            "PurchaseRequisitionItem": "20",
            "pr": {
                "PurchaseRequisition": "2000276449",
                "PurchaseRequisitionItem": "20",
                "Plant": "1000",
                "PurReqnItemCurrency": "QAR",
                "PurchaseRequisitionPrice": "4.50",
                "DeliveryDate": "2026-07-15",
                "PurchaseRequisitionType": "ZNPR",
            },
            "proposed_po": {
                "purch_group": "013",
                "payment_terms": "ZAPS",
                "incoterms": "DDP",
            },
        },
        ctx,
    )
    assert created["sealed"] is True
    assert created["called"] is False
    assert created["testrun"] is False
    assert created["tool"] == mcp_read.LIVE_BAPI_CREATE
    assert created["server_id"] == mcp_read.BAPI_SERVER_ID
    assert "TESTRUN is banned" in created["sap_block"]
    header = created["arguments"]["import"]["POHEADER"]
    assert header["DOC_TYPE"] == "ZLPO"
    assert header["PURCH_ORG"] == "1000"
    assert header["COMP_CODE"] == "1000"
    assert header["VENDOR"] == "1000000018"
    assert header["CURRENCY"] == "QAR"
    assert header["INCOTERMS2L"] == "Doha"
    assert "DOC_DATE" not in header
    item = created["arguments"]["tables"]["POITEM"][0]
    assert item["PO_ITEM"] == "00010"
    assert item["PREQ_ITEM"] == "00020"
    assert item["PREQ_NO"] == "2000276449"
    assert "POACCOUNT" not in created["arguments"]["tables"]
    assert "TESTRUN" not in created["arguments"]


@pytest.mark.asyncio
async def test_list_and_budget_wrappers_use_live_then_fixture(monkeypatch):
    ctx = _named_ctx(monkeypatch)
    from app.services.connectors.mcp import client as mcp_client

    captured: list[dict] = []
    monkeypatch.setattr(
        mcp_client,
        "list_tools",
        lambda server, **kwargs: {
            "tools": [{"name": "list_approved_prs"}, {"name": "check_budget"}],
            "session_id": "s1",
        },
    )

    def fake_call(server, **kwargs):
        captured.append(kwargs)
        if kwargs["contract_tool"] == "list_approved_prs":
            return {
                "ok": True,
                "result": {"prs": [{"pr_id": "PR-4402", "pr_type": "IT_HARDWARE"}]},
                "server_id": "sap",
                "tool": "list_approved_prs",
                "contract_tool": "list_approved_prs",
                "credential_source": "workspace",
                "duration_ms": 2,
            }
        return {
            "ok": True,
            "result": {"pr_id": "PR-4402", "budget_ok": True, "reason": "ok"},
            "server_id": "sap",
            "tool": "check_budget",
            "contract_tool": "check_budget",
            "credential_source": "workspace",
            "duration_ms": 2,
        }

    monkeypatch.setattr(mcp_client, "call_tool", fake_call)
    listed = await wrappers._sap_list_approved_prs_v1({}, ctx)
    assert listed["prs"][0]["pr_id"] == "PR-4402"
    budget = await wrappers._sap_check_budget_v1({"pr_id": "PR-4402"}, ctx)
    assert budget["budget_ok"] is True
    assert budget["reason"] == "ok"
    assert captured[0]["contract_tool"] == "list_approved_prs"
    assert captured[1]["contract_tool"] == "check_budget"
