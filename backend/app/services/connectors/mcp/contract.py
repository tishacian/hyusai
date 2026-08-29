"""PDF PR→PO MCP contract: seven tools, write-set in code, not in the payload."""

from __future__ import annotations

from typing import Any, Mapping

# Contract names (aliases default to these until the real MCP spec arrives).
LIST_APPROVED_PRS = "list_approved_prs"
CHECK_BUDGET = "check_budget"
GET_JUSTIFICATION = "get_justification"
REJECT_PR = "reject_pr"
CREATE_PO = "create_po"
HANDLE_REJECTION = "handle_rejection"
LIST_POS_BY_TYPE = "list_pos_by_type"

SAP_CONTRACT_TOOLS: tuple[str, ...] = (
    LIST_APPROVED_PRS,
    CHECK_BUDGET,
    GET_JUSTIFICATION,
    REJECT_PR,
    CREATE_PO,
    HANDLE_REJECTION,
)
HIKMA_CONTRACT_TOOLS: tuple[str, ...] = (LIST_POS_BY_TYPE,)

WRITE_CONTRACT_TOOLS: frozenset[str] = frozenset(
    {REJECT_PR, CREATE_PO, HANDLE_REJECTION}
)

CONTRACT_BY_SERVER: dict[str, tuple[str, ...]] = {
    "sap": SAP_CONTRACT_TOOLS,
    "hikma": HIKMA_CONTRACT_TOOLS,
}

# Named skill → (server_id, contract_tool). Canvas allowlist; no free tool.
NAMED_SKILLS: dict[str, tuple[str, str]] = {
    "sap_list_approved_prs_v1": ("sap", LIST_APPROVED_PRS),
    "sap_check_budget_v1": ("sap", CHECK_BUDGET),
    "sap_get_justification_v1": ("sap", GET_JUSTIFICATION),
    "sap_reject_pr_v1": ("sap", REJECT_PR),
    "hikma_list_pos_by_type_v1": ("hikma", LIST_POS_BY_TYPE),
    "sap_create_po_v1": ("sap", CREATE_PO),
    "sap_handle_rejection_v1": ("sap", HANDLE_REJECTION),
}

NAMED_SKILL_SLUGS: frozenset[str] = frozenset(NAMED_SKILLS)
MCP_SKILL_SLUGS: frozenset[str] = NAMED_SKILL_SLUGS | frozenset({"mcp_call_v1"})
WRITE_SKILL_SLUGS: frozenset[str] = frozenset(
    slug for slug, (_server, tool) in NAMED_SKILLS.items() if tool in WRITE_CONTRACT_TOOLS
)

TOOLS_LIST_CAP = 80
DEFAULT_TRANSPORT = "http_sse"
ALLOWED_TRANSPORTS: frozenset[str] = frozenset({DEFAULT_TRANSPORT})


def expected_tools(server_id: str) -> tuple[str, ...]:
    return CONTRACT_BY_SERVER.get(str(server_id or "").strip(), ())


def is_write_tool(tool: str) -> bool:
    return str(tool or "").strip() in WRITE_CONTRACT_TOOLS


def default_aliases(server_id: str) -> dict[str, str]:
    return {name: name for name in expected_tools(server_id)}


def resolve_alias(aliases: Mapping[str, Any] | None, contract_tool: str) -> str:
    name = str(contract_tool or "").strip()
    if not name:
        raise ValueError("tool is required")
    if not isinstance(aliases, Mapping):
        return name
    mapped = aliases.get(name)
    if mapped is None:
        return name
    resolved = str(mapped).strip()
    return resolved or name


def contract_gap(
    server_id: str, listed_names: list[str]
) -> dict[str, list[str]]:
    expected = list(expected_tools(server_id))
    listed = [str(n).strip() for n in listed_names if str(n).strip()]
    listed_set = set(listed)
    expected_set = set(expected)
    return {
        "expected": expected,
        "listed": listed[:TOOLS_LIST_CAP],
        "missing": [name for name in expected if name not in listed_set],
        "unexpected": [name for name in listed if name not in expected_set],
    }
