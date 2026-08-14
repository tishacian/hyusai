"""GET /work/{slug} — live preferred, entitled pilot, flag-gated."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import work as endpoint
from app.models.run import Run
from app.models.system import System
from app.models.system_version import SystemVersion
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services.experience import bindings as binding_service
from app.services.run_engine.execution_contract import canonical_flow_sha256
from app.services.systems import flow_publication


def _seed(db_session, *, enabled: bool = True, role_template: str = "workspace_admin"):
    workspace = Workspace(
        id="ws-work-api",
        slug="work-api",
        name="Work API",
        settings={
            "features": {
                "experience_v1": enabled,
                "flow_publication_v1": True,
            }
        },
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


def _client(db_session, workspace: Workspace, user: User, monkeypatch=None) -> TestClient:
    app = FastAPI()
    app.include_router(endpoint.router, prefix="/work")
    app.dependency_overrides[endpoint.get_current_workspace] = lambda: workspace
    app.dependency_overrides[endpoint.get_current_user] = lambda: user
    app.dependency_overrides[endpoint.get_db] = lambda: db_session
    if monkeypatch is not None:
        monkeypatch.setattr(endpoint, "schedule_run", lambda _run_id: None)
    return TestClient(app)


def _experiences_client(db_session, workspace: Workspace, user: User) -> TestClient:
    from app.api.v1.endpoints import experiences as experiences_endpoint

    app = FastAPI()
    app.include_router(experiences_endpoint.router, prefix="/experiences")
    app.dependency_overrides[experiences_endpoint.get_current_workspace] = lambda: workspace
    app.dependency_overrides[experiences_endpoint.get_current_user] = lambda: user
    app.dependency_overrides[experiences_endpoint.get_db] = lambda: db_session
    return TestClient(app)


def _pages(binding_key: str | None = None) -> dict:
    component = {"type": "header", "id": "header", "props": {"title": "Reset"}}
    if binding_key:
        component = {
            "type": "form",
            "id": "reset-form",
            "props": {"bindingKey": binding_key},
        }
    return {
        "pages": [
            {
                "id": "home",
                "title": "Home",
                "components": [component],
            }
        ]
    }


def _publish(
    client: TestClient,
    *,
    audience: dict | None = None,
    channel: str = "live",
    binding_key: str | None = None,
):
    create_body: dict[str, Any] = {
        "name": "Password reset",
        "slug": "password-reset",
        "pattern": "form_result",
    }
    if channel == "live" and audience is not None:
        create_body["access_policy"] = audience
    created = client.post(
        "/experiences",
        json=create_body,
    )
    assert created.status_code == 201, created.text
    experience_id = created.json()["id"]
    saved = client.put(
        f"/experiences/{experience_id}/draft",
        json={
            "pages": _pages(binding_key),
            "binding_keys": [binding_key] if binding_key else [],
            "expected_revision": 1,
        },
    )
    assert saved.status_code == 200, saved.text
    released = client.post(
        f"/experiences/{experience_id}/releases",
        json={
            "notes": "r1",
            "expected_draft_revision": saved.json()["revision"],
            "expected_content_sha256": saved.json()["content_sha256"],
        },
    )
    assert released.status_code == 201, released.text
    body: dict = {"channel": channel, "release_id": released.json()["id"]}
    if audience is not None:
        body["audience"] = audience
    deployed = client.post(f"/experiences/{experience_id}/deployments", json=body)
    assert deployed.status_code == 201, deployed.text
    return experience_id, released.json()["id"]


def _flow(*, ticket: bool = False) -> dict[str, Any]:
    properties: dict[str, Any] = {"query": {"type": "string"}}
    required = ["query"]
    if ticket:
        properties["ticket"] = {"type": "string"}
        required.append("ticket")
    return {
        "schema_version": 3,
        "io_mode": "strict",
        "nodes": [
            {
                "id": "manual.input",
                "kind": "source",
                "config": {
                    "ingress_kind": "manual",
                    "input_schema": {
                        "type": "object",
                        "required": required,
                        "properties": properties,
                        "additionalProperties": False,
                    },
                },
            },
            {"id": "result", "kind": "sink"},
        ],
        "edges": [{"from": "manual.input", "to": "result", "kind": "data"}],
    }


def _seed_binding(db_session, workspace: Workspace, user: User):
    flow = _flow()
    system = System(
        id="work-bound-system",
        workspace_id=workspace.id,
        name="Work bound system",
        objective="test",
        status="active",
        flow_definition=flow,
    )
    db_session.add(system)
    db_session.flush()
    version = SystemVersion(
        id="work-bound-v1",
        workspace_id=workspace.id,
        system_id=system.id,
        version_number=1,
        flow_definition=flow,
        flow_sha256=canonical_flow_sha256(flow),
        release_kind="publish",
        draft_revision=1,
        execution_contract=flow_publication.compile_execution_contract(
            db_session, flow, workspace
        ),
        message="v1",
        created_by=user.email,
    )
    db_session.add(version)
    db_session.flush()
    system.published_flow_version_id = version.id
    system.published_by = user.email
    system.published_at = datetime.utcnow()
    binding = binding_service.create_binding(
        db_session,
        workspace=workspace,
        actor=user.email,
        binding_key="work.reset",
        system_id=system.id,
        published_flow_version_id=version.id,
        ingress_id="manual.input",
        confirmation_policy="direct-safe",
        on_unavailable="unavailable",
    )
    db_session.commit()
    return system, version, binding


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


def test_work_prefers_entitled_pilot_over_live_and_returns_frozen_pages(db_session) -> None:
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
    assert body["channel"] == "pilot"
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


def test_work_catalog_and_channel_are_filtered_server_side(db_session) -> None:
    workspace, admin = _seed(db_session)
    studio = _experiences_client(db_session, workspace, admin)
    experience_id, release_id = _publish(
        studio,
        channel="live",
        audience={"roles": ["workspace_viewer", "workspace_admin"]},
    )
    assert studio.post(
        f"/experiences/{experience_id}/deployments",
        json={
            "channel": "pilot",
            "release_id": release_id,
            "audience": {"roles": ["workspace_admin"]},
        },
    ).status_code == 201
    viewer = User(
        id="user-work-catalog-viewer",
        username="catalog-viewer@example.invalid",
        email="catalog-viewer@example.invalid",
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

    viewer_catalog = _client(db_session, workspace, viewer).get("/work")
    admin_catalog = _client(db_session, workspace, admin).get("/work")

    assert viewer_catalog.status_code == 200
    assert viewer_catalog.json()["experiences"][0]["channel"] == "live"
    assert "pages" not in viewer_catalog.json()["experiences"][0]["release"]
    assert admin_catalog.json()["experiences"][0]["channel"] == "pilot"


def test_work_audience_is_strict_and_malformed_persisted_data_closes(db_session) -> None:
    from app.models.experience import ExperienceDeployment

    workspace, admin = _seed(db_session)
    studio = _experiences_client(db_session, workspace, admin)
    experience_id, _release_id = _publish(studio, channel="live")
    invalid = studio.post(
        f"/experiences/{experience_id}/deployments",
        json={
            "channel": "live",
            "release_id": db_session.query(ExperienceDeployment).one().release_id,
            "audience": {"roles": "workspace_admin"},
        },
    )
    assert invalid.status_code == 422
    deployment = db_session.query(ExperienceDeployment).one()
    deployment.audience = {"unknown": ["workspace_admin"]}
    db_session.commit()

    hidden = _client(db_session, workspace, admin)
    assert hidden.get("/work/password-reset").status_code == 404
    assert hidden.get("/work").json()["experiences"] == []


def test_deployed_run_uses_release_snapshot_after_binding_retarget_and_delete(
    db_session, monkeypatch
) -> None:
    workspace, admin = _seed(db_session)
    system, version_v1, _binding = _seed_binding(db_session, workspace, admin)
    studio = _experiences_client(db_session, workspace, admin)
    _publish(studio, binding_key="work.reset", channel="live")

    flow_v2 = _flow(ticket=True)
    version_v2 = SystemVersion(
        id="work-bound-v2",
        workspace_id=workspace.id,
        system_id=system.id,
        version_number=2,
        flow_definition=flow_v2,
        flow_sha256=canonical_flow_sha256(flow_v2),
        release_kind="publish",
        draft_revision=2,
        execution_contract=flow_publication.compile_execution_contract(
            db_session, flow_v2, workspace
        ),
        message="v2",
        created_by=admin.email,
    )
    db_session.add(version_v2)
    db_session.flush()
    system.flow_definition = flow_v2
    system.published_flow_version_id = version_v2.id
    binding_service.update_binding(
        db_session,
        workspace=workspace,
        binding_key="work.reset",
        published_flow_version_id=version_v2.id,
    )
    binding_service.delete_binding(
        db_session, workspace_id=workspace.id, binding_key="work.reset"
    )
    db_session.commit()

    work = _client(db_session, workspace, admin, monkeypatch)
    resolved = work.get("/work/password-reset/bindings/work.reset/resolve")
    invoked = work.post(
        "/work/password-reset/bindings/work.reset/runs",
        json={
            "payload": {"query": "reset"},
            "page_id": "home",
            "component_id": "reset-form",
        },
    )

    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["status"] == "ok"
    assert "published_flow_version_id" not in resolved.json()["binding"]
    assert "system_id" not in resolved.json()["binding"]
    assert invoked.status_code == 201, invoked.text
    assert "published_flow_version_id" not in invoked.json()
    assert "system_id" not in invoked.json()
    assert invoked.json()["origin"] == "experience:password-reset"
    run = db_session.get(Run, invoked.json()["id"])
    assert run.published_flow_version_id == version_v1.id
    adapter = run.input_ref["_ingress"]["adapter"]
    assert adapter["experience_release_id"] == invoked.json()["experience_release_id"]
    assert adapter["experience_deployment_id"] == invoked.json()["experience_deployment_id"]
    assert adapter["binding_key"] == "work.reset"
    assert adapter["page_id"] == "home"
    assert adapter["component_id"] == "reset-form"


def test_work_rejects_component_context_that_does_not_own_binding(
    db_session, monkeypatch
) -> None:
    workspace, admin = _seed(db_session)
    _seed_binding(db_session, workspace, admin)
    _publish(
        _experiences_client(db_session, workspace, admin),
        binding_key="work.reset",
        channel="live",
    )

    response = _client(db_session, workspace, admin, monkeypatch).post(
        "/work/password-reset/bindings/work.reset/runs",
        json={
            "payload": {"query": "reset"},
            "page_id": "home",
            "component_id": "other",
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "EXPERIENCE_BINDING_CONTEXT_INVALID"


def test_work_uses_frozen_release_identity_and_minimal_public_projection(db_session) -> None:
    workspace, admin = _seed(db_session)
    studio = _experiences_client(db_session, workspace, admin)
    created = studio.post(
        "/experiences",
        json={"name": "Frozen name", "slug": "frozen-app", "pattern": "dashboard"},
    )
    experience_id = created.json()["id"]
    saved = studio.put(
        f"/experiences/{experience_id}/draft",
        json={"pages": _pages(), "binding_keys": [], "expected_revision": 1},
    )
    released = studio.post(
        f"/experiences/{experience_id}/releases",
        json={
            "notes": "identity",
            "expected_draft_revision": saved.json()["revision"],
            "expected_content_sha256": saved.json()["content_sha256"],
        },
    )
    assert studio.patch(
        f"/experiences/{experience_id}",
        json={"name": "Future name", "pattern": "approval"},
    ).status_code == 200
    assert studio.post(
        f"/experiences/{experience_id}/deployments",
        json={"channel": "live", "release_id": released.json()["id"]},
    ).status_code == 201

    work = _client(db_session, workspace, admin)
    detail = work.get("/work/frozen-app")
    catalog = work.get("/work")

    assert detail.status_code == 200, detail.text
    assert detail.json()["experience"] == {
        "id": experience_id,
        "name": "Frozen name",
        "slug": "frozen-app",
        "pattern": "dashboard",
    }
    assert set(detail.json()["release"]) == {
        "id",
        "pages",
        "bindings_snapshot",
        "languages",
        "theme",
        "renderer_version",
    }
    item = catalog.json()["experiences"][0]
    assert item["experience"]["name"] == "Frozen name"
    assert "workspace_id" not in item["experience"]
    assert "access_policy" not in item["experience"]


def test_release_access_snapshot_cannot_be_widened_by_deployment(db_session) -> None:
    workspace, admin = _seed(db_session)
    studio = _experiences_client(db_session, workspace, admin)
    created = studio.post(
        "/experiences",
        json={
            "name": "Restricted",
            "slug": "restricted-app",
            "pattern": "dashboard",
            "access_policy": {"roles": ["workspace_admin"]},
        },
    )
    experience_id = created.json()["id"]
    saved = studio.put(
        f"/experiences/{experience_id}/draft",
        json={"pages": _pages(), "binding_keys": [], "expected_revision": 1},
    )
    released = studio.post(
        f"/experiences/{experience_id}/releases",
        json={
            "notes": "restricted",
            "expected_draft_revision": saved.json()["revision"],
            "expected_content_sha256": saved.json()["content_sha256"],
        },
    )
    release_id = released.json()["id"]
    widened_live = studio.post(
        f"/experiences/{experience_id}/deployments",
        json={
            "channel": "live",
            "release_id": release_id,
            "audience": {"roles": ["workspace_viewer"]},
        },
    )
    assert widened_live.status_code == 409
    assert widened_live.json()["detail"]["code"] == "EXPERIENCE_LIVE_AUDIENCE_IMMUTABLE"
    assert studio.post(
        f"/experiences/{experience_id}/deployments",
        json={
            "channel": "pilot",
            "release_id": release_id,
            "audience": {"roles": ["workspace_admin", "workspace_viewer"]},
        },
    ).status_code == 201

    viewer = User(
        id="user-release-bound-viewer",
        username="release-bound-viewer@example.invalid",
        email="release-bound-viewer@example.invalid",
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

    viewer_work = _client(db_session, workspace, viewer)
    assert viewer_work.get("/work/restricted-app").status_code == 404
    assert viewer_work.get("/work").json()["experiences"] == []
    assert _client(db_session, workspace, admin).get("/work/restricted-app").status_code == 200


def test_group_audience_is_enforced_server_side(db_session) -> None:
    workspace, admin = _seed(db_session)
    studio = _experiences_client(db_session, workspace, admin)
    _publish(studio, channel="pilot", audience={"groups": ["pilot-a"]})
    viewer = User(
        id="user-work-group",
        username="work-group@example.invalid",
        email="work-group@example.invalid",
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
                custom_labels=["pilot-a"],
            ),
        ]
    )
    db_session.commit()

    assert _client(db_session, workspace, viewer).get("/work/password-reset").status_code == 200


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("confirmation_policy", "anything"),
        ("on_unavailable", "fallback-anywhere"),
        ("flow_sha256", "z" * 64),
        ("input_schema_sha256", "short"),
    ],
)
def test_work_binding_snapshot_corruption_fails_closed(
    db_session, field: str, value: str
) -> None:
    from app.models.experience import ExperienceRelease

    workspace, admin = _seed(db_session)
    _seed_binding(db_session, workspace, admin)
    _publish(
        _experiences_client(db_session, workspace, admin),
        binding_key="work.reset",
        channel="live",
    )
    release = db_session.query(ExperienceRelease).one()
    snapshot = [dict(item) for item in release.bindings_snapshot]
    snapshot[0][field] = value
    release.bindings_snapshot = snapshot
    db_session.commit()

    response = _client(db_session, workspace, admin).get(
        "/work/password-reset/bindings/work.reset/resolve"
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "RELEASE_BINDING_SNAPSHOT_INVALID"
