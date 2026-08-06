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

P0 (variable-membrane / schema_version 3) adds two warn-level checks,
also declared on the frontend and emitted here in lockstep:

- ``port_type_mismatch``: a ``kind='data'`` edge whose ``from_port`` /
  ``to_port`` reference declared ports with incompatible primitive
  schemas.
- ``variable_unresolved``: a ``config.inputs_map`` typed ``VariableRef``
  (``{node_id, path}``) pointing at a node_id/port that is neither a
  reserved namespace nor present upstream. Legacy dot-path strings are
  left untouched (resolved by the run engine, not the graph).

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

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set

from app.services.chains.variable_contract import (
    declared_namespaces,
    dot_path_to_variable_ref,
)
from app.services.flow_graph_identity import edge_identity
from app.services.flow_skill_binding import (
    FlowSkillBindingError,
    resolve_flow_skill_binding,
)
from app.services.run_engine.condition import ConditionError
from app.services.run_engine.condition import validate as validate_condition
from app.services.run_engine.variable_pool import (
    RESERVED_NAMESPACES,
    variable_ref_validation_error,
)

_CANONICAL_BUILDER_IDS: Set[str] = {
    "builder.objective",
    "builder.capability",
    "builder.skills",
    "builder.context",
    "builder.policy",
    "builder.launch",
}
_BUILTIN_RUNTIME_REFS: Set[str] = {"builtin:passthrough"}
_INGRESS_KINDS: Set[str] = {"manual", "chat", "http", "schedule", "event"}


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


def validate_flow_shape(flow: Any) -> List[ValidationIssue]:
    """Validate the JSON container shape required by every graph consumer.

    Drafts may be topologically incomplete while they are being authored, but
    they must never persist values that the validator, compiler and walker
    interpret differently.  This deliberately narrow pass rejects malformed
    containers and elements without imposing the full executable-graph rules.
    """

    if not isinstance(flow, Mapping):
        return [
            ValidationIssue(
                level="error",
                code="flow_invalid",
                message="Flow definition must be a JSON object.",
            )
        ]

    issues: List[ValidationIssue] = []
    raw_nodes = flow.get("nodes", [])
    if not isinstance(raw_nodes, list):
        issues.append(
            ValidationIssue(
                level="error",
                code="nodes_invalid",
                message="Flow nodes must be a JSON array when present.",
            )
        )
    else:
        for index, node in enumerate(raw_nodes):
            if not isinstance(node, Mapping):
                issues.append(
                    ValidationIssue(
                        level="error",
                        code="node_invalid",
                        message=f"Flow node at index {index} must be a JSON object.",
                    )
                )
                continue
            node_id = node.get("id")
            invalid_fields: List[str] = []
            if (
                not isinstance(node_id, str)
                or not node_id.strip()
                or node_id != node_id.strip()
            ):
                invalid_fields.append("a non-empty, already-trimmed string id")
            for field in ("config", "data"):
                value = node.get(field)
                if value is not None and not isinstance(value, Mapping):
                    invalid_fields.append(f"an object-valued {field}")
            for field in ("inputs", "outputs"):
                value = node.get(field)
                if value is not None and not isinstance(value, list):
                    invalid_fields.append(f"an array-valued {field}")
            if invalid_fields:
                issues.append(
                    ValidationIssue(
                        level="error",
                        code="node_invalid",
                        message=(
                            f"Flow node at index {index} must declare "
                            + ", ".join(invalid_fields)
                            + "."
                        ),
                        node_id=(
                            node_id
                            if isinstance(node_id, str) and node_id.strip() == node_id
                            else None
                        ),
                    )
                )

    raw_edges = flow.get("edges", [])
    if not isinstance(raw_edges, list):
        issues.append(
            ValidationIssue(
                level="error",
                code="edges_invalid",
                message="Flow edges must be a JSON array when present.",
            )
        )
    else:
        for index, edge in enumerate(raw_edges):
            if not isinstance(edge, Mapping):
                issues.append(
                    ValidationIssue(
                        level="error",
                        code="edge_invalid",
                        message=f"Flow edge at index {index} must be a JSON object.",
                        edge_index=index,
                    )
                )
                continue
            source = edge.get("from") if "from" in edge else edge.get("source")
            target = edge.get("to") if "to" in edge else edge.get("target")
            malformed_endpoint = any(
                not isinstance(endpoint, str)
                or not endpoint.strip()
                or endpoint != endpoint.strip()
                for endpoint in (source, target)
            )
            if malformed_endpoint:
                issues.append(
                    ValidationIssue(
                        level="error",
                        code="edge_invalid",
                        message=(
                            f"Flow edge at index {index} must use non-empty, "
                            "already-trimmed string endpoints."
                        ),
                        edge_index=index,
                    )
                )
    return issues


def _node_id(node: Mapping[str, Any]) -> Optional[str]:
    nid = node.get("id")
    return nid if isinstance(nid, str) and nid else None


def _node_kind(node: Mapping[str, Any]) -> str:
    kind = node.get("kind")
    if isinstance(kind, str) and kind:
        return kind
    # Back-compat: nodes persisted before kind existed default to task.
    return "task"


def _is_declarative_source_node(node: Mapping[str, Any]) -> bool:
    """True for declarative source/asset nodes (Phase 1 Flow Builder sources).

    These sit UPSTREAM of the real entry (``asset.collection`` naming a
    collection, ``source.sftp_arrival`` naming a trigger) and are purely
    declarative — the run engine ignores them. They may legitimately be left
    unwired while authoring, so they are exempted from the ``unreachable_node``
    / ``node_orphan`` ERRORS that would otherwise block a save. Matches the
    ``asset`` kind and any typed ``source.*`` node (e.g. ``source.sftp_arrival``,
    ``source.collection``) — never the plain chat/request entry (``type:input``).
    """
    if _node_kind(node) == "asset":
        return True
    node_type = node.get("type")
    return isinstance(node_type, str) and node_type.startswith("source.")


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


def _reachable_from(starts: Sequence[str], adj: Mapping[str, Sequence[str]]) -> Set[str]:
    seen: Set[str] = set()
    stack = list(starts)
    while stack:
        node = stack.pop()
        if node in seen:
            continue
        seen.add(node)
        stack.extend(adj.get(node, ()))
    return seen


# --- v3 variable-membrane helpers (kept in lockstep with the frontend
# ``FlowSerializer.validateFlow``: same codes, same warn level, same
# semantics). -------------------------------------------------------------
_PRIMITIVE_SCHEMAS: Set[str] = {
    "string",
    "number",
    "integer",
    "boolean",
    "object",
    "array",
}

# Reserved variable namespaces that resolve outside the node graph
# (mirror of ``RESERVED_VARIABLE_NAMESPACES`` on the frontend).
_RESERVED_VARIABLE_NAMESPACES: Set[str] = set(RESERVED_NAMESPACES)


def _ports(node: Mapping[str, Any], key: str) -> Dict[str, Optional[str]]:
    """Map declared port name → primitive schema (or ``None``)."""
    out: Dict[str, Optional[str]] = {}
    raw = node.get(key)
    if isinstance(raw, list):
        for port in raw:
            if isinstance(port, Mapping):
                name = port.get("name")
                schema = port.get("schema")
                if isinstance(name, str) and name:
                    out[name] = schema if isinstance(schema, str) else None
    return out


def _primitives_incompatible(a: Optional[str], b: Optional[str]) -> bool:
    """True only when BOTH schemas are known primitives and incompatible.
    Unknown / ``ref:``-style schemas are not comparable. ``number`` and
    ``integer`` are treated as compatible.
    """
    if a not in _PRIMITIVE_SCHEMAS or b not in _PRIMITIVE_SCHEMAS:
        return False
    if a == b:
        return False
    numeric = {"number", "integer"}
    if a in numeric and b in numeric:
        return False
    return True


def _ancestors(node_id: str, rev: Mapping[str, Sequence[str]]) -> Set[str]:
    """Backward-reachable set (ancestors) over the purified reverse edges."""
    seen: Set[str] = set()
    stack = list(rev.get(node_id, ()))
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        stack.extend(rev.get(cur, ()))
    return seen


def _is_variable_ref(value: Any) -> bool:
    """Return whether a value satisfies the complete typed v3 contract."""
    return variable_ref_validation_error(value) is None


def _edge_branch_label(edge: Mapping[str, Any]) -> Optional[str]:
    """Return the canonical branch label, accepting the legacy ``label`` key."""
    raw = edge.get("branch_label")
    if raw is None:
        raw = edge.get("label")
    return raw.strip() if isinstance(raw, str) and raw.strip() else None


def _decision_contract_issues(
    *,
    node: Mapping[str, Any],
    node_id: str,
    config: Mapping[str, Any],
    outgoing_edges: Sequence[tuple[int, Mapping[str, Any]]],
) -> List[ValidationIssue]:
    """Validate Decision branches and their route edges as one contract."""
    issues: List[ValidationIssue] = []
    raw_branches = config.get("branches")
    if not isinstance(raw_branches, list) or len(raw_branches) < 2:
        return [
            ValidationIssue(
                level="error",
                code="decision_no_branches",
                message=f"Decision {node.get('label') or node_id!r} needs at least two branches.",
                node_id=node_id,
            )
        ]

    labels: List[str] = []
    for branch_index, branch in enumerate(raw_branches):
        if not isinstance(branch, Mapping):
            issues.append(
                ValidationIssue(
                    level="error",
                    code="decision_branch_invalid",
                    message=f"Decision branch {branch_index + 1} must be an object.",
                    node_id=node_id,
                )
            )
            continue
        raw_label = branch.get("label")
        label = raw_label.strip() if isinstance(raw_label, str) else ""
        if not label or label != raw_label:
            issues.append(
                ValidationIssue(
                    level="error",
                    code="decision_branch_invalid",
                    message=(
                        f"Decision branch {branch_index + 1} needs a non-empty, "
                        "already-trimmed label."
                    ),
                    node_id=node_id,
                )
            )
        else:
            labels.append(label)

        expression = branch.get("condition")
        if not isinstance(expression, str) or not expression.strip():
            issues.append(
                ValidationIssue(
                    level="error",
                    code="decision_condition_invalid",
                    message=f"Decision branch {label or branch_index + 1!r} needs a condition.",
                    node_id=node_id,
                )
            )
        else:
            try:
                validate_condition(expression)
            except ConditionError as exc:
                issues.append(
                    ValidationIssue(
                        level="error",
                        code="decision_condition_invalid",
                        message=(
                            f"Decision branch {label or branch_index + 1!r} has an "
                            f"invalid condition: {exc}."
                        ),
                        node_id=node_id,
                    )
                )

    duplicate_labels = sorted({label for label in labels if labels.count(label) > 1})
    if duplicate_labels:
        issues.append(
            ValidationIssue(
                level="error",
                code="decision_branch_duplicate",
                message="Decision branch labels must be unique: " + ", ".join(duplicate_labels),
                node_id=node_id,
            )
        )

    default_branch = config.get("default_branch")
    if default_branch is not None and (
        not isinstance(default_branch, str)
        or not default_branch.strip()
        or default_branch not in labels
    ):
        issues.append(
            ValidationIssue(
                level="error",
                code="decision_default_invalid",
                message="Decision default_branch must reference an existing branch label.",
                node_id=node_id,
            )
        )

    routed_labels = {
        label
        for _, edge in outgoing_edges
        if str(edge.get("kind") or "data") == "branch"
        for label in [_edge_branch_label(edge)]
        if label is not None
    }
    for label in sorted(set(labels) - routed_labels):
        issues.append(
            ValidationIssue(
                level="error",
                code="decision_branch_unwired",
                message=f"Decision branch {label!r} has no outgoing branch edge.",
                node_id=node_id,
            )
        )

    return issues


def _distances_from(
    start: str,
    adj: Mapping[str, Sequence[str]],
) -> Dict[str, int]:
    distances = {start: 0}
    queue = [start]
    while queue:
        current = queue.pop(0)
        for nxt in adj.get(current, ()):
            if nxt in distances:
                continue
            distances[nxt] = distances[current] + 1
            queue.append(nxt)
    return distances


def _lane_bypasses_join(
    start: str,
    join_id: str,
    adj: Mapping[str, Sequence[str]],
) -> bool:
    """Whether a lane can reach a real terminal without crossing ``join_id``."""
    seen: Set[str] = set()
    stack = [start]
    while stack:
        current = stack.pop()
        if current == join_id or current in seen:
            continue
        seen.add(current)
        outgoing = adj.get(current, ())
        if not outgoing:
            return True
        stack.extend(nxt for nxt in outgoing if nxt != join_id)
    return False


def _fork_join_topology_issues(
    *,
    nodes: Sequence[Mapping[str, Any]],
    edges: Sequence[Mapping[str, Any]],
    adj: Mapping[str, Sequence[str]],
    rev: Mapping[str, Sequence[str]],
    strict: bool,
) -> List[ValidationIssue]:
    """Pair forks with real reconverging joins instead of balancing counts."""
    issues: List[ValidationIssue] = []
    level = "error" if strict else "warn"
    nodes_by_id = {nid: node for node in nodes for nid in [_node_id(node)] if nid is not None}
    forks = sorted(nid for nid, node in nodes_by_id.items() if _node_kind(node) == "fork")
    joins = sorted(nid for nid, node in nodes_by_id.items() if _node_kind(node) == "join")
    matched_joins: Set[str] = set()

    for join_id in joins:
        strategy = str(
            ((nodes_by_id[join_id].get("config") or {}).get("strategy") or "all")
        ).lower()
        if strategy not in {"all", "any", "race"}:
            issues.append(
                ValidationIssue(
                    level=level,
                    code="join_strategy_invalid",
                    message=f"Join {join_id!r} has unsupported strategy {strategy!r}.",
                    node_id=join_id,
                )
            )
        if len(set(rev.get(join_id, ()))) < 2:
            issues.append(
                ValidationIssue(
                    level=level,
                    code="join_fanin_invalid",
                    message=f"Join {join_id!r} needs at least two distinct inbound lanes.",
                    node_id=join_id,
                )
            )

    for fork_id in forks:
        outgoing = [edge for edge in edges if edge.get("from") == fork_id]
        lanes = sorted(
            {str(edge.get("to")) for edge in outgoing if isinstance(edge.get("to"), str)}
        )
        if len(lanes) < 2:
            issues.append(
                ValidationIssue(
                    level=level,
                    code="fork_fanout_invalid",
                    message=f"Fork {fork_id!r} needs at least two distinct outgoing lanes.",
                    node_id=fork_id,
                )
            )

        config = nodes_by_id[fork_id].get("config") or {}
        expected_raw = config.get("branches") if isinstance(config, Mapping) else None
        expected = (
            [item.strip() for item in expected_raw if isinstance(item, str) and item.strip()]
            if isinstance(expected_raw, list)
            else []
        )
        observed = [
            _edge_branch_label(edge)
            or (edge.get("from_port").strip() if isinstance(edge.get("from_port"), str) else None)
            for edge in outgoing
        ]
        if (
            len(expected) < 2
            or len(set(expected)) != len(expected)
            or any(label is None for label in observed)
            or set(label for label in observed if label is not None) != set(expected)
        ):
            issues.append(
                ValidationIssue(
                    level=level,
                    code="branch_label_invalid",
                    message=(
                        f"Fork {fork_id!r} route labels must be unique and match "
                        "config.branches."
                    ),
                    node_id=fork_id,
                )
            )

        if len(lanes) < 2:
            continue
        lane_distances = [_distances_from(lane, adj) for lane in lanes]
        candidates = [
            join_id
            for join_id in joins
            if all(join_id in distances for distances in lane_distances)
        ]
        if candidates:
            candidates.sort(
                key=lambda join_id: (
                    max(distances[join_id] for distances in lane_distances),
                    sum(distances[join_id] for distances in lane_distances),
                    join_id,
                )
            )
            candidate = candidates[0]
            if not any(_lane_bypasses_join(lane, candidate, adj) for lane in lanes):
                matched_joins.add(candidate)
                continue
        issues.append(
            ValidationIssue(
                level=level,
                code="fork_unjoined",
                message=(
                    f"Fork {fork_id!r} has no join that reconverges and "
                    "post-dominates every lane."
                ),
                node_id=fork_id,
            )
        )

    for join_id in joins:
        if join_id not in matched_joins:
            issues.append(
                ValidationIssue(
                    level=level,
                    code="join_without_matching_fork",
                    message=f"Join {join_id!r} is not paired with a real upstream fork.",
                    node_id=join_id,
                )
            )
    return issues


def validate_flow(flow: Mapping[str, Any]) -> List[ValidationIssue]:
    """Run the full validator on ``flow_definition``. Return a list of
    issues (may be empty for a valid flow). Never raises.
    """

    issues = validate_flow_shape(flow)
    if issues:
        # Structural corruption makes every graph map and topology diagnostic
        # ambiguous.  Return all shape findings, but never continue into code
        # which assumes object-valued nodes/edges.
        return issues
    nodes = _iter_nodes(flow)
    edges = _iter_edges(flow)

    raw_io_mode = flow.get("io_mode")
    strict = raw_io_mode == "strict"
    try:
        schema_version = int(flow.get("schema_version") or 0)
    except (OverflowError, TypeError, ValueError):
        schema_version = 0
    if raw_io_mode is not None and (
        not isinstance(raw_io_mode, str)
        or raw_io_mode not in {"overlay", "strict"}
    ):
        issues.append(
            ValidationIssue(
                level="error",
                code="variable_contract_invalid",
                message="io_mode must be 'overlay' or 'strict'.",
            )
        )
    if strict and schema_version < 3:
        issues.append(
            ValidationIssue(
                level="error",
                code="variable_contract_invalid",
                message="io_mode 'strict' requires schema_version >= 3.",
            )
        )
    namespaces = declared_namespaces(flow)
    raw_namespaces = flow.get("variable_namespaces")
    if raw_namespaces is not None and (
        not isinstance(raw_namespaces, list)
        or any(not isinstance(item, str) or not item.strip() for item in raw_namespaces)
    ):
        issues.append(
            ValidationIssue(
                level="error",
                code="variable_contract_invalid",
                message="variable_namespaces must be a list of non-empty strings.",
            )
        )
    reserved_redeclarations = sorted(namespaces & _RESERVED_VARIABLE_NAMESPACES)
    if reserved_redeclarations:
        issues.append(
            ValidationIssue(
                level="error",
                code="variable_contract_invalid",
                message=(
                    "Built-in namespace(s) cannot be redeclared: "
                    + ", ".join(reserved_redeclarations)
                ),
            )
        )

    # Graph maps are keyed by node id and structural edge identity at runtime.
    # Reject collisions before building those maps: continuing would silently
    # overwrite a node or count the same route twice and make every subsequent
    # topology diagnostic ambiguous.
    node_id_counts = Counter(
        node.get("id")
        for node in nodes
        if isinstance(node, Mapping) and isinstance(node.get("id"), str)
    )
    for node_id in sorted(node_id for node_id, count in node_id_counts.items() if count > 1):
        issues.append(
            ValidationIssue(
                level="error",
                code="node_id_duplicate",
                message=(
                    f"Node id {node_id!r} is declared {node_id_counts[node_id]} times; "
                    "node ids must be unique."
                ),
                node_id=node_id,
            )
        )

    edge_indices: dict[str, list[int]] = defaultdict(list)
    for edge_index, edge in enumerate(edges):
        if isinstance(edge, Mapping):
            edge_indices[edge_identity(edge)].append(edge_index)
    for identity in sorted(edge_indices):
        duplicate_indices = edge_indices[identity]
        if len(duplicate_indices) < 2:
            continue
        for edge_index in duplicate_indices[1:]:
            issues.append(
                ValidationIssue(
                    level="error",
                    code="edge_duplicate",
                    message="This route duplicates an earlier edge structurally.",
                    edge_index=edge_index,
                )
            )

    if any(issue.code in {"node_id_duplicate", "edge_duplicate"} for issue in issues):
        return issues

    if strict:
        sink_ids = sorted(
            nid
            for node in nodes
            for nid in [_node_id(node)]
            if nid is not None and _node_kind(node) == "sink"
        )
        if not sink_ids:
            issues.append(
                ValidationIssue(
                    level="error",
                    code="flow_output_sink_required",
                    message="A strict Flow must declare exactly one explicit sink node.",
                )
            )
        elif len(sink_ids) > 1:
            issues.append(
                ValidationIssue(
                    level="error",
                    code="flow_output_sink_ambiguous",
                    message=(
                        "A strict Flow must declare exactly one explicit sink node; "
                        f"found {len(sink_ids)} ({', '.join(sink_ids)})."
                    ),
                )
            )

    # No structural validation possible on an empty flow. We tolerate it
    # in overlay mode (a draft with no nodes is legitimately an empty save).
    # Strict mode has already emitted its required-sink error above.
    if not nodes:
        return issues

    ids = {nid for nid in (_node_id(n) for n in nodes) if nid}
    nodes_by_id: Dict[str, Mapping[str, Any]] = {
        nid: node for node in nodes for nid in [_node_id(node)] if nid is not None
    }

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

    for node in nodes:
        nid = _node_id(node)
        if not nid:
            continue
        kind = _node_kind(node)
        cfg = node.get("config") or {}
        if not isinstance(cfg, Mapping):
            cfg = {}
        if "ingress_kind" in cfg:
            ingress_kind = cfg.get("ingress_kind")
            if not isinstance(ingress_kind, str) or ingress_kind not in _INGRESS_KINDS:
                issues.append(
                    ValidationIssue(
                        level="error",
                        code="ingress_kind_invalid",
                        message="Ingress kind must be manual, chat, http, schedule or event.",
                        node_id=nid,
                    )
                )
            elif kind != "source":
                issues.append(
                    ValidationIssue(
                        level="error",
                        code="ingress_node_kind_invalid",
                        message="Only a source node can declare an ingress kind.",
                        node_id=nid,
                    )
                )
        if kind == "source" and rev.get(nid):
            issues.append(
                ValidationIssue(
                    level="error",
                    code="ingress_source_not_root",
                    message="An executable ingress source cannot have inbound edges.",
                    node_id=nid,
                )
            )
        binding_error = False
        try:
            skill_binding = resolve_flow_skill_binding(node)
        except FlowSkillBindingError as exc:
            binding_error = True
            skill_binding = None
            issues.append(
                ValidationIssue(
                    level="error",
                    code=exc.code,
                    message=f"{exc.message} Node {node.get('label') or nid!r}.",
                    node_id=nid,
                )
            )

        if kind == "task":
            runtime_ref = cfg.get("runtime_ref")
            has_skill = bool(skill_binding and skill_binding.skill_slug)
            has_runtime_ref = isinstance(runtime_ref, str) and bool(runtime_ref.strip())
            is_builder_node = nid in _CANONICAL_BUILDER_IDS
            if (
                has_runtime_ref
                and str(runtime_ref).startswith("builtin:")
                and runtime_ref not in _BUILTIN_RUNTIME_REFS
            ):
                issues.append(
                    ValidationIssue(
                        level="error",
                        code="task_runtime_ref_invalid",
                        message=f"Task {node.get('label') or nid!r} uses an unknown builtin runtime_ref.",
                        node_id=nid,
                    )
                )
            if not binding_error and not has_skill and not has_runtime_ref and not is_builder_node:
                issues.append(
                    ValidationIssue(
                        level="warn",
                        code="task_no_skill",
                        message=f"Task node {node.get('label') or nid!r} has no Skill bound.",
                        node_id=nid,
                    )
                )
        elif kind == "decision":
            outgoing = [(idx, edge) for idx, edge in enumerate(edges) if edge.get("from") == nid]
            issues.extend(
                _decision_contract_issues(
                    node=node,
                    node_id=nid,
                    config=cfg,
                    outgoing_edges=outgoing,
                )
            )
        elif kind == "loop":
            budget = cfg.get("max_iterations")
            if not isinstance(budget, int) or isinstance(budget, bool) or budget <= 0:
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
            if not isinstance(attempts, int) or isinstance(attempts, bool) or attempts <= 0:
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
        elif kind == "asset":
            collection_slug = cfg.get("collection_slug")
            if not isinstance(collection_slug, str) or not collection_slug.strip():
                issues.append(
                    ValidationIssue(
                        level="warn",
                        code="asset_no_collection",
                        message=f"Asset {node.get('label') or nid!r} declares no collection_slug.",
                        node_id=nid,
                    )
                )

    # A branch edge is a routing primitive owned by a Decision. Validate it
    # independently so malformed edges are diagnosed even when the source
    # Decision contract itself is otherwise valid.
    for idx, edge in enumerate(edges):
        if str(edge.get("kind") or "data") != "branch":
            continue
        source = nodes_by_id.get(edge.get("from"))
        source_id = _node_id(source or {})
        label = _edge_branch_label(edge)
        branches = (
            ((source or {}).get("config") or {}).get("branches")
            if isinstance((source or {}).get("config") or {}, Mapping)
            else None
        )
        declared = {
            branch.get("label")
            for branch in branches or []
            if isinstance(branch, Mapping) and isinstance(branch.get("label"), str)
        }
        if source is None or _node_kind(source) != "decision" or label not in declared:
            issues.append(
                ValidationIssue(
                    level="error",
                    code="branch_edge_invalid",
                    message=(
                        "Branch edges must originate from a Decision and carry "
                        "one of its declared branch labels."
                    ),
                    node_id=source_id,
                    edge_index=idx,
                )
            )

    # Cycle detection. Run against the purified adjacency (dangling
    # edges have already been filtered out above) so the diagnostic
    # doesn't fire spuriously on a graph whose only "cycle" is a
    # broken edge.
    has_cycle = _has_cycle(adj)
    if has_cycle:
        issues.append(
            ValidationIssue(
                level="error",
                code="cycle_detected",
                message="Flow contains a cycle outside a loop node. Use a loop kind for controlled iteration.",
            )
        )
    else:
        issues.extend(
            _fork_join_topology_issues(
                nodes=nodes,
                edges=edges,
                adj=adj,
                rev=rev,
                strict=strict,
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
            # Declarative source/asset nodes sit upstream of the entry and may be
            # left unwired — never block a save on their reachability.
            if _is_declarative_source_node(node):
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
            # A declarative source/asset dropped on the canvas but not yet wired
            # is a legitimate authoring state, not a broken graph — do not error.
            if _is_declarative_source_node(node):
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

    # --- v3 data-membrane diagnostics (warn level; never block a save) ---
    # port_type_mismatch: a kind='data' edge whose from_port/to_port
    # reference declared ports with incompatible *primitive* schemas.
    for idx, edge in enumerate(edges):
        if str(edge.get("kind") or "data") != "data":
            continue
        from_port = edge.get("from_port")
        to_port = edge.get("to_port")
        if not isinstance(from_port, str) or not isinstance(to_port, str):
            continue
        src = nodes_by_id.get(edge.get("from"))
        dst = nodes_by_id.get(edge.get("to"))
        if src is None or dst is None:
            continue  # already reported as dangling_edge
        out_schema = _ports(src, "outputs").get(from_port)
        in_schema = _ports(dst, "inputs").get(to_port)
        if out_schema is None or in_schema is None:
            continue  # can't compare undeclared ports
        if _primitives_incompatible(out_schema, in_schema):
            issues.append(
                ValidationIssue(
                    level="warn",
                    code="port_type_mismatch",
                    message=(
                        f"Edge {edge.get('from')}.{from_port} ({out_schema}) → "
                        f"{edge.get('to')}.{to_port} ({in_schema}) connects incompatible types."
                    ),
                    edge_index=idx,
                )
            )

    # variable_unresolved: a config.inputs_map VariableRef points at a
    # node_id/port not present upstream. Legacy dot-path strings skipped.
    for node in nodes:
        nid = _node_id(node)
        if not nid:
            continue
        cfg = node.get("config") or {}
        if not isinstance(cfg, Mapping):
            continue
        inputs_map = cfg.get("inputs_map")
        if not isinstance(inputs_map, Mapping):
            inputs_map = {}
        ancestors: Optional[Set[str]] = None
        for port, raw in inputs_map.items():
            if isinstance(raw, str) and strict:
                conversion = dot_path_to_variable_ref(
                    raw,
                    node_ids=[item for item in ids],
                    variable_namespaces=namespaces,
                )
                if not conversion.converted:
                    issues.append(
                        ValidationIssue(
                            level="error",
                            code="variable_unresolved",
                            message=(
                                f"Input {port!r} selector {raw!r} has no unambiguous "
                                f"owner ({conversion.reason})."
                            ),
                            node_id=nid,
                        )
                    )
                    continue
                raw = conversion.ref
            ref_candidate = isinstance(raw, Mapping) and any(
                key in raw for key in ("node_id", "path", "required")
            )
            ref_error = variable_ref_validation_error(raw) if ref_candidate else None
            if ref_error is not None:
                issues.append(
                    ValidationIssue(
                        level="error" if strict else "warn",
                        code="variable_contract_invalid",
                        message=f"Input {port!r} has an invalid VariableRef ({ref_error}).",
                        node_id=nid,
                    )
                )
                continue
            if not _is_variable_ref(raw):
                if strict:
                    issues.append(
                        ValidationIssue(
                            level="error",
                            code="variable_unresolved",
                            message=f"Input {port!r} must be a VariableRef in strict mode.",
                            node_id=nid,
                        )
                    )
                continue
            ref_node = raw.get("node_id")
            path = raw.get("path") or []
            if ref_node in _RESERVED_VARIABLE_NAMESPACES:
                continue
            if ref_node in namespaces:
                continue
            if ref_node not in ids:
                issues.append(
                    ValidationIssue(
                        level="error" if strict else "warn",
                        code="variable_unresolved",
                        message=f"Input {port!r} references unknown node {ref_node!r}.",
                        node_id=nid,
                    )
                )
                continue
            if ancestors is None:
                ancestors = _ancestors(nid, rev)
            if ref_node not in ancestors:
                issues.append(
                    ValidationIssue(
                        level="error" if strict else "warn",
                        code="variable_unresolved",
                        message=f"Input {port!r} reads from {ref_node!r}, which is not upstream of {nid!r}.",
                        node_id=nid,
                    )
                )
                continue
            src_outputs = _ports(nodes_by_id.get(ref_node, {}), "outputs")
            head = path[0] if path else None
            if src_outputs and head and head not in src_outputs:
                issues.append(
                    ValidationIssue(
                        level="error" if strict else "warn",
                        code="variable_unresolved",
                        message=f"Input {port!r} reads port {head!r} not declared on {ref_node!r}.",
                        node_id=nid,
                    )
                )

        if strict:
            passthrough = cfg.get("passthrough_inputs")
            if passthrough is not None and (
                not isinstance(passthrough, list)
                or any(not isinstance(item, str) or not item for item in passthrough)
            ):
                issues.append(
                    ValidationIssue(
                        level="error",
                        code="variable_contract_invalid",
                        message="passthrough_inputs must be a list of input field names.",
                        node_id=nid,
                    )
                )

            outputs_map = cfg.get("outputs_map")
            if isinstance(outputs_map, Mapping):
                for output_port, target in outputs_map.items():
                    if not isinstance(target, str) or not target.strip():
                        issues.append(
                            ValidationIssue(
                                level="error",
                                code="variable_contract_invalid",
                                message=f"Output {output_port!r} has an invalid target.",
                                node_id=nid,
                            )
                        )
                        continue
                    head = target.split(".", 1)[0]
                    if head not in namespaces:
                        issues.append(
                            ValidationIssue(
                                level="error",
                                code="variable_contract_invalid",
                                message=(
                                    f"Output {output_port!r} writes undeclared logical "
                                    f"namespace {head!r}."
                                ),
                                node_id=nid,
                            )
                        )

    # asset_binding_mismatch (warn): a retrieval ``task`` fed by an ``asset`` node
    # via a data edge but whose ``inputs_map.collection`` VariableRef points at a
    # DIFFERENT node — an incoherent authoritative binding (Phase 2). Structural
    # only (the run engine still gates the binding by flag); keep it a warning so
    # the editor surfaces the drift without blocking a save.
    asset_ids = {nid for nid, node in nodes_by_id.items() if _node_kind(node) == "asset"}
    if asset_ids:
        asset_sources_by_target: Dict[str, Set[str]] = {}
        for edge in edges:
            src = edge.get("from")
            dst = edge.get("to")
            if src in asset_ids and isinstance(dst, str):
                asset_sources_by_target.setdefault(dst, set()).add(src)
        for node in nodes:
            nid = _node_id(node)
            if not nid or _node_kind(node) != "task":
                continue
            feeding_assets = asset_sources_by_target.get(nid)
            if not feeding_assets:
                continue
            cfg = node.get("config") or {}
            if not isinstance(cfg, Mapping):
                continue
            inputs_map = cfg.get("inputs_map")
            if not isinstance(inputs_map, Mapping):
                continue
            coll_ref = inputs_map.get("collection")
            if not _is_variable_ref(coll_ref):
                continue
            ref_node = coll_ref.get("node_id")
            if ref_node not in feeding_assets:
                issues.append(
                    ValidationIssue(
                        level="warn",
                        code="asset_binding_mismatch",
                        message=(
                            f"Task {node.get('label') or nid!r} binds collection from "
                            f"{ref_node!r} but is fed by asset node(s) "
                            f"{sorted(feeding_assets)}."
                        ),
                        node_id=nid,
                    )
                )

    return issues


def has_errors(issues: Sequence[ValidationIssue]) -> bool:
    return any(i.level == "error" for i in issues)


def issues_to_payload(issues: Sequence[ValidationIssue]) -> List[Dict[str, Any]]:
    return [i.to_dict() for i in issues]
