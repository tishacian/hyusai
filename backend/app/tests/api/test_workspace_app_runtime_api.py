"""Workspace bootstrap exposes the Lot-9 runtime authority safely."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import auth
from app.core.config import settings
from app.core.iam.roles import WORKSPACE_OWNER
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.models.workspace_app import WorkspaceAppInstallation
from app.services.workspace_app_manifests import (
    BUILTIN_WORKSPACE_APP_MANIFESTS,
    validate_manifest_configuration,
)
from app.services.workspace_app_runtime import (
    WORKSPACE_APP_PLATFORM_FEATURE,
    WORKSPACE_APP_ROLLOUT_STATE_KEY,
    inspect_authoritative_workspace_app_runtime,
    workspace_app_installations_sha256,
)

REVISION = "e" * 40


@pytest.fixture(autouse=True)
def _runtime_revision(monkeypatch):
    monkeypatch.setattr(settings, "agentium_image_revision", REVISION)


def _seed(db_session):
    workspace = Workspace(
        id=str(uuid4()),
        name="Workspace App runtime API",
        slug=f"workspace-app-runtime-api-{uuid4().hex[:8]}",
        settings={
            "family": "andritz",
            "features": {WORKSPACE_APP_PLATFORM_FEATURE: False},
        },
    )
    owner = User(
        id=str(uuid4()),
        username=f"workspace-app-owner-{uuid4().hex[:8]}",
        email=f"workspace-app-owner-{uuid4().hex[:8]}@example.test",
        role="user",
    )
    membership = WorkspaceMember(
        workspace_id=workspace.id,
        user_id=owner.id,
        role="owner",
        role_template=WORKSPACE_OWNER,
    )
    db_session.add_all([workspace, owner, membership])
    db_session.commit()
    return workspace, owner


def _client(db_session, owner: User) -> TestClient:
    app = FastAPI()
    app.include_router(auth.router, prefix="/auth")
    app.dependency_overrides[auth.get_current_user] = lambda: owner
    app.dependency_overrides[auth.get_db] = lambda: db_session
    return TestClient(app)


def _install_chat(db_session, workspace: Workspace) -> WorkspaceAppInstallation:
    manifest = BUILTIN_WORKSPACE_APP_MANIFESTS[("andritz.chat", "1.0.0")]
    row = WorkspaceAppInstallation(
        id=str(uuid4()),
        workspace_id=workspace.id,
        app_id=manifest.app_id,
        version=manifest.version,
        manifest_digest=manifest.digest,
        state="installed",
        configuration=validate_manifest_configuration(manifest, None),
        revision=1,
        installed_at=datetime.utcnow(),
        updated_by="runtime-api-test",
    )
    db_session.add(row)
    db_session.commit()
    return row


def _attest(db_session, workspace: Workspace) -> None:
    runtime = inspect_authoritative_workspace_app_runtime(workspace, db=db_session)
    evidence = "3" * 64
    artifact = "4" * 64
    preflight_evidence = "5" * 64
    preflight_artifact = "6" * 64
    probation = "7" * 64
    workspace.settings = {
        **workspace.settings,
        "features": {WORKSPACE_APP_PLATFORM_FEATURE: True},
        WORKSPACE_APP_ROLLOUT_STATE_KEY: {
            "schema_version": 1,
            "activations": [
                {
                    "workspace_id": workspace.id,
                    "evidence_sha256": evidence,
                    "evidence_ref": f"sha256:{evidence}",
                    "artifact_sha256": artifact,
                    "artifact_ref": f"sha256:{artifact}",
                    "artifact_tests": 7,
                    "preflight_evidence_sha256": preflight_evidence,
                    "preflight_evidence_ref": f"sha256:{preflight_evidence}",
                    "preflight_artifact_sha256": preflight_artifact,
                    "preflight_artifact_ref": f"sha256:{preflight_artifact}",
                    "preflight_artifact_tests": 3,
                    "postactivation_artifact_tests": 4,
                    "probation_ref": f"sha256:{probation}",
                    "revision": REVISION,
                    "installations_sha256": workspace_app_installations_sha256(runtime),
                    "installation_count": len(runtime.installations),
                    "activated_at": datetime.now(UTC).isoformat(),
                }
            ],
            "deactivations": [],
        },
    }
    db_session.commit()


def test_bootstrap_switches_from_legacy_to_exact_installed_runtime(db_session) -> None:
    workspace, owner = _seed(db_session)
    client = _client(db_session, owner)

    legacy = client.get(f"/auth/workspaces/{workspace.slug}")
    assert legacy.status_code == 200
    assert legacy.json()["workspace_app_runtime"] == {
        "schema_version": 1,
        "mode": "legacy",
        "enabled": False,
        "rollout_phase": "disabled",
        "rollout_ref": None,
        "valid": True,
        "installations": [],
        "experience": {
            "shell": "legacy",
            "routes": [],
            "primary_surface_ids": [],
            "default_routes": {},
            "branding_namespaces": [],
            "api_prefixes": [],
            "action_packs": [],
            "mission_room": None,
        },
    }

    manifest = BUILTIN_WORKSPACE_APP_MANIFESTS[("andritz.chat", "1.0.0")]
    _install_chat(db_session, workspace)
    _attest(db_session, workspace)

    authoritative = client.get(f"/auth/workspaces/{workspace.slug}")
    assert authoritative.status_code == 200
    runtime = authoritative.json()["workspace_app_runtime"]
    assert runtime["mode"] == "authoritative"
    assert runtime["valid"] is True
    assert runtime["installations"] == [
        {
            "app_id": "andritz.chat",
            "version": "1.0.0",
            "manifest_digest": manifest.digest,
            "category": "business_app",
            "routes": ["/chat"],
            "primary_surface_id": "chat",
            "default_route": "/chat",
            "branding_namespace": "andritz",
            "api_prefixes": ["/api/v1/chat", "/api/v1/sessions"],
            "action_packs": ["andritz_industrial_v1"],
            "entitlement_keys": ["chat"],
        }
    ]


def test_bootstrap_redacts_an_invalid_authoritative_installation(db_session) -> None:
    workspace, owner = _seed(db_session)
    row = _install_chat(db_session, workspace)
    row.manifest_digest = "0" * 64
    workspace.settings = {
        **workspace.settings,
        "features": {WORKSPACE_APP_PLATFORM_FEATURE: True},
    }
    db_session.commit()

    response = _client(db_session, owner).get(f"/auth/workspaces/{workspace.slug}")

    assert response.status_code == 200
    assert response.json()["workspace_app_runtime"] == {
        "schema_version": 1,
        "mode": "authoritative",
        "enabled": True,
        "rollout_phase": "invalid",
        "rollout_ref": None,
        "valid": False,
        "error_code": "manifest_untrusted",
        "installations": [],
        "experience": None,
    }


def test_generic_workspace_patch_cannot_toggle_or_remove_platform_authority(
    db_session,
) -> None:
    workspace, owner = _seed(db_session)
    client = _client(db_session, owner)

    enable = client.patch(
        f"/auth/workspaces/{workspace.slug}",
        json={
            "settings": {
                "family": "andritz",
                "features": {WORKSPACE_APP_PLATFORM_FEATURE: True},
            }
        },
    )
    assert enable.status_code == 409
    assert enable.json()["detail"]["code"] == "LOT9_WORKSPACE_APP_ROLLOUT_STATE_MANAGED"

    workspace.settings = {
        **workspace.settings,
        "features": {WORKSPACE_APP_PLATFORM_FEATURE: True},
    }
    db_session.commit()
    remove = client.patch(
        f"/auth/workspaces/{workspace.slug}",
        json={"settings": {"branding": {"name": "Safe"}}},
    )
    assert remove.status_code == 200
    assert remove.json()["settings"]["features"][WORKSPACE_APP_PLATFORM_FEATURE] is True
