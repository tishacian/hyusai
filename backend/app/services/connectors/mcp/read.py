"""Keyed read-only MCP call. Preview stays keyless; this path may pass arguments."""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Optional

from app.services.connectors.mcp import client as mcp_client
from app.services.connectors.mcp.contract import GET_JUSTIFICATION
from app.services.connectors.mcp.errors import McpToolUnknown
from app.services.connectors.mcp.preview import classify_kind, flatten_preview, gateway_refusal

LIVE_PR_ITEM_BY_KEY = "get_A_PurchaseRequisitionItem_by_key"
ITEM_TEXT_EXPAND = "to_PurchaseReqnItemText"
DEFAULT_PR_ITEM = "10"
_TEXT_KEYS = (
    "justification",
    "Note",
    "Text",
    "PlainLongText",
    "NoteDescription",
    "PurchaseRequisitionItemText",
)
_ENVELOPES = ("d", "data", "result")


def live_justification_arguments(pr_id: str, item: str = DEFAULT_PR_ITEM) -> dict[str, str]:
    return {
        "PurchaseRequisition": str(pr_id or ""),
        "PurchaseRequisitionItem": str(item or "").strip() or DEFAULT_PR_ITEM,
        "expand": ITEM_TEXT_EXPAND,
    }


def pick_justification_tool(
    advertised: Iterable[str],
    *,
    pr_id: str,
    item: str = DEFAULT_PR_ITEM,
) -> tuple[str, dict[str, str]]:
    """Advertise-then-call. Live keyed read first; fixture ``get_justification`` next."""
    names = {str(name or "").strip() for name in advertised}
    names.discard("")
    if LIVE_PR_ITEM_BY_KEY in names:
        return LIVE_PR_ITEM_BY_KEY, live_justification_arguments(pr_id, item)
    if GET_JUSTIFICATION in names:
        return GET_JUSTIFICATION, {"pr_id": str(pr_id or "")}
    raise McpToolUnknown(
        f"MCP tool {LIVE_PR_ITEM_BY_KEY!r} is not advertised by server 'sap'"
    )


def _text_from_mapping(row: Mapping[str, Any]) -> str:
    for key in _TEXT_KEYS:
        if key not in row:
            continue
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, Mapping):
            inner = value.get("value")
            if isinstance(inner, str) and inner.strip():
                return inner.strip()
    return ""


def _expand_rows(node: Any) -> list[Mapping[str, Any]]:
    if isinstance(node, list):
        return [item for item in node if isinstance(item, Mapping)]
    if not isinstance(node, Mapping):
        return []
    for key in ("results", "value"):
        found = node.get(key)
        if isinstance(found, list):
            return [item for item in found if isinstance(item, Mapping)]
    return [node]


def _collect_item_texts(node: Any) -> list[str]:
    texts: list[str] = []
    for row in _expand_rows(node):
        hit = _text_from_mapping(row)
        if hit:
            texts.append(hit)
    return texts


def extract_justification_text(payload: Any) -> str:
    """Read Note / Text / PlainLongText / justification. No invented column aliases."""
    if payload is None:
        return ""
    if isinstance(payload, str):
        return payload.strip()
    if not isinstance(payload, Mapping):
        return ""
    candidates: list[Mapping[str, Any]] = [payload]
    for key in _ENVELOPES:
        inner = payload.get(key)
        if isinstance(inner, Mapping):
            candidates.append(inner)
    for row in candidates:
        direct = row.get("justification")
        if isinstance(direct, str) and direct.strip():
            return direct.strip()
        expand = row.get(ITEM_TEXT_EXPAND)
        if expand is not None:
            texts = _collect_item_texts(expand)
            if texts:
                return "\n\n".join(texts)
        hit = _text_from_mapping(row)
        if hit:
            return hit
    return ""


def read_tool(
    server: Mapping[str, Any],
    *,
    tool: str,
    arguments: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """``tools/list`` then one read-only ``tools/call``. Write tools never run."""
    name = str(tool or "").strip()
    if not name:
        raise ValueError("tool is required")
    if classify_kind(name) != "read":
        raise ValueError(f"MCP tool {name!r} is not a read")
    if arguments is not None and not isinstance(arguments, Mapping):
        raise ValueError("arguments must be an object")
    args = dict(arguments) if isinstance(arguments, Mapping) else {}
    if args.get("_side_effect") is not None:
        raise ValueError("arguments._side_effect is not allowed; the write-set is code")
    called = mcp_client.call_tool(
        server,
        contract_tool=name,
        arguments=args,
        timeout_s=40.0,
    )
    refused = gateway_refusal(called.get("result"))
    if refused:
        raise ValueError(refused)
    raw = called.get("result")
    table = flatten_preview(raw)
    return {
        "ok": True,
        "server_id": str(called.get("server_id") or server.get("id") or ""),
        "tool": called.get("tool") or name,
        "kind": "read",
        "credential_source": called.get("credential_source"),
        "duration_ms": called.get("duration_ms"),
        "text": extract_justification_text(raw),
        "result": raw,
        **table,
    }


def call_justification(
    server: Mapping[str, Any],
    *,
    pr_id: str,
    item: str = DEFAULT_PR_ITEM,
) -> dict[str, Any]:
    """Named-skill path: live ``_by_key`` when advertised, else fixture ``get_justification``."""
    listed = mcp_client.list_tools(server)
    names = [str(tool.get("name") or "") for tool in listed.get("tools") or []]
    tool, arguments = pick_justification_tool(names, pr_id=pr_id, item=item)
    called = mcp_client.call_tool(server, contract_tool=tool, arguments=arguments)
    raw = called.get("result")
    text = extract_justification_text(raw)
    if not text and isinstance(raw, Mapping):
        text = str(raw.get("justification") or "").strip()
    return {
        "ok": True,
        "result": {"pr_id": str(pr_id or ""), "justification": text},
        "server_id": called.get("server_id") or server.get("id") or "",
        "tool": called.get("tool") or tool,
        "contract_tool": called.get("contract_tool") or tool,
        "credential_source": called.get("credential_source"),
        "duration_ms": called.get("duration_ms"),
    }
