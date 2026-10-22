"""Prove that a rejected approval has an authored, verdict-specific route.

Ordinary task continuations are approval-only. A terminal collector may retain
the verdict, and a Decision may handle refusal when its predicates are bound to
this gate and select a different route from both accepted approval statuses.
Ambiguous routing stops at the gate; this does not authorize any business effect.
"""

from __future__ import annotations

import ast
from typing import Any

from .condition import ConditionError, evaluate, validate
from .variable_pool import selector_segments

_VERDICT_FIELDS = {"approved", "rejected", "decision_status"}
_GATE_PORTS = _VERDICT_FIELDS | {"decision_id", "decided_by"}


def _predicate_names(expression: str) -> set[str]:
    validate(expression)
    names: set[str] = set()

    def visit(node: ast.AST) -> None:
        if isinstance(node, ast.Attribute):
            if not isinstance(node.value, ast.Name) or node.value.id not in {"ctx", "context"}:
                raise ConditionError("Approval routing requires gate-bound predicates")
            names.add(node.attr)
        elif isinstance(node, ast.Name):
            names.add(node.id)
        else:
            for child in ast.iter_child_nodes(node):
                visit(child)

    visit(ast.parse(expression, mode="eval"))
    return names


def _decision_handles_rejection(graph: Any, node: Any, gate_id: str) -> bool:
    config = node.config or {}
    # A second live predecessor could overwrite the verdict in overlay mode.
    if any(edge.source != gate_id for edge in graph.in_edges.get(node.id, [])):
        return False
    aliases = (
        {name: name for name in _VERDICT_FIELDS if name in (config.get("passthrough_inputs") or [])}
        if graph.strict_authoritative
        else {
            **{name: name for name in _VERDICT_FIELDS},
            "hitl_approved": "approved",
            "hitl_decision": "decision_status",
        }
    )
    inputs_map = config.get("inputs_map") or {}
    if not isinstance(inputs_map, dict):
        return False
    for name, selector in inputs_map.items():
        aliases.pop(name, None)
        segments = selector_segments(selector)
        if (
            segments
            and len(segments) == 2
            and segments[0] == gate_id
            and segments[1] in _VERDICT_FIELDS
        ):
            aliases[name] = segments[1]
    branches = config.get("branches") or []
    if not branches or any(not isinstance(branch, dict) for branch in branches):
        return False
    try:
        for branch in branches:
            if not _predicate_names(str(branch.get("condition") or "")) <= aliases.keys():
                return False
        routes: dict[str, set[str]] = {}
        rejection_condition = None
        for status in ("rejected", "accepted", "applied"):
            verdict = {
                "approved": status != "rejected",
                "rejected": status == "rejected",
                "decision_status": status,
            }
            payload = {name: verdict[field] for name, field in aliases.items()}
            selected = next(
                (branch for branch in branches if evaluate(branch["condition"], payload)), None
            )
            # An unconditional/default continuation is not a refusal route.
            if selected is None or not selected.get("label"):
                return False
            if status == "rejected":
                rejection_condition = selected["condition"]
            elif evaluate(rejection_condition, payload):
                return False
            routes[status] = {
                edge.target
                for edge in graph.out_edges.get(node.id, [])
                if edge.kind == "branch" and edge.branch_label == selected["label"]
            }
            if not routes[status]:
                return False
    except (ConditionError, TypeError, ValueError):
        return False
    return not (routes["rejected"] & (routes["accepted"] | routes["applied"]))


def has_explicit_rejection_route(graph: Any, state: Any, gate_id: str) -> bool:
    """Every live successor must safely collect or explicitly route refusal.

    Only immediate, verdict-bound Decision routes qualify. Task-mediated routing,
    foreign predicates and parallel task bypasses deliberately do not qualify.
    AgentLoop, child-run and specialized ML review gates own their separate rules.
    """
    # The proof uses the runtime verdict, not an authored overwrite of its
    # namespace (e.g. mapping rejected=True onto review.approved).
    outputs_map = graph.nodes[gate_id].config.get("outputs_map") or {}
    if not isinstance(outputs_map, dict):
        return False
    for source, target in outputs_map.items():
        segments = selector_segments(target)
        if segments and segments[0] == gate_id and segments != [gate_id, source]:
            return False
    edges = [
        edge
        for edge in graph.out_edges.get(gate_id, [])
        if (edge.source, edge.target, edge.branch_label) not in state.dead_edges
    ]
    if not edges:
        return False
    for edge in edges:
        if edge.from_port is not None and edge.from_port not in _GATE_PORTS:
            return False
        node = graph.nodes[edge.target]
        if node.kind == "sink" and not graph.out_edges.get(node.id):
            continue
        if node.kind != "decision" or not _decision_handles_rejection(graph, node, gate_id):
            return False
    return True
