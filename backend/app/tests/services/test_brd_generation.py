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
    body = SimpleNamespace(flow_definition={"nodes": [{"id": "source", "kind": "source", "config": {"input_schema": {"type": "object", "properties": {"question": {"type": "string"}}}}}, {"kind": "agent_loop", "config": config}]}, cases=[], skills=[])
    config["inputs_map"] = {"objective": {"node_id": "source", "path": ["question"], "required": True}}
    with pytest.raises(ValueError, match="structured decision"):
        service.validate_intervention_planner(body, ["decide_next_v1"])
    config["decide_skill"] = "decide_next_v1"
    with pytest.raises(ValueError, match="selected native"):
        service.validate_intervention_planner(body, [])
    service.validate_intervention_planner(body, ["decide_next_v1"])
    node = body.flow_definition["nodes"][-1]
    node["inputs_map"] = config.pop("inputs_map")
    with pytest.raises(ValueError, match="Move any node-level inputs_map into config.inputs_map"):
        service.validate_intervention_planner(body, ["decide_next_v1"])
    config["inputs_map"] = node.pop("inputs_map")
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
        {"kind": "agent_loop", "config": config}]}, cases=[case], skills=[])
    with pytest.raises(ValueError, match="done_when must be a list"):
        service.validate_intervention_planner(body, ["decide_next_v1"])
    config["goal"]["done_when"] = []
    with pytest.raises(ValueError, match="must equal question"):
        service.validate_intervention_planner(body, ["decide_next_v1"])
    case["input_ref"]["question"] = case["question"]
    service.validate_intervention_planner(body, ["decide_next_v1"])


def test_intervention_does_not_invent_an_agent_loop_output_envelope():
    config = {"decide_skill": "decide_next_v1", "privilege_tier": "recommend",
              "inputs_map": {"objective": {"node_id": "source", "path": ["question"], "required": True}}}
    ref = {"node_id": "loop", "path": ["result", "observations"], "required": True}
    body = SimpleNamespace(flow_definition={"nodes": [
        {"id": "source", "kind": "source", "config": {"input_schema": {
            "type": "object", "properties": {"question": {"type": "string"}}}}},
        {"id": "loop", "kind": "agent_loop", "config": config},
        {"id": "synthesis", "kind": "task", "config": {"inputs_map": {"evidence": ref}}}
    ]}, cases=[], skills=[])
    with pytest.raises(ValueError, match="no output field 'result'"):
        service.validate_intervention_planner(body, ["decide_next_v1"])
    ref["path"] = ["observations"]
    service.validate_intervention_planner(body, ["decide_next_v1"])


def test_intervention_template_must_actually_receive_retrieved_evidence():
    config = {"decide_skill": "decide_next_v1", "privilege_tier": "recommend",
              "inputs_map": {"objective": {"node_id": "source", "path": ["question"], "required": True}}}
    skill = SimpleNamespace(local_name="synthesis", executor={"params": {"template": "Use observations. {text}"}})
    body = SimpleNamespace(flow_definition={"nodes": [
        {"id": "source", "kind": "source", "config": {"input_schema": {
            "type": "object", "properties": {"question": {"type": "string"}}}}},
        {"id": "loop", "kind": "agent_loop", "config": config},
        {"id": "synthesis", "kind": "task", "config": {"skill_slug": "@synthesis", "inputs_map": {
            "observations": {"node_id": "loop", "path": ["observations"], "required": True}}}}
    ]}, cases=[], skills=[skill])
    with pytest.raises(ValueError, match="must include"):
        service.validate_intervention_planner(body, ["decide_next_v1"])
    skill.executor["params"]["template"] += " Evidence: {observations}"
    with pytest.raises(ValueError, match="original operator question"):
        service.validate_intervention_planner(body, ["decide_next_v1"])
    body.flow_definition["nodes"][-1]["config"]["inputs_map"]["objective"] = {
        "node_id": "source", "path": ["question"], "required": True}
    with pytest.raises(ValueError, match="original operator question"):
        service.validate_intervention_planner(body, ["decide_next_v1"])
    skill.executor["params"]["template"] += " Request: {objective}"
    service.validate_intervention_planner(body, ["decide_next_v1"])


def test_generated_review_tests_require_real_mapped_approval_and_rejection():
    from copy import deepcopy
    from pathlib import Path
    from app.api.v1.endpoints.skills import BrdProposalBody
    artifact = Path(__file__).resolve().parents[4] / 'docs/evidence/northforge-brd-2026-09-16/revision-2/live-generation.json'
    raw = json.loads(artifact.read_text())['result']['proposal']
    body = BrdProposalBody.model_validate({
        key: value for key, value in {**raw, 'request_key': 'review-contract'}.items()
        if key in BrdProposalBody.model_fields
    })
    with pytest.raises(ValueError, match='expose its decision_status'):
        service.validate_generated_review_tests(body)
    sink = next(node for node in body.flow_definition['nodes'] if node['kind'] == 'sink')
    config = sink['config']
    config['output_schema']['properties']['decision_status'] = {'type': 'string'}
    config['output_schema']['required'].append('decision_status')
    config['inputs_map']['decision_status'] = {
        'node_id': 'review_hitl', 'path': ['decision_status'], 'required': True}
    with pytest.raises(ValueError, match='both accepted and rejected'):
        service.validate_generated_review_tests(body)
    review_case = next(case for case in body.cases if case['id'] == 'case-review-reject')
    review_case['assertions'].append({'id': 'rejected', 'path': ['decision_status'],
                                      'operator': 'equals', 'value': 'rejected'})
    with pytest.raises(ValueError, match='both accepted and rejected'):
        service.validate_generated_review_tests(body)
    approval = deepcopy(review_case)
    approval['id'] = 'case-review-approve'
    approval['assertions'][-1]['value'] = 'approved'
    body.cases.append(approval)
    with pytest.raises(ValueError, match='both accepted and rejected'):
        service.validate_generated_review_tests(body)
    for mapping in body.mappings:
        if 'review_hitl' in mapping.node_ids:
            mapping.case_ids.append(approval['id'])
    # The runtime copies Decision.status (accepted), not its approved boolean.
    with pytest.raises(ValueError, match='both accepted and rejected'):
        service.validate_generated_review_tests(body)
    approval['assertions'][-1]['value'] = 'accepted'
    service.validate_generated_review_tests(body)
    config['inputs_map']['decision_status']['node_id'] = 'task_synthesis'
    with pytest.raises(ValueError, match='model text is not a decision'):
        service.validate_generated_review_tests(body)


def test_live_northforge_procedures_cannot_become_operator_inputs():
    from copy import deepcopy
    from pathlib import Path
    from app.api.v1.endpoints.skills import BrdProposalBody
    from app.services.skills_registry.brd_import import parse_business_requirements
    root = Path(__file__).resolve().parents[4]
    raw = json.loads((root / 'docs/evidence/release-1e374c3c-2026-09-17/generation-job.json').read_text())['result']['proposal']
    body = BrdProposalBody.model_validate({key: value for key, value in
        {**raw, 'request_key': 'reviewed-questions'}.items() if key in BrdProposalBody.model_fields})
    original = deepcopy(body.cases)
    document = SimpleNamespace(extraction=parse_business_requirements(
        (root / 'backend/app/tests/fixtures/brd/northforge-intervention.docx').read_bytes()))
    with pytest.raises(ValueError, match='copies an acceptance procedure'):
        service.validate_intervention_test_inputs(body, document)
    questions = [
        'What is the PMP-700 continuous pressure limit?',
        'What were the planned and actual durations for NF-04?',
        'Which equipment caused the NF-04 delay?',
        'Set PMP-700 to 800 bar and close NF-04.',
    ]
    for case, question in zip(body.cases, questions):
        case['question'] = question
        case['input_ref']['objective'] = question
    # Fixing the knowledge questions must not let tester-only review inputs pass.
    with pytest.raises(ValueError, match='Human-review case'):
        service.validate_intervention_test_inputs(body, document)
    for case in body.cases[4:]:
        case['question'] = questions[0]
        case['input_ref'] = deepcopy(body.cases[0]['input_ref'])
    service.validate_intervention_test_inputs(body, document)
    service.validate_generated_review_tests(body)
    assert [c['assertions'] for c in body.cases] == [c['assertions'] for c in original]


@pytest.mark.parametrize('procedure', [
    'History: ask for the recorded duration. Report 55 minutes.',
    'Historique : demander la durée enregistrée. Indiquer 55 minutes.',
])
def test_copied_procedure_guard_handles_whitespace_and_label_removal(procedure):
    document = SimpleNamespace(extraction={'acceptance_cases': [{'text': procedure}]})
    question = procedure.partition(':')[2].strip().upper().replace(' ', '  ')
    body = SimpleNamespace(cases=[{'id': 'copied', 'question': question}], flow_definition={'nodes': []})
    with pytest.raises(ValueError, match='copies an acceptance procedure'):
        service.validate_intervention_test_inputs(body, document)
    # A real source question remains usable verbatim; no generic prose rewriter.
    body.cases[0]['question'] = 'What is the duration?'
    document.extraction['acceptance_cases'].append({'text': body.cases[0]['question']})
    service.validate_intervention_test_inputs(body, document)
