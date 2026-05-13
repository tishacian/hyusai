from __future__ import annotations

from app.models.capability import Capability
from app.models.action_plan import WorkspaceActionItem
from app.models.calendar import WorkspaceCalendarEvent
from app.models.intelligence import FeedSource
from app.models.rag_preset import RagPreset
from app.models.system import System
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.models.workspace_visual import WorkspaceVisualSource
from app.services.intelligence.batch import ensure_intelligence_defaults
from app.services.mission_room import SENTINEL_WORKSPACE_SLUG, ensure_sentinel_ci_workspace, navigation_payload
from app.services.rag_preset_service import RagPresetService
from app.services.skills_registry import bound_slugs, seed_skills_and_capabilities


def test_sentinel_ci_seed_is_idempotent_and_demo_scoped(db_session):
    user = User(
        id="user-demo-admin",
        username="demo-admin",
        email="demo-admin@example.test",
        role="admin",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()

    seed_skills_and_capabilities(db_session)
    first = ensure_sentinel_ci_workspace(db_session)
    second = ensure_sentinel_ci_workspace(db_session)

    workspace = db_session.query(Workspace).filter(Workspace.slug == SENTINEL_WORKSPACE_SLUG).one()
    assert first["workspace_created"] == 1
    assert second["workspace_created"] == 0
    assert workspace.mode == "demo"
    assert workspace.settings["default_route"] == "/hypervisor/mission-room/cockpit"
    assert workspace.settings["workspace_app_shell"] == "immersive"
    assert workspace.settings["workspace_app_default_view"] == "cockpit"
    assert workspace.settings["hide_provider_details"] is True
    assert workspace.settings["mission_room"]["label"] == "VIGIE"
    assert len(workspace.settings["mission_room"]["navigation"]) >= 10
    assert workspace.settings["assistant_profile_default"] == "vigie_executive"
    assert workspace.settings["assistant_profiles"][0]["default_knowledge_scope"] == "vigie"
    assert workspace.settings["calendar"]["connector_id"] == "institutional_calendar"
    assert workspace.settings["calendar"]["write_policy"] == "direct"
    assert workspace.settings["action_planner"]["write_policy"] == "direct"
    assert workspace.settings["demo_time_context"]["current_date"] == "2026-04-15"
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
    ]
    assert db_session.query(WorkspaceMember).filter_by(workspace_id=workspace.id).count() == 1
    assert db_session.query(System).filter_by(workspace_id=workspace.id).count() == 7
    assert db_session.query(WorkspaceCalendarEvent).filter_by(workspace_id=workspace.id).count() >= 7
    assert db_session.query(WorkspaceActionItem).filter_by(workspace_id=workspace.id).count() >= 3
    assert db_session.query(WorkspaceVisualSource).filter_by(workspace_id=workspace.id).count() == 1
    assert db_session.query(FeedSource).filter_by(workspace_id=workspace.id).count() >= 3
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
        "strategic_project_pilotage",
        "territorial_action_map",
        "visual_situation_watch",
        "executive_instruction_drafting",
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
    veille = next(item for item in payload["items"] if item["key"] == "veille")

    assert presse["system_name"] == "Veille Presse & Signaux Faibles"
    assert veille["system_id"] == presse["system_id"]


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
