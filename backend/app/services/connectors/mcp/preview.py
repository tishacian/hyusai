"""Read-only MCP data preview. Never calls write tools."""

from __future__ import annotations

import json
from typing import Any, Mapping, Optional

from app.services.connectors.mcp import client as mcp_client
from app.services.connectors.mcp.errors import McpPreviewUnavailable

PREVIEW_ROW_CAP = 8
PREVIEW_COL_CAP = 8

_READ_PREFIXES = ("get_", "list_", "query_", "search_", "read_")
_WRITE_PREFIXES = ("post_", "patch_", "put_", "delete_", "create_", "update_")
_WRITE_NAMES = frozenset({"reject_pr", "create_po", "handle_rejection"})
_SAFE_OPTIONAL_ARGS = frozenset({"$top", "$skip", "$filter", "$select", "$orderby", "top", "skip", "limit"})
_RECORD_KEYS = ("value", "prs", "pos", "items", "records", "results", "data", "rows")


def classify_kind(name: str) -> str:
    """Classify a live MCP tool name. Does not invent contract aliases."""
    raw = str(name or "").strip()
    lower = raw.lower()
    if lower.startswith(_WRITE_PREFIXES) or lower in _WRITE_NAMES:
        return "write"
    if lower.startswith(_READ_PREFIXES):
        return "read"
    if "reject" in lower or lower.startswith("handle_"):
        return "write"
    return "other"


def _schema_map(tool: Mapping[str, Any]) -> dict[str, Any]:
    raw = tool.get("input_schema") or tool.get("inputSchema") or {}
    return dict(raw) if isinstance(raw, Mapping) else {}


def _required_args(schema: Mapping[str, Any]) -> list[str]:
    required = schema.get("required")
    if not isinstance(required, list):
        return []
    return [str(item) for item in required if item]


def is_preview_safe(tool: Mapping[str, Any]) -> bool:
    name = str(tool.get("name") or "").strip()
    if not name or classify_kind(name) != "read":
        return False
    required = _required_args(_schema_map(tool))
    return all(item in _SAFE_OPTIONAL_ARGS for item in required)


def preview_arguments(tool: Mapping[str, Any]) -> dict[str, Any]:
    schema = _schema_map(tool)
    props = schema.get("properties")
    props = props if isinstance(props, Mapping) else {}
    if "$top" in props:
        return {"$top": PREVIEW_ROW_CAP}
    if "top" in props:
        return {"top": PREVIEW_ROW_CAP}
    if "limit" in props:
        return {"limit": PREVIEW_ROW_CAP}
    return {}


def _rank(name: str) -> tuple[int, str]:
    lower = name.lower()
    if lower.startswith("list_"):
        return (0, lower)
    if lower.startswith("get_"):
        return (1, lower)
    if lower.startswith(("query_", "search_", "read_")):
        return (2, lower)
    return (3, lower)


def pick_preview_tool(
    tools: list[Mapping[str, Any]],
    *,
    requested: Optional[str] = None,
) -> dict[str, Any]:
    by_name = {str(item.get("name") or ""): item for item in tools if isinstance(item, Mapping)}
    wanted = str(requested or "").strip()
    if wanted:
        tool = by_name.get(wanted)
        if tool is None:
            raise McpPreviewUnavailable(f"MCP tool {wanted!r} is not advertised")
        if not is_preview_safe(tool):
            raise McpPreviewUnavailable(
                f"MCP tool {wanted!r} is not a read-only preview candidate"
            )
        return dict(tool)
    safe = [dict(item) for item in tools if isinstance(item, Mapping) and is_preview_safe(item)]
    if not safe:
        raise McpPreviewUnavailable("No read-only list or get tool can be previewed without keys")
    safe.sort(key=lambda item: _rank(str(item.get("name") or "")))
    return safe[0]


def _as_record(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return {"value": value}


def extract_records(payload: Any) -> list[dict[str, Any]]:
    if payload is None:
        return []
    if isinstance(payload, list):
        return [_as_record(item) for item in payload]
    if not isinstance(payload, Mapping):
        return [_as_record(payload)]
    nested = payload.get("d")
    if isinstance(nested, Mapping) and isinstance(nested.get("results"), list):
        return [_as_record(item) for item in nested["results"]]
    if isinstance(nested, list):
        return [_as_record(item) for item in nested]
    for key in _RECORD_KEYS:
        found = payload.get(key)
        if isinstance(found, list):
            return [_as_record(item) for item in found]
    if payload.get("result") is not None and payload.get("result") is not payload:
        inner = payload.get("result")
        if isinstance(inner, (list, Mapping)):
            return extract_records(inner)
    return [_as_record(payload)]


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        text = str(value)
    else:
        text = json.dumps(value, ensure_ascii=False, default=str)
    if len(text) > 120:
        return text[:117] + "..."
    return text


def flatten_preview(payload: Any) -> dict[str, Any]:
    records = extract_records(payload)
    columns: list[str] = []
    for row in records:
        for key in row:
            name = str(key)
            if name not in columns:
                columns.append(name)
            if len(columns) >= PREVIEW_COL_CAP:
                break
        if len(columns) >= PREVIEW_COL_CAP:
            break
    rows = [[_cell(row.get(col)) for col in columns] for row in records[:PREVIEW_ROW_CAP]]
    return {
        "columns": columns,
        "rows": rows,
        "row_count": len(rows),
        "truncated": len(records) > len(rows),
    }


def preview_server(
    server: Mapping[str, Any],
    *,
    tool_name: Optional[str] = None,
) -> dict[str, Any]:
    """``tools/list`` then one safe ``tools/call``. Write tools never run."""
    listed = mcp_client.list_tools(server)
    tools = [item for item in (listed.get("tools") or []) if isinstance(item, Mapping)]
    chosen = pick_preview_tool(tools, requested=tool_name)
    name = str(chosen.get("name") or "")
    called = mcp_client.call_tool(
        server,
        contract_tool=name,
        arguments=preview_arguments(chosen),
    )
    table = flatten_preview(called.get("result"))
    return {
        "ok": True,
        "server_id": str(server.get("id") or ""),
        "tool": name,
        "kind": "read",
        "credential_source": called.get("credential_source"),
        "duration_ms": called.get("duration_ms"),
        **table,
    }
