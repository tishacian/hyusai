"""Workspace App governance API boundary tests."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import workspace_app_governance
from app.core.iam.roles import WORKSPACE_CONTRIBUTOR, WORKSPACE_OWNER
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.models.workspace_app import WorkspaceAppInstallation, WorkspaceAppOperation
from app.services.workspace_app_manifests import BUILTIN_WORKSPACE_APP_MANIFESTS


def _seed(db_session):
    workspace = Workspace(
        id="workspace-app-governance-a",
        name="Workspace App Governance A",
        slug="workspace-app-governance-a",
        settings={"family": "andritz"},
    )
    other_workspace = Workspace(
        id="workspace-app-governance-b",
        name="Workspace App Governance B",
        slug="workspace-app-governance-b",
        settings={"family": "andritz"},
    )
    owner = User(
        id="workspace-app-governance-owner",
        username="workspace-app-governance-owner",
        email="owner@example.test",
    )
    member = User(
        id="workspace-app-governance-member",
        username="workspace-app-governance-member",
        email="member@example.test",
    )
    db_session.add_all(
        [
            workspace,
            other_workspace,
            owner,
            member,
            WorkspaceMember(
                workspace_id=workspace.id,
                user_id=owner.id,
                role="owner",
                role_template=WORKSPACE_OWNER,
            ),
            WorkspaceMember(
                workspace_id=workspace.id,
                user_id=member.id,
                role="member",
                role_template=WORKSPACE_CONTRIBUTOR,
            ),
        ]
    )
    db_session.commit()
    return workspace, other_workspace, owner, member


def _client(db_session, workspace: Workspace, user: User) -> TestClient:
    app = FastAPI()
    app.include_router(
        workspace_app_governance.router,
        prefix="/api/v1/governance/workspace-apps",
    )
    app.dependency_overrides[workspace_app_governance.get_current_user] = lambda: user
    app.dependency_overrides[workspace_app_governance.get_current_workspace] = lambda: workspace
    app.dependency_overrides[workspace_app_governance.get_db] = lambda: db_session
    return TestClient(app)


def _install_request(app_id: str, version: str) -> dict:
    manifest = BUILTIN_WORKSPACE_APP_MANIFESTS[(app_id, version)]
    return {
        "operation": "install",
        "app_id": app_id,
        "target_version": version,
        "expected_manifest_digest": manifest.digest,
    }


def test_manifest_registry_and_installations_are_admin_only_and_workspace_scoped(
    db_session,
):
    workspace, other_workspace, owner, member = _seed(db_session)
    owner_client = _client(db_session, workspace, owner)

    manifests = owner_client.get(
        "/api/v1/governance/workspace-apps/manifests",
        params={"app_id": "andritz.chat"},
    )
    denied = _client(db_session, workspace, member).get(
        "/api/v1/governance/workspace-apps/manifests"
    )

    assert manifests.status_code == 200
    assert [item["version"] for item in manifests.json()["manifests"]] == ["1.0.0"]
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "WORKSPACE_APP_ADMIN_REQUIRED"

    # A row in another tenant is never visible through the current workspace.
    other_manifest = BUILTIN_WORKSPACE_APP_MANIFESTS[("andritz.chat", "1.0.0")]
    db_session.add(
        WorkspaceAppInstallation(
            id="other-workspace-installation",
            workspace_id=other_workspace.id,
            app_id=other_manifest.app_id,
            version=other_manifest.version,
            manifest_digest=other_manifest.digest,
            state="installed",
            configuration={"api_contract": "andritz.chat.v1"},
            revision=1,
            updated_by=owner.id,
        )
    )
    db_session.commit()
    listed = owner_client.get("/api/v1/governance/workspace-apps/installations")
    assert listed.status_code == 200
    assert listed.json()["installations"] == []


def test_manifest_registry_is_structurally_filtered_without_cross_workspace_terms(
    db_session,
) -> None:
    workspace, _, owner, _ = _seed(db_session)
    client = _client(db_session, workspace, owner)

    andritz = client.get("/api/v1/governance/workspace-apps/manifests")
    assert andritz.status_code == 200
    assert {row["app_id"] for row in andritz.json()["manifests"]} == {
        "andritz.chat",
        "andritz.client360-pdr",
        "andritz.knowledge-capture",
    }
    knowledge = next(
        row
        for row in andritz.json()["manifests"]
        if row["app_id"] == "andritz.knowledge-capture"
    )
    assert knowledge["manifest"]["routes"] == [
        "/knowledge/capture",
        "/knowledge/interventions",
    ]
    assert knowledge["manifest"]["entitlement_keys"] == [
        "knowledge-capture",
        "fse-reports",
    ]

    # Deliberately misleading slug/name prove that compatibility is selected
    # only from the canonical family and structural Mission Room profile.
    workspace.slug = "octocity-decoy"
    workspace.name = "Octocity decoy"
    workspace.settings = {
        "family": "sentinel_ci",
        "mission_room": {"profile": "sentinel_government_v1"},
    }
    db_session.commit()
    sentinel = client.get("/api/v1/governance/workspace-apps/manifests")
    assert sentinel.status_code == 200
    assert [row["app_id"] for row in sentinel.json()["manifests"]] == [
        "sentinel.mission-room"
    ]
    sentinel_text = sentinel.text.lower()
    assert "octocity" not in sentinel_text
    assert "octave" not in sentinel_text

    workspace.slug = "sentinel-decoy"
    workspace.name = "Sentinel decoy"
    workspace.settings = {
        "family": "generic",
        "mission_room": {"profile": "octocity_institutional_v1"},
    }
    db_session.commit()
    octocity = client.get("/api/v1/governance/workspace-apps/manifests")
    assert octocity.status_code == 200
    assert [row["app_id"] for row in octocity.json()["manifests"]] == [
        "octocity.mission-room"
    ]
    octocity_text = octocity.text.lower()
    for forbidden in ("sentinel", "aya", "vigie"):
        assert forbidden not in octocity_text


def test_plan_then_apply_requires_exact_digest_plan_and_idempotency_key(db_session):
    workspace, _, owner, _ = _seed(db_session)
    client = _client(db_session, workspace, owner)
    request = _install_request("andritz.chat", "1.0.0")
    request["config"] = {"api_contract": "andritz.chat.v1"}

    planned = client.post(
        "/api/v1/governance/workspace-apps/plan",
        json=request,
    )
    assert planned.status_code == 200
    plan = planned.json()
    assert plan["workspace_id"] == workspace.id
    assert plan["to"]["manifest_digest"] == request["expected_manifest_digest"]
    assert plan["lifecycle_phase"] == "normal"
    assert [step["step_id"] for step in plan["steps"]] == [
        "workspace_app_platform.schema.069",
        "workspace_app_platform.lifecycle_steps.073",
    ]
    assert len(plan["steps_sha256"]) == 64
    assert plan["compensation"]["failure"] == "database_transaction_rollback"

    missing_key = client.post(
        "/api/v1/governance/workspace-apps/apply",
        json={**request, "expected_plan_sha256": plan["plan_sha256"]},
    )
    assert missing_key.status_code == 422

    forged_actor = client.post(
        "/api/v1/governance/workspace-apps/apply",
        headers={"Idempotency-Key": "forged-actor"},
        json={
            **request,
            "expected_plan_sha256": plan["plan_sha256"],
            "actor": "attacker-controlled",
        },
    )
    assert forged_actor.status_code == 422

    applied = client.post(
        "/api/v1/governance/workspace-apps/apply",
        headers={"Idempotency-Key": "governance-install-chat"},
        json={**request, "expected_plan_sha256": plan["plan_sha256"]},
    )
    replay = client.post(
        "/api/v1/governance/workspace-apps/apply",
        headers={"Idempotency-Key": "governance-install-chat"},
        json={**request, "expected_plan_sha256": plan["plan_sha256"]},
    )

    assert applied.status_code == replay.status_code == 200
    assert applied.json()["idempotent_replay"] is False
    assert replay.json()["idempotent_replay"] is True
    assert replay.json()["operation_id"] == applied.json()["operation_id"]
    assert applied.json()["lifecycle_phase"] == "normal"
    assert len(applied.json()["steps_sha256"]) == 64
    assert [row["outcome"] for row in applied.json()["step_receipts"]] == [
        "verified",
        "verified",
    ]
    assert all(
        "id" not in row and "installation_id" not in row and "operation_id" not in row
        for row in applied.json()["step_receipts"]
    )
    assert replay.json()["step_receipts"] == applied.json()["step_receipts"]
    assert applied.json()["installation"] == {
        "state": "installed",
        "version": "1.0.0",
        "manifest_digest": request["expected_manifest_digest"],
        "configuration": {"api_contract": "andritz.chat.v1"},
        "revision": 1,
    }
    receipt = db_session.query(WorkspaceAppOperation).one()
    assert receipt.actor == owner.id


def test_unknown_manifest_and_stale_plan_have_stable_safe_errors(db_session):
    workspace, _, owner, _ = _seed(db_session)
    client = _client(db_session, workspace, owner)
    valid = _install_request("andritz.chat", "1.0.0")

    unknown = client.post(
        "/api/v1/governance/workspace-apps/plan",
        json={**valid, "target_version": "9.9.9"},
    )
    wrong_digest = client.post(
        "/api/v1/governance/workspace-apps/plan",
        json={**valid, "expected_manifest_digest": "0" * 64},
    )
    assert unknown.status_code == 404
    assert unknown.json()["detail"]["code"] == "manifest_not_found"
    assert wrong_digest.status_code == 422
    assert wrong_digest.json()["detail"]["code"] == "manifest_contract_invalid"

    planned = client.post(
        "/api/v1/governance/workspace-apps/plan",
        json=valid,
    ).json()
    stale = client.post(
        "/api/v1/governance/workspace-apps/apply",
        headers={"Idempotency-Key": "stale-governance-plan"},
        json={**valid, "expected_plan_sha256": "f" * 64},
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "stale_plan"
    assert db_session.query(WorkspaceAppInstallation).count() == 0
    assert db_session.query(WorkspaceAppOperation).count() == 0
    assert planned["plan_sha256"] != "f" * 64


def test_apply_rechecks_admin_after_tenant_lock(db_session):
    workspace, _, _, member = _seed(db_session)
    client = _client(db_session, workspace, member)
    request = _install_request("andritz.chat", "1.0.0")

    response = client.post(
        "/api/v1/governance/workspace-apps/apply",
        headers={"Idempotency-Key": "member-cannot-apply"},
        json={**request, "expected_plan_sha256": "a" * 64},
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "WORKSPACE_APP_ADMIN_REQUIRED"
    assert db_session.query(WorkspaceAppInstallation).count() == 0
