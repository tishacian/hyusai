from __future__ import annotations

import copy
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException

from app.core.iam.dependencies import enforce_permission
from app.models.audit import AuditLog
from app.models.run import Run
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceIAMConfig, WorkspaceMember
from app.services.iam.decision_plane import (
    AuthorizationMode,
    build_authorization_v2_backfill,
    enforce_action,
    merge_authorization_v2_backfill,
    resolve_action,
    resolve_candidate_permission,
    resolve_manifest_permission,
    resolve_mode,
)
from app.services.iam.manifest import get_manifest
from app.services.run_access import readable_run_page, readable_runs


def _subject(db_session, *, role_template: str = "workspace_contributor"):
    workspace = Workspace(id="ws-authz-v2", slug="authz-v2", name="Authz v2")
    user = User(id="user-authz-v2", username="authz@test", email="authz@test")
    member = WorkspaceMember(
        user_id=user.id,
        workspace_id=workspace.id,
        role="member",
        role_template=role_template,
    )
    db_session.add_all([workspace, user, member])
    db_session.commit()
    return workspace, user, member


def _config(db_session, workspace, *, default="compat", modes=None):
    row = WorkspaceIAMConfig(
        workspace_id=workspace.id,
        role_flags={},
        capability_overrides={
            "authorization_v2": {
                "policy_version": 2,
                "default_mode": default,
                "modes": modes or {},
            }
        },
    )
    db_session.add(row)
    db_session.commit()
    return row


def test_compat_preserves_legacy_decision_while_exposing_candidate(db_session):
    workspace, user, _member = _subject(db_session, role_template="workspace_viewer")
    resolution = resolve_action(
        db_session,
        user=user,
        workspace=workspace,
        resource_kind="mail_draft",
        action="mail.send",
        legacy_allowed=True,
        resource_attrs={"draft_id": "draft-1"},
    )

    assert resolution.mode == "compat"
    assert resolution.effective_allowed is True
    assert resolution.legacy_allowed is True
    assert resolution.candidate_allowed is False
    assert resolution.mismatch is True
    assert db_session.query(AuditLog).count() == 0


def test_shadow_is_non_blocking_and_persists_redacted_diff(db_session):
    workspace, user, _member = _subject(db_session, role_template="workspace_contributor")
    _config(
        db_session,
        workspace,
        modes={"mail_draft.mail.send": "shadow"},
    )

    resolution = resolve_action(
        db_session,
        user=user,
        workspace=workspace,
        resource_kind="mail_draft",
        action="mail.send",
        legacy_allowed=True,
        resource_attrs={
            "draft_id": "draft-1",
            "to_email": "secret@example.test",
            "password": "never-log-me",
        },
    )

    assert resolution.mode == "shadow"
    assert resolution.effective_allowed is True
    # Simulate request teardown/rollback: shadow evidence uses its own durable
    # transaction and must not disappear with a read-only request session.
    db_session.rollback()
    event = db_session.query(AuditLog).filter_by(event_type="iam.shadow.diff").one()
    assert event.details["resource"] == {"kind": "mail_draft", "draft_id": "draft-1"}
    assert "secret@example.test" not in str(event.details)
    assert "never-log-me" not in str(event.details)
    observation = db_session.query(AuditLog).filter_by(event_type="iam.shadow.evaluation").one()
    assert observation.details["evaluation_count"] == 1
    assert observation.details["legacy_allowed"] == 1
    assert observation.details["candidate_denied"] == 1
    assert observation.details["mismatches"] == 1
    assert "secret@example.test" not in str(observation.details)


def test_shadow_match_still_persists_evaluation_evidence(db_session):
    workspace, user, _member = _subject(
        db_session,
        role_template="workspace_viewer",
    )
    _config(db_session, workspace, modes={"system.read": "shadow"})

    resolution = resolve_action(
        db_session,
        user=user,
        workspace=workspace,
        resource_kind="system",
        action="read",
        legacy_allowed=True,
        resource_attrs={"system_id": "system-shadow-match"},
    )

    assert resolution.mismatch is False
    assert db_session.query(AuditLog).filter_by(event_type="iam.shadow.diff").count() == 0
    observation = db_session.query(AuditLog).filter_by(event_type="iam.shadow.evaluation").one()
    assert observation.details["evaluation_count"] == 1
    assert observation.details["matches"] == 1
    assert observation.details["mismatches"] == 0
    assert observation.details["legacy_allowed"] == 1
    assert observation.details["candidate_allowed"] == 1


def test_collection_shadow_diff_is_durable_aggregated_and_redacted(db_session):
    workspace, user, _member = _subject(
        db_session,
        role_template="workspace_viewer",
    )
    _config(db_session, workspace, modes={"run.read": "shadow"})
    runs = [
        Run(
            id=f"run-shadow-summary-{index}",
            workspace_id=workspace.id,
            initiated_by_user_id=f"owner-{index}",
            status="completed",
            input_ref={"password": f"secret-{index}"},
        )
        for index in range(3)
    ]
    db_session.add_all(runs)
    db_session.commit()

    assert (
        readable_runs(
            db_session,
            runs=runs,
            user=user,
            workspace=workspace,
        )
        == runs
    )
    db_session.rollback()

    events = (
        db_session.query(AuditLog)
        .filter_by(
            workspace_id=workspace.id,
            event_type="iam.shadow.diff",
        )
        .all()
    )
    assert len(events) == 1
    details = events[0].details
    assert details["summary"] is True
    assert details["mismatch_count"] == 3
    assert details["resource"]["sample_ids"] == [run.id for run in runs]
    assert "password" not in str(details)
    assert "secret-" not in str(details)
    observation = (
        db_session.query(AuditLog)
        .filter_by(
            workspace_id=workspace.id,
            event_type="iam.shadow.evaluation",
        )
        .one()
    )
    assert observation.details["summary"] is True
    assert observation.details["evaluation_count"] == 3
    assert observation.details["legacy_allowed"] == 3
    assert observation.details["candidate_denied"] == 3
    assert observation.details["mismatches"] == 3


def test_authorized_run_page_is_filled_after_candidate_filtering(
    db_session,
    attest_authorization_v2,
):
    workspace, user, _member = _subject(
        db_session,
        role_template="workspace_contributor",
    )
    config = _config(db_session, workspace, modes={"run.read": "enforce"})
    attest_authorization_v2(config, ["run.read"])
    now = datetime.now(UTC).replace(tzinfo=None)
    denied = [
        Run(
            id=f"denied-recent-{index}",
            workspace_id=workspace.id,
            initiated_by_user_id="another-user",
            status="completed",
            started_at=now - timedelta(seconds=index),
        )
        for index in range(60)
    ]
    owned = Run(
        id="owned-older-run",
        workspace_id=workspace.id,
        initiated_by_user_id=user.id,
        status="completed",
        started_at=now - timedelta(hours=1),
    )
    db_session.add_all([*denied, owned])
    db_session.commit()

    page = readable_run_page(
        db_session,
        query=db_session.query(Run).filter(Run.workspace_id == workspace.id).order_by(
            Run.started_at.desc()
        ),
        limit=1,
        user=user,
        workspace=workspace,
    )

    assert [run.id for run in page] == [owned.id]


def test_enforce_uses_candidate_and_mode_precedence_is_granular(
    db_session,
    attest_authorization_v2,
):
    workspace, user, _member = _subject(db_session, role_template="workspace_viewer")
    config = _config(
        db_session,
        workspace,
        default="shadow",
        modes={
            "*.*": "shadow",
            "mail_draft.*": "compat",
            "mail_draft.mail.send": "enforce",
        },
    )
    attest_authorization_v2(config, ["mail_draft.mail.send"])
    db_session.commit()

    assert (
        resolve_mode(config, resource_kind="mail_draft", action="mail.send")
        is AuthorizationMode.ENFORCE
    )
    assert (
        resolve_mode(config, resource_kind="mail_draft", action="read") is AuthorizationMode.COMPAT
    )
    assert resolve_mode(config, resource_kind="run", action="read") is AuthorizationMode.SHADOW

    resolution = resolve_action(
        db_session,
        user=user,
        workspace=workspace,
        resource_kind="mail_draft",
        action="mail.send",
        legacy_allowed=True,
    )
    assert resolution.effective_allowed is False
    assert resolution.candidate_allowed is False


def test_enforce_is_exact_attested_and_bound_to_running_revision(
    db_session,
    monkeypatch,
    attest_authorization_v2,
):
    from app.core.config import settings

    workspace, user, _member = _subject(db_session)
    config = _config(
        db_session,
        workspace,
        default="enforce",
        modes={"*.*": "enforce", "system.read": "enforce"},
    )

    # Config/Blueprint writes and inherited enforce are never authoritative.
    assert (
        resolve_mode(config, resource_kind="system", action="read")
        is AuthorizationMode.INVALID_ENFORCE
    )
    assert resolve_mode(config, resource_kind="run", action="read") is AuthorizationMode.SHADOW

    attest_authorization_v2(config, ["system.read"])
    db_session.commit()
    assert resolve_mode(config, resource_kind="system", action="read") is AuthorizationMode.ENFORCE
    assert resolve_mode(config, resource_kind="run", action="read") is AuthorizationMode.SHADOW

    monkeypatch.setattr(settings, "agentium_image_revision", "d" * 40)
    assert (
        resolve_mode(config, resource_kind="system", action="read")
        is AuthorizationMode.INVALID_ENFORCE
    )
    drifted = resolve_action(
        db_session,
        user=user,
        workspace=workspace,
        resource_kind="system",
        action="read",
        legacy_allowed=True,
    )
    assert drifted.effective_allowed is False
    assert drifted.mode == "invalid_enforce"
    with pytest.raises(HTTPException) as exc_info:
        enforce_action(
            db_session,
            user=user,
            workspace=workspace,
            resource_kind="system",
            action="read",
            legacy_allowed=True,
        )
    assert exc_info.value.status_code == 503
    assert exc_info.value.detail["code"] == "AUTHORIZATION_ENFORCEMENT_INVALID"
    monkeypatch.setattr(settings, "agentium_image_revision", "a" * 40)

    payload = copy.deepcopy(config.capability_overrides)
    payload["authorization_v2"]["enforcement_attestations"]["system.read"]["trusted_runner"][
        "issuer"
    ] = "https://attacker.example.test"
    config.capability_overrides = payload
    assert (
        resolve_mode(config, resource_kind="system", action="read")
        is AuthorizationMode.INVALID_ENFORCE
    )

    attest_authorization_v2(config, ["system.read"])
    payload = copy.deepcopy(config.capability_overrides)
    payload["authorization_v2"]["enforcement_attestations"]["system.read"]["trusted_runner"][
        "project_id"
    ] = "untrusted-project"
    config.capability_overrides = payload
    assert (
        resolve_mode(config, resource_kind="system", action="read")
        is AuthorizationMode.INVALID_ENFORCE
    )


def test_manifest_required_permission_is_compared_under_action_execute_rollout(db_session):
    workspace, user, _member = _subject(db_session, role_template="workspace_contributor")
    _config(db_session, workspace, modes={"action.execute": "shadow"})

    resolution = resolve_manifest_permission(
        db_session,
        user=user,
        workspace=workspace,
        required_permission="deposit_file.promote",
        legacy_allowed=True,
        capability_manifest="secure_deposit",
        action_id="deposit.promote",
        resource_attrs={
            "system_id": "system-action-context",
            "capability_id": "capability-action-context",
            "password": "must-not-leak",
        },
    )

    assert resolution.mode == "shadow"
    assert resolution.effective_allowed is True
    assert resolution.candidate_allowed is False
    event = db_session.query(AuditLog).filter_by(event_type="iam.shadow.diff").one()
    assert event.details["resource"]["action_id"] == "deposit.promote"
    assert event.details["resource"]["system_id"] == "system-action-context"
    assert event.details["resource"]["capability_id"] == "capability-action-context"
    assert "must-not-leak" not in str(event.details)


def test_manifest_permission_preserves_a_real_resource_owner(db_session):
    workspace, user, _member = _subject(
        db_session,
        role_template="workspace_viewer",
    )
    _config(db_session, workspace, modes={"action.execute": "shadow"})

    resolution = resolve_manifest_permission(
        db_session,
        user=user,
        workspace=workspace,
        required_permission="deposit_file.read",
        legacy_allowed=True,
        capability_manifest="secure_deposit",
        action_id="deposit.read",
        resource_attrs={"owner_user_id": "another-user"},
    )

    assert resolution.mode == "shadow"
    assert resolution.legacy_allowed is True
    assert resolution.candidate_allowed is False
    assert resolution.mismatch is True
    event = db_session.query(AuditLog).filter_by(event_type="iam.shadow.diff").one()
    assert event.details["resource"]["owner_user_id"] == "another-user"

    db_session.query(AuditLog).delete()
    db_session.commit()
    missing_owner = resolve_manifest_permission(
        db_session,
        user=user,
        workspace=workspace,
        required_permission="deposit_file.read",
        legacy_allowed=True,
        capability_manifest="secure_deposit",
        action_id="deposit.read",
    )
    assert missing_owner.candidate_allowed is False


def test_backfill_document_is_explicit_and_idempotent():
    desired = build_authorization_v2_backfill(mode="shadow")
    assert desired["default_mode"] == "compat"
    assert desired["modes"]["mail_draft.mail.send"] == "shadow"
    assert desired["modes"]["capture_session.create"] == "shadow"
    assert desired["modes"]["capture_session.execute"] == "shadow"
    assert desired["modes"]["capability.read"] == "shadow"
    assert desired["modes"]["system.read"] == "shadow"
    assert desired["modes"]["run.read"] == "shadow"
    assert desired["modes"]["run.approve"] == "shadow"
    assert desired["modes"]["run.admin"] == "shadow"
    assert desired["modes"]["skill_invocation.read"] == "shadow"
    assert desired["modes"]["decision.read"] == "shadow"
    assert desired["modes"]["decision.admin"] == "shadow"
    assert desired["modes"]["audit_log.read"] == "shadow"
    assert desired["modes"]["control_policy.read"] == "shadow"
    assert desired["modes"]["control_policy.admin"] == "shadow"
    assert desired["modes"]["adaptive_policy.read"] == "shadow"
    assert desired["modes"]["adaptive_policy.admin"] == "shadow"
    assert desired["modes"]["action.read"] == "shadow"
    assert "workspace.admin" not in desired["modes"]

    first, changed = merge_authorization_v2_backfill({"existing": {"kept": True}})
    second, changed_again = merge_authorization_v2_backfill(first)
    assert changed is True
    assert changed_again is False
    assert second["existing"] == {"kept": True}


def test_backfill_preserves_unowned_authorization_entries():
    current = {
        "authorization_v2": {
            "policy_version": 1,
            "default_mode": "shadow",
            "modes": {"custom_resource.publish": "enforce"},
            "owner_note": "workspace policy",
        }
    }

    merged, changed = merge_authorization_v2_backfill(current, mode="shadow")

    assert changed is True
    assert merged["authorization_v2"]["policy_version"] == 2
    assert merged["authorization_v2"]["default_mode"] == "shadow"
    assert merged["authorization_v2"]["owner_note"] == "workspace policy"
    assert merged["authorization_v2"]["modes"]["custom_resource.publish"] == "enforce"
    assert merged["authorization_v2"]["modes"]["system.engine.run"] == "shadow"


def test_backfill_preserves_healthy_attested_enforce_and_rejects_drift(
    db_session,
    attest_authorization_v2,
):
    workspace, _user, _member = _subject(db_session)
    desired = build_authorization_v2_backfill(mode="shadow")
    config = _config(db_session, workspace, modes=desired["modes"])
    attest_authorization_v2(config, ["run.read", "system.read"])
    db_session.commit()

    before = copy.deepcopy(config.capability_overrides)
    merged, changed = merge_authorization_v2_backfill(before, mode="shadow")
    assert changed is False
    assert merged == before

    drifted = copy.deepcopy(before)
    drifted["authorization_v2"]["modes"]["run.read"] = "shadow"
    with pytest.raises(ValueError, match="incoherent"):
        merge_authorization_v2_backfill(drifted, mode="shadow")

    unattested = copy.deepcopy(before)
    unattested["authorization_v2"]["enforcement_attestations"].pop("run.read")
    with pytest.raises(ValueError, match="incoherent"):
        merge_authorization_v2_backfill(unattested, mode="shadow")


def test_knowledge_capture_reviewer_candidate_is_shadowed_before_enforce(
    db_session,
    attest_authorization_v2,
):
    workspace, reviewer, _member = _subject(
        db_session,
        role_template="workspace_reviewer",
    )
    workspace.settings = {"features": {"iam_enforced": True}}
    config = _config(
        db_session,
        workspace,
        modes={"capture_session.create": "shadow"},
    )

    legacy = enforce_permission(
        db_session,
        user=reviewer,
        workspace=workspace,
        resource_kind="capture_session",
        action="create",
        resource_attrs={"capability": "expert_knowledge_capture"},
        audit_prefix="kc",
    )

    assert legacy.allowed is True
    diff = db_session.query(AuditLog).filter_by(event_type="iam.shadow.diff").one()
    assert diff.details["resource"]["kind"] == "capture_session"
    assert diff.details["legacy_allowed"] is True
    assert diff.details["candidate_allowed"] is False

    config.capability_overrides = {
        "authorization_v2": {
            "policy_version": 2,
            "default_mode": "compat",
            "modes": {"capture_session.create": "enforce"},
        }
    }
    attest_authorization_v2(config, ["capture_session.create"])
    db_session.commit()

    with pytest.raises(HTTPException) as denied:
        enforce_permission(
            db_session,
            user=reviewer,
            workspace=workspace,
            resource_kind="capture_session",
            action="create",
            resource_attrs={"capability": "expert_knowledge_capture"},
            audit_prefix="kc",
        )
    assert denied.value.status_code == 403
    assert denied.value.detail["mode"] == "enforce"

    config.role_flags = {"reviewers_inherit_contributor": True}
    # Candidate inputs changed: the exact enforce group must be re-attested
    # before it can become authoritative again.
    attest_authorization_v2(config, ["capture_session.create"])
    db_session.commit()
    inherited = enforce_permission(
        db_session,
        user=reviewer,
        workspace=workspace,
        resource_kind="capture_session",
        action="create",
        resource_attrs={"capability": "expert_knowledge_capture"},
        audit_prefix="kc",
    )
    assert inherited.allowed is True


def test_knowledge_capture_v2_preserves_boundaries_but_splits_contributor_operations(
    db_session,
):
    legacy = get_manifest("expert_knowledge_capture")
    candidate = get_manifest("expert_knowledge_capture_v2")
    assert {(rule.resource_kind, rule.action) for rule in candidate.permissions} == {
        (rule.resource_kind, rule.action) for rule in legacy.permissions
    }

    workspace, reviewer, _member = _subject(
        db_session,
        role_template="workspace_reviewer",
    )
    cases = (
        ("capture_session", "create", {}, False),
        ("capture_session", "update", {"owner_user_id": reviewer.id}, False),
        ("knowledge_proposal", "review_decide", {"owner_user_id": "author"}, True),
        ("knowledge_proposal", "trigger_ingestion", {"owner_user_id": "author"}, True),
    )
    for resource_kind, action, attrs, candidate_allowed in cases:
        compat = resolve_candidate_permission(
            db_session,
            user=reviewer,
            workspace=workspace,
            resource_kind=resource_kind,
            action=action,
            legacy_allowed=True,
            candidate_manifest="expert_knowledge_capture_v2",
            resource_attrs={"capability": "expert_knowledge_capture", **attrs},
        )
        assert compat.mode == "compat"
        assert compat.effective_allowed is True
        assert compat.candidate_allowed is candidate_allowed

    _config(
        db_session,
        workspace,
        modes={f"{resource}.{action}": "shadow" for resource, action, _attrs, _allowed in cases},
    )
    for resource_kind, action, attrs, candidate_allowed in cases:
        shadow = resolve_candidate_permission(
            db_session,
            user=reviewer,
            workspace=workspace,
            resource_kind=resource_kind,
            action=action,
            legacy_allowed=True,
            candidate_manifest="expert_knowledge_capture_v2",
            resource_attrs={"capability": "expert_knowledge_capture", **attrs},
        )
        assert shadow.mode == "shadow"
        assert shadow.effective_allowed is True
        assert shadow.candidate_allowed is candidate_allowed
