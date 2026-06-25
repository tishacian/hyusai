"""Pure-logic tests for ``services.chains.dag_validator``.

Exercise every issue code on both positive (should fire) and negative
(should stay silent) cases. No DB, no FastAPI — just the validator.
"""
from __future__ import annotations

from app.services.chains.dag_validator import (
    has_errors,
    validate_flow,
)


def _codes(issues):
    return {i.code for i in issues}


def test_empty_flow_returns_no_issues() -> None:
    assert validate_flow({}) == []
    assert validate_flow({"nodes": [], "edges": []}) == []


def test_single_task_with_skill_is_valid() -> None:
    flow = {
        "nodes": [
            {
                "id": "n1",
                "kind": "task",
                "config": {"skill_id": "skill-123"},
            }
        ],
        "edges": [],
    }
    issues = validate_flow(flow)
    assert issues == []
    assert not has_errors(issues)


def test_task_without_skill_warns_but_does_not_error() -> None:
    flow = {"nodes": [{"id": "n1", "kind": "task"}], "edges": []}
    issues = validate_flow(flow)
    assert _codes(issues) == {"task_no_skill"}
    assert not has_errors(issues)


def test_builder_canonical_nodes_exempted_from_task_no_skill() -> None:
    flow = {
        "nodes": [{"id": "builder.objective", "kind": "task"}],
        "edges": [],
    }
    assert validate_flow(flow) == []


def test_dangling_edge_is_error() -> None:
    flow = {
        "nodes": [{"id": "n1", "kind": "task", "config": {"skill_id": "s"}}],
        "edges": [{"from": "n1", "to": "missing"}],
    }
    issues = validate_flow(flow)
    assert "dangling_edge" in _codes(issues)
    assert has_errors(issues)


def test_decision_without_two_branches_is_error() -> None:
    flow = {
        "nodes": [
            {"id": "d1", "kind": "decision", "config": {"branches": [{"label": "a", "condition": "x"}]}},
        ],
        "edges": [],
    }
    issues = validate_flow(flow)
    assert "decision_no_branches" in _codes(issues)
    assert has_errors(issues)


def test_decision_with_two_branches_is_valid() -> None:
    flow = {
        "nodes": [
            {
                "id": "d1",
                "kind": "decision",
                "config": {
                    "branches": [
                        {"label": "a", "condition": "x"},
                        {"label": "b", "condition": "y"},
                    ]
                },
            }
        ],
        "edges": [],
    }
    assert validate_flow(flow) == []


def test_loop_without_positive_budget_is_error() -> None:
    flow = {"nodes": [{"id": "l1", "kind": "loop", "config": {"max_iterations": 0}}], "edges": []}
    issues = validate_flow(flow)
    assert "loop_no_budget" in _codes(issues)
    assert has_errors(issues)


def test_retry_without_positive_attempts_is_error() -> None:
    flow = {"nodes": [{"id": "r1", "kind": "retry", "config": {}}], "edges": []}
    issues = validate_flow(flow)
    assert "retry_no_target" in _codes(issues)
    assert has_errors(issues)


def test_hitl_without_prompt_warns() -> None:
    flow = {"nodes": [{"id": "h1", "kind": "hitl", "config": {"prompt": ""}}], "edges": []}
    issues = validate_flow(flow)
    assert _codes(issues) == {"hitl_no_prompt"}
    assert not has_errors(issues)


def test_cycle_is_error() -> None:
    flow = {
        "nodes": [
            {"id": "a", "kind": "task", "config": {"skill_id": "s1"}},
            {"id": "b", "kind": "task", "config": {"skill_id": "s2"}},
        ],
        "edges": [
            {"from": "a", "to": "b"},
            {"from": "b", "to": "a"},
        ],
    }
    issues = validate_flow(flow)
    assert "cycle_detected" in _codes(issues)
    assert has_errors(issues)


def test_fork_and_join_balanced_passes() -> None:
    flow = {
        "nodes": [
            {"id": "f1", "kind": "fork", "config": {"branches": ["l", "r"]}},
            {"id": "a", "kind": "task", "config": {"skill_id": "s1"}},
            {"id": "b", "kind": "task", "config": {"skill_id": "s2"}},
            {"id": "j1", "kind": "join", "config": {"strategy": "all"}},
        ],
        "edges": [
            {"from": "f1", "to": "a"},
            {"from": "f1", "to": "b"},
            {"from": "a", "to": "j1"},
            {"from": "b", "to": "j1"},
        ],
    }
    issues = validate_flow(flow)
    assert _codes(issues) == set()


def test_fork_without_join_warns() -> None:
    flow = {
        "nodes": [
            {"id": "f1", "kind": "fork", "config": {"branches": ["l", "r"]}},
            {"id": "a", "kind": "task", "config": {"skill_id": "s"}},
        ],
        "edges": [{"from": "f1", "to": "a"}],
    }
    issues = validate_flow(flow)
    assert "fork_without_join" in _codes(issues)


def test_orphan_node_in_multi_node_flow_is_error() -> None:
    flow = {
        "nodes": [
            {"id": "a", "kind": "task", "config": {"skill_id": "s1"}},
            {"id": "b", "kind": "task", "config": {"skill_id": "s2"}},
            {"id": "orphan", "kind": "task", "config": {"skill_id": "s3"}},
        ],
        "edges": [{"from": "a", "to": "b"}],
    }
    issues = validate_flow(flow)
    codes = _codes(issues)
    assert "node_orphan" in codes
    assert has_errors(issues)


def test_unreachable_subgraph_with_internal_cycle_is_error() -> None:
    """Node unreachable from any entry. We need to construct a subgraph
    where every node has at least one inbound (so they're not entries)
    and the subgraph is disconnected from the actual entry — otherwise
    any node with zero inbound is considered an entry and nothing is
    unreachable.
    """
    flow = {
        "nodes": [
            {"id": "src", "kind": "source"},
            {"id": "main", "kind": "task", "config": {"skill_id": "s1"}},
            {"id": "iso_a", "kind": "task", "config": {"skill_id": "s2"}},
            {"id": "iso_b", "kind": "task", "config": {"skill_id": "s3"}},
        ],
        "edges": [
            {"from": "src", "to": "main"},
            # iso_a and iso_b form a mutual cycle that's disconnected
            # from src → main. Both have inbound (from each other) so
            # neither is an entry, yet they're unreachable from src.
            {"from": "iso_a", "to": "iso_b"},
            {"from": "iso_b", "to": "iso_a"},
        ],
    }
    issues = validate_flow(flow)
    codes = _codes(issues)
    # Cycle also fires — both are correct diagnostics for this flow.
    assert "unreachable_node" in codes
    assert "cycle_detected" in codes
    assert has_errors(issues)


def test_single_standalone_node_is_valid() -> None:
    flow = {
        "nodes": [{"id": "only", "kind": "task", "config": {"skill_id": "s"}}],
        "edges": [],
    }
    assert validate_flow(flow) == []


# ---------------------------------------------------------------------------
# P0 — variable-membrane (schema_version 3) checks. Kept in lockstep with the
# frontend ``FlowSerializer.validateFlow``: same codes, same warn level.
# ---------------------------------------------------------------------------


def test_port_type_mismatch_warns_on_incompatible_primitives() -> None:
    flow = {
        "schema_version": 3,
        "nodes": [
            {"id": "a", "kind": "source", "outputs": [{"name": "out", "schema": "string"}]},
            {
                "id": "b",
                "kind": "task",
                "config": {"skill_id": "s"},
                "inputs": [{"name": "in", "schema": "number"}],
            },
        ],
        "edges": [
            {"from": "a", "to": "b", "kind": "data", "from_port": "out", "to_port": "in"},
        ],
    }
    issues = validate_flow(flow)
    assert "port_type_mismatch" in _codes(issues)
    assert not has_errors(issues)  # warn level only


def test_port_type_mismatch_silent_on_compatible_and_numeric_widening() -> None:
    flow = {
        "schema_version": 3,
        "nodes": [
            {"id": "a", "kind": "source", "outputs": [{"name": "out", "schema": "integer"}]},
            {
                "id": "b",
                "kind": "task",
                "config": {"skill_id": "s"},
                "inputs": [{"name": "in", "schema": "number"}],
            },
        ],
        "edges": [
            {"from": "a", "to": "b", "kind": "data", "from_port": "out", "to_port": "in"},
        ],
    }
    assert "port_type_mismatch" not in _codes(validate_flow(flow))


def test_port_type_mismatch_silent_on_portless_or_ref_schemas() -> None:
    # Portless data edges (the seeded-flow shape) and non-primitive
    # ``ref:`` schemas are not comparable -> no diagnostic.
    flow = {
        "schema_version": 3,
        "nodes": [
            {"id": "a", "kind": "source", "outputs": [{"name": "out", "schema": "ref:chat.req"}]},
            {
                "id": "b",
                "kind": "task",
                "config": {"skill_id": "s"},
                "inputs": [{"name": "in", "schema": "string"}],
            },
        ],
        "edges": [
            # carries ports but source schema is a non-primitive ref
            {"from": "a", "to": "b", "kind": "data", "from_port": "out", "to_port": "in"},
            # portless edge -> skipped entirely
            {"from": "a", "to": "b", "kind": "data"},
        ],
    }
    assert "port_type_mismatch" not in _codes(validate_flow(flow))


def test_variable_unresolved_warns_on_unknown_node() -> None:
    flow = {
        "schema_version": 3,
        "nodes": [
            {
                "id": "b",
                "kind": "task",
                "config": {
                    "skill_id": "s",
                    "inputs_map": {"q": {"node_id": "ghost", "path": ["value"]}},
                },
            },
        ],
        "edges": [],
    }
    issues = validate_flow(flow)
    assert "variable_unresolved" in _codes(issues)
    assert not has_errors(issues)


def test_variable_unresolved_warns_when_not_upstream() -> None:
    # ``later`` exists but is downstream of ``b`` -> not a valid source.
    flow = {
        "schema_version": 3,
        "nodes": [
            {"id": "a", "kind": "source"},
            {
                "id": "b",
                "kind": "task",
                "config": {
                    "skill_id": "s",
                    "inputs_map": {"q": {"node_id": "later", "path": ["value"]}},
                },
            },
            {"id": "later", "kind": "task", "config": {"skill_id": "s2"}},
        ],
        "edges": [
            {"from": "a", "to": "b", "kind": "control"},
            {"from": "b", "to": "later", "kind": "control"},
        ],
    }
    assert "variable_unresolved" in _codes(validate_flow(flow))


def test_variable_unresolved_silent_for_reserved_namespace_and_legacy_strings() -> None:
    flow = {
        "schema_version": 3,
        "nodes": [
            {"id": "a", "kind": "source", "outputs": [{"name": "goal", "schema": "string"}]},
            {
                "id": "b",
                "kind": "task",
                "config": {
                    "skill_id": "s",
                    "inputs_map": {
                        # reserved namespace -> resolves outside the graph
                        "ws": {"node_id": "workspace", "path": ["settings", "x"]},
                        # valid upstream ref hitting a declared output port
                        "goal": {"node_id": "a", "path": ["goal"]},
                        # legacy dot-path string -> opaque, never flagged
                        "legacy": "session.objective",
                    },
                },
            },
        ],
        "edges": [
            {"from": "a", "to": "b", "kind": "data"},
        ],
    }
    assert "variable_unresolved" not in _codes(validate_flow(flow))


def test_variable_unresolved_warns_on_missing_declared_port() -> None:
    flow = {
        "schema_version": 3,
        "nodes": [
            {"id": "a", "kind": "source", "outputs": [{"name": "goal", "schema": "string"}]},
            {
                "id": "b",
                "kind": "task",
                "config": {
                    "skill_id": "s",
                    "inputs_map": {"q": {"node_id": "a", "path": ["nope"]}},
                },
            },
        ],
        "edges": [
            {"from": "a", "to": "b", "kind": "data"},
        ],
    }
    assert "variable_unresolved" in _codes(validate_flow(flow))
