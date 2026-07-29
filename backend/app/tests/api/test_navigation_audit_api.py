from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import audit
from app.models.audit import AuditLog
from app.models.user import User
from app.models.workspace import Workspace


def _client(db_session, workspace: Workspace, user: User) -> TestClient:
    app = FastAPI()
    app.include_router(audit.router, prefix="/api/v1/audit")
    app.dependency_overrides[audit.get_current_workspace] = lambda: workspace
    app.dependency_overrides[audit.get_current_user] = lambda: user
    app.dependency_overrides[audit.get_db] = lambda: db_session
    return TestClient(app)


def _seed(db_session) -> tuple[Workspace, User]:
    workspace = Workspace(
        id="workspace-andritz-navigation",
        slug="andritz",
        name="Andritz",
        mode="builder",
    )
    user = User(
        id="user-navigation",
        username="navigation.owner",
        email="navigation.owner@example.test",
        is_active=True,
    )
    db_session.add_all([workspace, user])
    db_session.commit()
    return workspace, user


def test_navigation_resolved_is_strict_workspace_authoritative_and_pii_free(db_session):
    workspace, user = _seed(db_session)
    response = _client(db_session, workspace, user).post(
        "/api/v1/audit",
        json={
            "event_type": "navigation.resolved",
            "actor": "spoofed@example.test",
            "trace_id": "trace-with-user-context",
            "agent_id": "agent-with-user-context",
            "severity": "critical",
            "details": {
                "schema_version": 1,
                "requested_route": "/systems?search=someone@example.test",
                "resolved_route": "/chat#private-note",
                "effective_workspace": "spoofed-workspace",
                "effective_surface": "chat",
                "redirect_owner": "navigation_resolver",
                "redirect_reason": "business_profile_disallowed",
                "redirected": True,
            },
        },
    )

    assert response.status_code == 200
    row = db_session.query(AuditLog).filter_by(event_type="navigation.resolved").one()
    assert row.workspace_id == workspace.id
    assert row.actor == "authenticated_user"
    assert row.trace_id is None
    assert row.agent_id is None
    assert row.severity == "info"
    assert row.details == {
        "schema_version": 1,
        "requested_route": "/systems",
        "resolved_route": "/chat",
        "effective_workspace": "andritz",
        "effective_surface": "chat",
        "redirect_owner": "navigation_resolver",
        "redirect_reason": "business_profile_disallowed",
        "redirected": True,
    }
    assert "example.test" not in str(response.json())


def test_navigation_resolved_rejects_extra_fields_and_pii_in_paths(db_session):
    workspace, user = _seed(db_session)
    client = _client(db_session, workspace, user)
    base_details = {
        "schema_version": 1,
        "requested_route": "/chat",
        "resolved_route": "/chat",
        "effective_workspace": "andritz",
        "effective_surface": "chat",
        "redirect_owner": "angular_router",
        "redirect_reason": "direct",
        "redirected": False,
    }

    with_extra = client.post(
        "/api/v1/audit",
        json={
            "event_type": "navigation.resolved",
            "details": {**base_details, "email": "someone@example.test"},
        },
    )
    assert with_extra.status_code == 422

    with_email_path = client.post(
        "/api/v1/audit",
        json={
            "event_type": "navigation.resolved",
            "details": {
                **base_details,
                "requested_route": "/account/someone%40example.test",
            },
        },
    )
    assert with_email_path.status_code == 422
    assert db_session.query(AuditLog).count() == 0


def test_navigation_resolved_canonicalizes_all_dynamic_path_segments(db_session):
    workspace, user = _seed(db_session)
    client = _client(db_session, workspace, user)
    cases = [
        (
            "/workspace/andritz/settings",
            "/workspace/:slug/settings",
        ),
        (
            "/client360/customers/Jean-Dupont",
            "/client360/:segment/:segment",
        ),
        (
            "/systems/private-system-name/capture",
            "/systems/:id/capture",
        ),
        (
            "/Jean-Dupont/private-case",
            "/:segment/:segment",
        ),
    ]

    for index, (requested_route, expected_route) in enumerate(cases):
        response = client.post(
            "/api/v1/audit",
            json={
                "event_type": "navigation.resolved",
                "details": {
                    "schema_version": 1,
                    "requested_route": requested_route,
                    "resolved_route": "/chat",
                    "effective_workspace": "spoofed",
                    "effective_surface": "chat",
                    "redirect_owner": "navigation_resolver",
                    "redirect_reason": "business_profile_disallowed",
                    "redirected": True,
                },
            },
        )
        assert response.status_code == 200
        row = (
            db_session.query(AuditLog)
            .filter_by(event_type="navigation.resolved")
            .order_by(AuditLog.timestamp.desc())
            .first()
        )
        assert row is not None, index
        assert row.details["requested_route"] == expected_route
        assert "Jean-Dupont" not in str(row.details)
        assert "private-system-name" not in str(row.details)


@pytest.mark.parametrize(
    ("redirect_owner", "redirect_reason"),
    (
        ("angular_router", "angular_route_redirect"),
        ("navigation_resolver", "business_knowledge_compatibility"),
        ("navigation_resolver", "business_profile_disallowed"),
        ("navigation_resolver", "business_system_capture_compatibility"),
        ("navigation_resolver", "workspace_default_route"),
        ("navigation_resolver", "workspace_extension_unavailable"),
        ("navigation_resolver", "workspace_settings_entrypoint"),
        ("navigation_resolver", "legacy_hypervisor_object_lens"),
    ),
)
def test_navigation_resolved_accepts_each_redirect_owner_reason_pair(
    db_session,
    redirect_owner: str,
    redirect_reason: str,
):
    workspace, user = _seed(db_session)
    response = _client(db_session, workspace, user).post(
        "/api/v1/audit",
        json={
            "event_type": "navigation.resolved",
            "details": {
                "schema_version": 1,
                "requested_route": "/systems",
                "resolved_route": "/chat",
                "effective_workspace": "andritz",
                "effective_surface": "chat",
                "redirect_owner": redirect_owner,
                "redirect_reason": redirect_reason,
                "redirected": True,
            },
        },
    )

    assert response.status_code == 200


@pytest.mark.parametrize(
    ("legacy_owner", "reason"),
    (
        ("navigation_profile", "business_profile_disallowed"),
        ("workspace_shell", "workspace_default_route"),
        ("workspace_entrypoint", "workspace_settings_entrypoint"),
    ),
)
def test_navigation_resolved_canonicalizes_legacy_owners_during_rollout(
    db_session,
    legacy_owner: str,
    reason: str,
):
    workspace, user = _seed(db_session)
    response = _client(db_session, workspace, user).post(
        "/api/v1/audit",
        json={
            "event_type": "navigation.resolved",
            "details": {
                "schema_version": 1,
                "requested_route": "/systems",
                "resolved_route": "/chat",
                "effective_workspace": "andritz",
                "effective_surface": "chat",
                "redirect_owner": legacy_owner,
                "redirect_reason": reason,
                "redirected": True,
            },
        },
    )

    assert response.status_code == 200
    assert response.json()["details"]["redirect_owner"] == "navigation_resolver"


def test_navigation_resolved_accepts_direct_navigation_with_equal_routes(
    db_session,
):
    workspace, user = _seed(db_session)
    response = _client(db_session, workspace, user).post(
        "/api/v1/audit",
        json={
            "event_type": "navigation.resolved",
            "details": {
                "schema_version": 1,
                "requested_route": "/systems/private-system",
                "resolved_route": "/systems/private-system",
                "effective_workspace": "andritz",
                "effective_surface": "chat",
                "redirect_owner": "angular_router",
                "redirect_reason": "direct",
                "redirected": False,
            },
        },
    )

    assert response.status_code == 200
    assert response.json()["details"] == {
        "schema_version": 1,
        "requested_route": "/systems/:id",
        "resolved_route": "/systems/:id",
        "effective_workspace": "andritz",
        "effective_surface": "systems",
        "redirect_owner": "angular_router",
        "redirect_reason": "direct",
        "redirected": False,
    }


def test_navigation_resolved_accepts_and_canonicalizes_fse_reports_surface(
    db_session,
):
    workspace, user = _seed(db_session)
    response = _client(db_session, workspace, user).post(
        "/api/v1/audit",
        json={
            "event_type": "navigation.resolved",
            "details": {
                "schema_version": 1,
                "requested_route": "/knowledge/interventions",
                "resolved_route": "/knowledge/interventions",
                "effective_workspace": workspace.slug,
                "effective_surface": "fse-reports",
                "redirect_owner": "angular_router",
                "redirect_reason": "direct",
                "redirected": False,
            },
        },
    )

    assert response.status_code == 200
    assert response.json()["details"]["effective_surface"] == "fse-reports"
    assert response.json()["details"]["resolved_route"] == "/knowledge/interventions"


@pytest.mark.parametrize(
    ("redirect_owner", "redirect_reason", "redirected"),
    (
        ("navigation_resolver", "direct", False),
        ("navigation_resolver", "angular_route_redirect", True),
        ("angular_router", "business_profile_disallowed", True),
        ("angular_router", "workspace_default_route", True),
        ("angular_router", "workspace_settings_entrypoint", True),
    ),
)
def test_navigation_resolved_rejects_impossible_owner_reason_pairs_without_echoing_pii(
    db_session,
    redirect_owner: str,
    redirect_reason: str,
    redirected: bool,
):
    workspace, user = _seed(db_session)
    response = _client(db_session, workspace, user).post(
        "/api/v1/audit",
        json={
            "event_type": "navigation.resolved",
            "details": {
                "schema_version": 1,
                "requested_route": "/systems?owner=private@example.test",
                "resolved_route": "/chat#private@example.test",
                "effective_workspace": "andritz",
                "effective_surface": "chat",
                "redirect_owner": redirect_owner,
                "redirect_reason": redirect_reason,
                "redirected": redirected,
            },
        },
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid navigation.resolved details"}
    assert "example.test" not in response.text
    assert db_session.query(AuditLog).count() == 0


@pytest.mark.parametrize(
    ("redirected", "redirect_reason"),
    (
        (True, "direct"),
        (False, "angular_route_redirect"),
    ),
)
def test_navigation_resolved_enforces_redirect_flag_semantics(
    db_session,
    redirected: bool,
    redirect_reason: str,
):
    workspace, user = _seed(db_session)
    response = _client(db_session, workspace, user).post(
        "/api/v1/audit",
        json={
            "event_type": "navigation.resolved",
            "details": {
                "schema_version": 1,
                "requested_route": "/systems",
                "resolved_route": "/chat",
                "effective_workspace": "andritz",
                "effective_surface": "chat",
                "redirect_owner": "angular_router",
                "redirect_reason": redirect_reason,
                "redirected": redirected,
            },
        },
    )

    assert response.status_code == 422
    assert db_session.query(AuditLog).count() == 0


def test_navigation_resolved_requires_equal_routes_for_direct_navigation_without_echoing_pii(
    db_session,
):
    workspace, user = _seed(db_session)
    response = _client(db_session, workspace, user).post(
        "/api/v1/audit",
        json={
            "event_type": "navigation.resolved",
            "details": {
                "schema_version": 1,
                "requested_route": "/systems?owner=private@example.test",
                "resolved_route": "/chat#private@example.test",
                "effective_workspace": "andritz",
                "effective_surface": "chat",
                "redirect_owner": "angular_router",
                "redirect_reason": "direct",
                "redirected": False,
            },
        },
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid navigation.resolved details"}
    assert "example.test" not in response.text
    assert db_session.query(AuditLog).count() == 0


def test_navigation_resolved_derives_surface_from_canonical_destination(db_session):
    workspace, user = _seed(db_session)
    client = _client(db_session, workspace, user)

    spoofed = client.post(
        "/api/v1/audit",
        json={
            "event_type": "navigation.resolved",
            "details": {
                "schema_version": 1,
                "requested_route": "/chat",
                "resolved_route": "/systems",
                "effective_workspace": "spoofed",
                "effective_surface": "chat",
                "redirect_owner": "angular_router",
                "redirect_reason": "angular_route_redirect",
                "redirected": True,
            },
        },
    )
    assert spoofed.status_code == 200
    assert spoofed.json()["details"]["effective_surface"] == "systems"

    unknown = client.post(
        "/api/v1/audit",
        json={
            "event_type": "navigation.resolved",
            "details": {
                "schema_version": 1,
                "requested_route": "/systems",
                "resolved_route": "/customer-name/private-object",
                "effective_workspace": "spoofed",
                "effective_surface": "systems",
                "redirect_owner": "angular_router",
                "redirect_reason": "angular_route_redirect",
                "redirected": True,
            },
        },
    )
    assert unknown.status_code == 200
    assert unknown.json()["details"]["resolved_route"] == "/:segment/:segment"
    assert unknown.json()["details"]["effective_surface"] == "unknown"


def test_generic_audit_event_keeps_existing_authenticated_actor_contract(db_session):
    workspace, user = _seed(db_session)
    response = _client(db_session, workspace, user).post(
        "/api/v1/audit",
        json={
            "event_type": "test.generic",
            "actor": "spoofed",
            "details": {"free_form": True},
            "severity": "warning",
        },
    )

    assert response.status_code == 200
    row = db_session.query(AuditLog).filter_by(event_type="test.generic").one()
    assert row.actor == user.username
    assert row.details == {"free_form": True}
    assert row.severity == "warning"


@pytest.mark.parametrize(
    "event_type",
    [
        "iam.shadow.evaluation",
        "lot7.authorization.enforce_promoted",
        "lot8.value_loop.canary_window.opened",
        "lot9.workspace_app_platform.activated",
        "decision.actuation.applied",
        "value_loop.action.executed",
        "workspace_app.install.applied",
        "run.completed",
        "system360.rollout.activated",
    ],
)
def test_public_audit_endpoint_rejects_server_namespaces(db_session, event_type):
    workspace, user = _seed(db_session)
    response = _client(db_session, workspace, user).post(
        "/api/v1/audit",
        json={
            "event_type": event_type,
            "details": {"origin": "server", "candidate_allowed": 1},
        },
    )

    assert response.status_code == 403
    assert db_session.query(AuditLog).filter_by(event_type=event_type).count() == 0
