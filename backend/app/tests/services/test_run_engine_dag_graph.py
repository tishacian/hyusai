"""Pure-logic tests for the DAG walker's graph parsing and dispatch probe.

These tests don't touch the database — they only exercise
:class:`DagGraph.from_flow_definition` and :func:`should_use_dag` against
representative ``flow_definition`` payloads.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.flow_skill_binding import FlowSkillBindingError
from app.services.run_engine.dag import _GRAPH_OWNED_BLOCKS, DagGraph, should_use_dag
from app.services.run_engine.execution_contract import (
    GRAPH_OWNED_CONFIG_SKILLS,
    canonical_flow_sha256,
    resolve_flow_execution,
    resolve_run_flow_execution,
)


def _system(flow: dict) -> SimpleNamespace:
    return SimpleNamespace(flow_definition=flow)


def test_should_use_dag_rejects_v1_flows() -> None:
    assert should_use_dag(_system({})) is False
    assert should_use_dag(_system({"schema_version": 1, "nodes": [], "edges": []})) is False


def test_should_use_dag_rejects_v2_without_control_nodes() -> None:
    flow = {
        "schema_version": 2,
        "nodes": [
            {"id": "a", "kind": "task"},
            {"id": "b", "kind": "task"},
        ],
        "edges": [{"from": "a", "to": "b"}],
    }
    assert should_use_dag(_system(flow)) is False


def test_should_use_dag_accepts_v2_with_decision_node() -> None:
    flow = {
        "schema_version": 2,
        "nodes": [
            {"id": "src", "kind": "source"},
            {"id": "d", "kind": "decision", "config": {"branches": []}},
            {"id": "sink", "kind": "sink"},
        ],
        "edges": [],
    }
    assert should_use_dag(_system(flow)) is True


def test_runtime_resolver_names_strict_overlay_and_legacy_truthfully() -> None:
    strict_workspace = SimpleNamespace(
        settings={"features": {"flow_v3_dag_authoritative": True}}
    )
    strict = {
        "schema_version": 3,
        "io_mode": "strict",
        "nodes": [{"id": "work", "kind": "task"}],
        "edges": [],
    }
    overlay = {
        "schema_version": 3,
        "io_mode": "strict",
        "nodes": [{"id": "route", "kind": "decision"}],
        "edges": [],
    }

    assert resolve_flow_execution(strict, strict_workspace).runtime_mode == "dag_strict"
    assert resolve_flow_execution(overlay).runtime_mode == "dag_overlay"
    assert resolve_flow_execution(strict).runtime_mode == "sequential_legacy"
    assert canonical_flow_sha256({"b": 1, "a": 2}) == canonical_flow_sha256(
        {"a": 2, "b": 1}
    )


def test_a_data_plane_flow_routes_to_the_walker_that_configures_its_nodes() -> None:
    """A dataset chain has one runnable walker, and the resolver has to pick it.

    Nothing about a SQL → Polars → train → score Flow is a control node, so the
    task-only rule sent it to the sequential walker — the one walker that does
    not inject ``_transform``/``_train``, which meant every node refused for lack
    of the configuration the graph was holding. The Flow Builder writes exactly
    this shape when an author wires the data palette, so the failure was the
    default rather than an edge case.
    """

    flow = {
        "schema_version": 3,
        "nodes": [
            {"id": "src", "kind": "source"},
            {
                "id": "task.clean",
                "kind": "task",
                "config": {"skill_slug": "sql_transform_v1", "params": {"sql": "SELECT 1"}},
            },
            {
                "id": "task.train",
                "kind": "task",
                "config": {"skill_slug": "ml_train_sklearn_v1", "params": {"target": "churn"}},
            },
            {"id": "sink", "kind": "sink"},
        ],
        "edges": [
            {"from": "src", "to": "task.clean"},
            {"from": "task.clean", "to": "task.train"},
            {"from": "task.train", "to": "sink"},
        ],
    }
    resolution = resolve_flow_execution(flow)
    assert resolution.runtime_mode == "dag_overlay"
    assert resolution.reason == "graph_owned_config_requires_compatibility_dag"

    # A strict workspace still gets the strict walker: this rule only rescues the
    # flows that would otherwise have had no walker at all.
    strict_workspace = SimpleNamespace(
        settings={"features": {"flow_v3_dag_authoritative": True}}
    )
    assert (
        resolve_flow_execution({**flow, "io_mode": "strict"}, strict_workspace).runtime_mode
        == "dag_strict"
    )
    # And a Flow of ordinary skills is untouched — the legacy path stays the
    # default for everything that does not need graph-owned configuration.
    plain = {
        "schema_version": 3,
        "nodes": [
            {"id": "task.answer", "kind": "task", "config": {"skill_slug": "llm_rag_answer_v1"}}
        ],
        "edges": [],
    }
    assert resolve_flow_execution(plain).runtime_mode == "sequential_legacy"
    automation = {
        "schema_version": 3,
        "variant": "automation_v1",
        "nodes": [
            {"id": "trigger", "kind": "source"},
            {"id": "agent", "kind": "task", "config": {"skill_slug": "workspace_llm_v1"}},
            {"id": "output", "kind": "sink"},
        ],
        "edges": [{"from": "trigger", "to": "agent"}, {"from": "agent", "to": "output"}],
    }
    resolution = resolve_flow_execution(automation)
    assert resolution.runtime_mode == "dag_overlay"
    assert resolution.reason == "automation_graph"


def test_the_routing_list_and_the_injection_table_name_the_same_skills() -> None:
    """Two lists, one fact: which nodes are configured by the graph.

    The resolver has to know the answer before ``dag`` is importable, so the set
    lives in the contract module while the block table lives in the walker. A
    skill added to one and not the other is the silent version of the bug this
    rule exists to prevent — routed to the sequential walker, or routed to the
    DAG and still handed no configuration.
    """

    injected = {slug for _key, slugs, _params in _GRAPH_OWNED_BLOCKS for slug in slugs}
    assert injected == set(GRAPH_OWNED_CONFIG_SKILLS)


def test_run_runtime_uses_even_an_empty_frozen_snapshot_and_pinned_mode() -> None:
    mutable_system = _system(
        {
            "schema_version": 3,
            "io_mode": "strict",
            "nodes": [{"id": "route", "kind": "decision"}],
        }
    )
    empty_snapshot = SimpleNamespace(flow_snapshot={}, input_ref={})
    assert (
        resolve_run_flow_execution(empty_snapshot, mutable_system).runtime_mode
        == "sequential_legacy"
    )

    pinned = SimpleNamespace(
        flow_snapshot=mutable_system.flow_definition,
        input_ref={"execution": {"runtime_mode": "dag_overlay"}},
    )
    strict_workspace = SimpleNamespace(
        settings={"features": {"flow_v3_dag_authoritative": True}}
    )
    assert (
        resolve_run_flow_execution(pinned, mutable_system, strict_workspace).runtime_mode
        == "dag_overlay"
    )


def test_graph_parsing_preserves_ports_and_branch_labels() -> None:
    flow = {
        "schema_version": 2,
        "nodes": [
            {"id": "src", "kind": "source", "label": "Trigger"},
            {
                "id": "task1",
                "kind": "task",
                "label": "Answer",
                "config": {"skill_slug": "llm_rag_answer_v1"},
            },
            {
                "id": "decide",
                "kind": "decision",
                "config": {"branches": [{"label": "hi", "condition": "confidence > 0.8"}]},
            },
            {"id": "sink", "kind": "sink"},
        ],
        "edges": [
            {"from": "src", "to": "task1", "kind": "data"},
            {"from": "task1", "to": "decide", "kind": "data"},
            {"from": "decide", "to": "sink", "kind": "branch", "branch_label": "hi"},
        ],
    }
    g = DagGraph.from_flow_definition(flow)
    assert set(g.nodes.keys()) == {"src", "task1", "decide", "sink"}
    assert g.nodes["task1"].skill_slug == "llm_rag_answer_v1"
    assert g.nodes["decide"].kind == "decision"
    assert g.roots() == ["src"]
    assert len(g.out_edges["decide"]) == 1
    assert g.out_edges["decide"][0].branch_label == "hi"
    assert len(g.in_edges["sink"]) == 1


def test_graph_parsing_ignores_dangling_edges() -> None:
    flow = {
        "schema_version": 2,
        "nodes": [{"id": "a", "kind": "task"}],
        "edges": [
            {"from": "a", "to": "ghost"},      # target missing
            {"from": "nowhere", "to": "a"},    # source missing
        ],
    }
    g = DagGraph.from_flow_definition(flow)
    assert g.edges == []
    assert g.roots() == ["a"]


def test_graph_pulls_skill_slug_from_data_fallback() -> None:
    flow = {
        "schema_version": 2,
        "nodes": [
            {
                "id": "t",
                "kind": "task",
                "data": {"bound_skill_slug": "eval_radar_v1"},
            }
        ],
        "edges": [],
    }
    g = DagGraph.from_flow_definition(flow)
    assert g.nodes["t"].skill_slug == "eval_radar_v1"


def test_graph_rejects_skill_id_without_dispatch_slug() -> None:
    flow = {
        "schema_version": 2,
        "nodes": [
            {
                "id": "t",
                "kind": "task",
                "config": {"skill_id": "skill-id-only"},
            }
        ],
        "edges": [],
    }

    with pytest.raises(FlowSkillBindingError) as exc_info:
        DagGraph.from_flow_definition(flow)

    assert exc_info.value.code == "skill_slug_required"


def test_graph_rejects_conflicting_skill_slug_locations() -> None:
    flow = {
        "schema_version": 2,
        "nodes": [
            {
                "id": "t",
                "kind": "task",
                "config": {"skill_slug": "first"},
                "data": {"skill_slug": "second"},
            }
        ],
        "edges": [],
    }

    with pytest.raises(FlowSkillBindingError) as exc_info:
        DagGraph.from_flow_definition(flow)

    assert exc_info.value.code == "skill_binding_conflict"
