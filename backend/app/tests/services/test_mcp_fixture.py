"""The fixture is the MCP contract until live credentials exist. Not HANA."""

from __future__ import annotations

import threading
from contextlib import contextmanager

import pytest

from app.services.connectors.mcp import client as mcp_client
from app.services.connectors.mcp.contract import contract_gap
from app.services.connectors.mcp.errors import McpToolUnknown, McpUnreachable
from app.services.connectors.mcp.fixture import STATE, handle_jsonrpc, serve
from datetime import date

from app.services.connectors.mcp.poc import (
    build_bapi_po_payload,
    majority_supplier_format,
    override_delivery_date,
    select_next_pr,
)


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


def test_handle_jsonrpc_lists_contract_tools_without_hana():
    sap = handle_jsonrpc("sap", {"jsonrpc": "2.0", "id": "1", "method": "tools/list"})
    names = [tool["name"] for tool in sap["result"]["tools"]]
    assert names == [
        "list_approved_prs",
        "check_budget",
        "get_justification",
        "reject_pr",
        "create_po",
        "handle_rejection",
    ]
    hikma = handle_jsonrpc("hikma", {"jsonrpc": "2.0", "id": "2", "method": "tools/list"})
    assert [tool["name"] for tool in hikma["result"]["tools"]] == ["list_pos_by_type"]
    gap = contract_gap("sap", names)
    assert gap["missing"] == []
    assert gap["unexpected"] == []


def test_client_talks_http_fixture_for_both_prs():
    with _fixture_http() as base:
        sap = _server(f"{base}/sap", "sap")
        hikma = _server(f"{base}/hikma", "hikma")
        listed = mcp_client.call_tool(sap, contract_tool="list_approved_prs", arguments={})
        prs = listed["result"]["prs"]
        assert {row["pr_id"] for row in prs} == {"PR-4401", "PR-4402"}
        assert listed["server_id"] == "sap"
        assert listed["credential_source"] == "workspace"

        budget_ko = mcp_client.call_tool(
            sap, contract_tool="check_budget", arguments={"pr_id": "PR-4401"}
        )
        assert budget_ko["result"]["budget_ok"] is False
        rejected = mcp_client.call_tool(
            sap,
            contract_tool="reject_pr",
            arguments={"pr_id": "PR-4401", "reason": "budget"},
        )
        assert rejected["result"]["rejected"] is True

        budget_ok = mcp_client.call_tool(
            sap, contract_tool="check_budget", arguments={"pr_id": "PR-4402"}
        )
        assert budget_ok["result"]["budget_ok"] is True
        pos = mcp_client.call_tool(
            hikma, contract_tool="list_pos_by_type", arguments={"pr_type": "IT_HARDWARE"}
        )
        vote = majority_supplier_format({"pos": pos["result"]["pos"], "pr_id": "PR-4402"})
        assert vote["supplier"] == "ACME"
        assert vote["format"] == "XML"
        created = mcp_client.call_tool(
            sap,
            contract_tool="create_po",
            arguments={
                "pr_id": "PR-4402",
                "supplier": vote["supplier"],
                "format": vote["format"],
            },
        )
        assert created["result"]["created"] is True
        assert created["server_id"] == "sap"
        assert created["tool"] == "create_po"
        assert "hana" not in str(created).lower()


def test_unknown_tool_and_unreachable_are_named():
    with _fixture_http() as base:
        sap = _server(f"{base}/sap", "sap")
        with pytest.raises(McpToolUnknown, match="mcp_tool_unknown"):
            mcp_client.call_tool(sap, contract_tool="drop_table", arguments={})
    with pytest.raises(McpUnreachable, match="mcp_unreachable"):
        mcp_client.call_tool(
            _server("http://127.0.0.1:1/sap", "sap"),
            contract_tool="list_approved_prs",
            arguments={},
        )


def test_select_next_pr_pins_or_takes_first():
    prs = [{"pr_id": "PR-4401"}, {"pr_id": "PR-4402"}]
    assert select_next_pr({"prs": prs, "pr_id": "PR-4402"})["pr_id"] == "PR-4402"
    assert select_next_pr({"prs": prs})["pr_id"] == "PR-4401"
    assert select_next_pr({"prs": []})["empty"] is True
    item = select_next_pr(
        {
            "prs": [
                {
                    "PurchaseRequisition": "2000276450",
                    "PurchaseRequisitionItem": "20",
                    "MaterialGroup": "L001",
                }
            ]
        }
    )
    assert item["pr_id"] == "2000276450"
    assert item["PurchaseRequisitionItem"] == "20"
    assert item["MaterialGroup"] == "L001"
    assert item["Plant"] == ""
    consumed = select_next_pr(
        {
            "prs": [
                {
                    "PurchaseRequisition": "2000276581",
                    "RequestedQuantity": "1",
                    "OrderedQuantity": "1",
                },
                {
                    "PurchaseRequisition": "2000276449",
                    "RequestedQuantity": "12",
                    "OrderedQuantity": "0",
                    "Plant": "1000",
                },
            ]
        }
    )
    assert consumed["pr_id"] == "2000276449"
    assert consumed["Plant"] == "1000"


def test_bapi_payload_uses_plant_zlpo_and_overrides_past_date():
    assert override_delivery_date("2026-07-15", date(2026, 8, 22)) == "20260907"
    body = build_bapi_po_payload(
        pr_id="2000276449",
        pr_item="20",
        supplier="1000000018",
        plant="1000",
        currency="QAR",
        net_price="4.50",
        delivery_date="2026-07-15",
        today=date(2026, 8, 22),
    )
    header = body["tables"]["POHEADER"]
    assert header["DOC_TYPE"] == "ZLPO"
    assert header["PURCH_ORG"] == header["COMP_CODE"] == "1000"
    assert header["INCOTERMS2L"] == "Doha"
    assert "DOC_DATE" not in header
    assert "TESTRUN" not in body
    assert "POACCOUNT" not in body["tables"]
    assert body["tables"]["POITEM"][0]["PREQ_ITEM"] == "00020"
    assert body["tables"]["POITEM"][0]["PO_ITEM"] == "00010"
    assert body["tables"]["POSCHEDULE"][0]["DELIVERY_DATE"] == "20260907"
