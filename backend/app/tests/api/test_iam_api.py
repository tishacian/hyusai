from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import iam
from app.core.iam.roles import WORKSPACE_OWNER
from app.models.audit import AuditLog
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceIAMConfig, WorkspaceMember
from app.services.iam.decision_plane import candidate_config_sha256
from app.services.iam.shadow_review import (
    MISMATCH_REVIEW_EVENT_TYPE,
    build_source_manifest_row,
    sha256_ref,
)


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
        (item["resource_kind"], item["action"], tuple(item["conditions"])): item[
            "allowed_for_subject"
        ]
        for item in body["permissions"]
    }
    assert permissions[("capture_session", "create", ())] is True
    assert permissions[("capture_session", "update", ("owner_match",))] is True
    assert permissions[("capture_session", "execute", ("owner_match",))] is True


def _owner_with_rollout_config(db_session, *, suffix: str):
    workspace = Workspace(
        id=f"ws-iam-rollout-{suffix}",
        name=f"IAM rollout {suffix}",
        slug=f"iam-rollout-{suffix}",
        settings={},
    )
    owner = User(
        id=f"user-iam-rollout-{suffix}",
        username=f"owner-{suffix}",
        email=f"owner-{suffix}@example.test",
    )
    policy = {
        "policy_version": 2,
        "default_mode": "compat",
        "modes": {"system.read": "enforce", "run.read": "shadow"},
        "enforcement_attestations": {
            "system.read": {"workspace_id": workspace.id, "revision": "a" * 40}
        },
        "enforcement_history": [{"action": "promote", "revision": "a" * 40}],
    }
    config = WorkspaceIAMConfig(
        workspace_id=workspace.id,
        version=1,
        role_flags={},
        capability_overrides={
            "authorization_v2": policy,
            "old_override": {"enabled": True},
        },
        updated_by_user_id=owner.id,
    )
    db_session.add_all(
        [
            workspace,
            owner,
            WorkspaceMember(
                user_id=owner.id,
                workspace_id=workspace.id,
                role="owner",
                role_template=WORKSPACE_OWNER,
            ),
            config,
        ]
    )
    db_session.commit()
    return workspace, owner, config, policy


def test_iam_patch_preserves_rollout_owned_authority_when_editing_other_overrides(
    db_session,
):
    workspace, owner, config, policy = _owner_with_rollout_config(db_session, suffix="preserve")

    response = _client(db_session, workspace, owner).patch(
        "/api/v1/iam/config",
        json={"capability_overrides": {"new_override": {"enabled": False}}},
    )

    assert response.status_code == 200
    db_session.refresh(config)
    assert config.capability_overrides == {
        "new_override": {"enabled": False},
        "authorization_v2": policy,
    }


def test_iam_patch_cannot_forge_or_downgrade_rollout_owned_enforce_state(
    db_session,
):
    workspace, owner, config, policy = _owner_with_rollout_config(db_session, suffix="immutable")
    client = _client(db_session, workspace, owner)

    forge = client.patch(
        "/api/v1/iam/config",
        json={
            "capability_overrides": {
                "authorization_v2": {
                    "policy_version": 2,
                    "modes": {"run.read": "enforce"},
                }
            }
        },
    )
    downgrade = client.patch(
        "/api/v1/iam/config",
        json={
            "capability_overrides": {
                "authorization_v2": {
                    "policy_version": 2,
                    "modes": {"system.read": "shadow"},
                }
            }
        },
    )
    forge_attestation = client.patch(
        "/api/v1/iam/config",
        json={
            "capability_overrides": {
                "authorization_v2": {
                    "policy_version": 2,
                    "enforcement_attestations": {"system.read": {"revision": "b" * 40}},
                }
            }
        },
    )
    forge_history = client.patch(
        "/api/v1/iam/config",
        json={
            "capability_overrides": {
                "authorization_v2": {
                    "policy_version": 2,
                    "enforcement_history": [],
                }
            }
        },
    )
    forge_default_enforce = client.patch(
        "/api/v1/iam/config",
        json={
            "capability_overrides": {
                "authorization_v2": {
                    "policy_version": 2,
                    "default_mode": "enforce",
                }
            }
        },
    )
    invalidate_policy_version = client.patch(
        "/api/v1/iam/config",
        json={
            "capability_overrides": {
                "authorization_v2": {
                    "policy_version": 1,
                    "modes": {"system.read": "enforce"},
                }
            }
        },
    )

    for response in (
        forge,
        downgrade,
        forge_attestation,
        forge_history,
        forge_default_enforce,
        invalidate_policy_version,
    ):
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "IAM_ROLLOUT_MANAGED_FIELD"
    db_session.expire_all()
    stored = db_session.query(WorkspaceIAMConfig).filter_by(workspace_id=workspace.id).one()
    assert stored.capability_overrides["authorization_v2"] == policy


def test_iam_patch_cannot_mutate_any_existing_rollout_document(db_session):
    workspace, owner, config, policy = _owner_with_rollout_config(db_session, suffix="no-delete")

    response = _client(db_session, workspace, owner).patch(
        "/api/v1/iam/config",
        json={
            "capability_overrides": {
                "authorization_v2": {
                    "policy_version": 2,
                    "default_mode": "compat",
                    "modes": {"run.read": "compat"},
                }
            }
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "IAM_ROLLOUT_MANAGED_FIELD"
    db_session.refresh(config)
    stored = config.capability_overrides["authorization_v2"]
    assert stored["modes"] == policy["modes"]
    assert stored["enforcement_attestations"] == policy["enforcement_attestations"]
    assert stored["enforcement_history"] == policy["enforcement_history"]


def test_iam_patch_cannot_create_shadow_rollout_document(db_session):
    workspace = Workspace(
        id="ws-iam-rollout-create",
        name="IAM rollout create",
        slug="iam-rollout-create",
        settings={},
    )
    owner = User(
        id="user-iam-rollout-create",
        username="owner-create",
        email="owner-create@example.test",
    )
    db_session.add_all(
        [
            workspace,
            owner,
            WorkspaceMember(
                user_id=owner.id,
                workspace_id=workspace.id,
                role="owner",
                role_template=WORKSPACE_OWNER,
            ),
        ]
    )
    db_session.commit()

    response = _client(db_session, workspace, owner).patch(
        "/api/v1/iam/config",
        json={
            "capability_overrides": {
                "authorization_v2": {
                    "policy_version": 2,
                    "default_mode": "shadow",
                    "modes": {"system.read": "shadow"},
                }
            }
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "IAM_ROLLOUT_MANAGED_FIELD"


def test_iam_patch_requires_explicit_demotion_before_role_flag_drift(db_session):
    workspace, owner, config, _policy = _owner_with_rollout_config(
        db_session,
        suffix="role-flags",
    )

    response = _client(db_session, workspace, owner).patch(
        "/api/v1/iam/config",
        json={"role_flags": {"can_manage_systems": True}},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "IAM_ENFORCE_REQUIRES_DEMOTION",
        "message": "Demote the exact enforce action group before changing candidate role flags",
        "actions": ["system.read"],
    }
    db_session.refresh(config)
    assert config.role_flags == {}


def test_policy_admin_records_content_addressed_review_for_exact_audit_rows(
    db_session,
    monkeypatch,
):
    workspace, owner, config, _policy = _owner_with_rollout_config(
        db_session,
        suffix="mismatch-review",
    )
    revision = "a" * 40
    monkeypatch.setattr(iam.settings, "agentium_image_revision", revision)
    end = datetime.now(UTC) - timedelta(seconds=5)
    start = end - timedelta(hours=1)
    observation_id = "audit-iam-reviewed-mismatch"
    counters = {
        "legacy_allowed": 1,
        "legacy_denied": 0,
        "candidate_allowed": 0,
        "candidate_denied": 1,
        "matches": 0,
        "mismatches": 1,
    }
    details = {
        "origin": "server",
        "policy_version": 2,
        "configured_mode": "shadow",
        "action": "run.read",
        "evaluation_count": 1,
        "runtime_revision": revision,
        "candidate_config_sha256": candidate_config_sha256(config),
        "candidate_config_version": config.version,
        **counters,
    }
    observed_at = start + timedelta(minutes=1)
    db_session.add(
        AuditLog(
            id=observation_id,
            workspace_id=workspace.id,
            timestamp=observed_at.replace(tzinfo=None),
            event_type="iam.shadow.evaluation",
            actor="opaque-subject",
            details=details,
        )
    )
    source_manifest = {
        "schema_version": 1,
        "workspace_id": workspace.id,
        "actions": ["run.read"],
        "window_started_at": start.isoformat(),
        "window_ended_at": end.isoformat(),
        "event_type": "iam.shadow.evaluation",
        "runtime_revision": revision,
        "candidate_config_sha256": candidate_config_sha256(config),
        "candidate_config_version": config.version,
        "rows": [
            build_source_manifest_row(
                row_id=observation_id,
                timestamp=observed_at,
                action="run.read",
                evaluation_count=1,
                runtime_revision=revision,
                candidate_config_sha256=candidate_config_sha256(config),
                candidate_config_version=config.version,
                counters=counters,
            )
        ],
    }
    db_session.commit()

    response = _client(db_session, workspace, owner).post(
        "/api/v1/iam/authorization-v2/mismatch-reviews",
        json={
            "source_ref": sha256_ref(source_manifest),
            "source_manifest": source_manifest,
            "entries": [
                {
                    "action": "run.read",
                    "observation_ids": [observation_id],
                    "reason_code": "reviewer_role_separation",
                    "reason": "Reviewer execution rights are intentionally removed in policy v2.",
                }
            ],
        },
    )

    assert response.status_code == 201
    review = response.json()
    assert review["artifact_ref"] == sha256_ref(review["document"])
    assert review["document"]["reviewed_by"] == {
        "user_id": owner.id,
        "identity": owner.email,
    }
    row = db_session.query(AuditLog).filter_by(id=review["audit_id"]).one()
    assert row.event_type == MISMATCH_REVIEW_EVENT_TYPE
    assert row.actor == owner.email
