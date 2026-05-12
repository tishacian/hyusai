from __future__ import annotations

from app.models.capability import Capability
from app.models.intelligence import FeedSource
from app.models.rag_preset import RagPreset
from app.models.system import System
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services.intelligence.batch import ensure_intelligence_defaults
from app.services.mission_room import SENTINEL_WORKSPACE_SLUG, ensure_sentinel_ci_workspace
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
    assert workspace.settings["default_route"] == "/hypervisor/mission-room"
    assert workspace.settings["hide_provider_details"] is True
    assert db_session.query(WorkspaceMember).filter_by(workspace_id=workspace.id).count() == 1
    assert db_session.query(System).filter_by(workspace_id=workspace.id).count() == 6
    assert db_session.query(FeedSource).filter_by(workspace_id=workspace.id).count() >= 3
    preset = db_session.query(RagPreset).filter_by(workspace_id=workspace.id, is_default=True).one()
    assert preset.config["mode"] == "chah"
    assert preset.config["asyncRetrieval"] is True


def test_government_capabilities_and_skills_are_seeded_and_bound(db_session):
    seed_skills_and_capabilities(db_session)

    for slug in [
        "government_mission_room",
        "ministerial_daily_briefing",
        "open_intelligence_watch",
        "strategic_project_pilotage",
        "territorial_action_map",
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
    ]:
        assert statuses[slug] == "bound"


def test_intelligence_defaults_are_workspace_scoped(db_session):
    global_added = ensure_intelligence_defaults(db_session)
    workspace_added = ensure_intelligence_defaults(db_session, workspace_id="workspace-demo")

    assert global_added is True
    assert workspace_added is True
    assert db_session.query(FeedSource).filter(FeedSource.workspace_id.is_(None)).count() == 2
    assert db_session.query(FeedSource).filter(FeedSource.workspace_id == "workspace-demo").count() == 2
