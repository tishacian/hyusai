"""Seed URL policy: live env wins, fixture only when MCP_FIXTURE=1, else empty."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from scripts import seed_nawa_pr_to_po as seed
from app.services.connectors.mcp import service as mcp_service


def test_server_url_prefers_live_then_fixture_then_empty(monkeypatch):
    monkeypatch.delenv("MCP_SAP_URL", raising=False)
    monkeypatch.delenv("MCP_HIKMA_URL", raising=False)
    live = "https://hikmah-s4-po-mcp.cfapps.eu10.hana.ondemand.com/mcp"
    assert seed._server_url("sap", fixture=False, live_default=live) == live
    assert seed._server_url("sap", fixture=True, live_default=live) == "http://127.0.0.1:8765/sap"
    assert seed._server_url("sap_gr", fixture=True, live_default=live) == ""
    monkeypatch.setenv("MCP_SAP_URL", "https://sap.example/mcp")
    assert seed._server_url("sap", fixture=True, live_default=live) == "https://sap.example/mcp"


def test_nawa_live_servers_are_the_four_hikma_s4_urls():
    ids = [row[0] for row in seed.NAWA_LIVE_SERVERS]
    assert ids == ["sap", "hikma", "sap_gr", "sap_inbox"]
    by_id = {row[0]: row for row in seed.NAWA_LIVE_SERVERS}
    assert by_id["sap"][2].endswith("/mcp")
    assert "pr-mcp" in by_id["sap"][2]
    assert "po-mcp" in by_id["hikma"][2]
    assert "goods-receipt" in by_id["sap_gr"][2]
    assert "inbox" in by_id["sap_inbox"][2]
    assert seed.NAWA_OAUTH_TOKEN_URL.endswith("/oauth/token")
    assert seed.NAWA_OAUTH_CLIENT_ID.startswith("sb-hikmah-s4-mcp")


def _workspace():
    return SimpleNamespace(settings={})


def _db():
    db = MagicMock()
    db.add = MagicMock()
    db.commit = MagicMock()
    db.refresh = MagicMock()
    return db


def test_ensure_mcp_servers_writes_nawa_oauth_inherit(monkeypatch):
    monkeypatch.delenv("MCP_FIXTURE", raising=False)
    monkeypatch.delenv("MCP_OAUTH_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("MCP_SAP_URL", raising=False)
    monkeypatch.setattr(mcp_service, "flag_modified", lambda *_a, **_k: None)
    body = seed.ensure_mcp_servers(_db(), _workspace())
    assert [row["id"] for row in body["servers"]] == ["sap", "hikma", "sap_gr", "sap_inbox"]
    assert {row["auth_mode"] for row in body["servers"]} == {"inherit"}
    assert {row["transport"] for row in body["servers"]} == {"streamable_http"}
    assert body["shared_auth"]["oauth_client_id"] == seed.NAWA_OAUTH_CLIENT_ID
    assert body["shared_auth"]["oauth_token_url"] == seed.NAWA_OAUTH_TOKEN_URL
    assert body["shared_auth"]["secret_set"] is False
    sap = next(row for row in body["servers"] if row["id"] == "sap")
    assert sap["url"] == seed.NAWA_LIVE_SERVERS[0][2]
    assert sap["configured"] is False


def test_ensure_mcp_servers_fixture_keeps_sap_hikma_on_http(monkeypatch):
    monkeypatch.setenv("MCP_FIXTURE", "1")
    monkeypatch.delenv("MCP_SAP_URL", raising=False)
    monkeypatch.setattr(mcp_service, "flag_modified", lambda *_a, **_k: None)
    body = seed.ensure_mcp_servers(_db(), _workspace())
    sap = next(row for row in body["servers"] if row["id"] == "sap")
    hikma = next(row for row in body["servers"] if row["id"] == "hikma")
    gr = next(row for row in body["servers"] if row["id"] == "sap_gr")
    assert sap["auth_mode"] == "bearer"
    assert sap["transport"] == "http_sse"
    assert sap["url"] == "http://127.0.0.1:8765/sap"
    assert hikma["url"] == "http://127.0.0.1:8765/hikma"
    assert gr["url"] == ""
    assert gr["auth_mode"] == "inherit"
