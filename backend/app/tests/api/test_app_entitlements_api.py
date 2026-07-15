from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import auth, iam
from app.core.iam.roles import WORKSPACE_CONTRIBUTOR, WORKSPACE_OWNER
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services.iam.app_entitlements import (
    BUSINESS_APP_KEYS,
    CHAT_APP,
    CLIENT360_APP,
    KNOWLEDGE_CAPTURE_APP,
    list_member_app_entitlements,
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

    assert response.status_code == 200
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
