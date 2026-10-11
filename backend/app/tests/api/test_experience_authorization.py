"""Experience / binding IAM: view, edit, release, deploy, manage."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import experiences as experience_endpoint
from app.api.v1.endpoints import system_bindings as binding_endpoint
from app.core.iam.roles import (
    WORKSPACE_CONTRIBUTOR,
    WORKSPACE_REVIEWER,
    WORKSPACE_VIEWER,
)
from app.models.experience import ExperienceRelease
from app.models.system import System
from app.models.system_binding import SystemBinding
from app.models.system_version import SystemVersion
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services.run_engine.execution_contract import canonical_flow_sha256
from app.services.systems import flow_publication


def _flow() -> dict[str, Any]:
    schema = {
        "type": "object",
        "required": ["query"],
        "properties": {"query": {"type": "string"}},
        "additionalProperties": False,
    }
    return {
        "schema_version": 3,
        "io_mode": "strict",
        "nodes": [
            {
                "id": "manual.input",
                "kind": "source",
                "config": {"ingress_kind": "manual", "input_schema": schema},
            },
            {"id": "result", "kind": "sink"},
        ],
        "edges": [{"from": "manual.input", "to": "result", "kind": "data"}],
    }


def _seed(db_session, *, suffix: str):
    workspace = Workspace(
        id=f"ws-exp-iam-{suffix}",
        slug=f"exp-iam-{suffix}",
        name=f"Experience IAM {suffix}",
        settings={"features": {"experience_v1": True, "flow_publication_v1": True}},
    )
    admin = User(
        id=f"user-exp-iam-admin-{suffix}",
        username=f"exp-iam-admin-{suffix}@example.invalid",
        email=f"exp-iam-admin-{suffix}@example.invalid",
        role="admin",
    )
    flow = _flow()
    system = System(
        id=f"system-exp-iam-{suffix}",
        workspace_id=workspace.id,
        name="Bound system",
        objective="test",
        status="active",
        flow_definition=flow,
    )
    db_session.add_all(
        [
            workspace,
            admin,
            WorkspaceMember(
                workspace_id=workspace.id,
                user_id=admin.id,
                role="admin",
                role_template="workspace_admin",
            ),
            system,
        ]
    )
    db_session.flush()
    contract = flow_publication.compile_execution_contract(db_session, flow, workspace)
    version = SystemVersion(
        id=f"version-exp-iam-{suffix}",
        workspace_id=workspace.id,
        system_id=system.id,
        version_number=1,
        flow_definition=flow,
        flow_sha256=canonical_flow_sha256(flow),
        release_kind="publish",
        draft_revision=1,
        execution_contract=contract,
        message="published",
        created_by=admin.email,
    )
    db_session.add(version)
    db_session.flush()
    system.published_flow_version_id = version.id
    system.published_by = admin.email
    system.published_at = datetime.utcnow()
    db_session.commit()
    return workspace, admin, version


def _member(db_session, workspace: Workspace, *, suffix: str, role_template: str) -> User:
    user = User(
        id=f"user-exp-iam-{suffix}",
        username=f"exp-iam-{suffix}@example.invalid",
        email=f"exp-iam-{suffix}@example.invalid",
        role="member",
    )
    db_session.add_all(
        [
            user,
            WorkspaceMember(
                workspace_id=workspace.id,
                user_id=user.id,
                role="member",
                role_template=role_template,
            ),
        ]
    )
    db_session.commit()
    return user


def _client(db_session, workspace: Workspace, user: User) -> TestClient:
    app = FastAPI()
    app.include_router(experience_endpoint.router, prefix="/experiences")
    app.include_router(binding_endpoint.router, prefix="/system-bindings")
    app.dependency_overrides[experience_endpoint.get_current_workspace] = lambda: workspace
    app.dependency_overrides[experience_endpoint.get_current_user] = lambda: user
    app.dependency_overrides[experience_endpoint.get_db] = lambda: db_session
    app.dependency_overrides[binding_endpoint.get_current_workspace] = lambda: workspace
    app.dependency_overrides[binding_endpoint.get_current_user] = lambda: user
    app.dependency_overrides[binding_endpoint.get_db] = lambda: db_session
    return TestClient(app)


def _experience_body(**overrides) -> dict[str, Any]:
    body = {
        "name": "Password reset",
        "slug": "password-reset",
        "pattern": "form_result",
        "languages": ["en"],
        "theme": {},
        "access_policy": {"roles": []},
    }
    body.update(overrides)
    return body


def _pages() -> dict[str, Any]:
    return {
        "pages": [
            {
                "id": "home",
                "title": "Home",
                "components": [{"type": "header", "id": "header"}],
            }
        ]
    }


def _binding_body(version: SystemVersion) -> dict[str, Any]:
    return {
        "binding_key": "expenses.submit",
        "system_id": version.system_id,
        "published_flow_version_id": version.id,
        "ingress_id": "manual.input",
        "confirmation_policy": "direct-safe",
        "on_unavailable": "unavailable",
    }


def _ready_experience(admin_client: TestClient) -> str:
    created = admin_client.post("/experiences", json=_experience_body())
    assert created.status_code == 201, created.text
    experience_id = created.json()["id"]
    saved = admin_client.put(
        f"/experiences/{experience_id}/draft",
        json={"pages": _pages(), "binding_keys": [], "expected_revision": 1},
    )
    assert saved.status_code == 200, saved.text
    return experience_id


def _release_body(client: TestClient, experience_id: str, notes: str) -> dict[str, Any]:
    detail = client.get(f"/experiences/{experience_id}").json()
    draft = detail["draft"]
    ready = client.get(f"/experiences/{experience_id}/ready-check").json()
    return {
        "notes": notes,
        "expected_draft_revision": draft["revision"],
        "expected_content_sha256": draft["content_sha256"],
        "expected_experience_updated_at": detail["updated_at"],
        "expected_bindings_sha256": ready["bindings_sha256"],
    }


def test_viewer_can_list_cannot_edit_release_deploy_or_manage(db_session) -> None:
    workspace, admin, version = _seed(db_session, suffix="viewer")
    viewer = _member(
        db_session, workspace, suffix="viewer", role_template=WORKSPACE_VIEWER
    )
    admin_client = _client(db_session, workspace, admin)
    experience_id = _ready_experience(admin_client)
    client = _client(db_session, workspace, viewer)

    listed = client.get("/experiences")
    bindings = client.get("/system-bindings")
    audit = client.get("/experiences/audit")
    edited = client.post("/experiences", json=_experience_body(slug="viewer-app"))
    released = client.post(
        f"/experiences/{experience_id}/releases",
        json=_release_body(admin_client, experience_id, "viewer must not release"),
    )
    deployed = client.post(
        f"/experiences/{experience_id}/deployments",
        json={
            "channel": "pilot",
            "release_id": "missing",
            "expected_current_release_id": None,
            "expected_deployment_updated_at": None,
        },
    )
    managed = client.post("/system-bindings", json=_binding_body(version))

    assert listed.status_code == 403
    assert bindings.status_code == 200
    assert audit.status_code == 403
    assert edited.status_code == 403
    assert released.status_code == 403
    assert deployed.status_code == 403
    assert managed.status_code == 403
    assert db_session.query(ExperienceRelease).count() == 0
    assert db_session.query(SystemBinding).count() == 0


def test_contributor_can_edit_and_manage_cannot_release_or_deploy(db_session) -> None:
    workspace, admin, version = _seed(db_session, suffix="contributor")
    contributor = _member(
        db_session,
        workspace,
        suffix="contributor",
        role_template=WORKSPACE_CONTRIBUTOR,
    )
    admin_client = _client(db_session, workspace, admin)
    experience_id = _ready_experience(admin_client)
    client = _client(db_session, workspace, contributor)

    created = client.post("/experiences", json=_experience_body(slug="contributor-app"))
    saved = client.put(
        f"/experiences/{created.json()['id']}/draft",
        json={"pages": _pages(), "binding_keys": [], "expected_revision": 1},
    )
    binding = client.post("/system-bindings", json=_binding_body(version))
    released = client.post(
        f"/experiences/{experience_id}/releases",
        json=_release_body(client, experience_id, "contributor must not release"),
    )
    deployed = client.post(
        f"/experiences/{experience_id}/deployments",
        json={
            "channel": "pilot",
            "release_id": "missing",
            "expected_current_release_id": None,
            "expected_deployment_updated_at": None,
        },
    )

    assert created.status_code == 201, created.text
    assert saved.status_code == 200, saved.text
    assert binding.status_code == 201, binding.text
    assert released.status_code == 403
    assert deployed.status_code == 403
    assert db_session.query(ExperienceRelease).count() == 0


def test_reviewer_can_release_and_deploy_cannot_edit_or_manage(db_session) -> None:
    workspace, admin, version = _seed(db_session, suffix="reviewer")
    reviewer = _member(
        db_session, workspace, suffix="reviewer", role_template=WORKSPACE_REVIEWER
    )
    admin_client = _client(db_session, workspace, admin)
    experience_id = _ready_experience(admin_client)
    client = _client(db_session, workspace, reviewer)

    edited = client.post("/experiences", json=_experience_body(slug="reviewer-app"))
    managed = client.post("/system-bindings", json=_binding_body(version))
    released = client.post(
        f"/experiences/{experience_id}/releases",
        json=_release_body(client, experience_id, "reviewer release"),
    )
    deployed = client.post(
        f"/experiences/{experience_id}/deployments",
        json={
            "channel": "pilot",
            "release_id": released.json()["id"],
            "expected_current_release_id": None,
            "expected_deployment_updated_at": None,
        },
    )

    assert edited.status_code == 403
    assert managed.status_code == 403
    assert released.status_code == 201, released.text
    assert deployed.status_code == 201, deployed.text
    assert db_session.query(SystemBinding).count() == 0
    assert db_session.query(ExperienceRelease).count() == 1


def test_reviewer_governance_reads_survive_studio_opt_out_but_authoring_is_hidden(
    db_session,
) -> None:
    workspace, admin, version = _seed(db_session, suffix="runtime-governance")
    reviewer = _member(
        db_session,
        workspace,
        suffix="runtime-governance",
        role_template=WORKSPACE_REVIEWER,
    )
    admin_client = _client(db_session, workspace, admin)
    experience_id = _ready_experience(admin_client)
    release_payload = _release_body(admin_client, experience_id, "governed release")
    released = admin_client.post(
        f"/experiences/{experience_id}/releases",
        json=release_payload,
    )
    assert released.status_code == 201, released.text
    release_id = released.json()["id"]
    deployed = admin_client.post(
        f"/experiences/{experience_id}/deployments",
        json={
            "channel": "pilot",
            "release_id": release_id,
            "expected_current_release_id": None,
            "expected_deployment_updated_at": None,
        },
    )
    assert deployed.status_code == 201, deployed.text
    binding = admin_client.post("/system-bindings", json=_binding_body(version))
    assert binding.status_code == 201, binding.text

    workspace.settings = {
        "features": {
            "experience_v1": True,
            "experience_studio_v1": False,
            "flow_publication_v1": True,
        }
    }
    db_session.add(workspace)
    db_session.commit()
    client = _client(db_session, workspace, reviewer)

    listed = client.get("/experiences")
    audit = client.get("/experiences/audit")
    releases = client.get(f"/experiences/{experience_id}/releases")
    drift = client.get("/system-bindings/drift")

    assert listed.status_code == 200, listed.text
    governed = listed.json()["experiences"][0]
    assert governed["id"] == experience_id
    assert governed["deployments"][0]["release_id"] == release_id
    assert audit.status_code == 200, audit.text
    assert audit.json()["total"] > 0
    assert releases.status_code == 200, releases.text
    assert releases.json()["releases"][0]["id"] == release_id
    assert drift.status_code == 200, drift.text

    hidden = [
        client.get(f"/experiences/{experience_id}"),
        client.get(f"/experiences/{experience_id}/draft/revisions"),
        client.get(f"/experiences/{experience_id}/ready-check"),
        client.post(
            "/experiences",
            json=_experience_body(slug="studio-disabled"),
        ),
        client.post(
            f"/experiences/{experience_id}/releases",
            json=release_payload,
        ),
        client.post(
            f"/experiences/{experience_id}/deployments",
            json={
                "channel": "pilot",
                "release_id": release_id,
                "expected_current_release_id": release_id,
                "expected_deployment_updated_at": deployed.json()["updated_at"],
            },
        ),
        client.post(
            f"/experiences/{experience_id}/draft/revisions/1/restore",
            json={"expected_revision": 2},
        ),
        client.patch(
            "/system-bindings/expenses.submit",
            json={"confirmation_policy": "confirm"},
        ),
    ]
    assert {response.status_code for response in hidden} == {404}
    assert {
        response.json()["detail"]["code"] for response in hidden
    } == {"EXPERIENCE_STUDIO_V1_DISABLED"}
