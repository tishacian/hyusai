"""Structural contract for the production Agentic chat graph."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

AGENTIC_SYSTEM_TYPE = "chat_agentic"
AGENTIC_VARIANT = "chat_agentic_thinking_v1"
EXPECTED_FLOW_REVISION = "056_andritz_chat_asset_binding"
NOTICES_COLLECTION = "andritz-notices-techniques-spl-pilot"
EXPECTED_FLOW_CONTRACT_SHA256 = "6780628580346fb97c7112e86e7492fb31abc688329b7d72cd81afecf75c762a"
_INSTALLATION_OR_COSMETIC_CONFIG_KEYS = frozenset({"skill_id", "params_note"})


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _contract_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _contract_value(item)
            for key, item in value.items()
            if key not in _INSTALLATION_OR_COSMETIC_CONFIG_KEYS
        }
    if isinstance(value, list):
        return [_contract_value(item) for item in value]
    return value


def agentic_flow_contract_digest(flow_definition: Any) -> str | None:
    """Hash the complete executable spine while ignoring editor cosmetics.

    All node ids/kinds/configuration and every typed/labelled edge are pinned.
    Only installation-specific skill UUIDs and documentary ``params_note``
    fields are removed.  Adding a bypass edge, dropping HITL/egress/evaluation
    nodes, or changing a decision condition therefore changes the digest.
    """

    flow = _mapping(flow_definition)
    raw_nodes = flow.get("nodes")
    raw_edges = flow.get("edges")
    if not isinstance(raw_nodes, list) or not isinstance(raw_edges, list):
        return None
    if not all(isinstance(node, Mapping) for node in raw_nodes) or not all(
        isinstance(edge, Mapping) for edge in raw_edges
    ):
        return None
    canonical = {
        "variant": flow.get("variant"),
        # DAG insertion order is executable: join merges and scheduling retain
        # the persisted order.  Keep both lists verbatim in the contract.
        "nodes": [
            {
                "id": node.get("id"),
                "kind": node.get("kind"),
                "config": _contract_value(node.get("config") or {}),
            }
            for node in raw_nodes
        ],
        "edges": [
            {
                "from": edge.get("from"),
                "to": edge.get("to"),
                "kind": edge.get("kind"),
                "branch_label": edge.get("branch_label"),
            }
            for edge in raw_edges
        ],
    }
    try:
        payload = json.dumps(
            canonical,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError):
        return None
    return hashlib.sha256(payload).hexdigest()


def is_expected_agentic_flow(settings: Any, flow_definition: Any) -> bool:
    """Validate the pinned revision and complete governed serving topology."""

    system_settings = _mapping(settings)
    if (
        system_settings.get("system_type") != AGENTIC_SYSTEM_TYPE
        or system_settings.get("flow_revision") != EXPECTED_FLOW_REVISION
    ):
        return False
    return agentic_flow_contract_digest(flow_definition) == EXPECTED_FLOW_CONTRACT_SHA256
