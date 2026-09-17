"""Mandates use the canonical draft revision and immutable publication boundary."""
from copy import deepcopy

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api.v1.endpoints import mandates, flow_publication as endpoint
from app.models.policy import ControlPolicy
from app.models.system import System
from app.models.system_flow_draft import SystemFlowDraft
from app.models.system_version import SystemVersion
from app.models.knowledge_collection import KnowledgeCollection
from app.models.skill import Skill
from app.models.workspace import Workspace, WorkspaceMember
from app.services import flow_contracts, flow_diff
from app.services.control_policy_snapshot import freeze_control_policy
from app.services.systems import flow_publication as publication, mandate_draft
from app.tests.api.test_flow_publication_api import _seed


@pytest.fixture(autouse=True)
def clean_policy_fixture(db_session):
    # The shared fixture preserves policy ledgers. These test policies belong
    # only to this module and must not affect another module's identical System.
    db_session.query(ControlPolicy).filter_by(target_id="system-publication").delete(synchronize_session=False)
    db_session.commit()
    yield
    db_session.rollback()
    db_session.query(ControlPolicy).filter_by(target_id="system-publication").delete(synchronize_session=False)
    db_session.commit()


def seed(db):
    workspace, user, system = _seed(db)
    app = FastAPI()
    app.include_router(mandates.router)
    app.include_router(endpoint.router, prefix="/systems")
    app.dependency_overrides[mandates.get_current_workspace] = lambda: workspace
    app.dependency_overrides[mandates.get_current_user] = lambda: user
    app.dependency_overrides[mandates.get_db] = lambda: db
    return workspace, user, system, TestClient(app)


def state(api, system):
    response = api.get(f"/systems/{system.id}/mandate/draft")
    assert response.status_code == 200, response.text
    return response.json()


def save(api, system, before, spec):
    return api.put(f"/systems/{system.id}/mandate/draft", json={
        "expected_revision": before["draft"]["revision"],
        "expected_snapshot_sha256": before["draft"]["snapshot_sha256"], "spec": spec,
    })


def publish(db, api, system, workspace, revision, **kw):
    draft = db.get(SystemFlowDraft, system.id)
    contract = publication.compile_execution_contract(db, draft.flow_definition, workspace, system=system)
    return api.post(f"/systems/{system.id}/flow/publish", json={
        "expected_draft_revision": revision, "expected_published_version_id": system.published_flow_version_id,
        "expected_execution_contract_sha256": contract["contract_sha256"],
        "message": "Publish reviewed mandate", "breaking_change_intent": "acknowledged", **kw,
    })


def make_legacy(db, system):
    version = db.get(SystemVersion, system.published_flow_version_id)
    contract = deepcopy(version.execution_contract)
    contract.pop("control_policy_snapshot")
    contract.pop("contract_sha256")
    contract["contract_sha256"] = flow_contracts.canonical_sha256(contract)
    version.execution_contract = contract
    db.get(SystemFlowDraft, system.id).control_policy_snapshot = None
    policy = ControlPolicy(id="legacy-policy", workspace_id=system.workspace_id, scope="system", target_id=system.id,
                           max_cost_per_decision=2, extra={"nonsecret_metadata": "preserved"})
    db.add(policy)
    system.control_policy_id = policy.id
    db.commit()
    return policy


def test_edit_validate_publish_restore_pins_each_version_without_mutating_shared_policy(db_session):
    workspace, user, system, api = seed(db_session)
    policy = make_legacy(db_session, system)
    original_policy = deepcopy(policy.extra)
    original_pointer = system.published_flow_version_id
    before = state(api, system)
    assert before["published"]["policy_binding"] == "legacy"
    assert before["draft"]["spec_is_seed"] is True
    assert before["draft"]["spec"]["outbound"]["expert_review_required"] is False
    spec = deepcopy(before["draft"]["spec"])
    spec["valves"]["max_cost_per_decision"] = 1
    spec["provenance"]["require_citations"] = True
    response = save(api, system, before, spec)
    assert response.status_code == 200, response.text
    current = response.json()
    assert current["draft"]["spec_is_seed"] is False
    assert current["draft"]["revision"] == 2
    assert current["published"]["spec"] != spec
    assert system.published_flow_version_id == original_pointer
    assert policy.max_cost_per_decision == 2 and policy.extra == original_policy
    assert db_session.query(ControlPolicy).filter_by(workspace_id=workspace.id, target_id=system.id).count() == 1
    validation = api.post(f"/systems/{system.id}/mandate/draft/validate", json={
        "expected_revision": 2, "expected_snapshot_sha256": current["draft"]["snapshot_sha256"],
    })
    assert validation.status_code == 200, validation.text
    checks = {row["code"]: row["status"] for row in validation.json()["checks"]}
    assert validation.json()["valid"] and checks["workspace_resources"] == "passed"
    assert checks["runtime_tests"] == checks["provider_availability"] == "not_run"
    draft = db_session.get(SystemFlowDraft, system.id)
    test_run = publication.create_draft_test_run(db_session, system_id=system.id, workspace=workspace,
                    user_id=user.id, input_ref={"case": "verify candidate"}, expected_draft_revision=2,
                    expected_flow_sha256=draft.flow_sha256)
    assert test_run.execution_contract["control_policy_snapshot"] == draft.control_policy_snapshot
    assert system.published_flow_version_id == original_pointer
    db_session.commit()
    published = publish(db_session, api, system, workspace, 2)
    assert published.status_code == 200, published.text
    version = db_session.get(SystemVersion, system.published_flow_version_id)
    first_version = version.id
    frozen = deepcopy(version.execution_contract)
    assert frozen["control_policy_snapshot"]["policy"]["max_cost_per_decision"] == 1
    assert published.json()["draft"]["control_policy_snapshot_sha256"] == frozen["control_policy_snapshot"]["sha256"]
    assert db_session.get(SystemVersion, original_pointer).execution_contract.get("control_policy_snapshot") is None
    # A later mandate publishes another version, not an in-place policy update.
    current = state(api, system)
    spec = deepcopy(current["draft"]["spec"])
    spec["valves"]["max_cost_per_decision"] = 0.5
    assert save(api, system, current, spec).status_code == 200
    assert publish(db_session, api, system, workspace, 3).status_code == 200
    assert db_session.get(SystemVersion, first_version).execution_contract == frozen
    live_pointer = system.published_flow_version_id
    restored = api.post(f"/systems/{system.id}/flow-draft/restore/{first_version}", json={"expected_revision": 3})
    assert restored.status_code == 200, restored.text
    assert db_session.get(SystemFlowDraft, system.id).control_policy_snapshot == frozen["control_policy_snapshot"]
    assert system.published_flow_version_id == live_pointer
    assert restored.json()["revision"] == 4


def test_read_has_no_mutation_and_scope_permissions_do_not_follow_editor_preference(db_session, monkeypatch):
    workspace, user, system, api = seed(db_session)
    before = state(api, system)
    assert state(api, system) == before
    assert before["permissions"]["can_edit"]
    assert before["draft"]["policy_binding"] == "frozen" and before["draft"]["spec_is_seed"] is True
    user.role = "user"
    db_session.add(WorkspaceMember(user_id=user.id, workspace_id=workspace.id, role="viewer", role_template="workspace_viewer"))
    db_session.commit()
    def deny(*args, **kwargs):
        raise HTTPException(403, "Canonical System administration denied")
    monkeypatch.setattr(mandates, "_enforce_system_admin", deny)
    read = api.get(f"/systems/{system.id}/mandate/draft")
    assert read.status_code == 200, read.text
    assert read.json()["permissions"]["can_edit"] is False
    assert save(api, system, before, before["draft"]["spec"]).status_code == 403
    other = System(id="other-tenant-system", workspace_id="other", name="Private")
    db_session.add(other)
    db_session.commit()
    assert api.get(f"/systems/{other.id}/mandate/draft").status_code == 404


def test_cas_rejects_stale_flow_revision_and_unseen_legacy_policy_change(db_session):
    workspace, user, system, api = seed(db_session)
    policy = make_legacy(db_session, system)
    before = state(api, system)
    policy.max_cost_per_decision = 3
    db_session.commit()
    response = save(api, system, before, before["draft"]["spec"])
    assert response.status_code == 409 and response.json()["detail"]["code"] == "MANDATE_SNAPSHOT_MISMATCH"
    fresh = state(api, system)
    assert save(api, system, fresh, fresh["draft"]["spec"]).status_code == 200
    response = save(api, system, fresh, fresh["draft"]["spec"])
    assert response.status_code == 409 and response.json()["detail"]["code"] == "FLOW_DRAFT_REVISION_MISMATCH"
    latest = state(api, system)
    response = save(api, system, latest, latest["draft"]["spec"])
    assert response.status_code == 200 and response.json()["no_op"]
    assert response.json()["draft"]["revision"] == latest["draft"]["revision"]


def test_policy_only_change_requires_reviewed_digest_and_breaking_intent(db_session):
    workspace, user, system, api = seed(db_session)
    before = state(api, system)
    assert save(api, system, before, before["draft"]["spec"]).status_code == 200
    draft = db_session.get(SystemFlowDraft, system.id)
    original = db_session.get(SystemVersion, system.published_flow_version_id)
    target = publication.compile_execution_contract(db_session, draft.flow_definition, workspace, system=system)
    diff = flow_diff.semantic_flow_diff(system.flow_definition, system.flow_definition,
            base_identity="published", target_identity="draft", base_contract=original.execution_contract, target_contract=target)
    assert [c["category"] for c in diff["changes"]] == ["mandate"]
    assert diff["changes"][0]["impact"] == "breaking"
    assert publish(db_session, api, system, workspace, 2, expected_execution_contract_sha256=None).json()["detail"]["code"] == "FLOW_PUBLISH_REVIEW_REQUIRED"
    assert publish(db_session, api, system, workspace, 2, expected_execution_contract_sha256="0"*64).json()["detail"]["code"] == "FLOW_PUBLISH_REVIEW_STALE"
    assert publish(db_session, api, system, workspace, 2, breaking_change_intent=None).json()["detail"]["code"] == "FLOW_BREAKING_CHANGE_INTENT_REQUIRED"
    assert system.published_flow_version_id == original.id


@pytest.mark.parametrize("facet,field,value", [
    ("valves", "token_budget", 3.2), ("valves", "token_budget", True),
    ("valves", "max_cost_per_decision", -1), ("outbound", "gate_if_confidence_below", 2),
    ("valves", "max_latency_ms", "300"), ("outbound", "expert_review_required", "false"),
    ("capabilities", "allowed_skills", ["outside-the-options"]),
    ("capabilities", "allowed_actions", ["write-private"]),
    ("capabilities", "allowed_delegations", [{"system_id": "foreign"}]),
    ("provenance", "object_store_prefix", "private-bucket"),
    ("inbound", "industrial_grounding", True),
])
def test_editor_rejects_unsupported_or_unauthorized_changes(db_session, facet, field, value):
    workspace, user, system, api = seed(db_session)
    before = state(api, system)
    spec = deepcopy(before["draft"]["spec"])
    spec[facet][field] = value
    response = save(api, system, before, spec)
    assert response.status_code == 422, response.text
    assert db_session.get(SystemFlowDraft, system.id).revision == 1


def test_deleted_resource_remains_editable_but_cannot_validate_or_publish(db_session):
    workspace, user, system, api = seed(db_session)
    collection = KnowledgeCollection(id="source", workspace_id=workspace.id, slug="source", name="Readable source",
                                    vector_collection_name="scoped-source", artifact_prefix="source/")
    db_session.add(collection)
    db_session.commit()
    before = state(api, system)
    assert before["options"]["collections"] == [{"id": "source", "label": "Readable source"}]
    spec = deepcopy(before["draft"]["spec"])
    spec["inbound"]["collection_allowlist"] = ["source"]
    assert save(api, system, before, spec).status_code == 200
    db_session.delete(collection)
    db_session.commit()
    validation = api.post(f"/systems/{system.id}/mandate/draft/validate", json={"expected_revision": 2})
    assert validation.status_code == 200, validation.text
    assert validation.json()["valid"] is False
    check = next(c for c in validation.json()["checks"] if c["code"] == "workspace_resources")
    assert check["reason_code"] == "MANDATE_REFERENCE_UNAVAILABLE"
    assert check["details"]["field"] == "inbound.collection_allowlist"
    result = api.post(f"/systems/{system.id}/flow/publish", json={"expected_draft_revision": 2,
            "expected_published_version_id": system.published_flow_version_id, "message": "no", "breaking_change_intent": "acknowledged"})
    assert result.status_code == 422 and result.json()["detail"]["code"] == "MANDATE_REFERENCE_UNAVAILABLE"


def test_invalid_frozen_payload_does_not_fall_back_to_live_policy(db_session):
    workspace, user, system, api = seed(db_session)
    draft = db_session.get(SystemFlowDraft, system.id)
    draft.control_policy_snapshot = None
    version = db_session.get(SystemVersion, system.published_flow_version_id)
    contract = deepcopy(version.execution_contract)
    contract["control_policy_snapshot"] = None
    version.execution_contract = contract
    db_session.commit()
    response = api.get(f"/systems/{system.id}/mandate/draft")
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "FLOW_POLICY_SNAPSHOT_INVALID"


def test_policy_credentials_cannot_enter_public_execution_contract(db_session):
    workspace, user, system, api = seed(db_session)
    policy = make_legacy(db_session, system)
    policy.extra = {"api_key": "never-return-this"}
    db_session.commit()
    response = api.get(f"/systems/{system.id}/mandate/draft")
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == "MANDATE_POLICY_CONTAINS_CREDENTIALS"
    assert "never-return-this" not in response.text
    with pytest.raises(publication.FlowPublicationError) as exc:
        publication.compile_execution_contract(db_session, system.flow_definition, workspace, system=system)
    assert exc.value.code == "MANDATE_POLICY_CONTAINS_CREDENTIALS"


@pytest.mark.parametrize("resource", ["skill", "model"])
def test_unresolved_existing_resource_is_never_green_verified(db_session, resource):
    workspace, user, system, api = seed(db_session)
    policy = make_legacy(db_session, system)
    if resource == "skill":
        policy.allowed_skills = ["deleted-skill"]
    else:
        policy.allowed_models = ["not-configured-model"]
    db_session.commit()
    before = state(api, system)
    assert save(api, system, before, before["draft"]["spec"]).status_code == 200
    validation = api.post(f"/systems/{system.id}/mandate/draft/validate", json={"expected_revision": 2})
    assert validation.status_code == 200, validation.text
    assert validation.json()["valid"] is False
    assert next(c for c in validation.json()["checks"] if c["code"] == "workspace_resources")["reason_code"] == "MANDATE_REFERENCE_UNAVAILABLE"


def test_legacy_v1_delegation_is_preserved_without_implicit_v2_upgrade(db_session):
    workspace, user, system, api = seed(db_session)
    policy = make_legacy(db_session, system)
    policy.extra = {"membrane_spec": {"version": 1, "capabilities": {"allowed_delegations": ["historical-child"]}}}
    db_session.commit()
    before = state(api, system)
    spec = deepcopy(before["draft"]["spec"])
    spec["valves"]["max_cost_per_decision"] = 1
    response = save(api, system, before, spec)
    assert response.status_code == 200, response.text
    assert response.json()["draft"]["spec"]["version"] == 1
    assert response.json()["draft"]["spec"]["capabilities"]["allowed_delegations"] == ["historical-child"]
    assert (policy.extra or {})["membrane_spec"]["version"] == 1


def test_current_policy_drift_after_diff_blocks_publish_without_changing_revision(db_session):
    workspace, user, system, api = seed(db_session)
    policy = make_legacy(db_session, system)
    reviewed = publication.compile_execution_contract(db_session, system.flow_definition, workspace, system=system)
    policy.max_cost_per_decision = 5
    db_session.commit()
    response = publish(db_session, api, system, workspace, 1,
                       expected_execution_contract_sha256=reviewed["contract_sha256"])
    assert response.status_code == 409 and response.json()["detail"]["code"] == "FLOW_PUBLISH_REVIEW_STALE"
    assert db_session.get(SystemFlowDraft, system.id).revision == 1
    assert db_session.get(SystemFlowDraft, system.id).control_policy_snapshot is None


def test_candidate_flow_model_is_selectable_and_statically_validated(db_session):
    workspace, user, system, api = seed(db_session)
    flow = deepcopy(system.flow_definition)
    flow["nodes"][0]["config"]["model"] = "candidate-model"
    response = api.put(f"/systems/{system.id}/flow-draft", json={"expected_revision": 1, "flow_definition": flow})
    assert response.status_code == 200, response.text
    before = state(api, system)
    assert {"id": "candidate-model", "label": "candidate-model"} in before["options"]["models"]
    spec = deepcopy(before["draft"]["spec"])
    spec["capabilities"]["allowed_models"] = ["candidate-model"]
    assert save(api, system, before, spec).status_code == 200
    validation = api.post(f"/systems/{system.id}/mandate/draft/validate", json={"expected_revision": 3})
    assert validation.status_code == 200 and validation.json()["valid"], validation.text
    assert system.flow_definition != flow


def test_nested_delegation_credential_never_leaks_via_draft_or_options(db_session):
    workspace, user, system, api = seed(db_session)
    policy = make_legacy(db_session, system)
    policy.extra = {"membrane_spec": {"version": 2, "enforcement_mode": "shadow", "capabilities": {
        "allowed_delegations": [{"system_id": system.id, "input_contract": {"type": "object", "properties": {
            "api_key": {"type": "string", "default": "never-return-this"}}}}]}}}
    db_session.commit()
    response = api.get(f"/systems/{system.id}/mandate/draft")
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == "MANDATE_POLICY_CONTAINS_CREDENTIALS"
    assert "never-return-this" not in response.text
