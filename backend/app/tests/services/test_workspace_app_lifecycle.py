"""Authoritative Workspace App lifecycle service contracts."""

import hashlib
import json
from copy import deepcopy
from types import MappingProxyType
from uuid import uuid4

import pytest
from sqlalchemy import event

from app.models.audit import AuditLog
from app.models.workspace import Workspace, WorkspaceMemberAppEntitlement
from app.models.workspace_app import (
    WorkspaceAppInstallation,
    WorkspaceAppLifecycleStepReceipt,
    WorkspaceAppOperation,
)
from app.services import workspace_app_lifecycle as lifecycle_service
from app.services.workspace_app_lifecycle import (
    WorkspaceAppLifecycleConflict,
    WorkspaceAppLifecycleNotFound,
    WorkspaceAppLifecycleValidationError,
    apply_workspace_app_lifecycle,
    plan_workspace_app_lifecycle,
    validate_workspace_app_compatibility,
    workspace_app_is_compatible,
)
from app.services.workspace_app_manifests import (
    BUILTIN_WORKSPACE_APP_MANIFESTS,
    CompiledWorkspaceAppManifest,
)
from app.services.workspace_app_runtime import WORKSPACE_APP_PLATFORM_FEATURE


def _workspace(
    db,
    suffix: str,
    *,
    family: str = "generic",
    profile: str | None = None,
) -> Workspace:
    settings: dict = {"family": family}
    if profile is not None:
        settings["mission_room"] = {"enabled": True, "profile": profile}
    workspace = Workspace(
        id=str(uuid4()),
        name=f"Workspace {suffix}",
        slug=f"workspace-app-{suffix}-{uuid4().hex[:8]}",
        mode="executive",
        settings=settings,
    )
    db.add(workspace)
    db.commit()
    return workspace


def _manifest(app_id: str, version: str):
    return BUILTIN_WORKSPACE_APP_MANIFESTS[(app_id, version)]


def _legacy_prerequisite(
    workspace: Workspace,
    manifest,
    plan,
    *,
    requested_workspace_ids: list[str] | None = None,
) -> dict:
    report = {
        "schema_version": 1,
        "selection": "explicit_workspace_ids",
        "requested_workspace_ids": requested_workspace_ids or [workspace.id],
        "workspace_count": 1,
        "workspaces": [{"workspace_id": workspace.id}],
        "changes": [
            {
                "workspace_id": workspace.id,
                "app_id": manifest.app_id,
                "version": manifest.version,
                "manifest_digest": manifest.digest,
                "operation": "install",
                "reason": "legacy_contract_detected",
                "plan_sha256": plan.plan_sha256,
            }
        ],
        "blockers": [],
        "ready": True,
    }
    report["analysis_sha256"] = hashlib.sha256(
        json.dumps(
            report,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    return {f"{manifest.app_id}.legacy_installation.v1": report}


def _plan_and_apply(
    db,
    workspace: Workspace,
    *,
    operation: str,
    app_id: str,
    version: str | None,
    digest: str,
    key: str,
    configuration=None,
    lifecycle_phase: str = "normal",
    prerequisite_evidence=None,
):
    plan = plan_workspace_app_lifecycle(
        db,
        workspace_id=workspace.id,
        operation=operation,
        app_id=app_id,
        target_version=version,
        expected_manifest_digest=digest,
        configuration=configuration,
        lifecycle_phase=lifecycle_phase,
    )
    result = apply_workspace_app_lifecycle(
        db,
        workspace_id=workspace.id,
        operation=operation,
        app_id=app_id,
        target_version=version,
        expected_manifest_digest=digest,
        expected_plan_sha256=plan.plan_sha256,
        configuration=configuration,
        actor="lot9-test",
        idempotency_key=key,
        lifecycle_phase=lifecycle_phase,
        prerequisite_evidence=prerequisite_evidence,
    )
    return plan, result


def test_install_is_content_addressed_audited_and_does_not_mutate_entitlements(db_session):
    workspace = _workspace(db_session, "install", family="andritz")
    manifest = _manifest("andritz.chat", "1.0.0")

    plan, result = _plan_and_apply(
        db_session,
        workspace,
        operation="install",
        app_id=manifest.app_id,
        version=manifest.version,
        digest=manifest.digest,
        key="install-andritz-chat",
    )

    assert plan.from_state == "absent"
    assert result.idempotent_replay is False
    assert result.installation.state == "installed"
    assert result.installation.version == manifest.version
    assert result.installation.manifest_digest == manifest.digest
    assert result.installation.configuration == {"api_contract": "andritz.chat.v1"}
    assert result.installation.revision == 1
    assert plan.lifecycle_phase == "normal"
    assert [step.manifest_role for step in plan.steps] == ["target", "target"]
    assert [step.step_id for step in plan.steps] == [
        "workspace_app_platform.schema.069",
        "workspace_app_platform.lifecycle_steps.073",
    ]
    assert len(plan.steps_sha256) == 64
    assert plan.compensation["failure"] == "database_transaction_rollback"
    assert plan.compensation["post_commit"] == "uninstall"
    assert db_session.query(WorkspaceMemberAppEntitlement).count() == 0
    receipt = db_session.query(WorkspaceAppOperation).one()
    assert receipt.plan_sha256 == plan.plan_sha256
    assert receipt.lifecycle_phase == "normal"
    assert receipt.steps_sha256 == plan.steps_sha256
    assert receipt.compensation == plan.compensation
    step_receipts = db_session.query(WorkspaceAppLifecycleStepReceipt).order_by(
        WorkspaceAppLifecycleStepReceipt.position
    ).all()
    assert [row.step_sha256 for row in step_receipts] == [
        step.step_sha256 for step in plan.steps
    ]
    assert [row.outcome for row in step_receipts] == ["verified", "verified"]
    assert result.step_receipts == tuple(step_receipts)
    audit = db_session.query(AuditLog).filter(AuditLog.event_type.like("workspace_app.%")).one()
    assert audit.event_type == "workspace_app.install.applied"
    assert audit.details["configuration_fields"] == ["api_contract"]
    assert audit.details["entitlements_mutated"] is False
    assert audit.details["lifecycle_phase"] == "normal"
    assert audit.details["steps_sha256"] == plan.steps_sha256
    assert audit.details["step_count"] == 2
    assert "configuration" not in audit.details


def test_normal_lifecycle_excludes_legacy_backfill_and_legacy_adoption_requires_evidence(
    db_session,
):
    normal_workspace = _workspace(db_session, "normal-phase", family="andritz")
    legacy_workspace = _workspace(db_session, "legacy-phase", family="andritz")
    manifest = _manifest("andritz.chat", "1.0.0")

    normal_plan = plan_workspace_app_lifecycle(
        db_session,
        workspace_id=normal_workspace.id,
        operation="install",
        app_id=manifest.app_id,
        target_version=manifest.version,
        expected_manifest_digest=manifest.digest,
    )
    assert all(step.kind == "platform_schema" for step in normal_plan.steps)

    legacy_plan = plan_workspace_app_lifecycle(
        db_session,
        workspace_id=legacy_workspace.id,
        operation="install",
        app_id=manifest.app_id,
        target_version=manifest.version,
        expected_manifest_digest=manifest.digest,
        lifecycle_phase="legacy_adoption",
    )
    assert [step.kind for step in legacy_plan.steps] == [
        "platform_schema",
        "platform_schema",
        "explicit_application_backfill",
    ]

    with pytest.raises(WorkspaceAppLifecycleConflict) as missing:
        apply_workspace_app_lifecycle(
            db_session,
            workspace_id=legacy_workspace.id,
            operation="install",
            app_id=manifest.app_id,
            target_version=manifest.version,
            expected_manifest_digest=manifest.digest,
            expected_plan_sha256=legacy_plan.plan_sha256,
            actor="lot9-test",
            idempotency_key="missing-legacy-evidence",
            lifecycle_phase="legacy_adoption",
        )
    assert missing.value.code == "lifecycle_prerequisite_unsatisfied"
    assert db_session.query(WorkspaceAppInstallation).count() == 0
    assert db_session.query(WorkspaceAppOperation).count() == 0
    assert db_session.query(WorkspaceAppLifecycleStepReceipt).count() == 0

    result = apply_workspace_app_lifecycle(
        db_session,
        workspace_id=legacy_workspace.id,
        operation="install",
        app_id=manifest.app_id,
        target_version=manifest.version,
        expected_manifest_digest=manifest.digest,
        expected_plan_sha256=legacy_plan.plan_sha256,
        actor="lot9-test",
        idempotency_key="valid-legacy-evidence",
        lifecycle_phase="legacy_adoption",
        prerequisite_evidence=_legacy_prerequisite(
            legacy_workspace,
            manifest,
            legacy_plan,
        ),
    )
    assert result.operation.lifecycle_phase == "legacy_adoption"
    assert [row.outcome for row in result.step_receipts] == [
        "verified",
        "verified",
        "verified",
    ]


def test_legacy_evidence_must_explicitly_select_the_current_workspace(db_session):
    workspace = _workspace(db_session, "legacy-wrong-workspace", family="andritz")
    manifest = _manifest("andritz.chat", "1.0.0")
    plan = plan_workspace_app_lifecycle(
        db_session,
        workspace_id=workspace.id,
        operation="install",
        app_id=manifest.app_id,
        target_version=manifest.version,
        expected_manifest_digest=manifest.digest,
        lifecycle_phase="legacy_adoption",
    )

    with pytest.raises(WorkspaceAppLifecycleConflict) as caught:
        apply_workspace_app_lifecycle(
            db_session,
            workspace_id=workspace.id,
            operation="install",
            app_id=manifest.app_id,
            target_version=manifest.version,
            expected_manifest_digest=manifest.digest,
            expected_plan_sha256=plan.plan_sha256,
            actor="lot9-test",
            idempotency_key="wrong-workspace-evidence",
            lifecycle_phase="legacy_adoption",
            prerequisite_evidence=_legacy_prerequisite(
                workspace,
                manifest,
                plan,
                requested_workspace_ids=["different-workspace"],
            ),
        )
    assert caught.value.code == "lifecycle_prerequisite_unsatisfied"
    assert db_session.query(WorkspaceAppInstallation).count() == 0
    assert db_session.query(WorkspaceAppLifecycleStepReceipt).count() == 0


def test_exact_retry_is_idempotent_and_conflicting_reuse_is_rejected(db_session):
    workspace = _workspace(db_session, "idempotent")
    manifest = _manifest("mission-room.extension", "1.0.0")
    plan, first = _plan_and_apply(
        db_session,
        workspace,
        operation="install",
        app_id=manifest.app_id,
        version=manifest.version,
        digest=manifest.digest,
        key="stable-request-key",
    )
    replay = apply_workspace_app_lifecycle(
        db_session,
        workspace_id=workspace.id,
        operation="install",
        app_id=manifest.app_id,
        target_version=manifest.version,
        expected_manifest_digest=manifest.digest,
        expected_plan_sha256=plan.plan_sha256,
        actor="lot9-test",
        idempotency_key="stable-request-key",
    )
    assert replay.idempotent_replay is True
    assert replay.operation.id == first.operation.id
    assert [row.id for row in replay.step_receipts] == [
        row.id for row in first.step_receipts
    ]
    assert replay.result_snapshot["revision"] == 1
    assert db_session.query(WorkspaceAppOperation).count() == 1
    assert db_session.query(WorkspaceAppLifecycleStepReceipt).count() == 2
    assert db_session.query(AuditLog).filter(AuditLog.event_type.like("workspace_app.%")).count() == 1

    with pytest.raises(WorkspaceAppLifecycleConflict) as caught:
        apply_workspace_app_lifecycle(
            db_session,
            workspace_id=workspace.id,
            operation="install",
            app_id=manifest.app_id,
            target_version=manifest.version,
            expected_manifest_digest=manifest.digest,
            expected_plan_sha256=plan.plan_sha256,
            configuration={"profile": "different"},
            actor="lot9-test",
            idempotency_key="stable-request-key",
        )
    assert caught.value.code == "idempotency_conflict"


def test_pre_073_operation_receipt_keeps_exact_idempotent_replay(db_session):
    workspace = _workspace(db_session, "legacy-operation-replay", family="andritz")
    manifest = _manifest("andritz.chat", "1.0.0")
    plan_sha256 = "7" * 64
    installation = WorkspaceAppInstallation(
        id=str(uuid4()),
        workspace_id=workspace.id,
        app_id=manifest.app_id,
        version=manifest.version,
        manifest_digest=manifest.digest,
        state="installed",
        configuration={"api_contract": "andritz.chat.v1"},
        revision=1,
        updated_by="legacy-actor",
    )
    request_sha256 = lifecycle_service._legacy_request_sha256(
        workspace_id=workspace.id,
        operation="install",
        app_id=manifest.app_id,
        target_version=manifest.version,
        expected_manifest_digest=manifest.digest,
        configuration=None,
        expected_plan_sha256=plan_sha256,
        actor="legacy-actor",
    )
    operation = WorkspaceAppOperation(
        id=str(uuid4()),
        workspace_id=workspace.id,
        installation_id=installation.id,
        app_id=manifest.app_id,
        idempotency_key="legacy-operation-key",
        request_sha256=request_sha256,
        operation="install",
        from_version=None,
        to_version=manifest.version,
        manifest_digest=manifest.digest,
        plan_sha256=plan_sha256,
        lifecycle_phase="legacy_unorchestrated",
        steps_sha256=lifecycle_service._hash_payload({"steps": []}),
        compensation={
            "failure": "database_transaction_rollback",
            "post_commit": "legacy_unorchestrated",
        },
        before_state={
            "state": "absent",
            "version": None,
            "manifest_digest": None,
            "configuration": {},
            "revision": 0,
        },
        after_state={
            "state": "installed",
            "version": manifest.version,
            "manifest_digest": manifest.digest,
            "configuration": {"api_contract": "andritz.chat.v1"},
            "revision": 1,
        },
        actor="legacy-actor",
    )
    db_session.add_all([installation, operation])
    db_session.commit()

    replay = apply_workspace_app_lifecycle(
        db_session,
        workspace_id=workspace.id,
        operation="install",
        app_id=manifest.app_id,
        target_version=manifest.version,
        expected_manifest_digest=manifest.digest,
        expected_plan_sha256=plan_sha256,
        actor="legacy-actor",
        idempotency_key="legacy-operation-key",
    )

    assert replay.idempotent_replay is True
    assert replay.operation.id == operation.id
    assert replay.step_receipts == ()


def test_active_runtime_authority_blocks_new_lifecycle_but_allows_exact_replay(
    db_session,
):
    workspace = _workspace(db_session, "active-authority", family="andritz")
    manifest = _manifest("andritz.chat", "1.0.0")
    install_plan, first = _plan_and_apply(
        db_session,
        workspace,
        operation="install",
        app_id=manifest.app_id,
        version=manifest.version,
        digest=manifest.digest,
        key="active-authority-install",
    )
    uninstall_plan = plan_workspace_app_lifecycle(
        db_session,
        workspace_id=workspace.id,
        operation="uninstall",
        app_id=manifest.app_id,
        target_version=None,
        expected_manifest_digest=manifest.digest,
    )
    workspace.settings = {
        **workspace.settings,
        "features": {WORKSPACE_APP_PLATFORM_FEATURE: True},
    }
    db_session.commit()

    with pytest.raises(WorkspaceAppLifecycleConflict) as plan_conflict:
        plan_workspace_app_lifecycle(
            db_session,
            workspace_id=workspace.id,
            operation="uninstall",
            app_id=manifest.app_id,
            target_version=None,
            expected_manifest_digest=manifest.digest,
        )
    assert plan_conflict.value.code == "runtime_authority_active"

    with pytest.raises(WorkspaceAppLifecycleConflict) as apply_conflict:
        apply_workspace_app_lifecycle(
            db_session,
            workspace_id=workspace.id,
            operation="uninstall",
            app_id=manifest.app_id,
            target_version=None,
            expected_manifest_digest=manifest.digest,
            expected_plan_sha256=uninstall_plan.plan_sha256,
            actor="lot9-test",
            idempotency_key="active-authority-uninstall",
        )
    assert apply_conflict.value.code == "runtime_authority_active"

    replay = apply_workspace_app_lifecycle(
        db_session,
        workspace_id=workspace.id,
        operation="install",
        app_id=manifest.app_id,
        target_version=manifest.version,
        expected_manifest_digest=manifest.digest,
        expected_plan_sha256=install_plan.plan_sha256,
        actor="lot9-test",
        idempotency_key="active-authority-install",
    )
    assert replay.idempotent_replay is True
    assert replay.operation.id == first.operation.id

    workspace.settings = {
        **workspace.settings,
        "features": {WORKSPACE_APP_PLATFORM_FEATURE: False},
    }
    db_session.commit()
    applied = apply_workspace_app_lifecycle(
        db_session,
        workspace_id=workspace.id,
        operation="uninstall",
        app_id=manifest.app_id,
        target_version=None,
        expected_manifest_digest=manifest.digest,
        expected_plan_sha256=uninstall_plan.plan_sha256,
        actor="lot9-test",
        idempotency_key="active-authority-uninstall",
    )
    assert applied.installation.state == "uninstalled"


def test_upgrade_rollback_and_uninstall_are_explicit_ordered_transitions(db_session):
    workspace = _workspace(db_session, "ordered")
    v1 = _manifest("mission-room.extension", "1.0.0")
    v11 = _manifest("mission-room.extension", "1.1.0")
    _plan_and_apply(
        db_session,
        workspace,
        operation="install",
        app_id=v1.app_id,
        version=v1.version,
        digest=v1.digest,
        key="ordered-install",
    )
    upgrade_plan, upgraded = _plan_and_apply(
        db_session,
        workspace,
        operation="upgrade",
        app_id=v11.app_id,
        version=v11.version,
        digest=v11.digest,
        key="ordered-upgrade",
    )
    assert upgraded.installation.version == "1.1.0"
    assert upgraded.installation.configuration["decision_surfaces"] is True
    assert upgraded.installation.revision == 2
    assert [step.manifest_role for step in upgrade_plan.steps] == [
        "source",
        "source",
        "target",
        "target",
    ]
    assert upgrade_plan.compensation["post_commit"] == "rollback_exact_before_state"

    rollback_plan, rolled_back = _plan_and_apply(
        db_session,
        workspace,
        operation="rollback",
        app_id=v1.app_id,
        version=v1.version,
        digest=v1.digest,
        key="ordered-rollback",
        configuration={"profile": "generic", "assistant_profile": "default"},
    )
    assert rolled_back.installation.version == "1.0.0"
    assert "decision_surfaces" not in rolled_back.installation.configuration
    assert rolled_back.installation.revision == 3
    assert [step.manifest_role for step in rollback_plan.steps] == [
        "source",
        "source",
        "target",
        "target",
    ]
    assert rollback_plan.compensation["post_commit"] == "upgrade_exact_before_state"

    uninstall_plan, uninstalled = _plan_and_apply(
        db_session,
        workspace,
        operation="uninstall",
        app_id=v1.app_id,
        version=None,
        digest=v1.digest,
        key="ordered-uninstall",
    )
    assert uninstalled.installation.state == "uninstalled"
    assert uninstalled.installation.version is None
    assert uninstalled.installation.manifest_digest is None
    assert uninstalled.installation.configuration == {}
    assert uninstalled.installation.revision == 4
    assert [step.manifest_role for step in uninstall_plan.steps] == [
        "source",
        "source",
    ]
    assert uninstall_plan.compensation["post_commit"] == "install_exact_before_state"
    assert db_session.query(WorkspaceAppOperation).count() == 4
    assert db_session.query(WorkspaceAppLifecycleStepReceipt).count() == 12


def test_rollback_requires_the_exact_previously_installed_state(db_session):
    workspace = _workspace(db_session, "rollback-history")
    v1 = _manifest("mission-room.extension", "1.0.0")
    v11 = _manifest("mission-room.extension", "1.1.0")
    _plan_and_apply(
        db_session,
        workspace,
        operation="install",
        app_id=v11.app_id,
        version=v11.version,
        digest=v11.digest,
        key="install-latest-directly",
    )
    with pytest.raises(WorkspaceAppLifecycleConflict) as missing_history:
        plan_workspace_app_lifecycle(
            db_session,
            workspace_id=workspace.id,
            operation="rollback",
            app_id=v1.app_id,
            target_version=v1.version,
            expected_manifest_digest=v1.digest,
        )
    assert missing_history.value.code == "rollback_target_not_recorded"


def test_unknown_version_digest_and_incompatible_config_fail_without_rows(db_session):
    workspace = _workspace(db_session, "invalid")
    sentinel = _manifest("sentinel.mission-room", "1.0.0")
    with pytest.raises(WorkspaceAppLifecycleNotFound):
        plan_workspace_app_lifecycle(
            db_session,
            workspace_id=workspace.id,
            operation="install",
            app_id=sentinel.app_id,
            target_version="2.0.0",
            expected_manifest_digest=sentinel.digest,
        )
    with pytest.raises(WorkspaceAppLifecycleValidationError, match="digest mismatch"):
        plan_workspace_app_lifecycle(
            db_session,
            workspace_id=workspace.id,
            operation="install",
            app_id=sentinel.app_id,
            target_version=sentinel.version,
            expected_manifest_digest="0" * 64,
        )
    with pytest.raises(WorkspaceAppLifecycleValidationError, match="allowed values"):
        plan_workspace_app_lifecycle(
            db_session,
            workspace_id=workspace.id,
            operation="install",
            app_id=sentinel.app_id,
            target_version=sentinel.version,
            expected_manifest_digest=sentinel.digest,
            configuration={"assistant_profile": "octave_executive"},
        )
    assert db_session.query(WorkspaceAppInstallation).count() == 0
    assert db_session.query(WorkspaceAppOperation).count() == 0


def test_workspace_tenant_isolation_allows_same_app_and_key_per_tenant(db_session):
    first_workspace = _workspace(db_session, "tenant-a", family="andritz")
    second_workspace = _workspace(db_session, "tenant-b", family="andritz")
    manifest = _manifest("andritz.knowledge-capture", "1.0.0")
    for workspace in (first_workspace, second_workspace):
        _plan_and_apply(
            db_session,
            workspace,
            operation="install",
            app_id=manifest.app_id,
            version=manifest.version,
            digest=manifest.digest,
            key="same-tenant-local-key",
        )
    rows = db_session.query(WorkspaceAppInstallation).order_by(
        WorkspaceAppInstallation.workspace_id
    ).all()
    assert {row.workspace_id for row in rows} == {
        first_workspace.id,
        second_workspace.id,
    }
    assert len(rows) == 2
    assert db_session.query(WorkspaceAppOperation).count() == 2


def test_stale_plan_is_rejected_after_intervening_install_and_uninstall(db_session):
    workspace = _workspace(db_session, "stale", family="andritz")
    manifest = _manifest("andritz.client360-pdr", "1.0.0")
    stale = plan_workspace_app_lifecycle(
        db_session,
        workspace_id=workspace.id,
        operation="install",
        app_id=manifest.app_id,
        target_version=manifest.version,
        expected_manifest_digest=manifest.digest,
    )
    _plan_and_apply(
        db_session,
        workspace,
        operation="install",
        app_id=manifest.app_id,
        version=manifest.version,
        digest=manifest.digest,
        key="intervening-install",
    )
    _plan_and_apply(
        db_session,
        workspace,
        operation="uninstall",
        app_id=manifest.app_id,
        version=None,
        digest=manifest.digest,
        key="intervening-uninstall",
    )
    with pytest.raises(WorkspaceAppLifecycleConflict) as caught:
        apply_workspace_app_lifecycle(
            db_session,
            workspace_id=workspace.id,
            operation="install",
            app_id=manifest.app_id,
            target_version=manifest.version,
            expected_manifest_digest=manifest.digest,
            expected_plan_sha256=stale.plan_sha256,
            actor="lot9-test",
            idempotency_key="stale-install",
        )
    assert caught.value.code == "stale_plan"
    assert db_session.query(WorkspaceAppOperation).count() == 2


def test_composed_apply_can_defer_commit_to_a_wider_transaction(db_session):
    workspace = _workspace(db_session, "deferred-commit", family="andritz")
    manifest = _manifest("andritz.chat", "1.0.0")
    plan = plan_workspace_app_lifecycle(
        db_session,
        workspace_id=workspace.id,
        operation="install",
        app_id=manifest.app_id,
        target_version=manifest.version,
        expected_manifest_digest=manifest.digest,
    )

    apply_workspace_app_lifecycle(
        db_session,
        workspace_id=workspace.id,
        operation="install",
        app_id=manifest.app_id,
        target_version=manifest.version,
        expected_manifest_digest=manifest.digest,
        expected_plan_sha256=plan.plan_sha256,
        actor="composed-transaction",
        idempotency_key="deferred-commit-install",
        commit=False,
    )
    assert db_session.query(WorkspaceAppInstallation).count() == 1
    assert db_session.query(WorkspaceAppOperation).count() == 1

    db_session.rollback()
    assert db_session.query(WorkspaceAppInstallation).count() == 0
    assert db_session.query(WorkspaceAppOperation).count() == 0
    assert db_session.query(WorkspaceAppLifecycleStepReceipt).count() == 0


def test_audit_failure_rolls_back_installation_and_receipt(db_session):
    workspace = _workspace(
        db_session,
        "audit-failure",
        profile="octocity_institutional_v1",
    )
    manifest = _manifest("octocity.mission-room", "1.0.0")
    plan = plan_workspace_app_lifecycle(
        db_session,
        workspace_id=workspace.id,
        operation="install",
        app_id=manifest.app_id,
        target_version=manifest.version,
        expected_manifest_digest=manifest.digest,
    )

    def fail_lifecycle_audit(session, _flush_context, _instances):
        if any(
            isinstance(row, AuditLog) and row.event_type.startswith("workspace_app.")
            for row in session.new
        ):
            raise RuntimeError("audit unavailable")

    event.listen(db_session, "before_flush", fail_lifecycle_audit)
    try:
        with pytest.raises(RuntimeError, match="audit unavailable"):
            apply_workspace_app_lifecycle(
                db_session,
                workspace_id=workspace.id,
                operation="install",
                app_id=manifest.app_id,
                target_version=manifest.version,
                expected_manifest_digest=manifest.digest,
                expected_plan_sha256=plan.plan_sha256,
                actor="lot9-test",
                idempotency_key="audit-fails",
            )
    finally:
        event.remove(db_session, "before_flush", fail_lifecycle_audit)
    assert db_session.query(WorkspaceAppInstallation).count() == 0
    assert db_session.query(WorkspaceAppOperation).count() == 0
    assert db_session.query(WorkspaceAppLifecycleStepReceipt).count() == 0
    assert db_session.query(AuditLog).filter(AuditLog.event_type.like("workspace_app.%")).count() == 0


def test_step_executor_failure_rolls_back_installation_receipts_and_audit(
    db_session,
    monkeypatch,
):
    workspace = _workspace(db_session, "step-failure", family="andritz")
    manifest = _manifest("andritz.chat", "1.0.0")
    plan = plan_workspace_app_lifecycle(
        db_session,
        workspace_id=workspace.id,
        operation="install",
        app_id=manifest.app_id,
        target_version=manifest.version,
        expected_manifest_digest=manifest.digest,
    )
    original = lifecycle_service.LIFECYCLE_STEP_EXECUTORS[
        "platform_schema_contract_v1"
    ]

    def fail_second_step(db, *, step, **context):
        if step.step_id == "workspace_app_platform.lifecycle_steps.073":
            raise RuntimeError("closed executor unavailable")
        return original(db, step=step, **context)

    monkeypatch.setattr(
        lifecycle_service,
        "LIFECYCLE_STEP_EXECUTORS",
        MappingProxyType(
            {
                **lifecycle_service.LIFECYCLE_STEP_EXECUTORS,
                "platform_schema_contract_v1": fail_second_step,
            }
        ),
    )
    with pytest.raises(RuntimeError, match="closed executor unavailable"):
        apply_workspace_app_lifecycle(
            db_session,
            workspace_id=workspace.id,
            operation="install",
            app_id=manifest.app_id,
            target_version=manifest.version,
            expected_manifest_digest=manifest.digest,
            expected_plan_sha256=plan.plan_sha256,
            actor="lot9-test",
            idempotency_key="step-failure",
        )

    assert db_session.query(WorkspaceAppInstallation).count() == 0
    assert db_session.query(WorkspaceAppOperation).count() == 0
    assert db_session.query(WorkspaceAppLifecycleStepReceipt).count() == 0
    assert db_session.query(AuditLog).filter(AuditLog.event_type.like("workspace_app.%")).count() == 0


def test_family_and_profile_compatibility_use_structural_settings_only(db_session):
    slug_only = _workspace(db_session, "andritz-by-slug")
    slug_only.slug = "andritz"
    db_session.commit()
    andritz = _manifest("andritz.chat", "1.0.0")
    assert workspace_app_is_compatible(slug_only, andritz) is False

    with pytest.raises(WorkspaceAppLifecycleConflict) as family_error:
        plan_workspace_app_lifecycle(
            db_session,
            workspace_id=slug_only.id,
            operation="install",
            app_id=andritz.app_id,
            target_version=andritz.version,
            expected_manifest_digest=andritz.digest,
        )
    assert family_error.value.code == "workspace_family_incompatible"

    sentinel_workspace = _workspace(
        db_session,
        "sentinel-wrong-profile",
        family="sentinel_ci",
        profile="octocity_institutional_v1",
    )
    sentinel = _manifest("sentinel.mission-room", "1.0.0")
    with pytest.raises(WorkspaceAppLifecycleConflict) as profile_error:
        plan_workspace_app_lifecycle(
            db_session,
            workspace_id=sentinel_workspace.id,
            operation="install",
            app_id=sentinel.app_id,
            target_version=sentinel.version,
            expected_manifest_digest=sentinel.digest,
        )
    assert profile_error.value.code == "workspace_profile_incompatible"

    compatible_sentinel = _workspace(
        db_session,
        "sentinel-compatible",
        family="sentinel_ci",
        profile="sentinel_government_v1",
    )
    assert validate_workspace_app_compatibility(compatible_sentinel, sentinel) == {
        "family": "sentinel_ci",
        "profile": "sentinel_government_v1",
    }
    assert workspace_app_is_compatible(compatible_sentinel, sentinel) is True

    malformed = _workspace(db_session, "malformed-family")
    malformed.settings = {"family": "showcase"}
    db_session.commit()
    generic = _manifest("mission-room.extension", "1.1.0")
    with pytest.raises(WorkspaceAppLifecycleConflict) as invalid_family:
        plan_workspace_app_lifecycle(
            db_session,
            workspace_id=malformed.id,
            operation="install",
            app_id=generic.app_id,
            target_version=generic.version,
            expected_manifest_digest=generic.digest,
        )
    assert invalid_family.value.code == "workspace_family_invalid"


def test_generic_mission_room_rejects_reserved_structural_profile(db_session):
    workspace = _workspace(
        db_session,
        "reserved-generic",
        profile="octocity_institutional_v1",
    )
    manifest = _manifest("mission-room.extension", "1.1.0")

    with pytest.raises(WorkspaceAppLifecycleConflict) as caught:
        plan_workspace_app_lifecycle(
            db_session,
            workspace_id=workspace.id,
            operation="install",
            app_id=manifest.app_id,
            target_version=manifest.version,
            expected_manifest_digest=manifest.digest,
        )
    assert caught.value.code == "workspace_profile_reserved"


@pytest.mark.parametrize(
    ("first_app", "first_family", "first_profile", "second_app", "second_family", "second_profile"),
    [
        (
            "sentinel.mission-room",
            "sentinel_ci",
            "sentinel_government_v1",
            "octocity.mission-room",
            "generic",
            "octocity_institutional_v1",
        ),
        (
            "octocity.mission-room",
            "generic",
            "octocity_institutional_v1",
            "sentinel.mission-room",
            "sentinel_ci",
            "sentinel_government_v1",
        ),
    ],
)
def test_sentinel_and_octocity_cannot_coexist_in_either_direction(
    db_session,
    first_app,
    first_family,
    first_profile,
    second_app,
    second_family,
    second_profile,
):
    workspace = _workspace(
        db_session,
        f"exclusive-{first_app.split('.')[0]}",
        family=first_family,
        profile=first_profile,
    )
    first = _manifest(first_app, "1.0.0")
    _plan_and_apply(
        db_session,
        workspace,
        operation="install",
        app_id=first.app_id,
        version=first.version,
        digest=first.digest,
        key=f"install-{first.app_id}",
    )

    workspace.settings = {
        "family": second_family,
        "mission_room": {"enabled": True, "profile": second_profile},
    }
    db_session.commit()
    second = _manifest(second_app, "1.0.0")
    with pytest.raises(WorkspaceAppLifecycleConflict) as caught:
        plan_workspace_app_lifecycle(
            db_session,
            workspace_id=workspace.id,
            operation="install",
            app_id=second.app_id,
            target_version=second.version,
            expected_manifest_digest=second.digest,
        )

    assert caught.value.code == "conflict_group"
    installed = db_session.query(WorkspaceAppInstallation).filter(
        WorkspaceAppInstallation.workspace_id == workspace.id,
        WorkspaceAppInstallation.state == "installed",
    ).all()
    assert [row.app_id for row in installed] == [first.app_id]


def test_business_and_immersive_shells_cannot_be_composed(db_session):
    workspace = _workspace(db_session, "shell-conflict", family="andritz")
    business = _manifest("andritz.chat", "1.0.0")
    _plan_and_apply(
        db_session,
        workspace,
        operation="install",
        app_id=business.app_id,
        version=business.version,
        digest=business.digest,
        key="install-business-shell",
    )
    workspace.settings = {
        "family": "generic",
        "mission_room": {"enabled": True, "profile": "generic"},
    }
    db_session.commit()
    immersive = _manifest("mission-room.extension", "1.1.0")

    with pytest.raises(WorkspaceAppLifecycleConflict) as caught:
        plan_workspace_app_lifecycle(
            db_session,
            workspace_id=workspace.id,
            operation="install",
            app_id=immersive.app_id,
            target_version=immersive.version,
            expected_manifest_digest=immersive.digest,
        )
    assert caught.value.code == "shell_conflict"


def test_nested_exclusive_routes_are_rejected_even_without_a_shared_group(
    db_session,
    monkeypatch,
):
    workspace = _workspace(db_session, "route-conflict", family="andritz")
    installed = _manifest("andritz.chat", "1.0.0")
    _plan_and_apply(
        db_session,
        workspace,
        operation="install",
        app_id=installed.app_id,
        version=installed.version,
        digest=installed.digest,
        key="install-route-owner",
    )

    payload = deepcopy(_manifest("andritz.client360-pdr", "1.0.0").as_dict())
    payload["app_id"] = "andritz.chat-extension"
    payload["routes"] = ["/chat/embedded"]
    payload["surfaces"][0]["route"] = "/chat/embedded"
    payload["experience"]["default_route"] = "/chat/embedded"
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    fake = CompiledWorkspaceAppManifest(
        app_id=payload["app_id"],
        version=payload["version"],
        digest=hashlib.sha256(canonical.encode()).hexdigest(),
        canonical_json=canonical,
    )
    original_resolver = lifecycle_service._resolve_manifest

    def resolve(app_id, version, expected_digest):
        if app_id == fake.app_id:
            assert version == fake.version
            assert expected_digest == fake.digest
            return fake
        return original_resolver(app_id, version, expected_digest)

    monkeypatch.setattr(lifecycle_service, "_resolve_manifest", resolve)
    with pytest.raises(WorkspaceAppLifecycleConflict) as caught:
        plan_workspace_app_lifecycle(
            db_session,
            workspace_id=workspace.id,
            operation="install",
            app_id=fake.app_id,
            target_version=fake.version,
            expected_manifest_digest=fake.digest,
        )
    assert caught.value.code == "route_conflict"


def test_second_composed_apply_failure_rolls_back_the_wider_transaction(db_session):
    workspace = _workspace(db_session, "composed-failure", family="andritz")
    first = _manifest("andritz.chat", "1.0.0")
    second = _manifest("andritz.client360-pdr", "1.0.0")
    first_plan = plan_workspace_app_lifecycle(
        db_session,
        workspace_id=workspace.id,
        operation="install",
        app_id=first.app_id,
        target_version=first.version,
        expected_manifest_digest=first.digest,
    )
    plan_workspace_app_lifecycle(
        db_session,
        workspace_id=workspace.id,
        operation="install",
        app_id=second.app_id,
        target_version=second.version,
        expected_manifest_digest=second.digest,
    )
    apply_workspace_app_lifecycle(
        db_session,
        workspace_id=workspace.id,
        operation="install",
        app_id=first.app_id,
        target_version=first.version,
        expected_manifest_digest=first.digest,
        expected_plan_sha256=first_plan.plan_sha256,
        actor="composed-transaction",
        idempotency_key="composed-first",
        commit=False,
    )

    with pytest.raises(WorkspaceAppLifecycleConflict) as caught:
        apply_workspace_app_lifecycle(
            db_session,
            workspace_id=workspace.id,
            operation="install",
            app_id=second.app_id,
            target_version=second.version,
            expected_manifest_digest=second.digest,
            expected_plan_sha256="f" * 64,
            actor="composed-transaction",
            idempotency_key="composed-second",
            commit=False,
        )
    assert caught.value.code == "stale_plan"
    assert db_session.query(WorkspaceAppInstallation).count() == 0
    assert db_session.query(WorkspaceAppOperation).count() == 0
    assert db_session.query(WorkspaceAppLifecycleStepReceipt).count() == 0
    assert db_session.query(AuditLog).filter(AuditLog.event_type.like("workspace_app.%")).count() == 0
