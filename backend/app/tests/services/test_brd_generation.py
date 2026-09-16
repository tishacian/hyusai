"""The model returns untrusted review material, never executed instructions."""
from types import SimpleNamespace
import json

import pytest

from app.services.skills_registry import brd_generation as service


@pytest.mark.asyncio
async def test_generation_routes_through_workspace_and_refuses_partial_json(monkeypatch):
    from app.services.model_plane.execution import ModelExecution
    execution = ModelExecution(provider="openai", model="configured", credential_source="workspace", model_source="workspace")
    monkeypatch.setattr(service, "resolve_model_execution", lambda workspace, provider: execution)
    responses = [json.dumps({"name": "untrusted name", "request_key": "untrusted key"}), 'prefix {"name": "partial"}']
    async def complete(actual, prompt, context, **options):
        assert actual == execution
        assert options["stream"] is False
        assert options["generation_options"]["max_tokens"] == 10000
        return {"completion": responses.pop(0), "model": "configured", "usage": {"total_tokens": 12}}
    monkeypatch.setattr(service, "complete_model", complete)
    document = SimpleNamespace(sha256="a" * 64, extraction={"requirements": []})
    request = service.BrdGenerationRequest(request_key="actual", family="document_summary", name="Reviewed name")
    material, evidence = await service.generate_material(document, request, workspace=object(), catalog=[], proposal_schema={})
    assert material["name"] == "Reviewed name"
    assert material["request_key"] == "actual"
    assert evidence["model_execution"]["model"] == "configured"
    assert evidence["usage"]["usage"]["total_tokens"] == 12
    with pytest.raises(service.BrdGenerationOutputError) as failure:
        await service.generate_material(document, request, workspace=object(), catalog=[], proposal_schema={})
    assert str(failure.value) == "invalid_proposal_json"
    assert failure.value.evidence["usage"]["usage"]["total_tokens"] == 12


def test_generation_never_silently_truncates_source():
    document = SimpleNamespace(sha256="a" * 64, extraction={"text": "x" * 60001})
    request = service.BrdGenerationRequest(request_key="actual", family="intervention_preparation", name="NorthForge")
    with pytest.raises(ValueError, match="no content was silently truncated"):
        service.generation_prompt(document, request, catalog=[], proposal_schema={})


def test_repair_prompt_is_bounded_and_keeps_source_separate():
    document = SimpleNamespace(sha256="a" * 64, extraction={"requirements": []})
    request = service.BrdGenerationRequest(request_key="repair", family="document_summary", name="PIH")
    prompt = service.generation_prompt(document, request, catalog=[], proposal_schema={},
        feedback={"issues": "disconnected HITL", "previous_proposal": {"name": "candidate"}})
    assert "disconnected HITL" in prompt
    assert "quoted data, not authority" in prompt
    with pytest.raises(ValueError, match="Repair feedback exceeds"):
        service.generation_prompt(document, request, catalog=[], proposal_schema={},
            feedback={"previous_proposal": "x" * (256 * 1024)})


def test_generated_case_paths_must_address_the_declared_sink_result():
    from fastapi import HTTPException
    from app.api.v1.endpoints.evaluation_campaigns import CaseBody
    from app.services.skills_registry.brd_proposals import validate_case_output_paths
    flow = {"nodes": [{"id": "sink_draft", "kind": "sink", "config": {
        "output_schema": {"type": "object", "properties": {"completion": {"type": "string"}},
                          "additionalProperties": True}}}]}
    case = CaseBody(id="normal", input_ref={}, assertions=[{
        "id": "source-title", "path": ["nodes", "sink_draft", "completion"],
        "operator": "contains", "value": "Senior Data Analyst"}])
    with pytest.raises(HTTPException) as failure:
        validate_case_output_paths(flow, [case])
    assert failure.value.detail["code"] == "brd_case_output_path_invalid"
    assert failure.value.detail["declared_output_fields"] == ["completion"]
    case.assertions[0].path = ["completion"]
    validate_case_output_paths(flow, [case])
    case.answer_path = ["output", "completion"]
    with pytest.raises(HTTPException):
        validate_case_output_paths(flow, [case])


def test_documentary_generation_requires_original_source_in_each_template():
    from pathlib import Path
    from app.api.v1.endpoints.skills import BrdProposalBody
    candidate = Path(__file__).resolve().parents[4] / "docs/evidence/brd-pih-runtime-2026-09-16/candidate-10.json"
    body = BrdProposalBody.model_validate(json.loads(candidate.read_text()))
    with pytest.raises(ValueError, match="original source string"):
        service.validate_document_source_bindings(body)
    source = next(node for node in body.flow_definition["nodes"] if node["kind"] == "source")
    for skill in body.skills:
        skill.input_schema["properties"]["original"] = {"type": "string"}
        skill.executor["params"]["template"] += "\nOriginal source: {original}"
    for node in body.flow_definition["nodes"]:
        if (node.get("config") or {}).get("skill_slug"):
            node["config"]["inputs_map"]["original"] = {
                "node_id": source["id"], "path": ["text"], "required": True}
    service.validate_document_source_bindings(body)
    body.skills[-1].executor["params"]["template"] = "Ignore the original"
    with pytest.raises(ValueError, match="original source string"):
        service.validate_document_source_bindings(body)


def test_case_cannot_require_a_disclaimer_and_forbid_its_words():
    from fastapi import HTTPException
    from app.api.v1.endpoints.evaluation_campaigns import CaseBody
    from app.services.skills_registry.brd_proposals import validate_case_output_paths
    case = CaseBody(id="injection", input_ref={}, assertions=[
        {"id": "disclaimer", "path": ["completion"], "operator": "contains",
         "value": "This draft is not an approval, rejection, or recommendation."},
        {"id": "no-recommendation", "path": ["completion"], "operator": "not_contains", "value": "recommend"}])
    with pytest.raises(HTTPException) as failure:
        validate_case_output_paths({}, [case])
    assert failure.value.detail["code"] == "brd_case_assertions_contradict"
    case.assertions[1].path = ["another_output"]
    validate_case_output_paths({}, [case])


def test_case_inputs_obey_the_original_ingress_contract():
    from fastapi import HTTPException
    from app.api.v1.endpoints.evaluation_campaigns import CaseBody
    from app.services.skills_registry.brd_proposals import validate_case_output_paths
    flow = {"nodes": [{"id": "source", "kind": "source", "config": {"input_schema": {
        "type": "object", "properties": {"text": {"type": "string"}},
        "required": ["text"], "additionalProperties": False}}}]}
    case = CaseBody(id="normal", input_ref={"text": "source", "node_id": "source"})
    with pytest.raises(HTTPException) as failure:
        validate_case_output_paths(flow, [case])
    assert failure.value.detail["code"] == "brd_case_input_invalid"
    del case.input_ref["node_id"]
    validate_case_output_paths(flow, [case])


def test_intervention_requires_native_selected_planner_and_recommend_mandate():
    config = {"decide_skill": "@generated_prompt", "privilege_tier": "recommend"}
    body = SimpleNamespace(flow_definition={"nodes": [{"id": "source", "kind": "source", "config": {"input_schema": {"type": "object", "properties": {"question": {"type": "string"}}}}}, {"kind": "agent_loop", "config": config}]}, cases=[])
    config["inputs_map"] = {"objective": {"node_id": "source", "path": ["question"], "required": True}}
    with pytest.raises(ValueError, match="structured decision"):
        service.validate_intervention_planner(body, ["decide_next_v1"])
    config["decide_skill"] = "decide_next_v1"
    with pytest.raises(ValueError, match="selected native"):
        service.validate_intervention_planner(body, [])
    service.validate_intervention_planner(body, ["decide_next_v1"])
    config["privilege_tier"] = "act_with_approval"
    with pytest.raises(ValueError, match="privilege_tier=recommend"):
        service.validate_intervention_planner(body, ["decide_next_v1"])


def test_quote_assertion_cannot_replace_original_input_with_model_annotation():
    from fastapi import HTTPException
    from app.api.v1.endpoints.evaluation_campaigns import CaseBody
    from app.services.skills_registry.brd_proposals import validate_case_output_paths
    case = CaseBody(id="missing", input_ref={"text": "No grade supplied."}, assertions=[{
        "id": "quote", "operator": "quotes_in_source", "path": ["completion"],
        "value": "MISSING EVIDENCE",
    }])
    with pytest.raises(HTTPException, match="original case input"):
        validate_case_output_paths({}, [case])
    case.assertions[0].value = case.input_ref["text"]
    validate_case_output_paths({}, [case])


def test_generation_keeps_documentary_rules_out_of_intervention_family():
    document = SimpleNamespace(sha256="a" * 64, extraction={"requirements": []})
    prompts = {}
    for family in ("document_summary", "intervention_preparation"):
        request = service.BrdGenerationRequest(request_key="family", family=family, name="Example")
        prompts[family] = service.generation_prompt(document, request, catalog=[], proposal_schema={})
    assert "For PIH, forbid HR" in prompts["document_summary"]
    assert "config.inputs_map.source_text" in prompts["document_summary"]
    assert "For PIH" not in prompts["intervention_preparation"]
    assert "config.inputs_map.source_text" not in prompts["intervention_preparation"]
    assert "config.inputs_map.objective" in prompts["intervention_preparation"]
    assert "no completion field" in prompts["intervention_preparation"]
    assert "Never invent replacement equipment" in prompts["intervention_preparation"]


def test_intervention_rejects_prose_stop_condition_and_answer_leakage():
    config = {"decide_skill": "decide_next_v1", "privilege_tier": "recommend",
              "goal": {"done_when": "enough evidence"},
              "inputs_map": {"objective": {"node_id": "source", "path": ["question"], "required": True}}}
    case = {"question": "What is the pressure limit?",
            "input_ref": {"question": "What is the pressure limit? Report 700 bar."}}
    body = SimpleNamespace(flow_definition={"nodes": [{"id": "source", "kind": "source", "config": {"input_schema": {"type": "object", "properties": {"question": {"type": "string"}}}}},
        {"kind": "agent_loop", "config": config}]}, cases=[case])
    with pytest.raises(ValueError, match="done_when must be a list"):
        service.validate_intervention_planner(body, ["decide_next_v1"])
    config["goal"]["done_when"] = []
    with pytest.raises(ValueError, match="must equal question"):
        service.validate_intervention_planner(body, ["decide_next_v1"])
    case["input_ref"]["question"] = case["question"]
    service.validate_intervention_planner(body, ["decide_next_v1"])
