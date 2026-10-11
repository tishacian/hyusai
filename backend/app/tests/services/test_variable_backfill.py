import pytest

from app.models.workspace import Workspace
from app.services.chains.variable_backfill import plan_variable_backfill
from scripts import backfill_flow_v3_variables as backfill_script


def test_legacy_variable_backfill_is_blocked_by_flow_publication() -> None:
    workspace = Workspace(
        id="ws-variable-backfill-publication",
        name="Variable backfill publication",
        slug="variable-backfill-publication",
        settings={"features": {"flow_publication_v1": True}},
    )

    with pytest.raises(RuntimeError, match="backfill is disabled"):
        backfill_script.require_legacy_flow_authority(workspace)


def _flow(selector, *, io_mode="overlay"):
    return {
        "schema_version": 3,
        "io_mode": io_mode,
        "variable_namespaces": ["session"],
        "nodes": [
            {"id": "task.primary", "kind": "task", "config": {}},
            {
                "id": "consumer",
                "kind": "task",
                "config": {"inputs_map": {"query": selector}},
            },
        ],
        "edges": [{"from": "task.primary", "to": "consumer", "kind": "data"}],
    }


def test_backfill_uses_longest_node_id_and_is_idempotent() -> None:
    first = plan_variable_backfill(_flow("task.primary.answer"))
    assert first.status == "converted"
    assert first.conversions == 1
    assert first.flow["nodes"][1]["config"]["inputs_map"]["query"] == {
        "node_id": "task.primary",
        "path": ["answer"],
    }

    second = plan_variable_backfill(first.flow)
    assert second.status == "already_canonical"
    assert second.changed is False
    assert second.conversions == 0


def test_backfill_accepts_declared_namespace() -> None:
    plan = plan_variable_backfill(_flow("session.objective"))
    assert plan.flow["nodes"][1]["config"]["inputs_map"]["query"] == {
        "node_id": "session",
        "path": ["objective"],
    }


def test_ambiguous_ref_stays_string_and_strict_is_downgraded() -> None:
    plan = plan_variable_backfill(_flow("unknown.value", io_mode="strict"))
    assert plan.status == "ambiguous_overlay"
    assert plan.flow["io_mode"] == "overlay"
    assert plan.flow["nodes"][1]["config"]["inputs_map"]["query"] == "unknown.value"
    assert plan.unresolved[0]["reason"] == "unknown_namespace"


def test_empty_dot_path_segment_is_never_converted() -> None:
    plan = plan_variable_backfill(_flow("session..objective", io_mode="strict"))
    assert plan.status == "ambiguous_overlay"
    assert plan.flow["io_mode"] == "overlay"
    assert plan.flow["nodes"][1]["config"]["inputs_map"]["query"] == (
        "session..objective"
    )
    assert plan.unresolved[0]["reason"] == "invalid_path"

    trailing = plan_variable_backfill(_flow("task.primary.", io_mode="strict"))
    assert trailing.status == "ambiguous_overlay"
    assert trailing.unresolved[0]["reason"] == "invalid_path"


def test_pre_v3_flow_is_never_touched() -> None:
    plan = plan_variable_backfill({"schema_version": 2, "nodes": []})
    assert plan.status == "skipped_pre_v3"
    assert plan.changed is False
