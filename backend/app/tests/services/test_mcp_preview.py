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
    assert mcp_preview.classify_kind("post_A_PurchaseOrder") == "write"
    assert mcp_preview.classify_kind("create_po") == "write"
    assert mcp_preview.classify_kind("reject_pr") == "write"
    assert mcp_preview.classify_kind("handle_rejection") == "write"


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


def test_flatten_unwraps_fixture_and_odata_shapes():
    table = mcp_preview.flatten_preview({"prs": [{"pr_id": "PR-1", "title": "Scanners"}]})
    assert table["columns"] == ["pr_id", "title"]
    assert table["rows"][0] == ["PR-1", "Scanners"]
    odata = mcp_preview.flatten_preview({"value": [{"PurchaseRequisition": "1001"}]})
    assert odata["rows"][0][0] == "1001"


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
