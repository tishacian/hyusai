"""Plan an idempotent v3 dot-path migration without rewriting history."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Mapping

from app.services.chains.variable_contract import convert_flow_dot_paths


@dataclass(frozen=True)
class VariableBackfillPlan:
    flow: dict[str, Any]
    status: str
    changed: bool
    conversions: int
    unresolved: list[dict[str, Any]]


def plan_variable_backfill(flow_definition: Mapping[str, Any]) -> VariableBackfillPlan:
    """Return the safe next flow snapshot for one System.

    A historical ``SystemVersion`` is never touched by this pure planner. The
    caller may persist ``flow`` as a new version only when ``changed`` is true.
    Ambiguous refs stay byte-for-byte strings; a previously strict flow is
    downgraded to overlay so those refs cannot become authoritative by accident.
    """
    source = deepcopy(dict(flow_definition))
    try:
        schema_version = int(source.get("schema_version") or 0)
    except (TypeError, ValueError):
        schema_version = 0
    if schema_version < 3:
        return VariableBackfillPlan(
            flow=source,
            status="skipped_pre_v3",
            changed=False,
            conversions=0,
            unresolved=[],
        )

    converted, unresolved = convert_flow_dot_paths(source)
    conversions = _count_conversions(source, converted)
    if unresolved:
        # An ambiguous v3 contract remains explicitly non-authoritative. This
        # is the only mutation allowed when no selector can be converted.
        if converted.get("io_mode") == "strict":
            converted["io_mode"] = "overlay"
        return VariableBackfillPlan(
            flow=converted,
            status="ambiguous_overlay",
            changed=converted != source,
            conversions=conversions,
            unresolved=unresolved,
        )

    return VariableBackfillPlan(
        flow=converted,
        status="converted" if conversions else "already_canonical",
        changed=converted != source,
        conversions=conversions,
        unresolved=[],
    )


def _count_conversions(before: Mapping[str, Any], after: Mapping[str, Any]) -> int:
    before_nodes = before.get("nodes") if isinstance(before.get("nodes"), list) else []
    after_nodes = after.get("nodes") if isinstance(after.get("nodes"), list) else []
    after_by_id = {
        str(node.get("id")): node
        for node in after_nodes
        if isinstance(node, Mapping) and node.get("id") is not None
    }
    count = 0
    for node in before_nodes:
        if not isinstance(node, Mapping):
            continue
        config = node.get("config") if isinstance(node.get("config"), Mapping) else {}
        inputs = config.get("inputs_map") if isinstance(config.get("inputs_map"), Mapping) else {}
        other = after_by_id.get(str(node.get("id")))
        other_config = other.get("config") if isinstance(other, Mapping) and isinstance(other.get("config"), Mapping) else {}
        other_inputs = other_config.get("inputs_map") if isinstance(other_config.get("inputs_map"), Mapping) else {}
        for port, selector in inputs.items():
            if isinstance(selector, str) and isinstance(other_inputs.get(port), Mapping):
                count += 1
    return count
