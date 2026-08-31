"""Keyed read-only MCP call. Preview stays keyless; this path may pass arguments."""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Optional

from app.services.connectors.mcp import client as mcp_client
from app.services.connectors.mcp.contract import (
    CHECK_BUDGET,
    CREATE_PO,
    GET_JUSTIFICATION,
    HANDLE_REJECTION,
    LIST_APPROVED_PRS,
    LIST_POS_BY_TYPE,
    REJECT_PR,
)
from app.services.connectors.mcp.errors import McpToolUnknown
from app.services.connectors.mcp.preview import (
    classify_kind,
    extract_records,
    gateway_refusal,
)

LIVE_PR_ITEM = "get_A_PurchaseRequisitionItem"
LIVE_PR_ITEM_BY_KEY = "get_A_PurchaseRequisitionItem_by_key"
LIVE_BUDGET = "fi_Validate"
LIVE_ACCT = "get_A_PurReqnAcctAssgmt"
LIVE_PO_ITEM = "get_A_PurchaseOrderItem"
LIVE_PO_HEADER = "get_A_PurchaseOrder"
LIVE_DISCARD = "fi_DiscardFromPurchasing"
LIVE_CREATE_PO = "post_A_PurchaseOrder"
ITEM_TEXT_EXPAND = "to_PurchaseReqnItemText"
DEFAULT_PR_ITEM = "10"
APPROVED_PR_TOP = "50"
PO_ITEM_TOP = "200"
PO_HEADER_CAP = 5
READ_ROW_CAP = 50
APPROVED_PR_FILTER = (
    "PurchaseRequisitionStatus eq 'X' and PurchasingDocument eq '' "
    "and IsDeleted eq '' and IsClosed eq false"
)
APPROVED_PR_SELECT = (
    "PurchaseRequisition,PurchaseRequisitionItem,PurchaseRequisitionItemText,"
    "Material,MaterialGroup,RequestedQuantity,BaseUnit,PurchaseRequisitionPrice,"
    "PurReqnItemCurrency,Plant,CompanyCode,PurchasingGroup,DeliveryDate,"
    "PurchaseRequisitionType"
)
ACCT_SELECT = (
    "PurchaseRequisitionItem,CostCenter,WBSElement,Fund,FundsCenter,"
    "CommitmentItem,GLAccount,PurReqnNetAmount"
)
PO_ITEM_SELECT = (
    "PurchaseOrder,PurchaseOrderItem,Material,MaterialGroup,Plant,"
    "NetPriceAmount,DocumentCurrency,PurchaseRequisition"
)
PO_HEADER_SELECT = (
    "PurchaseOrder,Supplier,PurchaseOrderType,PaymentTerms,DocumentCurrency,"
    "IncotermsClassification,PurchasingOrganization,PurchasingGroup,CompanyCode,"
    "NetPaymentDays"
)
WRITE_SEALED_REASON = "write_sealed"
SAP_CREATE_BLOCK = (
    "The API accepts only document type NB; client 300 has no NB number range "
    "and ZAPO is not allowed through the API"
)
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


def _advertised(names: Iterable[str]) -> set[str]:
    found = {str(name or "").strip() for name in names}
    found.discard("")
    return found


def _pick(advertised: Iterable[str], live: str, fixture: str, server_id: str) -> str:
    names = _advertised(advertised)
    if live in names:
        return live
    if fixture in names:
        return fixture
    raise McpToolUnknown(f"MCP tool {live!r} is not advertised by server {server_id!r}")


def approved_pr_item_arguments() -> dict[str, Any]:
    return {
        "filter": APPROVED_PR_FILTER,
        "select": APPROVED_PR_SELECT,
        "orderby": "PurchaseRequisitionReleaseDate desc",
        "top": APPROVED_PR_TOP,
        "inlinecount": "allpages",
    }


def budget_arguments(pr_id: str) -> dict[str, str]:
    return {"PurchaseRequisition": str(pr_id or "")}


def acct_assgmt_arguments(pr_id: str) -> dict[str, str]:
    return {
        "filter": f"PurchaseRequisition eq '{str(pr_id or '')}'",
        "select": ACCT_SELECT,
    }


def po_item_arguments(material_group: str) -> dict[str, str]:
    group = str(material_group or "").replace("'", "")
    return {
        "filter": f"MaterialGroup eq '{group}'",
        "select": PO_ITEM_SELECT,
        "top": PO_ITEM_TOP,
    }


def po_header_arguments(po_id: str) -> dict[str, str]:
    number = str(po_id or "").replace("'", "")
    return {
        "filter": f"PurchaseOrder eq '{number}'",
        "select": PO_HEADER_SELECT,
    }


def inbox_list_arguments(*, top: int = 50) -> dict[str, int]:
    return {"top": int(top)}


def discard_arguments(pr_id: str, item: str = DEFAULT_PR_ITEM) -> dict[str, str]:
    return {
        "PurchaseRequisition": str(pr_id or ""),
        "PurchaseRequisitionItem": str(item or "").strip() or DEFAULT_PR_ITEM,
    }


def create_po_request_body(
    *,
    pr_id: str,
    item: str = DEFAULT_PR_ITEM,
    supplier: str = "",
    material: str = "",
    plant: str = "1000",
    quantity: str = "1",
    unit: str = "EA",
    net_price: str = "0.00",
    currency: str = "QAR",
    purchase_order: str = "",
    company_code: str = "1000",
    purchase_order_type: str = "NB",
    purchasing_organization: str = "CPO",
    purchasing_group: str = "351",
    payment_terms: str = "Z090",
    incoterms: str = "DAP",
) -> dict[str, Any]:
    header_po = str(purchase_order or "")
    item_no = str(item or "").strip() or DEFAULT_PR_ITEM
    return {
        "PurchaseOrder": header_po,
        "CompanyCode": str(company_code or "1000"),
        "PurchaseOrderType": str(purchase_order_type or "NB"),
        "PurchasingOrganization": str(purchasing_organization or "CPO"),
        "PurchasingGroup": str(purchasing_group or "351"),
        "Supplier": str(supplier or ""),
        "DocumentCurrency": str(currency or "QAR"),
        "PaymentTerms": str(payment_terms or "Z090"),
        "IncotermsClassification": str(incoterms or "DAP"),
        "to_PurchaseOrderItem": [
            {
                "PurchaseOrder": header_po,
                "PurchaseOrderItem": item_no,
                "PurchaseOrderItemCategory": "0",
                "PurchaseRequisition": str(pr_id or ""),
                "PurchaseRequisitionItem": item_no,
                "Material": str(material or ""),
                "Plant": str(plant or "1000"),
                "StorageLocation": "1000",
                "OrderQuantity": str(quantity or "1"),
                "PurchaseOrderQuantityUnit": str(unit or "EA"),
                "NetPriceAmount": str(net_price or "0.00"),
                "DocumentCurrency": str(currency or "QAR"),
                "RequisitionerName": "AGENT",
            }
        ],
    }


def pick_approved_pr_tool(advertised: Iterable[str]) -> tuple[str, dict[str, Any]]:
    tool = _pick(advertised, LIVE_PR_ITEM, LIST_APPROVED_PRS, "sap")
    if tool == LIVE_PR_ITEM:
        return tool, approved_pr_item_arguments()
    return tool, {}


def pick_budget_tool(advertised: Iterable[str], *, pr_id: str) -> tuple[str, dict[str, Any]]:
    tool = _pick(advertised, LIVE_BUDGET, CHECK_BUDGET, "sap")
    if tool == LIVE_BUDGET:
        return tool, budget_arguments(pr_id)
    return tool, {"pr_id": str(pr_id or "")}


def pick_acct_tool(advertised: Iterable[str], *, pr_id: str) -> tuple[str, dict[str, str]]:
    names = _advertised(advertised)
    if LIVE_ACCT in names:
        return LIVE_ACCT, acct_assgmt_arguments(pr_id)
    raise McpToolUnknown(f"MCP tool {LIVE_ACCT!r} is not advertised by server 'sap'")


def pick_po_item_tool(
    advertised: Iterable[str], *, material_group: str, pr_type: str = ""
) -> tuple[str, dict[str, Any]]:
    tool = _pick(advertised, LIVE_PO_ITEM, LIST_POS_BY_TYPE, "hikma")
    if tool == LIVE_PO_ITEM:
        return tool, po_item_arguments(material_group)
    return tool, {"pr_type": str(pr_type or "")}


def pick_po_header_tool(advertised: Iterable[str], *, po_id: str) -> tuple[str, dict[str, str]]:
    names = _advertised(advertised)
    if LIVE_PO_HEADER in names:
        return LIVE_PO_HEADER, po_header_arguments(po_id)
    raise McpToolUnknown(f"MCP tool {LIVE_PO_HEADER!r} is not advertised by server 'hikma'")


def pick_discard_tool(advertised: Iterable[str]) -> str:
    return _pick(advertised, LIVE_DISCARD, REJECT_PR, "sap")


def pick_create_po_tool(advertised: Iterable[str]) -> str:
    names = _advertised(advertised)
    if LIVE_CREATE_PO in names:
        return LIVE_CREATE_PO
    if CREATE_PO in names:
        return CREATE_PO
    raise McpToolUnknown(f"MCP tool {LIVE_CREATE_PO!r} is not advertised by server 'hikma'")


def pick_handle_rejection_tool(advertised: Iterable[str]) -> str:
    names = _advertised(advertised)
    if LIVE_DISCARD in names:
        return LIVE_DISCARD
    if HANDLE_REJECTION in names:
        return HANDLE_REJECTION
    if REJECT_PR in names:
        return REJECT_PR
    raise McpToolUnknown(f"MCP tool {LIVE_DISCARD!r} is not advertised by server 'sap'")


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


def _odata_count(payload: Any, fallback: int) -> int:
    if not isinstance(payload, Mapping):
        return fallback
    envelopes: list[Mapping[str, Any]] = [payload]
    for key in ("d", "data"):
        inner = payload.get(key)
        if isinstance(inner, Mapping):
            envelopes.append(inner)
    for row in envelopes:
        for key in ("__count", "count"):
            raw = row.get(key)
            if raw is None:
                continue
            try:
                return int(raw)
            except (TypeError, ValueError):
                continue
    return fallback


def flatten_read(payload: Any) -> dict[str, Any]:
    """Table for keyed / filtered reads. Preview row cap stays 8."""
    from app.services.connectors.mcp.preview import _cell, _visible_columns

    records = extract_records(payload)
    columns = _visible_columns(records)
    rows = [[_cell(row.get(col)) for col in columns] for row in records[:READ_ROW_CAP]]
    return {
        "columns": columns,
        "rows": rows,
        "row_count": _odata_count(payload, len(records)),
        "truncated": len(records) > len(rows),
    }


def budget_ok_from_payload(payload: Any) -> tuple[bool, str]:
    """Empty or warnings-only = pass. Any Type 'E' = fail. Never writes."""
    records = extract_records(payload)
    if not records:
        return True, "ok"
    errors: list[str] = []
    for row in records:
        kind = str(row.get("Type") or row.get("type") or "").strip().upper()
        if kind != "E":
            continue
        message = str(
            row.get("Message") or row.get("message") or row.get("Text") or row.get("Note") or ""
        ).strip()
        errors.append(message or "E")
    if errors:
        return False, errors[0]
    return True, "ok"


def listed_tool_names(server: Mapping[str, Any]) -> list[str]:
    listed = mcp_client.list_tools(server)
    return [str(tool.get("name") or "") for tool in listed.get("tools") or []]


def compose_write_sealed(
    *,
    server_id: str,
    tool: str,
    arguments: Mapping[str, Any],
    sap_block: str = "",
) -> dict[str, Any]:
    """Advertise-confirmed write payload. Never calls the tool."""
    return {
        "ok": True,
        "sealed": True,
        "called": False,
        "kind": "write",
        "reason": WRITE_SEALED_REASON,
        "sap_block": sap_block,
        "server_id": server_id,
        "tool": tool,
        "contract_tool": tool,
        "result": {
            "sealed": True,
            "called": False,
            "tool": tool,
            "arguments": dict(arguments),
            "sap_block": sap_block,
        },
    }


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
    table = flatten_read(raw)
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
