"""OAuth client-credentials for MCP HTTP servers. No HANA fallback."""

from __future__ import annotations

import hashlib
import json
import math
import time
from collections.abc import Mapping
from typing import Any

import httpx

from app.services.connectors.http_transport import destination_for_url, pinned_client
from app.services.connectors.legacy_network import network_scoped
from app.services.connectors.mcp.contract import AUTH_INHERIT, AUTH_OAUTH
from app.services.connectors.mcp.errors import McpCallFailed, McpUnconfigured, McpUnreachable
from app.services.connectors.network_policy import ConnectorNetworkError

DEFAULT_TIMEOUT_S = 20.0
_SKEW_S = 30.0
_DEFAULT_TTL_S = 300.0
_CACHE: dict[str, tuple[str, float]] = {}


def clear_token_cache() -> None:
    _CACHE.clear()


def fetch_access_token(
    *,
    token_url: str,
    client_id: str,
    client_secret: str,
    scope: str = "",
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> str:
    token_url = str(token_url or "").strip()
    client_id = str(client_id or "").strip()
    client_secret = str(client_secret or "").strip()
    scope = str(scope or "").strip()
    if not token_url or not client_id or not client_secret:
        raise McpUnconfigured(
            "MCP OAuth client-credentials is incomplete "
            "(oauth_token_url, oauth_client_id, oauth_client_secret)"
        )
    try:
        checked_url, destination = destination_for_url(token_url, require_https=True)
    except ConnectorNetworkError as exc:
        raise McpUnreachable("MCP OAuth destination refused", code=exc.code) from None
    # Scope and credential rotation cannot reuse an earlier grant. Only the
    # digest is retained as the cache key; never retain the client secret there.
    cache_key = hashlib.sha256(
        json.dumps([str(checked_url), client_id, client_secret, scope]).encode()
    ).hexdigest()
    now = time.monotonic()
    cached = _CACHE.get(cache_key)
    if cached and cached[1] > now:
        return cached[0]

    data: dict[str, str] = {"grant_type": "client_credentials"}
    if scope:
        data["scope"] = scope
    try:
        with pinned_client(checked_url, destination, timeout=timeout_s) as client:
            response = client.post(
                token_url,
                data=data,
                auth=(client_id, client_secret),
                headers={"Accept": "application/json"},
            )
    except ConnectorNetworkError as exc:
        raise McpUnreachable("MCP OAuth destination refused", code=exc.code) from None
    except httpx.TimeoutException:
        raise McpUnreachable("MCP OAuth token endpoint timed out") from None
    except httpx.RequestError:
        raise McpUnreachable("MCP OAuth connection failed") from None
    if 300 <= response.status_code < 400:
        raise McpUnreachable("MCP OAuth redirect refused", code="CONNECTOR_REDIRECT_DENIED")
    if response.status_code >= 400:
        raise McpUnreachable("MCP OAuth token request rejected")
    try:
        body = response.json()
    except Exception as exc:
        raise McpCallFailed("MCP OAuth token endpoint returned non-JSON") from exc
    if not isinstance(body, Mapping):
        raise McpCallFailed("MCP OAuth token endpoint returned a non-object JSON body")
    token = str(body.get("access_token") or "").strip()
    if not token:
        raise McpCallFailed("MCP OAuth token endpoint returned no access_token")
    try:
        ttl = float(body.get("expires_in"))
    except (TypeError, ValueError):
        ttl = _DEFAULT_TTL_S
    if not math.isfinite(ttl) or ttl <= 0:
        raise McpCallFailed("MCP OAuth token expiry is invalid")
    _CACHE[cache_key] = (token, now + max(0, ttl - _SKEW_S))
    return token


@network_scoped
def access_token_for_server(server: Mapping[str, Any]) -> str:
    mode = str(server.get("auth_mode") or "")
    if mode in {AUTH_OAUTH, AUTH_INHERIT}:
        return fetch_access_token(
            token_url=str(server.get("oauth_token_url") or ""),
            client_id=str(server.get("oauth_client_id") or ""),
            client_secret=str(server.get("oauth_client_secret") or ""),
            scope=str(server.get("oauth_scope") or ""),
        )
    return str(server.get("token") or "")
