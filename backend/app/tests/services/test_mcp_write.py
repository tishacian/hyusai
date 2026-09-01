"""Flag-gated MCP writes: allow-list, TESTRUN ban, sealed default, rollback."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.connectors.mcp import client as mcp_client
from app.services.connectors.mcp import write as mcp_write


def _workspace(**features) -> SimpleNamespace:
    return SimpleNamespace(id="ws-1", slug="nawa", settings={"features": features})


def _server(server_id: str = "bapi_po") -> dict:
    return {
        "id": server_id,
        "url": "http://mock",
        "token": "",
        "tool_aliases": {},
        "credential_source": "workspace",
        "configured": True,
        "enabled": True,
    }


def test_flag_defaults_off_and_reads_features():
    assert mcp_write.workspace_write_unsealed(_workspace()) is False
    assert mcp_write.workspace_write_unsealed(_workspace(sap_write_unsealed=False)) is False
    assert mcp_write.workspace_write_unsealed(_workspace(sap_write_unsealed=True)) is True


def test_allow_list_refuses_everything_else(monkeypatch):
    def boom(*_args, **_kwargs):
        raise AssertionError("no socket may open for a refused tool")

    monkeypatch.setattr(mcp_client, "call_tool", boom)
    for tool in ("BAPI_PO_CHANGE", "delete_A_PurchaseOrder", "get_A_PurchaseOrder", ""):
        with pytest.raises(ValueError):
            mcp_write.invoke_write_tool(
                _server(), server_id="bapi_po", tool=tool, arguments={}, unsealed=True
            )


def test_testrun_is_banned_at_any_depth(monkeypatch):
    def boom(*_args, **_kwargs):
        raise AssertionError("a TESTRUN payload must never reach the client")

    monkeypatch.setattr(mcp_client, "call_tool", boom)
    payloads = [
        {"TESTRUN": "X"},
        {"import": {"TESTRUN": "X"}},
        {"tables": {"POITEM": [{"TESTRUN": "X"}]}},
        {"import": {"testrun": ""}},
    ]
    for arguments in payloads:
        with pytest.raises(ValueError, match="TESTRUN is banned"):
            mcp_write.invoke_write_tool(
                _server(),
                server_id="bapi_po",
                tool="BAPI_PO_CREATE1",
                arguments=arguments,
                unsealed=True,
            )
        # The ban holds on the sealed path too: a sealed envelope carrying
        # TESTRUN would be approved by a human and replayed verbatim later.
        with pytest.raises(ValueError, match="TESTRUN is banned"):
            mcp_write.invoke_write_tool(
                None,
                server_id="bapi_po",
                tool="BAPI_PO_CREATE1",
                arguments=arguments,
                unsealed=False,
            )


def test_sealed_envelope_never_calls_and_needs_no_server(monkeypatch):
    def boom(*_args, **_kwargs):
        raise AssertionError("sealed writes must not call the tool")

    monkeypatch.setattr(mcp_client, "call_tool", boom)
    out = mcp_write.invoke_write_tool(
        None,
        server_id="bapi_po",
        tool="BAPI_PO_CREATE1",
        arguments={"tables": {"POHEADER": {"DOC_TYPE": "ZLPO"}}},
        unsealed=False,
    )
    assert out["sealed"] is True
    assert out["called"] is False
    assert out["reason"] == "write_sealed"
    assert "sap_write_unsealed" in out["sap_block"]
    assert out["result"]["arguments"]["tables"]["POHEADER"]["DOC_TYPE"] == "ZLPO"


def test_unsealed_write_requires_a_resolved_server():
    with pytest.raises(ValueError, match="resolved server"):
        mcp_write.invoke_write_tool(
            None,
            server_id="bapi_po",
            tool="BAPI_TRANSACTION_COMMIT",
            arguments={"import": {"WAIT": "X"}},
            unsealed=True,
        )


def _fake_call(responses: dict[str, dict], captured: list[dict]):
    def call(server, **kwargs):
        captured.append(kwargs)
        return {
            "ok": True,
            "result": responses[kwargs["contract_tool"]],
            "server_id": str(server.get("id") or ""),
            "tool": kwargs["contract_tool"],
            "contract_tool": kwargs["contract_tool"],
            "credential_source": "workspace",
            "duration_ms": 12,
        }

    return call


def test_unsealed_create_success_reads_return_and_po_number(monkeypatch):
    captured: list[dict] = []
    ok_create = {
        "tables": {
            "RETURN": [
                {"TYPE": "W", "ID": "06", "NUMBER": "219", "MESSAGE": "Net price adopted"},
            ]
        },
        "export": {"EXPHEADER": {"PO_NUMBER": "4500382517"}, "EXPPURCHASEORDER": "4500382517"},
    }
    monkeypatch.setattr(
        mcp_client, "call_tool", _fake_call({"BAPI_PO_CREATE1": ok_create}, captured)
    )
    out = mcp_write.invoke_write_tool(
        _server(),
        server_id="bapi_po",
        tool="BAPI_PO_CREATE1",
        arguments={"tables": {}},
        unsealed=True,
    )
    assert out["sealed"] is False
    assert out["called"] is True
    assert out["sap_ok"] is True
    assert out["po_number"] == "4500382517"
    assert out["rolled_back"] is False
    assert out["messages"][0]["type"] == "W"
    assert [call["contract_tool"] for call in captured] == ["BAPI_PO_CREATE1"]


def test_failed_create_rolls_back_immediately(monkeypatch):
    captured: list[dict] = []
    failed_create = {
        "tables": {
            "RETURN": [
                {"TYPE": "E", "ID": "ME", "NUMBER": "023", "MESSAGE": "Supplier blocked"},
                {"TYPE": "E", "ID": "MEPO", "NUMBER": "000", "MESSAGE": "faulty items"},
            ]
        }
    }
    monkeypatch.setattr(
        mcp_client,
        "call_tool",
        _fake_call(
            {"BAPI_PO_CREATE1": failed_create, "BAPI_TRANSACTION_ROLLBACK": {"tables": {}}},
            captured,
        ),
    )
    out = mcp_write.invoke_write_tool(
        _server(),
        server_id="bapi_po",
        tool="BAPI_PO_CREATE1",
        arguments={"tables": {}},
        unsealed=True,
    )
    assert out["sap_ok"] is False
    assert out["rolled_back"] is True
    assert out["po_number"] == ""
    assert [call["contract_tool"] for call in captured] == [
        "BAPI_PO_CREATE1",
        "BAPI_TRANSACTION_ROLLBACK",
    ]


def test_commit_and_discard_do_not_roll_back(monkeypatch):
    captured: list[dict] = []
    monkeypatch.setattr(
        mcp_client,
        "call_tool",
        _fake_call(
            {
                "BAPI_TRANSACTION_COMMIT": {"tables": {"RETURN": []}},
                "fi_DiscardFromPurchasing": {"status": 200, "data": {}},
            },
            captured,
        ),
    )
    committed = mcp_write.invoke_write_tool(
        _server(),
        server_id="bapi_po",
        tool="BAPI_TRANSACTION_COMMIT",
        arguments={"import": {"WAIT": "X"}},
        unsealed=True,
    )
    assert committed["sap_ok"] is True
    assert committed["rolled_back"] is False
    discarded = mcp_write.invoke_write_tool(
        _server("sap"),
        server_id="sap",
        tool="fi_DiscardFromPurchasing",
        arguments={"PurchaseRequisition": "2000276449", "PurchaseRequisitionItem": "20"},
        unsealed=True,
    )
    assert discarded["sap_ok"] is True
    assert discarded["tool"] == "fi_DiscardFromPurchasing"
    assert len(captured) == 2


def test_gateway_refusal_reads_as_sap_error(monkeypatch):
    captured: list[dict] = []
    refusal = {"status": 403, "error": True, "message": "Not authorized"}
    monkeypatch.setattr(
        mcp_client,
        "call_tool",
        _fake_call(
            {"fi_DiscardFromPurchasing": refusal},
            captured,
        ),
    )
    out = mcp_write.invoke_write_tool(
        _server("sap"),
        server_id="sap",
        tool="fi_DiscardFromPurchasing",
        arguments={"PurchaseRequisition": "1", "PurchaseRequisitionItem": "10"},
        unsealed=True,
    )
    assert out["sap_ok"] is False
    assert out["messages"][0]["message"] == "Not authorized"


def test_verdict_never_uses_the_transport_flag():
    # isError stays false on SAP rejections; the verdict is the payload's own.
    ok, messages = mcp_write.sap_write_verdict(
        "BAPI_PO_CREATE1",
        {"tables": {"RETURN": [{"TYPE": "E", "MESSAGE": "ME/006 locked"}]}},
    )
    assert ok is False
    assert messages[0]["message"] == "ME/006 locked"
    ok, messages = mcp_write.sap_write_verdict("BAPI_TRANSACTION_COMMIT", {"tables": {}})
    assert ok is True
    assert messages == []
    assert mcp_write.bapi_po_number(
        {"export": {"EXPPURCHASEORDER": "4500382511"}}
    ) == "4500382511"
