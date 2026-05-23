"""API tests for ``/api/v1/meetings`` (Phase I)."""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import meetings
from app.models.user import User
from app.models.workspace import Workspace
from app.services.workspace_calendar import create_event


def _client(db_session, workspace: Workspace, user: User) -> TestClient:
    app = FastAPI()
    app.include_router(meetings.router, prefix="/api/v1/meetings")
    app.dependency_overrides[meetings.get_current_workspace] = lambda: workspace
    app.dependency_overrides[meetings.get_current_user] = lambda: user
    app.dependency_overrides[meetings.get_db] = lambda: db_session
    return TestClient(app)


def _seed(db_session):
    workspace = Workspace(id="ws-meet", slug="sentinel-ci", name="SENTINEL-CI", mode="demo")
    user = User(id="user-meet", username="vp", email="vp@example.test", is_active=True)
    db_session.add_all([workspace, user])
    db_session.commit()
    start = datetime.utcnow() + timedelta(hours=1)
    event = create_event(
        db_session,
        workspace,
        user,
        title="Rencontre Prefet Nawa",
        start_at=start,
        end_at=start + timedelta(minutes=45),
        category="ministerial",
        priority="high",
    )
    db_session.commit()
    return workspace, user, event


def test_meeting_detail_returns_event_and_decisions(db_session):
    workspace, user, event = _seed(db_session)
    client = _client(db_session, workspace, user)

    detail = client.get(f"/api/v1/meetings/{event.id}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["event"]["id"] == event.id
    assert body["agenda_items"] == []
    assert body["decisions"] == []


def test_meeting_decision_can_be_logged_and_listed(db_session):
    workspace, user, event = _seed(db_session)
    client = _client(db_session, workspace, user)

    create_resp = client.post(
        f"/api/v1/meetings/{event.id}/decisions",
        json={
            "agenda_item_ref": "agenda-cacao-diversification",
            "options_offered": [
                {"key": "A", "label": "Statu quo"},
                {"key": "B", "label": "Diversification anacarde"},
            ],
            "chosen_option": "B",
            "rationale": "Alignement Banque mondiale + EUDR.",
            "source_refs": ["sentinel-ci-anacarde-diversification-v1"],
        },
    )
    assert create_resp.status_code == 200, create_resp.text
    decision = create_resp.json()
    assert decision["chosen_option"] == "B"
    assert decision["calendar_event_id"] == event.id

    listing = client.get(f"/api/v1/meetings/{event.id}/decisions")
    assert listing.status_code == 200
    payload = listing.json()
    assert payload["event_id"] == event.id
    assert len(payload["decisions"]) == 1
    assert payload["decisions"][0]["rationale"].startswith("Alignement")

    detail = client.get(f"/api/v1/meetings/{event.id}").json()
    assert detail["decision_count"] == 1


def test_meeting_unknown_event_returns_404(db_session):
    workspace, user, _event = _seed(db_session)
    client = _client(db_session, workspace, user)
    response = client.get("/api/v1/meetings/does-not-exist")
    assert response.status_code == 404
