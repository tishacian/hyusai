"""Structural DAG validator for custom chains (``System.flow_definition``).

Mirrors the frontend ``FlowSerializer.validateFlow`` logic
(``frontend-ng/src/app/core/flow-serializer.service.ts:681-799``) so
that what the builder previews is exactly what the backend enforces
at save time — no drift, no surprise when a saved flow fails at
execute.

E3.1 adds two checks that the frontend declared but never emitted:

- ``unreachable_node``: node unreachable from any ``source`` / entry
  node. Declared in ``FlowValidationIssue.code`` since Vague C but
  never implemented (see audit 2026-04-24).
- ``node_orphan``: node with no inbound **and** no outbound edge,
  typical leftover of a half-finished drag/drop that the builder
  forgot to wire up.

The result is a list of ``ValidationIssue`` dicts, shaped identically
to the frontend ``FlowValidationIssue`` so the editor can display
server-side errors without translating anything.

Gating policy used by ``PATCH /systems/{id}``:
    - ``level = "error"`` → save is rejected (HTTP 400 with issues
      in the response body).
    - ``level = "warn"`` → save proceeds but issues are echoed back
      in the response so the UI can flag them.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set


_CANONICAL_BUILDER_IDS: Set[str] = {
    "builder.objective",
    "builder.capability",
    "builder.skills",
    "builder.context",
    "builder.policy",
    "builder.launch",
}


@dataclass
class ValidationIssue:
    """Single diagnostic. Mirrors the frontend ``FlowValidationIssue``
    shape so responses can be rendered 1:1 in the editor.
    """

    level: str  # "error" | "warn"
    code: str
    message: str
    node_id: Optional[str] = None
    edge_index: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        return {k: v for k, v in data.items() if v is not None}


def _iter_nodes(flow: Mapping[str, Any]) -> List[Dict[str, Any]]:
    nodes = flow.get("nodes")
    return list(nodes) if isinstance(nodes, list) else []


def _iter_edges(flow: Mapping[str, Any]) -> List[Dict[str, Any]]:
    edges = flow.get("edges")
    return list(edges) if isinstance(edges, list) else []


def _node_id(node: Mapping[str, Any]) -> Optional[str]:
    nid = node.get("id")
    return nid if isinstance(nid, str) and nid else None


def _node_kind(node: Mapping[str, Any]) -> str:
    kind = node.get("kind")
    if isinstance(kind, str) and kind:
        return kind
    # Back-compat: nodes persisted before kind existed default to task.
    return "task"


def _has_cycle(adj: Mapping[str, Sequence[str]]) -> bool:
    """Iterative DFS cycle detection. We avoid recursion to survive
    runaway auto-generated graphs without hitting Python's default
    recursion limit.
    """
    WHITE, GRAY, BLACK = 0, 1, 2
    color: Dict[str, int] = {node: WHITE for node in adj}
    for start in adj:
        if color[start] != WHITE:
            continue
        stack: List[tuple] = [(start, iter(adj[start]))]
        color[start] = GRAY
        while stack:
            node, it = stack[-1]
            try:
                nxt = next(it)
            except StopIteration:
                color[node] = BLACK
                stack.pop()
                continue
            if color.get(nxt, WHITE) == GRAY:
                return True
            if color.get(nxt, WHITE) == WHITE:
                color[nxt] = GRAY
                stack.append((nxt, iter(adj.get(nxt, ()))))
    return False


def _reachable_from(
    starts: Sequence[str], adj: Mapping[str, Sequence[str]]
) -> Set[str]:
    seen: Set[str] = set()
    stack = list(starts)
    while stack:
        node = stack.pop()
        if node in seen:
            continue
        seen.add(node)
        stack.extend(adj.get(node, ()))
    return seen


def validate_flow(flow: Mapping[str, Any]) -> List[ValidationIssue]:
    """Run the full validator on ``flow_definition``. Return a list of
    issues (may be empty for a valid flow). Never raises.
    """

    issues: List[ValidationIssue] = []
    nodes = _iter_nodes(flow)
    edges = _iter_edges(flow)

    # No structural validation possible on an empty flow. We tolerate it
    # (a draft with no nodes is legitimately a valid "empty" save) and
    # return zero issues; the gate only blocks on *errors*, so saving
    # stays allowed.
    if not nodes:
        return issues

    ids = {nid for nid in (_node_id(n) for n in nodes) if nid}

    adj: Dict[str, List[str]] = {nid: [] for nid in ids}
    rev: Dict[str, List[str]] = {nid: [] for nid in ids}

    for idx, edge in enumerate(edges):
        src = edge.get("from")
        dst = edge.get("to")
        if not isinstance(src, str) or not isinstance(dst, str) or src not in ids or dst not in ids:
            issues.append(
                ValidationIssue(
                    level="error",
                    code="dangling_edge",
                    message=f"Edge {src!r} → {dst!r} references unknown node(s).",
                    edge_index=idx,
                )
            )
            continue
        adj[src].append(dst)
        rev[dst].append(src)

    fork_count = 0
    join_count = 0

    for node in nodes:
        nid = _node_id(node)
        if not nid:
            continue
        kind = _node_kind(node)
        cfg = node.get("config") or {}
        if not isinstance(cfg, Mapping):
            cfg = {}

        if kind == "fork":
            fork_count += 1
        elif kind == "join":
            join_count += 1

        if kind == "task":
            skill_id = cfg.get("skill_id")
            skill_slug = cfg.get("skill_slug")
            runtime_ref = cfg.get("runtime_ref")
            has_skill = (
                isinstance(skill_id, str)
                and skill_id
                or isinstance(skill_slug, str)
                and skill_slug
            )
            has_runtime_ref = isinstance(runtime_ref, str) and bool(runtime_ref.strip())
            is_builder_node = nid in _CANONICAL_BUILDER_IDS
            if not has_skill and not has_runtime_ref and not is_builder_node:
                issues.append(
                    ValidationIssue(
                        level="warn",
                        code="task_no_skill",
                        message=f"Task node {node.get('label') or nid!r} has no Skill bound.",
                        node_id=nid,
                    )
                )
        elif kind == "decision":
            branches = cfg.get("branches")
            if not isinstance(branches, list) or len(branches) < 2:
                issues.append(
                    ValidationIssue(
                        level="error",
                        code="decision_no_branches",
                        message=f"Decision {node.get('label') or nid!r} needs at least two branches.",
                        node_id=nid,
                    )
                )
        elif kind == "loop":
            budget = cfg.get("max_iterations")
            if not isinstance(budget, (int, float)) or budget <= 0:
                issues.append(
                    ValidationIssue(
                        level="error",
                        code="loop_no_budget",
                        message=f"Loop {node.get('label') or nid!r} is missing a positive max_iterations budget.",
                        node_id=nid,
                    )
                )
        elif kind == "retry":
            attempts = cfg.get("max_attempts")
            if not isinstance(attempts, (int, float)) or attempts <= 0:
                issues.append(
                    ValidationIssue(
                        level="error",
                        code="retry_no_target",
                        message=f"Retry {node.get('label') or nid!r} is missing a positive max_attempts.",
                        node_id=nid,
                    )
                )
        elif kind == "hitl":
            prompt = cfg.get("prompt")
            if not isinstance(prompt, str) or not prompt.strip():
                issues.append(
                    ValidationIssue(
                        level="warn",
                        code="hitl_no_prompt",
                        message=f"HITL {node.get('label') or nid!r} should include an approver prompt.",
                        node_id=nid,
                    )
                )

    if join_count > 0 and fork_count == 0:
        issues.append(
            ValidationIssue(
                level="warn",
                code="join_without_fork",
                message="Flow has join node(s) but no fork — join will degenerate to passthrough.",
            )
        )
    if fork_count > 0 and join_count == 0:
        issues.append(
            ValidationIssue(
                level="warn",
                code="fork_without_join",
                message="Flow has fork node(s) but no join — branches may race to the sink.",
            )
        )

    # Cycle detection. Run against the purified adjacency (dangling
    # edges have already been filtered out above) so the diagnostic
    # doesn't fire spuriously on a graph whose only "cycle" is a
    # broken edge.
    if _has_cycle(adj):
        issues.append(
            ValidationIssue(
                level="error",
                code="cycle_detected",
                message="Flow contains a cycle outside a loop node. Use a loop kind for controlled iteration.",
            )
        )

    # Reachability from entry nodes. We treat a node as an entry if
    # its kind is ``source`` OR it has zero inbound edges (common for
    # task-based chains that omit an explicit source). Unreachable
    # nodes can't fire at runtime and are almost always a wiring
    # mistake from a drag-and-drop left dangling.
    entries: List[str] = []
    for node in nodes:
        nid = _node_id(node)
        if not nid:
            continue
        if _node_kind(node) == "source" or not rev.get(nid):
            entries.append(nid)

    if entries:
        reachable = _reachable_from(entries, adj)
        for node in nodes:
            nid = _node_id(node)
            if not nid:
                continue
            if nid not in reachable:
                issues.append(
                    ValidationIssue(
                        level="error",
                        code="unreachable_node",
                        message=f"Node {node.get('label') or nid!r} is unreachable from any entry point.",
                        node_id=nid,
                    )
                )

    # Orphan detection. An orphan has zero inbound + zero outbound
    # edges *and* is not the only node (a chain of one is legitimately
    # a draft). Unreachable misses this case because orphans are
    # themselves entry points (zero inbound) so they show up in their
    # own reachable set and escape the previous loop.
    if len(nodes) >= 2:
        for node in nodes:
            nid = _node_id(node)
            if not nid:
                continue
            if not adj.get(nid) and not rev.get(nid):
                issues.append(
                    ValidationIssue(
                        level="error",
                        code="node_orphan",
                        message=f"Node {node.get('label') or nid!r} is disconnected (no inbound nor outbound edge).",
                        node_id=nid,
                    )
                )

    return issues


def has_errors(issues: Sequence[ValidationIssue]) -> bool:
    return any(i.level == "error" for i in issues)


def issues_to_payload(issues: Sequence[ValidationIssue]) -> List[Dict[str, Any]]:
    return [i.to_dict() for i in issues]
