"""Two-phase, attested rollout for Workspace App runtime authority."""

from __future__ import annotations

import base64
import copy
import hashlib
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.core.config import settings
from app.models.audit import AuditLog
from app.models.workspace import Workspace
from app.models.workspace_app import WorkspaceAppInstallation
from app.services.workspace_app_lifecycle import (
    WorkspaceAppLifecycleConflict,
    plan_workspace_app_lifecycle,
)
from app.services.workspace_app_manifests import (
    BUILTIN_WORKSPACE_APP_MANIFESTS,
    validate_manifest_configuration,
)
from app.services.workspace_app_runtime import (
    WORKSPACE_APP_ROLLOUT_STATE_KEY,
    WorkspaceAppRuntimeError,
    inspect_authoritative_workspace_app_runtime,
    resolve_workspace_app_runtime,
)
from scripts import rollout_workspace_app_platform as rollout

REVISION = "a" * 40


def _trusted_runner(
    *,
    revision: str = REVISION,
    pipeline_id: str = "pipeline-1",
    job_id: str = "job-1",
) -> dict:
    return {
        "issuer": "https://gitlab.com",
        "project_id": "42",
        "pipeline_id": pipeline_id,
        "job_id": job_id,
        "commit_sha": revision,
        "ref": "demo/agentic",
        "ref_protected": True,
    }


def _workspace(db, *, marked: bool = True, family: str = "andritz") -> Workspace:
    workspace = Workspace(
        id=str(uuid4()),
        name="Opaque Workspace App target",
        slug=f"opaque-{uuid4().hex[:8]}",
        settings={
            "family": family,
            "features": {rollout.WORKSPACE_APP_PLATFORM_FEATURE: False},
            "experience": (
                {rollout.CANARY_MARKER: rollout.CANARY_MARKER_VALUE} if marked else {}
            ),
        },
    )
    db.add(workspace)
    db.commit()
    return workspace


def _install(db, workspace: Workspace, app_id: str = "andritz.chat") -> WorkspaceAppInstallation:
    manifest = BUILTIN_WORKSPACE_APP_MANIFESTS[(app_id, "1.0.0")]
    row = WorkspaceAppInstallation(
        id=str(uuid4()),
        workspace_id=workspace.id,
        app_id=manifest.app_id,
        version=manifest.version,
        manifest_digest=manifest.digest,
        state="installed",
        configuration=validate_manifest_configuration(manifest, None),
        revision=1,
        installed_at=datetime.now(UTC).replace(tzinfo=None),
        updated_by="rollout-test",
    )
    db.add(row)
    db.commit()
    return row


def _evidence(
    db,
    workspace: Workspace,
    *,
    phase: str,
    generated_at: datetime | None = None,
    probation_ref: str | None = None,
    trusted_runner: dict | None = None,
) -> dict:
    runtime = (
        resolve_workspace_app_runtime(workspace, db=db)
        if phase == "postactivation"
        else inspect_authoritative_workspace_app_runtime(workspace, db=db)
    )
    installations = rollout._installation_subject(runtime)
    installation_sha = rollout._sha256(installations)
    if phase == "preflight":
        kind = rollout.PREFLIGHT_EVIDENCE_KIND
        suite = rollout.PREFLIGHT_EVIDENCE_SUITE
        checks = rollout.PREFLIGHT_CHECKS
    else:
        kind = rollout.POSTACTIVATION_EVIDENCE_KIND
        suite = rollout.POSTACTIVATION_EVIDENCE_SUITE
        checks = rollout.POSTACTIVATION_CHECKS
        probation_ref = probation_ref or runtime.rollout_ref
    source_junit = f"<testsuite name='{phase}-source'/>".encode()
    source_junit_sha256 = hashlib.sha256(source_junit).hexdigest()
    source_junit_ref = f"sha256:{source_junit_sha256}"
    observation_ref = "sha256:" + hashlib.sha256(
        f"{workspace.id}:{phase}:{probation_ref or ''}".encode()
    ).hexdigest()
    properties = (
        f'<property name="revision" value="{REVISION}"/>'
        f'<property name="workspace_id" value="{workspace.id}"/>'
        f'<property name="installations_sha256" value="{installation_sha}"/>'
        f'<property name="observation_ref" value="{observation_ref}"/>'
        f'<property name="source_junit_ref" value="{source_junit_ref}"/>'
    )
    if probation_ref is not None:
        properties += f'<property name="probation_ref" value="{probation_ref}"/>'
    testcases = "".join(
        f'<testcase name="{name}" classname="{suite}"/>' for name in checks
    )
    raw = (
        f'<testsuite name="{suite}" tests="{len(checks)}" failures="0" '
        f'errors="0" skipped="0"><properties>{properties}</properties>'
        f"{testcases}</testsuite>"
    ).encode()
    digest = hashlib.sha256(raw).hexdigest()
    subject = {
        "workspace_id": workspace.id,
        "installations": installations,
        "installations_sha256": installation_sha,
    }
    if probation_ref is not None:
        subject["probation_ref"] = probation_ref
    return {
        "schema_version": rollout.EVIDENCE_SCHEMA_VERSION,
        "kind": kind,
        "activation_grade": True,
        "generated_at": (generated_at or datetime.now(UTC)).isoformat(),
        "revision": REVISION,
        "validated_by": "protected-runner",
        "observation_ref": observation_ref,
        "trusted_runner": trusted_runner or _trusted_runner(),
        "source_junit": {
            "media_type": "application/junit+xml",
            "sha256": source_junit_sha256,
            "artifact_ref": source_junit_ref,
        },
        "subject": subject,
        "checks": {key: True for key in checks},
        "runner_artifact": {
            "media_type": "application/junit+xml",
            "sha256": digest,
            "artifact_ref": f"sha256:{digest}",
            "content_base64": base64.b64encode(raw).decode(),
        },
    }


def _stage(db, workspace: Workspace) -> dict:
    return rollout.stage(
        db,
        workspace_id=workspace.id,
        evidence=_evidence(db, workspace, phase="preflight"),
        apply=True,
        actor="operator@example.test",
        trusted_runner=_trusted_runner(),
    )


def _finalize(db, workspace: Workspace) -> dict:
    runtime = resolve_workspace_app_runtime(workspace, db=db)
    return rollout.finalize(
        db,
        workspace_id=workspace.id,
        evidence=_evidence(
            db,
            workspace,
            phase="postactivation",
            probation_ref=runtime.rollout_ref,
        ),
        apply=True,
        actor="operator@example.test",
        trusted_runner=_trusted_runner(),
    )


@pytest.fixture(autouse=True)
def _runtime_revision(monkeypatch):
    monkeypatch.setattr(settings, "agentium_image_revision", REVISION)
    monkeypatch.setattr(
        settings,
        "authorization_v2_trusted_oidc_issuer",
        "https://gitlab.com",
    )
    monkeypatch.setattr(settings, "authorization_v2_trusted_project_id", "42")
    monkeypatch.setattr(settings, "authorization_v2_trusted_ref", "demo/agentic")


def test_status_stage_dry_run_and_direct_activation_boundary(db_session) -> None:
    workspace = _workspace(db_session)
    assert rollout.status(db_session, workspace_id=workspace.id)["blocker"] == "no_installed_apps"
    _install(db_session, workspace)

    preview = rollout.stage(
        db_session,
        workspace_id=workspace.id,
        evidence=_evidence(db_session, workspace, phase="preflight"),
        apply=False,
        actor="",
    )
    assert preview["operation"] == "stage"
    assert preview["changed"] is True
    db_session.refresh(workspace)
    assert workspace.settings["features"][rollout.WORKSPACE_APP_PLATFORM_FEATURE] is False
    assert rollout.ROLLOUT_STATE_KEY not in workspace.settings
    with pytest.raises(rollout.WorkspaceAppRolloutError, match="direct activation"):
        rollout.activate()


def test_bootstrap_is_dry_run_safe_applied_once_and_audited(db_session) -> None:
    workspace = _workspace(db_session, marked=False)
    _install(db_session, workspace)

    preview = rollout.bootstrap(
        db_session,
        workspace_id=workspace.id,
        apply=False,
        actor="",
    )
    assert preview["changed"] is True
    assert preview["runtime_authority_enabled"] is False
    db_session.refresh(workspace)
    assert rollout._is_canary(workspace) is False

    applied = rollout.bootstrap(
        db_session,
        workspace_id=workspace.id,
        apply=True,
        actor="operator@example.test",
    )
    db_session.refresh(workspace)
    assert applied["changed"] is True
    assert rollout._is_canary(workspace) is True
    assert workspace.settings["features"][rollout.WORKSPACE_APP_PLATFORM_FEATURE] is False
    assert (
        db_session.query(AuditLog)
        .filter_by(event_type="lot9.workspace_app_platform.canary_bootstrapped")
        .count()
        == 1
    )

    replay = rollout.bootstrap(
        db_session,
        workspace_id=workspace.id,
        apply=True,
        actor="",
    )
    assert replay["changed"] is False
    assert (
        db_session.query(AuditLog)
        .filter_by(event_type="lot9.workspace_app_platform.canary_bootstrapped")
        .count()
        == 1
    )


def test_bootstrap_rejects_another_marker_empty_set_and_active_authority(db_session) -> None:
    marked = _workspace(db_session, marked=True)
    _install(db_session, marked)
    target = _workspace(db_session, marked=False)
    _install(db_session, target)
    with pytest.raises(rollout.WorkspaceAppRolloutError, match="another active Workspace"):
        rollout.bootstrap(
            db_session,
            workspace_id=target.id,
            apply=False,
            actor="",
        )

    marked.settings = {
        **marked.settings,
        "experience": {},
    }
    empty = _workspace(db_session, marked=False)
    db_session.commit()
    with pytest.raises(rollout.WorkspaceAppRolloutError, match="at least one trusted"):
        rollout.bootstrap(
            db_session,
            workspace_id=empty.id,
            apply=False,
            actor="",
        )

    empty.settings = {
        **empty.settings,
        "features": {rollout.WORKSPACE_APP_PLATFORM_FEATURE: True},
    }
    db_session.commit()
    with pytest.raises(rollout.WorkspaceAppRolloutError, match="must be disabled"):
        rollout.bootstrap(
            db_session,
            workspace_id=empty.id,
            apply=False,
            actor="",
        )


def test_stage_opens_bounded_probation_and_finalize_binds_both_proofs(db_session) -> None:
    workspace = _workspace(db_session)
    _install(db_session, workspace)
    staged = _stage(db_session, workspace)

    db_session.refresh(workspace)
    probation = resolve_workspace_app_runtime(workspace, db=db_session)
    assert probation.rollout_phase == "probation"
    assert probation.rollout_ref == staged["probation_ref"]
    state = rollout._state(workspace)
    assert state["activations"] == []
    assert "content_base64" not in str(state)

    finalized = _finalize(db_session, workspace)
    db_session.refresh(workspace)
    active = resolve_workspace_app_runtime(workspace, db=db_session)
    state = rollout._state(workspace)
    assert finalized["changed"] is True
    assert active.rollout_phase == "active"
    assert active.app_ids == ("andritz.chat",)
    assert state["probation"] is None
    assert len(state["activations"]) == 1
    activation = state["activations"][0]
    assert activation["workspace_id"] == workspace.id
    assert activation["probation_ref"] == staged["probation_ref"]
    assert activation["preflight_artifact_tests"] == 3
    assert activation["postactivation_artifact_tests"] == 4
    assert activation["artifact_tests"] == 7
    assert (
        db_session.query(AuditLog)
        .filter_by(event_type="lot9.workspace_app_platform.staged")
        .count()
        == 1
    )
    assert (
        db_session.query(AuditLog)
        .filter_by(event_type="lot9.workspace_app_platform.activated")
        .count()
        == 1
    )


def test_probation_expiry_fails_closed_but_abort_is_always_safe(db_session) -> None:
    workspace = _workspace(db_session)
    _install(db_session, workspace)
    _stage(db_session, workspace)
    state = rollout._state(workspace)
    probation = state["probation"]
    assert probation is not None
    probation["staged_at"] = (datetime.now(UTC) - timedelta(minutes=2)).isoformat()
    probation["expires_at"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    probation["probation_sha256"] = rollout._probation_digest(probation)
    probation["probation_ref"] = f"sha256:{probation['probation_sha256']}"
    state["probation"] = probation
    rollout._save_state(workspace, state)
    db_session.commit()

    with pytest.raises(WorkspaceAppRuntimeError) as expired:
        resolve_workspace_app_runtime(workspace, db=db_session)
    assert expired.value.code == "rollout_probation_expired"

    aborted = rollout.abort(
        db_session,
        workspace_id=workspace.id,
        apply=True,
        actor="operator@example.test",
        reason="probation expired",
    )
    db_session.refresh(workspace)
    assert aborted["changed"] is True
    assert workspace.settings["features"][rollout.WORKSPACE_APP_PLATFORM_FEATURE] is False
    assert rollout._state(workspace)["probation"] is None
    assert resolve_workspace_app_runtime(workspace, db=db_session).rollout_phase == "disabled"


def test_lifecycle_is_blocked_for_the_whole_probation(db_session) -> None:
    workspace = _workspace(db_session)
    row = _install(db_session, workspace)
    _stage(db_session, workspace)

    with pytest.raises(WorkspaceAppLifecycleConflict) as blocked:
        plan_workspace_app_lifecycle(
            db_session,
            workspace_id=workspace.id,
            operation="upgrade",
            app_id=row.app_id,
            target_version=row.version,
            expected_manifest_digest=str(row.manifest_digest),
        )
    assert blocked.value.code == "runtime_authority_active"


def test_installation_or_configuration_drift_invalidates_probation(db_session) -> None:
    workspace = _workspace(db_session)
    row = _install(db_session, workspace)
    _stage(db_session, workspace)
    row.configuration = {"unexpected": "behaviour drift"}
    db_session.commit()

    with pytest.raises(WorkspaceAppRuntimeError) as drifted:
        resolve_workspace_app_runtime(workspace, db=db_session)
    assert drifted.value.code in {"manifest_untrusted", "rollout_attestation_stale"}


def test_cross_workspace_rollout_state_transplant_fails_closed(db_session) -> None:
    source = _workspace(db_session)
    _install(db_session, source)
    _stage(db_session, source)
    _finalize(db_session, source)

    target = _workspace(db_session, marked=False)
    _install(db_session, target)
    target.settings = {
        **target.settings,
        "features": {rollout.WORKSPACE_APP_PLATFORM_FEATURE: True},
        WORKSPACE_APP_ROLLOUT_STATE_KEY: copy.deepcopy(
            source.settings[WORKSPACE_APP_ROLLOUT_STATE_KEY]
        ),
    }
    db_session.commit()

    with pytest.raises(WorkspaceAppRuntimeError) as transplanted:
        resolve_workspace_app_runtime(target, db=db_session)
    assert transplanted.value.code == "rollout_workspace_mismatch"


def test_finalize_rejects_another_probation_or_subject(db_session) -> None:
    workspace = _workspace(db_session)
    _install(db_session, workspace)
    _stage(db_session, workspace)
    evidence = _evidence(db_session, workspace, phase="postactivation")

    wrong_probation = copy.deepcopy(evidence)
    wrong_probation["subject"]["probation_ref"] = "sha256:" + "b" * 64
    with pytest.raises(rollout.WorkspaceAppRolloutError, match="different probation"):
        rollout.finalize(
            db_session,
            workspace_id=workspace.id,
            evidence=wrong_probation,
            apply=False,
            actor="",
        )

    wrong_workspace = copy.deepcopy(evidence)
    wrong_workspace["subject"]["workspace_id"] = str(uuid4())
    with pytest.raises(rollout.WorkspaceAppRolloutError, match="target Workspace"):
        rollout.finalize(
            db_session,
            workspace_id=workspace.id,
            evidence=wrong_workspace,
            apply=False,
            actor="",
        )


def test_deactivate_closes_final_activation_and_allows_fresh_stage(db_session) -> None:
    workspace = _workspace(db_session)
    _install(db_session, workspace)
    _stage(db_session, workspace)
    _finalize(db_session, workspace)

    result = rollout.deactivate(
        db_session,
        workspace_id=workspace.id,
        apply=True,
        actor="operator@example.test",
        reason="planned lifecycle window",
    )
    db_session.refresh(workspace)
    assert result["changed"] is True
    assert resolve_workspace_app_runtime(workspace, db=db_session).rollout_phase == "disabled"
    state = rollout._state(workspace)
    assert len(state["activations"]) == len(state["deactivations"]) == 1
    assert state["deactivations"][0]["workspace_id"] == workspace.id

    restaged = _stage(db_session, workspace)
    assert restaged["changed"] is True
    assert resolve_workspace_app_runtime(workspace, db=db_session).rollout_phase == "probation"


def test_stage_requires_same_oidc_job_and_source_junit_binding(db_session) -> None:
    workspace = _workspace(db_session)
    _install(db_session, workspace)
    evidence = _evidence(db_session, workspace, phase="preflight")

    preview = rollout.stage(
        db_session,
        workspace_id=workspace.id,
        evidence=evidence,
        apply=False,
        actor="",
    )
    assert preview["validation"]["trusted_runner"] == _trusted_runner()
    with pytest.raises(rollout.WorkspaceAppRolloutError, match="protected GitLab OIDC runner"):
        rollout.stage(
            db_session,
            workspace_id=workspace.id,
            evidence=evidence,
            apply=True,
            actor="operator@example.test",
        )
    with pytest.raises(rollout.WorkspaceAppRolloutError, match="same protected GitLab job"):
        rollout.stage(
            db_session,
            workspace_id=workspace.id,
            evidence=evidence,
            apply=True,
            actor="operator@example.test",
            trusted_runner=_trusted_runner(pipeline_id="pipeline-2"),
        )

    tampered = copy.deepcopy(evidence)
    tampered["source_junit"]["sha256"] = "9" * 64
    tampered["source_junit"]["artifact_ref"] = "sha256:" + "9" * 64
    with pytest.raises(rollout.WorkspaceAppRolloutError, match="subject differs"):
        rollout.stage(
            db_session,
            workspace_id=workspace.id,
            evidence=tampered,
            apply=False,
            actor="",
        )
    assert workspace.settings["features"][rollout.WORKSPACE_APP_PLATFORM_FEATURE] is False


def test_finalize_is_bound_to_the_preflight_and_postactivation_job(db_session) -> None:
    workspace = _workspace(db_session)
    _install(db_session, workspace)
    _stage(db_session, workspace)
    runtime = resolve_workspace_app_runtime(workspace, db=db_session)
    post_from_another_job = _evidence(
        db_session,
        workspace,
        phase="postactivation",
        probation_ref=runtime.rollout_ref,
        trusted_runner=_trusted_runner(job_id="job-2"),
    )

    with pytest.raises(rollout.WorkspaceAppRolloutError, match="same protected GitLab job as preflight"):
        rollout.finalize(
            db_session,
            workspace_id=workspace.id,
            evidence=post_from_another_job,
            apply=True,
            actor="operator@example.test",
            trusted_runner=_trusted_runner(job_id="job-2"),
        )
    assert resolve_workspace_app_runtime(workspace, db=db_session).rollout_phase == "probation"
