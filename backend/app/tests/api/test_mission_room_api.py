from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import mission_room
from app.models.audit import AuditLog
from app.models.intelligence import FeedArticle, FeedSource
from app.models.run import Run
from app.models.user import User
from app.models.workspace import Workspace
from app.services.workspace_calendar import ensure_calendar_seed


def _client(db_session, workspace: Workspace, user: User) -> TestClient:
    app = FastAPI()
    app.include_router(mission_room.router, prefix="/api/v1/mission-room")
    app.dependency_overrides[mission_room.get_current_workspace] = lambda: workspace
    app.dependency_overrides[mission_room.get_current_user] = lambda: user
    app.dependency_overrides[mission_room.get_db] = lambda: db_session
    return TestClient(app)


def test_mission_room_overview_is_workspace_scoped(db_session):
    workspace = Workspace(id="workspace-sentinel", slug="sentinel-ci", name="SENTINEL-CI", mode="demo")
    user = User(id="user-1", username="minister", email="minister@example.test", is_active=True)
    db_session.add_all([workspace, user])
    db_session.commit()

    response = _client(db_session, workspace, user).get("/api/v1/mission-room/overview")

    assert response.status_code == 200
    body = response.json()
    assert body["workspace"]["slug"] == "sentinel-ci"
    assert body["briefing_status"] == "ready"
    assert len(body["priorities"]) >= 3
    assert body["kpis"]["press_alerts"] == 16


def test_mission_room_navigation_cockpit_and_search_are_audited(db_session):
    workspace = Workspace(id="workspace-sentinel", slug="sentinel-ci", name="SENTINEL-CI", mode="demo")
    user = User(id="user-1", username="minister", email="minister@example.test", is_active=True)
    db_session.add_all([workspace, user])
    db_session.commit()
    client = _client(db_session, workspace, user)

    navigation = client.get("/api/v1/mission-room/navigation")
    cockpit = client.get("/api/v1/mission-room/cockpit")
    search = client.get("/api/v1/mission-room/search", params={"q": "Nord"})

    assert navigation.status_code == 200
    assert navigation.json()["app"]["default_view"] == "cockpit"
    assert navigation.json()["app"]["assistant_label"] == "VIGIE"
    assert navigation.json()["items"][0]["route"] == "/hypervisor/mission-room/cockpit"
    assert cockpit.status_code == 200
    assert cockpit.json()["layout"]["variant"] == "executive_grid"
    assert search.status_code == 200
    assert search.json()["total"] >= 1

    event_types = {row.event_type for row in db_session.query(AuditLog).all()}
    assert "mission_room.navigation.viewed" in event_types
    assert "mission_room.cockpit.viewed" in event_types
    assert "mission_room.search.performed" in event_types


def test_mission_room_news_uses_live_workspace_intelligence_without_cross_tenant_leak(db_session):
    workspace = Workspace(id="workspace-sentinel", slug="sentinel-ci", name="SENTINEL-CI", mode="demo")
    other = Workspace(id="workspace-andritz", slug="andritz", name="Andritz", mode="standard")
    user = User(id="user-1", username="minister", email="minister@example.test", is_active=True)
    source = FeedSource(
        id="feed-sentinel",
        workspace_id=workspace.id,
        name="Africanews",
        url="https://example.test/rss",
        active=True,
    )
    other_source = FeedSource(
        id="feed-andritz",
        workspace_id=other.id,
        name="Andritz private",
        url="https://andritz.example.test/rss",
        active=True,
    )
    article = FeedArticle(
        id="article-ci",
        source_id=source.id,
        title="Cote d'Ivoire: signaux publics autour d'un projet prioritaire",
        summary="Plusieurs sources publiques convergent vers un besoin de communication preventive.",
        url="https://example.test/article-ci",
        embedded=True,
        relevance_score=0.87,
        analysis={"risk_level": "high", "sentiment": "mixed", "entities": ["Cote d'Ivoire", "Abidjan"]},
    )
    other_article = FeedArticle(
        id="article-andritz",
        source_id=other_source.id,
        title="Andritz internal deposit",
        summary="This must not leak into SENTINEL-CI.",
        embedded=True,
        relevance_score=0.99,
        analysis={"risk_level": "critical", "sentiment": "negative", "entities": ["Andritz"]},
    )
    run = Run(
        id="run-intel-ci",
        workspace_id=workspace.id,
        input_ref={"source": "intelligence.analyze"},
        output_ref={},
        status="completed",
        decision="brief_ready",
    )
    db_session.add_all([workspace, other, user, source, other_source, article, other_article, run])
    db_session.commit()
    client = _client(db_session, workspace, user)

    news = client.get("/api/v1/mission-room/news")
    cockpit = client.get("/api/v1/mission-room/cockpit")

    assert news.status_code == 200
    news_body = news.json()
    assert news_body["source_health"]["live_news_used"] is True
    assert news_body["source_health"]["last_run_id"] == run.id
    assert news_body["source_health"]["high_risk"] == 1
    assert news_body["executive_alerts"][0]["article_id"] == article.id
    assert "Andritz" not in str(news_body)
    assert cockpit.status_code == 200
    assert cockpit.json()["press_intelligence"]["last_run_id"] == run.id

    audit = db_session.query(AuditLog).filter_by(event_type="mission_room.news.synthesized").one()
    assert audit.details["last_run_id"] == run.id
    assert audit.details["live_news_used"] is True


def test_mission_room_timeline_decisions_and_library_are_workspace_scoped(db_session):
    workspace = Workspace(id="workspace-sentinel", slug="sentinel-ci", name="SENTINEL-CI", mode="demo")
    user = User(id="user-1", username="minister", email="minister@example.test", is_active=True)
    db_session.add_all([workspace, user])
    db_session.commit()
    ensure_calendar_seed(db_session, workspace)
    db_session.commit()
    client = _client(db_session, workspace, user)

    timeline = client.get("/api/v1/mission-room/timeline")
    decisions = client.get("/api/v1/mission-room/decisions")
    library = client.get("/api/v1/mission-room/library")

    assert timeline.status_code == 200
    assert timeline.json()["workspace"]["slug"] == workspace.slug
    assert timeline.json()["calendar"]["connector"]["id"] == "institutional_calendar"
    assert timeline.json()["agenda"][0]["title"] == "Conseil Defense restreint"
    assert len(timeline.json()["messages"]) >= 1
    assert decisions.status_code == 200
    assert decisions.json()["policy"]["human_validation_required"] is True
    assert library.status_code == 200
    assert "sentinel-ci-projects" in library.json()["collections"]


def test_draft_action_is_advisory_and_audited(db_session):
    workspace = Workspace(id="workspace-sentinel", slug="sentinel-ci", name="SENTINEL-CI", mode="demo")
    user = User(id="user-1", username="minister", email="minister@example.test", is_active=True)
    db_session.add_all([workspace, user])
    db_session.commit()

    response = _client(db_session, workspace, user).post(
        "/api/v1/mission-room/actions/draft",
        json={"target_id": "proj-health-north", "target_type": "project"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "draft"
    assert body["sent"] is False
    assert body["requires_validation"] is True
    assert body["control"]["human_authority_required"] is True

    audit = db_session.query(AuditLog).filter_by(event_type="mission_room.instruction.drafted").one()
    assert audit.workspace_id == workspace.id
    assert audit.actor == user.email
    assert audit.details["sent"] is False
