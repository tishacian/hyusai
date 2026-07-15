from __future__ import annotations

import json

import pytest

from app.models.action_plan import WorkspaceActionItem
from app.models.audit import AuditLog
from app.models.calendar import WorkspaceCalendarEvent
from app.models.capability import Capability
from app.models.intelligence import FeedSource
from app.models.knowledge_collection import KnowledgeCollection
from app.models.knowledge_guide import KnowledgeGuide
from app.models.rag_preset import RagPreset
from app.models.system import System
from app.models.user import User
from app.models.workspace import (
    Workspace,
    WorkspaceMember,
    WorkspaceMemberAppEntitlement,
)
from app.models.workspace_map import (
    WorkspaceMap,
    WorkspaceMapLayer,
    WorkspaceMapScore,
    WorkspaceMapSignal,
    WorkspaceMapZone,
)
from app.models.workspace_visual import WorkspaceVisualSource
from app.services.demo_time_context import resolve_demo_date
from app.services.document_intelligence import resolve_document_profile
from app.services.iam.app_entitlements import (
    APP_ENTITLEMENTS_FEATURE,
    BUSINESS_APP_KEYS,
    lock_workspace_for_app_entitlement_mutation,
)
from app.services.intelligence.batch import ensure_intelligence_defaults
from app.services.knowledge_guides import effective_guides
from app.services.mission_room import (
    OCTOCITY_MISSION_ROOM_PROFILE,
    OCTOCITY_WORKSPACE_SLUG,
    SENTINEL_MISSION_ROOM_PROFILE,
    SENTINEL_WORKSPACE_SLUG,
    cockpit_payload,
    ensure_octocity_mission_room_workspace,
    ensure_sentinel_ci_workspace,
    is_octocity_mission_room,
    map_payload,
    navigation_payload,
    octocity_forbidden_terms_present,
    present_payload_for_workspace,
)
from app.services.rag_preset_service import RagPresetService
from app.services.skills_registry import bound_slugs, seed_skills_and_capabilities
from app.services.workspace_maps import (
    OCTOCITY_MAP_FIXTURE_PROFILE,
    OCTOCITY_MAP_SLUG,
    SENTINEL_MAP_SLUG,
    ensure_workspace_map_seed,
    handle_map_chat_query,
)


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
    assert workspace.settings["mission_room"]["profile"] == SENTINEL_MISSION_ROOM_PROFILE
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
    assert (
        workspace.settings["document_intelligence"]["default_profile"] == "sentinel_ci_ministerial"
    )
    assert workspace.settings["document_intelligence"]["ocr"]["enabled"] is True
    assert (
        workspace.settings["demo_time_context"]["current_date"] == resolve_demo_date().isoformat()
    )
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
    assert (
        db_session.query(WorkspaceCalendarEvent).filter_by(workspace_id=workspace.id).count() >= 7
    )
    assert db_session.query(WorkspaceActionItem).filter_by(workspace_id=workspace.id).count() >= 3
    assert db_session.query(WorkspaceVisualSource).filter_by(workspace_id=workspace.id).count() >= 8
    feeds = db_session.query(FeedSource).filter_by(workspace_id=workspace.id).all()
    assert len(feeds) >= 12
    assert {feed.category for feed in feeds} >= {
        "ci-local",
        "ci-agency",
        "ci-public",
        "ci-national",
        "cedeao",
        "world",
    }
    assert workspace.settings["mission_room"]["region_scope"] == [
        "Cote d'Ivoire",
        "West Africa",
        "Sahel",
        "Gulf of Guinea",
    ]
    assert "trace_rumor_origin" in workspace.settings["assistant_profiles"][0]["allowed_actions"]
    assert workspace.settings["assistant_profiles"][0]["actions"]["enabled_packs"] == [
        "global_voice_v1",
        "sentinel_ci_aya_v1",
        "sentinel_ci_aya_security_v1",
    ]
    assert (
        workspace.settings["assistant_profiles"][0]["voice_loop"]["default_mode"] == "session_loop"
    )
    assert workspace.settings["assistant_profiles"][0]["voice_loop"]["enabled_default"] is False
    assert (
        workspace.settings["assistant_profiles"][0]["voice_loop"]["manual_start_required"] is True
    )
    assert workspace.settings["assistant_profiles"][0]["voice_output"]["flush_timeout_ms"] == 450
    assert (
        workspace.settings["assistant_profiles"][0]["response_style"]["address_as"]
        == "Monsieur le Vice Premier Ministre"
    )
    sentinel_navigation = present_payload_for_workspace(
        workspace,
        navigation_payload(db_session, workspace),
    )
    assert sentinel_navigation["app"]["label"] == "SENTINEL-CI"
    assert sentinel_navigation["app"]["assistant_label"] == "AYA"
    assert sentinel_navigation["app"]["profile"] == SENTINEL_MISSION_ROOM_PROFILE
    sentinel_runtime = json.dumps(sentinel_navigation, ensure_ascii=False)
    for forbidden in ("Octocity", "OCTAVE", "octocity_", "octave."):
        assert forbidden not in sentinel_runtime
    guides = (
        db_session.query(KnowledgeGuide).filter_by(workspace_id=workspace.id, is_current=True).all()
    )
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
    assert document_profile.profile["synonyms"]["decision"] == [
        "arbitrage",
        "instruction",
        "validation",
        "deadline",
    ]
    preset = db_session.query(RagPreset).filter_by(workspace_id=workspace.id, is_default=True).one()
    assert preset.scope_id == workspace.id
    assert preset.config["mode"] == "chah"
    assert preset.config["ragPipelineMode"] == "chah"
    assert preset.config["ragCollectionName"] == "sentinel-ci-open-intelligence"
    assert preset.config["ragTopK"] == 6
    assert preset.config["asyncRetrieval"] is True


def test_sentinel_existing_workspace_locks_before_seed_mutations(db_session, monkeypatch):
    workspace = Workspace(
        id="workspace-sentinel-existing-lock",
        slug=SENTINEL_WORKSPACE_SLUG,
        name="Legacy Sentinel name",
        mode="demo",
        settings={"runtime_setting": {"preserve": True}},
    )
    db_session.add(workspace)
    db_session.commit()
    seed_skills_and_capabilities(db_session)

    lock_observations: list[dict[str, object]] = []
    original_lock = lock_workspace_for_app_entitlement_mutation

    def _tracking_lock(db, workspace_id):
        locked = original_lock(db, workspace_id)
        lock_observations.append(
            {
                "workspace_id": locked.id,
                "name_before_seed": locked.name,
                "mission_room_before_seed": (locked.settings or {}).get("mission_room"),
            }
        )
        return locked

    monkeypatch.setattr(
        "app.services.mission_room.lock_workspace_for_app_entitlement_mutation",
        _tracking_lock,
    )

    first = ensure_sentinel_ci_workspace(db_session)
    second = ensure_sentinel_ci_workspace(db_session)
    db_session.refresh(workspace)

    assert first["workspace_created"] == 0
    assert second["workspace_created"] == 0
    assert len(lock_observations) == 2
    assert lock_observations[0] == {
        "workspace_id": workspace.id,
        "name_before_seed": "Legacy Sentinel name",
        "mission_room_before_seed": None,
    }
    assert workspace.settings["runtime_setting"] == {"preserve": True}


def test_octocity_runtime_selection_uses_profile_not_workspace_slug(db_session):
    slug_only = Workspace(
        id="workspace-octocity-slug-only",
        slug=OCTOCITY_WORKSPACE_SLUG,
        name="Slug-only workspace",
        mode="demo",
        settings={},
    )
    profiled = Workspace(
        id="workspace-octocity-profiled",
        slug="portable-mission-room",
        name="Profiled workspace",
        mode="demo",
        settings={"mission_room": {"profile": OCTOCITY_MISSION_ROOM_PROFILE}},
    )
    db_session.add_all([slug_only, profiled])
    db_session.flush()

    slug_only_map = ensure_workspace_map_seed(db_session, slug_only)
    profiled_map = ensure_workspace_map_seed(db_session, profiled)

    assert is_octocity_mission_room(slug_only) is False
    assert is_octocity_mission_room(profiled) is True
    assert present_payload_for_workspace(slug_only, {"assistant": "AYA"}) == {"assistant": "AYA"}
    assert present_payload_for_workspace(profiled, {"assistant": "AYA"}) == {"assistant": "OCTAVE"}
    assert slug_only_map.slug == SENTINEL_MAP_SLUG
    assert profiled_map.slug == OCTOCITY_MAP_SLUG


def test_octocity_existing_entitlement_workspace_locks_and_grants_seed_owner(
    db_session,
    monkeypatch,
):
    owner_email = "octocity-entitled-owner@example.test"
    owner = User(
        id="user-octocity-entitled-owner",
        username="octocity-entitled-owner",
        email=owner_email,
        role="admin",
        is_active=True,
    )
    workspace = Workspace(
        id="workspace-octocity-entitled-existing",
        slug=OCTOCITY_WORKSPACE_SLUG,
        name="Legacy Octocity name",
        mode="demo",
        settings={
            "features": {APP_ENTITLEMENTS_FEATURE: True},
            "runtime_setting": {"preserve": True},
        },
    )
    db_session.add_all([owner, workspace])
    db_session.commit()
    seed_skills_and_capabilities(db_session)

    lock_observations: list[dict[str, object]] = []
    original_lock = lock_workspace_for_app_entitlement_mutation

    def _tracking_lock(db, workspace_id):
        locked = original_lock(db, workspace_id)
        lock_observations.append(
            {
                "workspace_id": locked.id,
                "name_before_seed": locked.name,
                "mission_room_before_seed": (locked.settings or {}).get("mission_room"),
            }
        )
        return locked

    monkeypatch.setattr(
        "app.services.mission_room.lock_workspace_for_app_entitlement_mutation",
        _tracking_lock,
    )
    monkeypatch.setenv("OCTOCITY_OWNER_EMAILS", owner_email)

    first = ensure_octocity_mission_room_workspace(db_session)
    second = ensure_octocity_mission_room_workspace(db_session)

    membership = (
        db_session.query(WorkspaceMember)
        .filter_by(workspace_id=workspace.id, user_id=owner.id)
        .one()
    )
    grants = (
        db_session.query(WorkspaceMemberAppEntitlement)
        .filter_by(workspace_member_id=membership.id)
        .order_by(WorkspaceMemberAppEntitlement.app_key.asc())
        .all()
    )
    db_session.refresh(workspace)

    assert first["workspace_created"] == 0
    assert first["members_added"] == 1
    assert second["members_added"] == 0
    assert len(lock_observations) == 2
    assert lock_observations[0] == {
        "workspace_id": workspace.id,
        "name_before_seed": "Legacy Octocity name",
        "mission_room_before_seed": None,
    }
    assert workspace.settings["runtime_setting"] == {"preserve": True}
    assert workspace.settings["features"][APP_ENTITLEMENTS_FEATURE] is True
    assert [row.app_key for row in grants] == sorted(BUSINESS_APP_KEYS)
    assert {row.grant_source for row in grants} == {"octocity_seed_owner"}


def test_octocity_mission_room_seed_is_idempotent_and_anonymized(db_session, monkeypatch, caplog):
    owner_email = "octocity-owner@example.test"
    monkeypatch.setenv("OCTOCITY_OWNER_EMAILS", owner_email)
    owner = User(
        id="user-octocity-owner",
        username="octocity-owner",
        email=owner_email,
        role="admin",
        is_active=True,
    )
    db_session.add(owner)
    db_session.commit()

    seed_skills_and_capabilities(db_session)
    first = ensure_octocity_mission_room_workspace(db_session)
    monkeypatch.delenv("OCTOCITY_OWNER_EMAILS")
    second = ensure_octocity_mission_room_workspace(db_session)

    workspace = db_session.query(Workspace).filter(Workspace.slug == OCTOCITY_WORKSPACE_SLUG).one()
    assert first["workspace_created"] == 1
    assert second["workspace_created"] == 0
    assert first["members_added"] == 1
    assert second["members_added"] == 0
    assert "existing memberships are preserved" in caplog.text
    assert first["systems_created"] == 6
    assert second["systems_created"] == 0
    assert workspace.name == "Octocity Mission Room"
    assert workspace.mode == "demo"
    assert workspace.settings["workspace_app_label"] == "Octocity Mission Room"
    assert workspace.settings["assistant_profile_default"] == "octave_executive"
    assert workspace.settings["voice_loop"]["trigger_word"] == "OCTAVE"
    assert workspace.settings["actions"]["enabled_packs"] == [
        "global_voice_v1",
        "octave_mission_room_v1",
        "octave_security_v1",
    ]
    assert workspace.settings["mission_room"]["profile"] == OCTOCITY_MISSION_ROOM_PROFILE
    assert (
        workspace.settings["mission_room"]["brand"]["emblem"] == "/assets/brand/agentium-mark.svg"
    )
    assert workspace.settings["workspace_app_label"] != "SENTINEL-CI"
    assert "sentinel_ci_aya_v1" not in workspace.settings["actions"]["enabled_packs"]
    assert (
        db_session.query(WorkspaceMember)
        .filter_by(
            workspace_id=workspace.id,
            user_id=owner.id,
        )
        .one()
    )

    systems = db_session.query(System).filter_by(workspace_id=workspace.id).all()
    system_names = {row.name for row in systems}
    assert {
        "OCTAVE Mission Room",
        "OCTAVE Territorial Map",
        "OCTAVE Open Intelligence",
        "OCTAVE Decision Desk",
        "Workspace Chat",
        "Knowledge Capture",
    }.issubset(system_names)
    octave_systems = [row for row in systems if row.name.startswith("OCTAVE ")]
    assert {(row.flow_definition or {}).get("variant") for row in octave_systems} == {
        "octocity_mission_room",
        "octocity_territorial_map",
        "octocity_intelligence",
        "octocity_decision_desk",
    }
    assert all(
        str((row.flow_definition or {}).get("template_id", "")).startswith("octocity-")
        for row in octave_systems
    )
    assert all(
        "sentinel" not in f"{row.name} {row.objective} {row.flow_definition}".lower()
        for row in octave_systems
    )
    capability_slugs = {
        row.id: row.slug
        for row in db_session.query(Capability)
        .filter(Capability.id.in_([system.capability_id for system in octave_systems]))
        .all()
    }
    assert {row.name: capability_slugs[row.capability_id] for row in octave_systems} == {
        "OCTAVE Mission Room": "government_mission_room",
        "OCTAVE Territorial Map": "territorial_action_map",
        "OCTAVE Open Intelligence": "open_intelligence_watch",
        "OCTAVE Decision Desk": "executive_instruction_drafting",
    }

    collection_slugs = {
        row.slug
        for row in db_session.query(KnowledgeCollection)
        .filter(KnowledgeCollection.workspace_id == workspace.id)
        .all()
    }
    assert {
        "octocity-open-intelligence",
        "octocity-ministerial-briefs",
        "octocity-knowledge-capture",
        "octocity-evidence-graph",
    }.issubset(collection_slugs)
    assert all(slug.startswith("octocity-") for slug in collection_slugs)

    preset = db_session.query(RagPreset).filter_by(workspace_id=workspace.id, is_default=True).one()
    assert preset.config["ragCollectionName"] == "octocity-open-intelligence"

    nav = present_payload_for_workspace(
        workspace,
        navigation_payload(db_session, workspace),
    )
    assert nav["app"]["assistant_label"] == "OCTAVE"
    assert nav["app"]["brand"]["style"] == "agentium"

    cockpit = present_payload_for_workspace(workspace, cockpit_payload(workspace, db_session))
    assert cockpit["workspace"]["slug"] == OCTOCITY_WORKSPACE_SLUG
    assert cockpit["fused_map_preview"]["geo_preview"]["camera"]["bounds"] == [
        [-5.3, 42.35],
        [8.1, 50.8],
    ]
    assert octocity_forbidden_terms_present(cockpit) == []

    mission_map = present_payload_for_workspace(workspace, map_payload(workspace, db_session))
    assert octocity_forbidden_terms_present(mission_map) == []

    member = (
        db_session.query(WorkspaceMember)
        .filter_by(workspace_id=workspace.id, user_id=owner.id)
        .one()
    )
    assert member.role == "owner"
    assert member.role_template == "workspace_owner"
    assert member.custom_labels == ["octocity:video-owner"]

    member.role = "member"
    member.role_template = "workspace_member"
    member.custom_labels = ["explicit:test-member"]
    db_session.commit()
    third = ensure_octocity_mission_room_workspace(db_session)
    db_session.refresh(member)
    assert third["members_added"] == 0
    assert member.role == "member"
    assert member.role_template == "workspace_member"
    assert member.custom_labels == ["explicit:test-member"]


def test_octocity_upgrade_rebinds_and_replaces_legacy_sentinel_map_fixture(db_session):
    workspace = Workspace(
        id="workspace-octocity-upgrade",
        slug="octocity-upgrade-pending",
        name="Legacy Octocity",
        mode="demo",
        settings={},
    )
    db_session.add(workspace)
    db_session.commit()

    legacy_map = ensure_workspace_map_seed(db_session, workspace)
    legacy_map_id = legacy_map.id
    db_session.commit()
    assert legacy_map.slug == SENTINEL_MAP_SLUG
    assert legacy_map.system_id is None
    assert legacy_map.country == "Cote d'Ivoire"
    legacy_fixture_ids = {
        "layers": {
            row.id
            for row in db_session.query(WorkspaceMapLayer).filter_by(map_id=legacy_map.id).all()
        },
        "zones": {
            row.id
            for row in db_session.query(WorkspaceMapZone).filter_by(map_id=legacy_map.id).all()
        },
        "signals": {
            row.id
            for row in db_session.query(WorkspaceMapSignal).filter_by(map_id=legacy_map.id).all()
        },
        "scores": {
            row.id
            for row in db_session.query(WorkspaceMapScore).filter_by(map_id=legacy_map.id).all()
        },
    }

    workspace.slug = OCTOCITY_WORKSPACE_SLUG
    db_session.commit()
    seed_skills_and_capabilities(db_session)
    ensure_octocity_mission_room_workspace(db_session)

    map_row = db_session.query(WorkspaceMap).filter_by(workspace_id=workspace.id).one()
    map_system = (
        db_session.query(System)
        .filter_by(
            workspace_id=workspace.id,
            name="OCTAVE Territorial Map",
        )
        .one()
    )
    assert map_row.id == legacy_map_id
    assert map_row.slug == OCTOCITY_MAP_SLUG
    assert map_row.system_id == map_system.id
    assert map_row.country == "France"
    assert map_row.settings["fixture_profile"] == OCTOCITY_MAP_FIXTURE_PROFILE
    assert legacy_fixture_ids["layers"].issubset(
        {row.id for row in db_session.query(WorkspaceMapLayer).filter_by(map_id=map_row.id).all()}
    )
    assert legacy_fixture_ids["zones"] == {
        row.id for row in db_session.query(WorkspaceMapZone).filter_by(map_id=map_row.id).all()
    }
    assert legacy_fixture_ids["signals"].issubset(
        {row.id for row in db_session.query(WorkspaceMapSignal).filter_by(map_id=map_row.id).all()}
    )
    assert legacy_fixture_ids["scores"] == {
        row.id for row in db_session.query(WorkspaceMapScore).filter_by(map_id=map_row.id).all()
    }

    persisted_fixture = {
        "map": {
            "slug": map_row.slug,
            "name": map_row.name,
            "description": map_row.description,
            "country": map_row.country,
            "projection": map_row.projection,
            "settings": map_row.settings,
        },
        "layers": [
            {"key": row.key, "label": row.label, "payload": row.payload}
            for row in db_session.query(WorkspaceMapLayer).filter_by(map_id=map_row.id).all()
        ],
        "zones": [
            {
                "key": row.zone_key,
                "name": row.name,
                "metadata": row.meta_data,
                "sources": row.source_refs,
            }
            for row in db_session.query(WorkspaceMapZone).filter_by(map_id=map_row.id).all()
        ],
        "signals": [
            {
                "source_id": row.source_id,
                "title": row.title,
                "summary": row.summary,
                "metadata": row.meta_data,
            }
            for row in db_session.query(WorkspaceMapSignal).filter_by(map_id=map_row.id).all()
        ],
    }
    fixture_text = json.dumps(persisted_fixture, ensure_ascii=False)
    for forbidden in ("sentinel", "cote d'ivoire", "côte d'ivoire", "abidjan", "aya"):
        assert forbidden not in fixture_text.lower()
    assert all(
        (row.meta_data or {}).get("seed") == "octocity"
        for row in db_session.query(WorkspaceMapSignal).filter_by(map_id=map_row.id).all()
    )

    first_zone_count = db_session.query(WorkspaceMapZone).filter_by(map_id=map_row.id).count()
    first_score_ids = {
        row.id for row in db_session.query(WorkspaceMapScore).filter_by(map_id=map_row.id).all()
    }
    first_signal_ids = {
        row.id for row in db_session.query(WorkspaceMapSignal).filter_by(map_id=map_row.id).all()
    }
    first_upgrade_events = (
        db_session.query(AuditLog)
        .filter_by(
            workspace_id=workspace.id,
            event_type="map.system.upgraded",
        )
        .count()
    )
    assert first_zone_count == 5
    assert len(first_score_ids) == 5
    assert len(first_signal_ids) == 11
    assert first_upgrade_events == 1

    ensure_octocity_mission_room_workspace(db_session)
    assert db_session.query(WorkspaceMap).filter_by(workspace_id=workspace.id).count() == 1
    assert db_session.query(WorkspaceMap).filter_by(id=legacy_map_id, system_id=map_system.id).one()
    assert (
        db_session.query(WorkspaceMapZone).filter_by(map_id=map_row.id).count() == first_zone_count
    )
    assert {
        row.id for row in db_session.query(WorkspaceMapScore).filter_by(map_id=map_row.id).all()
    } == first_score_ids
    assert {
        row.id for row in db_session.query(WorkspaceMapSignal).filter_by(map_id=map_row.id).all()
    } == first_signal_ids
    assert (
        db_session.query(AuditLog)
        .filter_by(
            workspace_id=workspace.id,
            event_type="map.system.upgraded",
        )
        .count()
        == first_upgrade_events
    )


def test_octocity_map_seed_repairs_a_missing_zone_score(db_session):
    workspace = Workspace(
        id="workspace-octocity-score-repair",
        slug=OCTOCITY_WORKSPACE_SLUG,
        name="Octocity score repair",
        mode="demo",
        settings={"mission_room": {"profile": OCTOCITY_MISSION_ROOM_PROFILE}},
    )
    db_session.add(workspace)
    db_session.commit()

    map_row = ensure_workspace_map_seed(db_session, workspace)
    db_session.commit()
    scores = db_session.query(WorkspaceMapScore).filter_by(map_id=map_row.id).all()
    assert len(scores) == 5

    db_session.delete(scores[0])
    db_session.commit()
    ensure_workspace_map_seed(db_session, workspace)
    db_session.commit()

    repaired_scores = db_session.query(WorkspaceMapScore).filter_by(map_id=map_row.id).all()
    assert len(repaired_scores) == 5
    assert {score.zone_id for score in repaired_scores} == {
        zone.id for zone in db_session.query(WorkspaceMapZone).filter_by(map_id=map_row.id).all()
    }
    assert (
        db_session.query(AuditLog)
        .filter_by(
            workspace_id=workspace.id,
            event_type="map.system.upgraded",
        )
        .count()
        == 1
    )


def test_octocity_map_repair_preserves_operator_rows_settings_and_existing_ids(db_session):
    workspace = Workspace(
        id="workspace-octocity-safe-repair",
        slug=OCTOCITY_WORKSPACE_SLUG,
        name="Octocity safe repair",
        mode="demo",
        settings={"mission_room": {"profile": OCTOCITY_MISSION_ROOM_PROFILE}},
    )
    db_session.add(workspace)
    db_session.commit()
    map_row = ensure_workspace_map_seed(db_session, workspace)
    db_session.commit()

    seed_zone = (
        db_session.query(WorkspaceMapZone)
        .filter_by(
            map_id=map_row.id,
            zone_key="zone-sud",
        )
        .one()
    )
    seed_layer = (
        db_session.query(WorkspaceMapLayer)
        .filter_by(
            map_id=map_row.id,
            key="territorial-risk",
        )
        .one()
    )
    seed_signal = (
        db_session.query(WorkspaceMapSignal)
        .filter_by(
            map_id=map_row.id,
            source_id="zone-sud-signal-1",
        )
        .one()
    )
    seed_ids = {
        "zone": seed_zone.id,
        "layer": seed_layer.id,
        "signal": seed_signal.id,
    }

    operator_zone = WorkspaceMapZone(
        id="operator-zone-id",
        map_id=map_row.id,
        zone_key="operator-zone",
        name="Operator review area",
        level=37,
        tone="stable",
        polygon="10,10 20,10 20,20 10,20",
        centroid={"x": 15, "y": 15},
        meta_data={"operator": {"owner": "field-team"}, "signals": ["Operator observation"]},
        source_refs=["operator-source-1"],
    )
    operator_layer = WorkspaceMapLayer(
        id="operator-layer-id",
        map_id=map_row.id,
        key="operator-overlay",
        label="Operator overlay",
        kind="annotation",
        visible=False,
        payload={"operator": True, "sources": ["operator-layer-source"]},
        sort_order=900,
    )
    operator_signal = WorkspaceMapSignal(
        id="operator-signal-id",
        map_id=map_row.id,
        zone_id=operator_zone.id,
        source_kind="operator_note",
        source_id="operator-signal-1",
        title="Operator observation",
        summary="Human-authored observation",
        weight=17,
        confidence=0.91,
        meta_data={"operator": True},
    )
    operator_score = WorkspaceMapScore(
        id="operator-score-id",
        map_id=map_row.id,
        zone_id=operator_zone.id,
        score=37,
        level_label="medium",
        drivers=["Operator observation"],
        recommendations=[{"title": "Keep the operator review"}],
        recommended_windows=[{"label": "Operator window"}],
    )
    db_session.add_all([operator_zone, operator_layer, operator_signal, operator_score])

    map_row.settings = {
        **map_row.settings,
        "fixture_version": 0,
        "operator_preferences": {"review_mode": "manual", "retention_days": 30},
    }
    seed_zone.name = "Obsolete fixture zone"
    seed_zone.meta_data = {**seed_zone.meta_data, "operator_note": "keep-zone-note"}
    seed_layer.label = "Obsolete fixture layer"
    seed_layer.payload = {**seed_layer.payload, "operator_style": {"opacity": 0.42}}
    seed_signal.title = "Obsolete fixture signal"
    seed_signal.summary = "Obsolete fixture signal"
    db_session.commit()

    repaired = ensure_workspace_map_seed(db_session, workspace)
    db_session.commit()

    assert repaired.id == map_row.id
    assert repaired.settings["operator_preferences"] == {
        "review_mode": "manual",
        "retention_days": 30,
    }
    assert repaired.settings["fixture_version"] != 0

    preserved_zone = db_session.query(WorkspaceMapZone).filter_by(id=operator_zone.id).one()
    preserved_layer = db_session.query(WorkspaceMapLayer).filter_by(id=operator_layer.id).one()
    preserved_signal = db_session.query(WorkspaceMapSignal).filter_by(id=operator_signal.id).one()
    preserved_score = db_session.query(WorkspaceMapScore).filter_by(id=operator_score.id).one()
    assert preserved_zone.name == "Operator review area"
    assert preserved_zone.meta_data == {
        "operator": {"owner": "field-team"},
        "signals": ["Operator observation"],
    }
    assert preserved_layer.payload == {"operator": True, "sources": ["operator-layer-source"]}
    assert preserved_signal.summary == "Human-authored observation"
    assert preserved_signal.meta_data == {"operator": True}
    assert preserved_score.drivers == ["Operator observation"]

    repaired_zone = db_session.query(WorkspaceMapZone).filter_by(id=seed_ids["zone"]).one()
    repaired_layer = db_session.query(WorkspaceMapLayer).filter_by(id=seed_ids["layer"]).one()
    repaired_signal = db_session.query(WorkspaceMapSignal).filter_by(id=seed_ids["signal"]).one()
    assert repaired_zone.name == "Mediterranean Gate"
    assert repaired_zone.meta_data["operator_note"] == "keep-zone-note"
    assert repaired_layer.label == "Decision heatmap"
    assert repaired_layer.payload["operator_style"] == {"opacity": 0.42}
    assert repaired_signal.title == "Port capacity watch"


@pytest.mark.parametrize(
    ("query", "expected_target"),
    [
        ("OCTAVE, montre le port de Marseille sur la carte", "port-marseille"),
        ("OCTAVE, montre Marseille avec le filtre douanes", "port-marseille"),
        ("OCTAVE, affiche la plateforme logistique de Nantes", "port-nantes"),
    ],
)
def test_octave_map_chat_uses_france_logistics_targets_without_sentinel_vocabulary(
    db_session,
    query,
    expected_target,
):
    workspace = Workspace(
        id=f"workspace-octocity-chat-{expected_target}",
        slug=OCTOCITY_WORKSPACE_SLUG,
        name="Octocity chat",
        mode="demo",
        settings={"mission_room": {"profile": OCTOCITY_MISSION_ROOM_PROFILE}},
    )
    db_session.add(workspace)
    db_session.commit()
    ensure_workspace_map_seed(db_session, workspace)

    action = handle_map_chat_query(
        db_session,
        workspace,
        None,
        query=query,
        assistant_profile="octave_executive",
    )

    assert action is not None
    assert action["command"]["target"] == expected_target
    assert "France" in action["content"]
    assert "Octocity" in action["content"]
    action_text = json.dumps(action, ensure_ascii=False).lower()
    for forbidden in ("abidjan", "golfe de guinee", "golfe de guinée", "douane"):
        assert forbidden not in action_text


def test_octave_map_chat_does_not_parse_sentinel_locations_or_customs(db_session):
    workspace = Workspace(
        id="workspace-octocity-chat-foreign-vocabulary",
        slug=OCTOCITY_WORKSPACE_SLUG,
        name="Octocity chat vocabulary",
        mode="demo",
        settings={"mission_room": {"profile": OCTOCITY_MISSION_ROOM_PROFILE}},
    )
    db_session.add(workspace)
    db_session.commit()
    ensure_workspace_map_seed(db_session, workspace)

    action = handle_map_chat_query(
        db_session,
        workspace,
        None,
        query="OCTAVE, affiche le port d'Abidjan, le Golfe de Guinée et les douanes sur la carte",
        assistant_profile="octave_executive",
    )
    neutral_action = handle_map_chat_query(
        db_session,
        workspace,
        None,
        query="OCTAVE, affiche la carte",
        assistant_profile="octave_executive",
    )

    assert action is not None
    assert neutral_action is not None
    assert action["command"]["target"] == neutral_action["command"]["target"]
    assert action["command"]["map_state"]["selected_port"] is None
    action_text = json.dumps(action, ensure_ascii=False).lower()
    for forbidden in ("abidjan", "golfe de guinee", "golfe de guinée", "douane"):
        assert forbidden not in action_text
    assert "france" in action_text
    assert "octocity" in action_text


@pytest.mark.parametrize(
    "configured_navigation",
    [
        [
            {
                "key": "cockpit",
                "label": "Only cockpit",
                "glyph": "ledger",
                "variant": "octocity_mission_room",
                "object": "Workbench",
            }
        ],
        [
            {
                "key": "cockpit",
                "label": "Broken cockpit",
                "glyph": "ledger",
                "variant": "octocity_mission_room",
            },
            *[
                {
                    "key": key,
                    "label": key,
                    "glyph": "ledger",
                    "variant": "octocity_mission_room",
                    "object": "Workbench",
                }
                for key in ("strategie", "securite", "reputation", "agenda", "presse", "decisions")
            ],
        ],
        "not-a-navigation-list",
    ],
    ids=("partial-list", "malformed-item", "wrong-type"),
)
def test_octocity_navigation_falls_back_to_complete_workspace_defaults(
    db_session,
    configured_navigation,
):
    seed_skills_and_capabilities(db_session)
    ensure_octocity_mission_room_workspace(db_session)
    workspace = db_session.query(Workspace).filter_by(slug=OCTOCITY_WORKSPACE_SLUG).one()
    settings = dict(workspace.settings or {})
    mission_room_settings = dict(settings.get("mission_room") or {})
    mission_room_settings["navigation"] = configured_navigation
    settings["mission_room"] = mission_room_settings
    workspace.settings = settings
    db_session.commit()

    payload = navigation_payload(db_session, workspace)

    assert [item["key"] for item in payload["items"]] == [
        "cockpit",
        "strategie",
        "securite",
        "reputation",
        "agenda",
        "presse",
        "decisions",
    ]
    assert {item["key"]: item["system_name"] for item in payload["items"]} == {
        "cockpit": "OCTAVE Mission Room",
        "strategie": "OCTAVE Territorial Map",
        "securite": "OCTAVE Open Intelligence",
        "reputation": "OCTAVE Open Intelligence",
        "agenda": "OCTAVE Mission Room",
        "presse": "OCTAVE Open Intelligence",
        "decisions": "OCTAVE Decision Desk",
    }
    assert all(str(item["variant"]).startswith("octocity_") for item in payload["items"])
    assert octocity_forbidden_terms_present(payload) == []


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
    assert (
        db_session.query(FeedSource).filter(FeedSource.workspace_id == "workspace-demo").count()
        == 2
    )


def test_mission_room_navigation_prefers_workspace_intelligence_system(db_session):
    seed_skills_and_capabilities(db_session)
    ensure_sentinel_ci_workspace(db_session)
    workspace = db_session.query(Workspace).filter(Workspace.slug == SENTINEL_WORKSPACE_SLUG).one()

    # Simulate the generic boot seed adding a second variant=intelligence System.
    capability = (
        db_session.query(Capability).filter(Capability.slug == "open_intelligence_watch").one()
    )
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


def test_octocity_mission_room_navigation_items_bind_to_active_systems(db_session):
    seed_skills_and_capabilities(db_session)
    ensure_octocity_mission_room_workspace(db_session)
    workspace = db_session.query(Workspace).filter(Workspace.slug == OCTOCITY_WORKSPACE_SLUG).one()

    payload = navigation_payload(db_session, workspace)
    active_system_ids = {
        row.id
        for row in db_session.query(System)
        .filter(System.workspace_id == workspace.id, System.status == "active")
        .all()
    }

    assert len(payload["items"]) == 7
    assert all(item.get("system_id") in active_system_ids for item in payload["items"])
    assert {item["key"]: item["system_name"] for item in payload["items"]} == {
        "cockpit": "OCTAVE Mission Room",
        "strategie": "OCTAVE Territorial Map",
        "securite": "OCTAVE Open Intelligence",
        "reputation": "OCTAVE Open Intelligence",
        "agenda": "OCTAVE Mission Room",
        "presse": "OCTAVE Open Intelligence",
        "decisions": "OCTAVE Decision Desk",
    }
    assert all(str(item["variant"]).startswith("octocity_") for item in payload["items"])
    assert octocity_forbidden_terms_present(payload) == []


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
