"""API tests for ``/api/v1/meetings`` (Phase I)."""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import meetings
from app.models.user import User
from app.models.workspace import Workspace
from app.services.meeting_decisions import log_decision_for_workspace
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


def test_meeting_decisions_log_is_workspace_scoped_and_not_captured_as_event_id(
    db_session,
):
    workspace, user, event = _seed(db_session)
    foreign_workspace = Workspace(
        id="ws-meet-foreign",
        slug="octocity-test",
        name="Octocity test",
        mode="demo",
    )
    db_session.add(foreign_workspace)
    db_session.flush()
    own = log_decision_for_workspace(
        db_session,
        workspace,
        user,
        calendar_event_id=event.id,
        agenda_item_ref="own-decision",
        options_offered=[],
        chosen_option="A",
        rationale="Workspace scoped",
        source_refs=[],
    )
    log_decision_for_workspace(
        db_session,
        foreign_workspace,
        user,
        calendar_event_id="foreign-event",
        agenda_item_ref="foreign-decision",
        options_offered=[],
        chosen_option="B",
        rationale="Must stay private",
        source_refs=[],
    )
    db_session.commit()

    response = _client(db_session, workspace, user).get(
        "/api/v1/meetings/decisions-log",
        params={"workspace": foreign_workspace.slug},
    )

    assert response.status_code == 200
    assert [row["id"] for row in response.json()["decisions"]] == [own.id]


def test_meeting_unknown_event_returns_404(db_session):
    workspace, user, _event = _seed(db_session)
    client = _client(db_session, workspace, user)
    response = client.get("/api/v1/meetings/does-not-exist")
    assert response.status_code == 404


def test_meeting_start_sets_current_meeting(db_session):
    workspace, user, event = _seed(db_session)
    client = _client(db_session, workspace, user)

    response = client.post(f"/api/v1/meetings/{event.id}/start")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["event"]["id"] == event.id
    assert body["current_meeting"] == event.id

    # Workspace settings record the active meeting so a follow-up
    # ``aya.log_decision`` voice command finds the right event.
    db_session.refresh(workspace)
    assert (workspace.settings or {}).get("actions", {}).get("current_meeting") == event.id


def test_meeting_agenda_patch_propose_then_confirm(db_session):
    workspace, user, event = _seed(db_session)
    client = _client(db_session, workspace, user)

    # No pending patch initially.
    initial = client.get(f"/api/v1/meetings/{event.id}/agenda-patch").json()
    assert initial["pending_agenda_patch"] is None

    proposed_items = [
        {
            "id": "agenda-cacao-diversification",
            "title": "Point cacao - diversification anacarde (clic UI)",
            "decision_required": True,
        }
    ]
    propose = client.post(
        f"/api/v1/meetings/{event.id}/agenda-patch",
        json={"agenda_items": proposed_items},
    )
    assert propose.status_code == 200, propose.text
    pending = propose.json()["pending_agenda_patch"]
    assert pending and pending["agenda_items"][0]["id"] == "agenda-cacao-diversification"

    # The detail endpoint surfaces the pending patch so the meeting view can
    # display the validate banner.
    detail = client.get(f"/api/v1/meetings/{event.id}").json()
    assert detail["pending_agenda_patch"]["event_id"] == event.id

    confirm = client.post(
        f"/api/v1/meetings/{event.id}/agenda-patch/confirm",
        json={},
    )
    assert confirm.status_code == 200, confirm.text
    body = confirm.json()
    assert body["pending_agenda_patch"] is None
    assert body["agenda_items"][0]["id"] == "agenda-cacao-diversification"

    # Pending patch cleared after confirm.
    cleared = client.get(f"/api/v1/meetings/{event.id}/agenda-patch").json()
    assert cleared["pending_agenda_patch"] is None


def test_meeting_agenda_patch_confirm_without_pending_returns_400(db_session):
    workspace, user, event = _seed(db_session)
    client = _client(db_session, workspace, user)

    response = client.post(
        f"/api/v1/meetings/{event.id}/agenda-patch/confirm",
        json={},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "no_pending_agenda_patch"
