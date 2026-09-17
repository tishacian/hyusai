"""Frozen mandates also govern projections and block ineffective live actuators."""
from copy import deepcopy
from uuid import uuid4

import pytest

from app.models.run import SkillInvocation
from app.models.system_version import SystemVersion
from app.models.value_loop import ValueActionExecution
from app.services import chat_run_ledger, system_perspective, value_loop
from app.services.control_policy_snapshot import freeze_control_policy
from app.services.flow_contracts import canonical_sha256
from app.services.value_loop_contract import validate_value_loop_runtime_contract
from app.tests.services.test_value_loop import _approved, _seed, ACTUATOR


def publish(db, system, policy):
    contract = {"schema_version": 1, "runtime_mode": "dag_overlay", "validation_mode": "observe",
                "ingresses": [], "nodes": {}, "outputs": [],
                "control_policy_snapshot": freeze_control_policy(policy, workspace_id=system.workspace_id, system_id=system.id)}
    contract["contract_sha256"] = canonical_sha256(contract)
    version = SystemVersion(id=str(uuid4()), system_id=system.id, workspace_id=system.workspace_id,
                            version_number=1, flow_definition={}, execution_contract=contract)
    db.add(version)
    db.flush()
    system.published_flow_version_id = version.id
    db.commit()
    return version


def test_governance_preview_reads_published_policy_not_the_mutated_live_row(db_session):
    workspace, system, policy, _ = _seed(db_session)
    policy.allowed_models = ["published-model"]
    publish(db_session, system, policy)
    policy.allowed_models = ["live-other-model"]
    db_session.commit()
    resolved = system_perspective._control_policy(db_session, workspace.id, system)
    assert resolved.allowed_models == ["published-model"]
    db_session.delete(policy)
    db_session.commit()
    assert system_perspective._control_policy(db_session, workspace.id, system).allowed_models == ["published-model"]


def test_governance_preview_does_not_inherit_current_policy_after_explicit_absence(db_session):
    workspace, system, _, _ = _seed(db_session)
    publish(db_session, system, None)
    assert system_perspective._control_policy(db_session, workspace.id, system) is None


def test_chat_ledger_provenance_uses_the_run_frozen_policy(db_session, monkeypatch):
    _, system, policy, run = _seed(db_session)
    policy.extra = {"membrane_spec": {"version": 2, "enforcement_mode": "enforce",
                    "inbound": {"collection_allowlist": ["frozen-manuals"]}}}
    version = publish(db_session, system, policy)
    run.execution_contract = deepcopy(version.execution_contract)
    policy.extra = {"membrane_spec": {"version": 2, "enforcement_mode": "enforce",
                    "inbound": {"collection_allowlist": ["new-client-documents"]}}}
    invocation = SkillInvocation(id=str(uuid4()), run_id=run.id, skill_slug="audit_log_v1", trace={})
    db_session.add(invocation)
    db_session.commit()
    specs = []
    monkeypatch.setattr("app.services.membrane.enforcement.persist_provenance_artifact",
                        lambda spec, **kwargs: specs.append(spec) or None)
    chat_run_ledger._attach_membrane_provenance(db_session, run, [invocation])
    assert specs[0].inbound.collection_allowlist == ["frozen-manuals"]
    assert invocation.trace["membrane"]["inbound"]["collection_allowlist"] == ["frozen-manuals"]


def test_chat_ledger_explicit_no_policy_cannot_inherit_live_provenance(db_session, monkeypatch):
    _, system, _, run = _seed(db_session)
    run.execution_contract = deepcopy(publish(db_session, system, None).execution_contract)
    invocation = SkillInvocation(id=str(uuid4()), run_id=run.id, skill_slug="audit_log_v1", trace={})
    db_session.add(invocation)
    db_session.commit()
    monkeypatch.setattr("app.services.membrane.enforcement.persist_provenance_artifact",
                        lambda *args, **kwargs: pytest.fail("No frozen provenance policy applies"))
    chat_run_ledger._attach_membrane_provenance(db_session, run, [invocation])
    assert invocation.trace == {}


def test_approved_live_actuator_cannot_claim_to_change_a_frozen_published_mandate(db_session):
    workspace, system, policy, baseline = _seed(db_session)
    scenario, _, decision = _approved(db_session, workspace, system, baseline)
    before = policy.mandatory_hitl_if_confidence_below
    publish(db_session, system, policy)
    readiness = validate_value_loop_runtime_contract(db_session, workspace_id=workspace.id, system=system)
    assert readiness.valid is False and readiness.reason == "mandate_publication_required"
    with pytest.raises(value_loop.ValueLoopConflict) as caught:
        value_loop.act_value_scenario(db_session, workspace_id=workspace.id, scenario_id=scenario.id,
            actuator=ACTUATOR, patch={"mandatory_hitl_if_confidence_below": 0.6},
            actor="operator@example.test", idempotency_key="blocked-frozen-act")
    assert caught.value.code == "mandate_publication_required"
    assert "draft review and publication" in str(caught.value)
    db_session.refresh(policy)
    db_session.refresh(decision)
    assert policy.mandatory_hitl_if_confidence_below == before
    assert decision.status == "accepted"
    assert db_session.query(ValueActionExecution).filter_by(scenario_id=scenario.id).count() == 0


def test_completed_actuator_receipt_still_replays_after_frozen_publication(db_session):
    workspace, system, policy, baseline = _seed(db_session)
    scenario, _, _ = _approved(db_session, workspace, system, baseline)
    request = dict(workspace_id=workspace.id, scenario_id=scenario.id, actuator=ACTUATOR,
                   patch={"mandatory_hitl_if_confidence_below": 0.6}, actor="operator@example.test",
                   idempotency_key="act-before-publication")
    first = value_loop.act_value_scenario(db_session, **request)
    publish(db_session, system, policy)
    replay = value_loop.act_value_scenario(db_session, **request)
    assert replay.id == first.id
    assert db_session.query(ValueActionExecution).filter_by(scenario_id=scenario.id).count() == 1
