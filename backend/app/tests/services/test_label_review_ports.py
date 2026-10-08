from copy import deepcopy

import pytest

from app.services.chains.dag_validator import validate_flow
from app.services.systems.flow_manifest import _unit_for_node


def strict_flow():
    return {"schema_version": 3, "io_mode": "strict", "nodes": [
        {"id": "source", "kind": "source", "outputs": [{"name": "dataset_id", "schema": "string"}]},
        {"id": "review", "kind": "hitl", "outputs": [{"name": "approved", "schema": "boolean"}],
         "config": {"prompt": "Review labels", "prompt_kind": "review_dataset_labels",
                    "inputs_map": {"dataset_id": {"node_id": "source", "path": ["dataset_id"], "required": True}}}},
        {"id": "sink", "kind": "sink", "inputs": [{"name": "dataset_id", "schema": "string"}],
         "config": {"inputs_map": {"dataset_id": {"node_id": "review", "path": ["dataset_id"], "required": True}}}},
    ], "edges": [{"from": "source", "to": "review"}, {"from": "review", "to": "sink"}]}


def test_review_dataset_output_is_derived_even_when_saved_ports_are_old_or_absent():
    flow = strict_flow()
    original = deepcopy(flow)
    assert not validate_flow(flow)
    assert flow == original
    del flow["nodes"][1]["outputs"]
    assert not validate_flow(flow)


@pytest.mark.parametrize("prompt_kind,path", [("approve_write", "dataset_id"), ("review_dataset_labels", "forged")])
def test_declared_ports_cannot_forge_human_gate_output(prompt_kind, path):
    flow = strict_flow()
    flow["nodes"][1]["config"]["prompt_kind"] = prompt_kind
    flow["nodes"][1]["outputs"] = [{"name": path, "schema": "string"}]
    flow["nodes"][2]["config"]["inputs_map"]["dataset_id"]["path"] = [path]
    issues = validate_flow(flow)
    assert any(issue.code == "variable_unresolved" and issue.level == "error" for issue in issues)


def test_manifest_exposes_the_same_runtime_owned_review_contract():
    node = strict_flow()["nodes"][1]
    node["outputs"] = [{"name": "forged", "schema": "string"}]
    implementation = _unit_for_node(node, {})["implementation"]
    assert implementation["input_schema"]["properties"]["dataset_id"] == {"type": "string"}
    properties = implementation["output_schema"]["properties"]
    assert properties["dataset_id"] == {"type": "string"}
    assert properties["rows"] == {"type": "integer"}
    assert "forged" not in properties
    node["config"]["prompt_kind"] = "approve_write"
    assert "dataset_id" not in _unit_for_node(node, {})["implementation"]["output_schema"]["properties"]
