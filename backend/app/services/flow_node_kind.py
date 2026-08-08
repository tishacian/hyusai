"""Canonical structural role of one authored Flow node.

Two graph dialects exist in the estate.  The canonical one names the structural
role in ``kind`` (``source``/``task``/``sink``/``decision``…) and uses ``type``
only as a sub-discriminator of that role (``source.webhook``, ``input``).
Graphs authored before ``kind`` existed carry no ``kind`` at all and name the
role in ``type``.

``kind`` is canonical and ``type`` is tolerated legacy: a node carrying both
resolves from ``kind`` alone, so a graph whose two fields disagree resolves
deterministically instead of by mapping order.  The fallback is deliberately
narrow — only the exact literal ``type: "source"``.  Dotted ``source.*`` types
are sub-discriminators that accompany an explicit ``kind`` in every graph in the
estate, and ``kind: asset`` with ``type: source.collection`` is a declarative
asset rather than an entry point; widening the fallback to the ``source.``
prefix would promote those assets to externally invokable ingresses.

Every reader that asks "is this node a source?" must resolve it here.  The
compiler decides from that answer whether to freeze an ingress, and the DAG
walker re-checks the same property before it will serve a Run against that
frozen ingress (``dag._contract_ingress_selection``); if the two disagree the
boundary accepts a Run the engine then refuses.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

DEFAULT_NODE_KIND = "task"

# Role names tolerated in ``type`` when ``kind`` is absent. Deliberately not the
# full role vocabulary: a legacy ``type: "sink"`` stays a task because promoting
# it would change compiled outputs and terminal-collection semantics, which is a
# separate decision from recognising an entry point.
_LEGACY_ROLE_TYPES = frozenset({"source"})


def flow_node_kind(node: Mapping[str, Any]) -> str:
    """Resolve a node's structural role, preferring the canonical ``kind``."""

    kind = node.get("kind")
    if isinstance(kind, str) and kind:
        return kind
    node_type = node.get("type")
    if isinstance(node_type, str) and node_type in _LEGACY_ROLE_TYPES:
        return node_type
    return DEFAULT_NODE_KIND


def is_flow_source_node(node: Mapping[str, Any]) -> bool:
    """True when the node is an entry point in either graph dialect."""

    return flow_node_kind(node) == "source"


__all__ = ["DEFAULT_NODE_KIND", "flow_node_kind", "is_flow_source_node"]
