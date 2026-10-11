from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import maritime, mission_room, webcam_proxy
from app.core.config import settings as app_settings
from app.core.iam.roles import WORKSPACE_CONTRIBUTOR
from app.db.base import SessionLocal
from app.extensions.registry import WORKSPACE_EXTENSION_NOT_FOUND_CODE
from app.models.audit import AuditLog
from app.models.calendar import WorkspaceCalendarEvent
from app.models.decision import Decision
from app.models.run import Run
from app.models.system import System
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceIAMConfig, WorkspaceMember
from app.models.workspace_app import WorkspaceAppInstallation
from app.services.mission_room import (
    OCTOCITY_MISSION_ROOM_PROFILE,
    SENTINEL_MISSION_ROOM_PROFILE,
)
from app.services.workspace_app_manifests import (
    BUILTIN_WORKSPACE_APP_MANIFESTS,
    validate_manifest_configuration,
)
from app.services.workspace_app_runtime import (
    WORKSPACE_APP_PLATFORM_FEATURE,
    WORKSPACE_APP_PREFLIGHT_CHECK_COUNT,
    WORKSPACE_APP_PROBATION_MAX_AGE,
    WORKSPACE_APP_ROLLOUT_STATE_KEY,
    _probation_digest,
    _workspace_app_probation_audit_details,
    inspect_authoritative_workspace_app_runtime,
    workspace_app_installation_subject,
    workspace_app_installations_sha256,
)

REVISION = "9" * 40


@pytest.fixture(autouse=True)
def _runtime_revision(monkeypatch):
    monkeypatch.setattr(app_settings, "agentium_image_revision", REVISION)
    monkeypatch.setattr(
        app_settings,
        "authorization_v2_trusted_oidc_issuer",
        "https://gitlab.com",
    )
    monkeypatch.setattr(app_settings, "authorization_v2_trusted_project_id", "42")
    monkeypatch.setattr(app_settings, "authorization_v2_trusted_ref", "demo/agentic")


def _client(db_session, workspace: Workspace, user: User) -> TestClient:
    app = FastAPI()
    app.include_router(mission_room.router, prefix="/api/v1/mission-room")
    app.include_router(
        maritime.router,
        prefix="/api/v1/mission-room/maritime",
    )
    app.include_router(
        webcam_proxy.router,
        prefix="/api/v1/mission-room/webcams",
    )
    app.dependency_overrides[mission_room.get_current_workspace] = lambda: workspace
    app.dependency_overrides[mission_room.get_current_user] = lambda: user
    app.dependency_overrides[mission_room.get_db] = lambda: db_session
    return TestClient(app)


def _install_workspace_app(
    db_session,
    workspace: Workspace,
    app_id: str,
    version: str,
) -> WorkspaceAppInstallation:
    manifest = BUILTIN_WORKSPACE_APP_MANIFESTS[(app_id, version)]
    row = WorkspaceAppInstallation(
        id=str(uuid4()),
        workspace_id=workspace.id,
        app_id=app_id,
        version=version,
        manifest_digest=manifest.digest,
        state="installed",
        configuration=validate_manifest_configuration(manifest, None),
        revision=1,
        installed_at=datetime.utcnow(),
        updated_by="mission-room-runtime-test",
    )
    db_session.add(row)
    db_session.commit()
    _attest_workspace_apps(db_session, workspace)
    return row


def _attest_workspace_apps(db_session, workspace: Workspace) -> None:
    runtime = inspect_authoritative_workspace_app_runtime(workspace, db=db_session)
    installation_subject = workspace_app_installation_subject(runtime)
    preflight_evidence = "7" * 64
    preflight_artifact = "8" * 64
    source_junit = "6" * 64
    staged_at = datetime.now(UTC)
    probation = {
        "workspace_id": workspace.id,
        "revision": REVISION,
        "installations_sha256": workspace_app_installations_sha256(runtime),
        "installation_count": len(installation_subject),
        "preflight_evidence_sha256": preflight_evidence,
        "preflight_evidence_ref": f"sha256:{preflight_evidence}",
        "preflight_artifact_sha256": preflight_artifact,
        "preflight_artifact_ref": f"sha256:{preflight_artifact}",
        "preflight_artifact_tests": WORKSPACE_APP_PREFLIGHT_CHECK_COUNT,
        "preflight_source_junit_ref": f"sha256:{source_junit}",
        "trusted_runner": {
            "issuer": str(app_settings.authorization_v2_trusted_oidc_issuer),
            "project_id": str(app_settings.authorization_v2_trusted_project_id),
            "pipeline_id": "mission-room-runtime-pipeline",
            "job_id": "mission-room-runtime-job",
            "commit_sha": REVISION,
            "ref": str(app_settings.authorization_v2_trusted_ref),
            "ref_protected": True,
        },
        "staged_at": staged_at.isoformat(),
        "expires_at": (staged_at + WORKSPACE_APP_PROBATION_MAX_AGE).isoformat(),
        "staged_by": "mission-room-runtime-test",
    }
    probation_sha = _probation_digest(probation)
    probation["probation_sha256"] = probation_sha
    probation["probation_ref"] = f"sha256:{probation_sha}"
    audit_id = str(uuid4())
    db_session.add(
        AuditLog(
            id=audit_id,
            workspace_id=workspace.id,
            event_type="lot9.workspace_app_platform.staged",
            actor="mission-room-runtime-test",
            severity="info",
            details=_workspace_app_probation_audit_details(
                probation,
                trusted_runner=probation["trusted_runner"],
            ),
        )
    )
    db_session.flush()
    probation["audit_id"] = audit_id
    workspace.settings = {
        **workspace.settings,
        WORKSPACE_APP_ROLLOUT_STATE_KEY: {
            "schema_version": 1,
            "activations": [],
            "deactivations": [],
            "probation": probation,
            "probation_aborts": [],
        },
    }
    db_session.commit()


def _platform_workspace(
    db_session,
    *,
    family: str,
    profile: str | None,
    legacy_tampering: dict | None = None,
) -> tuple[Workspace, User]:
    settings = {
        "family": family,
        "features": {WORKSPACE_APP_PLATFORM_FEATURE: True},
        **(legacy_tampering or {}),
    }
    if profile is not None:
        mission_room_settings = settings.get("mission_room")
        mission_room_settings = (
            dict(mission_room_settings) if isinstance(mission_room_settings, dict) else {}
        )
        mission_room_settings["profile"] = profile
        settings["mission_room"] = mission_room_settings
    suffix = uuid4().hex[:10]
    workspace = Workspace(
        id=str(uuid4()),
        slug=f"mission-runtime-{suffix}",
        name=f"Mission Runtime {suffix}",
        mode="demo",
        settings=settings,
    )
    user = User(
        id=str(uuid4()),
        username=f"mission-user-{suffix}",
        email=f"mission-{suffix}@example.test",
        is_active=True,
    )
    db_session.add_all([workspace, user])
    db_session.commit()
    return workspace, user


def _grant_contributor(db_session, workspace: Workspace, user: User) -> None:
    db_session.add(
        WorkspaceMember(
            workspace_id=workspace.id,
            user_id=user.id,
            role="member",
            role_template=WORKSPACE_CONTRIBUTOR,
        )
    )
    db_session.commit()


def _set_authorization_modes(
    db_session,
    workspace: Workspace,
    user: User,
    modes: dict[str, str],
) -> WorkspaceIAMConfig:
    config = WorkspaceIAMConfig(
        workspace_id=workspace.id,
        version=1,
        role_flags={},
        capability_overrides={
            "authorization_v2": {
                "policy_version": 2,
                "default_mode": "compat",
                "modes": modes,
            }
        },
        updated_by_user_id=user.id,
    )
    db_session.add(config)
    db_session.commit()
    return config


def test_generic_workspace_cannot_discover_mission_room(
    db_session,
    monkeypatch,
):
    workspace = Workspace(
        id="workspace-generic",
        slug="generic",
        name="Generic Workspace",
        settings={},
    )
    user = User(
        id="user-generic",
        username="generic-user",
        email="generic@example.test",
        is_active=True,
    )
    db_session.add_all([workspace, user])
    db_session.commit()

    def unexpected_provider_call(*_args, **_kwargs):
        pytest.fail("disabled Mission Room reached an extension provider")

    monkeypatch.setattr(maritime, "fetch_snapshot", unexpected_provider_call)
    monkeypatch.setattr(
        webcam_proxy,
        "fetch_webcam_snapshot",
        unexpected_provider_call,
    )

    client = _client(db_session, workspace, user)
    responses = [
        client.get("/api/v1/mission-room/overview"),
        client.get("/api/v1/mission-room/maritime/snapshot"),
        client.get("/api/v1/mission-room/webcams/sources"),
    ]
    head_response = client.head(
        "/api/v1/mission-room/webcams/proxy",
        params={"source_id": "apm-apapa-gate-1"},
    )

    for response in responses:
        assert response.status_code == 404
        assert response.json() == {"detail": {"code": WORKSPACE_EXTENSION_NOT_FOUND_CODE}}
    assert head_response.status_code == 404
    assert head_response.content == b""
    assert db_session.query(AuditLog).count() == 0


@pytest.mark.parametrize(
    ("slug", "name", "settings", "expected_terms", "forbidden_terms"),
    [
        (
            "sentinel-ci",
            "SENTINEL-CI",
            {
                "workspace_app_label": "SENTINEL-CI",
                "actions": {
                    "enabled_packs": [
                        "global_voice_v1",
                        "sentinel_ci_aya_v1",
                        "sentinel_ci_aya_security_v1",
                    ]
                },
                "mission_room": {
                    "enabled": True,
                    "profile": SENTINEL_MISSION_ROOM_PROFILE,
                    "label": "AYA",
                },
            },
            ("SENTINEL-CI", "AYA", SENTINEL_MISSION_ROOM_PROFILE),
            ("Octocity", "OCTAVE", "octocity_", "octave."),
        ),
        (
            "octocity-mission-room",
            "Octocity Mission Room",
            {
                "workspace_app_label": "Octocity Mission Room",
                "workspace_app_brand": {
                    "label": "Octocity Mission Room",
                    "lines": ["AGENTIUM", "MISSION ROOM"],
                    "emblem": "/assets/brand/agentium-mark.svg",
                    "style": "agentium",
                },
                "actions": {
                    "enabled_packs": [
                        "global_voice_v1",
                        "octave_mission_room_v1",
                        "octave_security_v1",
                    ]
                },
                "mission_room": {
                    "enabled": True,
                    "profile": OCTOCITY_MISSION_ROOM_PROFILE,
                    "label": "OCTAVE",
                },
            },
            ("Octocity Mission Room", "OCTAVE", OCTOCITY_MISSION_ROOM_PROFILE),
            ("SENTINEL-CI", "AYA", "sentinel-ci", "sentinel_ci"),
        ),
    ],
)
def test_configured_mission_room_profiles_are_allowed_and_presented(
    db_session,
    slug,
    name,
    settings,
    expected_terms,
    forbidden_terms,
):
    workspace = Workspace(
        id=f"workspace-{slug}",
        slug=slug,
        name=name,
        mode="demo",
        settings=settings,
    )
    user = User(
        id=f"user-{slug}",
        username=f"user-{slug}",
        email=f"{slug}@example.test",
        is_active=True,
    )
    db_session.add_all([workspace, user])
    db_session.commit()
    client = _client(db_session, workspace, user)

    overview = client.get("/api/v1/mission-room/overview")
    navigation = client.get("/api/v1/mission-room/navigation")

    assert overview.status_code == 200
    assert navigation.status_code == 200
    runtime_payload = {
        "overview": overview.json(),
        "navigation": navigation.json(),
    }
    serialized = json.dumps(runtime_payload, ensure_ascii=False)
    for expected in expected_terms:
        assert expected in serialized
    for forbidden in forbidden_terms:
        assert forbidden not in serialized


@pytest.mark.parametrize(
    (
        "app_id",
        "family",
        "profile",
        "tampered",
        "expected_label",
        "expected_assistant",
        "expected_style",
        "forbidden_terms",
    ),
    [
        (
            "sentinel.mission-room",
            "sentinel_ci",
            SENTINEL_MISSION_ROOM_PROFILE,
            {
                "demo_profile": "octocity_mission_room",
                "workspace_app_label": "Octocity Legacy Trap",
                "workspace_app_brand": {"label": "Octocity Legacy Trap", "style": "agentium"},
                "assistant_profile_default": "octave_executive",
                "actions": {"enabled_packs": ["octave_mission_room_v1"]},
                "mission_room": {
                    "enabled": True,
                    "assistant_label": "OCTAVE",
                    "brand": {"label": "Octocity Legacy Trap", "style": "agentium"},
                    "navigation": [{"key": "cockpit", "variant": "octocity_mission_room"}],
                },
            },
            "SENTINEL-CI",
            "AYA",
            "sentinel",
            ("Octocity Legacy Trap", "OCTAVE", "octave_"),
        ),
        (
            "octocity.mission-room",
            "generic",
            OCTOCITY_MISSION_ROOM_PROFILE,
            {
                "demo_profile": "government_mission_room",
                "workspace_app_label": "SENTINEL LEGACY TRAP",
                "workspace_app_brand": {"label": "SENTINEL LEGACY TRAP", "style": "sentinel"},
                "assistant_profile_default": "vigie_executive",
                "actions": {"enabled_packs": ["sentinel_ci_aya_v1"]},
                "mission_room": {
                    "enabled": True,
                    "assistant_label": "AYA",
                    "brand": {"label": "SENTINEL LEGACY TRAP", "style": "sentinel"},
                    "navigation": [{"key": "cockpit", "variant": "sentinel_ci"}],
                },
            },
            "Octocity Mission Room",
            "OCTAVE",
            "agentium",
            ("SENTINEL LEGACY TRAP", "sentinel_ci_aya_", '"AYA"'),
        ),
    ],
)
def test_authoritative_provider_ignores_cross_profile_legacy_presentation(
    db_session,
    app_id,
    family,
    profile,
    tampered,
    expected_label,
    expected_assistant,
    expected_style,
    forbidden_terms,
):
    workspace, user = _platform_workspace(
        db_session,
        family=family,
        profile=profile,
        legacy_tampering=tampered,
    )
    _install_workspace_app(db_session, workspace, app_id, "1.0.0")

    client = _client(db_session, workspace, user)
    overview = client.get("/api/v1/mission-room/overview")
    navigation = client.get("/api/v1/mission-room/navigation")

    assert overview.status_code == 200
    assert navigation.status_code == 200
    app = navigation.json()["app"]
    assert app == {
        "label": expected_label,
        "assistant_label": expected_assistant,
        "shell": "immersive",
        "default_route": "/hypervisor/mission-room/cockpit",
        "default_view": "cockpit",
        "brand": {"label": expected_label, "style": expected_style},
        "profile": profile,
    }
    serialized = json.dumps(
        {"overview": overview.json(), "navigation": navigation.json()},
        ensure_ascii=False,
    )
    for forbidden in forbidden_terms:
        assert forbidden not in serialized


def test_generic_or_invalid_authoritative_runtime_never_reaches_sentinel_provider(
    db_session,
    monkeypatch,
):
    def unexpected_provider_call(*_args, **_kwargs):
        pytest.fail("provider-less or invalid runtime reached Sentinel fixtures")

    monkeypatch.setattr(mission_room, "overview_payload", unexpected_provider_call)
    monkeypatch.setattr(maritime, "fetch_snapshot", unexpected_provider_call)
    monkeypatch.setattr(
        webcam_proxy,
        "fetch_webcam_snapshot",
        unexpected_provider_call,
    )

    generic, generic_user = _platform_workspace(
        db_session,
        family="generic",
        profile=None,
    )
    _install_workspace_app(db_session, generic, "mission-room.extension", "1.1.0")
    generic_client = _client(db_session, generic, generic_user)
    generic_responses = [
        generic_client.get("/api/v1/mission-room/overview"),
        generic_client.get("/api/v1/mission-room/navigation"),
        generic_client.get("/api/v1/mission-room/maritime/snapshot"),
        generic_client.get("/api/v1/mission-room/webcams/sources"),
    ]
    generic_head = generic_client.head(
        "/api/v1/mission-room/webcams/proxy",
        params={"source_id": "apm-apapa-gate-1"},
    )
    for generic_response in generic_responses:
        assert generic_response.status_code == 404
        assert generic_response.json() == {"detail": {"code": WORKSPACE_EXTENSION_NOT_FOUND_CODE}}
    assert generic_head.status_code == 404
    assert generic_head.content == b""

    invalid, invalid_user = _platform_workspace(
        db_session,
        family="sentinel_ci",
        profile=SENTINEL_MISSION_ROOM_PROFILE,
    )
    installation = _install_workspace_app(
        db_session,
        invalid,
        "sentinel.mission-room",
        "1.0.0",
    )
    installation.manifest_digest = "0" * 64
    db_session.commit()
    invalid_response = _client(db_session, invalid, invalid_user).get(
        "/api/v1/mission-room/overview"
    )
    assert invalid_response.status_code == 404
    assert invalid_response.json() == {"detail": {"code": WORKSPACE_EXTENSION_NOT_FOUND_CODE}}


def test_customs_pdf_is_owned_by_the_installed_sentinel_app_and_workspace(
    db_session,
):
    document_id = "proces-verbal-douanes-non-conformite-2026-05-18"
    sentinel, sentinel_user = _platform_workspace(
        db_session,
        family="sentinel_ci",
        profile=SENTINEL_MISSION_ROOM_PROFILE,
    )
    _install_workspace_app(
        db_session,
        sentinel,
        "sentinel.mission-room",
        "1.0.0",
    )

    downloaded = _client(db_session, sentinel, sentinel_user).get(
        f"/api/v1/mission-room/customs-records/{document_id}.pdf"
    )

    assert downloaded.status_code == 200
    assert downloaded.headers["content-type"] == "application/pdf"
    assert downloaded.content.startswith(b"%PDF")
    audit = (
        db_session.query(AuditLog)
        .filter(
            AuditLog.workspace_id == sentinel.id,
            AuditLog.event_type == "mission_room.customs_record.downloaded",
        )
        .one()
    )
    assert audit.details["owner_workspace_id"] == sentinel.id
    assert audit.details["owner_app_id"] == "sentinel.mission-room"
    assert audit.details["resource_scope"] == "workspace_app"

    octocity, octocity_user = _platform_workspace(
        db_session,
        family="generic",
        profile=OCTOCITY_MISSION_ROOM_PROFILE,
    )
    _install_workspace_app(
        db_session,
        octocity,
        "octocity.mission-room",
        "1.0.0",
    )
    denied_octocity = _client(db_session, octocity, octocity_user).get(
        f"/api/v1/mission-room/customs-records/{document_id}.pdf"
    )
    assert denied_octocity.status_code == 404
    assert denied_octocity.json() == {"detail": "customs_record_not_found"}

    generic, generic_user = _platform_workspace(
        db_session,
        family="generic",
        profile=None,
    )
    _install_workspace_app(db_session, generic, "mission-room.extension", "1.1.0")
    denied_generic = _client(db_session, generic, generic_user).get(
        f"/api/v1/mission-room/customs-records/{document_id}.pdf"
    )
    assert denied_generic.status_code == 404
    assert denied_generic.json() == {"detail": {"code": WORKSPACE_EXTENSION_NOT_FOUND_CODE}}
    assert (
        db_session.query(AuditLog)
        .filter(
            AuditLog.workspace_id.in_([octocity.id, generic.id]),
            AuditLog.event_type == "mission_room.customs_record.downloaded",
        )
        .count()
        == 0
    )


def test_generic_provider_serves_only_real_workspace_objects(
    db_session,
):
    workspace, user = _platform_workspace(
        db_session,
        family="generic",
        profile=None,
    )
    foreign_workspace, _foreign_user = _platform_workspace(
        db_session,
        family="generic",
        profile=None,
    )
    db_session.add(
        WorkspaceMember(
            workspace_id=workspace.id,
            user_id=user.id,
            role="reviewer",
            role_template="workspace_reviewer",
        )
    )
    db_session.commit()
    _install_workspace_app(db_session, workspace, "mission-room.extension", "1.2.0")

    system = System(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name="Contract Review",
        objective="Review workspace contracts",
        status="active",
        created_by="workspace-owner",
    )
    run = Run(
        id=str(uuid4()),
        workspace_id=workspace.id,
        system_id=system.id,
        status="completed",
        duration_ms=125.0,
    )
    decision = Decision(
        id=str(uuid4()),
        workspace_id=workspace.id,
        scope="system",
        target_id=system.id,
        title="Approve contract review",
        status="accepted",
        rationale={"summary": "Evidence reviewed"},
    )
    audit = AuditLog(
        id=str(uuid4()),
        workspace_id=workspace.id,
        event_type="workspace.contract.reviewed",
        actor="workspace-owner",
        severity="info",
        details={"system_id": system.id},
    )
    calendar = WorkspaceCalendarEvent(
        id=str(uuid4()),
        workspace_id=workspace.id,
        title="Contract review meeting",
        description="Review the current decision",
        start_at=datetime(2026, 7, 23, 9, 0),
        end_at=datetime(2026, 7, 23, 9, 30),
        timezone="Europe/Paris",
        location="Online",
        participants=["workspace-owner"],
        category="review",
        priority="high",
        status="scheduled",
        source_kind="internal_shared",
        source_label="Workspace calendar",
    )
    foreign_system = System(
        id=str(uuid4()),
        workspace_id=foreign_workspace.id,
        name="SENTINEL-CI FOREIGN OBJECT",
        objective="OCTAVE FOREIGN OBJECT",
        status="active",
    )
    foreign_run = Run(
        id=str(uuid4()),
        workspace_id=foreign_workspace.id,
        system_id=foreign_system.id,
        status="failed",
    )
    foreign_decision = Decision(
        id=str(uuid4()),
        workspace_id=foreign_workspace.id,
        title="AYA FOREIGN DECISION",
        status="proposed",
    )
    db_session.add_all(
        [
            system,
            run,
            decision,
            audit,
            calendar,
            foreign_system,
            foreign_run,
            foreign_decision,
        ]
    )
    db_session.commit()

    client = _client(db_session, workspace, user)
    responses = {
        "overview": client.get("/api/v1/mission-room/overview"),
        "navigation": client.get("/api/v1/mission-room/navigation"),
        "cockpit": client.get("/api/v1/mission-room/cockpit"),
        "briefing": client.get("/api/v1/mission-room/briefing"),
        "timeline": client.get("/api/v1/mission-room/timeline"),
        "projects": client.get("/api/v1/mission-room/projects"),
        "decisions": client.get("/api/v1/mission-room/decisions"),
        "library": client.get("/api/v1/mission-room/library"),
        "search": client.get("/api/v1/mission-room/search", params={"q": ""}),
        "map": client.get("/api/v1/mission-room/map"),
        "monitor": client.get("/api/v1/mission-room/monitor"),
        "news": client.get("/api/v1/mission-room/news"),
        "draft": client.post(
            "/api/v1/mission-room/actions/draft",
            json={"target_id": system.id, "target_type": "system"},
        ),
    }

    assert all(response.status_code == 200 for response in responses.values())
    assert all(
        response.json()["provider_kind"] == "workspace_objects_v1"
        for response in responses.values()
    )
    assert responses["navigation"].json()["app"] == {
        "label": "Mission Room",
        "assistant_label": "Assistant",
        "shell": "immersive",
        "default_route": "/hypervisor/mission-room/cockpit",
        "default_view": "cockpit",
        "profile": "generic",
        "brand": {"label": "Mission Room", "style": "agentium"},
    }
    assert responses["map"].json()["state"] == "not_configured"
    assert responses["map"].json()["empty_state"]["code"] == ("geospatial_data_not_configured")
    assert responses["news"].json()["state"] == "not_configured"
    assert responses["draft"].json()["sent"] is False
    assert responses["draft"].json()["requires_validation"] is True

    serialized = json.dumps(
        {key: response.json() for key, response in responses.items()},
        ensure_ascii=False,
    )
    for expected in (system.id, run.id, decision.id, audit.id, calendar.id):
        assert expected in serialized
    for forbidden in (
        foreign_workspace.id,
        foreign_system.id,
        foreign_run.id,
        foreign_decision.id,
        "SENTINEL-CI FOREIGN OBJECT",
        "OCTAVE FOREIGN OBJECT",
        "AYA FOREIGN DECISION",
    ):
        assert forbidden not in serialized


def test_generic_provider_never_reveals_another_users_private_run_graph(
    db_session,
):
    workspace, user = _platform_workspace(
        db_session,
        family="generic",
        profile=None,
    )
    _grant_contributor(db_session, workspace, user)
    _install_workspace_app(db_session, workspace, "mission-room.extension", "1.2.0")
    other = User(
        id=str(uuid4()),
        username=f"private-owner-{uuid4().hex[:8]}",
        email=f"private-owner-{uuid4().hex[:8]}@example.test",
        is_active=True,
    )
    system = System(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name="Private-run boundary",
        status="active",
    )
    own_run = Run(
        id=str(uuid4()),
        workspace_id=workspace.id,
        system_id=system.id,
        initiated_by_user_id=user.id,
        trigger="chat_agentic",
        status="completed",
    )
    private_run = Run(
        id=str(uuid4()),
        workspace_id=workspace.id,
        system_id=system.id,
        initiated_by_user_id=other.id,
        trigger="chat_agentic",
        status="completed",
    )
    own_decision = Decision(
        id=str(uuid4()),
        workspace_id=workspace.id,
        scope="run",
        target_id=own_run.id,
        title="Visible own decision",
        status="proposed",
    )
    private_decision = Decision(
        id=str(uuid4()),
        workspace_id=workspace.id,
        scope="run",
        target_id=private_run.id,
        title="PRIVATE DECISION SECRET",
        status="proposed",
    )
    own_audit = AuditLog(
        id=str(uuid4()),
        workspace_id=workspace.id,
        event_type="visible.own.run",
        details={"run_id": own_run.id},
    )
    private_audit = AuditLog(
        id=str(uuid4()),
        workspace_id=workspace.id,
        event_type="private.run.secret",
        details={
            "resource": {
                "kind": "run",
                "sample_ids": [private_run.id],
            }
        },
    )
    db_session.add_all(
        [
            other,
            system,
            own_run,
            private_run,
            own_decision,
            private_decision,
            own_audit,
            private_audit,
        ]
    )
    db_session.commit()

    response = _client(db_session, workspace, user).get(
        "/api/v1/mission-room/search",
        params={"q": ""},
    )

    assert response.status_code == 200
    serialized = json.dumps(response.json(), ensure_ascii=False)
    for visible in (own_run.id, own_decision.id):
        assert visible in serialized
    for hidden in (
        own_audit.id,
        private_run.id,
        private_decision.id,
        private_audit.id,
        "PRIVATE DECISION SECRET",
        "private.run.secret",
    ):
        assert hidden not in serialized


def test_generic_provider_filters_candidate_denials_in_enforce_mode(
    db_session,
    attest_authorization_v2,
    monkeypatch,
):
    workspace, user = _platform_workspace(
        db_session,
        family="generic",
        profile=None,
    )
    _grant_contributor(db_session, workspace, user)
    _install_workspace_app(db_session, workspace, "mission-room.extension", "1.2.0")
    other = User(
        id=str(uuid4()),
        username=f"enforce-owner-{uuid4().hex[:8]}",
        email=f"enforce-owner-{uuid4().hex[:8]}@example.test",
        is_active=True,
    )
    system = System(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name="Enforce boundary",
        status="active",
    )
    denied_run = Run(
        id=str(uuid4()),
        workspace_id=workspace.id,
        system_id=system.id,
        initiated_by_user_id=other.id,
        trigger="manual",
        status="completed",
    )
    denied_decision = Decision(
        id=str(uuid4()),
        workspace_id=workspace.id,
        scope="system",
        target_id=system.id,
        title="ENFORCE DENIED DECISION",
        status="proposed",
    )
    denied_audit = AuditLog(
        id=str(uuid4()),
        workspace_id=workspace.id,
        event_type="enforce.denied.audit",
        details={"system_id": system.id},
    )
    db_session.add_all([other, system, denied_run, denied_decision, denied_audit])
    config = _set_authorization_modes(
        db_session,
        workspace,
        user,
        {
            "run.read": "enforce",
            "decision.read": "enforce",
            "audit_log.read": "enforce",
        },
    )
    actions = ["audit_log.read", "decision.read", "run.read"]
    attest_authorization_v2(config, actions, attested_revision=REVISION)
    monkeypatch.setattr(app_settings, "agentium_image_revision", REVISION)
    db_session.commit()

    response = _client(db_session, workspace, user).get(
        "/api/v1/mission-room/search",
        params={"q": ""},
    )

    assert response.status_code == 200
    serialized = json.dumps(response.json(), ensure_ascii=False)
    for hidden in (
        denied_run.id,
        denied_decision.id,
        denied_audit.id,
        "ENFORCE DENIED DECISION",
        "enforce.denied.audit",
    ):
        assert hidden not in serialized


def test_generic_provider_shadow_preserves_legacy_and_persists_evidence(
    db_session,
):
    workspace, user = _platform_workspace(
        db_session,
        family="generic",
        profile=None,
    )
    _grant_contributor(db_session, workspace, user)
    _install_workspace_app(db_session, workspace, "mission-room.extension", "1.2.0")
    other = User(
        id=str(uuid4()),
        username=f"shadow-owner-{uuid4().hex[:8]}",
        email=f"shadow-owner-{uuid4().hex[:8]}@example.test",
        is_active=True,
    )
    system = System(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name="Shadow boundary",
        status="active",
    )
    legacy_run = Run(
        id=str(uuid4()),
        workspace_id=workspace.id,
        system_id=system.id,
        initiated_by_user_id=other.id,
        trigger="manual",
        status="completed",
    )
    legacy_decision = Decision(
        id=str(uuid4()),
        workspace_id=workspace.id,
        scope="system",
        target_id=system.id,
        title="Shadow-visible decision",
        status="proposed",
    )
    legacy_audit = AuditLog(
        id=str(uuid4()),
        workspace_id=workspace.id,
        event_type="shadow.visible.audit",
        details={"system_id": system.id},
    )
    db_session.add_all([other, system, legacy_run, legacy_decision, legacy_audit])
    _set_authorization_modes(
        db_session,
        workspace,
        user,
        {
            "run.read": "shadow",
            "decision.read": "shadow",
            "audit_log.read": "shadow",
        },
    )

    response = _client(db_session, workspace, user).get(
        "/api/v1/mission-room/search",
        params={"q": ""},
    )

    assert response.status_code == 200
    serialized = json.dumps(response.json(), ensure_ascii=False)
    for visible in (legacy_run.id, legacy_decision.id):
        assert visible in serialized
    assert legacy_audit.id not in serialized
    assert "shadow.visible.audit" not in serialized
    evidence = (
        db_session.query(AuditLog)
        .filter(
            AuditLog.workspace_id == workspace.id,
            AuditLog.event_type == "iam.shadow.evaluation",
        )
        .all()
    )
    assert {item.details.get("action") for item in evidence}.issuperset(
        {"run.read", "decision.read", "audit_log.read"}
    )
    assert all(item.details.get("summary") is True for item in evidence)


def test_generic_system_read_enforce_allows_contributor_and_reviewer(
    db_session,
    attest_authorization_v2,
    monkeypatch,
):
    workspace, user = _platform_workspace(
        db_session,
        family="generic",
        profile=None,
    )
    _grant_contributor(db_session, workspace, user)
    _install_workspace_app(db_session, workspace, "mission-room.extension", "1.2.0")
    system = System(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name="Authorized generic System",
        status="active",
    )
    db_session.add(system)
    config = _set_authorization_modes(
        db_session,
        workspace,
        user,
        {"system.read": "enforce"},
    )
    attest_authorization_v2(
        config,
        ["system.read"],
        attested_revision=REVISION,
    )
    monkeypatch.setattr(app_settings, "agentium_image_revision", REVISION)
    db_session.commit()
    client = _client(db_session, workspace, user)

    for role, role_template in (
        ("member", WORKSPACE_CONTRIBUTOR),
        ("reviewer", "workspace_reviewer"),
    ):
        member = (
            db_session.query(WorkspaceMember)
            .filter_by(workspace_id=workspace.id, user_id=user.id)
            .one()
        )
        member.role = role
        member.role_template = role_template
        db_session.commit()
        overview = client.get("/api/v1/mission-room/overview")
        projects = client.get("/api/v1/mission-room/projects")
        search = client.get(
            "/api/v1/mission-room/search",
            params={"q": "Authorized generic System"},
        )
        draft = client.post(
            "/api/v1/mission-room/actions/draft",
            json={"target_id": system.id, "target_type": "system"},
        )
        assert overview.status_code == projects.status_code == 200
        assert search.status_code == draft.status_code == 200
        assert overview.json()["counts"]["systems"] == 1
        assert projects.json()["summary"]["total"] == 1
        assert search.json()["total"] == 1
        assert search.json()["results"][0]["id"] == system.id
        assert draft.json()["sources"] == [system.id]


def test_generic_system_read_invalid_enforce_hides_every_projection(
    db_session,
):
    workspace, user = _platform_workspace(
        db_session,
        family="generic",
        profile=None,
    )
    _grant_contributor(db_session, workspace, user)
    _install_workspace_app(db_session, workspace, "mission-room.extension", "1.2.0")
    system = System(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name="INVALID ATTESTATION SYSTEM SECRET",
        status="active",
    )
    db_session.add(system)
    _set_authorization_modes(
        db_session,
        workspace,
        user,
        {"system.read": "enforce"},
    )
    db_session.commit()
    client = _client(db_session, workspace, user)

    responses = {
        "overview": client.get("/api/v1/mission-room/overview"),
        "cockpit": client.get("/api/v1/mission-room/cockpit"),
        "briefing": client.get("/api/v1/mission-room/briefing"),
        "projects": client.get("/api/v1/mission-room/projects"),
        "library": client.get("/api/v1/mission-room/library"),
        "search": client.get(
            "/api/v1/mission-room/search",
            params={"q": ""},
        ),
    }
    assert all(response.status_code == 200 for response in responses.values())
    assert responses["overview"].json()["counts"]["systems"] == 0
    assert responses["overview"].json()["latest"]["system"] is None
    assert responses["cockpit"].json()["kpis"]["systems"] == 0
    assert responses["cockpit"].json()["priorities"] == []
    assert responses["projects"].json()["summary"]["total"] == 0
    assert responses["projects"].json()["projects"] == []
    assert "Systems" not in responses["library"].json()["collections"]
    assert all(item["kind"] != "system" for item in responses["search"].json()["results"])
    serialized = json.dumps(
        {key: response.json() for key, response in responses.items()},
        ensure_ascii=False,
    )
    assert system.id not in serialized
    assert "INVALID ATTESTATION SYSTEM SECRET" not in serialized
    draft = client.post(
        "/api/v1/mission-room/actions/draft",
        json={"target_id": system.id, "target_type": "system"},
    )
    assert draft.status_code == 404
    assert draft.json() == {"detail": "workspace_object_not_found"}


def test_generic_system_read_shadow_emits_collection_summary(db_session):
    workspace, user = _platform_workspace(
        db_session,
        family="generic",
        profile=None,
    )
    _grant_contributor(db_session, workspace, user)
    _install_workspace_app(db_session, workspace, "mission-room.extension", "1.2.0")
    system = System(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name="Shadow System",
        status="active",
    )
    db_session.add(system)
    _set_authorization_modes(
        db_session,
        workspace,
        user,
        {"system.read": "shadow"},
    )

    response = _client(db_session, workspace, user).get("/api/v1/mission-room/projects")

    assert response.status_code == 200
    assert response.json()["projects"][0]["id"] == system.id
    evidence = [
        item
        for item in db_session.query(AuditLog)
        .filter_by(
            workspace_id=workspace.id,
            event_type="iam.shadow.evaluation",
        )
        .all()
        if item.details.get("action") == "system.read"
    ]
    assert len(evidence) == 1
    assert evidence[0].details["summary"] is True
    assert evidence[0].details["evaluation_count"] == 1
    assert evidence[0].details["mismatches"] == 0


@pytest.mark.parametrize(
    ("path", "params"),
    [
        ("/api/v1/mission-room/security-monitor", None),
        ("/api/v1/mission-room/satellite/scenes", None),
        ("/api/v1/mission-room/satellite/proxy", {"scene_id": "foreign"}),
        ("/api/v1/mission-room/evidence-graph", None),
        ("/api/v1/mission-room/evidence-graph/trace", {"from": "foreign"}),
        (
            "/api/v1/mission-room/customs-records/foreign.pdf",
            None,
        ),
        ("/api/v1/mission-room/reports/foreign/foreign.pdf", None),
        ("/api/v1/mission-room/macro-indicators", None),
        ("/api/v1/mission-room/cedeao-index", None),
        ("/api/v1/mission-room/maritime/snapshot", None),
        ("/api/v1/mission-room/webcams/sources", None),
        ("/api/v1/mission-room/webcams/proxy", {"source_id": "foreign"}),
    ],
)
def test_generic_provider_blocks_every_specialized_shared_prefix_route(
    db_session,
    path,
    params,
):
    workspace, user = _platform_workspace(
        db_session,
        family="generic",
        profile=None,
    )
    _install_workspace_app(db_session, workspace, "mission-room.extension", "1.2.0")

    response = _client(db_session, workspace, user).get(path, params=params)

    assert response.status_code == 404
    assert response.json() == {"detail": {"code": WORKSPACE_EXTENSION_NOT_FOUND_CODE}}


def test_get_and_both_draft_providers_commit_audits_visible_to_a_fresh_session(
    db_session,
):
    generic, generic_user = _platform_workspace(
        db_session,
        family="generic",
        profile=None,
    )
    _install_workspace_app(db_session, generic, "mission-room.extension", "1.2.0")
    system = System(
        id=str(uuid4()),
        workspace_id=generic.id,
        name="Audited System",
        objective="Verify durable audit writes",
        status="active",
    )
    db_session.add(system)
    db_session.commit()
    generic_client = _client(db_session, generic, generic_user)

    viewed = generic_client.get("/api/v1/mission-room/overview")
    generic_draft = generic_client.post(
        "/api/v1/mission-room/actions/draft",
        json={"target_id": system.id, "target_type": "system"},
    )

    sentinel, sentinel_user = _platform_workspace(
        db_session,
        family="sentinel_ci",
        profile=SENTINEL_MISSION_ROOM_PROFILE,
    )
    _install_workspace_app(
        db_session,
        sentinel,
        "sentinel.mission-room",
        "1.0.0",
    )
    specialized_draft = _client(db_session, sentinel, sentinel_user).post(
        "/api/v1/mission-room/actions/draft",
        json={"target_id": "package-zone-nord", "target_type": "project"},
    )

    assert viewed.status_code == 200
    assert generic_draft.status_code == 200
    assert specialized_draft.status_code == 200
    for response in (generic_draft, specialized_draft):
        assert response.json()["sent"] is False
        assert response.json()["requires_validation"] is True

    fresh = SessionLocal()
    try:
        assert (
            fresh.query(AuditLog)
            .filter(
                AuditLog.workspace_id == generic.id,
                AuditLog.event_type == "mission_room.overview.viewed",
            )
            .count()
            == 1
        )
        assert (
            fresh.query(AuditLog)
            .filter(
                AuditLog.workspace_id == generic.id,
                AuditLog.event_type == "mission_room.generic_draft.created",
            )
            .count()
            == 1
        )
        assert (
            fresh.query(AuditLog)
            .filter(
                AuditLog.workspace_id == sentinel.id,
                AuditLog.event_type == "mission_room.instruction.drafted",
            )
            .count()
            == 1
        )
    finally:
        fresh.close()
