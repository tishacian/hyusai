"""A member's role changes only from the role the administrator saw."""

from __future__ import annotations

from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import auth
from app.core.iam.roles import WORKSPACE_ADMIN, WORKSPACE_CONTRIBUTOR, WORKSPACE_OWNER, WORKSPACE_REVIEWER
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember


def _seed(db_session):
    token = uuid4().hex[:8]
    workspace = Workspace(id=str(uuid4()), name="Roles", slug=f"roles-{token}", settings={})
    owner = User(id=str(uuid4()), username=f"owner-{token}", email=f"owner-{token}@example.test", role="user")
    admin = User(id=str(uuid4()), username=f"admin-{token}", email=f"admin-{token}@example.test", role="user")
    member = User(id=str(uuid4()), username=f"member-{token}", email=f"member-{token}@example.test", role="user")
    db_session.add_all([
        workspace, owner, admin, member,
        WorkspaceMember(workspace_id=workspace.id, user_id=owner.id, role="owner", role_template=WORKSPACE_OWNER),
        WorkspaceMember(workspace_id=workspace.id, user_id=admin.id, role="admin", role_template=WORKSPACE_ADMIN),
        WorkspaceMember(workspace_id=workspace.id, user_id=member.id, role="member", role_template=WORKSPACE_CONTRIBUTOR),
    ])
    db_session.commit()
    return workspace, owner, admin, member


def _client(db_session, user: User) -> TestClient:
    app = FastAPI()
    app.include_router(auth.router, prefix="/auth")
    app.dependency_overrides[auth.get_current_user] = lambda: user
    app.dependency_overrides[auth.get_db] = lambda: db_session
    return TestClient(app)


def _role(db_session, workspace, user) -> str:
    db_session.expire_all()
    return db_session.query(WorkspaceMember).filter_by(workspace_id=workspace.id, user_id=user.id).one().role_template


def test_role_change_applies_when_the_seen_role_is_still_current(db_session):
    workspace, owner, _admin, member = _seed(db_session)
    response = _client(db_session, owner).patch(
        f"/auth/workspaces/{workspace.slug}/members/{member.id}",
        json={"role_template": WORKSPACE_REVIEWER, "expected_role_template": WORKSPACE_CONTRIBUTOR},
    )
    assert response.status_code == 200, response.text
    assert _role(db_session, workspace, member) == WORKSPACE_REVIEWER


def test_two_administrators_changing_the_same_role_never_overwrite_each_other(db_session):
    workspace, owner, admin, member = _seed(db_session)
    first = _client(db_session, owner).patch(
        f"/auth/workspaces/{workspace.slug}/members/{member.id}",
        json={"role_template": WORKSPACE_REVIEWER, "expected_role_template": WORKSPACE_CONTRIBUTOR},
    )
    assert first.status_code == 200, first.text
    # The second administrator still saw "contributor".
    second = _client(db_session, admin).patch(
        f"/auth/workspaces/{workspace.slug}/members/{member.id}",
        json={"role_template": WORKSPACE_ADMIN, "expected_role_template": WORKSPACE_CONTRIBUTOR},
    )
    assert second.status_code == 409, second.text
    assert second.json()["detail"]["code"] == "member_role_changed"
    assert second.json()["detail"]["current_role_template"] == WORKSPACE_REVIEWER
    assert _role(db_session, workspace, member) == WORKSPACE_REVIEWER


def test_a_change_without_the_seen_role_keeps_the_previous_contract(db_session):
    workspace, owner, _admin, member = _seed(db_session)
    response = _client(db_session, owner).patch(
        f"/auth/workspaces/{workspace.slug}/members/{member.id}",
        json={"role_template": WORKSPACE_REVIEWER},
    )
    assert response.status_code == 200, response.text
    assert _role(db_session, workspace, member) == WORKSPACE_REVIEWER
