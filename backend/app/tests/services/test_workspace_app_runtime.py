"""Workspace App installation authority at runtime."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi import HTTPException, Request

from app.core.config import settings
from app.core.iam.dependencies import require_app_entitlement
from app.extensions.registry import MISSION_ROOM_EXTENSION_ID, require_workspace_extension
from app.models.audit import AuditLog
from app.models.system import System
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.models.workspace_app import WorkspaceAppInstallation
from app.services import workspace_app_manifests, workspace_app_runtime
from app.services.actions.registry import catalog_action_manifests, effective_action_manifests
from app.services.iam.app_entitlements import (
    list_member_app_entitlements,
    replace_member_app_entitlements,
)
from app.services.workspace_app_manifests import (
    BUILTIN_WORKSPACE_APP_MANIFESTS,
    _compile_manifest,
    validate_manifest_configuration,
)
from app.services.workspace_app_runtime import (
    WORKSPACE_APP_PLATFORM_FEATURE,
    WORKSPACE_APP_ROLLOUT_STATE_KEY,
    WorkspaceAppRuntimeError,
    _workspace_app_activation_audit_details,
    inspect_authoritative_workspace_app_runtime,
    installed_app_ids,
    installed_entitlement_keys,
    mission_room_provider_request_allowed,
    resolve_mission_room_provider_runtime,
    resolve_workspace_app_runtime,
    safe_workspace_app_runtime_payload,
    workspace_app_installations_sha256,
)

REVISION = "c" * 40


def _request(path: str) -> Request:
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "https",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": [],
            "client": ("testclient", 50000),
            "server": ("testserver", 443),
        }
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


def _trusted_runner() -> dict[str, object]:
    return {
        "issuer": "https://gitlab.com",
        "project_id": "42",
        "pipeline_id": "runtime-pipeline",
        "job_id": "runtime-job",
        "commit_sha": REVISION,
        "ref": "demo/agentic",
        "ref_protected": True,
    }


def _workspace(
    db,
    *,
    family: str = "generic",
    enabled: bool = True,
    mission_profile: str | None = None,
) -> Workspace:
    settings = {
        "family": family,
        "features": {WORKSPACE_APP_PLATFORM_FEATURE: enabled},
    }
    if mission_profile is not None:
        settings["mission_room"] = {"profile": mission_profile}
    workspace = Workspace(
        id=str(uuid4()),
        slug=f"runtime-{uuid4().hex[:10]}",
        name="Runtime authority",
        settings=settings,
    )
    db.add(workspace)
    db.commit()
    return workspace


def test_runtime_fails_closed_without_relational_integrity_schema(
    db_session,
    monkeypatch,
) -> None:
    workspace = _workspace(db_session, enabled=False)
    monkeypatch.setattr(
        workspace_app_runtime,
        "workspace_app_relational_integrity_errors",
        lambda _db: [
            "foreign_key:workspace_app_operations."
            "fk_workspace_app_operations_installation_lineage"
        ],
    )

    with pytest.raises(WorkspaceAppRuntimeError) as exc:
        inspect_authoritative_workspace_app_runtime(workspace, db=db_session)
    assert exc.value.code == "runtime_schema_unsatisfied"


def _attest(db, workspace: Workspace) -> None:
    runtime = inspect_authoritative_workspace_app_runtime(workspace, db=db)
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    evidence = "1" * 64
    artifact = "2" * 64
    preflight_evidence = "3" * 64
    preflight_artifact = "4" * 64
    probation = "5" * 64
    source_junit = "6" * 64
    preflight_source_junit = "7" * 64
    runner = _trusted_runner()
    actor = "runtime-test"
    activation = {
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
        "preflight_source_junit_ref": f"sha256:{preflight_source_junit}",
        "postactivation_artifact_tests": 4,
        "source_junit_ref": f"sha256:{source_junit}",
        "trusted_runner": runner,
        "probation_ref": f"sha256:{probation}",
        "revision": REVISION,
        "installations_sha256": workspace_app_installations_sha256(runtime),
        "installation_count": len(runtime.installations),
        "activated_at": now,
        "actor": actor,
    }
    audit_id = str(uuid4())
    db.add(
        AuditLog(
            id=audit_id,
            workspace_id=workspace.id,
            event_type="lot9.workspace_app_platform.activated",
            actor=actor,
            severity="info",
            details=_workspace_app_activation_audit_details(
                activation,
                trusted_runner=runner,
            ),
        )
    )
    db.flush()
    activation["audit_id"] = audit_id
    workspace.settings = {
        **workspace.settings,
        WORKSPACE_APP_ROLLOUT_STATE_KEY: {
            "schema_version": 1,
            "activations": [activation],
            "deactivations": [],
        },
    }
    db.commit()


def _install(
    db,
    workspace: Workspace,
    app_id: str,
    version: str,
    *,
    attest: bool = True,
) -> WorkspaceAppInstallation:
    manifest = BUILTIN_WORKSPACE_APP_MANIFESTS[(app_id, version)]
    installation = WorkspaceAppInstallation(
        id=str(uuid4()),
        workspace_id=workspace.id,
        app_id=app_id,
        version=version,
        manifest_digest=manifest.digest,
        state="installed",
        configuration=validate_manifest_configuration(manifest, None),
        revision=1,
        installed_at=datetime.utcnow(),
        updated_by="runtime-test",
    )
    db.add(installation)
    db.commit()
    if attest and workspace_app_runtime.workspace_app_platform_enabled(workspace):
        _attest(db, workspace)
    return installation


def _boundary_manifest(*, app_id: str, api_prefix: str):
    payload = deepcopy(
        BUILTIN_WORKSPACE_APP_MANIFESTS[("andritz.client360-pdr", "1.0.0")].as_dict()
    )
    route = "/authority-probe"
    payload.update(
        {
            "app_id": app_id,
            "display_name": "Authority Probe",
            "routes": [route],
            "api_prefixes": [api_prefix],
            "conflict_group": None,
        }
    )
    payload["surfaces"] = [
        {
            "id": f"{app_id}.surface.1",
            "route": route,
            "api_prefix": api_prefix,
        }
    ]
    payload["experience"] = {
        **payload["experience"],
        "primary_surface_id": f"{app_id}.surface.1",
        "default_route": route,
    }
    return _compile_manifest(payload)


def test_gate_off_does_not_query_or_change_the_historical_runtime() -> None:
    workspace = Workspace(
        id="detached-legacy-workspace",
        slug="detached-legacy-workspace",
        name="Detached legacy workspace",
        settings={
            "family": "sentinel_ci",
            "features": {WORKSPACE_APP_PLATFORM_FEATURE: False},
        },
    )

    runtime = resolve_workspace_app_runtime(workspace)

    assert runtime.mode == "legacy"
    assert runtime.enabled is False
    assert runtime.installations == ()
    assert runtime.shell == "legacy"


def test_authoritative_runtime_is_content_addressed_and_secret_free(db_session) -> None:
    workspace = _workspace(
        db_session,
        family="sentinel_ci",
        mission_profile="sentinel_government_v1",
    )
    manifest = BUILTIN_WORKSPACE_APP_MANIFESTS[("sentinel.mission-room", "1.0.0")]
    _install(db_session, workspace, manifest.app_id, manifest.version)

    runtime = resolve_workspace_app_runtime(workspace, db=db_session)
    public = runtime.as_public_payload()

    assert runtime.app_ids == ("sentinel.mission-room",)
    assert runtime.shell == "immersive"
    assert runtime.mission_room is not None
    assert runtime.mission_room["app_id"] == "sentinel.mission-room"
    assert runtime.mission_room["assistant_profile"] == "vigie_executive"
    assert "octocity" not in str(public).lower()
    assert public["installations"][0]["manifest_digest"] == manifest.digest
    assert public["installations"][0]["api_prefixes"] == ["/api/v1/mission-room"]
    assert public["experience"]["api_prefixes"] == ["/api/v1/mission-room"]
    assert "configuration" not in public["installations"][0]


def test_generic_mission_room_resolves_only_declared_configuration_sources(db_session) -> None:
    workspace = _workspace(db_session)
    row = _install(db_session, workspace, "mission-room.extension", "1.1.0")
    row.configuration = {
        "profile": "board-room",
        "assistant_profile": "facilitator",
        "decision_surfaces": True,
    }
    db_session.commit()

    with pytest.raises(WorkspaceAppRuntimeError) as stale:
        resolve_workspace_app_runtime(workspace, db=db_session)
    assert stale.value.code == "rollout_attestation_stale"

    _attest(db_session, workspace)
    runtime = resolve_workspace_app_runtime(workspace, db=db_session)

    assert runtime.mission_room is not None
    assert runtime.mission_room["profile"] == "board-room"
    assert runtime.mission_room["assistant_profile"] == "facilitator"
    assert "profile_source" not in runtime.mission_room


def test_generic_mission_room_provider_requires_the_exact_versioned_contract(
    db_session,
) -> None:
    providerless = _workspace(db_session)
    _install(db_session, providerless, "mission-room.extension", "1.1.0")

    with pytest.raises(WorkspaceAppRuntimeError) as unavailable:
        resolve_mission_room_provider_runtime(providerless, db=db_session)
    assert unavailable.value.code == "mission_room_provider_unavailable"

    workspace = _workspace(db_session)
    _install(db_session, workspace, "mission-room.extension", "1.2.0")
    runtime = resolve_mission_room_provider_runtime(workspace, db=db_session)

    assert runtime.mission_room is not None
    assert runtime.mission_room["provider_kind"] == "workspace_objects_v1"
    assert mission_room_provider_request_allowed(
        runtime,
        "GET",
        "/api/v1/mission-room/overview",
    )
    assert mission_room_provider_request_allowed(
        runtime,
        "POST",
        "/api/v1/mission-room/actions/draft",
    )
    assert not mission_room_provider_request_allowed(
        runtime,
        "GET",
        "/api/v1/mission-room/actions/draft",
    )
    assert not mission_room_provider_request_allowed(
        runtime,
        "GET",
        "/api/v1/mission-room/security-monitor",
    )
    assert not mission_room_provider_request_allowed(
        runtime,
        "GET",
        "/api/v1/mission-room/maritime/snapshot",
    )
    assert not mission_room_provider_request_allowed(
        runtime,
        "GET",
        "/api/v1/mission-room/webcams/sources",
    )


def test_tampered_manifest_digest_fails_closed_without_row_disclosure(db_session) -> None:
    workspace = _workspace(db_session, family="andritz")
    row = _install(db_session, workspace, "andritz.chat", "1.0.0")
    row.manifest_digest = "0" * 64
    db_session.commit()

    with pytest.raises(WorkspaceAppRuntimeError) as caught:
        installed_app_ids(workspace, db=db_session)
    assert caught.value.code == "manifest_untrusted"

    public = safe_workspace_app_runtime_payload(workspace, db=db_session)
    assert public == {
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


def test_overlapping_installed_api_authorities_fail_closed_without_mutation(
    db_session,
    monkeypatch,
) -> None:
    workspace = _workspace(db_session, family="andritz")
    chat = _install(
        db_session,
        workspace,
        "andritz.chat",
        "1.0.0",
        attest=False,
    )
    child = _boundary_manifest(
        app_id="andritz.chat-authority-child",
        api_prefix="/api/v1/chat/admin",
    )
    child_row = WorkspaceAppInstallation(
        id=str(uuid4()),
        workspace_id=workspace.id,
        app_id=child.app_id,
        version=child.version,
        manifest_digest=child.digest,
        state="installed",
        configuration=validate_manifest_configuration(child, None),
        revision=1,
        installed_at=datetime.utcnow(),
        updated_by="runtime-test",
    )
    db_session.add(child_row)
    db_session.commit()
    monkeypatch.setattr(
        workspace_app_manifests,
        "BUILTIN_WORKSPACE_APP_MANIFESTS",
        {
            **BUILTIN_WORKSPACE_APP_MANIFESTS,
            (child.app_id, child.version): child,
        },
    )
    monkeypatch.setattr(
        workspace_app_runtime,
        "get_builtin_workspace_app_manifest",
        workspace_app_manifests.get_builtin_workspace_app_manifest,
    )
    before = {
        "rows": [
            (row.id, row.app_id, row.version, row.revision)
            for row in db_session.query(WorkspaceAppInstallation)
            .filter(WorkspaceAppInstallation.workspace_id == workspace.id)
            .order_by(WorkspaceAppInstallation.app_id.asc())
            .all()
        ],
        "audits": db_session.query(AuditLog).count(),
    }

    with pytest.raises(WorkspaceAppRuntimeError) as caught:
        inspect_authoritative_workspace_app_runtime(workspace, db=db_session)
    assert caught.value.code == "api_prefix_conflict"
    assert safe_workspace_app_runtime_payload(workspace, db=db_session) == {
        "schema_version": 1,
        "mode": "authoritative",
        "enabled": True,
        "rollout_phase": "invalid",
        "rollout_ref": None,
        "valid": False,
        "error_code": "api_prefix_conflict",
        "installations": [],
        "experience": None,
    }
    assert {
        "rows": [
            (row.id, row.app_id, row.version, row.revision)
            for row in db_session.query(WorkspaceAppInstallation)
            .filter(WorkspaceAppInstallation.workspace_id == workspace.id)
            .order_by(WorkspaceAppInstallation.app_id.asc())
            .all()
        ],
        "audits": db_session.query(AuditLog).count(),
    } == before
    assert chat.state == child_row.state == "installed"


def test_installed_action_packs_ignore_legacy_cross_profile_overrides(db_session) -> None:
    workspace = _workspace(
        db_session,
        family="sentinel_ci",
        mission_profile="sentinel_government_v1",
    )
    workspace.settings = {
        **workspace.settings,
        "actions": {
            "enabled_packs": ["octave_mission_room_v1", "octave_security_v1"],
            "enabled_actions": ["octave.priority_summary"],
        },
        "assistant_profile_default": "octave_executive",
    }
    _install(db_session, workspace, "sentinel.mission-room", "1.0.0")
    db_session.commit()
    cross_profile_system = System(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name="Cross-profile legacy override",
        execution_profile={
            "actions": {"enabled_packs": ["octave_mission_room_v1", "octave_security_v1"]}
        },
    )

    effective_ids = {
        item.action_id
        for item in effective_action_manifests(
            workspace,
            surface="chat",
            system=cross_profile_system,
        )
    }
    catalog_ids = {item.action_id for item in catalog_action_manifests(workspace)}

    assert "aya.priority_summary" in effective_ids
    assert "octave.priority_summary" not in effective_ids
    assert "octave.priority_summary" not in catalog_ids


def test_business_and_extension_entry_gates_require_an_installed_app(db_session) -> None:
    business = _workspace(db_session, family="andritz")
    business_gate = require_app_entitlement("chat")
    user = User(
        id=str(uuid4()),
        username="runtime-entry-user",
        email="runtime-entry@example.test",
    )

    with pytest.raises(HTTPException) as missing_business:
        asyncio.run(
            business_gate(
                request=_request("/api/v1/chat"),
                user=user,
                workspace=business,
                db=db_session,
            )
        )
    assert missing_business.value.status_code == 404
    assert missing_business.value.detail == {"code": "WORKSPACE_APP_NOT_FOUND"}

    _install(db_session, business, "andritz.chat", "1.0.0")
    db_session.add(user)
    db_session.flush()
    membership = WorkspaceMember(
        workspace_id=business.id,
        user_id=user.id,
        role="member",
    )
    db_session.add(membership)
    db_session.flush()
    replace_member_app_entitlements(
        db_session,
        membership,
        ["chat"],
        granted_by_user_id=None,
    )
    db_session.commit()
    allowed = asyncio.run(
        business_gate(
            request=_request("/api/v1/chat/completions"),
            user=user,
            workspace=business,
            db=db_session,
        )
    )
    assert allowed.granted is True
    assert allowed.enforced is True
    sessions_allowed = asyncio.run(
        business_gate(
            request=_request("/api/v1/sessions"),
            user=user,
            workspace=business,
            db=db_session,
        )
    )
    assert sessions_allowed.granted is True
    runtime = resolve_workspace_app_runtime(business, db=db_session)
    assert runtime.as_public_payload()["installations"][0]["api_prefixes"] == [
        "/api/v1/chat",
        "/api/v1/sessions",
    ]
    with pytest.raises(HTTPException) as wrong_business_prefix:
        asyncio.run(
            business_gate(
                request=_request("/api/v1/client360"),
                user=user,
                workspace=business,
                db=db_session,
            )
        )
    assert wrong_business_prefix.value.status_code == 404

    mission = _workspace(
        db_session,
        family="sentinel_ci",
        mission_profile="sentinel_government_v1",
    )
    extension_gate = require_workspace_extension(MISSION_ROOM_EXTENSION_ID)
    with pytest.raises(HTTPException) as missing_extension:
        extension_gate(
            request=_request("/api/v1/mission-room/overview"),
            workspace=mission,
            db=db_session,
        )
    assert missing_extension.value.status_code == 404

    _install(db_session, mission, "sentinel.mission-room", "1.0.0")
    assert (
        extension_gate(
            request=_request("/api/v1/mission-room/overview"),
            workspace=mission,
            db=db_session,
        )
        is mission
    )

    with pytest.raises(HTTPException) as wrong_prefix:
        extension_gate(
            request=_request("/api/v1/chat"),
            workspace=mission,
            db=db_session,
        )
    assert wrong_prefix.value.status_code == 404


def test_entry_entitlements_are_derived_from_the_installed_manifest(
    db_session,
    monkeypatch,
) -> None:
    workspace = _workspace(db_session, family="andritz")
    payload = BUILTIN_WORKSPACE_APP_MANIFESTS[("andritz.chat", "1.0.0")].as_dict()
    payload.update(
        {
            "app_id": "andritz.future-surface",
            "display_name": "Andritz Future Surface",
            "entitlement_keys": ["future-surface"],
        }
    )
    payload["surfaces"][0]["id"] = "andritz.future-surface.surface.1"
    payload["migrations"].append(
        {
            "executor": "platform_schema_contract_v1",
            "id": "workspace_app_platform.entitlement_registry.070",
            "kind": "platform_schema",
            "phase": "precondition",
            "required": True,
            "reversibility": "persistent_additive_schema",
        }
    )
    future = _compile_manifest(payload)
    db_session.add(
        WorkspaceAppInstallation(
            id=str(uuid4()),
            workspace_id=workspace.id,
            app_id=future.app_id,
            version=future.version,
            manifest_digest=future.digest,
            state="installed",
            configuration=validate_manifest_configuration(future, None),
            revision=1,
            installed_at=datetime.utcnow(),
            updated_by="runtime-test",
        )
    )
    db_session.commit()
    monkeypatch.setattr(
        workspace_app_manifests,
        "BUILTIN_WORKSPACE_APP_MANIFESTS",
        {**BUILTIN_WORKSPACE_APP_MANIFESTS, (future.app_id, future.version): future},
    )
    monkeypatch.setattr(
        workspace_app_runtime,
        "get_builtin_workspace_app_manifest",
        workspace_app_manifests.get_builtin_workspace_app_manifest,
    )
    _attest(db_session, workspace)

    assert installed_entitlement_keys(workspace, db=db_session) == {"future-surface"}
    gate = require_app_entitlement("future-surface")
    user = User(
        id=str(uuid4()),
        username="future-surface-user",
        email="future-surface@example.test",
    )
    db_session.add(user)
    db_session.flush()
    membership = WorkspaceMember(
        workspace_id=workspace.id,
        user_id=user.id,
        role="member",
    )
    db_session.add(membership)
    db_session.flush()
    assert replace_member_app_entitlements(
        db_session,
        membership,
        ["future-surface"],
        granted_by_user_id=None,
    ) == ["future-surface"]
    allowed = asyncio.run(
        gate(
            request=_request("/api/v1/chat/future"),
            user=user,
            workspace=workspace,
            db=db_session,
        )
    )
    assert allowed.granted is True
    assert allowed.enforced is True
    assert list_member_app_entitlements(db_session, membership) == ["future-surface"]

    installation = (
        db_session.query(WorkspaceAppInstallation)
        .filter_by(
            workspace_id=workspace.id,
            app_id=future.app_id,
        )
        .one()
    )
    installation.state = "uninstalled"
    installation.version = None
    installation.manifest_digest = None
    installation.configuration = {}
    db_session.flush()
    assert list_member_app_entitlements(db_session, membership) == []
    with pytest.raises(
        ValueError,
        match="Installed Workspace App entitlement state is invalid",
    ):
        replace_member_app_entitlements(
            db_session,
            membership,
            ["future-surface"],
            granted_by_user_id=None,
        )


def test_family_or_profile_drift_after_install_fails_closed(db_session) -> None:
    workspace = _workspace(
        db_session,
        family="sentinel_ci",
        mission_profile="sentinel_government_v1",
    )
    _install(db_session, workspace, "sentinel.mission-room", "1.0.0")
    assert resolve_workspace_app_runtime(workspace, db=db_session).mode == "authoritative"

    workspace.settings = {
        **workspace.settings,
        "mission_room": {"profile": "octocity_institutional_v1"},
    }
    db_session.commit()
    drifted = safe_workspace_app_runtime_payload(workspace, db=db_session)
    assert drifted["valid"] is False
    assert drifted["error_code"] == "workspace_profile_incompatible"


def test_active_runtime_rechecks_revision_installations_and_rollout_history(
    db_session,
    monkeypatch,
) -> None:
    workspace = _workspace(db_session, family="andritz")
    _install(db_session, workspace, "andritz.chat", "1.0.0")
    assert resolve_workspace_app_runtime(workspace, db=db_session).enabled is True

    _install(
        db_session,
        workspace,
        "andritz.knowledge-capture",
        "1.0.0",
        attest=False,
    )
    stale = safe_workspace_app_runtime_payload(workspace, db=db_session)
    assert stale["valid"] is False
    assert stale["error_code"] == "rollout_attestation_stale"
    assert "andritz" not in str(stale["installations"]).lower()

    _attest(db_session, workspace)
    monkeypatch.setattr(settings, "agentium_image_revision", "d" * 40)
    revision_drift = safe_workspace_app_runtime_payload(workspace, db=db_session)
    assert revision_drift["error_code"] == "runtime_revision_mismatch"

    monkeypatch.setattr(settings, "agentium_image_revision", REVISION)
    state = dict(workspace.settings[WORKSPACE_APP_ROLLOUT_STATE_KEY])
    state["deactivations"] = [
        {
            "deactivated_at": datetime.now(UTC).isoformat(),
            "previous_activation_ref": "sha256:" + "1" * 64,
        }
    ]
    workspace.settings = {**workspace.settings, WORKSPACE_APP_ROLLOUT_STATE_KEY: state}
    db_session.commit()
    invalid_history = safe_workspace_app_runtime_payload(workspace, db=db_session)
    assert invalid_history["error_code"] == "rollout_attestation_invalid"


def test_feature_flag_without_activation_attestation_fails_closed(db_session) -> None:
    workspace = _workspace(db_session, family="andritz", enabled=False)
    _install(db_session, workspace, "andritz.chat", "1.0.0", attest=False)
    workspace.settings = {
        **workspace.settings,
        "features": {WORKSPACE_APP_PLATFORM_FEATURE: True},
    }
    db_session.commit()

    invalid = safe_workspace_app_runtime_payload(workspace, db=db_session)

    assert invalid["valid"] is False
    assert invalid["error_code"] == "rollout_attestation_missing"
