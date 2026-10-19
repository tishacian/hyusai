"""Real adapters delegate explicit current rights without inventing an initiator."""

import json
from datetime import datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import hooks, systems
from app.core.config import settings
from app.models.knowledge_collection import KnowledgeCollection
from app.models.run import Run, SkillInvocation
from app.models.run_schedule import RunSchedule
from app.models.system import System
from app.models.user import User
from app.models.webhook_hook import WebhookHook
from app.models.workspace import Workspace, WorkspaceMember
from app.services import governed_assets
from app.services.evaluation.run_evidence import capture_run_evidence
from app.services.run_engine import scheduler, webhooks
from app.services.run_engine.execution_principal import (
    ExecutionPrincipalError,
    execution_user_id,
)
from app.tests.publication_baseline import baseline_flow_publication


@pytest.fixture
def delegated(db_session, monkeypatch, tmp_path):
    db = db_session
    workspace = Workspace(id=str(uuid4()), name="Events", slug="events-" + uuid4().hex)
    user = User(id=str(uuid4()), username="delegator-" + uuid4().hex, is_active=True)
    db.add_all([workspace, user])
    db.flush()
    membership = WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="member")
    system = System(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name="Event execution",
        status="active",
        settings={"event_trigger": {"mode": "live"}},
        flow_definition={
            "schema_version": 3,
            "nodes": [
                {"id": "hook", "kind": "source", "type": "source.webhook"},
                {"id": "cron", "kind": "source", "type": "source.schedule"},
                {"id": "done", "kind": "sink"},
            ],
            "edges": [
                {"from": "hook", "to": "done", "kind": "control"},
                {"from": "cron", "to": "done", "kind": "control"},
            ],
        },
    )
    db.add_all([membership, system])
    db.commit()
    baseline_flow_publication(db, system)
    app = FastAPI()
    app.include_router(systems.router, prefix="/systems")
    app.include_router(hooks.router, prefix="/hooks")
    app.dependency_overrides[systems.get_current_workspace] = lambda: workspace
    app.dependency_overrides[systems.get_current_user] = lambda: user
    app.dependency_overrides[systems.get_db] = lambda: db
    monkeypatch.setattr(hooks, "SessionLocal", lambda: db)
    monkeypatch.setattr(db, "close", lambda: None)
    monkeypatch.setattr(settings, "enable_event_triggers", True)
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path))
    return SimpleNamespace(
        db=db, ws=workspace, user=user, membership=membership, system=system, client=TestClient(app)
    )


def create_hook(s, **extra):
    response = s.client.post(
        f"/systems/{s.system.id}/hooks",
        json={
            "name": "Signed source",
            "enabled": True,
            "execution_identity": "current_user",
            **extra,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def deliver(s, hook, payload=None):
    body = json.dumps(payload or {"claim": "one"}).encode()
    return s.client.post(
        f"/hooks/{hook['id']}",
        content=body,
        headers={
            webhooks.SIGNATURE_HEADER: "sha256=" + webhooks.compute_signature(hook["secret"], body),
            "content-type": "application/json",
        },
    )


def test_signed_delivery_freezes_delegation_and_deduplicates_without_human_initiator(delegated):
    from app.api.v1.endpoints.runs import _row

    s = delegated
    hook = create_hook(s)
    assert hook["execution_identity"]["user_id"] == s.user.id
    assert "grant_id" not in hook["execution_identity"]
    response = deliver(s, hook, {"claim": "one", "user_id": "injected-admin"})
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "accepted", response.text
    run_id = response.json()["results"][0]["run_id"]
    run = s.db.get(Run, run_id)
    assert run.initiated_by_user_id is None
    assert run.execution_principal["user_id"] == s.user.id
    assert run.execution_principal["source_id"] == hook["id"]
    assert execution_user_id(s.db, run) == s.user.id
    public = _row(run, db=s.db)
    assert public["initiated_by_user_id"] is None
    assert public["execution_principal"]["user_id"] == s.user.id
    assert "grant_id" not in public["execution_principal"]
    duplicate = deliver(s, hook, {"claim": "one", "user_id": "injected-admin"})
    assert duplicate.json()["results"][0]["run_id"] == run_id
    assert s.db.query(Run).count() == 1


def test_creation_without_consent_does_not_infer_creator_or_payload_identity(delegated):
    s = delegated
    hook = create_hook(s, execution_identity=None)
    assert hook["execution_identity"] is None
    response = deliver(s, hook, {"user_id": s.user.id})
    run = s.db.get(Run, response.json()["results"][0]["run_id"])
    assert run.initiated_by_user_id is None and run.execution_principal is None
    assert execution_user_id(s.db, run) is None


def test_identity_api_refuses_arbitrary_user_selection(delegated):
    s = delegated
    response = s.client.post(
        f"/systems/{s.system.id}/hooks",
        json={
            "execution_identity": {"kind": "delegated_user", "user_id": "another-user"},
        },
    )
    assert response.status_code == 422
    assert s.db.query(WebhookHook).count() == 0


@pytest.mark.parametrize("revoke", ["membership", "inactive", "role", "grant"])
def test_revocation_refuses_new_delivery_and_previously_accepted_run(delegated, revoke):
    s = delegated
    hook = create_hook(s)
    response = deliver(s, hook)
    run = s.db.get(Run, response.json()["results"][0]["run_id"])
    if revoke == "membership":
        s.db.delete(s.membership)
    elif revoke == "inactive":
        s.user.is_active = False
    elif revoke == "role":
        s.membership.role = "viewer"
        s.membership.role_template = "workspace_viewer"
    else:
        response = s.client.patch(
            f"/systems/{s.system.id}/hooks/{hook['id']}", json={"execution_identity": "none"}
        )
        assert response.status_code == 200
    s.db.commit()
    with pytest.raises(ExecutionPrincipalError, match="REVOKED|FORBIDDEN"):
        execution_user_id(s.db, run)
    if revoke != "grant":
        assert deliver(s, hook, {"claim": "two"}).status_code == 403


def test_global_admin_without_membership_cannot_delegate(delegated):
    s = delegated
    s.user.role = "admin"
    s.db.delete(s.membership)
    s.db.commit()
    response = s.client.post(
        f"/systems/{s.system.id}/hooks", json={"execution_identity": "current_user"}
    )
    assert response.status_code == 403
    assert s.db.query(WebhookHook).count() == 0


def test_reapplying_same_identity_preserves_grant_and_unrelated_schedule(delegated):
    s = delegated
    hook = create_hook(s)
    source = s.db.get(WebhookHook, hook["id"])
    before = dict(source.execution_identity)
    assert (
        s.client.patch(
            f"/systems/{s.system.id}/hooks/{hook['id']}",
            json={"execution_identity": "current_user"},
        ).status_code
        == 200
    )
    s.db.refresh(source)
    assert source.execution_identity == before
    assert source.enabled is True


def test_native_schedule_records_principal_and_preserves_machine_initiation(delegated, monkeypatch):
    s = delegated
    response = s.client.post(
        f"/systems/{s.system.id}/schedules",
        json={
            "name": "Due queue",
            "cron_expr": "0 8 * * 1-5",
            "timezone": "UTC",
            "enabled": True,
            "execution_identity": "current_user",
            "input_payload": {"user_id": "forged"},
        },
    )
    assert response.status_code == 201, response.text
    sched = s.db.get(RunSchedule, response.json()["id"])
    sched.next_fire_at = datetime.utcnow() - timedelta(minutes=1)
    s.db.commit()
    dispatched = []
    monkeypatch.setattr(scheduler, "_dispatch_run", dispatched.append)
    result = scheduler.scheduler_tick()
    assert result["fired"] == 1
    s.db.refresh(sched)
    run = s.db.get(Run, sched.last_run_id)
    assert run.initiated_by_user_id is None
    assert run.execution_principal["source_type"] == "schedule"
    assert execution_user_id(s.db, run) == s.user.id
    assert dispatched == [run.id]


def test_same_run_judge_snapshot_honors_delegated_source_permissions(delegated):
    s = delegated
    hook = create_hook(s)
    response = deliver(s, hook)
    run = s.db.get(Run, response.json()["results"][0]["run_id"])
    run.status = "running"
    collection = KnowledgeCollection(
        id=str(uuid4()),
        workspace_id=s.ws.id,
        slug="policy",
        name="Policy",
        status="ready",
        vector_collection_name="policy",
        artifact_prefix="policy",
        active_generation="one",
    )
    invocation = SkillInvocation(
        id=str(uuid4()),
        run_id=run.id,
        skill_slug="proposal_v1",
        status="completed",
        output_ref={"action": "review"},
    )
    s.db.add_all([collection, invocation])
    s.db.commit()
    ctx = {"workspace_id": s.ws.id, "run_id": run.id, "user_id": "ignored-payload-user"}
    config = {
        "sources": [{"id": "proposal", "skill_slug": "proposal_v1", "paths": ["/action"]}],
        "native_refs": [{"kind": "document_set", "id": collection.id}],
    }
    reference = capture_run_evidence(s.db, ctx, config, node_id="judge")
    asset = governed_assets.resolve_asset_ref(s.db, s.ws.id, reference)
    assert asset.run_id == run.id and run.initiated_by_user_id is None
    collection.access = {"read": []}
    s.db.commit()
    with pytest.raises(governed_assets.GovernanceError, match="ACCESS_DENIED"):
        capture_run_evidence(s.db, ctx, config, node_id="judge")


def test_other_viewer_cannot_edit_or_rotate_another_users_delegated_source(delegated):
    s = delegated
    hook = create_hook(s)
    schedule_response = s.client.post(
        f"/systems/{s.system.id}/schedules",
        json={
            "cron_expr": "0 8 * * 1-5",
            "execution_identity": "current_user",
            "enabled": False,
        },
    )
    assert schedule_response.status_code == 201
    schedule_id = schedule_response.json()["id"]
    viewer = User(id=str(uuid4()), username="viewer-" + uuid4().hex, is_active=True)
    s.db.add(viewer)
    s.db.flush()
    s.db.add(WorkspaceMember(workspace_id=s.ws.id, user_id=viewer.id, role="viewer"))
    s.db.commit()
    s.client.app.dependency_overrides[systems.get_current_user] = lambda: viewer
    for payload in (
        {"rotate_secret": True},
        {"enabled": False},
        {"execution_identity": "current_user"},
        {"execution_identity": "none"},
    ):
        response = s.client.patch(f"/systems/{s.system.id}/hooks/{hook['id']}", json=payload)
        assert response.status_code == 403
    assert s.client.delete(f"/systems/{s.system.id}/hooks/{hook['id']}").status_code == 403
    for payload in (
        {"input_payload": {"scope": "other"}},
        {"cron_expr": "* * * * *"},
        {"enabled": True},
    ):
        assert (
            s.client.patch(
                f"/systems/{s.system.id}/schedules/{schedule_id}", json=payload
            ).status_code
            == 403
        )
    assert s.client.delete(f"/systems/{s.system.id}/schedules/{schedule_id}").status_code == 403
    source = s.db.get(WebhookHook, hook["id"], populate_existing=True)
    assert source.secret == hook["secret"] and source.execution_identity["user_id"] == s.user.id
    scheduled = s.db.get(RunSchedule, schedule_id, populate_existing=True)
    assert scheduled.input_payload == {} and scheduled.enabled is False


def test_republication_requires_new_consent_and_invalidates_old_grant_when_renewed(delegated):
    from app.models.system_version import SystemVersion
    from app.services.flow_contracts import canonical_sha256
    from app.services.systems.flow_ingress import FlowIngressError, create_published_ingress_run

    s = delegated
    hook = create_hook(s)
    accepted = deliver(s, hook)
    run = s.db.get(Run, accepted.json()["results"][0]["run_id"])
    old_principal = dict(run.execution_principal)
    old_version = s.db.get(SystemVersion, run.published_flow_version_id)
    # A new published identity can share the graph: the execution grant must
    # still be explicitly reviewed, not silently widened by another publisher.
    newer = SystemVersion(
        id=str(uuid4()),
        system_id=s.system.id,
        workspace_id=s.ws.id,
        version_number=old_version.version_number + 1,
        flow_definition=old_version.flow_definition,
        flow_sha256=old_version.flow_sha256,
        execution_contract=old_version.execution_contract,
        release_kind=old_version.release_kind,
    )
    s.db.add(newer)
    s.db.flush()
    s.system.published_flow_version_id = newer.id
    s.db.commit()
    assert deliver(s, hook, {"claim": "two"}).status_code == 403
    # The immutable accepted Run may finish while its existing grant still
    # matches. Renewing the source grant explicitly revokes that old authority.
    assert execution_user_id(s.db, run) == s.user.id
    response = s.client.patch(
        f"/systems/{s.system.id}/hooks/{hook['id']}", json={"execution_identity": "current_user"}
    )
    assert response.status_code == 200, response.text
    source = s.db.get(WebhookHook, hook["id"], populate_existing=True)
    assert source.execution_identity["grant_id"] != old_principal["grant_id"]
    assert source.execution_identity["authority"]["execution_contract_sha256"] == canonical_sha256(
        newer.execution_contract
    )
    with pytest.raises(ExecutionPrincipalError, match="REVOKED"):
        execution_user_id(s.db, run)
    # Race protection also lives inside the locked ingress admission, after
    # resolving the actually accepted publication, rather than only in HTTP.
    with pytest.raises(FlowIngressError, match="reviewed"):
        create_published_ingress_run(
            s.db,
            system_id=s.system.id,
            workspace=s.ws,
            ingress_id="hook",
            kind="http",
            payload={},
            execution_principal=old_principal,
        )


def test_accepted_run_cannot_substitute_a_different_execution_contract(delegated):
    s = delegated
    hook = create_hook(s)
    response = deliver(s, hook)
    run = s.db.get(Run, response.json()["results"][0]["run_id"])
    run.execution_contract = {**run.execution_contract, "changed_after_admission": True}
    s.db.commit()
    with pytest.raises(ExecutionPrincipalError, match="PUBLICATION_CHANGED"):
        execution_user_id(s.db, run)
