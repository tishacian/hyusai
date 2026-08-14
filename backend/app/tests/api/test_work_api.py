"""GET /work/{slug} — live preferred, entitled pilot, flag-gated."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import work as endpoint
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember


def _seed(db_session, *, enabled: bool = True, role_template: str = "workspace_admin"):
    workspace = Workspace(
        id="ws-work-api",
        slug="work-api",
        name="Work API",
        settings={"features": {"experience_v1": enabled}},
    )
    user = User(
        id="user-work-admin",
        username="work-admin@example.invalid",
        email="work-admin@example.invalid",
        role="admin" if role_template == "workspace_admin" else "member",
    )
    member = WorkspaceMember(
        workspace_id=workspace.id,
        user_id=user.id,
        role="admin" if role_template == "workspace_admin" else "member",
        role_template=role_template,
    )
    db_session.add_all([workspace, user, member])
    db_session.commit()
    return workspace, user


def _client(db_session, workspace: Workspace, user: User) -> TestClient:
    app = FastAPI()
    app.include_router(endpoint.router, prefix="/work")
    app.dependency_overrides[endpoint.get_current_workspace] = lambda: workspace
    app.dependency_overrides[endpoint.get_current_user] = lambda: user
    app.dependency_overrides[endpoint.get_db] = lambda: db_session
    return TestClient(app)


def _experiences_client(db_session, workspace: Workspace, user: User) -> TestClient:
    from app.api.v1.endpoints import experiences as experiences_endpoint

    app = FastAPI()
    app.include_router(experiences_endpoint.router, prefix="/experiences")
    app.dependency_overrides[experiences_endpoint.get_current_workspace] = lambda: workspace
    app.dependency_overrides[experiences_endpoint.get_current_user] = lambda: user
    app.dependency_overrides[experiences_endpoint.get_db] = lambda: db_session
    return TestClient(app)


def _pages() -> dict:
    return {
        "pages": [
            {
                "id": "home",
                "title": "Home",
                "components": [{"type": "header", "props": {"title": "Reset"}}],
            }
        ]
    }


def _publish(client: TestClient, *, audience: dict | None = None, channel: str = "live"):
    created = client.post(
        "/experiences",
        json={"name": "Password reset", "slug": "password-reset", "pattern": "form_result"},
    )
    assert created.status_code == 201, created.text
    experience_id = created.json()["id"]
    assert client.put(
        f"/experiences/{experience_id}/draft",
        json={"pages": _pages(), "binding_keys": []},
    ).status_code == 200
    released = client.post(f"/experiences/{experience_id}/releases", json={"notes": "r1"})
    assert released.status_code == 201, released.text
    body: dict = {"channel": channel, "release_id": released.json()["id"]}
    if audience is not None:
        body["audience"] = audience
    deployed = client.post(f"/experiences/{experience_id}/deployments", json=body)
    assert deployed.status_code == 201, deployed.text
    return experience_id, released.json()["id"]


def test_work_is_feature_gated(db_session) -> None:
    workspace, user = _seed(db_session, enabled=False)
    client = _client(db_session, workspace, user)

    response = client.get("/work/password-reset")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "EXPERIENCE_V1_DISABLED"


def test_work_unknown_slug_is_not_found(db_session) -> None:
    workspace, user = _seed(db_session)
    client = _client(db_session, workspace, user)

    response = client.get("/work/missing-app")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "EXPERIENCE_NOT_FOUND"


def test_work_prefers_live_and_returns_frozen_pages(db_session) -> None:
    workspace, user = _seed(db_session)
    studio = _experiences_client(db_session, workspace, user)
    experience_id, release_id = _publish(studio, channel="pilot")
    listed = studio.get("/experiences")
    assert studio.post(
        f"/experiences/{experience_id}/deployments",
        json={"channel": "live", "release_id": release_id},
    ).status_code == 201

    work = _client(db_session, workspace, user).get("/work/password-reset")

    assert work.status_code == 200, work.text
    body = work.json()
    assert body["channel"] == "live"
    assert body["experience"]["slug"] == "password-reset"
    assert body["release"]["pages"]["pages"][0]["id"] == "home"
    assert body["release"]["bindings_snapshot"] == []
    assert body["release"]["renderer_version"] == "certified-components-0.1.0"
    assert listed.json()["experiences"][0]["deployments"]


def test_work_returns_pages_when_renderer_pin_mismatches(db_session) -> None:
    from app.models.experience import ExperienceRelease

    workspace, user = _seed(db_session)
    studio = _experiences_client(db_session, workspace, user)
    _publish(studio, channel="live")
    release = db_session.query(ExperienceRelease).one()
    release.renderer_version = "certified-components-9.9.9"
    db_session.commit()

    work = _client(db_session, workspace, user).get("/work/password-reset")

    assert work.status_code == 200, work.text
    body = work.json()
    assert body["release"]["pages"]["pages"][0]["id"] == "home"
    assert body["release"]["renderer_version"] == "certified-components-9.9.9"


def test_work_pilot_empty_audience_is_open(db_session) -> None:
    workspace, admin = _seed(db_session)
    studio = _experiences_client(db_session, workspace, admin)
    _publish(studio, channel="pilot", audience={})

    viewer = User(
        id="user-work-viewer",
        username="work-viewer@example.invalid",
        email="work-viewer@example.invalid",
        role="member",
    )
    db_session.add_all(
        [
            viewer,
            WorkspaceMember(
                workspace_id=workspace.id,
                user_id=viewer.id,
                role="member",
                role_template="workspace_viewer",
            ),
        ]
    )
    db_session.commit()

    work = _client(db_session, workspace, viewer).get("/work/password-reset")

    assert work.status_code == 200, work.text
    assert work.json()["channel"] == "pilot"


def test_work_pilot_hides_unentitled_audience(db_session) -> None:
    workspace, admin = _seed(db_session)
    studio = _experiences_client(db_session, workspace, admin)
    _publish(studio, channel="pilot", audience={"roles": ["workspace_admin"]})

    viewer = User(
        id="user-work-viewer-closed",
        username="work-viewer-closed@example.invalid",
        email="work-viewer-closed@example.invalid",
        role="member",
    )
    db_session.add_all(
        [
            viewer,
            WorkspaceMember(
                workspace_id=workspace.id,
                user_id=viewer.id,
                role="member",
                role_template="workspace_viewer",
            ),
        ]
    )
    db_session.commit()

    hidden = _client(db_session, workspace, viewer).get("/work/password-reset")
    visible = _client(db_session, workspace, admin).get("/work/password-reset")

    assert hidden.status_code == 404
    assert visible.status_code == 200
    assert visible.json()["channel"] == "pilot"
