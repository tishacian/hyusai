"""Read-only MCP preview: fixture lists, write tools never run."""

from __future__ import annotations

import threading
from contextlib import contextmanager

import pytest

from app.services.connectors.mcp import preview as mcp_preview
from app.services.connectors.mcp.errors import McpPreviewUnavailable
from app.services.connectors.mcp.fixture import STATE, serve


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


def test_classify_kind_uses_live_names_not_pdf_aliases():
    assert mcp_preview.classify_kind("get_A_PurchaseRequisitionHeader") == "read"
    assert mcp_preview.classify_kind("list_approved_prs") == "read"
    assert mcp_preview.classify_kind("getTaskCollection") == "read"
    assert mcp_preview.classify_kind("listCommentCollection") == "read"
    assert mcp_preview.classify_kind("post_A_PurchaseOrder") == "write"
    assert mcp_preview.classify_kind("create_po") == "write"
    assert mcp_preview.classify_kind("reject_pr") == "write"
    assert mcp_preview.classify_kind("handle_rejection") == "write"
    assert mcp_preview.classify_kind("fi_Validate") == "read"
    assert mcp_preview.classify_kind("check_budget") == "read"
    assert mcp_preview.classify_kind("fi_DiscardFromPurchasing") == "write"
    assert mcp_preview.classify_kind("fi_EnableForPurchasing") == "write"
    assert mcp_preview.classify_kind("BAPI_PO_CREATE1") == "write"
    assert mcp_preview.classify_kind("BAPI_TRANSACTION_COMMIT") == "write"
    assert mcp_preview.classify_kind("BAPI_TRANSACTION_ROLLBACK") == "write"
    assert not mcp_preview.is_preview_safe({"name": "searchUsersWorkflowTask", "input_schema": {}})
    assert mcp_preview.pick_preview_tool(
        [
            {"name": "listCommentCollection", "input_schema": {}},
            {"name": "getTaskCollection", "input_schema": {"properties": {"top": {"type": "string"}}}},
            {"name": "searchUsersWorkflowTask", "input_schema": {}},
        ]
    )["name"] == "getTaskCollection"


def test_gateway_refusal_is_not_a_live_table():
    assert mcp_preview.gateway_refusal(
        {
            "status": 403,
            "error": True,
            "message": "No service found for namespace '', name 'API_MATERIAL_DOCUMENT_SRV'",
            "data": {"error": {"code": "/IWFND/MED/170"}},
        }
    )


def test_preview_safe_rejects_required_keys_and_writes():
    assert mcp_preview.is_preview_safe(
        {"name": "list_approved_prs", "input_schema": {"type": "object"}}
    )
    assert mcp_preview.is_preview_safe(
        {
            "name": "get_A_PurchaseRequisitionHeader",
            "input_schema": {
                "type": "object",
                "properties": {"$top": {"type": "integer"}},
            },
        }
    )
    assert not mcp_preview.is_preview_safe(
        {
            "name": "get_A_PurchaseRequisitionHeader",
            "input_schema": {
                "type": "object",
                "required": ["PurchaseRequisition"],
            },
        }
    )
    assert not mcp_preview.is_preview_safe(
        {"name": "post_A_PurchaseOrder", "input_schema": {}}
    )
    assert not mcp_preview.is_preview_safe(
        {
            "name": "get_A_PurchaseRequisitionHeader_by_key",
            "input_schema": {"type": "object", "properties": {"PurchaseRequisition": {}}},
        }
    )
    assert mcp_preview.preview_arguments(
        {
            "name": "get_A_PurchaseRequisitionHeader",
            "input_schema": {
                "type": "object",
                "properties": {"top": {"type": "string"}},
            },
        }
    ) == {"top": "8"}


def test_flatten_unwraps_fixture_and_odata_shapes():
    table = mcp_preview.flatten_preview({"prs": [{"pr_id": "PR-1", "title": "Scanners"}]})
    assert table["columns"] == ["pr_id", "title"]
    assert table["rows"][0] == ["PR-1", "Scanners"]
    odata = mcp_preview.flatten_preview({"value": [{"PurchaseRequisition": "1001"}]})
    assert odata["rows"][0][0] == "1001"
    sap = mcp_preview.flatten_preview(
        {
            "status": 200,
            "data": {
                "results": [
                    {
                        "__metadata": {"type": "A_PurchaseRequisitionHeaderType"},
                        "PurchaseRequisition": "1000000000",
                        "PurReqnDescription": "Scanners",
                    }
                ]
            },
        }
    )
    assert sap["columns"] == ["PurchaseRequisition", "PurReqnDescription"]
    assert sap["rows"][0] == ["1000000000", "Scanners"]
    wide_po = mcp_preview.flatten_preview(
        {
            "status": 200,
            "data": {
                "results": [
                    {
                        "PurchaseOrder": "4200000000",
                        "PurchaseOrderType": "ZAPO",
                        "CompanyCode": "4510",
                        "PurchasingDocumentDeletionCode": "",
                        "PurchasingProcessingStatus": "02",
                        "CreatedByUser": "DEMO",
                        "CreationDate": "2026-01-01",
                        "LastChangeDateTime": "2026-01-02",
                        "Supplier": "100012",
                        "PurchasingOrganization": "4510",
                    }
                ]
            },
        }
    )
    assert "Supplier" in wide_po["columns"]
    assert wide_po["rows"][0][wide_po["columns"].index("Supplier")] == "100012"


def test_fixture_preview_lists_prs_and_never_calls_write():
    with _fixture_http() as base:
        sap = _server(f"{base}/sap", "sap")
        hikma = _server(f"{base}/hikma", "hikma")
        listed = mcp_preview.preview_server(sap)
        assert listed["ok"] is True
        assert listed["tool"] == "list_approved_prs"
        assert listed["kind"] == "read"
        pr_idx = listed["columns"].index("pr_id")
        assert "PR-4401" in {row[pr_idx] for row in listed["rows"]}
        with STATE._lock:
            assert STATE.rejected == []
            assert STATE.pos == []

        pos = mcp_preview.preview_server(hikma)
        assert pos["tool"] == "list_pos_by_type"
        assert pos["row_count"] >= 1

        with pytest.raises(McpPreviewUnavailable, match="mcp_preview_unavailable"):
            mcp_preview.pick_preview_tool(
                [{"name": "reject_pr", "input_schema": {}}],
                requested="reject_pr",
            )


def test_preview_refuses_write_even_if_requested():
    tools = [
        {"name": "list_approved_prs", "input_schema": {}},
        {"name": "create_po", "input_schema": {}},
    ]
    with pytest.raises(McpPreviewUnavailable, match="read-only"):
        mcp_preview.pick_preview_tool(tools, requested="create_po")
    picked = mcp_preview.pick_preview_tool(tools)
    assert picked["name"] == "list_approved_prs"


def test_pick_prefers_paged_purchase_header_over_item_text():
    tools = [
        {
            "name": "get_A_PurchaseReqnItemText",
            "input_schema": {"properties": {"top": {"type": "string"}}},
        },
        {
            "name": "get_A_PurchaseRequisitionHeader",
            "input_schema": {"properties": {"top": {"type": "string"}}},
        },
        {
            "name": "get_A_PurchaseRequisitionHeader_by_key",
            "input_schema": {"properties": {"PurchaseRequisition": {}}},
        },
    ]
    picked = mcp_preview.pick_preview_tool(tools)
    assert picked["name"] == "get_A_PurchaseRequisitionHeader"
