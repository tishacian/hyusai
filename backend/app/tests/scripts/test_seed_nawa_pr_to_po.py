"""Seed URL policy: live env wins, fixture only when MCP_FIXTURE=1, else empty."""

from __future__ import annotations

from scripts import seed_nawa_pr_to_po as seed


def test_server_url_prefers_live_then_fixture_then_empty(monkeypatch):
    monkeypatch.delenv("MCP_SAP_URL", raising=False)
    monkeypatch.delenv("MCP_HIKMA_URL", raising=False)
    assert seed._server_url("sap", fixture=False) == ""
    assert seed._server_url("sap", fixture=True) == "http://127.0.0.1:8765/sap"
    monkeypatch.setenv("MCP_SAP_URL", "https://sap.example/mcp")
    assert seed._server_url("sap", fixture=True) == "https://sap.example/mcp"
