"""New execution contracts pin policy contents, not mutable ControlPolicy rows."""
from copy import deepcopy
import uuid

import pytest

from app.models.decision import Decision
from app.models.policy import ControlPolicy
from app.models.run import Run, SkillInvocation
from app.models.system import System
from app.models.workspace import Workspace
from app.services.control_policy_snapshot import (
    freeze_control_policy, thaw_control_policy, validate_frozen_control_policy,
)
from app.services.flow_contracts import canonical_sha256, compile_execution_contract, validate_execution_contract
from app.services.run_engine import dag, engine
from app.tests.services.test_run_engine_membrane_v2 import _create_contract, _fake_artifact, _install_skill, _spec


@pytest.fixture(autouse=True)
def no_external_jobs(monkeypatch):
    monkeypatch.setattr("app.services.evaluation.auto_eval.schedule_eval", lambda _id: None)
    monkeypatch.setattr(dag, "persist_provenance_artifact", _fake_artifact)


def pin(db, system, run, policy):
    run.flow_snapshot = deepcopy(system.flow_definition)
    contract = compile_execution_contract(db, flow=run.flow_snapshot, workspace_id=system.workspace_id, runtime_mode="dag_overlay")
    contract["control_policy_snapshot"] = freeze_control_policy(policy, workspace_id=system.workspace_id, system_id=system.id)
    contract.pop("contract_sha256")
    contract["contract_sha256"] = canonical_sha256(contract)
    run.execution_contract = validate_execution_contract(contract)
    db.commit()
    return deepcopy(run.execution_contract)


def test_snapshot_is_detached_scoped_and_explicit_absence_never_inherits(db_session):
    system, run = _create_contract(db_session, slug="answer_v1", membrane_spec=_spec())
    policy = db_session.get(ControlPolicy, system.control_policy_id)
    frozen = freeze_control_policy(policy, workspace_id=None, system_id=system.id)
    policy.extra = {"membrane_spec": {"version": 1}}
    value = thaw_control_policy(frozen, workspace_id=None, system_id=system.id)
    assert value.extra["membrane_spec"]["version"] == 2
    value.extra["membrane_spec"]["version"] = 9
    assert frozen["policy"]["extra"]["membrane_spec"]["version"] == 2
    with pytest.raises(ValueError, match="scope_mismatch"):
        thaw_control_policy(frozen, workspace_id="another-workspace", system_id=system.id)
    pin(db_session, system, run, None)
    assert engine._load_control_policy(db_session, system, run=run) is None
    assert engine._load_control_policy(db_session, system).id == policy.id


async def test_two_queued_versions_execute_their_own_policy_after_mutation_and_deletion(db_session, monkeypatch):
    calls = []
    async def answer(_payload, ctx):
        calls.append(ctx["source_policy"]["membrane_spec"]["capabilities"]["allowed_models"])
        return {"answer":"frozen v1", "confidence":0.9, "citations":[{"id":"source"}]}
    _install_skill(monkeypatch, "answer_v1", answer)
    system, first = _create_contract(db_session, slug="answer_v1", membrane_spec=_spec())
    policy = db_session.get(ControlPolicy, system.control_policy_id)
    first_contract = pin(db_session, system, first, policy)
    policy.extra = {"membrane_spec": _spec(capabilities={"allowed_skills":["answer_v1"],"allowed_models":["another-model"],"allowed_actions":["system.engine.run"]})}
    candidate = Run(id=str(uuid.uuid4()), system_id=system.id, status="pending", input_ref={}, execution_surface="draft_test")
    db_session.add(candidate)
    candidate_contract = pin(db_session, system, candidate, policy)
    assert first_contract["control_policy_snapshot"]["sha256"] != candidate_contract["control_policy_snapshot"]["sha256"]
    db_session.delete(policy)
    db_session.commit()
    assert (await dag.execute_run_dag(first.id))["status"] == "completed"
    assert (await dag.execute_run_dag(candidate.id))["status"] == "failed"
    assert calls == [["gpt-test"]]
    db_session.expire_all()
    assert db_session.get(Run, first.id).execution_contract == first_contract
    assert db_session.get(Run, candidate.id).execution_contract == candidate_contract


async def test_hitl_resume_and_replay_keep_frozen_content_when_live_policy_changes(db_session, monkeypatch):
    calls = []
    async def answer(_payload, _ctx):
        calls.append("answer")
        return {"answer":"review me", "confidence":0.4, "citations":[{"id":"source"}]}
    _install_skill(monkeypatch, "answer_v1", answer)
    system, run = _create_contract(db_session, slug="answer_v1", membrane_spec=_spec(outbound={"expert_review_required":False,"gate_if_confidence_below":0.8}))
    policy = db_session.get(ControlPolicy, system.control_policy_id)
    accepted_contract = pin(db_session, system, run, policy)
    paused = await dag.execute_run_dag(run.id)
    assert paused["status"] == "hitl_pending"
    db_session.expire_all()
    policy = db_session.get(ControlPolicy, policy.id)
    policy.extra = {"membrane_spec": _spec(capabilities={"allowed_models":["revoked-live-model"]})}
    decision = db_session.get(Decision, paused["awaiting_decision"])
    decision.status = "accepted"
    db_session.commit()
    result = await dag.resume_run_dag(run.id, decision_id=decision.id)
    assert result["status"] == "completed", result
    assert calls == ["answer"]
    replay = Run(id=str(uuid.uuid4()),system_id=system.id,parent_run_id=run.id,status="pending",trigger="rerun",input_ref={},flow_snapshot=deepcopy(system.flow_definition),execution_contract=deepcopy(accepted_contract))
    db_session.add(replay)
    db_session.commit()
    assert (await dag.execute_run_dag(replay.id))["status"] == "hitl_pending"
    assert calls == ["answer", "answer"]


async def test_tampered_snapshot_fails_before_invocation_without_falling_back(db_session, monkeypatch):
    async def answer(_payload, _ctx):
        pytest.fail("tampered policy must never reach an executor")
    _install_skill(monkeypatch, "answer_v1", answer)
    system, run = _create_contract(db_session, slug="answer_v1", membrane_spec=_spec())
    policy = db_session.get(ControlPolicy, system.control_policy_id)
    accepted = pin(db_session, system, run, policy)
    modified = deepcopy(accepted)
    modified["control_policy_snapshot"]["policy"]["allowed_models"] = ["forged"]
    run.execution_contract = modified
    db_session.commit()
    result = await dag.execute_run_dag(run.id)
    assert result["status"] == "failed"
    assert "control_policy_snapshot_invalid" in result["error"]
    assert db_session.query(SkillInvocation).filter(SkillInvocation.run_id == run.id).count() == 0
    with pytest.raises(ValueError):
        validate_frozen_control_policy(modified["control_policy_snapshot"])


def test_caller_input_cannot_select_a_policy_and_legacy_live_revocation_remains(db_session):
    system, run = _create_contract(db_session, slug="answer_v1", membrane_spec=_spec())
    policy = db_session.get(ControlPolicy, system.control_policy_id)
    run.input_ref = {"execution":{"control_policy_snapshot":freeze_control_policy(None,workspace_id=None,system_id=system.id)}}
    assert engine._load_control_policy(db_session, system, run=run).id == policy.id
    run.status = "debug_pending"
    policy.allowed_models = ["revoked"]
    assert engine._load_control_policy(db_session, system, run=run).allowed_models == ["revoked"]


async def test_debug_resume_uses_frozen_policy_even_if_live_row_is_deleted(db_session, monkeypatch):
    async def answer(_payload, _ctx):
        return {"answer":"frozen debug", "confidence":0.95, "citations":[{"id":"source"}]}
    _install_skill(monkeypatch,"answer_v1",answer)
    system, run = _create_contract(db_session,slug="answer_v1",membrane_spec=_spec())
    policy = db_session.get(ControlPolicy,system.control_policy_id)
    pin(db_session,system,run,policy)
    run.input_ref = {"_debug":{"mode":"step"}}
    db_session.commit()
    paused = await dag.execute_run_dag(run.id)
    assert paused["status"] == "debug_pending", paused
    db_session.expire_all()
    policy = db_session.get(ControlPolicy, policy.id)
    db_session.delete(policy)
    db_session.commit()
    result = await dag.resume_run_dag_debug(run.id,action="continue")
    assert result["status"] == "completed", result
    assert db_session.query(SkillInvocation).filter(SkillInvocation.run_id == run.id).count() == 1


async def test_published_child_and_parent_resume_keep_independent_frozen_mandates(db_session, monkeypatch):
    from app.models.skill import Skill
    from app.services.systems import flow_ingress, flow_publication
    from app.services.run_engine.execution_contract import canonical_flow_sha256

    calls = []
    async def answer(_payload,_ctx):
        calls.append("child")
        return {"answer":"approved child", "confidence":0.95}
    _install_skill(monkeypatch,"child_answer_v1",answer)
    workspace = Workspace(id=str(uuid.uuid4()),slug=f"frozen-child-{uuid.uuid4().hex[:6]}",name="Frozen child",settings={"features":{"flow_publication_v1":True}})
    skill = Skill(id=str(uuid.uuid4()),slug="child_answer_v1",version="v1",name="Child answer",input_schema={},output_schema={},execution={},pricing={},certification_level="basic")
    child_flow = {"schema_version":2,"nodes":[{"id":"source","kind":"source"},{"id":"review","kind":"hitl","config":{"prompt":"Review child"}},{"id":"work","kind":"task","config":{"skill_slug":skill.slug}},{"id":"sink","kind":"sink"}],"edges":[{"from":"source","to":"review"},{"from":"review","to":"work"},{"from":"work","to":"sink"}]}
    child = System(id=str(uuid.uuid4()),workspace_id=workspace.id,name="Child",objective="Child",status="active",skill_ids=[skill.id],default_model="gpt-test",flow_definition=child_flow)
    parent_flow = {"schema_version":2,"nodes":[{"id":"source","kind":"source"},{"id":"delegate","kind":"subflow","config":{"system_id":child.id,"subflow_ingress_kind":"manual"}},{"id":"sink","kind":"sink"}],"edges":[{"from":"source","to":"delegate"},{"from":"delegate","to":"sink"}]}
    parent = System(id=str(uuid.uuid4()),workspace_id=workspace.id,name="Parent",objective="Parent",status="active",skill_ids=[],default_model="gpt-test",flow_definition=parent_flow)
    policies = []
    for system, capabilities in [
        (child,{"allowed_skills":[skill.slug],"allowed_models":["gpt-test"],"allowed_actions":["system.engine.run"]}),
        (parent,{"allowed_models":["gpt-test"],"allowed_actions":["system.engine.run"],"allowed_delegations":[{"system_id":child.id,"branches":["default"],"input_contract":{},"output_contract":{}}]}),
    ]:
        policy = ControlPolicy(id=str(uuid.uuid4()),workspace_id=workspace.id,target_id=system.id,scope="system",extra={"membrane_spec":_spec(capabilities=capabilities,provenance={"require_citations":False})})
        system.control_policy_id = policy.id
        policies.append(policy)
    db_session.add_all([workspace,skill,child,parent,*policies])
    db_session.commit()
    for system in (child,parent):
        flow_publication.initialize_publication_state(db_session,system=system,workspace=workspace,actor="test")
    db_session.commit()
    run = flow_ingress.create_published_ingress_run(db_session,system_id=parent.id,workspace=workspace,ingress_id="source",kind="manual",payload={},expected_published_version_id=parent.published_flow_version_id,expected_flow_sha256=canonical_flow_sha256(parent_flow),adapter_evidence={"surface":"test"})
    db_session.commit()
    first = await dag.execute_run_dag(run.id)
    assert first["status"] == "hitl_pending"
    db_session.expire_all()
    child_run = db_session.query(Run).filter(Run.parent_run_id == run.id).one()
    original_child_contract = deepcopy(child_run.execution_contract)
    assert original_child_contract["control_policy_snapshot"]["system_id"] == child.id
    for policy in policies:
        db_session.get(ControlPolicy,policy.id).extra = {"membrane_spec":_spec(capabilities={"allowed_models":["live-revoked"]})}
    decision = db_session.get(Decision,first["awaiting_decision"])
    decision.status = "accepted"
    db_session.commit()
    result = await dag.resume_run_dag(run.id,decision_id=decision.id)
    assert result["status"] == "completed", result
    assert calls == ["child"]
    db_session.expire_all()
    assert db_session.query(Run).filter(Run.parent_run_id == run.id).count() == 1
    assert db_session.get(Run,child_run.id).execution_contract == original_child_contract
