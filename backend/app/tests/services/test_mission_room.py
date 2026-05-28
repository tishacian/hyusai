from __future__ import annotations

from app.models.capability import Capability
from app.models.action_plan import WorkspaceActionItem
from app.models.calendar import WorkspaceCalendarEvent
from app.models.intelligence import FeedSource
from app.models.rag_preset import RagPreset
from app.models.knowledge_guide import KnowledgeGuide
from app.models.system import System
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.models.workspace_visual import WorkspaceVisualSource
from app.services.intelligence.batch import ensure_intelligence_defaults
from app.services.document_intelligence import resolve_document_profile
from app.services.knowledge_guides import effective_guides
from app.services.mission_room import SENTINEL_WORKSPACE_SLUG, ensure_sentinel_ci_workspace, navigation_payload
from app.services.rag_preset_service import RagPresetService
from app.services.skills_registry import bound_slugs, seed_skills_and_capabilities
from app.services.demo_time_context import resolve_demo_date


def test_sentinel_ci_seed_is_idempotent_and_demo_scoped(db_session):
    user = User(
        id="user-demo-admin",
        username="demo-admin",
        email="demo-admin@example.test",
        role="admin",
        is_active=True,
    )
    outsider = User(
        id="user-demo-outsider",
        username="demo-outsider",
        email="demo-outsider@example.test",
        role="user",
        is_active=True,
    )
    db_session.add_all([user, outsider])
    db_session.commit()

    seed_skills_and_capabilities(db_session)
    first = ensure_sentinel_ci_workspace(db_session)
    second = ensure_sentinel_ci_workspace(db_session)

    workspace = db_session.query(Workspace).filter(Workspace.slug == SENTINEL_WORKSPACE_SLUG).one()
    assert first["workspace_created"] == 1
    assert second["workspace_created"] == 0
    assert first["members_added"] == 0
    assert second["members_added"] == 0
    assert workspace.mode == "demo"
    assert workspace.settings["default_route"] == "/hypervisor/mission-room/cockpit"
    assert workspace.settings["workspace_app_shell"] == "immersive"
    assert workspace.settings["workspace_app_default_view"] == "cockpit"
    assert workspace.settings["hide_provider_details"] is True
    assert workspace.settings["mission_room"]["label"] == "AYA"
    assert [item["key"] for item in workspace.settings["mission_room"]["navigation"]] == [
        "cockpit",
        "strategie",
        "securite",
        "reputation",
        "agenda",
        "presse",
        "decisions",
    ]
    assert workspace.settings["assistant_profile_default"] == "vigie_executive"
    assert workspace.settings["assistant_profiles"][0]["default_knowledge_scope"] == "vigie"
    assert workspace.settings["assistant_profiles"][0]["grounding"]["default_mode"] == "balanced"
    assert workspace.settings["calendar"]["connector_id"] == "institutional_calendar"
    assert workspace.settings["calendar"]["write_policy"] == "direct"
    assert workspace.settings["action_planner"]["write_policy"] == "direct"
    assert workspace.settings["actions"]["enabled_packs"] == [
        "global_voice_v1",
        "sentinel_ci_aya_v1",
        "sentinel_ci_aya_security_v1",
    ]
    assert workspace.settings["voice_loop"]["default_mode"] == "session_loop"
    assert workspace.settings["voice_loop"]["enabled_default"] is False
    assert workspace.settings["voice_loop"]["manual_start_required"] is True
    assert workspace.settings["voice_loop"]["commands_enabled"] is True
    assert workspace.settings["voice_output"]["latency_profile"] == "fast"
    assert workspace.settings["voice_output"]["flush_first_chars"] == 18
    assert workspace.settings["voice_output"]["flush_next_chars"] == 56
    assert workspace.settings["voice_output"]["flush_timeout_ms"] == 450
    assert workspace.settings["document_intelligence"]["default_profile"] == "sentinel_ci_ministerial"
    assert workspace.settings["document_intelligence"]["ocr"]["enabled"] is True
    assert workspace.settings["demo_time_context"]["current_date"] == resolve_demo_date().isoformat()
    assert workspace.settings["demo_time_context"]["mode"] == "rolling"
    assert workspace.settings["connectors"]["institutional_calendar"]["enabled"] is True
    assert workspace.settings["connectors"]["visual_streams"]["enabled"] is True
    assert workspace.settings["visual_intelligence"]["enabled"] is True
    assert workspace.settings["knowledge_scopes"][0]["collection_slugs"] == [
        "sentinel-ci-open-intelligence",
        "sentinel-ci-projects",
        "sentinel-ci-ministerial-briefs",
        "sentinel-ci-territorial-map",
        "sentinel-ci-territorial-intelligence",
        "sentinel-ci-visual-intelligence",
        "sentinel-ci-maritime-intelligence",
        "sentinel-ci-evidence-graph",
        "sentinel-ci-security-briefs",
    ]
    assert db_session.query(WorkspaceMember).filter_by(workspace_id=workspace.id).count() == 0
    db_session.add(
        WorkspaceMember(
            workspace_id=workspace.id,
            user_id=user.id,
            role="owner",
            role_template="workspace_owner",
            custom_labels=["explicit:test-owner"],
        )
    )
    db_session.commit()
    third = ensure_sentinel_ci_workspace(db_session)
    members = db_session.query(WorkspaceMember).filter_by(workspace_id=workspace.id).all()
    assert third["members_added"] == 0
    assert len(members) == 1
    assert members[0].user_id == user.id
    assert db_session.query(System).filter_by(workspace_id=workspace.id).count() >= 15
    assert db_session.query(WorkspaceCalendarEvent).filter_by(workspace_id=workspace.id).count() >= 7
    assert db_session.query(WorkspaceActionItem).filter_by(workspace_id=workspace.id).count() >= 3
    assert db_session.query(WorkspaceVisualSource).filter_by(workspace_id=workspace.id).count() >= 8
    feeds = db_session.query(FeedSource).filter_by(workspace_id=workspace.id).all()
    assert len(feeds) >= 12
    assert {feed.category for feed in feeds} >= {"ci-local", "ci-agency", "ci-public", "ci-national", "cedeao", "world"}
    assert workspace.settings["mission_room"]["region_scope"] == ["Cote d'Ivoire", "West Africa", "Sahel", "Gulf of Guinea"]
    assert "trace_rumor_origin" in workspace.settings["assistant_profiles"][0]["allowed_actions"]
    assert workspace.settings["assistant_profiles"][0]["actions"]["enabled_packs"] == [
        "global_voice_v1",
        "sentinel_ci_aya_v1",
        "sentinel_ci_aya_security_v1",
    ]
    assert workspace.settings["assistant_profiles"][0]["voice_loop"]["default_mode"] == "session_loop"
    assert workspace.settings["assistant_profiles"][0]["voice_loop"]["enabled_default"] is False
    assert workspace.settings["assistant_profiles"][0]["voice_loop"]["manual_start_required"] is True
    assert workspace.settings["assistant_profiles"][0]["voice_output"]["flush_timeout_ms"] == 450
    assert workspace.settings["assistant_profiles"][0]["response_style"]["address_as"] == "Monsieur le Vice Premier Ministre"
    guides = db_session.query(KnowledgeGuide).filter_by(workspace_id=workspace.id, is_current=True).all()
    assert {guide.guide_key for guide in guides} >= {
        "sentinel-ci-aya-mission-room-v1",
        "sentinel-ci-open-intelligence-v1",
        "sentinel-ci-territorial-map-v1",
        "sentinel-ci-doc-intelligence-v1",
    }
    assert {guide.target_type for guide in guides} >= {"scope", "collection"}
    effective = effective_guides(
        db_session,
        workspace_id=workspace.id,
        scope_key="vigie",
        collection_slugs=["sentinel-ci-open-intelligence", "sentinel-ci-ministerial-briefs"],
    )
    assert {guide.guide_key for guide in effective} >= {
        "sentinel-ci-aya-mission-room-v1",
        "sentinel-ci-open-intelligence-v1",
        "sentinel-ci-doc-intelligence-v1",
    }
    document_profile = resolve_document_profile(workspace=workspace)
    assert document_profile.source == "workspace_profile"
    assert document_profile.profile["key"] == "sentinel_ci_ministerial"
    assert document_profile.profile["synonyms"]["decision"] == ["arbitrage", "instruction", "validation", "deadline"]
    preset = db_session.query(RagPreset).filter_by(workspace_id=workspace.id, is_default=True).one()
    assert preset.scope_id == workspace.id
    assert preset.config["mode"] == "chah"
    assert preset.config["ragPipelineMode"] == "chah"
    assert preset.config["ragCollectionName"] == "sentinel-ci-open-intelligence"
    assert preset.config["ragTopK"] == 6
    assert preset.config["asyncRetrieval"] is True


def test_government_capabilities_and_skills_are_seeded_and_bound(db_session):
    seed_skills_and_capabilities(db_session)

    for slug in [
        "government_mission_room",
        "ministerial_daily_briefing",
        "open_intelligence_watch",
        "scenario_fusion_monitor",
        "strategic_project_pilotage",
        "territorial_action_map",
        "visual_situation_watch",
        "government_calendar_assist",
        "aya_voice_command",
        "executive_instruction_drafting",
        "osint_rumor_intelligence",
        "evidence_graph",
        "maritime_customs_watch",
        "strategic_forecasts",
        "decision_desk",
    ]:
        assert db_session.query(Capability).filter(Capability.slug == slug).one()

    statuses = bound_slugs()
    for slug in [
        "ministerial_briefing_v1",
        "news_signal_synthesis_v1",
        "project_risk_explainer_v1",
        "territorial_signal_map_v1",
        "instruction_draft_v1",
        "calendar_read_v1",
        "calendar_create_event_v1",
        "calendar_update_event_v1",
        "calendar_cancel_event_v1",
        "calendar_daily_summary_v1",
        "action_plan_create_v1",
        "action_plan_reschedule_v1",
        "action_plan_status_v1",
        "action_plan_cancel_v1",
        "time_context_set_v1",
        "territorial_action_window_v1",
        "map_command_apply_v1",
        "visual_source_read_v1",
        "visual_snapshot_capture_v1",
        "visual_snapshot_analyze_v1",
        "visual_observation_sync_knowledge_v1",
        "source_registry_refresh_v1",
        "osint_signal_prioritize_v1",
        "rumor_origin_trace_v1",
        "evidence_graph_build_v1",
        "situation_posture_score_v1",
        "maritime_snapshot_read_v1",
        "decision_option_rank_v1",
        "draft_response_email_v1",
    ]:
        assert statuses[slug] == "bound"


def test_intelligence_defaults_are_workspace_scoped(db_session):
    global_added = ensure_intelligence_defaults(db_session)
    workspace_added = ensure_intelligence_defaults(db_session, workspace_id="workspace-demo")

    assert global_added is True
    assert workspace_added is True
    assert db_session.query(FeedSource).filter(FeedSource.workspace_id.is_(None)).count() == 2
    assert db_session.query(FeedSource).filter(FeedSource.workspace_id == "workspace-demo").count() == 2


def test_mission_room_navigation_prefers_workspace_intelligence_system(db_session):
    seed_skills_and_capabilities(db_session)
    ensure_sentinel_ci_workspace(db_session)
    workspace = db_session.query(Workspace).filter(Workspace.slug == SENTINEL_WORKSPACE_SLUG).one()

    # Simulate the generic boot seed adding a second variant=intelligence System.
    capability = db_session.query(Capability).filter(Capability.slug == "open_intelligence_watch").one()
    db_session.add(
        System(
            workspace_id=workspace.id,
            name="News Lab",
            objective="Generic intelligence system",
            capability_id=capability.id,
            flow_definition={"variant": "intelligence"},
            status="active",
        )
    )
    db_session.commit()

    payload = navigation_payload(db_session, workspace)
    presse = next(item for item in payload["items"] if item["key"] == "presse")

    assert presse["system_name"] == "Veille Presse & Signaux Faibles"
    assert "veille" not in {item["key"] for item in payload["items"]}


def test_rag_preset_resolver_does_not_borrow_other_workspace_defaults(db_session):
    a = Workspace(id="workspace-a", slug="andritz", name="Andritz")
    b = Workspace(id="workspace-b", slug="sentinel-ci", name="SENTINEL-CI")
    db_session.add_all([a, b])
    db_session.add(
        RagPreset(
            workspace_id=a.id,
            name="Andritz default",
            scope="workspace",
            scope_id=a.id,
            config={"ragCollectionName": "andritz-secure-deposit"},
            is_default=True,
        )
    )
    db_session.commit()

    resolved = RagPresetService.resolve_for(db_session, workspace_id=b.id)

    assert resolved["ragCollectionName"] == "documents"
