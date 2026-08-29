"""Frozen PR/PO MCP fixture. Same process serves ``/sap`` and ``/hikma``.

This is the contract until live credentials exist. It is not a HANA
demo_dataset fallback — skills only reach it when the workspace (or env)
points a server URL here.
"""

from __future__ import annotations

import json
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock
from typing import Any, Mapping
from urllib.parse import urlparse

from app.services.connectors.mcp.client import PROTOCOL_VERSION
from app.services.connectors.mcp.contract import (
    CHECK_BUDGET,
    CREATE_PO,
    GET_JUSTIFICATION,
    HANDLE_REJECTION,
    HIKMA_CONTRACT_TOOLS,
    LIST_APPROVED_PRS,
    LIST_POS_BY_TYPE,
    REJECT_PR,
    SAP_CONTRACT_TOOLS,
)

SERVER_INFO = {"name": "agentium-mcp-fixture", "version": "1"}

_INITIAL_PRS: list[dict[str, Any]] = [
    {
        "pr_id": "PR-4401",
        "type": "IT_HARDWARE",
        "pr_type": "IT_HARDWARE",
        "title": "Warehouse scanners",
        "amount": 85_000,
        "currency": "QAR",
        "requester": "Fatima Al-Sayed",
        "status": "approved",
    },
    {
        "pr_id": "PR-4402",
        "type": "IT_HARDWARE",
        "pr_type": "IT_HARDWARE",
        "title": "Laptop replacements — finance",
        "amount": 12_000,
        "currency": "QAR",
        "requester": "Hassan Al-Mansouri",
        "status": "approved",
    },
]

_BUDGETS: dict[str, dict[str, Any]] = {
    "PR-4401": {
        "pr_id": "PR-4401",
        "budget_ok": False,
        "available": 50_000,
        "requested": 85_000,
        "currency": "QAR",
        "reason": "Requested amount exceeds remaining cost-center budget",
    },
    "PR-4402": {
        "pr_id": "PR-4402",
        "budget_ok": True,
        "available": 50_000,
        "requested": 12_000,
        "currency": "QAR",
        "reason": "Within remaining cost-center budget",
    },
}

_JUSTIFICATIONS: dict[str, dict[str, Any]] = {
    "PR-4401": {
        "pr_id": "PR-4401",
        "justification": (
            "Replace failing handheld scanners on the Doha warehouse floor. "
            "Current devices drop barcode reads during peak inbound, which "
            "has delayed two weekly cycles. The request is for 40 units."
        ),
    },
    "PR-4402": {
        "pr_id": "PR-4402",
        "justification": (
            "Finance laptops are past refresh. The team needs six machines "
            "with a shared docking format so month-end close can continue "
            "while staff rotate between office and plant."
        ),
    },
}

_HIKMA_POS: list[dict[str, Any]] = [
    {"po_id": "PO-881", "pr_type": "IT_HARDWARE", "supplier": "ACME", "format": "XML"},
    {"po_id": "PO-882", "pr_type": "IT_HARDWARE", "supplier": "ACME", "format": "XML"},
    {"po_id": "PO-883", "pr_type": "IT_HARDWARE", "supplier": "ACME", "format": "XML"},
    {"po_id": "PO-884", "pr_type": "IT_HARDWARE", "supplier": "BETA", "format": "EDI"},
    {"po_id": "PO-900", "pr_type": "FACILITIES", "supplier": "DELTA", "format": "PDF"},
]


class FixtureState:
    """In-memory PR/PO ledger. Tests call ``reset()`` between cases."""

    def __init__(self) -> None:
        self._lock = Lock()
        self.reset()

    def reset(self) -> None:
        with self._lock:
            self.prs = deepcopy(_INITIAL_PRS)
            self.rejected: list[dict[str, Any]] = []
            self.pos: list[dict[str, Any]] = []
            self.handled: list[dict[str, Any]] = []

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "prs": deepcopy(self.prs),
                "rejected": deepcopy(self.rejected),
                "pos": deepcopy(self.pos),
                "handled": deepcopy(self.handled),
            }


STATE = FixtureState()


def _tool_schema(name: str) -> dict[str, Any]:
    return {"name": name, "description": f"Fixture contract tool {name}", "inputSchema": {"type": "object"}}


def sap_tools() -> list[dict[str, Any]]:
    return [_tool_schema(name) for name in SAP_CONTRACT_TOOLS]


def hikma_tools() -> list[dict[str, Any]]:
    return [_tool_schema(name) for name in HIKMA_CONTRACT_TOOLS]


def _pr(pr_id: str) -> dict[str, Any] | None:
    for row in STATE.prs:
        if str(row.get("pr_id") or "") == pr_id:
            return row
    return None


def call_sap(name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
    args = dict(arguments) if isinstance(arguments, Mapping) else {}
    pr_id = str(args.get("pr_id") or "").strip()
    if name == LIST_APPROVED_PRS:
        with STATE._lock:
            prs = [row for row in deepcopy(STATE.prs) if row.get("status") == "approved"]
        return {"prs": prs, "count": len(prs)}
    if name == CHECK_BUDGET:
        if pr_id not in _BUDGETS:
            raise KeyError(pr_id)
        return dict(_BUDGETS[pr_id])
    if name == GET_JUSTIFICATION:
        if pr_id not in _JUSTIFICATIONS:
            raise KeyError(pr_id)
        return dict(_JUSTIFICATIONS[pr_id])
    if name == REJECT_PR:
        with STATE._lock:
            row = next((p for p in STATE.prs if p.get("pr_id") == pr_id), None)
            if row is None:
                raise KeyError(pr_id)
            row["status"] = "rejected"
            event = {
                "pr_id": pr_id,
                "reason": str(args.get("reason") or "budget"),
                "rejected": True,
            }
            STATE.rejected.append(event)
        return event
    if name == CREATE_PO:
        with STATE._lock:
            row = next((p for p in STATE.prs if p.get("pr_id") == pr_id), None)
            if row is None:
                raise KeyError(pr_id)
            po = {
                "po_id": f"PO-{pr_id}",
                "pr_id": pr_id,
                "supplier": str(args.get("supplier") or ""),
                "format": str(args.get("format") or ""),
                "amount": args.get("amount", row.get("amount")),
                "created": True,
            }
            row["status"] = "ordered"
            STATE.pos.append(po)
        return po
    if name == HANDLE_REJECTION:
        with STATE._lock:
            row = next((p for p in STATE.prs if p.get("pr_id") == pr_id), None)
            if row is None:
                raise KeyError(pr_id)
            row["status"] = "human_rejected"
            event = {
                "pr_id": pr_id,
                "note": str(args.get("note") or ""),
                "handled": True,
            }
            STATE.handled.append(event)
        return event
    raise KeyError(name)


def call_hikma(name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
    args = dict(arguments) if isinstance(arguments, Mapping) else {}
    if name != LIST_POS_BY_TYPE:
        raise KeyError(name)
    pr_type = str(args.get("pr_type") or args.get("type") or "").strip()
    pos = [row for row in _HIKMA_POS if not pr_type or row.get("pr_type") == pr_type]
    return {"pos": deepcopy(pos), "pr_type": pr_type, "count": len(pos)}


def handle_jsonrpc(server: str, request: Mapping[str, Any]) -> dict[str, Any]:
    """Pure JSON-RPC handler used by the HTTP server and by unit tests."""
    rpc_id = request.get("id")
    method = str(request.get("method") or "")
    params = request.get("params") if isinstance(request.get("params"), Mapping) else {}
    tools = sap_tools() if server == "sap" else hikma_tools() if server == "hikma" else []
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "result": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {**SERVER_INFO, "server": server},
            },
        }
    if method in {"notifications/initialized", "initialized"}:
        return {"jsonrpc": "2.0", "id": rpc_id, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": rpc_id, "result": {"tools": tools}}
    if method == "tools/call":
        name = str(params.get("name") or "").strip()
        arguments = params.get("arguments") if isinstance(params.get("arguments"), Mapping) else {}
        known = {tool["name"] for tool in tools}
        if name not in known:
            return {
                "jsonrpc": "2.0",
                "id": rpc_id,
                "error": {"code": -32601, "message": f"unknown tool {name}"},
            }
        try:
            if server == "sap":
                result = call_sap(name, arguments)
            else:
                result = call_hikma(name, arguments)
        except KeyError as exc:
            return {
                "jsonrpc": "2.0",
                "id": rpc_id,
                "error": {"code": -32602, "message": f"unknown argument {exc}"},
            }
        return {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "result": {
                "content": [{"type": "text", "text": json.dumps(result)}],
                "structuredContent": result,
                "isError": False,
            },
        }
    return {
        "jsonrpc": "2.0",
        "id": rpc_id,
        "error": {"code": -32601, "message": f"unknown method {method}"},
    }


class FixtureHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        return

    def _server_id(self) -> str | None:
        path = urlparse(self.path).path.rstrip("/") or "/"
        if path in {"/sap", "/mcp/sap"}:
            return "sap"
        if path in {"/hikma", "/mcp/hikma"}:
            return "hikma"
        return None

    def _send(self, status: int, body: Mapping[str, Any]) -> None:
        payload = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self) -> None:  # noqa: N802
        server = self._server_id()
        if server is None:
            self._send(404, {"error": "unknown MCP fixture path"})
            return
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            request = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            self._send(400, {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}})
            return
        if not isinstance(request, dict):
            self._send(400, {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "invalid request"}})
            return
        self._send(200, handle_jsonrpc(server, request))

    def do_GET(self) -> None:  # noqa: N802
        if urlparse(self.path).path.rstrip("/") in {"/health", ""}:
            self._send(200, {"ok": True, "fixture": True})
            return
        self._send(404, {"error": "use POST JSON-RPC on /sap or /hikma"})


def serve(host: str = "127.0.0.1", port: int = 8765) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), FixtureHandler)
