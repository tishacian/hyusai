from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import automation_edit
from app.core.iam.roles import WORKSPACE_ADMIN, WORKSPACE_CONTRIBUTOR
from app.models.system import System
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember


def _client(db_session, workspace: Workspace, user: User) -> TestClient:
    app = FastAPI()
    app.include_router(automation_edit.router, prefix="/systems")
    app.dependency_overrides[automation_edit.get_current_user] = lambda: user
    app.dependency_overrides[automation_edit.get_current_workspace] = lambda: workspace
    app.dependency_overrides[automation_edit.get_db] = lambda: db_session
    return TestClient(app)


def _seed(db_session):
    workspace = Workspace(
        id="ws-assistant-edit",
        slug="assistant-edit",
        name="Assistant edit",
        settings={
            "assistant": {
                "editors": {
                    "minimum_role": WORKSPACE_ADMIN,
                    "user_ids": ["user-assistant-editor"],
                }
            }
        },
    )
    owner = User(id="user-assistant-owner", username="owner", email="owner@example.test")
    editor = User(id="user-assistant-editor", username="editor", email="editor@example.test")
    contributor = User(
        id="user-assistant-contributor",
        username="contributor",
        email="contributor@example.test",
    )
    system = System(id="system-assistant-edit", workspace_id=workspace.id, name="Automation")
    db_session.add_all(
        [
            workspace,
            owner,
            editor,
            contributor,
            system,
            WorkspaceMember(
                workspace_id=workspace.id,
                user_id=owner.id,
                role="admin",
                role_template=WORKSPACE_ADMIN,
            ),
            WorkspaceMember(
                workspace_id=workspace.id,
                user_id=editor.id,
                role="member",
                role_template=WORKSPACE_CONTRIBUTOR,
            ),
            WorkspaceMember(
                workspace_id=workspace.id,
                user_id=contributor.id,
                role="member",
                role_template=WORKSPACE_CONTRIBUTOR,
            ),
        ]
    )
    db_session.commit()
    return workspace, system, editor, contributor


def test_assistant_edit_policy_allows_named_editor(db_session):
    workspace, system, editor, _contributor = _seed(db_session)

    response = _client(db_session, workspace, editor).post(
        f"/systems/{system.id}/automation-turn",
        json={"message": "make the summary shorter"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Automation draft not found"


def test_assistant_edit_policy_refuses_member_below_minimum_role(db_session):
    workspace, system, _editor, contributor = _seed(db_session)

    response = _client(db_session, workspace, contributor).post(
        f"/systems/{system.id}/automation-turn",
        json={"message": "make the summary shorter"},
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "AUTOMATION_EDIT_NOT_ALLOWED"
    assert response.json()["detail"]["message"] == (
        "You are not allowed to edit automations with the assistant. "
        "Ask a workspace administrator."
    )
