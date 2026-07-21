"""Canonical helpers for the additive v3 strict variable contract.

The browser serializer and the Python backfill use the same deterministic
rule: a legacy dot path is converted only when its owner can be identified
without guessing.  Node ids may themselves contain dots, so the longest
matching node id wins before built-in or declared namespaces are considered.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Optional, Sequence

from app.services.run_engine.variable_pool import RESERVED_NAMESPACES


@dataclass(frozen=True)
class SelectorConversion:
    selector: str
    ref: Optional[dict[str, Any]]
    reason: Optional[str] = None

    @property
    def converted(self) -> bool:
        return self.ref is not None


def declared_namespaces(flow: Mapping[str, Any]) -> set[str]:
    raw = flow.get("variable_namespaces")
    if not isinstance(raw, list):
        return set()
    return {str(item).strip() for item in raw if isinstance(item, str) and item.strip()}


def dot_path_to_variable_ref(
    selector: str,
    *,
    node_ids: Sequence[str] | Iterable[str],
    variable_namespaces: Iterable[str] = (),
) -> SelectorConversion:
    """Convert a legacy selector without inferring an unknown namespace."""
    text = str(selector or "").strip()
    if not text:
        return SelectorConversion(selector=text, ref=None, reason="empty_selector")

    def path_segments(tail: str) -> Optional[list[str]]:
        if not tail:
            return []
        segments = tail.split(".")
        if any(not segment.strip() for segment in segments):
            return None
        return segments

    ids = [str(item) for item in node_ids if str(item)]
    matches = [item for item in ids if text == item or text.startswith(f"{item}.")]
    if matches:
        longest = max(len(item) for item in matches)
        winners = [item for item in matches if len(item) == longest]
        # Duplicate node ids make ownership structurally ambiguous even though
        # their text is equal; the DAG validator reports the duplicate too.
        if len(winners) != 1:
            return SelectorConversion(selector=text, ref=None, reason="ambiguous_node")
        owner = winners[0]
        tail = text[len(owner) + 1 :] if text != owner else ""
        if text != owner and not tail:
            return SelectorConversion(selector=text, ref=None, reason="invalid_path")
        path = path_segments(tail)
        if path is None:
            return SelectorConversion(selector=text, ref=None, reason="invalid_path")
        return SelectorConversion(
            selector=text,
            ref={"node_id": owner, "path": path},
        )

    head, separator, tail = text.partition(".")
    allowed = set(RESERVED_NAMESPACES) | {
        str(item).strip() for item in variable_namespaces if str(item).strip()
    }
    if head not in allowed:
        return SelectorConversion(selector=text, ref=None, reason="unknown_namespace")
    path = path_segments(tail if separator else "")
    if path is None:
        return SelectorConversion(selector=text, ref=None, reason="invalid_path")
    return SelectorConversion(
        selector=text,
        ref={"node_id": head, "path": path},
    )


def convert_flow_dot_paths(flow: Mapping[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Return a converted copy plus a machine-readable unresolved report.

    Only ``inputs_map`` values are selectors. ``outputs_map`` values are write
    destinations and remain stable dot paths for compatibility.
    """
    converted = deepcopy(dict(flow))
    raw_nodes = converted.get("nodes")
    nodes = raw_nodes if isinstance(raw_nodes, list) else []
    node_ids = [
        str(node.get("id"))
        for node in nodes
        if isinstance(node, Mapping) and isinstance(node.get("id"), str) and node.get("id")
    ]
    namespaces = declared_namespaces(converted)
    unresolved: list[dict[str, Any]] = []

    for node in nodes:
        if not isinstance(node, dict):
            continue
        config = node.get("config")
        if not isinstance(config, dict):
            continue
        inputs_map = config.get("inputs_map")
        if not isinstance(inputs_map, dict):
            continue
        for port, selector in list(inputs_map.items()):
            if not isinstance(selector, str):
                continue
            result = dot_path_to_variable_ref(
                selector,
                node_ids=node_ids,
                variable_namespaces=namespaces,
            )
            if result.converted:
                inputs_map[port] = result.ref
            else:
                unresolved.append(
                    {
                        "node_id": node.get("id"),
                        "port": str(port),
                        "selector": selector,
                        "reason": result.reason,
                    }
                )
    return converted, unresolved
