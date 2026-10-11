"""Endpoint proofs for the Lot 7 authorization-v2 rollout boundaries."""

from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import actions, client360, hypervisor
from app.core.iam.roles import WORKSPACE_CONTRIBUTOR
from app.models.audit import AuditLog
from app.models.capability import Capability
from app.models.decision import Decision
from app.models.expert_capture import ExpertCaptureSession
from app.models.system import System
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceIAMConfig, WorkspaceMember
from app.services.client360_contract import (
    CLIENT360_CAPABILITY_SLUG,
    CLIENT360_SYSTEM_VARIANT,
)


def _seed_contributor(db_session, *, suffix: str, settings: dict | None = None):
    workspace = Workspace(
        id=f"ws-authz-v2-{suffix}",
        slug=f"authz-v2-{suffix}",
        name=f"Authorization v2 {suffix}",
        settings=settings or {},
    )
    user = User(
        id=f"user-authz-v2-{suffix}",
        username=f"authz-v2-{suffix}",
        email=f"authz-v2-{suffix}@example.test",
    )
    membership = WorkspaceMember(
        workspace_id=workspace.id,
        user_id=user.id,
        role="member",
        role_template=WORKSPACE_CONTRIBUTOR,
    )
    db_session.add_all([workspace, user, membership])
    db_session.commit()
    return workspace, user


def _seed_client360_authority(db_session, workspace: Workspace, *, suffix: str):
    capability = Capability(
        id=f"cap-client360-{suffix}",
        workspace_id=workspace.id,
        slug=CLIENT360_CAPABILITY_SLUG,
        name="Client360 Opportunity Engine",
        tier="client",
    )
    system = System(
        id=f"system-client360-{suffix}",
        workspace_id=workspace.id,
        name="Client360 test authority",
        objective="Exercise the Client360 authorization boundary.",
        capability_id=capability.id,
        status="active",
        settings={"system_type": CLIENT360_SYSTEM_VARIANT},
        flow_definition={"variant": CLIENT360_SYSTEM_VARIANT},
    )
    db_session.add_all([capability, system])
    db_session.commit()
    return system, capability


def _set_mode(
    db_session,
    *,
    workspace: Workspace,
    user: User,
    key: str,
    mode: str,
) -> WorkspaceIAMConfig:
    config = db_session.query(WorkspaceIAMConfig).filter_by(workspace_id=workspace.id).first()
    document = {
        "authorization_v2": {
            "policy_version": 2,
            "default_mode": "compat",
            "modes": {key: mode},
        }
    }
    if config is None:
        config = WorkspaceIAMConfig(
            workspace_id=workspace.id,
            version=1,
            role_flags={},
            capability_overrides=document,
            updated_by_user_id=user.id,
        )
        db_session.add(config)
    else:
        config.capability_overrides = document
        config.version = int(config.version or 0) + 1
    db_session.commit()
    return config


def _client(db_session, workspace, user, module, prefix: str) -> TestClient:
    app = FastAPI()
    app.include_router(module.router, prefix=prefix)
    app.dependency_overrides[module.get_current_workspace] = lambda: workspace
    app.dependency_overrides[module.get_current_user] = lambda: user
    app.dependency_overrides[module.get_db] = lambda: db_session
    return TestClient(app)


def test_hypervisor_actor_is_token_derived_and_decision_approve_rolls_out(
    db_session,
    attest_authorization_v2,
):
    workspace, user = _seed_contributor(db_session, suffix="hypervisor")
    config = _set_mode(
        db_session,
        workspace=workspace,
        user=user,
        key="decision.approve",
        mode="shadow",
    )
    shadow_decision = Decision(
        id="decision-authz-v2-shadow",
        workspace_id=workspace.id,
        scope="capability",
        kind="recommendation",
        status="proposed",
        title="Shadow decision",
    )
    db_session.add(shadow_decision)
    db_session.commit()
    client = _client(db_session, workspace, user, hypervisor, "/hypervisor")

    shadow_response = client.post(
        f"/hypervisor/decisions/{shadow_decision.id}/accept",
        json={"actor": "spoofed-admin@example.test", "note": "Reviewed"},
    )

    assert shadow_response.status_code == 200
    db_session.refresh(shadow_decision)
    assert shadow_decision.approved_by == user.email
    assert shadow_decision.approved_by != "spoofed-admin@example.test"
    diff = db_session.query(AuditLog).filter_by(
        workspace_id=workspace.id,
        event_type="iam.shadow.diff",
    ).one()
    assert diff.details["resource"]["kind"] == "decision"
    assert diff.details["action"] == "decision.approve"
    assert diff.details["legacy_allowed"] is True
    assert diff.details["candidate_allowed"] is False

    enforce_decision = Decision(
        id="decision-authz-v2-enforce",
        workspace_id=workspace.id,
        scope="capability",
        kind="recommendation",
        status="proposed",
        title="Enforce decision",
    )
    db_session.add(enforce_decision)
    _set_mode(
        db_session,
        workspace=workspace,
        user=user,
        key="decision.approve",
        mode="enforce",
    )
    attest_authorization_v2(config, ["decision.approve"])
    db_session.commit()

    enforce_response = client.post(
        f"/hypervisor/decisions/{enforce_decision.id}/accept",
        json={"actor": "spoofed-admin@example.test"},
    )

    assert enforce_response.status_code == 403
    assert enforce_response.json()["detail"]["mode"] == "enforce"
    db_session.refresh(enforce_decision)
    assert enforce_decision.status == "proposed"
    assert enforce_decision.approved_by is None


def test_client360_mail_send_shadow_is_non_blocking_and_enforce_blocks(
    db_session,
    monkeypatch,
    attest_authorization_v2,
):
    workspace, user = _seed_contributor(
        db_session,
        suffix="client360-mail",
        settings={"family": "andritz"},
    )
    system, capability = _seed_client360_authority(
        db_session,
        workspace,
        suffix="mail",
    )
    config = _set_mode(
        db_session,
        workspace=workspace,
        user=user,
        key="mail_draft.mail.send",
        mode="shadow",
    )
    draft = SimpleNamespace(
        id="draft-authz-v2",
        opportunity_id="opportunity-authz-v2",
        action_item_id=None,
        campaign_id=None,
        subject="Subject",
        generated_body="Generated",
        sent_body="Sent",
        language="fr",
        status="sent",
        meta_data={},
        created_by_user_id=user.id,
        created_at=None,
        updated_at=None,
        sent_at=None,
    )
    calls: list[str] = []

    def _send(*_args, draft_id: str, **_kwargs):
        calls.append(draft_id)
        return draft, None

    monkeypatch.setattr(client360, "send_mail_draft", _send)
    monkeypatch.setattr(db_session, "refresh", lambda _row: None)
    client = _client(db_session, workspace, user, client360, "/client360")

    shadow_response = client.post(
        f"/client360/mail-drafts/{draft.id}/send",
        json={"to_email": "recipient@example.test"},
    )

    assert shadow_response.status_code == 200
    assert calls == [draft.id]
    diff = db_session.query(AuditLog).filter_by(
        workspace_id=workspace.id,
        event_type="iam.shadow.diff",
    ).one()
    assert diff.details["resource"] == {
        "kind": "mail_draft",
        "system_id": system.id,
        "capability_id": capability.id,
        "draft_id": draft.id,
    }

    _set_mode(
        db_session,
        workspace=workspace,
        user=user,
        key="mail_draft.mail.send",
        mode="enforce",
    )
    attest_authorization_v2(config, ["mail_draft.mail.send"])
    db_session.commit()
    enforce_response = client.post(
        f"/client360/mail-drafts/{draft.id}/send",
        json={"to_email": "recipient@example.test"},
    )

    assert enforce_response.status_code == 403
    assert enforce_response.json()["detail"]["mode"] == "enforce"
    assert calls == [draft.id]


def test_client360_authorization_fails_closed_before_business_handler_without_authority(
    db_session,
    monkeypatch,
):
    workspace, user = _seed_contributor(
        db_session,
        suffix="client360-unbound",
        settings={"family": "andritz"},
    )
    calls: list[str] = []
    monkeypatch.setattr(
        client360,
        "client360_scope",
        lambda _workspace: calls.append("scope") or {},
    )

    response = _client(db_session, workspace, user, client360, "/client360").get(
        "/client360/scope"
    )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "CLIENT360_AUTHORITY_UNAVAILABLE"
    assert calls == []


def test_client360_decision_enforce_denies_before_persisted_mutation(
    db_session,
    monkeypatch,
    attest_authorization_v2,
):
    workspace, user = _seed_contributor(
        db_session,
        suffix="client360-decision",
        settings={"family": "andritz"},
    )
    _seed_client360_authority(db_session, workspace, suffix="decision")
    config = _set_mode(
        db_session,
        workspace=workspace,
        user=user,
        key="decision.approve",
        mode="enforce",
    )
    attest_authorization_v2(config, ["decision.approve"])
    db_session.commit()
    calls: list[str] = []
    monkeypatch.setattr(
        client360,
        "patch_opportunity",
        lambda *_args, **_kwargs: calls.append("patch"),
    )

    response = _client(db_session, workspace, user, client360, "/client360").patch(
        "/client360/opportunities/opportunity-1",
        json={"status": "qualified"},
    )

    assert response.status_code == 403
    assert response.json()["detail"]["mode"] == "enforce"
    assert calls == []


def test_action_manifest_required_permission_is_effective_at_api_boundary(
    db_session,
    monkeypatch,
    attest_authorization_v2,
):
    workspace, user = _seed_contributor(
        db_session,
        suffix="action-manifest",
        settings={"family": "andritz"},
    )
    config = _set_mode(
        db_session,
        workspace=workspace,
        user=user,
        key="action.execute",
        mode="shadow",
    )
    calls: list[str] = []

    def _execute(*_args, action_id: str, **_kwargs):
        calls.append(action_id)
        return {"status": "ok", "action_id": action_id}

    monkeypatch.setattr(actions, "execute_action", _execute)
    client = _client(db_session, workspace, user, actions, "/actions")
    payload = {
        "action_id": "andritz.promote_deposit_file",
        "surface": "ui",
        "confirm": True,
    }

    shadow_response = client.post("/actions/execute", json=payload)

    assert shadow_response.status_code == 200
    assert calls == [payload["action_id"]]
    diff = db_session.query(AuditLog).filter_by(
        workspace_id=workspace.id,
        event_type="iam.shadow.diff",
    ).one()
    assert diff.details["resource"] == {
        "kind": "action",
        "action_id": payload["action_id"],
    }
    assert diff.details["candidate_allowed"] is False

    _set_mode(
        db_session,
        workspace=workspace,
        user=user,
        key="action.execute",
        mode="enforce",
    )
    attest_authorization_v2(config, ["action.execute"])
    db_session.commit()
    enforce_response = client.post("/actions/execute", json=payload)

    assert enforce_response.status_code == 403
    assert enforce_response.json()["detail"]["mode"] == "enforce"
    assert calls == [payload["action_id"]]


def test_capture_action_resolves_persisted_session_owner_before_enforce(
    db_session,
    attest_authorization_v2,
):
    workspace, user = _seed_contributor(
        db_session,
        suffix="capture-owner",
        settings={"family": "andritz"},
    )
    other = User(
        id="user-authz-v2-capture-other",
        username="capture-other",
        email="capture-other@example.test",
    )
    owned = ExpertCaptureSession(
        id="capture-owned",
        workspace_id=workspace.id,
        created_by_user_id=user.id,
        objective="Owned capture",
    )
    foreign_owner = ExpertCaptureSession(
        id="capture-other",
        workspace_id=workspace.id,
        created_by_user_id=other.id,
        objective="Another member capture",
    )
    db_session.add_all([other, owned, foreign_owner])
    config = _set_mode(
        db_session,
        workspace=workspace,
        user=user,
        key="action.execute",
        mode="enforce",
    )
    attest_authorization_v2(config, ["action.execute"])
    db_session.commit()
    client = _client(db_session, workspace, user, actions, "/actions")
    base = {
        "action_id": "andritz.next_capture_question",
        "surface": "knowledge_capture",
        "confirm": True,
    }

    allowed = client.post(
        "/actions/execute",
        json={**base, "payload": {"capture_session_id": owned.id}},
    )
    denied = client.post(
        "/actions/execute",
        json={**base, "payload": {"capture_session_id": foreign_owner.id}},
    )
    missing = client.post(
        "/actions/execute",
        json={**base, "payload": {"capture_session_id": "missing"}},
    )

    assert allowed.status_code == 200, allowed.text
    assert denied.status_code == 403
    assert denied.json()["detail"]["mode"] == "enforce"
    assert missing.status_code == 404
