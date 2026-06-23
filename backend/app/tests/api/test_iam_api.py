from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import iam
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember


def _client(db_session, workspace: Workspace, user: User) -> TestClient:
    app = FastAPI()
    app.include_router(iam.router, prefix="/api/v1/iam")
    app.dependency_overrides[iam.get_current_workspace] = lambda: workspace
    app.dependency_overrides[iam.get_current_user] = lambda: user
    app.dependency_overrides[iam.get_db] = lambda: db_session
    return TestClient(app)


def test_iam_matrix_exposes_reviewer_capture_create_and_owned_execution(db_session):
    workspace = Workspace(
        id="ws-iam-matrix-reviewer-capture",
        name="IAM Matrix Reviewer Capture",
        slug="iam-matrix-reviewer-capture",
        settings={"features": {"iam_enforced": True}},
    )
    reviewer = User(
        id="user-iam-matrix-reviewer-capture",
        username="reviewer-matrix",
        email="reviewer-matrix@example.test",
    )
    db_session.add_all(
        [
            workspace,
            reviewer,
            WorkspaceMember(
                user_id=reviewer.id,
                workspace_id=workspace.id,
                role="member",
                role_template="workspace_reviewer",
            ),
        ]
    )
    db_session.commit()

    response = _client(db_session, workspace, reviewer).get("/api/v1/iam/matrix")

    assert response.status_code == 200
    body = response.json()
    assert body["role_template"] == "workspace_reviewer"
    assert body["enforcement"] is True
    permissions = {
        (item["resource_kind"], item["action"], tuple(item["conditions"])): item["allowed_for_subject"]
        for item in body["permissions"]
    }
    assert permissions[("capture_session", "create", ())] is True
    assert permissions[("capture_session", "update", ("owner_match",))] is True
    assert permissions[("capture_session", "execute", ("owner_match",))] is True
