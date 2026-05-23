from __future__ import annotations

import json

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
    evidence_graph = client.get("/api/v1/mission-room/evidence-graph")
    search = client.get("/api/v1/mission-room/search", params={"q": "Nord"})

    assert navigation.status_code == 200
    assert navigation.json()["app"]["default_view"] == "cockpit"
    assert navigation.json()["app"]["assistant_label"] == "AYA"
    assert navigation.json()["items"][0]["route"] == "/hypervisor/mission-room/cockpit"
    assert [item["key"] for item in navigation.json()["items"]] == [
        "cockpit",
        "monitor",
        "strategie",
        "briefing",
        "agenda",
        "presse",
        "decisions",
    ]
    assert [item["label"] for item in navigation.json()["items"]] == [
        "Cockpit",
        "Situation live",
        "Carte fusionnee",
        "Aide a la decision",
        "Agenda",
        "Renseignement",
        "Arbitrages",
    ]
    assert cockpit.status_code == 200
    cockpit_body = cockpit.json()
    assert cockpit_body["layout"]["variant"] == "vp_decision_cockpit"
    assert len(cockpit_body["layout"]["widgets"]) >= 8
    assert {widget["stratum"] for widget in cockpit_body["layout"]["widgets"]} == {
        "monitoring",
        "alerting",
        "decision",
    }
    assert cockpit_body["decision_sentence"]["text"].startswith("M. le Vice-Président")
    assert cockpit_body["vp_story"]["scenario_id"] == "sentinel-ci-vp-morning-zone-nord-v1"
    assert cockpit_body["vp_story"]["assistant"] == "AYA"
    assert cockpit_body["vp_story"]["anchors"]["priority_zone"] == "Zone Nord"
    assert cockpit_body["vp_story"]["directive_of_day"]["text"] == cockpit_body["directive_of_day"]["text"]
    assert cockpit_body["vp_story"]["agenda_day"]["label"] == cockpit_body["agenda_day"]["label"]
    assert [item["id"] for item in cockpit_body["vp_story"]["attention_required"]] == [
        "attention-inter-budget",
        "attention-zone-nord",
        "attention-ambassadeur-france",
    ]
    ambassadeur = next(item for item in cockpit_body["attention_required"] if item["id"] == "attention-ambassadeur-france")
    assert ambassadeur["action_route"] == "/hypervisor/mission-room/decisions"
    assert len(cockpit_body["arbitration_cards"]) >= 3
    assert [card["rank"] for card in cockpit_body["arbitration_cards"]] == sorted(
        card["rank"] for card in cockpit_body["arbitration_cards"]
    )
    assert cockpit_body["arbitration_cards"][0]["id"] == "attention-inter-budget"
    assert cockpit_body["arbitration_cards"][0]["domain"] == "PRESSE"
    assert cockpit_body["arbitration_cards"][0]["drill_down"]["view"] == "presse"
    diplomacy_card = next(card for card in cockpit_body["arbitration_cards"] if card["id"] == "attention-ambassadeur-france")
    assert diplomacy_card["drill_down"]["view"] == "decisions"
    assert diplomacy_card["secondary_drill_down"]["view"] == "agenda"
    assert len(cockpit_body["intelligence_feeds"]) == 8
    assert {feed["key"] for feed in cockpit_body["intelligence_feeds"]} == {
        "satellite",
        "maritime-ais",
        "ads-b",
        "osint",
        "mobile-signal",
        "economy",
        "terrain-sensors",
        "cyber",
    }
    geo_preview = cockpit_body["fused_map_preview"]["geo_preview"]
    assert geo_preview["top_zone_id"] == "zone-nord"
    assert geo_preview["active_layers"] == ["threat", "press"]
    assert geo_preview["camera"]["center"]
    assert geo_preview["zone_scores"]
    assert 2 <= len(cockpit_body["press_preview"]) <= 3
    assert cockpit_body["press_preview"][0]["route"].startswith("/hypervisor/mission-room/presse?highlight=")
    assert cockpit_body["agenda_timeline"]["separate_from_actions"] is True
    assert cockpit_body["agenda_timeline"]["now_marker"]["label"] == "MAINTENANT"
    assert any(event.get("countdown") == "dans 1h44" for event in cockpit_body["agenda_timeline"]["events"])
    assert cockpit_body["demo_narrative"]["scenario_id"] == cockpit_body["vp_story"]["scenario_id"]
    assert [step["phase"] for step in cockpit_body["demo_narrative"]["steps"]] == [
        "explorer",
        "comprendre",
        "decider",
    ]
    assert cockpit_body["demo_narrative"]["steps"][1]["anchor"] == "attention-inter-budget"
    assert cockpit_body["demo_narrative"]["steps"][2]["anchor"] == "package-zone-nord"
    assert cockpit_body["demo_narrative"]["economic_hook"]["cross_sources"] == ["maritime", "projets"]
    assert cockpit_body["directive_of_day"]["primary_cta"] == "Ouvrir le dossier Zone Nord"
    assert cockpit_body["vp_status_bar"][0]["key"] == "posture"
    assert cockpit_body["agenda_day"]["label"] == "Agenda ministeriel"
    assert cockpit_body["fused_map_preview"]["route"] == "/hypervisor/mission-room/strategie"
    assert cockpit_body["geographic_signal_tiers"][0]["key"] == "ci"
    assert len(cockpit_body["attention_required"]) == 3
    assert len(cockpit_body["sixty_second_cockpit"]["urgences"]) == 3
    assert cockpit_body["strategic_posture"]["label"] in {"stable", "monitoring", "elevated", "critical"}
    assert cockpit_body["situation_monitor"]["route"] == "/hypervisor/mission-room/monitor"
    assert cockpit_body["decision_posture"]["modes"][0]["key"] == "explorer"
    assert cockpit_body["source_freshness"]["items"]
    assert cockpit_body["monitoring_layers"]
    assert cockpit_body["evidence_graph_summary"]["node_count"] >= 10
    assert cockpit_body["evidence_graph_summary"]["collection_slug"] == "sentinel-ci-evidence-graph"
    assert briefing.status_code == 200
    assert any(section["id"] == "visual_cross_check" for section in briefing.json()["sections"])
    assert briefing.json()["visual_intelligence_brief"]["transcription"]["available"] is False
    assert evidence_graph.status_code == 200
    assert evidence_graph.json()["mode"] == "evidence_graph_v1"
    assert evidence_graph.json()["knowledge"]["scope"] == "vigie"
    assert evidence_graph.json()["nodes"]
    assert evidence_graph.json()["edges"]
    assert evidence_graph.json()["summary"]["top_relationships"]
    assert search.status_code == 200
    assert search.json()["total"] >= 1

    event_types = {row.event_type for row in db_session.query(AuditLog).all()}
    assert "mission_room.navigation.viewed" in event_types
    assert "mission_room.cockpit.viewed" in event_types
    assert "mission_room.evidence_graph.viewed" in event_types
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
    assert news_body["vp_story"]["scenario_id"] == "sentinel-ci-vp-morning-zone-nord-v1"
    assert news_body["vp_story"]["anchors"]["press_signal"] == "Article L'Inter - critique personnelle sur budget defense"
    assert news_body["vp_story"]["attention_required"][0]["id"] == "attention-inter-budget"
    assert news_body["source_health"]["last_run_id"] == run.id
    assert news_body["source_health"]["high_risk"] == 1
    assert news_body["source_health"]["geography_order"] == ["ci", "cedeao", "africa", "world"]
    assert news_body["geographic_priority"][0]["key"] == "ci"
    assert news_body["viewpoints"][0]["key"] == "interior"
    assert news_body["social_listening"]["rumor_origins"]
    assert news_body["maritime_intelligence"]["latest_observation"]["domain"] in {"customs", "port_flow"}
    assert news_body["maritime_intelligence"]["active_evidence"]["type"] == "maritime"
    assert any(feed["url"] == "https://www.portabidjan.ci/rss.xml" for feed in news_body["maritime_intelligence"]["feeds"])
    assert news_body["executive_alerts"][0]["article_id"] == article.id
    assert news_body["executive_alerts"][0]["geography_tier"] == "ci"
    assert news_body["executive_alerts"][0]["geo_tier"] == "ci"
    assert news_body["executive_alerts"][0]["velocity"] in {"rapide", "elevee", "moderee", "veille"}
    assert news_body["executive_alerts"][0]["briefing_value"]
    assert news_body["executive_alerts"][0]["viewpoint"] == "politique interieure ivoirienne"
    assert [section["key"] for section in news_body["geo_sections"]] == ["ci", "cedeao", "africa", "world"]
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
    assert timeline.json()["vp_story"]["scenario_id"] == "sentinel-ci-vp-morning-zone-nord-v1"
    assert timeline.json()["vp_story"]["anchors"]["agenda_signal"] == "Ambassadeur France - dejeuner dans 1h44"
    assert timeline.json()["agenda_day"]["label"] == "Agenda ministeriel"
    assert timeline.json()["attention_required"][1]["id"] == "attention-zone-nord"
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
    assert "sentinel-ci-maritime-intelligence" in library.json()["collections"]
    assert "sentinel-ci-evidence-graph" in library.json()["collections"]
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
    assert body["vp_story"]["scenario_id"] == "sentinel-ci-vp-morning-zone-nord-v1"
    assert body["vp_story"]["directive_of_day"]["text"] == body["directive_of_day"]["text"]
    assert body["agenda_day"]["label"] == "Agenda ministeriel"
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
    assert body["worldmonitor_principles"]["map_dominant"] is True
    assert body["active_evidence"]["title"]
    assert body["active_evidence"]["decision_deadline"]
    assert body["active_evidence"]["aya_context"]["answer_frame"].startswith("Situation")
    assert body["voice_context"]["demo_script"]["prompt"].startswith("AYA")
    assert body["voice_context"]["active_evidence"]["id"] == body["active_evidence"]["id"]
    assert body["voice_context"]["decision_packages"][0]["id"] == "package-zone-nord"
    assert body["voice_context"]["rumor_trace"]["headline"] == "Rumeur prioritaire sous verification"
    assert any(command["intent"] == "rumor_origin" for command in body["voice_context"]["commands"])
    assert body["panel_layout"][0]["key"] == "map"
    assert any(signal["id"] == "visual-activity" for signal in body["cross_source_signals"])
    assert any(signal["id"] == "maritime-customs-watch" for signal in body["cross_source_signals"])
    assert any(signal["id"] == "social-rumor-origin" for signal in body["cross_source_signals"])
    assert all(signal["evidence_refs"] for signal in body["cross_source_signals"])
    assert all(signal["decision_deadline"] for signal in body["cross_source_signals"])
    assert all(signal["aya_context"]["answer_frame"].startswith("Situation") for signal in body["cross_source_signals"])
    assert body["zones"][0]["popup_brief"]["cta"] == "Preparer arbitrage"
    assert body["visual"]["connector"]["id"] == "visual_streams"
    assert body["visual"]["source_health"]["total_sources"] >= 1
    assert body["maritime"]["active_evidence"]["type"] == "maritime"
    assert body["maritime"]["active_evidence"]["map_focus"]["active_layers"][-1] == "maritime-traffic"
    assert [layer["key"] for layer in body["layers"]] == ["territorial-risk", "open-intelligence", "visual-streams", "maritime-traffic"]
    assert body["layers"][-1]["enabled"] is False
    assert [layer["key"] for layer in body["map_system"]["layer_catalog"]] == ["territorial-risk", "open-intelligence", "visual-streams", "maritime-traffic"]
    assert "maritime-traffic" not in body["map_system"]["default_map_state"]["active_layers"]
    assert any(layer["key"] == "visual-streams" for layer in body["layers"])

    audit = db_session.query(AuditLog).filter_by(event_type="mission_room.monitor.viewed").one()
    assert audit.workspace_id == workspace.id
    assert audit.details["posture"] == body["posture"]["label"]


def test_mission_room_vp_story_is_consistent_across_core_surfaces(db_session):
    workspace = Workspace(id="workspace-sentinel", slug="sentinel-ci", name="SENTINEL-CI", mode="demo")
    user = User(id="user-1", username="minister", email="minister@example.test", is_active=True)
    db_session.add_all([workspace, user])
    db_session.commit()
    ensure_calendar_seed(db_session, workspace)
    ensure_action_plan_seed(db_session, workspace)
    db_session.commit()
    client = _client(db_session, workspace, user)

    surfaces = {
        "cockpit": client.get("/api/v1/mission-room/cockpit").json(),
        "briefing": client.get("/api/v1/mission-room/briefing").json(),
        "timeline": client.get("/api/v1/mission-room/timeline").json(),
        "news": client.get("/api/v1/mission-room/news").json(),
        "map": client.get("/api/v1/mission-room/map").json(),
        "monitor": client.get("/api/v1/mission-room/monitor").json(),
    }

    stories = {name: body["vp_story"] for name, body in surfaces.items()}
    assert {story["scenario_id"] for story in stories.values()} == {"sentinel-ci-vp-morning-zone-nord-v1"}
    directive = stories["cockpit"]["directive_of_day"]["text"]
    assert all(story["directive_of_day"]["text"] == directive for story in stories.values())
    assert all(story["anchors"]["priority_zone"] == "Zone Nord" for story in stories.values())
    assert all(story["anchors"]["rumor_signal"] == "Emoi public - rumeur a contenir" for story in stories.values())
    assert all(story["anchors"]["maritime_signal"] == "Port d'Abidjan - douanes et flux economiques" for story in stories.values())
    assert all(story["attention_required"][0]["id"] == "attention-inter-budget" for story in stories.values())
    assert all(story["attention_required"][1]["deadline"] == "15:00" for story in stories.values())
    assert all(story["decision_queue"][0]["id"] == "package-zone-nord" for story in stories.values())
    assert all(story["agenda_day"]["label"] == "Agenda ministeriel" for story in stories.values())
    cockpit = surfaces["cockpit"]
    assert cockpit["demo_narrative"]["steps"][1]["anchor"] == cockpit["vp_story"]["attention_required"][0]["id"]
    assert cockpit["demo_narrative"]["steps"][2]["anchor"] == cockpit["vp_story"]["decision_queue"][0]["id"]
    assert cockpit["arbitration_cards"][0]["id"] == cockpit["vp_story"]["attention_required"][0]["id"]
    assert surfaces["cockpit"]["directive_of_day"]["text"] == directive
    assert surfaces["briefing"]["directive_of_day"]["text"] == directive
    assert surfaces["monitor"]["directive_of_day"]["text"] == directive


def test_mission_room_core_routes_are_non_empty_and_demo_clean(db_session):
    workspace = Workspace(id="workspace-sentinel", slug="sentinel-ci", name="SENTINEL-CI", mode="demo")
    user = User(id="user-1", username="minister", email="minister@example.test", is_active=True)
    db_session.add_all([workspace, user])
    db_session.commit()
    ensure_calendar_seed(db_session, workspace)
    ensure_action_plan_seed(db_session, workspace)
    db_session.commit()
    client = _client(db_session, workspace, user)

    routes = [
        "/api/v1/mission-room/overview",
        "/api/v1/mission-room/navigation",
        "/api/v1/mission-room/cockpit",
        "/api/v1/mission-room/briefing",
        "/api/v1/mission-room/timeline",
        "/api/v1/mission-room/projects",
        "/api/v1/mission-room/decisions",
        "/api/v1/mission-room/library",
        "/api/v1/mission-room/search?q=Nord",
        "/api/v1/mission-room/map",
        "/api/v1/mission-room/monitor",
        "/api/v1/mission-room/evidence-graph",
        "/api/v1/mission-room/news",
    ]

    for route in routes:
        response = client.get(route)
        assert response.status_code == 200, route
        payload = response.json()
        serialized = json.dumps(payload, ensure_ascii=False)
        assert len(serialized) > 200, route
        assert "Andritz" not in serialized
        assert "agenda QA" not in serialized
        assert "qa wiring" not in serialized.lower()
        assert "transfert-aborted" not in serialized
        assert "SFTP / Secure Deposit" not in serialized


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
