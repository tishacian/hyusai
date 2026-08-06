from __future__ import annotations

import json

from app.services.flow_diff import edge_identity, semantic_flow_diff


def _flow() -> dict:
    return {
        "schema_version": 3,
        "nodes": [
            {"id": "source", "kind": "source", "label": "Input", "position": {"x": 0, "y": 0}},
            {
                "id": "task",
                "kind": "task",
                "label": "Answer",
                "position": {"x": 100, "y": 0},
                "config": {"skill_slug": "answer-v1", "api_token": "must-never-leak"},
            },
            {"id": "sink", "kind": "sink", "label": "Output"},
        ],
        "edges": [
            {"from": "source", "to": "task", "kind": "data"},
            {"from": "task", "to": "sink", "kind": "data"},
        ],
    }


def test_edge_identity_includes_routing_and_ports() -> None:
    assert edge_identity(
        {
            "from": "decision",
            "to": "sink",
            "kind": "branch",
            "branch_label": "yes",
            "from_port": "yes",
            "to_port": "value",
        }
    ) == (
        '{"branch_label":"yes","from":"decision","from_port":"yes",'
        '"kind":"branch","to":"sink","to_port":"value"}'
    )


def test_semantic_diff_is_deterministic_and_secret_free() -> None:
    base = _flow()
    target = _flow()
    target["nodes"][1]["label"] = "Answer safely"
    target["nodes"][1]["position"] = {"x": 120, "y": 20}
    target["nodes"][1]["config"]["timeout_ms"] = 1200
    target["nodes"][1]["config"]["api_token"] = "new-secret"
    target["edges"].pop()

    first = semantic_flow_diff(base, target, base_identity="published", target_identity="draft")
    second = semantic_flow_diff(base, target, base_identity="published", target_identity="draft")

    assert first == second
    assert first["summary"] == {
        "breaking": 1,
        "behavioral": 1,
        "presentation": 1,
        "total": 3,
    }
    rendered = json.dumps(first)
    assert "must-never-leak" not in rendered
    assert "new-secret" not in rendered
    assert {item["impact"] for item in first["changes"]} == {
        "breaking",
        "behavioral",
        "presentation",
    }


def test_node_removal_and_kind_change_are_breaking() -> None:
    base = _flow()
    target = _flow()
    target["nodes"] = [node for node in target["nodes"] if node["id"] != "sink"]
    target["nodes"][1]["kind"] = "decision"

    result = semantic_flow_diff(base, target, base_identity="version:1", target_identity="draft")
    breaking_subjects = {
        item["subject"] for item in result["changes"] if item["impact"] == "breaking"
    }
    assert {"sink", "task"} <= breaking_subjects


def test_flow_runtime_and_variable_namespace_changes_are_breaking() -> None:
    base = _flow()
    target = _flow()
    base.update({"io_mode": "overlay", "variable_namespaces": ["input", "node"]})
    target.update({"io_mode": "strict", "variable_namespaces": ["input", "node", "memory"]})

    result = semantic_flow_diff(base, target, base_identity="version:1", target_identity="draft")
    breaking_paths = {item["path"] for item in result["changes"] if item["impact"] == "breaking"}
    assert {"io_mode", "variable_namespaces"} <= breaking_paths


def test_variant_and_executable_order_changes_are_breaking() -> None:
    base = _flow()
    target = _flow()
    base["variant"] = "chat_agentic_thinking_v1"
    target["variant"] = "classic"
    target["nodes"] = [target["nodes"][1], target["nodes"][0], target["nodes"][2]]
    target["edges"] = list(reversed(target["edges"]))

    result = semantic_flow_diff(base, target, base_identity="version:1", target_identity="draft")
    breaking_paths = {item["path"] for item in result["changes"] if item["impact"] == "breaking"}

    assert {"variant", "nodes/order", "edges/order"} <= breaking_paths


def test_frozen_execution_contract_change_is_breaking_even_for_same_graph() -> None:
    flow = _flow()
    before = {
        "schema_version": 1,
        "contract_sha256": "before",
        "nodes": {"task": {"output_schema": {"type": "string"}}},
    }
    after = {
        "schema_version": 1,
        "contract_sha256": "after",
        "nodes": {"task": {"output_schema": {"type": "boolean"}}},
    }

    result = semantic_flow_diff(
        flow,
        flow,
        base_identity="published",
        target_identity="draft",
        base_contract=before,
        target_contract=after,
    )

    assert result["summary"] == {
        "breaking": 1,
        "behavioral": 0,
        "presentation": 0,
        "total": 1,
    }
    assert result["changes"][0]["path"] == "execution_contract"
    assert result["base"]["execution_contract_sha256"] == "before"
    assert result["target"]["execution_contract_sha256"] == "after"


def test_legacy_contract_introduction_is_behavioral_but_removal_is_breaking() -> None:
    flow = _flow()
    valid = {
        "schema_version": 1,
        "contract_sha256": "valid",
        "nodes": {"task": {"output_schema": {"type": "string"}}},
    }

    introduced = semantic_flow_diff(
        flow,
        flow,
        base_identity="published",
        target_identity="draft",
        base_contract=None,
        target_contract=valid,
    )
    removed = semantic_flow_diff(
        flow,
        flow,
        base_identity="published",
        target_identity="draft",
        base_contract=valid,
        target_contract=None,
    )

    assert introduced["summary"] == {
        "breaking": 0,
        "behavioral": 1,
        "presentation": 0,
        "total": 1,
    }
    assert removed["summary"] == {
        "breaking": 1,
        "behavioral": 0,
        "presentation": 0,
        "total": 1,
    }
    assert introduced["changes"][0]["path"] == "execution_contract"
    assert removed["changes"][0]["path"] == "execution_contract"


def test_legacy_data_only_skill_binding_change_is_not_diff_invisible() -> None:
    base = _flow()
    target = _flow()
    base["nodes"][1]["config"].pop("skill_slug")
    target["nodes"][1]["config"].pop("skill_slug")
    base["nodes"][1]["data"] = {"bound_skill_slug": "answer-v1"}
    target["nodes"][1]["data"] = {"skill_slug": "answer-v2"}

    result = semantic_flow_diff(
        base,
        target,
        base_identity="published",
        target_identity="draft",
    )

    assert result["summary"]["total"] >= 1
    assert any(
        change["path"] == "nodes/task/contract" and change["impact"] == "behavioral"
        for change in result["changes"]
    )


def test_duplicate_declarations_are_breaking_and_never_diff_invisible() -> None:
    base = _flow()
    target = _flow()
    target["nodes"].append(dict(target["nodes"][-1]))
    target["edges"].append(dict(target["edges"][-1]))

    result = semantic_flow_diff(
        base,
        target,
        base_identity="published",
        target_identity="draft",
    )

    breaking_paths = {item["path"] for item in result["changes"] if item["impact"] == "breaking"}
    assert "nodes/sink/duplicate_declarations" in breaking_paths
    assert any(path.endswith("/duplicate_declarations") for path in breaking_paths)
    assert result["summary"]["breaking"] >= 2
    assert result["summary"]["total"] > 0


def test_edge_identity_does_not_collide_on_user_delimiters() -> None:
    base = _flow()
    base["nodes"].extend(
        [
            {"id": "a|b", "kind": "source"},
            {"id": "a", "kind": "source"},
            {"id": "c", "kind": "sink"},
            {"id": "b|c", "kind": "sink"},
        ]
    )
    base["edges"] = [{"from": "a|b", "to": "c", "kind": "data"}]
    target = json.loads(json.dumps(base))
    target["edges"].append({"from": "a", "to": "b|c", "kind": "data"})

    result = semantic_flow_diff(
        base,
        target,
        base_identity="published",
        target_identity="draft",
    )

    assert result["summary"]["total"] > 0
    assert not any(item["path"].endswith("/duplicate_declarations") for item in result["changes"])


def test_top_level_output_and_unknown_runtime_fields_fail_safe() -> None:
    base = _flow()
    target = _flow()
    target["output_contract"] = {"type": "boolean"}
    target["future_runtime_switch"] = {"mode": "authoritative"}

    result = semantic_flow_diff(
        base,
        target,
        base_identity="published",
        target_identity="draft",
    )

    breaking_paths = {item["path"] for item in result["changes"] if item["impact"] == "breaking"}
    assert {"output_contract", "future_runtime_switch"} <= breaking_paths


def test_top_level_metadata_and_ui_changes_are_presentation_only() -> None:
    base = _flow()
    target = _flow()
    # Presence itself is observable: explicit null must remain presentation,
    # never fall through to the fail-safe breaking bucket.
    target["metadata"] = None
    target["ui"] = {"zoom": 1.25}

    result = semantic_flow_diff(
        base,
        target,
        base_identity="published",
        target_identity="draft",
    )

    assert result["summary"] == {
        "breaking": 0,
        "behavioral": 0,
        "presentation": 2,
        "total": 2,
    }


def test_unknown_node_field_change_gets_unclassified_breaking_fallback() -> None:
    base = _flow()
    target = _flow()
    target["nodes"][1]["future_executor"] = {"mode": "new"}

    result = semantic_flow_diff(
        base,
        target,
        base_identity="published",
        target_identity="draft",
    )

    assert result["summary"] == {
        "breaking": 1,
        "behavioral": 0,
        "presentation": 0,
        "total": 1,
    }
    assert result["changes"][0]["path"] == "flow/unclassified"
