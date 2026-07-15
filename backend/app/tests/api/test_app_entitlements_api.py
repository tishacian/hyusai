from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import delete, update

from app.api.v1.endpoints import auth, iam
from app.core.iam.roles import WORKSPACE_CONTRIBUTOR, WORKSPACE_OWNER
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
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
    workspace.settings = {
        "family": "andritz",
        "_migration_058_canonical_contracts_state": marker,
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

    db_session.refresh(workspace)
    assert workspace.settings["family"] == "andritz"
    assert workspace.settings["_migration_058_canonical_contracts_state"] == marker


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
