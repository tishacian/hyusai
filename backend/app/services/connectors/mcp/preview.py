"""Read-only MCP data preview. Never calls write tools."""

from __future__ import annotations

import json
from typing import Any, Mapping, Optional

from app.services.connectors.mcp import client as mcp_client
from app.services.connectors.mcp.errors import McpPreviewUnavailable

PREVIEW_ROW_CAP = 8
PREVIEW_COL_CAP = 8

_READ_PREFIXES = ("get_", "get", "list_", "list", "query_", "query", "search_", "search", "read_", "read")
_WRITE_PREFIXES = ("post_", "post", "patch_", "patch", "put_", "put", "delete_", "delete", "create_", "create", "update_", "update")
_WRITE_NAMES = frozenset(
    {
        "reject_pr",
        "create_po",
        "handle_rejection",
        "fi_discardfrompurchasing",
        "fi_enableforpurchasing",
    }
)
_READ_NAMES = frozenset({"fi_validate", "check_budget"})
_SAFE_OPTIONAL_ARGS = frozenset(
    {"$top", "$skip", "$filter", "$select", "$orderby", "top", "skip", "limit"}
)
_RECORD_KEYS = ("value", "prs", "pos", "items", "records", "results", "data", "rows")
_PAGE_KEYS = ("$top", "top", "limit")
_SKIP_NAME_SUFFIXES = ("_by_key",)
_SKIP_NAME_TOKENS = ("itemtext", "unitofmeasure", "searchusers")
_PREFERRED_ENTITIES = (
    "purchaserequisitionheader",
    "purchaserequisition",
    "purchaseorder",
    "materialdocument",
    "taskcollection",
)
_PREFERRED_COLUMNS = (
    "PurchaseRequisition",
    "PurchaseRequisitionType",
    "PurReqnDescription",
    "CreationDate",
    "TaskTitle",
    "TaskDefinitionName",
    "Status",
    "Priority",
    "InstanceID",
    "PurchaseOrder",
    "PurchaseOrderType",
    "Supplier",
    "PurchaseOrderDate",
    "PurchasingOrganization",
    "MaterialDocument",
    "MaterialDocumentYear",
    "GoodsMovementCode",
    "PostingDate",
)


def classify_kind(name: str) -> str:
    """Classify a live MCP tool name. Does not invent contract aliases."""
    raw = str(name or "").strip()
    lower = raw.lower()
    if lower.startswith(_WRITE_PREFIXES) or lower in _WRITE_NAMES:
        return "write"
    if lower.startswith("bapi_") and any(token in lower for token in ("create", "commit", "rollback")):
        return "write"
    if lower in _READ_NAMES or lower.startswith(_READ_PREFIXES):
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


def _is_by_key(name: str) -> bool:
    lower = name.lower()
    return any(lower.endswith(suffix) for suffix in _SKIP_NAME_SUFFIXES)


def is_preview_safe(tool: Mapping[str, Any]) -> bool:
    name = str(tool.get("name") or "").strip()
    if not name or classify_kind(name) != "read":
        return False
    if _is_by_key(name):
        return False
    if any(token in name.lower() for token in _SKIP_NAME_TOKENS):
        return False
    required = _required_args(_schema_map(tool))
    return all(item in _SAFE_OPTIONAL_ARGS for item in required)


def _page_value(spec: Any, *, default: int = PREVIEW_ROW_CAP) -> Any:
    if isinstance(spec, Mapping) and spec.get("type") == "string":
        return str(default)
    return default


def preview_arguments(tool: Mapping[str, Any]) -> dict[str, Any]:
    schema = _schema_map(tool)
    props = schema.get("properties")
    props = props if isinstance(props, Mapping) else {}
    for key in _PAGE_KEYS:
        if key in props:
            return {key: _page_value(props.get(key))}
    return {}


def _rank(tool: Mapping[str, Any]) -> tuple[int, int, int, int, str]:
    name = str(tool.get("name") or "")
    lower = name.lower()
    props = _schema_map(tool).get("properties")
    props = props if isinstance(props, Mapping) else {}
    has_page = 0 if any(key in props for key in _PAGE_KEYS) else 1
    preferred = 0 if any(token in lower for token in _PREFERRED_ENTITIES) else 1
    noisy = 1 if any(token in lower for token in _SKIP_NAME_TOKENS) else 0
    if lower.startswith("list"):
        verb = 0
    elif lower.startswith("get"):
        verb = 1
    elif lower.startswith(("query", "search", "read")):
        verb = 2
    else:
        verb = 3
    return (noisy, preferred, verb, has_page, lower)


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
    safe.sort(key=_rank)
    return safe[0]


def pick_preview_tools(
    tools: list[Mapping[str, Any]],
    *,
    requested: Optional[str] = None,
    limit: int = 3,
) -> list[dict[str, Any]]:
    if requested:
        return [pick_preview_tool(tools, requested=requested)]
    safe = [dict(item) for item in tools if isinstance(item, Mapping) and is_preview_safe(item)]
    safe.sort(key=_rank)
    if not safe:
        raise McpPreviewUnavailable("No read-only list or get tool can be previewed without keys")
    return safe[: max(1, int(limit))]


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
    data = payload.get("data")
    if isinstance(data, Mapping):
        for key in ("results", "value", "items"):
            found = data.get(key)
            if isinstance(found, list):
                return [_as_record(item) for item in found]
    if isinstance(data, list):
        return [_as_record(item) for item in data]
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


def gateway_refusal(payload: Any) -> str | None:
    """SAP Gateway sometimes answers MCP with HTTP 200 and a 403 body."""
    if not isinstance(payload, Mapping):
        return None
    status = payload.get("status")
    flagged = payload.get("error") is True or str(status) in {"403", "401", "404"}
    if not flagged:
        return None
    message = payload.get("message")
    if isinstance(message, Mapping):
        message = message.get("value") or message.get("message")
    text = str(message or "").strip()
    return text or f"SAP refused the read ({status})"


def _visible_columns(records: list[dict[str, Any]]) -> list[str]:
    seen: list[str] = []
    lower: dict[str, str] = {}
    for row in records:
        for key in row:
            name = str(key)
            if name.startswith("__") or name.startswith("to_") or name in {"__metadata", "metadata"}:
                continue
            if name not in lower:
                lower[name.lower()] = name
                seen.append(name)
    preferred: list[str] = []
    for wanted in _PREFERRED_COLUMNS:
        hit = lower.get(wanted.lower())
        if hit and hit not in preferred:
            preferred.append(hit)
        if len(preferred) >= PREVIEW_COL_CAP:
            return preferred
    for name in seen:
        if name not in preferred:
            preferred.append(name)
        if len(preferred) >= PREVIEW_COL_CAP:
            break
    return preferred


def flatten_preview(payload: Any) -> dict[str, Any]:
    records = extract_records(payload)
    columns = _visible_columns(records)
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
    candidates = pick_preview_tools(tools, requested=tool_name)
    last_error: Optional[Exception] = None
    for chosen in candidates:
        name = str(chosen.get("name") or "")
        try:
            called = mcp_client.call_tool(
                server,
                contract_tool=name,
                arguments=preview_arguments(chosen),
                timeout_s=40.0,
            )
        except Exception as exc:  # noqa: BLE001 — try the next safe read tool
            last_error = exc
            continue
        refused = gateway_refusal(called.get("result"))
        if refused:
            last_error = McpPreviewUnavailable(refused)
            continue
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
    if last_error is not None:
        raise last_error
    raise McpPreviewUnavailable("No read-only list or get tool can be previewed without keys")
