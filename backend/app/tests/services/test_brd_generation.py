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
