from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import auth
from app.api.v1.endpoints import workspace_experience_activation as endpoint
from app.models.audit import AuditLog
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember


def _seed(db_session, *, enabled: bool | None = None, role_template: str = "workspace_admin"):
    features = {} if enabled is None else {"experience_v1": enabled}
    workspace = Workspace(
        id="ws-activation",
        slug="activation",
        name="Activation",
        settings={"family": "generic", "features": {**features, "keep": True}, "other": {"a": 1}},
    )
    admin = User(id="u-admin", username="admin@example.invalid", email="admin@example.invalid")
    db_session.add_all([workspace, admin])
    db_session.add(
        WorkspaceMember(
            workspace_id=workspace.id,
            user_id=admin.id,
            role="admin" if role_template == "workspace_admin" else "member",
            role_template=role_template,
        )
    )
    for index, template in enumerate(
        ["workspace_viewer", "workspace_viewer", "workspace_contributor", "workspace_reviewer"]
    ):
        user = User(id=f"u-{index}", username=f"u{index}@example.invalid")
        db_session.add(user)
        db_session.add(
            WorkspaceMember(
                workspace_id=workspace.id, user_id=user.id, role="member", role_template=template
            )
        )
    db_session.commit()
    return workspace, admin


def _client(db_session, user: User) -> TestClient:
    app = FastAPI()
    app.include_router(endpoint.router, prefix="/auth")
    app.dependency_overrides[auth.get_current_user] = lambda: user
    app.dependency_overrides[endpoint.get_current_user] = lambda: user
    app.dependency_overrides[endpoint.get_db] = lambda: db_session
    return TestClient(app)


URL = "/auth/workspaces/activation/features/experience"


def test_read_tells_the_admin_who_the_change_affects(db_session):
    _, admin = _seed(db_session)
    response = _client(db_session, admin).get(URL)
    assert response.status_code == 200, response.text
    assert response.json() == {
        "enabled": False,
        "studio_enabled": False,
        "members": {"total": 5, "studio_editors": 2, "studio_reviewers": 1},
    }


def test_enable_changes_only_the_flag_and_is_audited(db_session):
    workspace, admin = _seed(db_session)
    client = _client(db_session, admin)
    response = client.put(URL, json={"enabled": True, "expected_enabled": False})
    assert response.status_code == 200, response.text
    assert response.json()["enabled"] is True
    assert response.json()["studio_enabled"] is True
    db_session.refresh(workspace)
    assert workspace.settings == {
        "family": "generic",
        "features": {"experience_v1": True, "keep": True},
        "other": {"a": 1},
    }
    audit = db_session.query(AuditLog).filter_by(event_type="workspace.feature.updated").one()
    assert audit.actor == admin.id
    assert audit.details == {"feature": "experience_v1", "before": False, "after": True}


def test_stale_expected_value_is_refused_with_the_current_value(db_session):
    workspace, admin = _seed(db_session, enabled=True)
    response = _client(db_session, admin).put(
        URL, json={"enabled": True, "expected_enabled": False}
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "WORKSPACE_FEATURE_CONFLICT"
    assert response.json()["detail"]["current_enabled"] is True
    assert db_session.query(AuditLog).filter_by(event_type="workspace.feature.updated").count() == 0


def test_disable_then_no_op_writes_one_audit_row(db_session):
    workspace, admin = _seed(db_session, enabled=True)
    client = _client(db_session, admin)
    assert (
        client.put(URL, json={"enabled": False, "expected_enabled": True}).json()["enabled"]
        is False
    )
    assert client.put(URL, json={"enabled": False, "expected_enabled": False}).status_code == 200
    assert db_session.query(AuditLog).filter_by(event_type="workspace.feature.updated").count() == 1
    db_session.refresh(workspace)
    assert workspace.settings["features"]["experience_v1"] is False


def test_non_admin_can_neither_read_nor_change(db_session):
    workspace, user = _seed(db_session, role_template="workspace_contributor")
    client = _client(db_session, user)
    assert client.get(URL).status_code == 403
    assert client.put(URL, json={"enabled": True, "expected_enabled": False}).status_code == 403
    db_session.refresh(workspace)
    assert "experience_v1" not in workspace.settings["features"]


def test_unknown_workspace_and_extra_fields_are_refused(db_session):
    _, admin = _seed(db_session)
    client = _client(db_session, admin)
    assert client.get("/auth/workspaces/missing/features/experience").status_code == 404
    assert (
        client.put(
            URL, json={"enabled": True, "expected_enabled": False, "settings": {}}
        ).status_code
        == 422
    )


def test_experience_v1_is_not_a_code_default_for_new_workspaces():
    """Provisional choice of the UI/UX plan (lot 4): an administrator setting only."""
    from app.services.workspace_features import DEFAULT_ON_FEATURES

    assert "experience_v1" not in DEFAULT_ON_FEATURES
    assert not Workspace(settings={"family": "generic"}).settings.get("features")
