"""Required Skill inputs that nothing in a Flow feeds, read with the engine's rules.

The publication layer must not guess how a step receives its input: the
sequential walker and the DAG walker build it differently. This module asks
the walkers' own helpers which keys can reach each step, and reports a
required field only when the answer is certain. Whenever a rule cannot be
decided statically (an authored executor, an open upstream schema, a DAG node
that inherits its predecessors' merge…), the step is skipped: no warning is
better than a wrong one.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session as DBSession

from app.models.skill import Skill

from .dag import _GRAPH_OWNED_BLOCKS, DagGraph, _apply_retrieval_node_scope, _effective_inputs_map
from .engine import SERVER_OWNED_RUN_INPUT_KEYS, _build_skill_input
from .execution_contract import resolve_flow_execution
from .variable_pool import apply_inputs_map

_FED = object()


def _properties(schema: Any) -> Optional[set[str]]:
    """Field names a closed object schema guarantees; None when it is open or unknown."""
    if not isinstance(schema, Mapping):
        return None
    props = schema.get("properties")
    if not isinstance(props, Mapping):
        return None
    return {str(key) for key in props}


def _closed_properties(schema: Any) -> Optional[set[str]]:
    """Like ``_properties``, but only when no other key can appear."""
    if not isinstance(schema, Mapping) or schema.get("additionalProperties") is not False:
        return None
    return _properties(schema)


def _required(skill: Skill) -> list[str]:
    schema = skill.input_schema if isinstance(skill.input_schema, Mapping) else {}
    required = schema.get("required")
    return [str(item) for item in required] if isinstance(required, list) else []


def _certain(skill: Optional[Skill]) -> bool:
    """A step whose payload the engine alone builds (no authored executor)."""
    return skill is not None and not skill.executor


def _missing(slug: str, required: list[str], run_input: set[str], last_output: set[str]) -> list[str]:
    payload = _build_skill_input(
        slug,
        dict.fromkeys(run_input, _FED),
        dict.fromkeys(last_output, _FED),
        {},
    )
    return [field for field in required if payload.get(field) is None]


def _sequential(
    db: DBSession, *, workspace: Any, system: Any, run_input: set[str]
) -> list[dict[str, Any]]:
    from app.services.system_catalog_bindings import resolve_persisted_system_catalog_bindings

    skills = resolve_persisted_system_catalog_bindings(db, workspace=workspace, system=system).skills
    issues: list[dict[str, Any]] = []
    previous_output: Optional[set[str]] = set()
    for index, skill in enumerate(skills):
        # The step sees the Run input plus the previous step's output only.
        if previous_output is not None and _certain(skill):
            for field in _missing(skill.slug, _required(skill), run_input, previous_output):
                issues.append(
                    {"step": index + 1, "node_id": None, "skill_slug": skill.slug, "skill_name": skill.name, "field": field}
                )
        previous_output = _closed_properties(skill.output_schema)
    return issues


def _graph_owned(slug: str) -> bool:
    return any(slug in slugs for _key, slugs, _params in _GRAPH_OWNED_BLOCKS)


def _skill_by_slug(db: DBSession, *, workspace: Any, slug: str) -> Optional[Skill]:
    rows = (
        db.query(Skill)
        .filter(Skill.slug == slug, or_(Skill.workspace_id == workspace.id, Skill.workspace_id.is_(None)))
        .all()
    )
    return rows[0] if len(rows) == 1 else None


def _dag(db: DBSession, *, workspace: Any, flow: Mapping[str, Any], strict_flow: bool) -> list[dict[str, Any]]:
    graph = DagGraph.from_flow_definition(dict(flow))
    graph.strict_authoritative = strict_flow
    issues: list[dict[str, Any]] = []
    for index, node in enumerate(graph.nodes.values()):
        slug = node.skill_slug
        if node.kind != "task" or not slug or _graph_owned(slug):
            continue
        # An inheriting node receives its predecessors' merge: not decidable.
        if not (strict_flow or node.config.get("input_mode") == "mapped"):
            continue
        skill = _skill_by_slug(db, workspace=workspace, slug=slug)
        if not _certain(skill):
            continue
        passthrough = node.config.get("passthrough_inputs") or []
        config = {
            "input_mode": "mapped",
            "passthrough_inputs": passthrough,
        }
        # The walker's own strict rule: declared pass-through fields only…
        fed = set(apply_inputs_map(config, None, dict.fromkeys(map(str, passthrough), _FED), io_mode="strict"))
        # …plus every mapped port, and inspector params used as defaults.
        fed |= {str(port) for port in (_effective_inputs_map(node, graph) or {})}
        params = node.config.get("params")
        if isinstance(params, Mapping):
            fed |= {str(key) for key in params}
        # A Builder-authored retrieval scope writes its own canonical keys.
        probe: dict[str, Any] = {}
        try:
            _apply_retrieval_node_scope(node, probe)
        except ValueError:
            continue
        fed |= set(probe)
        for field in _required(skill):
            if field not in fed:
                issues.append(
                    {
                        "step": index + 1,
                        "node_id": node.id,
                        "skill_slug": slug,
                        "skill_name": node.label or skill.name,
                        "field": field,
                    }
                )
    return issues


def unfed_required_inputs(
    db: DBSession,
    *,
    workspace: Any,
    system: Any,
    flow: Mapping[str, Any],
    input_schema: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    """Required step fields that neither the Run input nor an upstream step provides.

    ``input_schema`` is the ingress contract (form or trigger fields). Only
    certain gaps are returned; an undecidable step is left out.
    """
    resolution = resolve_flow_execution(flow, workspace)
    if resolution.runtime_mode == "sequential_legacy":
        fields = _properties(input_schema)
        if fields is None:
            return []
        return _sequential(db, workspace=workspace, system=system, run_input=fields | SERVER_OWNED_RUN_INPUT_KEYS)
    return _dag(db, workspace=workspace, flow=flow, strict_flow=resolution.strict_authoritative)
