"""Bounded tool calls; mutations require the exact, approved public contract."""

from __future__ import annotations

import json
from types import SimpleNamespace
from urllib.parse import quote, urlencode
from uuid import uuid4

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError

from app.services.connectors.adapters.http import json_request, request, response
from app.services.connectors.adapters.sql import AdapterError, _remaining
from app.services.connectors.connections import ConnectionError
from app.services.connectors.tool_contracts import (
    _expand,
    allowed_url,
    compile_openapi,
    prepare_tool_contract,
    tool_digest,
)


def _validate(schema, value):
    try:
        schema = _expand(schema, schema)
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(value)
    except (SchemaError, ValidationError, ConnectionError):
        raise AdapterError("CONNECTOR_TOOL_SCHEMA_INVALID") from None


def _headers(config, credentials, deadline_at):
    mode = config.get("auth_mode", "none")
    token = None
    if mode == "bearer":
        token = credentials.get("bearer_token")
    elif mode == "oauth_user":
        token = credentials.get("access_token")
    elif mode == "oauth_client_credentials":
        payload = {
            "grant_type": "client_credentials",
            "client_id": config.get("client_id", ""),
            "client_secret": credentials.get("client_secret", ""),
            "scope": " ".join(config.get("scopes", [])),
        }
        if not payload["client_id"] or not payload["client_secret"]:
            raise AdapterError("CONNECTOR_GRANT_REQUIRED")
        _, body = json_request(
            "POST",
            allowed_url(config, config.get("token_endpoint", "")),
            deadline_at=deadline_at,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            content=urlencode(payload).encode(),
            max_bytes=65536,
        )
        if not isinstance(body, dict) or str(body.get("token_type", "")).lower() != "bearer":
            raise AdapterError("CONNECTOR_OAUTH_TOKEN_INVALID")
        token = body.get("access_token")
    elif mode != "none":
        raise AdapterError("CONNECTOR_AUTH_MODE_UNSUPPORTED")
    if mode != "none" and (
        not isinstance(token, str)
        or not token
        or len(token) > 16384
        or "\r" in token
        or "\n" in token
    ):
        raise AdapterError("CONNECTOR_GRANT_REQUIRED")
    return {"Accept": "application/json", **({"Authorization": f"Bearer {token}"} if token else {})}


def _rpc(config, headers, method, params, deadline_at, *, session_id=None, notification=False):
    request_id = str(uuid4())
    payload = {"jsonrpc": "2.0", "method": method, "params": params}
    if not notification:
        payload["id"] = request_id
    rpc_headers = {
        **headers,
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    if session_id:
        rpc_headers["Mcp-Session-Id"] = session_id
    response_headers, body = request(
        "POST",
        allowed_url(config, config["base_url"]),
        deadline_at=deadline_at,
        headers=rpc_headers,
        content=json.dumps(payload).encode(),
        max_bytes=4 * 1024 * 1024,
    )
    session_id = response_headers.get("mcp-session-id", session_id)
    if notification:
        return {}, session_id
    try:
        messages = (
            [json.loads(body)]
            if "text/event-stream" not in response_headers.get("content-type", "").lower()
            else [
                json.loads(line[5:].strip())
                for line in body.decode().splitlines()
                if line.startswith("data:") and line[5:].strip() not in {"", "[DONE]"}
            ]
        )
        message = next(
            (m for m in messages if isinstance(m, dict) and m.get("id") == request_id), None
        )
    except (ValueError, UnicodeError):
        raise AdapterError("CONNECTOR_MCP_RESPONSE_INVALID") from None
    if not message or message.get("error") or not isinstance(message.get("result"), dict):
        raise AdapterError("CONNECTOR_MCP_CALL_FAILED")
    return message["result"], session_id


def _mcp(operation, config, headers, parameters, deadline_at, execution=None):
    initialized, session_id = _rpc(
        config,
        headers,
        "initialize",
        {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "agentium", "version": "1"},
        },
        deadline_at,
    )
    _rpc(
        config,
        headers,
        "notifications/initialized",
        {},
        deadline_at,
        session_id=session_id,
        notification=True,
    )
    if operation == "test":
        return {
            "connected": True,
            "source": "third_party",
            "protocol_version": initialized.get("protocolVersion"),
        }
    tools, cursor, seen = [], None, set()
    for _ in range(20):
        result, session_id = _rpc(
            config,
            headers,
            "tools/list",
            {"cursor": cursor} if cursor else {},
            deadline_at,
            session_id=session_id,
        )
        batch = result.get("tools")
        if not isinstance(batch, list):
            raise AdapterError("CONNECTOR_MCP_RESPONSE_INVALID")
        for tool in batch:
            if not isinstance(tool, dict) or not isinstance(tool.get("name"), str):
                raise AdapterError("CONNECTOR_MCP_RESPONSE_INVALID")
            if tool["name"] in seen:
                raise AdapterError("CONNECTOR_MCP_RESPONSE_INVALID")
            seen.add(tool["name"])
            if tool["name"] in config.get("tool_allowlist", []):
                annotations = tool.get("annotations") or {}
                tools.append(
                    {
                        "id": tool["name"],
                        "input_schema": tool.get("inputSchema", {}),
                        "output_schema": tool.get("outputSchema", {}),
                        "write": tool["name"] in config.get("write_tools", [])
                        or annotations.get("readOnlyHint") is not True,
                    }
                )
        if len(seen) > 1000:
            raise AdapterError("CONNECTOR_MCP_CATALOG_TOO_LARGE")
        next_cursor = result.get("nextCursor")
        if not next_cursor:
            break
        if next_cursor == cursor or not isinstance(next_cursor, str) or len(next_cursor) > 4096:
            raise AdapterError("CONNECTOR_MCP_RESPONSE_INVALID")
        cursor = next_cursor
    else:
        raise AdapterError("CONNECTOR_MCP_CATALOG_TOO_LARGE")
    if operation == "catalog":
        return {"tools": tools, "source": "third_party"}
    selected = next((t for t in tools if t["id"] == parameters.get("operation_id")), None)
    if not selected:
        raise AdapterError("CONNECTOR_TOOL_NOT_ALLOWED")
    if operation in {"tool_write", "write_preview"}:
        _approved(config, "mcp", selected, parameters, execution)
    elif selected["write"]:
        raise AdapterError("CONNECTOR_TOOL_WRITE_SEALED")
    arguments = parameters.get("arguments", {})
    _validate(selected["input_schema"], arguments)
    if operation == "write_preview":
        return _preview_receipt(execution, selected, remote_schema_checked=True)
    result, _ = _rpc(
        config,
        headers,
        "tools/call",
        {"name": selected["id"], "arguments": arguments},
        deadline_at,
        session_id=session_id,
    )
    if result.get("isError"):
        raise AdapterError("CONNECTOR_TOOL_CALL_FAILED")
    if selected["output_schema"]:
        _validate(selected["output_schema"], result.get("structuredContent"))
    return {
        "tool": selected["id"],
        "result": result,
        "source": "third_party",
        **_receipt(operation, execution),
    }


def _openapi(operation, config, headers, parameters, deadline_at, execution=None):
    contract = compile_openapi(config.get("openapi_spec"), config)
    tools = [t for t in contract["operations"] if t["id"] in config.get("tool_allowlist", [])]
    if operation == "catalog":
        return {"tools": tools, "spec_digest": contract["digest"], "source": "third_party"}
    if operation == "test":
        # Validate a configured, allowed read operation; never invent a successful
        # network test from parsing the document alone.
        raise AdapterError("CONNECTOR_TEST_REQUIRES_TOOL_PREVIEW")
    selected = next((t for t in tools if t["id"] == parameters.get("operation_id")), None)
    if not selected:
        raise AdapterError("CONNECTOR_TOOL_NOT_ALLOWED")
    if operation in {"tool_write", "write_preview"}:
        _approved(config, "openapi", selected, parameters, execution)
    elif selected["write"] or selected["id"] in config.get("write_tools", []):
        raise AdapterError("CONNECTOR_TOOL_WRITE_SEALED")
    arguments = parameters.get("arguments", {})
    _validate(selected["input_schema"], arguments)
    path, query, body = selected["path"], {}, None
    for parameter in selected["parameters"]:
        name = parameter["name"]
        if name not in arguments:
            continue
        if parameter["in"] == "body":
            body = json.dumps(arguments[name], allow_nan=False).encode()
            continue
        value = (
            str(arguments[name]).lower()
            if isinstance(arguments[name], bool)
            else str(arguments[name])
        )
        if parameter["in"] == "path":
            if value in {".", ".."} or any(c in value for c in "/\\\x00"):
                raise AdapterError("CONNECTOR_TOOL_ARGUMENT_INVALID")
            path = path.replace("{" + name + "}", quote(value, safe=""))
        else:
            query[name] = value
    url = selected["base_url"] + path + ("?" + urlencode(query) if query else "")
    if operation == "write_preview":
        allowed_url(config, url)
        return _preview_receipt(execution, selected, remote_schema_checked=False)
    if operation == "tool_write":
        _, payload = mutation_request(
            selected["method"],
            allowed_url(config, url),
            deadline_at=deadline_at,
            headers={
                **headers,
                **({"Content-Type": "application/json"} if body is not None else {}),
            },
            content=body,
            max_bytes=4 * 1024 * 1024,
        )
        try:
            result = json.loads(payload) if payload else None
        except (ValueError, UnicodeError):
            raise AdapterError("CONNECTOR_TOOL_RESPONSE_INVALID") from None
    else:
        _, result = json_request(
            "GET",
            allowed_url(config, url),
            deadline_at=deadline_at,
            headers=headers,
            max_bytes=4 * 1024 * 1024,
        )
    if selected["output_schema"]:
        _validate(selected["output_schema"], result)
    return {
        "tool": selected["id"],
        "result": result,
        "source": "third_party",
        "spec_digest": contract["digest"],
        **_receipt(operation, execution),
    }


def execute(
    operation,
    config,
    credentials,
    parameters,
    deadline_at,
    output_dir,
    *,
    dialect,
    access,
    limits,
    execution=None,
):
    if operation not in {"test", "catalog", "preview", "tool_write", "write_preview"}:
        raise AdapterError("CONNECTOR_OPERATION_UNSUPPORTED")
    if operation in {"tool_write", "write_preview"} and (
        not execution or (access or {}).get("mode") != "read_write"
    ):
        raise AdapterError("CONNECTOR_APPROVAL_REQUIRED")
    if operation == "write_preview" and execution.get("write_operation") != "tool_write":
        raise AdapterError("CONNECTOR_WRITE_CONTRACT_CHANGED")
    try:
        headers = _headers(config, credentials, deadline_at)
        if dialect == "mcp":
            return _mcp(operation, config, headers, parameters, deadline_at, execution)
        if dialect == "openapi":
            return _openapi(operation, config, headers, parameters, deadline_at, execution)
        raise AdapterError("CONNECTOR_PROFILE_UNSUPPORTED")
    except ConnectionError as exc:
        raise AdapterError(exc.code) from None


def _approved(config, dialect, selected, parameters, execution):
    if not execution or not execution.get("operation_id") or not execution.get("contract_digest"):
        raise AdapterError("CONNECTOR_APPROVAL_REQUIRED")
    contract = prepare_tool_contract(
        SimpleNamespace(values=config, profile_key=dialect),
        parameters.get("operation_id"),
        parameters.get("arguments", {}),
    )
    if contract != execution.get("tool_contract") or tool_digest(selected) != tool_digest(
        contract["definition"]
    ):
        raise AdapterError("CONNECTOR_TOOL_CONTRACT_CHANGED")


def _preview_receipt(execution, selected, *, remote_schema_checked):
    return {
        "dry_run": True,
        "applied": False,
        "operation_id": execution["operation_id"],
        "contract_digest": execution["contract_digest"],
        "input_sha256": execution["input_sha256"],
        "write_operation": "tool_write",
        "tool": selected["id"],
        "definition_digest": tool_digest(selected),
        "remote_schema_checked": remote_schema_checked,
        "validation_scope": "live_tool_schema"
        if remote_schema_checked
        else "configured_openapi_contract",
        "effects_observed": False,
        "inserted": None,
        "updated": None,
        "deleted": None,
        "counts_are_estimates": True,
        "source": "third_party",
    }


def _receipt(operation, execution):
    if operation != "tool_write":
        return {}
    return {
        "applied": True,
        "operation_id": execution["operation_id"],
        "contract_digest": execution["contract_digest"],
        "outcome_check": "unsupported",
    }


def mutation_request(method, url, *, deadline_at, headers, content, max_bytes):
    with response(method, url, deadline_at=deadline_at, headers=headers, content=content) as reply:
        if reply.status_code == 202:
            # Accepted asynchronous work is not a receipt of completed mutation.
            raise AdapterError("CONNECTOR_TOOL_OUTCOME_UNKNOWN")
        size, parts = 0, []
        for chunk in reply.iter_bytes():
            _remaining(deadline_at)
            size += len(chunk)
            if size > max_bytes:
                raise AdapterError("CONNECTOR_RESPONSE_TOO_LARGE")
            parts.append(chunk)
        return dict(reply.headers), b"".join(parts)
