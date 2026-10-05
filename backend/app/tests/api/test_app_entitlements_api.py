from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import delete, update

from app.api.v1.endpoints import auth, iam
from app.core.config import settings
from app.core.iam import dependencies as iam_dependencies
from app.core.iam.dependencies import require_app_entitlement
from app.core.iam.roles import WORKSPACE_CONTRIBUTOR, WORKSPACE_OWNER
from app.models.audit import AuditLog
from app.models.capability import Capability
from app.models.system import System
from app.models.user import User
from app.models.workspace import (
    Workspace,
    WorkspaceMember,
    WorkspaceMemberAppEntitlement,
)
from app.services.iam.app_entitlements import (
    APP_ENTITLEMENTS_FEATURE,
    BUSINESS_APP_KEYS,
    CHAT_APP,
    CLIENT360_APP,
    KNOWLEDGE_CAPTURE_APP,
    WorkspaceEntitlementMutationConflictError,
    list_member_app_entitlements,
    lock_workspace_for_app_entitlement_mutation,
    replace_member_app_entitlements,
)
from app.services.projection_gate import (
    PROJECTION_FINALIZATION_AUDIT_EVENT,
    WORKSPACE_GATE_KEY,
    projection_activation_audit_details,
    projection_activation_sha256,
    with_projection_activation,
)
from app.services.value_loop_gate import FEATURE_KEY as VALUE_LOOP_FEATURE_KEY


def _seed_workspace(db_session):
    workspace = Workspace(
        id="workspace-app-entitlements-api",
        name="App Entitlements API",
        slug="app-entitlements-api",
        settings={
            "features": {
                "iam_enforced": True,
                "app_entitlements_v1": True,
            }
        },
    )
    owner = User(
        id="user-app-entitlements-owner",
        username="app-entitlements-owner",
        email="app-entitlements-owner@example.test",
        role="user",
    )
    member = User(
        id="user-app-entitlements-member",
        username="app-entitlements-member",
        email="app-entitlements-member@example.test",
        role="user",
    )
    invitee = User(
        id="user-app-entitlements-invitee",
        username="app-entitlements-invitee",
        email="app-entitlements-invitee@example.com",
        role="user",
    )
    owner_membership = WorkspaceMember(
        workspace_id=workspace.id,
        user_id=owner.id,
        role="owner",
        role_template=WORKSPACE_OWNER,
    )
    member_membership = WorkspaceMember(
        workspace_id=workspace.id,
        user_id=member.id,
        role="member",
        role_template=WORKSPACE_CONTRIBUTOR,
    )
    db_session.add_all([workspace, owner, member, invitee, owner_membership, member_membership])
    db_session.flush()
    replace_member_app_entitlements(
        db_session,
        owner_membership,
        BUSINESS_APP_KEYS,
        granted_by_user_id=owner.id,
        grant_source="api-test-seed",
    )
    replace_member_app_entitlements(
        db_session,
        member_membership,
        [KNOWLEDGE_CAPTURE_APP, CHAT_APP],
        granted_by_user_id=owner.id,
        grant_source="api-test-seed",
    )
    db_session.commit()
    return workspace, owner, member, invitee, owner_membership, member_membership


def _auth_client(db_session, owner: User) -> TestClient:
    app = FastAPI()
    app.include_router(auth.router, prefix="/auth")
    app.dependency_overrides[auth.get_current_user] = lambda: owner
    app.dependency_overrides[auth.get_db] = lambda: db_session
    return TestClient(app)


def _iam_client(db_session, workspace: Workspace, owner: User) -> TestClient:
    app = FastAPI()
    app.include_router(iam.router, prefix="/api/v1/iam")
    app.dependency_overrides[iam.get_current_user] = lambda: owner
    app.dependency_overrides[iam.get_current_workspace] = lambda: workspace
    app.dependency_overrides[iam.get_db] = lambda: db_session
    return TestClient(app)


def _entry_gate_client(db_session, workspace: Workspace, user: User) -> TestClient:
    app = FastAPI()

    @app.get(
        "/api/v1/chat/probe",
        dependencies=[Depends(require_app_entitlement(CHAT_APP))],
    )
    def probe() -> dict[str, bool]:
        return {"ok": True}

    app.dependency_overrides[iam_dependencies.get_current_user] = lambda: user
    app.dependency_overrides[iam_dependencies.get_current_workspace] = lambda: workspace
    app.dependency_overrides[iam_dependencies.get_db] = lambda: db_session
    return TestClient(app)


def test_auth_workspace_payloads_expose_canonical_app_entitlements(db_session) -> None:
    workspace, owner, member, _, _, _ = _seed_workspace(db_session)
    client = _auth_client(db_session, owner)

    me = client.get("/auth/me")
    listed = client.get("/auth/workspaces")
    detail = client.get(f"/auth/workspaces/{workspace.slug}")
    members = client.get(f"/auth/workspaces/{workspace.slug}/members")

    assert me.status_code == listed.status_code == detail.status_code == members.status_code == 200
    assert me.json()["workspaces"][0]["app_entitlements"] == list(BUSINESS_APP_KEYS)
    assert listed.json()[0]["app_entitlements"] == list(BUSINESS_APP_KEYS)
    assert detail.json()["app_entitlements"] == list(BUSINESS_APP_KEYS)
    by_user = {row["user_id"]: row for row in members.json()}
    assert by_user[owner.id]["app_entitlements"] == list(BUSINESS_APP_KEYS)
    assert by_user[member.id]["app_entitlements"] == [CHAT_APP, KNOWLEDGE_CAPTURE_APP]


def test_workspace_app_runtime_keeps_manifest_entitlements_fail_closed_when_legacy_flag_is_off(
    db_session,
    monkeypatch,
) -> None:
    workspace, _, member, _, _, member_membership = _seed_workspace(db_session)
    workspace.settings = {
        **(workspace.settings or {}),
        "features": {
            **((workspace.settings or {}).get("features") or {}),
            APP_ENTITLEMENTS_FEATURE: False,
            "workspace_app_platform_v1": True,
        },
    }
    db_session.query(WorkspaceMemberAppEntitlement).filter_by(
        workspace_member_id=member_membership.id,
        app_key=CHAT_APP,
    ).delete(synchronize_session=False)
    db_session.commit()

    monkeypatch.setattr(
        iam_dependencies,
        "installed_entitlement_keys",
        lambda *_args, **_kwargs: frozenset({CHAT_APP}),
    )
    monkeypatch.setattr(
        iam_dependencies,
        "workspace_app_api_path_allowed",
        lambda *_args, **_kwargs: True,
    )

    response = _entry_gate_client(db_session, workspace, member).get(
        "/api/v1/chat/probe"
    )

    assert response.status_code == 403
    assert response.json()["detail"] == {
        "code": "WORKSPACE_APP_ACCESS_DENIED",
        "message": "Workspace application access denied",
        "app_key": CHAT_APP,
    }


def test_generic_workspace_patch_cannot_enable_app_entitlements(db_session) -> None:
    workspace, owner, _, _, _, _ = _seed_workspace(db_session)
    workspace.settings = {
        "family": "generic",
        "features": {APP_ENTITLEMENTS_FEATURE: False},
    }
    db_session.commit()

    response = _auth_client(db_session, owner).patch(
        f"/auth/workspaces/{workspace.slug}",
        json={
            "settings": {
                "family": "generic",
                "features": {APP_ENTITLEMENTS_FEATURE: True},
            }
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "APP_ENTITLEMENTS_SETTING_MANAGED"
    db_session.refresh(workspace)
    assert workspace.settings["features"][APP_ENTITLEMENTS_FEATURE] is False


def test_generic_workspace_patch_cannot_bypass_lot7_projection_rollout(db_session) -> None:
    workspace, owner, _, _, _, _ = _seed_workspace(db_session)
    workspace.settings = with_projection_activation(
        {"family": "generic", "features": {APP_ENTITLEMENTS_FEATURE: True}},
        projection="capability",
        evidence_sha256="a" * 64,
        revision="b" * 40,
        system_id="system-canary",
        capability_id="capability-canary",
    )
    gate_rows = workspace.settings[WORKSPACE_GATE_KEY]["activations"]
    db_session.add_all(
        [
            Capability(
                id="capability-canary",
                workspace_id=workspace.id,
                slug="capability-canary",
                name="Capability canary",
            ),
            System(
                id="system-canary",
                workspace_id=workspace.id,
                capability_id="capability-canary",
                name="System canary",
                status="active",
                settings={
                    "experience": {"system_360_canary": "v1"},
                    "_lot7_projection_rollout_v1": {
                        "schema_version": 1,
                        "activations": [dict(row) for row in gate_rows],
                        "probations": [],
                        "deactivations": [],
                    },
                },
            ),
        ]
    )
    db_session.commit()
    client = _auth_client(db_session, owner)

    flag = client.patch(
        f"/auth/workspaces/{workspace.slug}",
        json={"settings": {"features": {"capability_360_projection_v1": False}}},
    )
    assert flag.status_code == 409
    assert flag.json()["detail"]["code"] == "LOT7_PROJECTION_ROLLOUT_STATE_MANAGED"

    gate = client.patch(
        f"/auth/workspaces/{workspace.slug}",
        json={"settings": {WORKSPACE_GATE_KEY: {"schema_version": 1, "activations": []}}},
    )
    assert gate.status_code == 409
    assert gate.json()["detail"]["code"] == "LOT7_PROJECTION_ROLLOUT_STATE_MANAGED"

    ordinary = client.patch(
        f"/auth/workspaces/{workspace.slug}",
        json={"settings": {"branding": {"name": "Safe"}}},
    )
    assert ordinary.status_code == 200
    assert ordinary.json()["settings"][WORKSPACE_GATE_KEY] == workspace.settings[
        WORKSPACE_GATE_KEY
    ]
    assert ordinary.json()["settings"]["features"][
        "capability_360_projection_v1"
    ] is True


def test_generic_workspace_patch_cannot_bypass_lot8_value_loop_rollout(
    db_session,
) -> None:
    workspace, owner, _, _, _, _ = _seed_workspace(db_session)
    workspace.settings = {
        "family": "generic",
        "features": {
            APP_ENTITLEMENTS_FEATURE: True,
            VALUE_LOOP_FEATURE_KEY: False,
        },
    }
    db_session.commit()
    client = _auth_client(db_session, owner)

    changed = client.patch(
        f"/auth/workspaces/{workspace.slug}",
        json={
            "settings": {
                "features": {
                    APP_ENTITLEMENTS_FEATURE: True,
                    VALUE_LOOP_FEATURE_KEY: True,
                }
            }
        },
    )
    assert changed.status_code == 409
    assert changed.json()["detail"]["code"] == (
        "LOT8_VALUE_LOOP_ROLLOUT_STATE_MANAGED"
    )

    ordinary = client.patch(
        f"/auth/workspaces/{workspace.slug}",
        json={"settings": {"branding": {"name": "Still safe"}}},
    )
    assert ordinary.status_code == 200
    assert ordinary.json()["settings"]["features"][VALUE_LOOP_FEATURE_KEY] is False


def test_workspace_response_exposes_only_sha_bound_effective_projection_flags(
    db_session,
    monkeypatch,
) -> None:
    workspace, owner, _, _, _, _ = _seed_workspace(db_session)
    workspace.settings = with_projection_activation(
        workspace.settings,
        projection="capability",
        evidence_sha256="a" * 64,
        revision="b" * 40,
        system_id="system-canary",
        capability_id="capability-canary",
    )
    gate_rows = workspace.settings[WORKSPACE_GATE_KEY]["activations"]
    trusted_runner = {
        "issuer": "https://gitlab.example.test",
        "project_id": "42",
        "pipeline_id": "314",
        "job_id": "159",
        "commit_sha": "b" * 40,
        "ref": "demo/agentic",
        "ref_protected": True,
    }
    activation = {
        **dict(gate_rows[0]),
        "trusted_runner": trusted_runner,
        "pilot_observation": {
            "audit_id": str(uuid4()),
            "observation_ref": f"sha256:{'b' * 64}",
            "participant_ref": f"sha256:{'c' * 64}",
            "profile": "operator",
        },
        "activated_by": "lot7-api-test-runner",
        "activated_at": "2026-01-01T00:00:00+00:00",
        "probation_lease_id": str(uuid4()),
    }
    activation["activation_sha256"] = projection_activation_sha256(activation)
    activation_audit_id = str(uuid4())
    db_session.add(
        AuditLog(
            id=activation_audit_id,
            workspace_id=workspace.id,
            event_type=PROJECTION_FINALIZATION_AUDIT_EVENT,
            actor=activation["activated_by"],
            agent_id="system-canary",
            details=projection_activation_audit_details(activation),
        )
    )
    activation["audit_id"] = activation_audit_id
    db_session.add_all(
        [
            Capability(
                id="capability-canary",
                workspace_id=workspace.id,
                slug="capability-canary",
                name="Capability canary",
            ),
            System(
                id="system-canary",
                workspace_id=workspace.id,
                capability_id="capability-canary",
                name="System canary",
                status="active",
                settings={
                    "experience": {"system_360_canary": "v1"},
                    "_lot7_projection_rollout_v1": {
                        "schema_version": 1,
                        "activations": [activation],
                        "probations": [],
                        "deactivations": [],
                    },
                },
            ),
        ]
    )
    db_session.commit()
    client = _auth_client(db_session, owner)

    monkeypatch.setattr(
        settings,
        "authorization_v2_trusted_oidc_issuer",
        trusted_runner["issuer"],
    )
    monkeypatch.setattr(
        settings,
        "authorization_v2_trusted_project_id",
        trusted_runner["project_id"],
    )
    monkeypatch.setattr(
        settings,
        "authorization_v2_trusted_ref",
        trusted_runner["ref"],
    )
    monkeypatch.setattr(settings, "agentium_image_revision", "b" * 40)
    current = client.get(f"/auth/workspaces/{workspace.slug}")
    assert current.status_code == 200
    assert current.json()["effective_features"]["capability_360_projection_v1"] is True

    monkeypatch.setattr(settings, "agentium_image_revision", "c" * 40)
    stale = client.get(f"/auth/workspaces/{workspace.slug}")
    assert stale.status_code == 200
    assert stale.json()["settings"]["features"]["capability_360_projection_v1"] is True
    assert stale.json()["effective_features"]["capability_360_projection_v1"] is False


def test_generic_workspace_patch_preserves_managed_flag_and_family_when_omitted(
    db_session,
) -> None:
    workspace, owner, _, _, _, _ = _seed_workspace(db_session)
    workspace.settings = {
        "family": "andritz",
        "_migration_058_canonical_contracts_state": {
            "schema": 2,
            "applied_family": "andritz",
        },
        "features": {
            "iam_enforced": True,
            APP_ENTITLEMENTS_FEATURE: True,
        },
        "old_replacement_key": True,
    }
    db_session.commit()

    response = _auth_client(db_session, owner).patch(
        f"/auth/workspaces/{workspace.slug}",
        json={"settings": {"branding": {"name": "Industrial"}}},
    )

    assert response.status_code == 200, response.text
    assert response.json()["settings"] == {
        "branding": {"name": "Industrial"},
        "family": "andritz",
        "_migration_058_canonical_contracts_state": {
            "schema": 2,
            "applied_family": "andritz",
        },
        "features": {APP_ENTITLEMENTS_FEATURE: True},
    }


def test_generic_workspace_patch_cannot_change_resolver_family_or_migration_state(
    db_session,
) -> None:
    workspace, owner, _, _, _, _ = _seed_workspace(db_session)
    marker = {"schema": 2, "applied_family": "andritz"}
    agentic_marker = {"schema": 1, "system_id": "system-agentic"}
    chat_execution = {
        "version": 1,
        "mode": "agentic_default",
        "rollout": {"percentage": 0},
    }
    workspace.settings = {
        "family": "andritz",
        "chat_execution": chat_execution,
        "_migration_058_canonical_contracts_state": marker,
        "_migration_059_andritz_agentic_default_state": agentic_marker,
        "features": {APP_ENTITLEMENTS_FEATURE: True},
    }
    db_session.commit()
    client = _auth_client(db_session, owner)

    family = client.patch(
        f"/auth/workspaces/{workspace.slug}",
        json={"settings": {"family": "generic"}},
    )
    assert family.status_code == 409
    assert family.json()["detail"]["code"] == "WORKSPACE_EXPERIENCE_SETTING_MANAGED"

    migration = client.patch(
        f"/auth/workspaces/{workspace.slug}",
        json={
            "settings": {
                "family": "andritz",
                "_migration_058_canonical_contracts_state": {
                    "schema": 2,
                    "applied_family": "generic",
                },
            }
        },
    )
    assert migration.status_code == 409
    assert migration.json()["detail"]["code"] == "WORKSPACE_MIGRATION_STATE_MANAGED"

    policy = client.patch(
        f"/auth/workspaces/{workspace.slug}",
        json={"settings": {"chat_execution": {"version": 1, "mode": "classic"}}},
    )
    assert policy.status_code == 409
    assert policy.json()["detail"]["code"] == "CHAT_EXECUTION_POLICY_MANAGED"

    agentic_migration = client.patch(
        f"/auth/workspaces/{workspace.slug}",
        json={
            "settings": {
                "_migration_059_andritz_agentic_default_state": {
                    "schema": 1,
                    "system_id": "other-system",
                }
            }
        },
    )
    assert agentic_migration.status_code == 409
    assert agentic_migration.json()["detail"]["code"] == "WORKSPACE_MIGRATION_STATE_MANAGED"

    db_session.refresh(workspace)
    assert workspace.settings["family"] == "andritz"
    assert workspace.settings["chat_execution"] == chat_execution
    assert workspace.settings["_migration_058_canonical_contracts_state"] == marker
    assert workspace.settings["_migration_059_andritz_agentic_default_state"] == agentic_marker


def test_generic_workspace_patch_rechecks_admin_authority_after_lock(
    db_session,
    monkeypatch,
) -> None:
    workspace, owner, _, _, _, _ = _seed_workspace(db_session)
    original_name = workspace.name

    def _lock_then_revoke_admin(db, workspace_id):
        locked = lock_workspace_for_app_entitlement_mutation(db, workspace_id)
        db.execute(
            update(WorkspaceMember)
            .where(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.user_id == owner.id,
            )
            .values(role="member", role_template=WORKSPACE_CONTRIBUTOR)
            .execution_options(synchronize_session=False)
        )
        db.flush()
        return locked

    monkeypatch.setattr(
        auth,
        "lock_workspace_for_app_entitlement_mutation",
        _lock_then_revoke_admin,
    )
    response = _auth_client(db_session, owner).patch(
        f"/auth/workspaces/{workspace.slug}",
        json={"name": "Unauthorized rename"},
    )

    assert response.status_code == 403
    db_session.refresh(workspace)
    assert workspace.name == original_name


def test_auth_invite_validates_and_persists_explicit_app_entitlements(db_session) -> None:
    workspace, owner, _, invitee, _, _ = _seed_workspace(db_session)
    client = _auth_client(db_session, owner)

    response = client.post(
        f"/auth/workspaces/{workspace.slug}/members",
        json={
            "email": invitee.email,
            "role": "member",
            "role_template": WORKSPACE_CONTRIBUTOR,
            "app_entitlements": [KNOWLEDGE_CAPTURE_APP, CHAT_APP, CHAT_APP],
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["app_entitlements"] == [CHAT_APP, KNOWLEDGE_CAPTURE_APP]
    membership = (
        db_session.query(WorkspaceMember)
        .filter_by(
            workspace_id=workspace.id,
            user_id=invitee.id,
        )
        .one()
    )
    assert list_member_app_entitlements(db_session, membership) == [
        CHAT_APP,
        KNOWLEDGE_CAPTURE_APP,
    ]


def test_auth_invite_rejects_unknown_app_before_membership_creation(db_session) -> None:
    workspace, owner, _, invitee, _, _ = _seed_workspace(db_session)
    client = _auth_client(db_session, owner)

    response = client.post(
        f"/auth/workspaces/{workspace.slug}/members",
        json={
            "email": invitee.email,
            "role": "member",
            "app_entitlements": ["mission-room"],
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "INVALID_APP_ENTITLEMENT"
    assert (
        db_session.query(WorkspaceMember)
        .filter_by(workspace_id=workspace.id, user_id=invitee.id)
        .count()
        == 0
    )


def test_auth_invite_requires_explicit_entitlements_when_feature_is_enabled(
    db_session,
) -> None:
    workspace, owner, _, invitee, _, _ = _seed_workspace(db_session)
    client = _auth_client(db_session, owner)

    response = client.post(
        f"/auth/workspaces/{workspace.slug}/members",
        json={
            "email": invitee.email,
            "role": "member",
            "role_template": WORKSPACE_CONTRIBUTOR,
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == {
        "code": "APP_ENTITLEMENTS_REQUIRED",
        "message": (
            "app_entitlements must be provided when workspace application entitlements are enabled"
        ),
    }
    assert (
        db_session.query(WorkspaceMember)
        .filter_by(workspace_id=workspace.id, user_id=invitee.id)
        .count()
        == 0
    )


def test_auth_invite_rechecks_fresh_entitlement_settings_under_workspace_lock(
    db_session,
    monkeypatch,
) -> None:
    workspace, owner, _, invitee, _, _ = _seed_workspace(db_session)
    workspace.settings = {
        "features": {
            "iam_enforced": True,
            APP_ENTITLEMENTS_FEATURE: False,
        }
    }
    db_session.commit()
    events: list[str] = []

    def _lock_with_concurrent_blueprint(db, workspace_id):
        events.append("lock")
        assert (
            db.query(WorkspaceMember)
            .filter_by(workspace_id=workspace.id, user_id=invitee.id)
            .count()
            == 0
        )
        assert workspace_id == workspace.id
        locked = lock_workspace_for_app_entitlement_mutation(db, workspace_id)
        locked.settings = {
            "features": {
                "iam_enforced": True,
                APP_ENTITLEMENTS_FEATURE: True,
            }
        }
        return locked

    monkeypatch.setattr(
        auth,
        "lock_workspace_for_app_entitlement_mutation",
        _lock_with_concurrent_blueprint,
    )
    response = _auth_client(db_session, owner).post(
        f"/auth/workspaces/{workspace.slug}/members",
        json={
            "email": invitee.email,
            "role": "member",
            "role_template": WORKSPACE_CONTRIBUTOR,
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "APP_ENTITLEMENTS_REQUIRED"
    assert events == ["lock"]
    assert (
        db_session.query(WorkspaceMember)
        .filter_by(workspace_id=workspace.id, user_id=invitee.id)
        .count()
        == 0
    )


def test_auth_invite_keeps_keycloak_network_phase_outside_workspace_lock(
    db_session,
    monkeypatch,
) -> None:
    workspace, owner, _, _, _, _ = _seed_workspace(db_session)
    email = "two-phase-invitee@example.com"
    events: list[str] = []

    async def _admin_token():
        events.append("network:token")
        return "admin-token"

    async def _provision(invitee_email, admin_token):
        assert invitee_email == email
        assert admin_token == "admin-token"
        events.append("network:provision")
        return "kc-two-phase-invitee", True

    async def _email(kc_sub, admin_token):
        assert kc_sub == "kc-two-phase-invitee"
        assert admin_token == "admin-token"
        assert db_session.in_transaction() is False
        events.append("network:email")
        return True

    def _lock(db, workspace_id):
        events.append("lock")
        assert db.query(User).filter(User.email == email).first() is None
        assert (
            db.query(WorkspaceMember)
            .filter(WorkspaceMember.workspace_id == workspace_id)
            .join(User, User.id == WorkspaceMember.user_id)
            .filter(User.email == email)
            .count()
            == 0
        )
        return lock_workspace_for_app_entitlement_mutation(db, workspace_id)

    def _replace(*args, **kwargs):
        events.append("replace_grants")
        return replace_member_app_entitlements(*args, **kwargs)

    monkeypatch.setattr(auth, "_get_admin_token", _admin_token)
    monkeypatch.setattr(auth, "_find_or_create_kc_user", _provision)
    monkeypatch.setattr(auth, "_send_invitation_email", _email)
    monkeypatch.setattr(auth, "lock_workspace_for_app_entitlement_mutation", _lock)
    monkeypatch.setattr(auth, "replace_member_app_entitlements", _replace)

    response = _auth_client(db_session, owner).post(
        f"/auth/workspaces/{workspace.slug}/members",
        json={
            "email": email,
            "role": "member",
            "role_template": WORKSPACE_CONTRIBUTOR,
            "app_entitlements": [CHAT_APP],
        },
    )

    assert response.status_code == 200, response.text
    assert events == [
        "network:token",
        "network:provision",
        "lock",
        "replace_grants",
        "network:email",
    ]
    assert response.json()["invitation_email_sent"] is True


def test_auth_invite_does_not_email_when_locked_policy_recheck_rejects(
    db_session,
    monkeypatch,
) -> None:
    workspace, owner, _, _, _, _ = _seed_workspace(db_session)
    workspace.settings = {
        "features": {
            "iam_enforced": True,
            APP_ENTITLEMENTS_FEATURE: False,
        }
    }
    db_session.commit()
    email = "policy-race-invitee@example.com"
    events: list[str] = []

    async def _admin_token():
        events.append("network:token")
        return "admin-token"

    async def _provision(invitee_email, admin_token):
        assert invitee_email == email
        assert admin_token == "admin-token"
        events.append("network:provision")
        return "kc-policy-race-invitee", True

    async def _email(*_args, **_kwargs):
        events.append("network:email")
        return True

    def _lock_with_concurrent_policy_change(db, workspace_id):
        events.append("lock")
        locked = lock_workspace_for_app_entitlement_mutation(db, workspace_id)
        locked.settings = {
            "features": {
                "iam_enforced": True,
                APP_ENTITLEMENTS_FEATURE: True,
            }
        }
        return locked

    monkeypatch.setattr(auth, "_get_admin_token", _admin_token)
    monkeypatch.setattr(auth, "_find_or_create_kc_user", _provision)
    monkeypatch.setattr(auth, "_send_invitation_email", _email)
    monkeypatch.setattr(
        auth,
        "lock_workspace_for_app_entitlement_mutation",
        _lock_with_concurrent_policy_change,
    )

    response = _auth_client(db_session, owner).post(
        f"/auth/workspaces/{workspace.slug}/members",
        json={
            "email": email,
            "role": "member",
            "role_template": WORKSPACE_CONTRIBUTOR,
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "APP_ENTITLEMENTS_REQUIRED"
    assert events == ["network:token", "network:provision", "lock"]
    assert db_session.query(User).filter(User.email == email).count() == 0


def test_auth_invite_fails_closed_when_preexisting_local_identity_disappears(
    db_session,
    monkeypatch,
) -> None:
    workspace, owner, _, invitee, _, _ = _seed_workspace(db_session)
    invitee.keycloak_sub = "kc-stale-local-invitee"
    db_session.commit()

    async def _unexpected_keycloak_lookup():
        pytest.fail("A pre-existing local identity must not trigger Keycloak provisioning")

    def _lock_after_identity_deletion(db, workspace_id):
        db.execute(
            delete(User).where(User.id == invitee.id).execution_options(synchronize_session=False)
        )
        # Prove the request still holds the stale object which must not be reused.
        assert invitee.keycloak_sub == "kc-stale-local-invitee"
        return lock_workspace_for_app_entitlement_mutation(db, workspace_id)

    monkeypatch.setattr(auth, "_get_admin_token", _unexpected_keycloak_lookup)
    monkeypatch.setattr(
        auth,
        "lock_workspace_for_app_entitlement_mutation",
        _lock_after_identity_deletion,
    )

    response = _auth_client(db_session, owner).post(
        f"/auth/workspaces/{workspace.slug}/members",
        json={
            "email": invitee.email,
            "role": "member",
            "role_template": WORKSPACE_CONTRIBUTOR,
            "app_entitlements": [CHAT_APP],
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "INVITEE_IDENTITY_CHANGED"
    assert db_session.query(User).filter(User.email == invitee.email).count() == 0


def test_auth_invite_fails_closed_on_concurrent_email_identity_mismatch(
    db_session,
    monkeypatch,
) -> None:
    workspace, owner, _, _, _, _ = _seed_workspace(db_session)
    email = "ambiguous-race-invitee@example.com"
    concurrent_user_id = "user-ambiguous-race-invitee"
    events: list[str] = []

    async def _admin_token():
        events.append("network:token")
        return "admin-token"

    async def _resolve_keycloak(invitee_email, admin_token):
        assert invitee_email == email
        assert admin_token == "admin-token"
        events.append("network:resolve:A")
        return "kc-identity-A", False

    def _lock_after_conflicting_local_identity(db, workspace_id):
        events.append("local-identity:B")
        db.add(
            User(
                id=concurrent_user_id,
                username="ambiguous-race-invitee",
                email=email,
                keycloak_sub="kc-identity-B",
                role="user",
                is_active=True,
            )
        )
        db.flush()
        return lock_workspace_for_app_entitlement_mutation(db, workspace_id)

    def _unexpected_grant_mutation(*_args, **_kwargs):
        pytest.fail("Ambiguous identities must fail before membership/grant mutation")

    monkeypatch.setattr(auth, "_get_admin_token", _admin_token)
    monkeypatch.setattr(auth, "_find_or_create_kc_user", _resolve_keycloak)
    monkeypatch.setattr(
        auth,
        "lock_workspace_for_app_entitlement_mutation",
        _lock_after_conflicting_local_identity,
    )
    monkeypatch.setattr(
        auth,
        "replace_member_app_entitlements",
        _unexpected_grant_mutation,
    )

    response = _auth_client(db_session, owner).post(
        f"/auth/workspaces/{workspace.slug}/members",
        json={
            "email": email,
            "role": "member",
            "role_template": WORKSPACE_CONTRIBUTOR,
            "app_entitlements": [CHAT_APP],
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "INVITEE_IDENTITY_CHANGED"
    assert events == ["network:token", "network:resolve:A", "local-identity:B"]
    assert (
        db_session.query(WorkspaceMember)
        .filter_by(workspace_id=workspace.id, user_id=concurrent_user_id)
        .count()
        == 0
    )


def test_auth_transfer_ownership_locks_before_membership_roles_change(
    db_session,
    monkeypatch,
) -> None:
    workspace, owner, member, _, owner_membership, member_membership = _seed_workspace(db_session)
    events: list[str] = []

    def _lock(db, workspace_id):
        events.append("lock")
        assert owner_membership.role == "owner"
        assert member_membership.role == "member"
        return lock_workspace_for_app_entitlement_mutation(db, workspace_id)

    monkeypatch.setattr(auth, "lock_workspace_for_app_entitlement_mutation", _lock)
    response = _auth_client(db_session, owner).post(
        f"/auth/workspaces/{workspace.slug}/transfer-ownership",
        json={"new_owner_user_id": member.id},
    )

    assert response.status_code == 200, response.text
    assert events == ["lock"]
    db_session.refresh(owner_membership)
    db_session.refresh(member_membership)
    assert owner_membership.role == "admin"
    assert member_membership.role == "owner"


def test_auth_leave_workspace_locks_before_membership_deletion(
    db_session,
    monkeypatch,
) -> None:
    workspace, _, member, _, _, member_membership = _seed_workspace(db_session)
    events: list[str] = []

    def _lock(db, workspace_id):
        events.append("lock")
        assert db.query(WorkspaceMember).filter_by(id=member_membership.id).count() == 1
        return lock_workspace_for_app_entitlement_mutation(db, workspace_id)

    monkeypatch.setattr(auth, "lock_workspace_for_app_entitlement_mutation", _lock)
    response = _auth_client(db_session, member).post(f"/auth/workspaces/{workspace.slug}/leave")

    assert response.status_code == 200, response.text
    assert events == ["lock"]
    assert db_session.query(WorkspaceMember).filter_by(id=member_membership.id).count() == 0


def test_auth_remove_member_locks_before_membership_deletion(
    db_session,
    monkeypatch,
) -> None:
    workspace, owner, member, _, _, member_membership = _seed_workspace(db_session)
    events: list[str] = []

    def _lock(db, workspace_id):
        events.append("lock")
        assert db.query(WorkspaceMember).filter_by(id=member_membership.id).count() == 1
        return lock_workspace_for_app_entitlement_mutation(db, workspace_id)

    monkeypatch.setattr(auth, "lock_workspace_for_app_entitlement_mutation", _lock)
    response = _auth_client(db_session, owner).delete(
        f"/auth/workspaces/{workspace.slug}/members/{member.id}"
    )

    assert response.status_code == 200, response.text
    assert events == ["lock"]
    assert db_session.query(WorkspaceMember).filter_by(id=member_membership.id).count() == 0


def test_iam_update_replaces_entitlements_and_omission_preserves_them(db_session) -> None:
    workspace, owner, member, _, _, member_membership = _seed_workspace(db_session)
    client = _iam_client(db_session, workspace, owner)

    updated = client.put(
        f"/api/v1/iam/members/{member.id}",
        json={
            "role_template": WORKSPACE_CONTRIBUTOR,
            "custom_labels": ["pdr"],
            "app_entitlements": [CLIENT360_APP, CHAT_APP],
        },
    )

    assert updated.status_code == 200
    assert updated.json()["member"]["app_entitlements"] == [CHAT_APP, CLIENT360_APP]

    preserved = client.put(
        f"/api/v1/iam/members/{member.id}",
        json={
            "role_template": WORKSPACE_CONTRIBUTOR,
            "custom_labels": ["pdr", "preserved"],
        },
    )
    assert preserved.status_code == 200
    assert preserved.json()["member"]["app_entitlements"] == [CHAT_APP, CLIENT360_APP]
    assert list_member_app_entitlements(db_session, member_membership) == [
        CHAT_APP,
        CLIENT360_APP,
    ]

    summary = client.get("/api/v1/iam/summary")
    assert summary.status_code == 200
    by_user = {row["user_id"]: row for row in summary.json()["members"]}
    assert by_user[member.id]["app_entitlements"] == [CHAT_APP, CLIENT360_APP]


def test_iam_update_rejects_unknown_app_without_mutating_existing_grants(db_session) -> None:
    workspace, owner, member, _, _, member_membership = _seed_workspace(db_session)
    client = _iam_client(db_session, workspace, owner)

    response = client.put(
        f"/api/v1/iam/members/{member.id}",
        json={
            "role_template": WORKSPACE_CONTRIBUTOR,
            "custom_labels": [],
            "app_entitlements": ["unknown-app"],
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "INVALID_APP_ENTITLEMENT"
    assert list_member_app_entitlements(db_session, member_membership) == [
        CHAT_APP,
        KNOWLEDGE_CAPTURE_APP,
    ]


def test_iam_member_update_locks_workspace_before_role_and_grant_mutation(
    db_session,
    monkeypatch,
) -> None:
    workspace, owner, member, _, _, member_membership = _seed_workspace(db_session)
    events: list[str] = []

    def _lock(db, workspace_id):
        events.append("lock")
        assert workspace_id == workspace.id
        assert member_membership.role_template == WORKSPACE_CONTRIBUTOR
        assert list_member_app_entitlements(db, member_membership) == [
            CHAT_APP,
            KNOWLEDGE_CAPTURE_APP,
        ]
        return lock_workspace_for_app_entitlement_mutation(db, workspace_id)

    def _replace(*args, **kwargs):
        events.append("replace_grants")
        assert events[0] == "lock"
        return replace_member_app_entitlements(*args, **kwargs)

    monkeypatch.setattr(iam, "lock_workspace_for_app_entitlement_mutation", _lock)
    monkeypatch.setattr(iam, "replace_member_app_entitlements", _replace)

    response = _iam_client(db_session, workspace, owner).put(
        f"/api/v1/iam/members/{member.id}",
        json={
            "role_template": WORKSPACE_CONTRIBUTOR,
            "custom_labels": ["locked"],
            "app_entitlements": [CLIENT360_APP],
        },
    )

    assert response.status_code == 200
    assert events == ["lock", "replace_grants"]
    assert response.json()["member"]["app_entitlements"] == [CLIENT360_APP]


def test_iam_member_update_refreshes_caller_authority_after_workspace_lock(
    db_session,
    monkeypatch,
) -> None:
    workspace, owner, member, _, owner_membership, member_membership = _seed_workspace(db_session)
    events: list[str] = []

    def _lock_after_concurrent_demotion(db, workspace_id):
        events.append("demote-before-lock")
        db.execute(
            update(WorkspaceMember)
            .where(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.user_id == owner.id,
            )
            .values(role="member", role_template=WORKSPACE_CONTRIBUTOR)
            .execution_options(synchronize_session=False)
        )
        # The identity map still contains the authority read by the first gate.
        assert owner_membership.role == "owner"
        return lock_workspace_for_app_entitlement_mutation(db, workspace_id)

    monkeypatch.setattr(
        iam,
        "lock_workspace_for_app_entitlement_mutation",
        _lock_after_concurrent_demotion,
    )
    response = _iam_client(db_session, workspace, owner).put(
        f"/api/v1/iam/members/{member.id}",
        json={
            "role_template": WORKSPACE_CONTRIBUTOR,
            "custom_labels": ["must-not-persist"],
            "app_entitlements": [CLIENT360_APP],
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "WORKSPACE_PERMISSION_DENIED"
    assert events == ["demote-before-lock"]
    db_session.refresh(owner_membership)
    db_session.refresh(member_membership)
    assert owner_membership.role_template == WORKSPACE_CONTRIBUTOR
    assert member_membership.custom_labels in (None, [])
    assert list_member_app_entitlements(db_session, member_membership) == [
        CHAT_APP,
        KNOWLEDGE_CAPTURE_APP,
    ]


def test_iam_member_update_lock_conflict_preserves_membership_and_grants(
    db_session,
    monkeypatch,
) -> None:
    workspace, owner, member, _, _, member_membership = _seed_workspace(db_session)

    def _conflict(*_args, **_kwargs):
        raise WorkspaceEntitlementMutationConflictError("workspace vanished")

    monkeypatch.setattr(iam, "lock_workspace_for_app_entitlement_mutation", _conflict)
    response = _iam_client(db_session, workspace, owner).put(
        f"/api/v1/iam/members/{member.id}",
        json={
            "role_template": WORKSPACE_CONTRIBUTOR,
            "custom_labels": ["must-not-persist"],
            "app_entitlements": [CLIENT360_APP],
        },
    )

    assert response.status_code == 409
    db_session.refresh(member_membership)
    assert member_membership.custom_labels in (None, [])
    assert list_member_app_entitlements(db_session, member_membership) == [
        CHAT_APP,
        KNOWLEDGE_CAPTURE_APP,
    ]


def _app_probe_client(db_session, workspace: Workspace, user: User) -> TestClient:
    app = FastAPI()
    for key in BUSINESS_APP_KEYS:

        @app.get(f"/probe/{key}", dependencies=[Depends(require_app_entitlement(key))])
        def probe() -> dict[str, bool]:
            return {"ok": True}

    @app.get(
        "/probe/capture-or-fse",
        dependencies=[
            Depends(iam_dependencies.require_any_app_entitlement(KNOWLEDGE_CAPTURE_APP, "fse-reports"))
        ],
    )
    def shared_probe() -> dict[str, bool]:
        return {"ok": True}

    app.dependency_overrides[iam_dependencies.get_current_user] = lambda: user
    app.dependency_overrides[iam_dependencies.get_current_workspace] = lambda: workspace
    app.dependency_overrides[iam_dependencies.get_db] = lambda: db_session
    return TestClient(app)


@pytest.mark.parametrize("family", ["generic", "industrial", "sentinel_ci", None])
def test_a_customer_application_never_opens_outside_its_family_even_without_flags(
    db_session, family
) -> None:
    workspace, owner, *_ = _seed_workspace(db_session)
    # The legacy contract (no entitlement or platform flag) used to grant every
    # member every app, so a generic workspace could open ANDRITZ's apps.
    workspace.settings = {"features": {}, **({"family": family} if family else {})}
    db_session.commit()
    client = _app_probe_client(db_session, workspace, owner)

    for product in (CHAT_APP, KNOWLEDGE_CAPTURE_APP, "capture-or-fse"):
        assert client.get(f"/probe/{product}").status_code == 200, product
    for customer_app in (CLIENT360_APP, "fse-reports"):
        response = client.get(f"/probe/{customer_app}")
        assert response.status_code == 404, customer_app
        assert response.json()["detail"] == {"code": "WORKSPACE_APP_NOT_FOUND"}


def test_the_andritz_family_keeps_its_applications(db_session) -> None:
    workspace, owner, *_ = _seed_workspace(db_session)
    workspace.settings = {"features": {}, "family": "andritz"}
    db_session.commit()
    client = _app_probe_client(db_session, workspace, owner)

    for key in (*BUSINESS_APP_KEYS, "capture-or-fse"):
        assert client.get(f"/probe/{key}").status_code == 200, key
