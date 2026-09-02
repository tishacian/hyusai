"""Flag-gated live MCP writes. Sealed by default; the write-set is code.

The read path (:mod:`read`) never runs a write tool. This module is the only
place a write tool can execute, and only when the workspace carries the
explicit ``sap_write_unsealed`` feature. With the flag off the same request
returns the sealed envelope — the payload the human would have approved —
without opening a connection.

Rules enforced here, all verified against PIH QA client 300 (2026-08-31):

- **Allow-list.** Only the six documented SAP write tools may run. Anything
  else is refused before a socket opens.
- **TESTRUN is banned** (decision 2026-08-31): a failed simulated create
  leaves the PR enqueue-locked under ``SAP_MCP``. The ban is a deep scan of
  the arguments, not a top-level check.
- **Rollback after a failed create.** ``BAPI_PO_CREATE1`` with any
  ``TYPE: "E"`` in ``tables.RETURN`` leaves the PR locked; this module calls
  ``BAPI_TRANSACTION_ROLLBACK`` on the same server before returning.
- **isError lies.** The MCP transport flag stays ``false`` on SAP rejections.
  Verdicts come from ``tables.RETURN`` (BAPI, upper-case ``TYPE``) or the
  OData payload's own error flag — never from the transport.
"""

from __future__ import annotations

import logging
from typing import Any, Iterable, Mapping, Optional

from app.services.connectors.mcp import client as mcp_client
from app.services.connectors.mcp.preview import classify_kind, gateway_refusal
from app.services.connectors.mcp.read import compose_write_sealed

logger = logging.getLogger(__name__)

WRITE_FLAG = "sap_write_unsealed"
WRITE_TIMEOUT_S = 90.0
BAPI_CREATE = "BAPI_PO_CREATE1"
BAPI_COMMIT = "BAPI_TRANSACTION_COMMIT"
BAPI_ROLLBACK = "BAPI_TRANSACTION_ROLLBACK"
COMMIT_ARGUMENTS: dict[str, Any] = {"import": {"WAIT": "X"}}
GUARDRAIL_REASON = "guardrail_disabled"

#: The only write tools this deployment may ever invoke. BAPI trio for the
#: create/commit/rollback sequence; the two OData function imports for the
#: reversible discard; ``post_A_PurchaseOrder`` documented-blocked (NB has no
#: number range on client 300) but allow-listed so the refusal is SAP's own.
ALLOWED_WRITE_TOOLS: frozenset[str] = frozenset(
    {
        "BAPI_PO_CREATE1",
        "BAPI_TRANSACTION_COMMIT",
        "BAPI_TRANSACTION_ROLLBACK",
        "fi_DiscardFromPurchasing",
        "fi_EnableForPurchasing",
        "post_A_PurchaseOrder",
    }
)

FLAG_OFF_BLOCK = (
    "Write stays sealed: workspace feature sap_write_unsealed is off. "
    "The envelope carries the exact payload that would be sent."
)


def workspace_write_unsealed(workspace: Any) -> bool:
    from app.services.workspace_features import feature_enabled

    return feature_enabled(workspace, WRITE_FLAG, csv_fallback="")


def _reject_testrun(node: Any, path: str = "arguments") -> None:
    if isinstance(node, Mapping):
        for key, value in node.items():
            name = str(key)
            if name.strip().upper() == "TESTRUN":
                raise ValueError(
                    f"TESTRUN is banned ({path}.{name}): a failed simulated create "
                    "leaves the PR enqueue-locked under SAP_MCP"
                )
            _reject_testrun(value, f"{path}.{name}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            _reject_testrun(value, f"{path}[{index}]")


def bapi_return_messages(payload: Any) -> list[dict[str, str]]:
    """``tables.RETURN`` rows as {type, id, number, message}. BAPI is upper-case."""
    if not isinstance(payload, Mapping):
        return []
    tables = payload.get("tables")
    rows = tables.get("RETURN") if isinstance(tables, Mapping) else None
    if rows is None:
        rows = payload.get("RETURN")
    if isinstance(rows, Mapping):
        rows = [rows]
    if not isinstance(rows, list):
        return []
    out: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        out.append(
            {
                "type": str(row.get("TYPE") or row.get("Type") or "").strip().upper(),
                "id": str(row.get("ID") or row.get("Id") or "").strip(),
                "number": str(row.get("NUMBER") or row.get("Number") or "").strip(),
                "message": str(row.get("MESSAGE") or row.get("Message") or "").strip(),
            }
        )
    return out


def bapi_po_number(payload: Any) -> str:
    """PO number from ``export.EXPHEADER.PO_NUMBER`` / ``export.EXPPURCHASEORDER``."""
    if not isinstance(payload, Mapping):
        return ""
    export = payload.get("export")
    if not isinstance(export, Mapping):
        export = payload
    header = export.get("EXPHEADER")
    if isinstance(header, Mapping):
        number = str(header.get("PO_NUMBER") or "").strip()
        if number:
            return number
    return str(export.get("EXPPURCHASEORDER") or "").strip()


def sap_write_verdict(tool: str, payload: Any) -> tuple[bool, list[dict[str, str]]]:
    """Never branch on the MCP transport flag; read the SAP payload itself."""
    messages = bapi_return_messages(payload)
    if messages:
        return not any(row["type"] == "E" for row in messages), messages
    refused = gateway_refusal(payload)
    if refused:
        return False, [{"type": "E", "id": "", "number": "", "message": refused}]
    return True, []


def normalized_blocked_tools(blocked_tools: Any) -> frozenset[str]:
    """Guardrail names the human switched off for this run (``run.input``)."""
    if isinstance(blocked_tools, str):
        blocked_tools = [blocked_tools]
    if not isinstance(blocked_tools, Iterable):
        return frozenset()
    return frozenset(
        str(name or "").strip() for name in blocked_tools if str(name or "").strip()
    )


def compose_write_blocked(
    *, server_id: str, tool: str, arguments: Mapping[str, Any]
) -> dict[str, Any]:
    """The guardrail refused the write; nothing left the platform."""
    return {
        "ok": False,
        "sealed": False,
        "called": False,
        "blocked": True,
        "kind": "write",
        "reason": GUARDRAIL_REASON,
        "server_id": server_id,
        "tool": tool,
        "contract_tool": tool,
        "sap_ok": False,
        "messages": [],
        "po_number": "",
        "rolled_back": False,
        "result": {
            "blocked": True,
            "called": False,
            "reason": GUARDRAIL_REASON,
            "tool": tool,
            "arguments": dict(arguments),
        },
    }


def invoke_write_tool(
    server: Optional[Mapping[str, Any]],
    *,
    server_id: str,
    tool: str,
    arguments: Optional[Mapping[str, Any]] = None,
    unsealed: bool,
    blocked_tools: Iterable[str] | None = None,
    sealed_block: str = FLAG_OFF_BLOCK,
) -> dict[str, Any]:
    """One allow-listed write. Blocked, sealed or live — in that order.

    This is the single gate every SAP write goes through: the HTTP invoke
    route, the run-engine skills and the free ``mcp_call_v1`` skill all end
    here, so the allow-list, the TESTRUN ban, the rollback rule and the
    flag are enforced once.
    """
    name = str(tool or "").strip()
    if not name:
        raise ValueError("tool is required")
    if name not in ALLOWED_WRITE_TOOLS:
        allowed = ", ".join(sorted(ALLOWED_WRITE_TOOLS))
        raise ValueError(f"MCP tool {name!r} is not on the write allow-list ({allowed})")
    if classify_kind(name) == "read":
        raise ValueError(f"MCP tool {name!r} is a read; use the read endpoint")
    if arguments is not None and not isinstance(arguments, Mapping):
        raise ValueError("arguments must be an object")
    args = dict(arguments) if isinstance(arguments, Mapping) else {}
    _reject_testrun(args)
    if name in normalized_blocked_tools(blocked_tools):
        return compose_write_blocked(server_id=server_id, tool=name, arguments=args)
    if not unsealed:
        return compose_write_sealed(
            server_id=server_id,
            tool=name,
            arguments=args,
            sap_block=sealed_block,
        )
    if not isinstance(server, Mapping):
        raise ValueError("a resolved server is required for an unsealed write")
    called = mcp_client.call_tool(
        server,
        contract_tool=name,
        arguments=args,
        timeout_s=WRITE_TIMEOUT_S,
    )
    raw = called.get("result")
    sap_ok, messages = sap_write_verdict(name, raw)
    rolled_back = False
    if name == BAPI_CREATE and not sap_ok:
        # A failed create holds the PR under the SAP_MCP enqueue (ME/006 on
        # retry). Rollback now; a rollback failure is logged, never masked.
        rolled_back = _rollback(server)
    return {
        "ok": True,
        "sealed": False,
        "called": True,
        "blocked": False,
        "kind": "write",
        "server_id": str(called.get("server_id") or server_id),
        "tool": called.get("tool") or name,
        "sap_ok": sap_ok,
        "messages": messages,
        "po_number": bapi_po_number(raw),
        "rolled_back": rolled_back,
        "credential_source": called.get("credential_source"),
        "duration_ms": called.get("duration_ms"),
        "result": raw,
    }


def audit_write(
    workspace_id: str,
    *,
    actor: str,
    server_id: str,
    out: Mapping[str, Any],
    run_id: str | None = None,
) -> None:
    """Every write that left the platform lands in the ledger, whoever asked."""
    from app.services.audit_logger import emit_audit_event

    calls = out.get("calls")
    rows = [row for row in calls if isinstance(row, Mapping)] if isinstance(calls, list) else [out]
    for row in rows:
        if not row.get("called"):
            continue
        details: dict[str, Any] = {
            "server_id": server_id,
            "tool": row.get("tool"),
            "sap_ok": row.get("sap_ok"),
            "po_number": row.get("po_number"),
            "rolled_back": row.get("rolled_back"),
            "messages": row.get("messages"),
            "duration_ms": row.get("duration_ms"),
        }
        if run_id:
            details["run_id"] = run_id
        emit_audit_event(
            workspace_id=str(workspace_id),
            event_type="mcp.write.invoked",
            actor=actor or "system",
            details=details,
        )


def _rollback(server: Mapping[str, Any]) -> bool:
    try:
        mcp_client.call_tool(
            server,
            contract_tool=BAPI_ROLLBACK,
            arguments={"import": {}},
            timeout_s=WRITE_TIMEOUT_S,
        )
        return True
    except Exception:  # noqa: BLE001
        logger.exception("BAPI_TRANSACTION_ROLLBACK failed after a failed create")
        return False


def create_and_commit_po(
    server: Optional[Mapping[str, Any]],
    *,
    server_id: str,
    arguments: Mapping[str, Any],
    unsealed: bool,
    blocked_tools: Iterable[str] | None = None,
    sealed_block: str = FLAG_OFF_BLOCK,
) -> dict[str, Any]:
    """``BAPI_PO_CREATE1`` then ``BAPI_TRANSACTION_COMMIT`` — two calls or nothing.

    The create alone returns a number that never existed: without the commit
    SAP forgets it. A blocked or failed commit rolls the create back so the
    PR is not left enqueue-locked. The envelope keeps both calls verbatim.
    """
    create = invoke_write_tool(
        server,
        server_id=server_id,
        tool=BAPI_CREATE,
        arguments=arguments,
        unsealed=unsealed,
        blocked_tools=blocked_tools,
        sealed_block=sealed_block,
    )
    out = dict(create)
    out["calls"] = [create]
    out["committed"] = False
    if create.get("blocked") or create.get("sealed") or not create.get("sap_ok"):
        return out
    commit = invoke_write_tool(
        server,
        server_id=server_id,
        tool=BAPI_COMMIT,
        arguments=COMMIT_ARGUMENTS,
        unsealed=unsealed,
        blocked_tools=blocked_tools,
        sealed_block=sealed_block,
    )
    out["calls"].append(commit)
    committed = bool(commit.get("called")) and bool(commit.get("sap_ok"))
    out["committed"] = committed
    out["messages"] = list(create.get("messages") or []) + list(commit.get("messages") or [])
    if not committed:
        out["sap_ok"] = False
        out["po_number"] = ""
        if isinstance(server, Mapping):
            out["rolled_back"] = _rollback(server)
    return out
