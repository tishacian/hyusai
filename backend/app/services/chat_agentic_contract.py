"""Structural contract for the production Agentic chat graph."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

AGENTIC_SYSTEM_TYPE = "chat_agentic"
AGENTIC_VARIANT = "chat_agentic_thinking_v1"
# Revision pinned by the Andritz migrations (048..078).  A System still on it
# is validated against the frozen artifact digest below; the 059 rollout
# marker keeps referring to it.
EXPECTED_FLOW_REVISION = "078_andritz_decision_contract"
ANDRITZ_MIGRATION_FLOW_REVISION = EXPECTED_FLOW_REVISION
NOTICES_COLLECTION = "andritz-notices-techniques-spl-pilot"
EXPECTED_FLOW_CONTRACT_SHA256 = "55611adbfba8848376c567b1be13ca39b2a5c5b008cd78548b7cbf40b077c4a5"
# Revision written by the workspace template (``systems/agentic_chat_template``).
# Its digest depends on the System's recorded ``chat_profile`` (collection
# binding, HITL wording), so it is rendered on demand rather than pinned.
TEMPLATE_FLOW_REVISION = "agentic_chat_template_v4"
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


def expected_contract_digest(settings: Any) -> str | None:
    """Digest a System on ``flow_revision`` must carry, or ``None`` if unknown."""

    system_settings = _mapping(settings)
    revision = system_settings.get("flow_revision")
    if revision == ANDRITZ_MIGRATION_FLOW_REVISION:
        return EXPECTED_FLOW_CONTRACT_SHA256
    if revision == TEMPLATE_FLOW_REVISION:
        from app.services.systems.agentic_chat_template import (
            AgenticChatProfile,
            contract_digest,
        )

        profile_raw = system_settings.get("chat_profile")
        if not isinstance(profile_raw, Mapping) or not profile_raw.get("slug"):
            return None
        try:
            return contract_digest(AgenticChatProfile.from_dict(profile_raw))
        except Exception:  # noqa: BLE001 - a malformed profile is a drift, fail closed
            return None
    return None


def is_expected_agentic_flow(settings: Any, flow_definition: Any) -> bool:
    """Validate the pinned revision and complete governed serving topology.

    Two revisions are legitimate: the Andritz migration pin (frozen digest) and
    the workspace template (digest rendered from the System's own profile).
    """

    system_settings = _mapping(settings)
    if system_settings.get("system_type") != AGENTIC_SYSTEM_TYPE:
        return False
    expected = expected_contract_digest(system_settings)
    if expected is None:
        return False
    return agentic_flow_contract_digest(flow_definition) == expected
