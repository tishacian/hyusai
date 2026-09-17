"""Deterministic, secret-free semantic diff for Flow publication."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from typing import Any

from app.services.flow_contracts import canonical_sha256
from app.services.flow_graph_identity import edge_identity
from app.services.flow_skill_binding import (
    FlowSkillBindingError,
    resolve_flow_skill_binding,
)


def _nodes(flow: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    raw = flow.get("nodes")
    if not isinstance(raw, list):
        return {}
    return {
        str(node["id"]): node
        for node in raw
        if isinstance(node, Mapping) and isinstance(node.get("id"), str) and node["id"]
    }


def _node_groups(flow: Mapping[str, Any]) -> dict[str, list[Mapping[str, Any]]]:
    groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    raw = flow.get("nodes")
    if isinstance(raw, list):
        for node in raw:
            if isinstance(node, Mapping) and isinstance(node.get("id"), str) and node["id"]:
                groups[str(node["id"])].append(node)
    return dict(groups)


def _edges(flow: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    raw = flow.get("edges")
    if not isinstance(raw, list):
        return {}
    return {edge_identity(edge): edge for edge in raw if isinstance(edge, Mapping)}


def _edge_groups(flow: Mapping[str, Any]) -> dict[str, list[Mapping[str, Any]]]:
    groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    raw = flow.get("edges")
    if isinstance(raw, list):
        for edge in raw:
            if isinstance(edge, Mapping):
                groups[edge_identity(edge)].append(edge)
    return dict(groups)


def _node_order(flow: Mapping[str, Any]) -> list[str]:
    raw = flow.get("nodes")
    if not isinstance(raw, list):
        return []
    return [str(node.get("id") or "") for node in raw if isinstance(node, Mapping)]


def _edge_order(flow: Mapping[str, Any]) -> list[str]:
    raw = flow.get("edges")
    if not isinstance(raw, list):
        return []
    return [edge_identity(edge) for edge in raw if isinstance(edge, Mapping)]


def _digest(value: Any) -> str | None:
    return canonical_sha256(value) if value is not None else None


def _field_changed(base: Mapping[str, Any], target: Mapping[str, Any], key: str) -> bool:
    """Compare value and presence so absent and explicit null stay observable."""

    return (key in base) != (key in target) or base.get(key) != target.get(key)


def _change(
    *,
    category: str,
    impact: str,
    subject: str,
    path: str,
    before: Any,
    after: Any,
    description: str,
) -> dict[str, Any]:
    return {
        "category": category,
        "impact": impact,
        "subject": subject,
        "path": path,
        "before_sha256": _digest(before),
        "after_sha256": _digest(after),
        "description": description,
    }


def _node_contract(node: Mapping[str, Any]) -> dict[str, Any]:
    config = node.get("config") if isinstance(node.get("config"), Mapping) else {}
    try:
        binding = resolve_flow_skill_binding(node)
        skill_id = binding.skill_id
        skill_slug = binding.skill_slug
        skill_binding_error = None
    except FlowSkillBindingError as exc:
        # Invalid candidates are rejected by the validator before Publish, but
        # their diff must still be non-empty and deterministic for the editor.
        skill_id = None
        skill_slug = None
        skill_binding_error = exc.code
    return {
        "kind": node.get("kind") or "task",
        "type": node.get("type"),
        "inputs": node.get("inputs") or [],
        "outputs": node.get("outputs") or [],
        "skill_id": skill_id,
        "skill_slug": skill_slug,
        "skill_binding_error": skill_binding_error,
        "runtime_ref": config.get("runtime_ref"),
        "branches": config.get("branches"),
        "default_branch": config.get("default_branch"),
        "inputs_map": config.get("inputs_map"),
        "outputs_map": config.get("outputs_map"),
        "input_schema": config.get("input_schema"),
        "output_schema": config.get("output_schema"),
        "ingress_kind": config.get("ingress_kind"),
    }


def _node_runtime(node: Mapping[str, Any]) -> dict[str, Any]:
    config = node.get("config") if isinstance(node.get("config"), Mapping) else {}
    excluded = {
        "branches",
        "default_branch",
        "inputs_map",
        "outputs_map",
        "input_schema",
        "output_schema",
        "ingress_kind",
    }
    # Values never leave the service; only their digest is returned.
    return {key: value for key, value in config.items() if key not in excluded}


def _presentation(node: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "label": node.get("label"),
        "position": node.get("position"),
        "menu": (node.get("data") or {}).get("menu")
        if isinstance(node.get("data"), Mapping)
        else None,
    }


def semantic_flow_diff(
    base: Mapping[str, Any],
    target: Mapping[str, Any],
    *,
    base_identity: str,
    target_identity: str,
    base_contract: Mapping[str, Any] | None = None,
    target_contract: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    changes: list[dict[str, Any]] = []
    base_policy = base_contract.get("control_policy_snapshot") if base_contract is not None else None
    target_policy = target_contract.get("control_policy_snapshot") if target_contract is not None else None
    if base_contract is not None and base_policy != target_policy:
        changes.append(_change(category="mandate", impact="breaking", subject="system",
                               path="execution_contract/control_policy_snapshot", before=base_policy,
                               after=target_policy, description="Frozen System mandate changed; review permissions, human gates and limits."))
    base_bindings = ({key: value for key, value in base_contract.items() if key not in {"control_policy_snapshot", "contract_sha256"}}
                     if base_contract is not None else None)
    target_bindings = ({key: value for key, value in target_contract.items() if key not in {"control_policy_snapshot", "contract_sha256"}}
                       if target_contract is not None else None)
    if base_bindings != target_bindings and (
        base_contract is not None or target_contract is not None
    ):
        changes.append(
            _change(
                category="execution_contract",
                # Introducing the first validated contract for a legacy
                # migration baseline is the sole non-breaking transition: the
                # baseline is already non-executable until that contract is
                # frozen. Removing authority, changing it, or replacing an
                # invalid frozen contract remains breaking.
                impact=(
                    "behavioral"
                    if base_contract is None and target_contract is not None
                    else "breaking"
                ),
                subject="flow",
                path="execution_contract",
                before=base_contract,
                after=target_contract,
                description="Frozen executable schemas or Skill bindings changed.",
            )
        )
    for key in ("schema_version", "io_mode", "variable_namespaces"):
        before_value = base.get(key)
        after_value = target.get(key)
        if _field_changed(base, target, key):
            changes.append(
                _change(
                    category="variables_contracts",
                    impact="breaking",
                    subject="flow",
                    path=key,
                    before=before_value,
                    after=after_value,
                    description=f"Flow {key} contract changed.",
                )
            )
    if _field_changed(base, target, "variant"):
        changes.append(
            _change(
                category="runtime",
                impact="breaking",
                subject="flow",
                path="variant",
                before=base.get("variant"),
                after=target.get("variant"),
                description="Flow runtime variant changed.",
            )
        )

    if _field_changed(base, target, "output_contract"):
        changes.append(
            _change(
                category="ingress_output",
                impact="breaking",
                subject="flow",
                path="output_contract",
                before=base.get("output_contract"),
                after=target.get("output_contract"),
                description="Flow output contract changed.",
            )
        )

    # Top-level UI/lineage fields are observable but not executable. Every
    # other unrecognised top-level field is classified fail-safe as breaking:
    # new runtime switches must never become invisible merely because this
    # diff implementation predates them.
    presentation_fields = {
        "data_flow_notes",
        "description",
        "extended",
        "label",
        "metadata",
        "name",
        "presentation",
        "source",
        "template_id",
        "template_name",
        "ui",
    }
    handled_fields = {
        "edges",
        "io_mode",
        "nodes",
        "output_contract",
        "schema_version",
        "variable_namespaces",
        "variant",
    }
    for key in sorted((set(base) | set(target)) - handled_fields):
        before_value = base.get(key)
        after_value = target.get(key)
        if not _field_changed(base, target, key):
            continue
        is_presentation = key in presentation_fields
        changes.append(
            _change(
                category="presentation" if is_presentation else "runtime",
                impact="presentation" if is_presentation else "breaking",
                subject="flow",
                path=key,
                before=before_value,
                after=after_value,
                description=(
                    f"Flow presentation field {key!r} changed."
                    if is_presentation
                    else f"Unclassified executable Flow field {key!r} changed."
                ),
            )
        )

    # Ordering is part of the executable contract for compatibility runtimes
    # (including the pinned Agentic chat contract).  Do not collapse it into
    # the id-keyed maps used for node/edge content comparison.
    for path, before_order, after_order in (
        ("nodes/order", _node_order(base), _node_order(target)),
        ("edges/order", _edge_order(base), _edge_order(target)),
    ):
        if before_order != after_order and sorted(before_order) == sorted(after_order):
            changes.append(
                _change(
                    category="topology",
                    impact="breaking",
                    subject="flow",
                    path=path,
                    before=before_order,
                    after=after_order,
                    description=f"Executable {path.replace('/', ' ')} changed.",
                )
            )
    base_node_groups = _node_groups(base)
    target_node_groups = _node_groups(target)
    for node_id in sorted(set(base_node_groups) | set(target_node_groups)):
        before_group = base_node_groups.get(node_id, [])
        after_group = target_node_groups.get(node_id, [])
        if max(len(before_group), len(after_group)) > 1 and before_group != after_group:
            changes.append(
                _change(
                    category="topology",
                    impact="breaking",
                    subject=node_id,
                    path=f"nodes/{node_id}/duplicate_declarations",
                    before=before_group,
                    after=after_group,
                    description="Duplicate node declarations changed.",
                )
            )
    base_nodes = _nodes(base)
    target_nodes = _nodes(target)
    for node_id in sorted(set(base_nodes) | set(target_nodes)):
        before = base_nodes.get(node_id)
        after = target_nodes.get(node_id)
        if before is None:
            changes.append(
                _change(
                    category="topology",
                    impact="behavioral",
                    subject=node_id,
                    path=f"nodes/{node_id}",
                    before=None,
                    after=_node_contract(after or {}),
                    description="Executable node added.",
                )
            )
            continue
        if after is None:
            changes.append(
                _change(
                    category="topology",
                    impact="breaking",
                    subject=node_id,
                    path=f"nodes/{node_id}",
                    before=_node_contract(before),
                    after=None,
                    description="Executable node removed.",
                )
            )
            continue
        before_contract = _node_contract(before)
        after_contract = _node_contract(after)
        if before_contract != after_contract:
            breaking_fields = {
                "kind",
                "type",
                "inputs",
                "outputs",
                "input_schema",
                "output_schema",
                "ingress_kind",
            }
            impact = (
                "breaking"
                if any(
                    before_contract.get(key) != after_contract.get(key) for key in breaking_fields
                )
                else "behavioral"
            )
            category = (
                "ingress_output"
                if any(
                    before_contract.get(key) != after_contract.get(key)
                    for key in ("input_schema", "output_schema", "ingress_kind")
                )
                else "variables_contracts"
            )
            changes.append(
                _change(
                    category=category,
                    impact=impact,
                    subject=node_id,
                    path=f"nodes/{node_id}/contract",
                    before=before_contract,
                    after=after_contract,
                    description="Executable node contract changed.",
                )
            )
        before_runtime = _node_runtime(before)
        after_runtime = _node_runtime(after)
        if before_runtime != after_runtime:
            changes.append(
                _change(
                    category="runtime",
                    impact="behavioral",
                    subject=node_id,
                    path=f"nodes/{node_id}/runtime",
                    before=before_runtime,
                    after=after_runtime,
                    description="Runtime configuration changed.",
                )
            )
        if _presentation(before) != _presentation(after):
            changes.append(
                _change(
                    category="presentation",
                    impact="presentation",
                    subject=node_id,
                    path=f"nodes/{node_id}/presentation",
                    before=_presentation(before),
                    after=_presentation(after),
                    description="Node presentation changed.",
                )
            )

    base_edge_groups = _edge_groups(base)
    target_edge_groups = _edge_groups(target)
    for identity in sorted(set(base_edge_groups) | set(target_edge_groups)):
        before_group = base_edge_groups.get(identity, [])
        after_group = target_edge_groups.get(identity, [])
        if max(len(before_group), len(after_group)) > 1 and before_group != after_group:
            changes.append(
                _change(
                    category="topology",
                    impact="breaking",
                    subject=identity,
                    path=f"edges/{canonical_sha256(identity)[:16]}/duplicate_declarations",
                    before=before_group,
                    after=after_group,
                    description="Duplicate route declarations changed.",
                )
            )

    base_edges = _edges(base)
    target_edges = _edges(target)
    for identity in sorted(set(base_edges) | set(target_edges)):
        before = base_edges.get(identity)
        after = target_edges.get(identity)
        if before is None:
            changes.append(
                _change(
                    category="topology",
                    impact="behavioral",
                    subject=identity,
                    path=f"edges/{canonical_sha256(identity)[:16]}",
                    before=None,
                    after={"identity": identity},
                    description="Route added.",
                )
            )
        elif after is None:
            changes.append(
                _change(
                    category="topology",
                    impact="breaking",
                    subject=identity,
                    path=f"edges/{canonical_sha256(identity)[:16]}",
                    before={"identity": identity},
                    after=None,
                    description="Route removed.",
                )
            )

    if not changes and canonical_sha256(base) != canonical_sha256(target):
        changes.append(
            _change(
                category="runtime",
                impact="breaking",
                subject="flow",
                path="flow/unclassified",
                before=base,
                after=target,
                description="An unclassified Flow field changed; publication must fail safe.",
            )
        )

    impact_order = {"breaking": 0, "behavioral": 1, "presentation": 2}
    changes.sort(
        key=lambda item: (
            impact_order[item["impact"]],
            item["category"],
            item["subject"],
            item["path"],
        )
    )
    summary = {
        "breaking": sum(item["impact"] == "breaking" for item in changes),
        "behavioral": sum(item["impact"] == "behavioral" for item in changes),
        "presentation": sum(item["impact"] == "presentation" for item in changes),
        "total": len(changes),
    }
    base_result = {"identity": base_identity, "flow_sha256": canonical_sha256(base)}
    target_result = {"identity": target_identity, "flow_sha256": canonical_sha256(target)}
    if base_contract is not None:
        base_result["execution_contract_sha256"] = str(
            base_contract.get("contract_sha256") or canonical_sha256(base_contract)
        )
    if target_contract is not None:
        target_result["execution_contract_sha256"] = str(
            target_contract.get("contract_sha256") or canonical_sha256(target_contract)
        )
    return {
        "base": base_result,
        "target": target_result,
        "summary": summary,
        "changes": changes,
    }
