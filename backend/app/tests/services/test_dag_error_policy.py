"""Explicit task error policy and join quorum behaviour."""

from app.services.run_engine.dag import (
    DagGraph,
    DagNode,
    WalkerState,
    _error_policy_output,
    _run_join,
)


def _node(node_id: str, kind: str = "task", config=None):
    return DagNode(
        id=node_id,
        type=kind,
        kind=kind,
        label=node_id,
        config=config or {},
        skill_slug=None,
        data={},
    )


def _route_graph():
    return DagGraph.from_flow_definition(
        {
            "nodes": [
                {"id": "task", "kind": "task"},
                {"id": "normal", "kind": "task"},
                {"id": "handler", "kind": "task"},
            ],
            "edges": [
                {"from": "task", "to": "normal"},
                {"from": "task", "to": "handler", "kind": "error"},
            ],
        }
    )


def test_on_error_continue_remains_the_default_and_preserves_the_envelope():
    outcome = _error_policy_output(
        _node("task"),
        _route_graph(),
        output={"source": "a"},
        error="provider_timeout",
        status="failed",
    )

    assert outcome == {
        "output": {"source": "a", "_error": "provider_timeout", "_status": "failed"}
    }


def test_on_error_fail_becomes_terminal():
    outcome = _error_policy_output(
        _node("task", config={"on_error": "fail"}),
        _route_graph(),
        output={},
        error="provider_timeout",
        status="failed",
    )

    assert outcome["terminal_error"] == "node_error_policy:task:provider_timeout"


def test_on_error_route_selects_only_the_error_edge():
    graph = _route_graph()
    outcome = _error_policy_output(
        _node("task", config={"on_error": "route"}),
        graph,
        output={"source": "a"},
        error="provider_timeout",
        status="failed",
    )

    assert outcome["inactive_targets"] == ["normal"]
    assert outcome["output"]["_error"] == "provider_timeout"


def test_join_reports_failed_branches_and_enforces_min_success():
    graph = DagGraph.from_flow_definition(
        {
            "nodes": [
                {"id": "a", "kind": "task"},
                {"id": "b", "kind": "task"},
                {"id": "join", "kind": "join", "config": {"min_success": 2}},
            ],
            "edges": [
                {"from": "a", "to": "join", "label": "a"},
                {"from": "b", "to": "join", "label": "b"},
            ],
        }
    )
    state = WalkerState()
    state.node_outputs = {
        "a": {"value": "ok"},
        "b": {"value": "bad", "_status": "failed", "_error": "timeout"},
    }

    outcome = _run_join(graph.nodes["join"], graph, state)

    assert outcome["terminal_error"] == "join_min_success:join:1/2"
    assert outcome["output"]["_failed_branches"] == ["b"]


def test_join_succeeds_above_min_success_and_still_names_failed_branches():
    graph = DagGraph.from_flow_definition(
        {
            "nodes": [
                {"id": "a", "kind": "task"},
                {"id": "b", "kind": "task"},
                {"id": "join", "kind": "join", "config": {"min_success": 1}},
            ],
            "edges": [
                {"from": "a", "to": "join", "label": "a"},
                {"from": "b", "to": "join", "label": "b"},
            ],
        }
    )
    state = WalkerState()
    state.node_outputs = {
        "a": {"value": "ok"},
        "b": {"value": "bad", "_status": "failed", "_error": "timeout"},
    }

    outcome = _run_join(graph.nodes["join"], graph, state)

    assert "terminal_error" not in outcome
    assert outcome["output"]["_failed_branches"] == ["b"]
