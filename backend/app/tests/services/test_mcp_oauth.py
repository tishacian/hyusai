"""OAuth client-credentials for the generic MCP client. No HANA fallback."""

from __future__ import annotations

import httpx
import pytest

from app.services.connectors.mcp import client as mcp_client
from app.services.connectors.mcp import oauth as mcp_oauth
from app.services.connectors.mcp.errors import McpUnconfigured, McpUnreachable


def test_oauth_token_is_sent_as_bearer(monkeypatch):
    mcp_oauth.clear_token_cache()
    token_response = httpx.Response(
        200,
        json={"access_token": "live-access", "expires_in": 3600, "token_type": "Bearer"},
        request=httpx.Request("POST", "https://auth.example/oauth/token"),
    )
    init_response = httpx.Response(
        200,
        json={
            "jsonrpc": "2.0",
            "id": "1",
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "serverInfo": {"name": "sap-mcp", "version": "1"},
            },
        },
        headers={"mcp-session-id": "sess-1"},
        request=httpx.Request("POST", "https://mcp.example/pr"),
    )
    list_response = httpx.Response(
        200,
        json={
            "jsonrpc": "2.0",
            "id": "2",
            "result": {"tools": [{"name": "list_approved_prs", "description": ""}]},
        },
        request=httpx.Request("POST", "https://mcp.example/pr"),
    )

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, headers=None, data=None, json=None, auth=None):
            posted.append({"url": url, "headers": dict(headers or {}), "data": data, "auth": auth})
            if url.endswith("/oauth/token"):
                assert auth == ("client-id", "client-secret")
                assert data["grant_type"] == "client_credentials"
                return token_response
            if json and json.get("method") == "initialize":
                assert headers["Authorization"] == "Bearer live-access"
                return init_response
            if json and json.get("method") == "tools/list":
                assert headers["Authorization"] == "Bearer live-access"
                return list_response
            raise AssertionError(f"unexpected POST {url} {json}")

    posted: list[dict] = []
    monkeypatch.setattr(httpx, "Client", _FakeClient)
    server = {
        "id": "sap",
        "url": "https://mcp.example/pr",
        "auth_mode": "inherit",
        "oauth_token_url": "https://auth.example/oauth/token",
        "oauth_client_id": "client-id",
        "oauth_client_secret": "client-secret",
        "tool_aliases": {},
        "credential_source": "workspace",
    }
    result = mcp_client.test_connection(server)
    assert result["ok"] is True
    assert result["server_id"] == "sap"
    assert result["protocol"] == "2024-11-05"
    assert [row["url"] for row in posted][0].endswith("/oauth/token")
    mcp_oauth.clear_token_cache()


def test_client_posts_with_redirects_enabled(monkeypatch):
    seen: dict[str, bool] = {}

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            seen["follow_redirects"] = bool(kwargs.get("follow_redirects"))

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, headers=None, json=None, **kwargs):
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": "1",
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "serverInfo": {"name": "sap-mcp", "version": "1"},
                    },
                },
                request=httpx.Request("POST", url),
            )

    monkeypatch.setattr(httpx, "Client", _FakeClient)
    result, _session = mcp_client.jsonrpc(
        {"id": "sap", "url": "https://mcp.example/pr", "token": "t", "auth_mode": "bearer"},
        "initialize",
        {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}},
    )
    assert seen["follow_redirects"] is True
    assert result["serverInfo"]["name"] == "sap-mcp"


def test_oauth_missing_secret_is_named():
    mcp_oauth.clear_token_cache()
    with pytest.raises(McpUnconfigured, match="mcp_unconfigured"):
        mcp_oauth.fetch_access_token(
            token_url="https://auth.example/oauth/token",
            client_id="client-id",
            client_secret="",
        )


def test_oauth_token_http_error_is_unreachable():
    mcp_oauth.clear_token_cache()

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, *args, **kwargs):
            return httpx.Response(
                401,
                text="unauthorized",
                request=httpx.Request("POST", "https://auth.example/oauth/token"),
            )

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(httpx, "Client", _FakeClient)
    try:
        with pytest.raises(McpUnreachable, match="mcp_unreachable"):
            mcp_oauth.fetch_access_token(
                token_url="https://auth.example/oauth/token",
                client_id="client-id",
                client_secret="nope",
            )
    finally:
        monkeypatch.undo()
        mcp_oauth.clear_token_cache()
