from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import mission_room
from app.models.audit import AuditLog
from app.models.intelligence import FeedArticle, FeedSource
from app.models.run import Run
from app.models.user import User
from app.models.workspace import Workspace
from app.services.action_plans import ensure_action_plan_seed
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
    briefing = client.get("/api/v1/mission-room/briefing")
    search = client.get("/api/v1/mission-room/search", params={"q": "Nord"})

    assert navigation.status_code == 200
    assert navigation.json()["app"]["default_view"] == "cockpit"
    assert navigation.json()["app"]["assistant_label"] == "AYA"
    assert navigation.json()["items"][0]["route"] == "/hypervisor/mission-room/cockpit"
    assert [item["key"] for item in navigation.json()["items"]] == [
        "cockpit",
        "monitor",
        "briefing",
        "agenda",
        "presse",
        "decisions",
        "strategie",
    ]
    assert [item["label"] for item in navigation.json()["items"]] == [
        "Priorites",
        "Situation live",
        "Briefing",
        "Agenda",
        "Presse",
        "Arbitrages",
        "Carte",
    ]
    assert cockpit.status_code == 200
    assert cockpit.json()["layout"]["variant"] == "executive_grid"
    assert cockpit.json()["decision_sentence"]["text"].startswith("M. le Vice-Président")
    assert len(cockpit.json()["attention_required"]) == 3
    assert len(cockpit.json()["sixty_second_cockpit"]["urgences"]) == 3
    assert cockpit.json()["strategic_posture"]["label"] in {"stable", "monitoring", "elevated", "critical"}
    assert cockpit.json()["situation_monitor"]["route"] == "/hypervisor/mission-room/monitor"
    assert briefing.status_code == 200
    assert any(section["id"] == "visual_cross_check" for section in briefing.json()["sections"])
    assert briefing.json()["visual_intelligence_brief"]["transcription"]["available"] is False
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
        category="ci-local",
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
    assert news_body["source_health"]["geography_order"] == ["ci", "cedeao", "africa", "world"]
    assert news_body["geographic_priority"][0]["key"] == "ci"
    assert news_body["viewpoints"][0]["key"] == "interior"
    assert news_body["social_listening"]["rumor_origins"]
    assert news_body["executive_alerts"][0]["article_id"] == article.id
    assert news_body["executive_alerts"][0]["geography_tier"] == "ci"
    assert news_body["executive_alerts"][0]["viewpoint"] == "politique interieure ivoirienne"
    assert "Andritz" not in str(news_body)
    assert cockpit.status_code == 200
    cockpit_body = cockpit.json()
    assert cockpit_body["press_intelligence"]["last_run_id"] == run.id
    assert cockpit_body["decision_sentence"]["deadline"] == "avant Conseil 15h00"
    assert len(cockpit_body["sixty_second_cockpit"]["urgences"]) == 3
    assert cockpit_body["executive_decision_packages"][0]["deadline"] == "15:00"
    assert cockpit_body["rumor_trace"]["origin"].startswith("WhatsApp")

    audit = db_session.query(AuditLog).filter_by(event_type="mission_room.news.synthesized").one()
    assert audit.details["last_run_id"] == run.id
    assert audit.details["live_news_used"] is True


def test_mission_room_timeline_decisions_and_library_are_workspace_scoped(db_session):
    workspace = Workspace(id="workspace-sentinel", slug="sentinel-ci", name="SENTINEL-CI", mode="demo")
    user = User(id="user-1", username="minister", email="minister@example.test", is_active=True)
    db_session.add_all([workspace, user])
    db_session.commit()
    ensure_calendar_seed(db_session, workspace)
    ensure_action_plan_seed(db_session, workspace)
    db_session.commit()
    client = _client(db_session, workspace, user)

    timeline = client.get("/api/v1/mission-room/timeline")
    decisions = client.get("/api/v1/mission-room/decisions")
    library = client.get("/api/v1/mission-room/library")
    projects = client.get("/api/v1/mission-room/projects")

    assert timeline.status_code == 200
    assert timeline.json()["workspace"]["slug"] == workspace.slug
    assert timeline.json()["calendar"]["connector"]["id"] == "institutional_calendar"
    assert timeline.json()["agenda"][0]["title"] == "Conseil Defense restreint"
    assert len(timeline.json()["action_items"]) >= 1
    assert len(timeline.json()["messages"]) >= 1
    assert decisions.status_code == 200
    assert decisions.json()["policy"]["human_validation_required"] is True
    assert decisions.json()["action_summary"]["active"] >= 1
    assert len(decisions.json()["action_items"]) >= 1
    assert library.status_code == 200
    assert "sentinel-ci-projects" in library.json()["collections"]
    assert "sentinel-ci-visual-intelligence" in library.json()["collections"]
    assert projects.status_code == 200
    assert projects.json()["projects"][0]["name"]


def test_mission_room_monitor_seeds_visual_context_and_is_audited(db_session):
    workspace = Workspace(id="workspace-sentinel", slug="sentinel-ci", name="SENTINEL-CI", mode="demo")
    user = User(id="user-1", username="minister", email="minister@example.test", is_active=True)
    db_session.add_all([workspace, user])
    db_session.commit()
    client = _client(db_session, workspace, user)

    response = client.get("/api/v1/mission-room/monitor")

    assert response.status_code == 200
    body = response.json()
    assert body["workspace"]["slug"] == "sentinel-ci"
    assert body["posture"]["label"] in {"stable", "monitoring", "elevated", "critical"}
    assert body["scenario"]["id"] == "scenario-crise-nationale"
    assert body["scenario"]["title"] == "Crise nationale"
    assert body["decision_sentence"]["text"].startswith("M. le Vice-Président")
    assert len(body["attention_required"]) == 3
    assert body["attention_required"][0]["deadline"] == "14:00"
    assert body["voice_demo_script"]["target_latency_s"] == 6
    assert len(body["executive_decision_packages"]) == 3
    assert body["executive_decision_packages"][0]["recommended_option"].startswith("Coordination CEDEAO")
    assert body["rumor_trace"]["recommended_action"].startswith("Verifier source primaire")
    assert body["demo_value_metrics"][0]["value"] == "80 -> 3"
    assert len(body["presentation_beats"]) == 4
    assert body["voice_context"]["assistant"] == "AYA"
    assert body["voice_context"]["mode"] == "voice_first"
    assert body["visual_intelligence_brief"]["source_quality"]["label"] == "Basse resolution publique"
    assert body["visual_intelligence_brief"]["transcription"]["type"] == "visual_snapshot_analysis"
    assert body["voice_context"]["visual_intelligence_brief"]["question_answered"].startswith("La valeur ajoutee")
    assert body["voice_context"]["demo_script"]["prompt"].startswith("AYA")
    assert body["voice_context"]["decision_packages"][0]["id"] == "package-zone-nord"
    assert body["voice_context"]["rumor_trace"]["headline"] == "Rumeur prioritaire sous verification"
    assert any(command["intent"] == "rumor_origin" for command in body["voice_context"]["commands"])
    assert body["panel_layout"][0]["key"] == "map"
    assert any(signal["id"] == "visual-activity" for signal in body["cross_source_signals"])
    assert any(signal["id"] == "social-rumor-origin" for signal in body["cross_source_signals"])
    assert body["visual"]["connector"]["id"] == "visual_streams"
    assert body["visual"]["source_health"]["total_sources"] >= 1
    assert any(layer["key"] == "regional-context" for layer in body["layers"])
    assert any(layer["key"] == "social-rumors" for layer in body["layers"])
    assert any(layer["key"] == "visual-streams" for layer in body["layers"])

    audit = db_session.query(AuditLog).filter_by(event_type="mission_room.monitor.viewed").one()
    assert audit.workspace_id == workspace.id
    assert audit.details["posture"] == body["posture"]["label"]


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
