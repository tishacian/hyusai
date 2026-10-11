"""One MCP client: JSON-RPC over HTTP (JSON or SSE). No stdio, no HANA fallback."""

from __future__ import annotations

import json
import time
from typing import Any, Mapping, Optional
from uuid import uuid4

import httpx

from app.services.connectors.mcp.contract import (
    TOOLS_LIST_CAP,
    contract_gap,
    resolve_alias,
)
from app.services.connectors.mcp.errors import (
    McpCallFailed,
    McpToolUnknown,
    McpUnreachable,
)
from app.services.connectors.mcp.oauth import access_token_for_server

DEFAULT_TIMEOUT_S = 20.0
PROTOCOL_VERSION = "2024-11-05"


def _headers(token: str, session_id: Optional[str] = None) -> dict[str, str]:
    headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if session_id:
        headers["Mcp-Session-Id"] = session_id
    return headers


def _parse_sse_json(text: str) -> Optional[dict[str, Any]]:
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _read_jsonrpc(response: httpx.Response) -> dict[str, Any]:
    ctype = (response.headers.get("content-type") or "").lower()
    text = response.text or ""
    if "text/event-stream" in ctype or text.lstrip().startswith("event:") or "\ndata:" in text:
        parsed = _parse_sse_json(text)
        if parsed is not None:
            return parsed
    try:
        body = response.json()
    except Exception as exc:
        raise McpCallFailed(f"MCP server returned non-JSON body ({response.status_code})") from exc
    if not isinstance(body, dict):
        raise McpCallFailed("MCP server returned a non-object JSON body")
    return body


def _rpc_error(body: Mapping[str, Any], *, default_code: str = "mcp_call_failed") -> None:
    err = body.get("error")
    if not isinstance(err, Mapping):
        return
    message = str(err.get("message") or "MCP call failed")
    code = err.get("code")
    if code in (-32601, "MethodNotFound") or "unknown tool" in message.lower():
        raise McpToolUnknown(message)
    raise McpCallFailed(f"{message} (rpc={code})", code=default_code)


def jsonrpc(
    server: Mapping[str, Any],
    method: str,
    params: Optional[Mapping[str, Any]] = None,
    *,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    session_id: Optional[str] = None,
    request_id: Optional[str] = None,
) -> tuple[dict[str, Any], Optional[str]]:
    """POST one JSON-RPC method. Returns (result object, session id)."""
    url = str(server.get("url") or "").strip()
    if not url:
        raise McpUnreachable("MCP server url is empty")
    token = access_token_for_server(server)
    payload = {
        "jsonrpc": "2.0",
        "id": request_id or str(uuid4()),
        "method": method,
        "params": dict(params) if isinstance(params, Mapping) else {},
    }
    try:
        with httpx.Client(timeout=timeout_s, follow_redirects=True) as client:
            response = client.post(url, headers=_headers(token, session_id), json=payload)
    except httpx.TimeoutException as exc:
        raise McpUnreachable(f"MCP server timed out calling {method}") from exc
    except httpx.RequestError as exc:
        raise McpUnreachable(f"MCP server unreachable: {exc}") from exc

    next_session = response.headers.get("mcp-session-id") or session_id
    if response.status_code >= 400:
        raise McpUnreachable(
            f"MCP server HTTP {response.status_code} on {method}: {response.text[:300]}"
        )
    body = _read_jsonrpc(response)
    _rpc_error(body)
    result = body.get("result")
    if result is None:
        raise McpCallFailed(f"MCP {method} returned no result")
    if not isinstance(result, dict):
        raise McpCallFailed(f"MCP {method} result must be an object")
    return result, next_session


def initialize(server: Mapping[str, Any], *, timeout_s: float = DEFAULT_TIMEOUT_S) -> dict[str, Any]:
    result, session_id = jsonrpc(
        server,
        "initialize",
        {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "agentium-mcp", "version": "1"},
        },
        timeout_s=timeout_s,
    )
    return {"result": result, "session_id": session_id}


def list_tools(
    server: Mapping[str, Any],
    *,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    session_id: Optional[str] = None,
    cap: int = TOOLS_LIST_CAP,
) -> dict[str, Any]:
    started = time.perf_counter()
    session = session_id
    if session is None:
        opened = initialize(server, timeout_s=timeout_s)
        session = opened.get("session_id")
    result, session = jsonrpc(
        server, "tools/list", {}, timeout_s=timeout_s, session_id=session
    )
    raw_tools = result.get("tools")
    tools: list[dict[str, Any]] = []
    if isinstance(raw_tools, list):
        for item in raw_tools[: max(1, int(cap))]:
            if isinstance(item, Mapping):
                tools.append(
                    {
                        "name": str(item.get("name") or ""),
                        "description": str(item.get("description") or ""),
                        "input_schema": item.get("inputSchema") or item.get("input_schema"),
                    }
                )
    names = [tool["name"] for tool in tools if tool["name"]]
    server_id = str(server.get("id") or "")
    return {
        "ok": True,
        "server_id": server_id,
        "tools": tools,
        "count": len(tools),
        "capped": isinstance(raw_tools, list) and len(raw_tools) > len(tools),
        "contract": contract_gap(server_id, names),
        "credential_source": server.get("credential_source"),
        "session_id": session,
        "duration_ms": int((time.perf_counter() - started) * 1000),
    }


def _unwrap_call_result(result: Mapping[str, Any]) -> Any:
    if "structuredContent" in result and result.get("structuredContent") is not None:
        return result.get("structuredContent")
    if "structured_content" in result and result.get("structured_content") is not None:
        return result.get("structured_content")
    content = result.get("content")
    if isinstance(content, list):
        texts: list[str] = []
        for item in content:
            if isinstance(item, Mapping) and item.get("type") in (None, "text"):
                texts.append(str(item.get("text") or ""))
        joined = "\n".join(part for part in texts if part).strip()
        if joined:
            try:
                parsed = json.loads(joined)
            except json.JSONDecodeError:
                return {"text": joined, "is_error": bool(result.get("isError"))}
            return parsed
    if result.get("isError"):
        raise McpCallFailed(str(result.get("error") or "MCP tool returned isError"))
    return dict(result)


def call_tool(
    server: Mapping[str, Any],
    *,
    contract_tool: str,
    arguments: Optional[Mapping[str, Any]] = None,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> dict[str, Any]:
    """``tools/list`` then ``tools/call``. Trace names the server and both tool names."""
    started = time.perf_counter()
    listed = list_tools(server, timeout_s=timeout_s)
    aliases = server.get("tool_aliases") if isinstance(server.get("tool_aliases"), Mapping) else {}
    mcp_name = resolve_alias(aliases, contract_tool)
    known = {str(tool.get("name") or "") for tool in listed.get("tools") or []}
    if mcp_name not in known:
        raise McpToolUnknown(
            f"MCP tool {mcp_name!r} is not advertised by server {server.get('id')!r}"
        )
    result, _session = jsonrpc(
        server,
        "tools/call",
        {"name": mcp_name, "arguments": dict(arguments) if isinstance(arguments, Mapping) else {}},
        timeout_s=timeout_s,
        session_id=listed.get("session_id"),
    )
    if result.get("isError"):
        detail = result.get("error")
        if not detail:
            content = result.get("content")
            if isinstance(content, list):
                texts = [
                    str(item.get("text") or "")
                    for item in content
                    if isinstance(item, Mapping)
                ]
                detail = " ".join(part for part in texts if part).strip()
        raise McpCallFailed(str(detail or f"MCP tool {mcp_name} failed"))
    unwrapped = _unwrap_call_result(result)
    payload = unwrapped if isinstance(unwrapped, dict) else {"value": unwrapped}
    return {
        "ok": True,
        "result": payload,
        "server_id": str(server.get("id") or ""),
        "tool": mcp_name,
        "contract_tool": str(contract_tool or ""),
        "credential_source": server.get("credential_source"),
        "duration_ms": int((time.perf_counter() - started) * 1000),
    }


def test_connection(server: Mapping[str, Any], *, timeout_s: float = DEFAULT_TIMEOUT_S) -> dict[str, Any]:
    """Session + ``tools/list`` — the operator health gesture."""
    started = time.perf_counter()
    opened = initialize(server, timeout_s=timeout_s)
    listed = list_tools(
        server, timeout_s=timeout_s, session_id=opened.get("session_id")
    )
    return {
        "ok": True,
        "server_id": str(server.get("id") or ""),
        "credential_source": server.get("credential_source"),
        "protocol": (opened.get("result") or {}).get("protocolVersion"),
        "server_info": (opened.get("result") or {}).get("serverInfo"),
        "tools": listed.get("tools") or [],
        "contract": listed.get("contract") or {},
        "duration_ms": int((time.perf_counter() - started) * 1000),
    }
