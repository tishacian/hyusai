from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import calendar
from app.models.audit import AuditLog
from app.models.user import User
from app.models.workspace import Workspace
from app.services.demo_time_context import resolve_demo_date
from app.services.workspace_calendar import ensure_calendar_seed, handle_calendar_chat_action, list_events


def _client(db_session, workspace: Workspace, user: User) -> TestClient:
    app = FastAPI()
    app.include_router(calendar.router, prefix="/api/v1/calendar")
    app.dependency_overrides[calendar.get_current_workspace] = lambda: workspace
    app.dependency_overrides[calendar.get_current_user] = lambda: user
    app.dependency_overrides[calendar.get_db] = lambda: db_session
    return TestClient(app)


def test_calendar_crud_is_workspace_scoped_and_audited(db_session):
    workspace = Workspace(
        id="workspace-sentinel",
        slug="sentinel-ci",
        name="SENTINEL-CI",
        mode="demo",
        settings={"calendar": {"mode": "internal_shared", "write_policy": "direct"}},
    )
    other = Workspace(id="workspace-andritz", slug="andritz", name="Andritz", mode="operator")
    user = User(id="user-1", username="minister", email="minister@example.test", is_active=True)
    db_session.add_all([workspace, other, user])
    db_session.commit()
    ensure_calendar_seed(db_session, other)
    db_session.commit()
    client = _client(db_session, workspace, user)

    created = client.post(
        "/api/v1/calendar/events",
        json={
            "title": "Cellule de coordination territoriale",
            "start_at": "2026-04-15T10:00:00",
            "end_at": "2026-04-15T10:45:00",
            "location": "Cabinet ministeriel",
            "priority": "high",
        },
    )
    assert created.status_code == 200
    event_id = created.json()["id"]

    listed = client.get("/api/v1/calendar/events")
    assert listed.status_code == 200
    assert [event["title"] for event in listed.json()["events"]] == ["Cellule de coordination territoriale"]
    assert "Conseil Defense restreint" not in str(listed.json())

    patched = client.patch(
        f"/api/v1/calendar/events/{event_id}",
        json={"start_at": "2026-04-15T10:30:00", "end_at": "2026-04-15T11:15:00"},
    )
    assert patched.status_code == 200
    assert patched.json()["time"] == "10:30"

    cancelled = client.post(f"/api/v1/calendar/events/{event_id}/cancel", json={"reason": "Arbitrage reporte"})
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"

    event_types = {row.event_type for row in db_session.query(AuditLog).all()}
    assert {"calendar.event.created", "calendar.event.updated", "calendar.event.cancelled"} <= event_types


def test_calendar_summary_uses_internal_connector(db_session):
    workspace = Workspace(
        id="workspace-sentinel",
        slug="sentinel-ci",
        name="SENTINEL-CI",
        mode="demo",
        settings={"calendar": {"mode": "internal_shared", "write_policy": "direct"}},
    )
    user = User(id="user-1", username="minister", email="minister@example.test", is_active=True)
    db_session.add_all([workspace, user])
    db_session.commit()
    ensure_calendar_seed(db_session, workspace)
    db_session.commit()

    response = _client(db_session, workspace, user).get("/api/v1/calendar/summary")

    assert response.status_code == 200
    body = response.json()
    assert body["date"] == resolve_demo_date(workspace).isoformat()
    assert body["connector"]["id"] == "institutional_calendar"
    assert body["connector"]["mode"] == "internal_shared"
    assert body["count"] >= 5
    assert body["events"][0]["title"] == "Conseil Defense restreint"
    assert body["events"][0]["date"] == body["date"]
    assert "conflict_score" in body
    assert "recommended_moves" in body
    assert body["decision_deadlines"] == []


def test_vigie_calendar_action_writes_when_policy_is_direct(db_session):
    workspace = Workspace(
        id="workspace-sentinel",
        slug="sentinel-ci",
        name="SENTINEL-CI",
        mode="demo",
        settings={"calendar": {"mode": "internal_shared", "write_policy": "direct"}},
    )
    user = User(id="user-1", username="minister", email="minister@example.test", is_active=True)
    db_session.add_all([workspace, user])
    db_session.commit()

    result = handle_calendar_chat_action(
        db_session,
        workspace,
        user,
        query="Ajoute une reunion agenda coordination cabinet a 10h30",
        assistant_profile="vigie_executive",
    )

    assert result is not None
    assert result["action"] == "calendar_create_event"
    assert result["applied"] is True
    assert len(list_events(db_session, workspace)) == 1
    assert list_events(db_session, workspace)[0].workspace_id == workspace.id
