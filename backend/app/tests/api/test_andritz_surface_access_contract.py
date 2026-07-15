"""Lot 0 contract tests for the three active Andritz business surfaces.

These tests intentionally describe the access contract that exists before the
navigation realignment.  They exercise the real workspace resolver (including
``X-Workspace-Slug`` membership checks) instead of overriding the resolved
workspace, so a later shell/navigation refactor cannot silently change backend
access to Chat Recherche, Knowledge Capture, or Client360.

Client360 is currently membership-scoped and has no action-level IAM manifest.
The mutation assertion below is a baseline of that current behaviour, not a
recommendation for the future authorization model.
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import chat, client360, knowledge_capture, sessions
from app.core.auth import get_current_user
from app.core.iam.roles import legacy_role_for_template
from app.db.base import get_db
from app.models.client360 import Client360Opportunity
from app.models.expert_capture import ExpertCaptureSession, KnowledgeUpdateProposal
from app.models.user import Session as ChatSession
from app.models.user import User
from app.models.workspace import (
    Workspace,
    WorkspaceMember,
    WorkspaceMemberAppEntitlement,
)
from app.services.iam.app_entitlements import (
    BUSINESS_APP_KEYS,
    CHAT_APP,
)

MEMBER_ROLES = (
    "workspace_viewer",
    "workspace_contributor",
    "workspace_reviewer",
    "workspace_admin",
)


@dataclass(frozen=True)
class AndritzContractState:
    workspace: Workspace
    other_workspace: Workspace
    users: dict[str, User]
    chat_sessions: dict[str, ChatSession]
    capture_sessions: dict[str, ExpertCaptureSession]
    proposal: KnowledgeUpdateProposal
    opportunity: Client360Opportunity
    foreign_opportunity: Client360Opportunity


def _make_user(role_template: str) -> User:
    suffix = role_template.removeprefix("workspace_")
    return User(
        id=f"andritz-{suffix}",
        username=f"andritz-{suffix}",
        email=f"andritz-{suffix}@example.test",
        # Keep platform-level admin disabled: workspace_admin must be proven by
        # its membership template, as it is for customer workspace admins.
        role="user",
        is_active=True,
    )


def _seed_andritz_contract(db_session) -> AndritzContractState:
    workspace = Workspace(
        id="workspace-andritz-contract",
        slug="andritz",
        name="Andritz",
        mode="executive",
        settings={
            "family": "andritz",
            "features": {
                "iam_enforced": True,
                "app_entitlements_v1": True,
                "workspace_experience_v2": True,
            },
            "navigation_profile": {
                "key": "business_end_user",
                "default_route": "/chat",
                "primary_surfaces": ["chat", "client360-pdr", "knowledge-capture"],
                "advanced_access": "admin_only",
            },
        },
    )
    other_workspace = Workspace(
        id="workspace-other-contract",
        slug="other-contract",
        name="Other Contract Workspace",
        mode="executive",
    )
    users = {role: _make_user(role) for role in MEMBER_ROLES}
    # A platform-level admin is still not allowed into Andritz without a
    # WorkspaceMember row.
    users["nonmember"] = User(
        id="andritz-nonmember",
        username="andritz-nonmember",
        email="andritz-nonmember@example.test",
        role="admin",
        is_active=True,
    )
    db_session.add_all([workspace, other_workspace, *users.values()])
    db_session.flush()

    memberships: dict[str, WorkspaceMember] = {}
    for role_template in MEMBER_ROLES:
        user = users[role_template]
        membership = WorkspaceMember(
            user_id=user.id,
            workspace_id=workspace.id,
            role=legacy_role_for_template(role_template),
            role_template=role_template,
        )
        memberships[role_template] = membership
        db_session.add(membership)
    db_session.flush()

    for membership in memberships.values():
        db_session.add_all(
            [
                WorkspaceMemberAppEntitlement(
                    workspace_member_id=membership.id,
                    app_key=app_key,
                    grant_source="andritz-contract-fixture",
                )
                for app_key in BUSINESS_APP_KEYS
            ]
        )

    chat_sessions: dict[str, ChatSession] = {}
    capture_sessions: dict[str, ExpertCaptureSession] = {}
    for role_template in MEMBER_ROLES:
        suffix = role_template.removeprefix("workspace_")
        user = users[role_template]
        chat_session = ChatSession(
            id=f"chat-{suffix}",
            workspace_id=workspace.id,
            user_id=user.id,
            title=f"Chat {suffix}",
            status="active",
        )
        capture_session = ExpertCaptureSession(
            id=f"capture-{suffix}",
            workspace_id=workspace.id,
            created_by_user_id=user.id,
            title=f"Capture {suffix}",
            objective=f"Baseline Andritz capture for {suffix}.",
            status="completed",
            plan={
                "schema_version": "free_conversation_v1",
                "mode": "free_conversation",
                "topics": [],
            },
        )
        chat_sessions[role_template] = chat_session
        capture_sessions[role_template] = capture_session
        db_session.add_all([chat_session, capture_session])

    proposal = KnowledgeUpdateProposal(
        id="andritz-proposal-contributor",
        workspace_id=workspace.id,
        session_id=capture_sessions["workspace_contributor"].id,
        created_by_user_id=users["workspace_contributor"].id,
        status="pending_review",
        proposal={
            "title": "Andritz baseline proposal",
            "report_markdown": "## Baseline\nCurrent review contract.",
        },
    )
    opportunity = Client360Opportunity(
        id="andritz-client360-opportunity",
        workspace_id=workspace.id,
        customer_key="andritz-customer",
        customer_name="Andritz Customer",
        part_family="wear belts",
        part_reference="PDR-CONTRACT-001",
        status="detected",
    )
    foreign_opportunity = Client360Opportunity(
        id="foreign-client360-opportunity",
        workspace_id=other_workspace.id,
        customer_key="foreign-customer",
        customer_name="Foreign Customer",
        part_family="foreign parts",
        part_reference="PDR-FOREIGN-001",
        status="detected",
    )
    db_session.add_all([proposal, opportunity, foreign_opportunity])
    db_session.commit()

    return AndritzContractState(
        workspace=workspace,
        other_workspace=other_workspace,
        users=users,
        chat_sessions=chat_sessions,
        capture_sessions=capture_sessions,
        proposal=proposal,
        opportunity=opportunity,
        foreign_opportunity=foreign_opportunity,
    )


def _client(db_session, user: User) -> TestClient:
    app = FastAPI()
    app.include_router(chat.router, prefix="/api/v1/chat")
    app.include_router(sessions.router, prefix="/api/v1/sessions")
    app.include_router(knowledge_capture.router, prefix="/api/v1/knowledge-capture")
    app.include_router(client360.router, prefix="/api/v1/client360")
    # Do not override get_current_workspace: its membership resolution is part
    # of the contract under test.
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = lambda: db_session
    return TestClient(app)


def _andritz_headers() -> dict[str, str]:
    return {"X-Workspace-Slug": "andritz"}


@pytest.mark.parametrize("role_template", MEMBER_ROLES)
def test_every_andritz_member_role_can_reach_all_three_business_surfaces(
    db_session,
    role_template: str,
) -> None:
    """Viewer through admin retain a readable entry point on each surface."""
    state = _seed_andritz_contract(db_session)
    client = _client(db_session, state.users[role_template])
    headers = _andritz_headers()

    chat_response = client.get("/api/v1/sessions", headers=headers)
    capture_response = client.get("/api/v1/knowledge-capture/voice-runtimes", headers=headers)
    client360_response = client.get("/api/v1/client360/scope", headers=headers)

    assert chat_response.status_code == 200
    assert capture_response.status_code == 200
    assert client360_response.status_code == 200


@pytest.mark.parametrize(
    "path",
    (
        "/api/v1/sessions",
        "/api/v1/knowledge-capture/voice-runtimes",
        "/api/v1/client360/scope",
    ),
)
def test_nonmember_cannot_reach_any_andritz_business_surface(db_session, path: str) -> None:
    state = _seed_andritz_contract(db_session)
    client = _client(db_session, state.users["nonmember"])

    response = client.get(path, headers=_andritz_headers())

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "WORKSPACE_ACCESS_DENIED"


def test_feature_disabled_preserves_legacy_membership_entry_without_grants(db_session) -> None:
    state = _seed_andritz_contract(db_session)
    viewer = state.users["workspace_viewer"]
    membership = db_session.query(WorkspaceMember).filter_by(
        workspace_id=state.workspace.id,
        user_id=viewer.id,
    ).one()
    db_session.query(WorkspaceMemberAppEntitlement).filter_by(
        workspace_member_id=membership.id,
    ).delete(synchronize_session=False)
    state.workspace.settings = {
        **(state.workspace.settings or {}),
        "features": {
            **((state.workspace.settings or {}).get("features") or {}),
            "app_entitlements_v1": False,
        },
    }
    db_session.commit()

    client = _client(db_session, viewer)
    headers = _andritz_headers()
    assert client.get("/api/v1/sessions", headers=headers).status_code == 200
    assert (
        client.get("/api/v1/knowledge-capture/voice-runtimes", headers=headers).status_code
        == 200
    )
    assert client.get("/api/v1/client360/scope", headers=headers).status_code == 200


def test_workspace_admin_cannot_bypass_a_missing_app_grant(db_session) -> None:
    state = _seed_andritz_contract(db_session)
    admin = state.users["workspace_admin"]
    membership = db_session.query(WorkspaceMember).filter_by(
        workspace_id=state.workspace.id,
        user_id=admin.id,
    ).one()
    db_session.query(WorkspaceMemberAppEntitlement).filter_by(
        workspace_member_id=membership.id,
        app_key=CHAT_APP,
    ).delete(synchronize_session=False)
    db_session.commit()

    client = _client(db_session, admin)
    headers = _andritz_headers()
    denied = client.get("/api/v1/sessions", headers=headers)

    assert denied.status_code == 403
    assert denied.json()["detail"] == {
        "code": "WORKSPACE_APP_ACCESS_DENIED",
        "message": "Workspace application access denied",
        "app_key": CHAT_APP,
    }
    # Grants are app-specific: the same admin retains the other two surfaces.
    assert (
        client.get("/api/v1/knowledge-capture/voice-runtimes", headers=headers).status_code
        == 200
    )
    assert client.get("/api/v1/client360/scope", headers=headers).status_code == 200


@pytest.mark.parametrize(
    ("app_key", "method", "path", "body"),
    (
        (CHAT_APP, "post", "/api/v1/chat/completion", {"query": "blocked"}),
        (CHAT_APP, "get", "/api/v1/sessions", None),
        (
            "knowledge-capture",
            "get",
            "/api/v1/knowledge-capture/voice-runtimes",
            None,
        ),
        ("client360-pdr", "get", "/api/v1/client360/scope", None),
    ),
)
def test_each_business_router_enforces_its_exact_app_grant(
    db_session,
    app_key: str,
    method: str,
    path: str,
    body: dict | None,
) -> None:
    state = _seed_andritz_contract(db_session)
    admin = state.users["workspace_admin"]
    membership = db_session.query(WorkspaceMember).filter_by(
        workspace_id=state.workspace.id,
        user_id=admin.id,
    ).one()
    db_session.query(WorkspaceMemberAppEntitlement).filter_by(
        workspace_member_id=membership.id,
        app_key=app_key,
    ).delete(synchronize_session=False)
    db_session.commit()

    client = _client(db_session, admin)
    response = client.request(
        method,
        path,
        headers=_andritz_headers(),
        json=body,
    )

    assert response.status_code == 403
    assert response.json()["detail"] == {
        "code": "WORKSPACE_APP_ACCESS_DENIED",
        "message": "Workspace application access denied",
        "app_key": app_key,
    }


def test_same_app_grant_in_another_workspace_does_not_authorize_andritz(db_session) -> None:
    state = _seed_andritz_contract(db_session)
    contributor = state.users["workspace_contributor"]
    andritz_membership = db_session.query(WorkspaceMember).filter_by(
        workspace_id=state.workspace.id,
        user_id=contributor.id,
    ).one()
    db_session.query(WorkspaceMemberAppEntitlement).filter_by(
        workspace_member_id=andritz_membership.id,
        app_key=CHAT_APP,
    ).delete(synchronize_session=False)
    other_membership = WorkspaceMember(
        workspace_id=state.other_workspace.id,
        user_id=contributor.id,
        role="member",
        role_template="workspace_contributor",
    )
    db_session.add(other_membership)
    db_session.flush()
    db_session.add(
        WorkspaceMemberAppEntitlement(
            workspace_member_id=other_membership.id,
            app_key=CHAT_APP,
            grant_source="cross-workspace-contract-fixture",
        )
    )
    db_session.commit()

    response = _client(db_session, contributor).get(
        "/api/v1/sessions",
        headers=_andritz_headers(),
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "WORKSPACE_APP_ACCESS_DENIED"


@pytest.mark.parametrize("role_template", MEMBER_ROLES)
def test_andritz_chat_ownership_and_admin_read_only_contract(
    db_session,
    role_template: str,
) -> None:
    state = _seed_andritz_contract(db_session)
    user = state.users[role_template]
    client = _client(db_session, user)
    headers = _andritz_headers()
    own = state.chat_sessions[role_template]
    foreign_role = (
        "workspace_viewer" if role_template != "workspace_viewer" else "workspace_contributor"
    )
    foreign = state.chat_sessions[foreign_role]

    listed = client.get(
        "/api/v1/sessions?include_admin=true&status=all",
        headers=headers,
    )
    assert listed.status_code == 200
    listed_ids = {row["id"] for row in listed.json()["sessions"]}
    if role_template == "workspace_admin":
        assert listed_ids == {session.id for session in state.chat_sessions.values()}
    else:
        assert listed_ids == {own.id}

    own_update = client.patch(
        f"/api/v1/sessions/{own.id}",
        json={"title": f"Updated by {role_template}"},
        headers=headers,
    )
    assert own_update.status_code == 200

    foreign_read = client.get(f"/api/v1/sessions/{foreign.id}", headers=headers)
    foreign_update = client.patch(
        f"/api/v1/sessions/{foreign.id}",
        json={"title": "Must not be changed"},
        headers=headers,
    )
    if role_template == "workspace_admin":
        assert foreign_read.status_code == 200
        assert foreign_update.status_code == 403
    else:
        assert foreign_read.status_code == 404
        assert foreign_update.status_code == 404


@pytest.mark.parametrize(
    ("role_template", "expected_status", "expected_visibility"),
    (
        ("workspace_viewer", 403, set()),
        ("workspace_contributor", 200, {"capture-contributor"}),
        (
            "workspace_reviewer",
            200,
            {"capture-viewer", "capture-contributor", "capture-reviewer", "capture-admin"},
        ),
        (
            "workspace_admin",
            200,
            {"capture-viewer", "capture-contributor", "capture-reviewer", "capture-admin"},
        ),
    ),
)
def test_andritz_capture_session_visibility_follows_current_iam_contract(
    db_session,
    role_template: str,
    expected_status: int,
    expected_visibility: set[str],
) -> None:
    state = _seed_andritz_contract(db_session)
    client = _client(db_session, state.users[role_template])

    response = client.get("/api/v1/knowledge-capture/sessions", headers=_andritz_headers())

    assert response.status_code == expected_status
    if expected_status == 200:
        assert {row["id"] for row in response.json()["sessions"]} == expected_visibility


@pytest.mark.parametrize(
    ("role_template", "expected_status"),
    (
        ("workspace_viewer", 403),
        ("workspace_contributor", 200),
        ("workspace_reviewer", 200),
        ("workspace_admin", 200),
    ),
)
def test_andritz_capture_creation_follows_current_iam_contract(
    db_session,
    monkeypatch,
    role_template: str,
    expected_status: int,
) -> None:
    state = _seed_andritz_contract(db_session)

    async def _skip_warm_cache(*_args, **_kwargs):
        return {"status": "skipped", "reason": "contract-test"}

    monkeypatch.setattr(knowledge_capture, "warm_capture_context_cache", _skip_warm_cache)
    client = _client(db_session, state.users[role_template])
    response = client.post(
        "/api/v1/knowledge-capture/plans",
        json={
            "title": f"Contract capture {role_template}",
            "objective": "Preserve the current Andritz creation contract.",
            "duration_minutes": 0,
            "plan_mode": "free_conversation",
        },
        headers=_andritz_headers(),
    )

    assert response.status_code == expected_status
    if expected_status == 200:
        assert response.json()["created_by_user_id"] == state.users[role_template].id


@pytest.mark.parametrize(
    ("role_template", "expected_status"),
    (
        ("workspace_viewer", 403),
        ("workspace_contributor", 403),
        ("workspace_reviewer", 403),
        ("workspace_admin", 200),
    ),
)
def test_only_andritz_admin_can_mutate_another_members_capture_session(
    db_session,
    role_template: str,
    expected_status: int,
) -> None:
    state = _seed_andritz_contract(db_session)
    client = _client(db_session, state.users[role_template])
    foreign_session = state.capture_sessions["workspace_contributor"]
    if role_template == "workspace_contributor":
        foreign_session = state.capture_sessions["workspace_reviewer"]

    response = client.post(
        f"/api/v1/knowledge-capture/sessions/{foreign_session.id}/archive",
        headers=_andritz_headers(),
    )

    assert response.status_code == expected_status


@pytest.mark.parametrize(
    ("role_template", "expected_status"),
    (
        ("workspace_viewer", 403),
        ("workspace_contributor", 403),
        ("workspace_reviewer", 200),
        ("workspace_admin", 200),
    ),
)
def test_andritz_proposal_review_is_reserved_for_reviewer_and_admin(
    db_session,
    role_template: str,
    expected_status: int,
) -> None:
    state = _seed_andritz_contract(db_session)
    client = _client(db_session, state.users[role_template])

    response = client.patch(
        f"/api/v1/knowledge-capture/proposals/{state.proposal.id}/review",
        json={"status": "rejected", "review_notes": "Contract role check"},
        headers=_andritz_headers(),
    )

    assert response.status_code == expected_status


@pytest.mark.parametrize("role_template", MEMBER_ROLES)
def test_client360_current_contract_is_membership_scoped_for_read_and_mutation(
    db_session,
    role_template: str,
) -> None:
    """Snapshot the current membership-only Client360 policy before IAM work."""
    state = _seed_andritz_contract(db_session)
    client = _client(db_session, state.users[role_template])
    headers = _andritz_headers()

    listed = client.get("/api/v1/client360/opportunities", headers=headers)
    assert listed.status_code == 200
    assert [row["id"] for row in listed.json()["items"]] == [state.opportunity.id]

    updated = client.patch(
        f"/api/v1/client360/opportunities/{state.opportunity.id}",
        json={"status": "validated", "validation_reason": f"Baseline {role_template}"},
        headers=headers,
    )
    assert updated.status_code == 200
    assert updated.json()["opportunity"]["status"] == "validated"

    foreign_update = client.patch(
        f"/api/v1/client360/opportunities/{state.foreign_opportunity.id}",
        json={"status": "validated"},
        headers=headers,
    )
    assert foreign_update.status_code == 404
