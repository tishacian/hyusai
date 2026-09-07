from __future__ import annotations

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
        id="workspace-andritz-transition",
        slug="andritz",
        name="Andritz",
        mode="builder",
    )
    user = User(
        id="user-transition",
        username="transition.owner",
        email="transition.owner@example.test",
        is_active=True,
    )
    db_session.add_all([workspace, user])
    db_session.commit()
    return workspace, user


def _payload(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "schema_version": 2,
        "from_surface": "systems",
        "to_surface": "runs",
        "trigger": "inpage",
        "zone_changed": False,
        "depth_delta": 1,
        "facet_changed": True,
    }
    body.update(overrides)
    return body


def test_navigation_transition_is_strict_pseudonymous_and_forbids_extra(db_session):
    workspace, user = _seed(db_session)
    response = _client(db_session, workspace, user).post(
        "/api/v1/audit",
        json={
            "event_type": "navigation.transition",
            "actor": "spoofed@example.test",
            "trace_id": "trace-with-user-context",
            "agent_id": "agent-with-user-context",
            "severity": "critical",
            "details": _payload(),
        },
    )

    assert response.status_code == 200
    row = db_session.query(AuditLog).filter_by(event_type="navigation.transition").one()
    assert row.workspace_id == workspace.id
    assert row.actor == "authenticated_user"
    assert row.trace_id is None
    assert row.agent_id is None
    assert row.severity == "info"
    assert row.details == _payload()


def test_navigation_transition_rejects_extra_fields_and_unknown_trigger(db_session):
    workspace, user = _seed(db_session)
    client = _client(db_session, workspace, user)

    extra = _client(db_session, workspace, user).post(
        "/api/v1/audit",
        json={
            "event_type": "navigation.transition",
            "details": {**_payload(), "system_id": "sys-private"},
        },
    )
    assert extra.status_code == 422
    assert extra.json() == {"detail": "Invalid navigation.transition details"}

    unknown = client.post(
        "/api/v1/audit",
        json={
            "event_type": "navigation.transition",
            "details": _payload(trigger="clickjack"),
        },
    )
    assert unknown.status_code == 422
    assert unknown.json() == {"detail": "Invalid navigation.transition details"}
    assert db_session.query(AuditLog).filter_by(event_type="navigation.transition").count() == 0


def test_navigation_transition_rejects_unknown_surface_and_unbounded_depth(db_session):
    workspace, user = _seed(db_session)
    client = _client(db_session, workspace, user)

    surface = client.post(
        "/api/v1/audit",
        json={
            "event_type": "navigation.transition",
            "details": _payload(from_surface="not-a-surface"),
        },
    )
    assert surface.status_code == 422

    depth = client.post(
        "/api/v1/audit",
        json={
            "event_type": "navigation.transition",
            "details": _payload(depth_delta=99),
        },
    )
    assert depth.status_code == 422
