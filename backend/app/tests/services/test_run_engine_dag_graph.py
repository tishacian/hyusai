"""Pure-logic tests for the DAG walker's graph parsing and dispatch probe.

These tests don't touch the database — they only exercise
:class:`DagGraph.from_flow_definition` and :func:`should_use_dag` against
representative ``flow_definition`` payloads.
"""
from __future__ import annotations

from types import SimpleNamespace

from app.services.run_engine.dag import DagGraph, should_use_dag


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
