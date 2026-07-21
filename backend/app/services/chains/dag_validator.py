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

from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set

from app.services.chains.variable_contract import (
    declared_namespaces,
    dot_path_to_variable_ref,
)
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


def validate_flow(flow: Mapping[str, Any]) -> List[ValidationIssue]:
    """Run the full validator on ``flow_definition``. Return a list of
    issues (may be empty for a valid flow). Never raises.
    """

    issues: List[ValidationIssue] = []
    nodes = _iter_nodes(flow)
    edges = _iter_edges(flow)

    raw_io_mode = flow.get("io_mode")
    strict = raw_io_mode == "strict"
    try:
        schema_version = int(flow.get("schema_version") or 0)
    except (TypeError, ValueError):
        schema_version = 0
    if raw_io_mode is not None and raw_io_mode not in {"overlay", "strict"}:
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
    nodes_by_id: Dict[str, Mapping[str, Any]] = {}
    for node in nodes:
        nid = _node_id(node)
        if nid:
            nodes_by_id[nid] = node

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
