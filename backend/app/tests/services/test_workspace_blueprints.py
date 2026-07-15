from __future__ import annotations

import json
from copy import deepcopy

import pytest

from app.models.capability import Capability
from app.models.context import Context
from app.models.evaluation_preset import EvaluationPreset
from app.models.knowledge_collection import KnowledgeCollection
from app.models.rag_preset import RagPreset
from app.models.skill import Skill
from app.models.system import System
from app.models.user import User
from app.models.workspace import (
    Workspace,
    WorkspaceMember,
    WorkspaceMemberAppEntitlement,
)
from app.services import workspace_blueprints
from app.services.iam.app_entitlements import (
    APP_ENTITLEMENTS_FEATURE,
    BUSINESS_APP_KEYS,
    WORKSPACE_EXPERIENCE_FEATURE,
)
from app.services.iam.config_service import load_iam_config, patch_iam_config


def _workspace(
    db_session,
    *,
    id_: str,
    slug: str,
    mode: str = "executive",
    settings: dict | None = None,
) -> Workspace:
    workspace = Workspace(
        id=id_,
        name=slug.title(),
        slug=slug,
        mode=mode,
        settings=settings or {},
    )
    db_session.add(workspace)
    db_session.flush()
    return workspace


def _user(db_session) -> User:
    user = User(id="user-1", username="builder", email="builder@example.test")
    db_session.add(user)
    db_session.flush()
    return user


def _reference_workspace(db_session) -> tuple[Workspace, User]:
    workspace = _workspace(db_session, id_="ws-source", slug="andritz")
    user = _user(db_session)
    skill = Skill(
        id="skill-rag",
        slug="llm_rag_answer_v1",
        name="RAG answer",
        workspace_id=None,
    )
    capability = Capability(
        id="cap-capture",
        workspace_id=workspace.id,
        slug="expert_knowledge_capture",
        name="Expert Knowledge Capture",
        description="Capture tacit expert knowledge.",
        skill_ids=[skill.id],
        pricing={"unit": "session", "unit_price": 0},
    )
    context = Context(
        id="ctx-andritz",
        workspace_id=workspace.id,
        name="Andritz MVP Knowledge Context",
        data_refs=["collection:andritz-secure-deposit"],
        environment_state={"site": "pilot"},
        ephemeral=False,
    )
    system = System(
        id="sys-capture",
        workspace_id=workspace.id,
        name="Expert Knowledge Capture",
        objective="Capture troubleshooting decisions from senior experts.",
        capability_id=capability.id,
        context_id=context.id,
        skill_ids=[skill.id],
        flow_definition={
            "nodes": [
                {
                    "id": "n1",
                    "kind": "task",
                    "config": {"skill_id": skill.id, "skill_slug": skill.slug},
                }
            ],
            "edges": [],
        },
        execution_mode="human_augmented",
        execution_profile={"voice_sla_ms": 1500},
        status="active",
    )
    collection = KnowledgeCollection(
        id="col-secure",
        workspace_id=workspace.id,
        slug="andritz-secure-deposit",
        name="Andritz Secure Deposit",
        description="Staged supplier files.",
        status="ready",
        document_names=["manual.pdf"],
        vector_collection_name="andritz_andritz-secure-deposit",
        artifact_prefix="workspaces/ws-source/collections/col-secure",
        document_count=1,
        chunk_count=12,
    )
    preset = RagPreset(
        id="preset-rag",
        workspace_id=workspace.id,
        name="Andritz default RAG",
        scope="workspace",
        config={"mode": "hybrid", "topK": 5},
        is_default=True,
    )
    db_session.add_all([skill, capability, context, system, collection, preset])
    db_session.flush()
    return workspace, user


def _validate_then_apply(
    db_session,
    *,
    target: Workspace,
    blueprint: dict,
    actor: User,
    experience_policy: str = "preserve_target",
    entitlement_policy: str = "preserve_target",
    activate_systems: bool = False,
) -> tuple[dict, dict]:
    dry_run = workspace_blueprints.apply_workspace_blueprint(
        db=db_session,
        workspace=target,
        blueprint=blueprint,
        actor=actor,
        dry_run=True,
        activate_systems=activate_systems,
        experience_policy=experience_policy,
        entitlement_policy=entitlement_policy,
    )
    applied = workspace_blueprints.apply_workspace_blueprint(
        db=db_session,
        workspace=target,
        blueprint=blueprint,
        actor=actor,
        dry_run=False,
        activate_systems=activate_systems,
        experience_policy=experience_policy,
        entitlement_policy=entitlement_policy,
        expected_plan_token=dry_run["plan_token"],
    )
    return dry_run, applied


def _add_member(
    db_session,
    *,
    workspace: Workspace,
    user_id: str,
    username: str,
) -> WorkspaceMember:
    user = User(id=user_id, username=username, email=f"{username}@example.test")
    membership = WorkspaceMember(
        user_id=user.id,
        workspace_id=workspace.id,
        role="member",
        role_template="business_user",
    )
    db_session.add_all([user, membership])
    db_session.flush()
    return membership


def test_export_workspace_blueprint_excludes_sensitive_data(db_session):
    workspace, user = _reference_workspace(db_session)

    blueprint = workspace_blueprints.export_workspace_blueprint(
        db=db_session,
        workspace=workspace,
        exported_by=user,
    )

    assert blueprint["kind"] == workspace_blueprints.BLUEPRINT_KIND
    assert blueprint["workspace"]["slug"] == "andritz"
    assert blueprint["systems"][0]["name"] == "Expert Knowledge Capture"
    assert blueprint["systems"][0]["capability_slug"] == "expert_knowledge_capture"
    assert blueprint["capabilities"][0]["skill_slugs"] == ["llm_rag_answer_v1"]
    assert blueprint["knowledge"]["collections"][0]["slug"] == "andritz-secure-deposit"
    assert blueprint["knowledge"]["exports_raw_documents"] is False
    assert blueprint["connectors"]["secure_deposit"]["exports_passwords"] is False
    assert blueprint["data_policy"]["workspace_members"] == "excluded"


def test_dry_run_reports_actions_without_writing(db_session):
    source, user = _reference_workspace(db_session)
    blueprint = workspace_blueprints.export_workspace_blueprint(
        db=db_session,
        workspace=source,
        exported_by=user,
    )
    target = _workspace(db_session, id_="ws-target", slug="target")

    report = workspace_blueprints.apply_workspace_blueprint(
        db=db_session,
        workspace=target,
        blueprint=blueprint,
        actor=user,
        dry_run=True,
    )

    assert report["dry_run"] is True
    assert report["created"]["systems"] == 1
    assert db_session.query(System).filter(System.workspace_id == target.id).count() == 0


def test_apply_workspace_blueprint_creates_draft_system_and_metadata(db_session):
    source, user = _reference_workspace(db_session)
    blueprint = workspace_blueprints.export_workspace_blueprint(
        db=db_session,
        workspace=source,
        exported_by=user,
    )
    target = _workspace(db_session, id_="ws-target", slug="target")

    _dry_run, report = _validate_then_apply(
        db_session,
        target=target,
        blueprint=blueprint,
        actor=user,
    )
    db_session.flush()

    imported = (
        db_session.query(System)
        .filter(System.workspace_id == target.id, System.name == "Expert Knowledge Capture")
        .one()
    )
    collection = (
        db_session.query(KnowledgeCollection)
        .filter(
            KnowledgeCollection.workspace_id == target.id,
            KnowledgeCollection.slug == "andritz-secure-deposit",
        )
        .one()
    )

    assert report["created"]["systems"] == 1
    assert report["created"]["capabilities"] == 1
    assert imported.status == "draft"
    assert imported.execution_mode == "human_augmented"
    assert imported.capability_id is not None
    assert collection.document_count == 0
    assert collection.status == "created"


def test_export_uses_positive_allowlists_and_removes_credential_shaped_config(db_session):
    workspace, user = _reference_workspace(db_session)
    workspace.settings = {
        "family": "andritz",
        "features": {WORKSPACE_EXPERIENCE_FEATURE: True},
        "smtp_password": "root-secret-value",
        "connectors": {"erp": {"api_key": "settings-secret-value"}},
    }
    capability = db_session.query(Capability).filter_by(id="cap-capture").one()
    capability.pricing = {
        "unit": "session",
        "vendor_secret": "pricing-secret-value",
        "token": "bare-token-value",
        "warehouse_dsn": "postgresql://warehouse:dsn-value@example.test/data",
        "endpoint": "https://embedded-user:embedded-value@example.test/api",
        "header": "Bearer bearer-value",
        "env": [
            {"name": "OPENAI_API_KEY", "value": "indirected-secret-value"},
            {"name": "REGION", "value": "eu-west-1"},
        ],
        "secretariat_label": "Executive office",
        "authorization_endpoint": "https://login.example.test/oauth/authorize",
        "passwordless_enabled": True,
        "public": {"currency": "EUR"},
    }
    context = db_session.query(Context).filter_by(id="ctx-andritz").one()
    context.environment_state = {
        "site": "pilot",
        "credentials": {"username": "operator", "password": "context-secret-value"},
    }
    system = db_session.query(System).filter_by(id="sys-capture").one()
    system.flow_definition = {
        "nodes": [
            {
                "id": "n1",
                "kind": "task",
                "config": {
                    "skill_id": "skill-rag",
                    "skill_slug": "llm_rag_answer_v1",
                    "api_key": "flow-secret-value",
                },
            }
        ],
        "edges": [],
    }
    system.execution_profile = {
        "latency_target_ms": 1500,
        "refresh_token": "execution-secret-value",
    }
    collection = db_session.query(KnowledgeCollection).filter_by(id="col-secure").one()
    collection.chunking_params = {
        "chunk_size": 800,
        "access_token": "collection-secret-value",
    }
    preset = db_session.query(RagPreset).filter_by(id="preset-rag").one()
    preset.config = {"mode": "hybrid", "provider_api_key": "preset-secret-value"}
    db_session.flush()

    blueprint = workspace_blueprints.export_workspace_blueprint(
        db=db_session,
        workspace=workspace,
        exported_by=user,
    )
    encoded = json.dumps(blueprint, sort_keys=True)

    for secret in (
        "root-secret-value",
        "settings-secret-value",
        "pricing-secret-value",
        "context-secret-value",
        "flow-secret-value",
        "execution-secret-value",
        "collection-secret-value",
        "preset-secret-value",
        "bare-token-value",
        "dsn-value",
        "embedded-value",
        "bearer-value",
        "indirected-secret-value",
    ):
        assert secret not in encoded
    assert "settings" not in blueprint["workspace"]
    assert blueprint["experience"]["profile"] == {"family": "andritz"}
    assert blueprint["capabilities"][0]["pricing"] == {
        "unit": "session",
        "env": [{"name": "REGION", "value": "eu-west-1"}],
        "secretariat_label": "Executive office",
        "authorization_endpoint": "https://login.example.test/oauth/authorize",
        "passwordless_enabled": True,
        "public": {"currency": "EUR"},
    }
    assert blueprint["contexts"][0]["environment_state"] == {"site": "pilot"}
    assert blueprint["systems"][0]["execution_profile"] == {"latency_target_ms": 1500}
    assert blueprint["presets"]["rag"][0]["config"] == {"mode": "hybrid"}


def test_v1_import_explicitly_ignores_workspace_mode_and_settings(db_session):
    user = _user(db_session)
    target = _workspace(
        db_session,
        id_="ws-target",
        slug="target",
        settings={"family": "target-family"},
    )
    blueprint = {
        "kind": workspace_blueprints.BLUEPRINT_KIND,
        "schema_version": 1,
        "workspace": {
            "name": "Legacy",
            "slug": "legacy",
            "mode": "demo",
            "settings": {
                "family": "legacy-family",
                "password": "must-not-be-consumed",
            },
        },
        "capabilities": [],
        "contexts": [],
        "systems": [],
        "knowledge": {"collections": []},
        "presets": {"rag": [], "evaluation": []},
        "iam": {},
    }

    dry_run = workspace_blueprints.apply_workspace_blueprint(
        db=db_session,
        workspace=target,
        blueprint=blueprint,
        actor=user,
        dry_run=True,
        experience_policy="replace_portable",
    )
    report = workspace_blueprints.apply_workspace_blueprint(
        db=db_session,
        workspace=target,
        blueprint=blueprint,
        actor=user,
        dry_run=False,
        experience_policy="replace_portable",
        expected_plan_token=dry_run["plan_token"],
    )

    assert dry_run["experience"]["legacy_ignored"] == [
        "/workspace/mode",
        "/workspace/settings",
    ]
    assert report["experience"]["legacy_ignored"] == dry_run["experience"]["legacy_ignored"]
    assert target.mode == "executive"
    assert target.settings == {"family": "target-family"}


def test_v1_realistic_structural_export_round_trips_only_after_dry_run_token(
    db_session,
):
    source, user = _reference_workspace(db_session)
    db_session.add(
        EvaluationPreset(
            id="preset-evaluation",
            workspace_id=source.id,
            name="Legacy evaluation",
            scope="workspace",
            config={"judge": "grounded"},
            is_default=True,
        )
    )
    patch_iam_config(
        db_session,
        workspace_id=source.id,
        role_flags={"workspace_contributor": {"can_publish": False}},
        capability_overrides={"expert_knowledge_capture": {"can_publish": False}},
        updated_by_user_id=user.id,
    )
    db_session.flush()
    legacy = workspace_blueprints.export_workspace_blueprint(
        db=db_session,
        workspace=source,
        exported_by=user,
    )
    legacy["schema_version"] = 1
    legacy["workspace"]["settings"] = {
        "family": "must-remain-ignored",
        "password": "must-not-be-consumed",
    }
    legacy.pop("experience")
    target = _workspace(
        db_session,
        id_="ws-target",
        slug="target",
        settings={"family": "generic", "target_only": True},
    )

    dry_run = workspace_blueprints.apply_workspace_blueprint(
        db=db_session,
        workspace=target,
        blueprint=legacy,
        actor=user,
        dry_run=True,
    )
    assert dry_run["created"] == {
        "capabilities": 1,
        "contexts": 1,
        "collections": 1,
        "systems": 1,
        "presets": 2,
    }
    with pytest.raises(
        workspace_blueprints.WorkspaceBlueprintConflictError,
        match="plan_token",
    ):
        workspace_blueprints.apply_workspace_blueprint(
            db=db_session,
            workspace=target,
            blueprint=legacy,
            actor=user,
            dry_run=False,
        )

    report = workspace_blueprints.apply_workspace_blueprint(
        db=db_session,
        workspace=target,
        blueprint=legacy,
        actor=user,
        dry_run=False,
        expected_plan_token=dry_run["plan_token"],
    )

    assert report["created"] == dry_run["created"]
    assert target.settings == {"family": "generic", "target_only": True}
    assert db_session.query(System).filter(System.workspace_id == target.id).count() == 1
    assert (
        db_session.query(KnowledgeCollection)
        .filter(KnowledgeCollection.workspace_id == target.id)
        .count()
        == 1
    )
    assert (
        db_session.query(EvaluationPreset)
        .filter(EvaluationPreset.workspace_id == target.id)
        .count()
        == 1
    )
    target_iam = load_iam_config(db_session, target.id, create=False)
    assert target_iam is not None
    assert target_iam.capability_overrides == {"expert_knowledge_capture": {"can_publish": False}}


def test_andritz_round_trip_backfills_all_members_before_entitlement_activation(db_session):
    source, user = _reference_workspace(db_session)
    source.mode = "operator"
    source.settings = {
        "family": "andritz",
        "hide_provider_details": True,
        "features": {
            WORKSPACE_EXPERIENCE_FEATURE: True,
            APP_ENTITLEMENTS_FEATURE: True,
            "unportable_feature": True,
        },
        "navigation_profile": {
            "key": "business_end_user",
            "default_route": "/client360-pdr",
            "primary_surfaces": list(BUSINESS_APP_KEYS),
            "advanced_access": "admin_only",
        },
        "default_route": "/client360-pdr",
        "workspace_app_shell": "standard",
        "workspace_app_label": "ANDRITZ",
        "workspace_app_default_view": "client360-pdr",
        "actions": {
            "enabled_packs": ["global_voice_v1", "andritz_industrial_v1"],
            "confirmation_policy": "confirm_side_effects",
            "runtime_history": ["not-portable"],
        },
        "assistant_profile_default": "andritz_operator",
        "assistant_profiles": [
            {
                "key": "andritz_operator",
                "label": "Industrial Assistant",
                "tone": "operational",
                "grounding": {
                    "default_mode": "strict",
                    "allowed_modes": ["strict", "balanced"],
                    "strict_guard": "default",
                },
                "actions": {
                    "enabled_packs": [
                        "global_voice_v1",
                        "andritz_industrial_v1",
                    ],
                    "confirmation_policy": "confirm_side_effects",
                },
            }
        ],
    }
    db_session.flush()
    blueprint = workspace_blueprints.export_workspace_blueprint(
        db=db_session,
        workspace=source,
        exported_by=user,
    )
    target = _workspace(
        db_session,
        id_="ws-target",
        slug="andritz-target",
        settings={
            "family": "old-family",
            "features": {APP_ENTITLEMENTS_FEATURE: False},
            "runtime_cache": {"opaque": True},
        },
    )
    _add_member(
        db_session,
        workspace=target,
        user_id="user-2",
        username="member-two",
    )
    _add_member(
        db_session,
        workspace=target,
        user_id="user-3",
        username="member-three",
    )

    dry_run, report = _validate_then_apply(
        db_session,
        target=target,
        blueprint=blueprint,
        actor=user,
        experience_policy="replace_portable",
        entitlement_policy="grant_all_existing_members",
    )
    db_session.flush()

    assert dry_run["experience"]["app_access"]["grants_planned"] == (2 * len(BUSINESS_APP_KEYS))
    assert report["experience"]["app_access"]["grants_created"] == (2 * len(BUSINESS_APP_KEYS))
    assert target.settings["features"][APP_ENTITLEMENTS_FEATURE] is True
    assert target.settings["runtime_cache"] == {"opaque": True}
    assert db_session.query(WorkspaceMemberAppEntitlement).join(
        WorkspaceMember,
        WorkspaceMember.id == WorkspaceMemberAppEntitlement.workspace_member_id,
    ).filter(WorkspaceMember.workspace_id == target.id).count() == 2 * len(BUSINESS_APP_KEYS)
    assert workspace_blueprints._serialize_workspace_experience(target) == blueprint["experience"]


def _mission_room_settings(kind: str) -> dict:
    sentinel = kind == "sentinel"
    profile = "sentinel_government_v1" if sentinel else "octocity_institutional_v1"
    demo_profile = "government_mission_room" if sentinel else "octocity_mission_room"
    assistant = "AYA" if sentinel else "OCTAVE"
    label = "SENTINEL-CI" if sentinel else "Octocity Mission Room"
    packs = [
        "global_voice_v1",
        "sentinel_ci_aya_v1" if sentinel else "octave_mission_room_v1",
        "sentinel_ci_aya_security_v1" if sentinel else "octave_security_v1",
    ]
    variant = "government_mission_room" if sentinel else "octocity_mission_room"
    navigation = [
        {
            "key": "cockpit",
            "label": "Cockpit",
            "glyph": "ledger",
            "variant": variant,
            "object": "Workbench",
        }
    ]
    brand = {
        "label": label,
        "lines": [label, "MISSION ROOM"],
        "emblem": "/assets/brand/sentinel-ci-emblem.png"
        if sentinel
        else "/assets/brand/agentium-mark.svg",
        "style": "sentinel" if sentinel else "agentium",
    }
    document_profile = "sentinel_ci_ministerial" if sentinel else "octocity_institutional"
    return {
        "family": "generic",
        "demo_profile": demo_profile,
        "hide_provider_details": True,
        "features": {WORKSPACE_EXPERIENCE_FEATURE: True},
        "default_route": "/hypervisor/mission-room/cockpit",
        "workspace_app_shell": "immersive",
        "workspace_app_label": label,
        "workspace_app_default_view": "cockpit",
        "workspace_app_brand": brand,
        "actions": {
            "enabled_packs": packs,
            "confirmation_policy": "confirm_side_effects",
        },
        "voice_loop": {
            "default_mode": "session_loop",
            "commands_enabled": True,
            "command_packs": packs,
            "trigger_word": assistant,
        },
        "calendar": {
            "mode": "internal_shared",
            "connector_id": "institutional_calendar",
            "connector_label": "Agenda institutionnel",
            "write_policy": "direct",
            "timezone": "Africa/Abidjan" if sentinel else "UTC",
            "api_key": "source-calendar-secret-must-not-export",
        },
        "action_planner": {
            "write_policy": "direct",
            "default_owner": "Cabinet" if sentinel else "Coordination",
            "advisory_only": True,
        },
        "document_intelligence": {
            "enabled": True,
            "default_profile": document_profile,
            "profiles": [
                {
                    "key": document_profile,
                    "label": f"{label} institutional documents",
                    "synonyms": {"briefing": ["brief", "note"]},
                    "max_candidate_facts": 1800,
                    "max_evidence_rows": 18,
                }
            ],
            "ocr": {
                "enabled": True,
                "provider_priority": ["tesseract_local", "ppocr_service"],
                "languages": ["fra", "eng"],
                "min_confidence": 0.45,
                "timeout_seconds": 20,
                "required": False,
                "openai_vision_enabled": False,
            },
            "citation_policy": "raw_source_first_page_section_paragraph",
        },
        "visual_intelligence": {
            "enabled": True,
            "capture_cadence_minutes": 60,
            "allowed_adapters": ["demo_static", "http_image"],
            "storage_policy": "snapshot_only_no_continuous_recording",
            "analysis_policy": "no_identification_no_biometrics",
            "source_model": "live_webcam_embed_layer",
        },
        "feature_flag": {"security_live_osint": False, "runtime_only": True},
        "connectors": {
            "institutional_calendar": {
                "enabled": True,
                "status": "connected",
                "mode": "internal_shared",
                "label": "Agenda institutionnel",
                "access_token": "source-connector-secret-must-not-export",
            },
            "visual_streams": {
                "enabled": True,
                "status": "connected",
                "mode": "live_webcam_embed_layer",
                "label": "Flux visuels institutionnels",
            },
        },
        "mission_room": {
            "enabled": True,
            "profile": profile,
            "country": "Cote d'Ivoire" if sentinel else "Asteria",
            "country_code": "CI" if sentinel else "AS",
            "region_scope": ["West Africa"] if sentinel else ["Atlantic Arc"],
            "label": assistant,
            "assistant_label": assistant,
            "brand": brand,
            "root_route": "/hypervisor/mission-room",
            "default_view": "cockpit",
            "navigation": navigation,
        },
    }


@pytest.mark.parametrize(
    ("kind", "forbidden_terms"),
    [
        ("sentinel", ("octocity", "octave")),
        ("octocity", ("sentinel",)),
    ],
)
def test_mission_room_round_trip_keeps_brand_and_action_pack_namespaces_isolated(
    db_session,
    kind,
    forbidden_terms,
):
    user = _user(db_session)
    source = _workspace(
        db_session,
        id_="ws-source",
        slug=f"{kind}-source",
        mode="demo",
        settings=_mission_room_settings(kind),
    )
    blueprint = workspace_blueprints.export_workspace_blueprint(
        db=db_session,
        workspace=source,
        exported_by=user,
    )
    experience_text = json.dumps(blueprint["experience"], sort_keys=True).lower()
    assert "source-calendar-secret-must-not-export" not in experience_text
    assert "source-connector-secret-must-not-export" not in experience_text
    for term in forbidden_terms:
        assert term not in experience_text

    target = _workspace(
        db_session,
        id_="ws-target",
        slug=f"{kind}-target",
        settings={
            "family": "legacy",
            "runtime_state": {"keep": True},
            "calendar": {"runtime_cursor": "keep"},
            "connectors": {
                "private_runtime_connector": {"api_key": "target-runtime-secret-must-remain"},
                "institutional_calendar": {"runtime_session": "keep"},
            },
        },
    )
    _dry_run, report = _validate_then_apply(
        db_session,
        target=target,
        blueprint=blueprint,
        actor=user,
        experience_policy="replace_portable",
    )

    assert report["experience"]["conflicts"] == []
    assert target.mode == "demo"
    assert target.settings["runtime_state"] == {"keep": True}
    assert target.settings["calendar"]["runtime_cursor"] == "keep"
    assert target.settings["connectors"]["private_runtime_connector"] == {
        "api_key": "target-runtime-secret-must-remain"
    }
    assert target.settings["connectors"]["institutional_calendar"]["runtime_session"] == "keep"
    dependencies = blueprint["experience"]["extensions"]["mission-room"]["dependencies"]
    assert set(dependencies) == {
        "calendar",
        "action_planner",
        "document_intelligence",
        "visual_intelligence",
        "feature_flags",
        "connectors",
    }
    assert dependencies["feature_flags"] == {"security_live_osint": False}
    assert workspace_blueprints._serialize_workspace_experience(target) == blueprint["experience"]


def test_merge_conflict_replace_idempotence_and_stale_plan_detection(db_session):
    user = _user(db_session)
    source = _workspace(
        db_session,
        id_="ws-source",
        slug="source",
        settings={
            "family": "generic",
            "features": {WORKSPACE_EXPERIENCE_FEATURE: True},
        },
    )
    blueprint = workspace_blueprints.export_workspace_blueprint(
        db=db_session,
        workspace=source,
        exported_by=user,
    )
    target = _workspace(
        db_session,
        id_="ws-target",
        slug="target",
        settings={"family": "sentinel_ci"},
    )

    conflict_plan = workspace_blueprints.apply_workspace_blueprint(
        db=db_session,
        workspace=target,
        blueprint=blueprint,
        actor=user,
        dry_run=True,
        experience_policy="merge_missing",
    )
    assert conflict_plan["can_apply"] is False
    assert any(
        item["path"] == "/workspace/settings/family"
        for item in conflict_plan["experience"]["conflicts"]
    )
    with pytest.raises(workspace_blueprints.WorkspaceBlueprintConflictError):
        workspace_blueprints.apply_workspace_blueprint(
            db=db_session,
            workspace=target,
            blueprint=blueprint,
            actor=user,
            dry_run=False,
            experience_policy="merge_missing",
            expected_plan_token=conflict_plan["plan_token"],
        )
    assert target.settings == {"family": "sentinel_ci"}

    first_plan, _first_apply = _validate_then_apply(
        db_session,
        target=target,
        blueprint=blueprint,
        actor=user,
        experience_policy="replace_portable",
    )
    assert first_plan["experience"]["applied"]
    second_plan = workspace_blueprints.apply_workspace_blueprint(
        db=db_session,
        workspace=target,
        blueprint=blueprint,
        actor=user,
        dry_run=True,
        experience_policy="replace_portable",
    )
    assert second_plan["experience"]["applied"] == []
    assert second_plan["experience"]["conflicts"] == []

    target.settings = {**target.settings, "family": "andritz"}
    db_session.flush()
    with pytest.raises(workspace_blueprints.WorkspaceBlueprintConflictError):
        workspace_blueprints.apply_workspace_blueprint(
            db=db_session,
            workspace=target,
            blueprint=blueprint,
            actor=user,
            dry_run=False,
            experience_policy="replace_portable",
            expected_plan_token=second_plan["plan_token"],
        )


def test_system_status_and_execution_mode_are_canonicalized_before_activation(db_session):
    source, user = _reference_workspace(db_session)
    blueprint = workspace_blueprints.export_workspace_blueprint(
        db=db_session,
        workspace=source,
        exported_by=user,
    )
    blueprint["systems"][0]["execution_mode"] = " human_augmented "
    blueprint["systems"][0]["source_status"] = " active "
    target = _workspace(db_session, id_="ws-target", slug="target")

    _dry_run, _report = _validate_then_apply(
        db_session,
        target=target,
        blueprint=blueprint,
        actor=user,
        activate_systems=True,
    )
    imported = db_session.query(System).filter(System.workspace_id == target.id).one()
    assert imported.execution_mode == "human_augmented"
    assert imported.status == "active"

    invalid = {**blueprint, "systems": [dict(blueprint["systems"][0])]}
    invalid["systems"][0]["source_status"] = "running"
    with pytest.raises(workspace_blueprints.WorkspaceBlueprintError):
        workspace_blueprints.apply_workspace_blueprint(
            db=db_session,
            workspace=target,
            blueprint=invalid,
            actor=user,
            dry_run=True,
            activate_systems=True,
        )


def test_import_rejects_credential_shaped_fields_in_arbitrary_configs(db_session):
    source, user = _reference_workspace(db_session)
    blueprint = workspace_blueprints.export_workspace_blueprint(
        db=db_session,
        workspace=source,
        exported_by=user,
    )
    target = _workspace(db_session, id_="ws-target", slug="target")
    mutations = (
        {"api_key": "do-not-import"},
        {"token": "bare-secret-token"},
        {"warehouse_dsn": "postgresql://user:password@example.test/data"},
        {"header": "Bearer opaque-secret"},
        {"endpoint": "https://user:password@example.test/api"},
        {"endpoint": "https://example.test/api?access_token=opaque-secret"},
        {"env": [{"name": "OPENAI_API_KEY", "value": "opaque-secret"}]},
    )

    for mutation in mutations:
        candidate = deepcopy(blueprint)
        candidate["systems"][0]["execution_profile"].update(mutation)
        with pytest.raises(
            workspace_blueprints.WorkspaceBlueprintError,
            match="Credential-shaped (field|value|indirection)",
        ):
            workspace_blueprints.apply_workspace_blueprint(
                db=db_session,
                workspace=target,
                blueprint=candidate,
                actor=user,
                dry_run=True,
            )

    benign = deepcopy(blueprint)
    benign["systems"][0]["execution_profile"].update(
        {
            "secretariat_label": "Executive office",
            "authorization_endpoint": "https://login.example.test/oauth/authorize",
            "passwordless_enabled": True,
        }
    )
    workspace_blueprints.apply_workspace_blueprint(
        db=db_session,
        workspace=target,
        blueprint=benign,
        actor=user,
        dry_run=True,
    )


def test_mission_dependencies_reject_credentials_and_v2_rejects_raw_settings(db_session):
    user = _user(db_session)
    source = _workspace(
        db_session,
        id_="ws-source",
        slug="sentinel-source",
        mode="demo",
        settings=_mission_room_settings("sentinel"),
    )
    blueprint = workspace_blueprints.export_workspace_blueprint(
        db=db_session,
        workspace=source,
        exported_by=user,
    )
    target = _workspace(db_session, id_="ws-target", slug="target")

    for invalid_version in (True, 1.0, 2.0, "2"):
        invalid_schema = deepcopy(blueprint)
        invalid_schema["schema_version"] = invalid_version
        with pytest.raises(
            workspace_blueprints.WorkspaceBlueprintError,
            match="Unsupported schema_version",
        ):
            workspace_blueprints.apply_workspace_blueprint(
                db=db_session,
                workspace=target,
                blueprint=invalid_schema,
                actor=user,
                dry_run=True,
            )

    invalid_contract = deepcopy(blueprint)
    invalid_contract["experience"]["contract_version"] = True
    with pytest.raises(
        workspace_blueprints.WorkspaceBlueprintError,
        match="experience.contract_version",
    ):
        workspace_blueprints.apply_workspace_blueprint(
            db=db_session,
            workspace=target,
            blueprint=invalid_contract,
            actor=user,
            dry_run=True,
        )

    raw_settings = deepcopy(blueprint)
    raw_settings["workspace"]["settings"] = {"family": "decorative-only"}
    with pytest.raises(
        workspace_blueprints.WorkspaceBlueprintError,
        match="Unknown fields at /workspace: settings",
    ):
        workspace_blueprints.apply_workspace_blueprint(
            db=db_session,
            workspace=target,
            blueprint=raw_settings,
            actor=user,
            dry_run=True,
        )

    unknown_family = deepcopy(blueprint)
    unknown_family["experience"]["profile"]["family"] = "decorative-only"
    with pytest.raises(
        workspace_blueprints.WorkspaceBlueprintError,
        match="canonical workspace family",
    ):
        workspace_blueprints.apply_workspace_blueprint(
            db=db_session,
            workspace=target,
            blueprint=unknown_family,
            actor=user,
            dry_run=True,
        )

    noncanonical_pack = deepcopy(blueprint)
    noncanonical_pack["experience"]["actions"]["enabled_packs"] = [" global_voice_v1 "]
    with pytest.raises(
        workspace_blueprints.WorkspaceBlueprintError,
        match="must be trimmed and unique",
    ):
        workspace_blueprints.apply_workspace_blueprint(
            db=db_session,
            workspace=target,
            blueprint=noncanonical_pack,
            actor=user,
            dry_run=True,
        )

    credential = deepcopy(blueprint)
    dependencies = credential["experience"]["extensions"]["mission-room"]["dependencies"]
    dependencies["connectors"]["institutional_calendar"]["api_key"] = "forbidden"
    with pytest.raises(
        workspace_blueprints.WorkspaceBlueprintError,
        match="Credential-shaped field",
    ):
        workspace_blueprints.apply_workspace_blueprint(
            db=db_session,
            workspace=target,
            blueprint=credential,
            actor=user,
            dry_run=True,
        )


def test_mutating_apply_reauthorizes_immediately_after_workspace_lock(
    db_session,
    monkeypatch,
):
    source, user = _reference_workspace(db_session)
    blueprint = workspace_blueprints.export_workspace_blueprint(
        db=db_session,
        workspace=source,
        exported_by=user,
    )
    target = _workspace(db_session, id_="ws-target", slug="target")
    dry_run = workspace_blueprints.apply_workspace_blueprint(
        db=db_session,
        workspace=target,
        blueprint=blueprint,
        actor=user,
        dry_run=True,
    )
    events: list[str] = []
    original_lock = workspace_blueprints._lock_workspace

    def _recording_lock(db, workspace):
        events.append("lock")
        return original_lock(db, workspace)

    class _AuthorityLostError(RuntimeError):
        pass

    def _deny_after_lock(locked_workspace):
        events.append("reauthorize")
        assert locked_workspace.id == target.id
        raise _AuthorityLostError("caller was demoted while waiting")

    monkeypatch.setattr(workspace_blueprints, "_lock_workspace", _recording_lock)

    with pytest.raises(_AuthorityLostError, match="demoted"):
        workspace_blueprints.apply_workspace_blueprint(
            db=db_session,
            workspace=target,
            blueprint=blueprint,
            actor=user,
            dry_run=False,
            expected_plan_token=dry_run["plan_token"],
            locked_workspace_guard=_deny_after_lock,
        )

    assert events == ["lock", "reauthorize"]
    assert db_session.query(System).filter(System.workspace_id == target.id).count() == 0


def test_replace_portable_blocks_before_erasing_private_state_in_object_lists(
    db_session,
):
    navigation_source = {
        "key": "cockpit",
        "label": "Source cockpit",
        "glyph": "radar",
        "variant": "primary",
        "object": "mission",
    }
    navigation_target = {
        **navigation_source,
        "label": "Target cockpit",
        "runtime_cursor": "private-navigation-state",
    }
    source = _workspace(
        db_session,
        id_="ws-source",
        slug="source",
        settings={
            "family": "generic",
            "assistant_profiles": [{"key": "guide", "label": "Source guide"}],
            "knowledge_scopes": [
                {
                    "key": "primary",
                    "label": "Source scope",
                    "collection_slugs": ["source-collection"],
                }
            ],
            "mission_room": {"enabled": True, "navigation": [navigation_source]},
            "document_intelligence": {
                "enabled": True,
                "profiles": [{"key": "brief", "label": "Source brief"}],
            },
        },
    )
    user = _user(db_session)
    blueprint = workspace_blueprints.export_workspace_blueprint(
        db=db_session,
        workspace=source,
        exported_by=user,
    )
    target_settings = {
        "family": "generic",
        "assistant_profiles": [
            {
                "key": "guide",
                "label": "Target guide",
                "runtime_session": "private-assistant-state",
            }
        ],
        "knowledge_scopes": [
            {
                "key": "primary",
                "label": "Target scope",
                "collection_slugs": ["target-collection"],
                "runtime_cache": "private-scope-state",
            }
        ],
        "mission_room": {"enabled": True, "navigation": [navigation_target]},
        "document_intelligence": {
            "enabled": True,
            "profiles": [
                {
                    "key": "brief",
                    "label": "Target brief",
                    "runtime_model": "private-document-state",
                }
            ],
        },
    }
    target = _workspace(
        db_session,
        id_="ws-target",
        slug="target",
        settings=deepcopy(target_settings),
    )

    report = workspace_blueprints.apply_workspace_blueprint(
        db=db_session,
        workspace=target,
        blueprint=blueprint,
        actor=user,
        dry_run=True,
        experience_policy="replace_portable",
    )

    conflict_paths = {
        item["path"]
        for item in report["experience"]["conflicts"]
        if item.get("reason") == "target_contains_nonportable_list_state"
    }
    assert conflict_paths == {
        "/workspace/settings/assistant_profiles",
        "/workspace/settings/knowledge_scopes",
        "/workspace/settings/mission_room/navigation",
        "/workspace/settings/document_intelligence/profiles",
    }
    encoded_report = json.dumps(report, sort_keys=True)
    assert "private-assistant-state" not in encoded_report
    assert "private-scope-state" not in encoded_report
    assert "private-navigation-state" not in encoded_report
    assert "private-document-state" not in encoded_report

    with pytest.raises(
        workspace_blueprints.WorkspaceBlueprintConflictError,
        match="experience conflicts",
    ):
        workspace_blueprints.apply_workspace_blueprint(
            db=db_session,
            workspace=target,
            blueprint=blueprint,
            actor=user,
            dry_run=False,
            experience_policy="replace_portable",
            expected_plan_token=report["plan_token"],
        )
    assert target.settings == target_settings
