"""Publish-time preparation validation without resolving or executing datasets."""

import copy

import pytest

from app.models.skill import Skill
from app.services.chains.dag_validator import validate_flow
from app.services.dataops.flow import data_prep_issues
from app.services.flow_contracts import FlowContractError, compile_execution_contract
from app.services.run_engine.dag import DagGraph, WalkerState, _merge_predecessor_outputs
from app.services.skills_registry.seed import SEED_SKILLS


def prep_node(operation="prepare", *, pins=None):
    outputs = (
        [{"port": "train", "name": "Train"}, {"port": "test", "name": "Test"}]
        if operation == "split"
        else [{"port": "out", "name": "Prepared"}]
    )
    return {
        "id": "prep",
        "kind": "task",
        "config": {
            "skill_slug": "data_prep_v1",
            "params": {
                "data_prep": {
                    "spec": {"operation": operation, "outputs": outputs},
                    "inputs": pins or {},
                }
            },
        },
    }


def prep_flow(operation="prepare", *, pins=None, incoming=None):
    if incoming is None:
        incoming = [{"from": "source", "to": "prep"}]
    return {
        "schema_version": 3,
        "nodes": [
            {"id": "source", "kind": "source"},
            prep_node(operation, pins=pins),
            {"id": "sink", "kind": "sink"},
        ],
        "edges": [
            *incoming,
            {
                "from": "prep",
                "to": "sink",
                **({"from_port": "test"} if operation == "split" else {}),
            },
        ],
    }


def data_config(flow):
    return flow["nodes"][1]["config"]["params"]["data_prep"]


def reasons(flow):
    return {reason for _, reason in data_prep_issues(flow)}


@pytest.mark.parametrize("operation", ["prepare", "aggregate", "pivot", "unpivot", "sample"])
def test_single_input_operations_keep_implicit_in_and_out(operation):
    flow = prep_flow(operation)
    original = copy.deepcopy(flow)
    assert data_prep_issues(flow) == []
    assert flow == original


@pytest.mark.parametrize("representation", ["nested", "direct", "identical"])
@pytest.mark.parametrize("binding", ["canonical", "nested_skill", "data_bound"])
def test_pins_and_canonical_skill_aliases_are_validated(representation, binding):
    flow = prep_flow(pins={"in": {"dataset_id": "immutable-version"}}, incoming=[])
    node = flow["nodes"][1]
    config = node["config"]
    if representation != "nested":
        config["data_prep"] = copy.deepcopy(data_config(flow))
        if representation == "direct":
            config.pop("params")
    if binding == "nested_skill":
        config["skill"] = {"slug": config.pop("skill_slug")}
    elif binding == "data_bound":
        node["data"] = {"bound_skill_slug": config.pop("skill_slug")}
    assert data_prep_issues(flow) == []


@pytest.mark.parametrize("field", ["spec", "inputs", "params"])
def test_malformed_graph_owned_config_returns_a_diagnostic(field):
    flow = prep_flow()
    if field == "params":
        flow["nodes"][1]["config"]["params"] = "invalid"
    else:
        data_config(flow)[field] = []
    assert reasons(flow) == {
        "DATAPREP_SPEC_INVALID"
        if field == "spec"
        else "DATAPREP_INPUTS_INVALID"
        if field == "inputs"
        else "DATAPREP_CONFIG_INVALID"
    }


def test_conflicting_graph_config_is_not_accepted_by_publication():
    flow = prep_flow()
    flow["nodes"][1]["config"]["data_prep"] = {"spec": {}}
    assert reasons(flow) == {"GRAPH_CONFIG_CONFLICT"}


def test_canonical_editor_configuration_uses_external_outputs_and_pinned_sources():
    flow = prep_flow(incoming=[])
    flow["nodes"][1]["config"]["params"] = {
        "spec": {"version": 1, "operation": "prepare", "params": {"steps": []}},
        "outputs": [{"port": "out", "name": "Prepared"}],
        "sources": [{"port": "in", "dataset_id": "immutable-version"}],
        "placement": "local",
        "timeout_s": 300,
    }
    assert data_prep_issues(flow) == []
    flow["edges"].append({"from": "source", "to": "prep", "to_port": "in"})
    assert "DATAPREP_INPUT_PORT_DUPLICATE" in reasons(flow)


@pytest.mark.parametrize("location", ["node", "config", "params", "data_prep"])
def test_inputs_map_is_forbidden_even_when_empty(location):
    flow = prep_flow()
    node = flow["nodes"][1]
    holders = {
        "node": node,
        "config": node["config"],
        "params": node["config"]["params"],
        "data_prep": data_config(flow),
    }
    holders[location]["inputs_map"] = {}
    assert reasons(flow) == {"DATAPREP_INPUTS_MAP_FORBIDDEN"}


@pytest.mark.parametrize(
    "spec_change",
    [
        {"version": 2},
        {"operation": "invented"},
        {"outputs": []},
        {"steps": [{"action": "trim"}] * 201},
        {"seed": -1},
    ],
)
def test_spec_shape_and_bounded_limits_are_checked(spec_change):
    flow = prep_flow()
    data_config(flow)["spec"].update(spec_change)
    assert reasons(flow) == {"DATAPREP_SPEC_INVALID"}


@pytest.mark.parametrize(
    "names", [("Clients préparés", "clients-prepares"), ("A" * 180 + "x", "A" * 180 + "y")]
)
def test_output_names_must_be_unique_after_native_slugification(names):
    flow = prep_flow("split", incoming=[{"from": "source", "to": "prep", "to_port": "in"}])
    for output, name in zip(data_config(flow)["spec"]["outputs"], names):
        output["name"] = name
    assert reasons(flow) == {"DATAPREP_OUTPUT_NAME_DUPLICATE"}


@pytest.mark.parametrize("operation", ["join", "union", "split"])
def test_multiport_operations_and_split_require_to_port(operation):
    assert "DATAPREP_PORT_UNNAMED" in reasons(prep_flow(operation))


def test_join_requires_both_ports_and_accepts_pin_plus_a_distinct_edge():
    flow = prep_flow("join", incoming=[{"from": "source", "to": "prep", "to_port": "left"}])
    assert reasons(flow) == {"DATAPREP_PORT_MISSING"}
    data_config(flow)["inputs"] = {"right": {"dataset_slug": "reference-table"}}
    assert data_prep_issues(flow) == []


@pytest.mark.parametrize("port", ["invented", " in ", "", [], 7])
def test_named_input_ports_cannot_be_ignored_or_coerced(port):
    flow = prep_flow(incoming=[{"from": "source", "to": "prep", "to_port": port}])
    assert reasons(flow) == {
        "DATAPREP_PORT_UNKNOWN" if port == "invented" else "DATAPREP_PORT_UNNAMED"
    }


@pytest.mark.parametrize("pins", [{}, {"in": {"dataset_id": "same"}}])
def test_multiple_edges_or_an_edge_and_a_pin_are_rejected(pins):
    flow = prep_flow(pins=pins)
    if not pins:
        flow["edges"].insert(0, {"from": "source-two", "to": "prep", "to_port": "in"})
    assert reasons(flow) == {"DATAPREP_INPUT_PORT_DUPLICATE"}


@pytest.mark.parametrize("size", [1, 2, 16, 17])
def test_union_has_two_to_sixteen_named_inputs(size):
    pins = {f"in_{i}": {"dataset_id": f"version-{i}"} for i in range(1, size + 1)}
    flow = prep_flow("union", pins=pins, incoming=[])
    assert reasons(flow) == (set() if 2 <= size <= 16 else {"DATAPREP_INPUT_PORTS_INVALID"})


def test_union_declared_ports_cannot_silently_drop_an_unconnected_input():
    flow = prep_flow(
        "union", pins={"in_1": {"dataset_id": "one"}, "in_2": {"dataset_id": "two"}}, incoming=[]
    )
    flow["nodes"][1]["inputs"] = [{"name": f"in_{i}"} for i in range(1, 4)]
    assert reasons(flow) == {"DATAPREP_PORT_MISSING"}


@pytest.mark.parametrize(
    "field,ports,reason",
    [
        ("inputs", [{"name": "in"}, {"name": "in"}], "DATAPREP_PORT_DUPLICATE"),
        ("inputs", [{"name": "other"}], "DATAPREP_INPUT_PORTS_INVALID"),
        ("outputs", [{"name": "other"}], "DATAPREP_OUTPUT_PORTS_INVALID"),
        ("outputs", ["out"], "DATAPREP_PORTS_INVALID"),
    ],
)
def test_declared_visual_ports_must_match_executable_ports(field, ports, reason):
    flow = prep_flow()
    flow["nodes"][1][field] = ports
    assert reasons(flow) == {reason}


@pytest.mark.parametrize("consumer", ["sink", "ml_batch_score_v1", "data_prep_v1"])
@pytest.mark.parametrize(
    "port,reason",
    [
        (None, "DATAPREP_SOURCE_PORT_REQUIRED"),
        ("missing", "DATAPREP_SOURCE_PORT_UNKNOWN"),
        ("train", None),
    ],
)
def test_split_branch_is_selected_for_every_consumer(consumer, port, reason):
    flow = prep_flow("split", incoming=[{"from": "source", "to": "prep", "to_port": "in"}])
    if consumer != "sink":
        target = (
            prep_node()
            if consumer == "data_prep_v1"
            else {"config": {"skill_slug": consumer}, "kind": "task"}
        )
        target["id"] = "sink"
        flow["nodes"][2] = target
    if port is None:
        flow["edges"][-1].pop("from_port")
    else:
        flow["edges"][-1]["from_port"] = port
    assert reasons(flow) == ({reason} if reason else set())


def test_control_edges_do_not_satisfy_a_required_dataset_input():
    flow = prep_flow(incoming=[{"from": "source", "to": "prep", "kind": "control"}])
    assert reasons(flow) == {"DATAPREP_PORT_MISSING"}


@pytest.mark.parametrize("kind", ["data", "control", "branch", "error", None])
@pytest.mark.parametrize("aliases", [False, True])
def test_split_port_validation_matches_the_merge_for_every_transported_edge(kind, aliases):
    flow = prep_flow("split", incoming=[{"from": "source", "to": "prep", "to_port": "in"}])
    source, target = ("source", "target") if aliases else ("from", "to")
    edge = {source: "prep", target: "sink", "kind": kind}
    flow["edges"][-1] = edge
    state = WalkerState(
        node_outputs={
            "prep": {
                "outputs": {
                    "train": {"dataset_id": "train-version"},
                    "test": {"dataset_id": "test-version"},
                }
            }
        }
    )
    assert reasons(flow) == {"DATAPREP_SOURCE_PORT_REQUIRED"}
    with pytest.raises(ValueError, match="DATAPREP_SOURCE_PORT_REQUIRED"):
        _merge_predecessor_outputs(DagGraph.from_flow_definition(flow), state, "sink")
    edge["from_port"] = "test"
    assert data_prep_issues(flow) == []
    assert _merge_predecessor_outputs(DagGraph.from_flow_definition(flow), state, "sink") == {
        "dataset_id": "test-version"
    }


def test_input_aliases_and_null_edge_kind_preserve_the_scoring_ingress():
    flow = prep_flow(incoming=[{"source": "source", "target": "prep", "kind": None}])
    assert data_prep_issues(flow) == []
    assert DagGraph.from_flow_definition(flow).in_edges["prep"][0].kind == "data"


def test_malformed_edge_items_are_left_to_the_shape_validator_without_crashing():
    flow = prep_flow()
    flow["edges"].append(None)
    assert data_prep_issues(flow) == []
    assert [issue.code for issue in validate_flow(flow)] == ["edge_invalid"]


def test_both_publication_entrypoints_fail_before_dataset_or_skill_resolution(db_session):
    flow = prep_flow(incoming=[])
    diagnostics = [issue for issue in validate_flow(flow) if issue.code == "data_prep_invalid"]
    assert [(issue.level, issue.node_id, issue.message) for issue in diagnostics] == [
        ("error", "prep", "DATAPREP_PORT_MISSING")
    ]
    with pytest.raises(FlowContractError) as error:
        compile_execution_contract(
            db_session, flow=flow, workspace_id=None, runtime_mode="dag_overlay"
        )
    assert error.value.code == "data_prep_invalid"
    assert error.value.path == "nodes/prep/config"
    assert error.value.message == "DATAPREP_PORT_MISSING"


def test_valid_scoring_ingress_compiles_the_derived_output_contract(db_session):
    definition = next(skill for skill in SEED_SKILLS if skill["slug"] == "data_prep_v1")
    db_session.add(Skill(**copy.deepcopy(definition)))
    db_session.flush()
    flow = prep_flow()
    flow["io_mode"] = "strict"
    assert not [issue for issue in validate_flow(flow) if issue.level == "error"]
    contract = compile_execution_contract(
        db_session, flow=flow, workspace_id=None, runtime_mode="dag_strict"
    )
    outputs = contract["nodes"]["prep"]["output_schema"]["properties"]["outputs"]
    assert outputs["required"] == ["out"]
    assert set(outputs["properties"]) == {"out"}
    assert outputs["additionalProperties"] is False
