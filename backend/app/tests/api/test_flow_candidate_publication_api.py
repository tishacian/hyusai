"""Reviewed publications must not borrow or overwrite an unfinished draft."""

from __future__ import annotations

import copy

import pytest

from app.models.audit import AuditLog
from app.models.policy import ControlPolicy
from app.models.skill import Skill
from app.models.system import System
from app.models.system_flow_draft import SystemFlowDraft
from app.models.system_version import SystemVersion
from app.models.workspace import Workspace, WorkspaceIAMConfig, WorkspaceMember
from app.services.control_policy_snapshot import freeze_control_policy
from app.services.run_engine.execution_contract import canonical_flow_sha256
from app.services.systems import flow_publication
from app.tests.api.test_flow_publication_api import _client, _flow, _seed


def _snapshot(draft):
    return {
        column.name: copy.deepcopy(getattr(draft, column.name))
        for column in draft.__table__.columns
    }


def _request(db, system, flow=None):
    draft = db.get(SystemFlowDraft, system.id)
    flow = _flow("independent-publication") if flow is None else flow
    return {
        "flow_definition": copy.deepcopy(flow),
        "expected_flow_sha256": canonical_flow_sha256(flow),
        "expected_draft_revision": draft.revision,
        "expected_draft_flow_sha256": draft.flow_sha256,
        "expected_published_version_id": system.published_flow_version_id,
    }


def _review(client, system, request):
    response = client.post(f"/systems/{system.id}/flow/review-candidate", json=request)
    assert response.status_code == 200, response.text
    return response.json()


def _publish_request(client, system, request):
    reviewed = _review(client, system, request)
    return {
        **request,
        "expected_execution_contract_sha256": reviewed["candidate"]["execution_contract_sha256"],
        "expected_review_sha256": reviewed["candidate"]["review_sha256"],
        "message": "Publish the reviewed candidate and preserve pending work",
    }


def _assert_unchanged(db, system, before_draft, pointer, versions=1):
    db.expire_all()
    assert _snapshot(db.get(SystemFlowDraft, system.id)) == before_draft
    assert db.get(System, system.id).published_flow_version_id == pointer
    assert db.query(SystemVersion).filter_by(system_id=system.id).count() == versions


def test_candidate_review_and_publish_preserve_all_dirty_draft_columns_and_mandate(db_session):
    workspace, user, system = _seed(db_session, status="paused")
    old_pointer = system.published_flow_version_id
    original = copy.deepcopy(db_session.get(SystemVersion, old_pointer).execution_contract)
    # A realistic incomplete builder draft: a missing Skill is acceptable in
    # an editor, but must never be compiled or accidentally published here.
    unfinished = _flow("unfinished-user-work")
    unfinished["nodes"].append(
        {"id": "unfinished", "kind": "task", "config": {"skill_slug": "not-configured"}}
    )
    draft, _ = flow_publication.save_draft(
        db_session,
        system_id=system.id,
        workspace=workspace,
        flow_definition=unfinished,
        expected_revision=1,
        actor="builder@example.invalid",
    )
    pending = ControlPolicy(
        id="pending-policy",
        workspace_id=workspace.id,
        scope="system",
        target_id=system.id,
        max_cost_per_decision=13,
        allowed_models=[],
        allowed_skills=[],
        extra={},
    )
    draft.control_policy_snapshot = freeze_control_policy(
        pending, workspace_id=workspace.id, system_id=system.id
    )
    db_session.commit()
    before = _snapshot(draft)
    client = _client(db_session, workspace, user)
    request = _request(db_session, system)

    reviewed = _review(client, system, request)
    _assert_unchanged(db_session, system, before, old_pointer)
    assert reviewed["draft_preserved"] is True
    assert (
        reviewed["candidate"]["control_policy_snapshot_sha256"]
        == original["control_policy_snapshot"]["sha256"]
    )
    response = client.post(
        f"/systems/{system.id}/flow/publish-candidate",
        json={
            **request,
            "expected_execution_contract_sha256": reviewed["candidate"][
                "execution_contract_sha256"
            ],
            "expected_review_sha256": reviewed["candidate"]["review_sha256"],
            "message": "Reviewed independent change",
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["draft_preserved"] is True
    assert payload["no_op"] is False
    assert payload["draft"]["no_op"] is True
    db_session.expire_all()
    published = db_session.get(SystemVersion, payload["published"]["version_id"])
    assert published.flow_definition == request["flow_definition"]
    assert (
        published.execution_contract["control_policy_snapshot"]
        == original["control_policy_snapshot"]
    )
    assert published.draft_revision is None
    assert published.version_number == 2
    assert db_session.get(System, system.id).status == "paused"
    assert db_session.get(System, system.id).flow_definition == request["flow_definition"]
    assert _snapshot(db_session.get(SystemFlowDraft, system.id)) == before
    assert db_session.get(SystemVersion, old_pointer).execution_contract == original
    event = db_session.query(AuditLog).filter_by(event_type="flow.published").one()
    assert event.details["publication_source"] == "candidate"
    assert event.details["base_published_version_id"] == old_pointer
    assert event.details["preserved_draft_revision"] == before["revision"]
    assert event.details["draft_revision"] is None


def test_noop_candidate_preserves_dirty_draft_and_does_not_append_version(db_session):
    workspace, user, system = _seed(db_session)
    draft, _ = flow_publication.save_draft(
        db_session,
        system_id=system.id,
        workspace=workspace,
        flow_definition=_flow("dirty"),
        expected_revision=1,
        actor="builder",
    )
    # Even a legacy NULL mandate must remain NULL, not be hydrated as a side effect.
    draft.control_policy_snapshot = None
    db_session.commit()
    before = _snapshot(draft)
    pointer = system.published_flow_version_id
    client = _client(db_session, workspace, user)
    request = _publish_request(client, system, _request(db_session, system, system.flow_definition))
    response = client.post(f"/systems/{system.id}/flow/publish-candidate", json=request)
    assert response.status_code == 200, response.text
    assert response.json()["no_op"] is True
    _assert_unchanged(db_session, system, before, pointer)


@pytest.mark.parametrize("route", ["review-candidate", "publish-candidate"])
@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("expected_draft_revision", 99, "FLOW_DRAFT_REVISION_MISMATCH"),
        ("expected_draft_flow_sha256", "0" * 64, "FLOW_DRAFT_SHA256_MISMATCH"),
        ("expected_published_version_id", "stale-publication", "PUBLISHED_FLOW_VERSION_MISMATCH"),
        ("expected_flow_sha256", "0" * 64, "FLOW_CANDIDATE_SHA256_MISMATCH"),
    ],
)
def test_candidate_stale_preconditions_reject_without_any_writes(
    db_session, route, field, value, code
):
    workspace, user, system = _seed(db_session)
    pointer = system.published_flow_version_id
    before = _snapshot(db_session.get(SystemFlowDraft, system.id))
    client = _client(db_session, workspace, user)
    request = _request(db_session, system)
    if route == "publish-candidate":
        request = _publish_request(client, system, request)
    request[field] = value
    response = client.post(f"/systems/{system.id}/flow/{route}", json=request)
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == code
    _assert_unchanged(db_session, system, before, pointer)


def test_candidate_requires_review_digest_and_rejects_unreviewed_mutation(db_session):
    workspace, user, system = _seed(db_session)
    pointer = system.published_flow_version_id
    before = _snapshot(db_session.get(SystemFlowDraft, system.id))
    client = _client(db_session, workspace, user)
    request = _request(db_session, system)
    missing = client.post(
        f"/systems/{system.id}/flow/publish-candidate", json={**request, "message": "No digest"}
    )
    assert missing.status_code == 422
    request = _publish_request(client, system, request)
    # Changing even a display field changes the Flow identity. Rehashing the
    # candidate cannot make the earlier reviewed execution contract valid.
    request["flow_definition"]["label"] = "unreviewed-change"
    request["expected_flow_sha256"] = canonical_flow_sha256(request["flow_definition"])
    stale = client.post(f"/systems/{system.id}/flow/publish-candidate", json=request)
    assert stale.status_code == 409, stale.text
    assert stale.json()["detail"]["code"] == "FLOW_PUBLISH_REVIEW_STALE"
    _assert_unchanged(db_session, system, before, pointer)


def test_candidate_recompiles_mutable_skill_contract_after_review(db_session):
    workspace, user, system = _seed(db_session)
    skill = Skill(
        id="candidate-skill",
        workspace_id=workspace.id,
        slug="candidate-skill",
        version="1",
        name="Candidate Skill",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        execution={},
    )
    db_session.add(skill)
    system.skill_ids = [skill.id]
    db_session.commit()
    candidate = _flow("skill-candidate")
    candidate["nodes"].insert(
        1, {"id": "task", "kind": "task", "config": {"skill_slug": skill.slug}}
    )
    candidate["edges"] = [{"from": "manual", "to": "task"}, {"from": "task", "to": "result"}]
    before = _snapshot(db_session.get(SystemFlowDraft, system.id))
    pointer = system.published_flow_version_id
    client = _client(db_session, workspace, user)
    request = _publish_request(client, system, _request(db_session, system, candidate))
    skill.output_schema = {
        "type": "object",
        "required": ["new_field"],
        "properties": {"new_field": {"type": "string"}},
    }
    db_session.commit()
    stale = client.post(f"/systems/{system.id}/flow/publish-candidate", json=request)
    assert stale.status_code == 409, stale.text
    assert stale.json()["detail"]["code"] == "FLOW_PUBLISH_REVIEW_STALE"
    _assert_unchanged(db_session, system, before, pointer)


@pytest.mark.parametrize("change", ["io_mode", "input", "output", "ingress"])
def test_candidate_retains_breaking_change_guards(db_session, change):
    workspace, user, system = _seed(db_session)
    candidate = _flow("breaking-change")
    if change == "io_mode":
        candidate["io_mode"] = "strict"
    elif change == "input":
        candidate["nodes"][0]["config"]["input_schema"]["properties"]["case"] = {"type": "integer"}
    elif change == "output":
        candidate["output_contract"] = {
            "type": "object",
            "required": ["answer"],
            "properties": {"answer": {"type": "string"}},
        }
    else:
        candidate["nodes"][0]["config"]["ingress_kind"] = "http"
    client = _client(db_session, workspace, user)
    reviewed = _review(client, system, _request(db_session, system, candidate))
    assert reviewed["breaking_change_intent_required"] is True
    request = _publish_request(client, system, _request(db_session, system, candidate))
    before = _snapshot(db_session.get(SystemFlowDraft, system.id))
    pointer = system.published_flow_version_id
    rejected = client.post(f"/systems/{system.id}/flow/publish-candidate", json=request)
    assert rejected.status_code == 409, rejected.text
    assert rejected.json()["detail"]["code"] == "FLOW_BREAKING_CHANGE_INTENT_REQUIRED"
    _assert_unchanged(db_session, system, before, pointer)
    accepted = client.post(
        f"/systems/{system.id}/flow/publish-candidate",
        json={**request, "breaking_change_intent": "acknowledged"},
    )
    assert accepted.status_code == 200, accepted.text


@pytest.mark.parametrize("invalid", ["shape", "cycle", "unbound_skill"])
def test_candidate_rejects_invalid_graph_before_publication(db_session, invalid):
    workspace, user, system = _seed(db_session)
    pointer = system.published_flow_version_id
    before = _snapshot(db_session.get(SystemFlowDraft, system.id))
    candidate = _flow("invalid")
    if invalid == "shape":
        candidate["nodes"] = [None]
    elif invalid == "cycle":
        candidate["edges"].append({"from": "result", "to": "manual"})
    else:
        candidate["nodes"].insert(
            1, {"id": "task", "kind": "task", "config": {"skill_slug": "unavailable"}}
        )
        candidate["edges"] = [{"from": "manual", "to": "task"}, {"from": "task", "to": "result"}]
    response = _client(db_session, workspace, user).post(
        f"/systems/{system.id}/flow/review-candidate", json=_request(db_session, system, candidate)
    )
    assert response.status_code == 422, response.text
    _assert_unchanged(db_session, system, before, pointer)


@pytest.mark.parametrize("route", ["review-candidate", "publish-candidate"])
def test_candidate_uses_existing_admin_authority_and_workspace_scope(
    db_session, route, attest_authorization_v2
):
    workspace, user, system = _seed(db_session)
    client = _client(db_session, workspace, user)
    request = _request(db_session, system)
    if route == "publish-candidate":
        request = _publish_request(client, system, request)
    user.role = "member"
    workspace.settings = {"features": {"flow_publication_v1": True, "iam_enforced": True}}
    db_session.add(
        WorkspaceMember(
            user_id=user.id,
            workspace_id=workspace.id,
            role="member",
            role_template="workspace_reviewer",
        )
    )
    config = WorkspaceIAMConfig(
        workspace_id=workspace.id,
        role_flags={},
        capability_overrides={
            "authorization_v2": {
                "policy_version": 2,
                "default_mode": "compat",
                "modes": {"system.admin": "enforce"},
            },
        },
    )
    db_session.add(config)
    db_session.commit()
    attest_authorization_v2(config, ["system.admin"])
    db_session.commit()
    denied = client.post(f"/systems/{system.id}/flow/{route}", json=request)
    assert denied.status_code == 403, denied.text
    other = Workspace(id="different-workspace", name="Other", slug="other-workspace")
    db_session.add(other)
    db_session.commit()
    missing = _client(db_session, other, user).post(
        f"/systems/{system.id}/flow/{route}", json=request
    )
    assert missing.status_code == 404


@pytest.mark.parametrize("route", ["review-candidate", "publish-candidate"])
def test_candidate_cannot_accept_caller_policy_override(db_session, route):
    workspace, user, system = _seed(db_session)
    client = _client(db_session, workspace, user)
    request = _request(db_session, system)
    if route == "publish-candidate":
        request = _publish_request(client, system, request)
    request["control_policy_snapshot"] = {"state": "not_configured"}
    rejected = client.post(f"/systems/{system.id}/flow/{route}", json=request)
    assert rejected.status_code == 422


def test_candidate_competing_publications_append_exactly_one_version(db_session):
    workspace, user, system = _seed(db_session)
    client = _client(db_session, workspace, user)
    request = _publish_request(client, system, _request(db_session, system))
    winner = client.post(f"/systems/{system.id}/flow/publish-candidate", json=request)
    assert winner.status_code == 200, winner.text
    loser = client.post(f"/systems/{system.id}/flow/publish-candidate", json=request)
    assert loser.status_code == 409
    assert loser.json()["detail"]["code"] == "PUBLISHED_FLOW_VERSION_MISMATCH"
    assert db_session.query(SystemVersion).filter_by(system_id=system.id).count() == 2


def test_candidate_late_failure_rolls_back_version_pointer_audit_and_preserves_draft(
    db_session, monkeypatch
):
    workspace, user, system = _seed(db_session)
    client = _client(db_session, workspace, user)
    request = _publish_request(client, system, _request(db_session, system))
    before = _snapshot(db_session.get(SystemFlowDraft, system.id))
    pointer = system.published_flow_version_id

    def fail_after_append(*args, **kwargs):
        raise flow_publication.FlowPublicationError(
            "TEST_POST_APPEND_FAILURE", "Injected after flush"
        )

    monkeypatch.setattr(
        "app.services.experience.bindings.retarget_seed_stub_bindings", fail_after_append
    )
    failed = client.post(f"/systems/{system.id}/flow/publish-candidate", json=request)
    assert failed.status_code == 409
    _assert_unchanged(db_session, system, before, pointer)
    assert db_session.query(AuditLog).filter_by(event_type="flow.published").count() == 0


def test_candidate_response_validation_cannot_fail_after_commit(db_session):
    workspace, user, system = _seed(db_session)
    draft = db_session.get(SystemFlowDraft, system.id)
    draft.control_policy_snapshot = {"corrupt": True}
    db_session.commit()
    before = _snapshot(draft)
    pointer = system.published_flow_version_id
    client = _client(db_session, workspace, user)
    # The candidate review inherits the valid published mandate, independent
    # of the invalid pending policy. A rejected response must still be atomic.
    request = _publish_request(client, system, _request(db_session, system))
    rejected = client.post(f"/systems/{system.id}/flow/publish-candidate", json=request)
    assert rejected.status_code == 409
    assert rejected.json()["detail"]["code"] == "FLOW_POLICY_SNAPSHOT_INVALID"
    _assert_unchanged(db_session, system, before, pointer)
    assert db_session.query(AuditLog).filter_by(event_type="flow.published").count() == 0
