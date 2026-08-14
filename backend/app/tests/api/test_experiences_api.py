"""Experience draft / release / deploy — gated by experience_v1."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import experiences as endpoint
from app.models.audit import AuditLog
from app.models.experience import Experience, ExperienceDeployment, ExperienceRelease
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services.iam.manifest import (
    ALL_CAPTURE_ROLES,
    CONTRIBUTOR_OR_ADMIN,
    REVIEW_ROLES,
    get_manifest,
)


def _seed(db_session, *, enabled: bool = True, role_template: str = "workspace_admin"):
    workspace = Workspace(
        id="ws-experience-api",
        slug="experience-api",
        name="Experience API",
        settings={"features": {"experience_v1": enabled}},
    )
    user = User(
        id="user-experience-admin",
        username="experience-admin@example.invalid",
        email="experience-admin@example.invalid",
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
    app.include_router(endpoint.router, prefix="/experiences")
    app.dependency_overrides[endpoint.get_current_workspace] = lambda: workspace
    app.dependency_overrides[endpoint.get_current_user] = lambda: user
    app.dependency_overrides[endpoint.get_db] = lambda: db_session
    return TestClient(app)


def _create_body(**overrides):
    body = {
        "name": "Password reset",
        "slug": "password-reset",
        "pattern": "form_result",
        "languages": ["en"],
        "theme": {},
    }
    body.update(overrides)
    return body


def _pages(*component_types: str) -> dict:
    components = [{"type": item} for item in component_types] or [{"type": "header"}]
    return {
        "pages": [
            {
                "id": "home",
                "title": "Home",
                "components": components,
            }
        ]
    }


def test_experience_actions_are_declared_on_the_object_actions_manifest() -> None:
    rules = {
        (rule.resource_kind, rule.action): rule
        for rule in get_manifest("agentium_object_actions", strict=True).permissions
    }
    assert rules[("experience", "view")].roles == ALL_CAPTURE_ROLES
    assert rules[("experience", "edit")].roles == CONTRIBUTOR_OR_ADMIN
    assert rules[("experience", "release")].roles == REVIEW_ROLES
    assert rules[("experience", "deploy")].roles == REVIEW_ROLES


def test_experiences_are_feature_gated(db_session) -> None:
    workspace, user = _seed(db_session, enabled=False)
    client = _client(db_session, workspace, user)

    listed = client.get("/experiences")
    created = client.post("/experiences", json=_create_body())

    assert listed.status_code == 404
    assert listed.json()["detail"]["code"] == "EXPERIENCE_V1_DISABLED"
    assert created.status_code == 404
    assert db_session.query(Experience).count() == 0


def test_create_and_list_experiences(db_session) -> None:
    workspace, user = _seed(db_session)
    client = _client(db_session, workspace, user)

    created = client.post("/experiences", json=_create_body())
    listed = client.get("/experiences")
    fetched = client.get(f"/experiences/{created.json()['id']}")

    assert created.status_code == 201, created.text
    body = created.json()
    assert body["slug"] == "password-reset"
    assert body["pattern"] == "form_result"
    assert body["draft"]["revision"] == 1
    assert body["draft"]["pages"] == {"pages": []}
    assert body["deployments"] == []
    assert listed.status_code == 200
    listed_row = listed.json()["experiences"][0]
    assert listed_row["slug"] == "password-reset"
    assert listed_row["binding_keys"] == []
    assert listed_row["draft_revision"] == 1
    assert listed_row["latest_release_number"] is None
    assert fetched.status_code == 200
    assert fetched.json()["id"] == body["id"]
    assert fetched.json()["draft"]["content_sha256"] == body["draft"]["content_sha256"]
    created_audit = (
        db_session.query(AuditLog)
        .filter(AuditLog.event_type == "experience.created")
        .one()
    )
    assert created_audit.details["slug"] == "password-reset"


def test_experience_audit_lists_prefix_and_delete_emits(db_session) -> None:
    workspace, user = _seed(db_session)
    client = _client(db_session, workspace, user)
    created = client.post("/experiences", json=_create_body())
    experience_id = created.json()["id"]
    saved = client.put(
        f"/experiences/{experience_id}/draft",
        json={"pages": _pages("form"), "binding_keys": []},
    )
    assert saved.status_code == 200, saved.text
    deleted = client.delete(f"/experiences/{experience_id}")
    listed = client.get("/experiences/audit")

    assert deleted.status_code == 204
    assert db_session.query(Experience).count() == 0
    assert (
        db_session.query(AuditLog)
        .filter(AuditLog.event_type == "experience.draft_saved")
        .count()
        == 1
    )
    assert (
        db_session.query(AuditLog)
        .filter(AuditLog.event_type == "experience.deleted")
        .one()
        .details["experience_id"]
        == experience_id
    )
    assert listed.status_code == 200, listed.text
    types = {item["event_type"] for item in listed.json()["logs"]}
    assert types == {
        "experience.created",
        "experience.draft_saved",
        "experience.deleted",
    }


def test_live_experience_cannot_be_deleted(db_session) -> None:
    workspace, user = _seed(db_session)
    client = _client(db_session, workspace, user)
    created = client.post("/experiences", json=_create_body())
    experience_id = created.json()["id"]
    assert client.put(
        f"/experiences/{experience_id}/draft",
        json={"pages": _pages("form"), "binding_keys": []},
    ).status_code == 200
    released = client.post(
        f"/experiences/{experience_id}/releases",
        json={"notes": "live"},
    )
    assert released.status_code == 201, released.text
    deployed = client.post(
        f"/experiences/{experience_id}/deployments",
        json={"channel": "live", "release_id": released.json()["id"]},
    )
    assert deployed.status_code == 201, deployed.text

    deleted = client.delete(f"/experiences/{experience_id}")

    assert deleted.status_code == 409
    assert deleted.json()["detail"]["code"] == "EXPERIENCE_LIVE_DEPLOYED"
    assert db_session.query(Experience).count() == 1
    assert (
        db_session.query(AuditLog)
        .filter(AuditLog.event_type == "experience.deleted")
        .count()
        == 0
    )

def test_draft_rejects_unknown_component_type(db_session) -> None:
    workspace, user = _seed(db_session)
    client = _client(db_session, workspace, user)
    created = client.post("/experiences", json=_create_body())
    assert created.status_code == 201, created.text

    response = client.put(
        f"/experiences/{created.json()['id']}/draft",
        json={"pages": _pages("fancy_chart"), "binding_keys": []},
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "DRAFT_COMPONENT_TYPE_INVALID"
    draft = client.get(f"/experiences/{created.json()['id']}")
    assert draft.json()["draft"]["revision"] == 1


def test_ready_check_blocks_missing_binding(db_session) -> None:
    workspace, user = _seed(db_session)
    client = _client(db_session, workspace, user)
    created = client.post("/experiences", json=_create_body())
    experience_id = created.json()["id"]
    saved = client.put(
        f"/experiences/{experience_id}/draft",
        json={"pages": _pages("form"), "binding_keys": ["missing.submit"]},
    )
    assert saved.status_code == 200, saved.text

    check = client.get(f"/experiences/{experience_id}/ready-check")
    blocked = client.post(
        f"/experiences/{experience_id}/releases",
        json={"notes": "should not release"},
    )

    assert check.status_code == 200
    assert check.json()["ready"] is False
    assert any(item["code"] == "BINDING_MISSING" for item in check.json()["blockers"])
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "EXPERIENCE_NOT_READY"
    assert db_session.query(ExperienceRelease).count() == 0


def test_release_does_not_deploy(db_session) -> None:
    workspace, user = _seed(db_session)
    client = _client(db_session, workspace, user)
    created = client.post("/experiences", json=_create_body())
    experience_id = created.json()["id"]
    assert client.put(
        f"/experiences/{experience_id}/draft",
        json={"pages": _pages("form", "action_button"), "binding_keys": []},
    ).status_code == 200

    released = client.post(
        f"/experiences/{experience_id}/releases",
        json={"notes": "first certified snapshot"},
    )
    listed = client.get(f"/experiences/{experience_id}/releases")
    detail = client.get(f"/experiences/{experience_id}")

    assert released.status_code == 201, released.text
    assert released.json()["release_number"] == 1
    assert released.json()["notes"] == "first certified snapshot"
    assert released.json()["renderer_version"] == "certified-components-0.1.0"
    assert listed.json()["releases"][0]["id"] == released.json()["id"]
    assert detail.json()["deployments"] == []
    assert db_session.query(ExperienceDeployment).count() == 0
    audit = (
        db_session.query(AuditLog)
        .filter(AuditLog.event_type == "experience.released")
        .one()
    )
    assert audit.details["release_id"] == released.json()["id"]


def test_deploy_pilot_and_rollback(db_session) -> None:
    workspace, user = _seed(db_session)
    client = _client(db_session, workspace, user)
    created = client.post("/experiences", json=_create_body())
    experience_id = created.json()["id"]
    assert client.put(
        f"/experiences/{experience_id}/draft",
        json={"pages": _pages("form"), "binding_keys": []},
    ).status_code == 200
    first = client.post(
        f"/experiences/{experience_id}/releases",
        json={"notes": "r1"},
    )
    assert first.status_code == 201, first.text
    assert client.put(
        f"/experiences/{experience_id}/draft",
        json={"pages": _pages("form", "result"), "binding_keys": []},
    ).status_code == 200
    second = client.post(
        f"/experiences/{experience_id}/releases",
        json={"notes": "r2"},
    )
    assert second.status_code == 201, second.text

    deployed = client.post(
        f"/experiences/{experience_id}/deployments",
        json={"channel": "pilot", "release_id": first.json()["id"]},
    )
    updated = client.post(
        f"/experiences/{experience_id}/deployments",
        json={"channel": "pilot", "release_id": second.json()["id"]},
    )
    rolled = client.post(f"/experiences/{experience_id}/deployments/pilot/rollback")

    assert deployed.status_code == 201, deployed.text
    assert deployed.json()["channel"] == "pilot"
    assert deployed.json()["release_id"] == first.json()["id"]
    assert updated.status_code == 201
    assert updated.json()["release_id"] == second.json()["id"]
    assert updated.json()["previous_release_id"] == first.json()["id"]
    assert rolled.status_code == 200, rolled.text
    assert rolled.json()["release_id"] == first.json()["id"]
    assert db_session.query(ExperienceDeployment).count() == 1
    assert (
        db_session.query(AuditLog)
        .filter(AuditLog.event_type == "experience.deployed")
        .count()
        == 2
    )
    rollback_audit = (
        db_session.query(AuditLog)
        .filter(AuditLog.event_type == "experience.rolled_back")
        .one()
    )
    assert rollback_audit.details["release_id"] == first.json()["id"]


def test_viewer_cannot_release(db_session) -> None:
    workspace, admin = _seed(db_session)
    viewer = User(
        id="user-experience-viewer",
        username="experience-viewer@example.invalid",
        email="experience-viewer@example.invalid",
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
    admin_client = _client(db_session, workspace, admin)
    created = admin_client.post("/experiences", json=_create_body())
    experience_id = created.json()["id"]
    assert admin_client.put(
        f"/experiences/{experience_id}/draft",
        json={"pages": _pages("form"), "binding_keys": []},
    ).status_code == 200

    viewer_client = _client(db_session, workspace, viewer)
    listed = viewer_client.get("/experiences")
    released = viewer_client.post(
        f"/experiences/{experience_id}/releases",
        json={"notes": "viewer must not release"},
    )

    assert listed.status_code == 200
    assert [item["slug"] for item in listed.json()["experiences"]] == ["password-reset"]
    assert released.status_code == 403
    assert released.json()["detail"]["code"] == "WORKSPACE_PERMISSION_DENIED"
    assert db_session.query(ExperienceRelease).count() == 0
