"""Pure-logic tests for ``services.chains.dag_validator``.

Exercise every issue code on both positive (should fire) and negative
(should stay silent) cases. No DB, no FastAPI — just the validator.
"""
from __future__ import annotations

import pytest

from app.services.chains.dag_validator import (
    has_errors,
    validate_flow,
)


def _codes(issues):
    return {i.code for i in issues}


def test_empty_flow_returns_no_issues() -> None:
    assert validate_flow({}) == []
    assert validate_flow({"nodes": [], "edges": []}) == []


@pytest.mark.parametrize(
    ("flow", "expected_codes"),
    [
        ({"nodes": {}, "edges": []}, {"nodes_invalid"}),
        ({"nodes": [], "edges": {}}, {"edges_invalid"}),
        ({"nodes": [None], "edges": []}, {"node_invalid"}),
        ({"nodes": [], "edges": [None]}, {"edge_invalid"}),
        ({"nodes": [], "edges": [{}]}, {"edge_invalid"}),
        ({"nodes": [{"kind": "source"}], "edges": []}, {"node_invalid"}),
        (
            {"nodes": [{"id": " source ", "kind": "source"}], "edges": []},
            {"node_invalid"},
        ),
        (
            {
                "nodes": [{"id": "source", "kind": "source", "config": []}],
                "edges": [],
            },
            {"node_invalid"},
        ),
        (
            {
                "nodes": [{"id": "source", "kind": "source"}],
                "edges": [{"from": [], "to": "source"}],
            },
            {"edge_invalid"},
        ),
    ],
)
def test_malformed_graph_shape_returns_structured_errors_without_raising(
    flow, expected_codes
) -> None:
    issues = validate_flow(flow)

    assert _codes(issues) == expected_codes
    assert all(issue.level == "error" for issue in issues)
    assert has_errors(issues)


def test_all_malformed_graph_elements_are_reported_before_topology_analysis() -> None:
    issues = validate_flow(
        {
            "nodes": [None, {"id": ""}, {"id": "valid", "data": []}],
            "edges": [None, {"from": {}, "to": "valid"}],
        }
    )

    assert [issue.code for issue in issues] == [
        "node_invalid",
        "node_invalid",
        "node_invalid",
        "edge_invalid",
        "edge_invalid",
    ]
    assert issues[3].edge_index == 0
    assert issues[4].edge_index == 1


def test_single_task_with_skill_is_valid() -> None:
    flow = {
        "nodes": [
            {
                "id": "n1",
                "kind": "task",
                "config": {"skill_slug": "skill-123"},
            }
        ],
        "edges": [],
    }
    issues = validate_flow(flow)
    assert issues == []
    assert not has_errors(issues)


@pytest.mark.parametrize(
    "binding",
    [
        {"config": {"skill_slug": "skill-123"}},
        {"config": {"skill": {"slug": "skill-123"}}},
        {"data": {"bound_skill_slug": "skill-123"}},
        {"data": {"skill_slug": "skill-123"}},
    ],
)
def test_all_supported_skill_slug_locations_are_valid(binding) -> None:
    flow = {
        "nodes": [{"id": "n1", "kind": "task", **binding}],
        "edges": [],
    }

    assert validate_flow(flow) == []


def test_skill_id_without_slug_fails_closed() -> None:
    issues = validate_flow(
        {
            "nodes": [{"id": "n1", "kind": "task", "config": {"skill_id": "skill-123"}}],
            "edges": [],
        }
    )

    assert _codes(issues) == {"skill_slug_required"}
    assert has_errors(issues)


def test_conflicting_skill_slug_locations_fail_closed() -> None:
    issues = validate_flow(
        {
            "nodes": [
                {
                    "id": "n1",
                    "kind": "task",
                    "config": {"skill_slug": "first"},
                    "data": {"bound_skill_slug": "second"},
                }
            ],
            "edges": [],
        }
    )

    assert _codes(issues) == {"skill_binding_conflict"}
    assert has_errors(issues)


def test_task_without_skill_warns_but_does_not_error() -> None:
    flow = {"nodes": [{"id": "n1", "kind": "task"}], "edges": []}
    issues = validate_flow(flow)
    assert _codes(issues) == {"task_no_skill"}
    assert not has_errors(issues)


def test_on_error_accepts_declared_policies() -> None:
    for on_error in ("continue", "fail", "route"):
        flow = {
            "nodes": [
                {"id": "task", "kind": "task", "config": {"on_error": on_error}},
                {"id": "handler", "kind": "task", "config": {"skill_slug": "handler"}},
            ],
            "edges": [{"from": "task", "to": "handler", "kind": "error"}],
        }
        assert not has_errors(validate_flow(flow))


def test_on_error_rejects_unknown_policy() -> None:
    flow = {
        "nodes": [{"id": "task", "kind": "task", "config": {"on_error": "ignore"}}],
        "edges": [],
    }

    issues = validate_flow(flow)

    assert _codes(issues) == {"on_error_invalid", "task_no_skill"}
    assert has_errors(issues)


def test_on_error_route_requires_an_error_edge() -> None:
    flow = {
        "nodes": [
            {"id": "task", "kind": "task", "config": {"on_error": "route"}},
            {"id": "normal", "kind": "task", "config": {"skill_slug": "next"}},
        ],
        "edges": [{"from": "task", "to": "normal", "kind": "data"}],
    }

    issues = validate_flow(flow)

    assert "on_error_route_missing" in _codes(issues)
    assert has_errors(issues)


def test_builder_canonical_nodes_exempted_from_task_no_skill() -> None:
    flow = {
        "nodes": [{"id": "builder.objective", "kind": "task"}],
        "edges": [],
    }
    assert validate_flow(flow) == []


def test_allowlisted_builtin_passthrough_is_a_real_runtime_binding() -> None:
    flow = {
        "nodes": [
            {
                "id": "passthrough",
                "kind": "task",
                "config": {"runtime_ref": "builtin:passthrough"},
            }
        ],
        "edges": [],
    }
    assert validate_flow(flow) == []


def test_unknown_builtin_runtime_ref_fails_closed() -> None:
    flow = {
        "nodes": [
            {
                "id": "mystery",
                "kind": "task",
                "config": {"runtime_ref": "builtin:does-not-exist"},
            }
        ],
        "edges": [],
    }
    issues = validate_flow(flow)
    assert "task_runtime_ref_invalid" in _codes(issues)
    assert has_errors(issues)


def test_dangling_edge_is_error() -> None:
    flow = {
        "nodes": [{"id": "n1", "kind": "task", "config": {"skill_slug": "s"}}],
        "edges": [{"from": "n1", "to": "missing"}],
    }
    issues = validate_flow(flow)
    assert "dangling_edge" in _codes(issues)
    assert has_errors(issues)


def test_duplicate_node_ids_fail_before_ambiguous_graph_analysis() -> None:
    issues = validate_flow(
        {
            "nodes": [
                {"id": "same", "kind": "source"},
                {"id": "same", "kind": "sink"},
            ],
            "edges": [],
        }
    )

    assert _codes(issues) == {"node_id_duplicate"}
    assert issues[0].node_id == "same"
    assert has_errors(issues)


def test_duplicate_edge_identity_is_structured_and_collision_free() -> None:
    flow = {
        "nodes": [
            {"id": "a|b", "kind": "source"},
            {"id": "a", "kind": "source"},
            {"id": "c", "kind": "sink"},
            {"id": "b|c", "kind": "sink"},
        ],
        "edges": [
            {"from": "a|b", "to": "c", "kind": "data"},
            {"from": "a", "to": "b|c", "kind": "data"},
        ],
    }

    assert "edge_duplicate" not in _codes(validate_flow(flow))

    flow["edges"].append(dict(flow["edges"][0]))
    duplicates = [issue for issue in validate_flow(flow) if issue.code == "edge_duplicate"]
    assert len(duplicates) == 1
    assert duplicates[0].edge_index == 2
    assert duplicates[0].level == "error"


@pytest.mark.parametrize(
    ("nodes", "edges", "expected_code"),
    [
        (
            [{"id": "source", "kind": "source"}],
            [],
            "flow_output_sink_required",
        ),
        (
            [
                {"id": "source", "kind": "source"},
                {"id": "first", "kind": "sink"},
                {"id": "second", "kind": "sink"},
            ],
            [
                {"from": "source", "to": "first"},
                {"from": "source", "to": "second"},
            ],
            "flow_output_sink_ambiguous",
        ),
    ],
)
def test_strict_flow_requires_exactly_one_explicit_sink(nodes, edges, expected_code) -> None:
    issues = validate_flow(
        {
            "schema_version": 3,
            "io_mode": "strict",
            "nodes": nodes,
            "edges": edges,
        }
    )

    assert expected_code in _codes(issues)
    assert has_errors(issues)


def test_strict_flow_accepts_one_explicit_sink() -> None:
    issues = validate_flow(
        {
            "schema_version": 3,
            "io_mode": "strict",
            "nodes": [
                {"id": "source", "kind": "source"},
                {"id": "result", "kind": "sink"},
            ],
            "edges": [{"from": "source", "to": "result"}],
        }
    )

    assert issues == []


def test_decision_without_two_branches_is_error() -> None:
    flow = {
        "nodes": [
            {
                "id": "d1",
                "kind": "decision",
                "config": {"branches": [{"label": "a", "condition": "x"}]},
            },
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
                        {"label": "a", "condition": "value == True"},
                        {"label": "b", "condition": "value == False"},
                    ],
                    "default_branch": "b",
                },
            },
            {"id": "a", "kind": "sink"},
            {"id": "b", "kind": "sink"},
        ],
        "edges": [
            {"from": "d1", "to": "a", "kind": "branch", "branch_label": "a"},
            {"from": "d1", "to": "b", "kind": "branch", "branch_label": "b"},
        ],
    }
    assert validate_flow(flow) == []


@pytest.mark.parametrize(
    ("branches", "default_branch", "expected_code"),
    [
        (
            [
                {"label": "yes", "condition": ""},
                {"label": "no", "condition": "value == False"},
            ],
            "no",
            "decision_condition_invalid",
        ),
        (
            [
                {"label": "same", "condition": "True"},
                {"label": "same", "condition": "False"},
            ],
            "same",
            "decision_branch_duplicate",
        ),
        (
            [
                {"label": "yes", "condition": "value == True"},
                {"label": "no", "condition": "value == False"},
            ],
            "missing",
            "decision_default_invalid",
        ),
        (
            [
                {"label": "yes", "condition": "__import__('os')"},
                {"label": "no", "condition": "False"},
            ],
            "no",
            "decision_condition_invalid",
        ),
    ],
)
def test_decision_contract_rejects_invalid_configuration(
    branches, default_branch, expected_code
) -> None:
    flow = {
        "nodes": [
            {
                "id": "d",
                "kind": "decision",
                "config": {"branches": branches, "default_branch": default_branch},
            },
            {"id": "yes", "kind": "sink"},
            {"id": "no", "kind": "sink"},
        ],
        "edges": [
            {"from": "d", "to": "yes", "kind": "branch", "branch_label": "yes"},
            {"from": "d", "to": "no", "kind": "branch", "branch_label": "no"},
        ],
    }
    assert expected_code in _codes(validate_flow(flow))


def test_decision_requires_every_branch_to_be_wired() -> None:
    flow = {
        "nodes": [
            {
                "id": "d",
                "kind": "decision",
                "config": {
                    "branches": [
                        {"label": "yes", "condition": "True"},
                        {"label": "no", "condition": "False"},
                    ]
                },
            },
            {"id": "sink", "kind": "sink"},
        ],
        "edges": [{"from": "d", "to": "sink", "kind": "branch", "branch_label": "yes"}],
    }
    assert "decision_branch_unwired" in _codes(validate_flow(flow))


def test_branch_edge_must_belong_to_a_decision_label() -> None:
    flow = {
        "nodes": [
            {"id": "source", "kind": "source"},
            {"id": "sink", "kind": "sink"},
        ],
        "edges": [{"from": "source", "to": "sink", "kind": "branch", "branch_label": "yes"}],
    }
    assert "branch_edge_invalid" in _codes(validate_flow(flow))


@pytest.mark.parametrize("budget", [0, True, 1.5, float("nan")])
def test_loop_without_positive_integer_budget_is_error(budget) -> None:
    flow = {
        "nodes": [{"id": "l1", "kind": "loop", "config": {"max_iterations": budget}}],
        "edges": [],
    }
    issues = validate_flow(flow)
    assert "loop_no_budget" in _codes(issues)
    assert has_errors(issues)


@pytest.mark.parametrize("attempts", [None, True, 1.5, float("nan")])
def test_retry_without_positive_integer_attempts_is_error(attempts) -> None:
    config = {} if attempts is None else {"max_attempts": attempts}
    flow = {"nodes": [{"id": "r1", "kind": "retry", "config": config}], "edges": []}
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
            {"id": "a", "kind": "task", "config": {"skill_slug": "s1"}},
            {"id": "b", "kind": "task", "config": {"skill_slug": "s2"}},
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
            {"id": "a", "kind": "task", "config": {"skill_slug": "s1"}},
            {"id": "b", "kind": "task", "config": {"skill_slug": "s2"}},
            {"id": "j1", "kind": "join", "config": {"strategy": "all"}},
        ],
        "edges": [
            {"from": "f1", "to": "a", "from_port": "l"},
            {"from": "f1", "to": "b", "from_port": "r"},
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
            {"id": "a", "kind": "task", "config": {"skill_slug": "s"}},
        ],
        "edges": [{"from": "f1", "to": "a"}],
    }
    issues = validate_flow(flow)
    assert "fork_fanout_invalid" in _codes(issues)
    assert "fork_unjoined" not in _codes(issues)  # fanout must be fixed first


def test_unrelated_fork_and_join_do_not_balance() -> None:
    flow = {
        "nodes": [
            {"id": "f", "kind": "fork", "config": {"branches": ["a", "b"]}},
            {"id": "fa", "kind": "sink"},
            {"id": "fb", "kind": "sink"},
            {"id": "x", "kind": "source"},
            {"id": "y", "kind": "source"},
            {"id": "j", "kind": "join", "config": {"strategy": "all"}},
        ],
        "edges": [
            {"from": "f", "to": "fa", "from_port": "a"},
            {"from": "f", "to": "fb", "from_port": "b"},
            {"from": "x", "to": "j"},
            {"from": "y", "to": "j"},
        ],
    }
    codes = _codes(validate_flow(flow))
    assert "fork_unjoined" in codes
    assert "join_without_matching_fork" in codes


def test_join_must_postdominate_every_fork_lane() -> None:
    flow = {
        "nodes": [
            {"id": "f", "kind": "fork", "config": {"branches": ["a", "b"]}},
            {"id": "a", "kind": "task", "config": {"skill_slug": "a"}},
            {"id": "b", "kind": "task", "config": {"skill_slug": "b"}},
            {"id": "bypass", "kind": "sink"},
            {"id": "j", "kind": "join", "config": {"strategy": "all"}},
        ],
        "edges": [
            {"from": "f", "to": "a", "from_port": "a"},
            {"from": "f", "to": "b", "from_port": "b"},
            {"from": "a", "to": "j"},
            {"from": "a", "to": "bypass"},
            {"from": "b", "to": "j"},
        ],
    }
    assert "fork_unjoined" in _codes(validate_flow(flow))


def test_topology_diagnostics_are_errors_in_strict_mode() -> None:
    flow = {
        "schema_version": 3,
        "io_mode": "strict",
        "nodes": [
            {"id": "f", "kind": "fork", "config": {"branches": ["a", "b"]}},
            {"id": "sink", "kind": "sink"},
        ],
        "edges": [{"from": "f", "to": "sink", "from_port": "a"}],
    }
    issues = validate_flow(flow)
    fanout = next(issue for issue in issues if issue.code == "fork_fanout_invalid")
    assert fanout.level == "error"
    assert has_errors(issues)


def test_orphan_node_in_multi_node_flow_is_error() -> None:
    flow = {
        "nodes": [
            {"id": "a", "kind": "task", "config": {"skill_slug": "s1"}},
            {"id": "b", "kind": "task", "config": {"skill_slug": "s2"}},
            {"id": "orphan", "kind": "task", "config": {"skill_slug": "s3"}},
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
            {"id": "main", "kind": "task", "config": {"skill_slug": "s1"}},
            {"id": "iso_a", "kind": "task", "config": {"skill_slug": "s2"}},
            {"id": "iso_b", "kind": "task", "config": {"skill_slug": "s3"}},
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
        "nodes": [{"id": "only", "kind": "task", "config": {"skill_slug": "s"}}],
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
                "config": {"skill_slug": "s"},
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
                "config": {"skill_slug": "s"},
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
                "config": {"skill_slug": "s"},
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
                    "skill_slug": "s",
                    "inputs_map": {"q": {"node_id": "ghost", "path": ["value"]}},
                },
            },
        ],
        "edges": [],
    }
    issues = validate_flow(flow)
    assert "variable_unresolved" in _codes(issues)
    assert not has_errors(issues)


def test_strict_variable_ref_shape_is_validated_before_resolution() -> None:
    flow = {
        "schema_version": 3,
        "io_mode": "strict",
        "nodes": [
            {"id": "source", "kind": "source"},
            {
                "id": "consumer",
                "kind": "task",
                "config": {
                    "skill_slug": "s",
                    "inputs_map": {
                        "blank_owner": {"node_id": " ", "path": []},
                        "mixed_path": {"node_id": "run", "path": ["query", 0]},
                        "bad_required": {
                            "node_id": "run",
                            "path": ["query"],
                            "required": "false",
                        },
                    },
                },
            },
        ],
        "edges": [{"from": "source", "to": "consumer", "kind": "data"}],
    }
    invalid = [
        issue
        for issue in validate_flow(flow)
        if issue.code == "variable_contract_invalid" and issue.node_id == "consumer"
    ]
    assert len(invalid) == 3
    assert all(issue.level == "error" for issue in invalid)


def test_overlay_invalid_variable_ref_shape_warns_without_becoming_valid() -> None:
    flow = {
        "schema_version": 3,
        "io_mode": "overlay",
        "nodes": [
            {
                "id": "consumer",
                "kind": "task",
                "config": {
                    "skill_slug": "s",
                    "inputs_map": {"q": {"node_id": "run", "path": [], "required": None}},
                },
            }
        ],
        "edges": [],
    }
    invalid = [issue for issue in validate_flow(flow) if issue.code == "variable_contract_invalid"]
    assert len(invalid) == 1
    assert invalid[0].level == "warn"


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
                    "skill_slug": "s",
                    "inputs_map": {"q": {"node_id": "later", "path": ["value"]}},
                },
            },
            {"id": "later", "kind": "task", "config": {"skill_slug": "s2"}},
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
                    "skill_slug": "s",
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


# ---------------------------------------------------------------------------
# Phase 1 Flow Builder sources — declarative asset / source nodes.
# ---------------------------------------------------------------------------


def test_asset_without_collection_warns_but_does_not_error() -> None:
    flow = {
        "nodes": [{"id": "asset.x", "kind": "asset", "type": "source.collection", "config": {}}],
        "edges": [],
    }
    issues = validate_flow(flow)
    assert _codes(issues) == {"asset_no_collection"}
    assert not has_errors(issues)


def test_asset_with_collection_is_valid() -> None:
    flow = {
        "nodes": [
            {
                "id": "asset.x",
                "kind": "asset",
                "type": "source.collection",
                "config": {"collection_slug": "andritz-notices", "workspace_scoped": True},
            }
        ],
        "edges": [],
    }
    assert validate_flow(flow) == []


def test_declarative_source_and_asset_exempt_from_orphan_and_unreachable() -> None:
    """An ``asset`` node and a typed declarative ``source.*`` trigger dropped on
    the canvas but not yet wired must NOT block a save (no orphan / unreachable
    error) — they sit upstream of the entry and the run engine ignores them."""
    flow = {
        "nodes": [
            {"id": "src", "kind": "source", "type": "input"},
            {"id": "main", "kind": "task", "config": {"skill_slug": "s1"}},
            {
                "id": "asset.coll",
                "kind": "asset",
                "type": "source.collection",
                "config": {"collection_slug": "c"},
            },
            {"id": "trigger.sftp", "kind": "source", "type": "source.sftp_arrival"},
        ],
        "edges": [{"from": "src", "to": "main"}],
    }
    issues = validate_flow(flow)
    codes = _codes(issues)
    assert "node_orphan" not in codes
    assert "unreachable_node" not in codes
    assert not has_errors(issues)


def test_asset_binding_mismatch_warns_when_collection_ref_points_elsewhere() -> None:
    """A retrieval task fed by an asset via a data edge but whose
    ``inputs_map.collection`` VariableRef points at a DIFFERENT node is an
    incoherent authoritative binding — warn (never error)."""
    flow = {
        "schema_version": 3,
        "nodes": [
            {
                "id": "asset.a",
                "kind": "asset",
                "type": "source.collection",
                "config": {"collection_slug": "coll-a"},
            },
            {
                "id": "asset.b",
                "kind": "asset",
                "type": "source.collection",
                "config": {"collection_slug": "coll-b"},
            },
            {
                "id": "task.retrieve",
                "kind": "task",
                "config": {
                    "skill_slug": "s",
                    # Fed by asset.a (edge below) but binds collection from asset.b.
                    "inputs_map": {"collection": {"node_id": "asset.b", "path": ["collection"]}},
                },
            },
        ],
        "edges": [
            {"from": "asset.a", "to": "task.retrieve", "kind": "data"},
        ],
    }
    issues = validate_flow(flow)
    assert "asset_binding_mismatch" in _codes(issues)
    assert not has_errors(issues)  # warn level only


def test_asset_binding_coherent_is_silent() -> None:
    """When the collection ref points at the SAME asset that feeds the task via a
    data edge (the seeded Phase 2 shape), no mismatch fires."""
    flow = {
        "schema_version": 3,
        "nodes": [
            {
                "id": "asset.a",
                "kind": "asset",
                "type": "source.collection",
                "config": {"collection_slug": "coll-a"},
            },
            {
                "id": "task.retrieve",
                "kind": "task",
                "config": {
                    "skill_slug": "s",
                    "inputs_map": {"collection": {"node_id": "asset.a", "path": ["collection"]}},
                },
            },
        ],
        "edges": [
            {"from": "asset.a", "to": "task.retrieve", "kind": "data"},
        ],
    }
    assert "asset_binding_mismatch" not in _codes(validate_flow(flow))


def test_variable_unresolved_warns_on_missing_declared_port() -> None:
    flow = {
        "schema_version": 3,
        "nodes": [
            {"id": "a", "kind": "source", "outputs": [{"name": "goal", "schema": "string"}]},
            {
                "id": "b",
                "kind": "task",
                "config": {
                    "skill_slug": "s",
                    "inputs_map": {"q": {"node_id": "a", "path": ["nope"]}},
                },
            },
        ],
        "edges": [
            {"from": "a", "to": "b", "kind": "data"},
        ],
    }
    assert "variable_unresolved" in _codes(validate_flow(flow))


def test_ingress_kind_typo_and_non_root_source_are_blocking() -> None:
    typo = {
        "nodes": [
            {
                "id": "webhook",
                "kind": "source",
                "type": "source.webhook",
                "config": {"ingress_kind": "htp"},
            }
        ],
        "edges": [],
    }
    inbound = {
        "nodes": [
            {"id": "entry", "kind": "source"},
            {"id": "nested", "kind": "source"},
        ],
        "edges": [{"from": "entry", "to": "nested"}],
    }

    assert "ingress_kind_invalid" in _codes(validate_flow(typo))
    assert "ingress_source_not_root" in _codes(validate_flow(inbound))
    assert has_errors(validate_flow(typo))
    assert has_errors(validate_flow(inbound))


def _decision_flow(io_mode: str, config_extra: dict | None = None) -> dict:
    config = {
        "branches": [
            {"label": "approved", "condition": "line_manager_approved == True"},
            {"label": "refused", "condition": "line_manager_approved == False"},
        ],
        **(config_extra or {}),
    }
    return {
        "schema_version": 3,
        "io_mode": io_mode,
        "nodes": [
            {"id": "entry", "kind": "source", "outputs": [{"name": "goal", "schema": "string"}]},
            {"id": "route", "kind": "decision", "config": config},
            {"id": "yes", "kind": "sink"},
            {"id": "no", "kind": "sink"},
        ],
        "edges": [
            {"from": "entry", "to": "route"},
            {"from": "route", "to": "yes", "kind": "branch", "branch_label": "approved"},
            {"from": "route", "to": "no", "kind": "branch", "branch_label": "refused"},
        ],
    }


def test_strict_decision_reading_an_unnamed_input_warns_without_blocking() -> None:
    issues = validate_flow(_decision_flow("strict"))

    warning = next(i for i in issues if i.code == "decision_condition_unbound")
    assert warning.level == "warn", "an authoring hint must never block Save"
    assert "line_manager_approved" in warning.message
    assert warning.node_id == "route"


@pytest.mark.parametrize(
    "config_extra",
    [
        {"inputs_map": {"line_manager_approved": {"node_id": "entry", "path": ["goal"]}}},
        {"passthrough_inputs": ["line_manager_approved"]},
    ],
)
def test_a_named_binding_or_passthrough_satisfies_the_predicate(config_extra) -> None:
    """Both halves of strict resolution count as binding the name."""

    assert "decision_condition_unbound" not in _codes(
        validate_flow(_decision_flow("strict", config_extra))
    )


def test_overlay_decisions_are_not_second_guessed_at_design_time() -> None:
    """Overlay merges the whole accumulated ctx, so the name set is not
    decidable from the graph — the runtime check owns that case."""

    assert "decision_condition_unbound" not in _codes(
        validate_flow(_decision_flow("overlay"))
    )
