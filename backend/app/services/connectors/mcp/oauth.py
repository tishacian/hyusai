"""OAuth client-credentials for MCP HTTP servers. No HANA fallback."""

from __future__ import annotations

import time
from typing import Any, Mapping

import httpx

from app.services.connectors.mcp.contract import AUTH_INHERIT, AUTH_OAUTH
from app.services.connectors.mcp.errors import McpCallFailed, McpUnconfigured, McpUnreachable

DEFAULT_TIMEOUT_S = 20.0
_SKEW_S = 30.0
_DEFAULT_TTL_S = 300.0
_CACHE: dict[tuple[str, str], tuple[str, float]] = {}


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
    cache_key = (token_url, client_id)
    now = time.monotonic()
    cached = _CACHE.get(cache_key)
    if cached and cached[1] > now:
        return cached[0]

    data: dict[str, str] = {"grant_type": "client_credentials"}
    if scope:
        data["scope"] = scope
    try:
        with httpx.Client(timeout=timeout_s) as client:
            response = client.post(
                token_url,
                data=data,
                auth=(client_id, client_secret),
                headers={"Accept": "application/json"},
            )
    except httpx.TimeoutException as exc:
        raise McpUnreachable("MCP OAuth token endpoint timed out") from exc
    except httpx.RequestError as exc:
        raise McpUnreachable(f"MCP OAuth token endpoint unreachable: {exc}") from exc
    if response.status_code >= 400:
        raise McpUnreachable(f"MCP OAuth token endpoint HTTP {response.status_code}")
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
    _CACHE[cache_key] = (token, now + max(_SKEW_S, ttl - _SKEW_S))
    return token


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
