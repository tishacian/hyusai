"""Exercise the real published Flow shape and fail-closed activation inputs."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import jsonschema
import pytest
from workflow_configuration import (
    JUDGE,
    OPERATIONS,
    SCHEDULE,
    WEBHOOK,
    build_flow,
    pin_work_model,
)

ROOT = Path(__file__).resolve().parent


@pytest.fixture
def base():
    return json.loads(
        (ROOT.parent / "showcase_learning/live_learning_plan.json").read_text()
    )["configuration"]


@pytest.fixture
def options():
    return {
        "judge_settings": json.loads((ROOT / "judge_settings.json").read_text()),
        "collection_ids": ["00000000-0000-0000-0000-000000000001"],
        "sla_model": {"id": "reviewed-model", "slug": "reviewed-model", "version": 3},
    }


def test_one_business_flow_keeps_manual_forecast_and_human_authority(base, options):
    from app.services.chains.dag_validator import validate_flow

    original = copy.deepcopy(base["flow_definition"])
    graph = build_flow(original, **options)
    assert original == base["flow_definition"]
    assert len(graph["nodes"]) == 27 and len(graph["edges"]) == 28
    assert not [issue for issue in validate_flow(graph) if issue.level == "error"]
    nodes = {node["id"]: node for node in graph["nodes"]}
    assert [node["id"] for node in graph["nodes"] if node.get("kind") == "source"] == [
        "source.request",
        "source.queue",
        "source.forecast",
        WEBHOOK,
        SCHEDULE,
    ]
    assert graph["runtime_contract"]["ecommerce_ingress_operations"] == OPERATIONS
    assert {"from": JUDGE, "to": "hitl.review", "kind": "data"} in graph["edges"]
    assert {"from": "hitl.review", "to": "task.simulate", "kind": "data"} in graph[
        "edges"
    ]
    assert not any(
        edge["from"] == JUDGE and edge["to"] == "task.simulate"
        for edge in graph["edges"]
    )
    assert nodes[JUDGE]["config"]["on_error"] == "fail"
    assert nodes["sav.score"]["config"]["params"]["pinned_version"] == 3
    assert nodes["forecast.predict"]["config"] == next(
        n["config"] for n in original["nodes"] if n["id"] == "forecast.predict"
    )


def test_signed_webhook_accepts_server_metadata_but_not_extra_business_fields(
    base, options
):
    nodes = {
        node["id"]: node
        for node in build_flow(base["flow_definition"], **options)["nodes"]
    }
    schema = nodes[WEBHOOK]["config"]["input_schema"]
    payload = {
        "claim_id": "RC-1042",
        "_webhook": {
            "hook_id": "hook",
            "system_id": "system",
            "event_type": "webhook.received",
        },
    }
    jsonschema.validate(payload, schema)
    for bad in (
        {**payload, "claim_id": "RC-9999"},
        {**payload, "operation": "queue"},
        {"_webhook": payload["_webhook"]},
    ):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(bad, schema)
    queue_schema = nodes[SCHEDULE]["config"]["input_schema"]
    jsonschema.validate({}, queue_schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"claim_id": "RC-1042"}, queue_schema)


def test_judge_receives_document_passages_and_explicit_unknown_calibration(
    base, options
):
    graph = build_flow(base["flow_definition"], **options)
    judge = next(
        node["config"]["typed_evaluation"]
        for node in graph["nodes"]
        if node["id"] == JUDGE
    )
    assert len(judge["questions"]) == 5
    assert all(q["requires_evidence"] and q["required"] for q in judge["questions"])
    assert "profile_ref" not in judge and "confidence" not in judge
    assert "/citations" in judge["run_evidence"]["sources"][0]["paths"]
    policy = next(
        source
        for source in judge["run_evidence"]["sources"]
        if source["id"] == "policy"
    )
    assert policy["paths"] == ["/citations", "/references"]
    assert judge["tariff"]["model"] == "gpt-5"
    assert judge["budget"]["max_calls"] == 1
    assert judge["budget"]["max_tokens"] == 40000
    assert judge["budget"]["max_cost_usd"] == 0.07
    assert judge["budget"]["max_output_tokens"] == 2048
    assert judge["budget"]["max_prompt_bytes"] == 32000


def test_preserved_draft_keeps_operator_changes_out_of_publication(base, options):
    draft = copy.deepcopy(base["flow_definition"])
    orphan = {
        "id": "operator.prepare",
        "kind": "task",
        "type": "skill",
        "config": {"skill_slug": "data_prep_v1"},
        "position": {"x": 42, "y": 17},
    }
    draft["nodes"].append(orphan)
    draft["nodes"][1]["label"] = "Unpublished wording"
    preserved = build_flow(draft, **options)
    published = build_flow(base["flow_definition"], **options)
    assert (
        next(node for node in preserved["nodes"] if node["id"] == orphan["id"])
        == orphan
    )
    assert preserved["nodes"][1]["label"] == "Unpublished wording"
    assert not any(node["id"] == orphan["id"] for node in published["nodes"])


@pytest.mark.parametrize("settings", [{}, {"budget": {}}, {"budget": {}, "tariff": {}}])
def test_missing_judge_price_or_budget_cannot_be_silently_defaulted(
    base, options, settings
):
    with pytest.raises(ValueError):
        build_flow(base["flow_definition"], **{**options, "judge_settings": settings})


def test_replay_refused_and_work_card_keeps_authored_semantics(base, options):
    graph = build_flow(base["flow_definition"], **options)
    with pytest.raises(ValueError, match="ALREADY_INSTALLED"):
        build_flow(graph, **options)
    original = copy.deepcopy(base["pages"])
    pages = pin_work_model(original, options["sla_model"])
    assert original == base["pages"]
    original_contract = next(
        c["props"]["predictionContract"]
        for p in original["pages"]
        for c in p["components"]
        if "predictionContract" in c.get("props", {})
    )
    contract = next(
        c["props"]["predictionContract"]
        for p in pages["pages"]
        for c in p["components"]
        if "predictionContract" in c.get("props", {})
    )
    assert contract == {
        **original_contract,
        "model_id": "reviewed-model",
        "model_version": 3,
    }
