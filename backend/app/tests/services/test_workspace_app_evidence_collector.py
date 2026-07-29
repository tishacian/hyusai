"""Hostile contracts for the two-phase Lot-9 evidence collector."""

from __future__ import annotations

import copy
import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.core.config import settings
from app.models.audit import AuditLog
from app.models.workspace import Workspace
from app.models.workspace_app import WorkspaceAppInstallation, WorkspaceAppOperation
from app.services.actions.registry import all_action_manifests, effective_action_manifests
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


def _seed(
    db,
    *,
    marked: bool = True,
    family: str = "andritz",
    app_id: str = "andritz.chat",
    version: str = "1.0.0",
) -> Workspace:
    workspace = Workspace(
        id=str(uuid4()),
        name="Opaque Lot 9 evidence target",
        slug=f"opaque-{uuid4().hex[:8]}",
        settings={
            "family": family,
            "features": {rollout.WORKSPACE_APP_PLATFORM_FEATURE: False},
            "experience": ({rollout.CANARY_MARKER: rollout.CANARY_MARKER_VALUE} if marked else {}),
        },
    )
    manifest = BUILTIN_WORKSPACE_APP_MANIFESTS[(app_id, version)]
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


def _preflight_semantic_diagnostics(db, workspace: Workspace, runtime) -> dict:
    installation = (
        db.query(WorkspaceAppInstallation)
        .filter(
            WorkspaceAppInstallation.workspace_id == workspace.id,
            WorkspaceAppInstallation.state == "installed",
        )
        .one()
    )
    proofs = []
    replay_ref = ""
    for index, operation in enumerate(("install", "upgrade", "rollback", "uninstall"), 1):
        digest_chars = (str(index), str(index + 4), "89ab"[index - 1])
        row = WorkspaceAppOperation(
            id=str(uuid4()),
            workspace_id=workspace.id,
            installation_id=installation.id,
            app_id=installation.app_id,
            idempotency_key=f"collector-{operation}-{uuid4()}",
            request_sha256=digest_chars[0] * 64,
            operation=operation,
            from_version=installation.version,
            to_version=installation.version,
            manifest_digest=installation.manifest_digest,
            plan_sha256=digest_chars[1] * 64,
            lifecycle_phase="normal",
            steps_sha256=digest_chars[2] * 64,
            compensation={},
            before_state={},
            after_state={},
            actor="canary@example.test",
            created_at=datetime.utcnow(),
        )
        db.add(row)
        operation_ref = _digest(row.id)
        proofs.append(
            {
                "operation": operation,
                "operation_id_sha256": operation_ref,
                "plan_sha256": row.plan_sha256,
                "manifest_digest": row.manifest_digest,
            }
        )
        if operation == "install":
            replay_ref = operation_ref
    db.commit()
    entry_policy, declared_count = rollout.workspace_app_canary_entry_policy(runtime)
    return {
        "source": "playwright",
        "exact_initial_ledger_restored": True,
        "exact_initial_reinstalled": True,
        "restored_runtime_shell": runtime.shell,
        "restored_entry_policy": entry_policy,
        "restored_declared_entitlement_count": declared_count,
        "ledger_sha256": collector._workspace_app_ledger_sha256(db, workspace),
        "exercised_manifest_digests": [installation.manifest_digest],
        "lifecycle_operation_proofs": proofs,
        "idempotent_replay_proof": {
            "operation_id_sha256": replay_ref,
            "replayed_operation_id_sha256": replay_ref,
            "idempotent_replay": True,
        },
        "restored_manifest_digest": installation.manifest_digest,
        "final_installed_count": len(runtime.installations),
    }


def _postactivation_semantic_diagnostics(db, workspace: Workspace, runtime) -> dict:
    actions = effective_action_manifests(workspace, surface="chat")
    action_pack_executions = []
    for pack in runtime.action_packs:
        candidates = sorted(
            (
                item
                for item in actions
                if item.pack == pack
                and item.handler.kind != "legacy_adapter"
                and not item.requires_confirmation
                and item.direct_safe
            ),
            key=lambda item: item.action_id,
        )
        manifest = candidates[0]
        audit = AuditLog(
            id=str(uuid4()),
            workspace_id=workspace.id,
            timestamp=datetime.utcnow(),
            event_type=manifest.audit_event,
            actor="canary@example.test",
            details={
                "action_id": manifest.action_id,
                "payload": {"canary_probe_ref": "sha256:" + "a" * 64},
                "surface": "chat",
            },
        )
        db.add(audit)
        action_pack_executions.append(
            {
                "pack": pack,
                "action_id": manifest.action_id,
                "audit_id": audit.id,
                "http_status": 200,
                "matched": True,
                "reason": "proposed",
                "response_action_id": manifest.action_id,
                "result_action": manifest.action_id,
                "applied": False,
                "requires_confirmation": False,
            }
        )

    target_packs = set(runtime.action_packs)
    if "andritz_industrial_v1" in target_packs:
        alternate = _seed(
            db,
            marked=False,
            family="generic",
            app_id="mission-room.extension",
            version="1.2.0",
        )
    else:
        alternate = _seed(db, marked=False)
    alternate_runtime = rollout.inspect_authoritative_workspace_app_runtime(
        alternate,
        db=db,
    )
    foreign = next(
        manifest
        for manifest in all_action_manifests()
        if manifest.pack in set(alternate_runtime.action_packs)
        and manifest.pack not in target_packs
    )
    denied_audit = AuditLog(
        id=str(uuid4()),
        workspace_id=workspace.id,
        timestamp=datetime.utcnow(),
        event_type="action.denied",
        actor="canary@example.test",
        details={
            "action_id": foreign.action_id,
            "surface": "chat",
            "reason": "not_visible",
        },
    )
    db.add(denied_audit)
    db.commit()
    source_installation = runtime.installations[0]
    target_installation = alternate_runtime.installations[0]
    source_route = collector._route_path(source_installation.payload["experience"]["default_route"])
    target_route = collector._route_path(target_installation.payload["experience"]["default_route"])
    source_surface = source_installation.payload["experience"]["primary_surface_id"]
    target_surface = target_installation.payload["experience"]["primary_surface_id"]
    assert (source_route, source_surface) != (target_route, target_surface)
    return {
        "action_pack_executions": action_pack_executions,
        "foreign_action_denial": {
            "pack": foreign.pack,
            "action_id": foreign.action_id,
            "audit_id": denied_audit.id,
            "http_status": 200,
            "matched": False,
            "reason": "not_visible",
        },
        "workspace_switch": {
            "from_workspace_sha256": _digest(workspace.id),
            "to_workspace_sha256": _digest(alternate.id),
            "from_runtime_identity_sha256": collector._runtime_identity_sha256(workspace, runtime),
            "to_runtime_identity_sha256": collector._runtime_identity_sha256(
                alternate, alternate_runtime
            ),
            "from_route_sha256": _digest(source_route),
            "to_route_sha256": _digest(target_route),
            "from_primary_surface_sha256": _digest(source_surface),
            "to_primary_surface_sha256": _digest(target_surface),
            "from_header_sha256": _digest(workspace.slug),
            "to_header_sha256": _digest(alternate.slug),
            "observed_request_paths_sha256": "b" * 64,
            "cache_revalidation_path_sha256": _digest(f"/api/v1/auth/workspaces/{alternate.slug}"),
            "observed_request_count": 3,
            "new_header_request_count": 3,
            "old_header_after_new_count": 0,
            "cache_revalidation": "network_no_store",
        },
    }


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
    entry_policy = None
    declared_entitlement_count = None
    entitlement_gate: bool | str | None = None
    if phase == "postactivation":
        entry_policy, declared_entitlement_count = rollout.workspace_app_canary_entry_policy(
            runtime
        )
        entitlement_gate = True if entry_policy == "business_entitlement" else "not_applicable"
    diagnostics = (
        {
            "source": "playwright",
            "runtime_shell": runtime.shell,
            "entry_policy": entry_policy,
            "shell_entry_boundary": True,
            "declared_entitlement_count": declared_entitlement_count,
            "entitlement_gate": entitlement_gate,
            **_postactivation_semantic_diagnostics(db, workspace, runtime),
        }
        if phase == "postactivation"
        else _preflight_semantic_diagnostics(db, workspace, runtime)
    )
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
        "diagnostics": diagnostics,
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
    assert evidence["source_junit"]["sha256"] == hashlib.sha256(_junit("preflight")).hexdigest()
    staged = rollout.stage(
        db_session,
        workspace_id=workspace.id,
        evidence=evidence,
        apply=True,
        actor="operator@example.test",
        trusted_runner=_trusted_runner(),
    )
    assert staged["probation_ref"].startswith("sha256:")


def test_preflight_rejects_boolean_only_observations(db_session) -> None:
    workspace = _seed(db_session)
    observation = _observation(db_session, workspace, phase="preflight")
    observation["diagnostics"] = {
        "source": "playwright",
        "exact_initial_ledger_restored": True,
        "exact_initial_reinstalled": True,
    }
    with pytest.raises(
        rollout.WorkspaceAppRolloutError,
        match="lifecycle_operation_proofs must be a nonempty array",
    ):
        collector.collect_evidence(
            db_session,
            phase="preflight",
            workspace_id=workspace.id,
            observation=observation,
            playwright_junit=_junit("preflight"),
            mode="protected",
            validated_by="protected-runner",
            trusted_runner=_trusted_runner(),
        )


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
    assert post["subject"]["runtime_shell"] == "business"
    assert post["subject"]["entry_policy"] == "business_entitlement"
    finalized = rollout.finalize(
        db_session,
        workspace_id=workspace.id,
        evidence=post,
        apply=True,
        actor="operator@example.test",
        trusted_runner=_trusted_runner(),
    )
    assert finalized["changed"] is True


def test_postactivation_rejects_boolean_only_observations(db_session) -> None:
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
    observation["diagnostics"] = {
        "source": "playwright",
        "runtime_shell": "business",
        "entry_policy": "business_entitlement",
        "shell_entry_boundary": True,
        "declared_entitlement_count": 1,
        "entitlement_gate": True,
        "action_pack_isolation": True,
        "workspace_epoch_purge": True,
    }

    with pytest.raises(
        rollout.WorkspaceAppRolloutError,
        match="action_pack_executions must be a nonempty array",
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


def test_postactivation_rejects_forged_action_or_workspace_switch_proof(
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
    forged_action = _observation(db_session, workspace, phase="postactivation")
    forged_action["diagnostics"]["action_pack_executions"][0]["audit_id"] = str(uuid4())
    with pytest.raises(
        rollout.WorkspaceAppRolloutError,
        match="does not resolve to an audit",
    ):
        collector.collect_evidence(
            db_session,
            phase="postactivation",
            workspace_id=workspace.id,
            observation=forged_action,
            playwright_junit=_junit("postactivation"),
            mode="protected",
            validated_by="protected-runner",
            trusted_runner=_trusted_runner(),
        )

    stale_header = _observation(db_session, workspace, phase="postactivation")
    stale_header["diagnostics"]["workspace_switch"]["old_header_after_new_count"] = 1
    with pytest.raises(
        rollout.WorkspaceAppRolloutError,
        match="clean post-commit request boundary",
    ):
        collector.collect_evidence(
            db_session,
            phase="postactivation",
            workspace_id=workspace.id,
            observation=stale_header,
            playwright_junit=_junit("postactivation"),
            mode="protected",
            validated_by="protected-runner",
            trusted_runner=_trusted_runner(),
        )


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
    observation["diagnostics"].update({"entitlement_gate": "not_applicable"})

    with pytest.raises(
        rollout.WorkspaceAppRolloutError,
        match="business entry proof must exercise",
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


def test_postactivation_accepts_an_entitlement_free_immersive_boundary(
    db_session,
) -> None:
    workspace = _seed(
        db_session,
        family="generic",
        app_id="mission-room.extension",
        version="1.2.0",
    )
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
    assert {
        key: observation["diagnostics"][key]
        for key in (
            "source",
            "runtime_shell",
            "entry_policy",
            "shell_entry_boundary",
            "declared_entitlement_count",
            "entitlement_gate",
        )
    } == {
        "source": "playwright",
        "runtime_shell": "immersive",
        "entry_policy": "immersive_extension",
        "shell_entry_boundary": True,
        "declared_entitlement_count": 0,
        "entitlement_gate": "not_applicable",
    }
    assert observation["diagnostics"]["action_pack_executions"]
    assert observation["diagnostics"]["foreign_action_denial"]["matched"] is False
    assert observation["diagnostics"]["workspace_switch"]["old_header_after_new_count"] == 0
    evidence = collector.collect_evidence(
        db_session,
        phase="postactivation",
        workspace_id=workspace.id,
        observation=observation,
        playwright_junit=_junit("postactivation"),
        mode="protected",
        validated_by="protected-runner",
        trusted_runner=_trusted_runner(),
    )
    assert evidence["subject"]["runtime_shell"] == "immersive"
    assert evidence["subject"]["entry_policy"] == "immersive_extension"
    assert evidence["subject"]["declared_entitlement_count"] == 0
    finalized = rollout.finalize(
        db_session,
        workspace_id=workspace.id,
        evidence=evidence,
        apply=False,
        actor="",
    )
    assert finalized["operation"] == "finalize"


def test_postactivation_rejects_a_shell_or_entry_policy_claim_mismatch(
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
        {
            "runtime_shell": "immersive",
            "entry_policy": "immersive_extension",
            "declared_entitlement_count": 0,
            "entitlement_gate": "not_applicable",
        }
    )
    with pytest.raises(
        rollout.WorkspaceAppRolloutError,
        match="differs from the installed runtime shell",
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

    observation = _observation(db_session, workspace, phase="postactivation")
    observation["diagnostics"]["declared_entitlement_count"] = True
    with pytest.raises(
        rollout.WorkspaceAppRolloutError,
        match="differs from the installed runtime shell",
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


def test_immersive_observation_cannot_fabricate_an_entitlement_gate(db_session) -> None:
    workspace = _seed(
        db_session,
        family="generic",
        app_id="mission-room.extension",
        version="1.2.0",
    )
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
    observation["diagnostics"]["entitlement_gate"] = True
    with pytest.raises(
        rollout.WorkspaceAppRolloutError,
        match="must not fabricate an entitlement gate",
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


def test_immersive_runtime_with_an_unenforced_entitlement_fails_closed(
    db_session,
) -> None:
    workspace = _seed(
        db_session,
        family="generic",
        app_id="mission-room.extension",
        version="1.2.0",
    )
    runtime = rollout.inspect_authoritative_workspace_app_runtime(
        workspace,
        db=db_session,
    )
    installation = runtime.installations[0]
    forged_payload = copy.deepcopy(installation.payload)
    forged_payload["entitlement_keys"] = [forged_payload["experience"]["primary_surface_id"]]
    forged_runtime = replace(
        runtime,
        installations=(replace(installation, payload=forged_payload),),
    )

    with pytest.raises(
        rollout.WorkspaceAppRolloutError,
        match="resolver cannot enforce",
    ):
        rollout.workspace_app_canary_entry_policy(forged_runtime)


def test_collector_uses_the_rollout_entry_policy_as_its_only_authority(
    db_session,
    monkeypatch,
) -> None:
    workspace = _seed(db_session)
    runtime = rollout.inspect_authoritative_workspace_app_runtime(
        workspace,
        db=db_session,
    )
    calls: list[object] = []

    def authoritative_policy(candidate):
        calls.append(candidate)
        return "business_entitlement", 1

    monkeypatch.setattr(
        rollout,
        "workspace_app_canary_entry_policy",
        authoritative_policy,
    )
    assert (
        collector._validate_postactivation_entry_policy(
            {
                "diagnostics": {
                    "runtime_shell": "business",
                    "entry_policy": "business_entitlement",
                    "shell_entry_boundary": True,
                    "declared_entitlement_count": 1,
                    "entitlement_gate": True,
                }
            },
            runtime=runtime,
        )
        == "business_entitlement"
    )
    assert calls == [runtime]


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
