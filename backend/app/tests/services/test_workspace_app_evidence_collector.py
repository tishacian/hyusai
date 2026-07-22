"""Hostile contracts for the two-phase Lot-9 evidence collector."""

from __future__ import annotations

import copy
import hashlib
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.core.config import settings
from app.models.workspace import Workspace
from app.models.workspace_app import WorkspaceAppInstallation
from app.services.workspace_app_manifests import (
    BUILTIN_WORKSPACE_APP_MANIFESTS,
    validate_manifest_configuration,
)
from scripts import collect_workspace_app_evidence as collector
from scripts import rollout_workspace_app_platform as rollout

REVISION = "f" * 40


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


def _seed(db, *, marked: bool = True) -> Workspace:
    workspace = Workspace(
        id=str(uuid4()),
        name="Opaque Lot 9 evidence target",
        slug=f"opaque-{uuid4().hex[:8]}",
        settings={
            "family": "andritz",
            "features": {rollout.WORKSPACE_APP_PLATFORM_FEATURE: False},
            "experience": (
                {rollout.CANARY_MARKER: rollout.CANARY_MARKER_VALUE} if marked else {}
            ),
        },
    )
    manifest = BUILTIN_WORKSPACE_APP_MANIFESTS[("andritz.chat", "1.0.0")]
    db.add(workspace)
    db.flush()
    db.add(
        WorkspaceAppInstallation(
            id=str(uuid4()),
            workspace_id=workspace.id,
            app_id=manifest.app_id,
            version=manifest.version,
            manifest_digest=manifest.digest,
            state="installed",
            configuration=validate_manifest_configuration(manifest, None),
            revision=1,
            installed_at=datetime.utcnow(),
            updated_by="collector-test",
        )
    )
    db.commit()
    return workspace


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _junit(phase: str) -> bytes:
    name = (
        collector.PREFLIGHT_CANARY_TEST_NAME
        if phase == "preflight"
        else collector.POSTACTIVATION_CANARY_TEST_NAME
    )
    return (
        '<testsuite tests="1" failures="0" errors="0" skipped="0">'
        f'<testcase classname="lot9" name="{name}"/>'
        "</testsuite>"
    ).encode()


def _observation(db, workspace: Workspace, *, phase: str) -> dict:
    if phase == "preflight":
        runtime = rollout.inspect_authoritative_workspace_app_runtime(workspace, db=db)
        kind = collector.PREFLIGHT_OBSERVATION_KIND
        checks = rollout.PREFLIGHT_CHECKS
        probation_ref = None
    else:
        runtime = rollout.resolve_workspace_app_runtime(workspace, db=db)
        kind = collector.POSTACTIVATION_OBSERVATION_KIND
        checks = rollout.POSTACTIVATION_CHECKS
        probation_ref = runtime.rollout_ref
    target = {
        "workspace_sha256": _digest(workspace.id),
        "installations_sha256": rollout.workspace_app_installations_sha256(runtime),
    }
    if probation_ref is not None:
        target["probation_ref"] = probation_ref
    return {
        "schema_version": 1,
        "kind": kind,
        "tested_revision": REVISION,
        "generated_at": datetime.now(UTC).isoformat(),
        "runner": {
            "protected_ci": True,
            "pipeline_id": "pipeline-1",
            "job_id": "job-1",
        },
        "target": target,
        "checks": {name: True for name in checks},
        "diagnostics": (
            {
                "source": "playwright",
                "declared_entitlement_count": 1,
                "entitlement_gate": True,
            }
            if phase == "postactivation"
            else {"source": "playwright"}
        ),
    }


def _collect(db, workspace: Workspace, *, phase: str, mode: str = "protected") -> dict:
    return collector.collect_evidence(
        db,
        phase=phase,
        workspace_id=workspace.id,
        observation=_observation(db, workspace, phase=phase),
        playwright_junit=_junit(phase),
        mode=mode,
        validated_by="protected-runner",
        trusted_runner=_trusted_runner() if mode == "protected" else None,
    )


def test_preflight_collection_is_directly_consumable_by_stage(db_session) -> None:
    workspace = _seed(db_session)
    evidence = _collect(db_session, workspace, phase="preflight")

    assert evidence["kind"] == rollout.PREFLIGHT_EVIDENCE_KIND
    assert evidence["activation_grade"] is True
    assert evidence["trusted_runner"] == _trusted_runner()
    assert evidence["source_junit"]["sha256"] == hashlib.sha256(
        _junit("preflight")
    ).hexdigest()
    staged = rollout.stage(
        db_session,
        workspace_id=workspace.id,
        evidence=evidence,
        apply=True,
        actor="operator@example.test",
        trusted_runner=_trusted_runner(),
    )
    assert staged["probation_ref"].startswith("sha256:")


def test_post_collection_is_bound_to_live_probation_and_finalizes(db_session) -> None:
    workspace = _seed(db_session)
    preflight = _collect(db_session, workspace, phase="preflight")
    staged = rollout.stage(
        db_session,
        workspace_id=workspace.id,
        evidence=preflight,
        apply=True,
        actor="operator@example.test",
        trusted_runner=_trusted_runner(),
    )
    post = _collect(db_session, workspace, phase="postactivation")

    assert post["subject"]["probation_ref"] == staged["probation_ref"]
    finalized = rollout.finalize(
        db_session,
        workspace_id=workspace.id,
        evidence=post,
        apply=True,
        actor="operator@example.test",
        trusted_runner=_trusted_runner(),
    )
    assert finalized["changed"] is True


def test_wrong_workspace_hash_and_cross_tenant_target_are_rejected(db_session) -> None:
    workspace = _seed(db_session)
    other = _seed(db_session, marked=False)
    observation = _observation(db_session, workspace, phase="preflight")
    observation["target"]["workspace_sha256"] = _digest(other.id)

    with pytest.raises(rollout.WorkspaceAppRolloutError, match="differs"):
        collector.collect_evidence(
            db_session,
            phase="preflight",
            workspace_id=workspace.id,
            observation=observation,
            playwright_junit=_junit("preflight"),
            mode="protected",
            validated_by="protected-runner",
        )
    with pytest.raises(rollout.WorkspaceAppRolloutError, match="unique structurally marked"):
        collector.collect_evidence(
            db_session,
            phase="preflight",
            workspace_id=other.id,
            observation=_observation(db_session, other, phase="preflight"),
            playwright_junit=_junit("preflight"),
            mode="protected",
            validated_by="protected-runner",
        )


def test_wrong_junit_or_phase_specific_checks_are_rejected(db_session) -> None:
    workspace = _seed(db_session)
    with pytest.raises(rollout.WorkspaceAppRolloutError, match="phase-specific"):
        collector.collect_evidence(
            db_session,
            phase="preflight",
            workspace_id=workspace.id,
            observation=_observation(db_session, workspace, phase="preflight"),
            playwright_junit=_junit("postactivation"),
            mode="protected",
            validated_by="protected-runner",
        )


def test_postactivation_cannot_claim_entry_gate_without_exercising_an_entitlement(
    db_session,
) -> None:
    workspace = _seed(db_session)
    preflight = _collect(db_session, workspace, phase="preflight")
    rollout.stage(
        db_session,
        workspace_id=workspace.id,
        evidence=preflight,
        apply=True,
        actor="operator@example.test",
        trusted_runner=_trusted_runner(),
    )
    observation = _observation(db_session, workspace, phase="postactivation")
    observation["diagnostics"].update(
        {"declared_entitlement_count": 0, "entitlement_gate": "not_declared"}
    )

    with pytest.raises(
        rollout.WorkspaceAppRolloutError,
        match="declared and exercised entitlement",
    ):
        collector.collect_evidence(
            db_session,
            phase="postactivation",
            workspace_id=workspace.id,
            observation=observation,
            playwright_junit=_junit("postactivation"),
            mode="protected",
            validated_by="protected-runner",
            trusted_runner=_trusted_runner(),
        )
    observation = _observation(db_session, workspace, phase="preflight")
    observation["checks"][rollout.PREFLIGHT_CHECKS[0]] = False
    with pytest.raises(rollout.WorkspaceAppRolloutError, match="must pass"):
        collector.collect_evidence(
            db_session,
            phase="preflight",
            workspace_id=workspace.id,
            observation=observation,
            playwright_junit=_junit("preflight"),
            mode="protected",
            validated_by="protected-runner",
        )


def test_local_collection_is_explicitly_non_promotable(db_session) -> None:
    workspace = _seed(db_session)
    observation = _observation(db_session, workspace, phase="preflight")
    observation["runner"] = {
        "protected_ci": False,
        "pipeline_id": None,
        "job_id": None,
    }
    result = collector.collect_evidence(
        db_session,
        phase="preflight",
        workspace_id=workspace.id,
        observation=observation,
        playwright_junit=_junit("preflight"),
        mode="local",
        validated_by="",
    )
    assert result["status"] == "non_promotable"
    assert "workspace_id" not in result


def test_post_observation_from_another_or_expired_probation_is_rejected(db_session) -> None:
    workspace = _seed(db_session)
    preflight = _collect(db_session, workspace, phase="preflight")
    rollout.stage(
        db_session,
        workspace_id=workspace.id,
        evidence=preflight,
        apply=True,
        actor="operator@example.test",
        trusted_runner=_trusted_runner(),
    )
    wrong = _observation(db_session, workspace, phase="postactivation")
    wrong["target"]["probation_ref"] = "sha256:" + "9" * 64
    with pytest.raises(rollout.WorkspaceAppRolloutError, match="different probation"):
        collector.collect_evidence(
            db_session,
            phase="postactivation",
            workspace_id=workspace.id,
            observation=wrong,
            playwright_junit=_junit("postactivation"),
            mode="protected",
            validated_by="protected-runner",
        )

    state = rollout._state(workspace)
    probation = copy.deepcopy(state["probation"])
    probation["staged_at"] = (datetime.now(UTC) - timedelta(minutes=2)).isoformat()
    probation["expires_at"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    probation["probation_sha256"] = rollout._probation_digest(probation)
    probation["probation_ref"] = f"sha256:{probation['probation_sha256']}"
    state["probation"] = probation
    rollout._save_state(workspace, state)
    db_session.commit()
    with pytest.raises(rollout.WorkspaceAppRolloutError, match="expired"):
        collector.collect_evidence(
            db_session,
            phase="postactivation",
            workspace_id=workspace.id,
            observation=wrong,
            playwright_junit=_junit("postactivation"),
            mode="protected",
            validated_by="protected-runner",
        )
