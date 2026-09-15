"""Draft corrections preserve published execution and require reviewed provenance."""
from copy import deepcopy
import pytest
from fastapi import HTTPException
from app.models.evaluation import EvaluationScore
from app.models.run import Run
from app.models.skill import Skill
from app.models.system import System
from app.models.system_flow_draft import SystemFlowDraft
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services.evaluation import corrections as c
from app.services.flow_node_overrides import override_executor
from app.services.flow_contracts import compile_execution_contract, FlowContractError
from app.services.run_engine.execution_contract import canonical_flow_sha256


@pytest.fixture
def scenario(db_session):
    db = db_session
    ws = Workspace(id="correction-ws", slug="correction", name="Correction", settings={})
    user = User(id="correction-user", username="correction-user")
    skill = Skill(id="correction-skill", workspace_id=ws.id, slug=f"ws.{ws.id}.reply", name="Reply", type="generation",
        input_schema={"type": "object", "properties": {"question": {"type": "string"}}}, output_schema={"type": "object"},
        executor={"kind": "prompt_template", "params": {"provider": "ollama", "template": "Answer {question}."}}, is_seeded="N")
    flow = {"schema_version": 3, "nodes": [{"id": "entry", "kind": "source"}, {"id": "answer", "kind": "task", "config": {"skill_slug": skill.slug}}, {"id": "result", "kind": "sink"}],
        "edges": [{"from": "entry", "to": "answer"}, {"from": "answer", "to": "result"}]}
    system = System(id="correction-system", workspace_id=ws.id, name="Correction", objective="Reply", skill_ids=[skill.id], flow_definition=deepcopy(flow))
    db.add_all([ws, user, skill, system, WorkspaceMember(workspace_id=ws.id, user_id=user.id, role="member", role_template="workspace_admin")]); db.flush()
    from app.services.systems.flow_publication import compile_execution_contract as compile_published
    contract = compile_published(db, flow, ws, system=system)
    run = Run(id="correction-run", workspace_id=ws.id, system_id=system.id, initiated_by_user_id=user.id, status="completed", execution_contract=contract, flow_snapshot=deepcopy(flow))
    draft = SystemFlowDraft(system_id=system.id, workspace_id=ws.id, flow_definition=deepcopy(flow), revision=1, flow_sha256=canonical_flow_sha256(flow), updated_by=user.id)
    evaluation = EvaluationScore(id="correction-eval", workspace_id=ws.id, run_id=run.id, claim_audit={"claims": [{"text": "Unsupported", "verdict": "unsupported"}]})
    db.add_all([run, draft, evaluation]); db.commit()
    return db, ws, user, skill, system, run, draft


def propose(scenario, **changes):
    db, ws, user, *_ = scenario
    args = dict(run_id="correction-run", node_id="answer", evaluation_id="correction-eval", expected_draft_revision=1,
        replacement_template="Use the supplied evidence for {question}; state missing evidence.", rationale="The evaluated answer contains an unsupported claim.", idempotency_key="request-1")
    args.update(changes)
    return c.create_proposal(db, user=user, workspace=ws, **args)


def apply(scenario, row, **changes):
    db, ws, user, *_ = scenario
    args = dict(proposal_id=row.id, expected_draft_revision=1, reviewed_proposal_sha256=row.proposal_sha256)
    args.update(changes)
    return c.apply_proposal(db, user=user, workspace=ws, **args)


def test_reviewed_apply_is_idempotent_and_never_mutates_skill_or_published_run(scenario):
    db, ws, user, skill, system, run, draft = scenario
    original_skill, original_run, original_flow = deepcopy(skill.executor), deepcopy(run.execution_contract), deepcopy(system.flow_definition)
    row = propose(scenario)
    assert propose(scenario).id == row.id
    with pytest.raises(HTTPException) as error:
        apply(scenario, row, reviewed_proposal_sha256="0" * 64)
    assert error.value.status_code == 409
    apply(scenario, row); db.commit()
    assert draft.revision == 2
    assert apply(scenario, row).applied_revision == 2
    assert skill.executor == original_skill and run.execution_contract == original_run and system.flow_definition == original_flow
    compiled = compile_execution_contract(db, flow=draft.flow_definition, workspace_id=ws.id, runtime_mode="dag")
    assert compiled["nodes"]["answer"]["executor"]["params"]["template"] == row.proposal["replacement_template"]
    assert compiled["nodes"]["answer"]["executor"]["params"]["provider"] == "ollama"


@pytest.mark.parametrize("changed", ["revision", "executor", "flow"])
def test_stale_proposal_refused(scenario, changed):
    db, ws, user, skill, system, run, draft = scenario
    row = propose(scenario)
    if changed == "revision": draft.revision += 1
    if changed == "executor": skill.executor = {"kind": "prompt_template", "params": {"provider": "ollama", "template": "Different {question}."}}
    if changed == "flow": draft.flow_sha256 = "0" * 64
    db.flush()
    with pytest.raises(HTTPException) as error: apply(scenario, row)
    assert error.value.status_code == 409 and row.status == "proposed"


def test_request_key_cannot_be_reused_for_another_patch(scenario):
    propose(scenario)
    with pytest.raises(HTTPException) as error: propose(scenario, rationale="Different")
    assert error.value.status_code == 409


@pytest.mark.parametrize("replacement", ["No placeholders", "{question} {secret}", "", "x" * 8001])
def test_template_boundaries(scenario, replacement):
    with pytest.raises(HTTPException) as error: propose(scenario, replacement_template=replacement)
    assert error.value.status_code == 422


def test_frozen_seeded_node_is_not_a_supported_template(scenario):
    db, ws, user, skill, system, run, draft = scenario
    run.execution_contract = {"nodes": {"answer": {"skill_slug": "llm_rag_answer_v1"}}}
    with pytest.raises(HTTPException) as error: propose(scenario)
    assert error.value.status_code == 422


def test_other_workspace_cannot_read_or_apply(scenario):
    db, ws, user, *_ = scenario
    row = propose(scenario)
    other = Workspace(id="other-correction", slug="other-correction", name="Other", settings={})
    db.add(other); db.flush()
    with pytest.raises(HTTPException) as error: c.get_proposal(db, user=user, workspace=other, proposal_id=row.id)
    assert error.value.status_code == 404


def test_unrelated_evaluation_refused(scenario):
    with pytest.raises(HTTPException) as error: propose(scenario, evaluation_id="other")
    assert error.value.status_code == 404


def test_override_rejects_non_template_executor():
    with pytest.raises(ValueError): override_executor({"kind": "registry_call", "params": {}}, {"prompt_template_override": "Text"})


@pytest.mark.parametrize("node_id,override", [("entry", "Test"), ("answer", "Missing input"), ("answer", "{question} {forbidden}")])
def test_compiler_rejects_invalid_overrides_even_outside_correction_api(scenario, node_id, override):
    db, ws, user, skill, system, run, draft = scenario
    flow = deepcopy(draft.flow_definition)
    next(n for n in flow["nodes"] if n["id"] == node_id).setdefault("config", {})["prompt_template_override"] = override
    with pytest.raises(FlowContractError):
        compile_execution_contract(db, flow=flow, workspace_id=ws.id, runtime_mode="dag")


@pytest.mark.asyncio
async def test_corrected_executor_really_dispatches_frozen_template(scenario, monkeypatch):
    from app.services.skills_registry import executors
    db, ws, user, skill, system, run, draft = scenario
    calls = []
    async def model(payload, ctx):
        calls.append(payload)
        return {"completion": "observed"}
    monkeypatch.setattr(executors, "_seeded_callable", lambda *args, **kwargs: model)
    row = propose(scenario); apply(scenario, row)
    contract = compile_execution_contract(db, flow=draft.flow_definition, workspace_id=ws.id, runtime_mode="dag")
    candidate = executors.bind_executor(contract["nodes"]["answer"]["executor"])
    reference = executors.bind_executor(run.execution_contract["nodes"]["answer"]["executor"])
    await candidate({"question": "Pressure?"}, {})
    await reference({"question": "Pressure?"}, {})
    assert calls[0]["prompt"] == "Use the supplied evidence for Pressure?; state missing evidence."
    assert calls[1]["prompt"] == "Answer Pressure?."


def test_returning_to_run_lists_saved_proposals_without_applying(scenario):
    db, ws, user, skill, system, run, draft = scenario
    row = propose(scenario); db.commit()
    listed = c.list_proposals(db, user=user, workspace=ws, run_id=run.id)
    assert [item.id for item in listed] == [row.id]
    assert listed[0].status == "proposed" and draft.revision == 1
    apply(scenario, row); db.commit()
    assert c.list_proposals(db, user=user, workspace=ws, run_id=run.id)[0].applied_revision == 2


def test_saved_proposal_listing_rechecks_run_and_workspace_access(scenario):
    db, ws, user, skill, system, run, draft = scenario
    propose(scenario)
    other = Workspace(id="list-other", slug="list-other", name="Other", settings={})
    db.add(other); db.flush()
    with pytest.raises(HTTPException) as error: c.list_proposals(db, user=user, workspace=other, run_id=run.id)
    assert error.value.status_code == 404
    with pytest.raises(HTTPException) as error: c.list_proposals(db, user=user, workspace=ws, run_id="missing")
    assert error.value.status_code == 404
