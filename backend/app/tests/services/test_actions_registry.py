from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import actions
from app.core.iam.roles import WORKSPACE_OWNER
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services.actions import effective_action_manifests, execute_action, handle_transverse_chat_action, resolve_action
from app.services.action_plans import list_action_items


def _workspace(slug: str, *, settings: dict | None = None) -> Workspace:
    return Workspace(id=f"ws-{slug}", slug=slug, name=slug.title(), settings=settings or {}, mode="builder")


def test_andritz_inherits_industrial_actions_but_not_aya():
    workspace = _workspace("andritz")

    ids = {action.action_id for action in effective_action_manifests(workspace, surface="chat")}

    assert "andritz.find_parameter_value" in ids
    assert "andritz.locate_evidence_table" in ids
    assert "aya.action_plan_status" not in ids


def test_sentinel_inherits_aya_actions_without_andritz_pack():
    workspace = _workspace("sentinel-ci")

    ids = {action.action_id for action in effective_action_manifests(workspace, surface="chat")}

    assert "aya.action_plan_status" in ids
    assert "andritz.find_parameter_value" not in ids


def test_octocity_inherits_octave_actions_without_aya_pack():
    workspace = _workspace(
        "octocity-mission-room",
        settings={
            "mission_room": {"profile": "octocity_institutional_v1"},
            "assistant_profile_default": "octave_executive",
            "actions": {"enabled_packs": ["global_voice_v1", "octave_mission_room_v1", "octave_security_v1"]},
            "assistant_profiles": [
                {
                    "key": "octave_executive",
                    "actions": {"enabled_packs": ["global_voice_v1", "octave_mission_room_v1", "octave_security_v1"]},
                }
            ],
        },
    )

    ids = {action.action_id for action in effective_action_manifests(workspace, surface="chat", assistant_profile="octave_executive")}

    assert "octave.priority_summary" in ids
    assert "octave.show_security_posture" in ids
    assert "aya.priority_summary" not in ids


def test_global_voice_actions_are_trans_workspace():
    andritz = _workspace("andritz")
    sentinel = _workspace("sentinel-ci")

    andritz_ids = {action.action_id for action in effective_action_manifests(andritz, surface="voice")}
    sentinel_ids = {action.action_id for action in effective_action_manifests(sentinel, surface="voice")}

    assert "voice.stop" in andritz_ids
    assert "voice.stop" in sentinel_ids
    assert resolve_action(andritz, text="on peut s'arrêter là", surface="voice").action_id == "voice.stop"


def test_catalog_override_can_enable_aya_in_andritz():
    workspace = _workspace("andritz", settings={"catalog": {"enabled_capabilities": ["aya_voice_command"]}})

    ids = {action.action_id for action in effective_action_manifests(workspace, surface="chat")}

    assert "aya.action_plan_status" in ids
    assert "andritz.find_parameter_value" in ids


def test_resolver_matches_andritz_parameter_action():
    workspace = _workspace("andritz")

    result = resolve_action(
        workspace,
        text="Peux-tu retrouver le diamètre labellisé par la lettre B ?",
        surface="chat",
    )

    assert result.matched is True
    assert result.action_id == "andritz.find_parameter_value"
    assert result.requires_confirmation is False


def test_aya_side_effect_action_requires_confirmation_before_legacy_execution(db_session):
    workspace = _workspace(
        "sentinel-ci",
        settings={"action_planner": {"write_policy": "direct"}},
    )
    user = User(id="user-1", username="minister", email="minister@example.test", is_active=True)
    db_session.add_all([workspace, user])
    db_session.commit()

    result = handle_transverse_chat_action(
        db_session,
        workspace,
        user,
        query="Ajoute une action cabinet prioritaire pour preparer les elements de langage a 10h30",
        assistant_profile="vigie_executive",
    )

    assert result is not None
    assert result["action"] == "action_plan_proposal"
    assert result["requires_confirmation"] is True
    assert len(list_action_items(db_session, workspace)) == 0


def test_aya_confirmed_legacy_action_executes(db_session):
    workspace = _workspace(
        "sentinel-ci",
        settings={"action_planner": {"write_policy": "direct"}},
    )
    user = User(id="user-1", username="minister", email="minister@example.test", is_active=True)
    db_session.add_all([workspace, user])
    db_session.commit()

    result = execute_action(
        db_session,
        workspace,
        user,
        action_id="aya.action_plan_create",
        text="Ajoute une action cabinet prioritaire pour preparer les elements de langage a 10h30",
        surface="chat",
        assistant_profile="vigie_executive",
        confirm=True,
    )

    assert result["reason"] == "executed"
    assert result["result"]["action"] == "action_plan_create"
    assert len(list_action_items(db_session, workspace)) == 1


def test_aya_voice_side_effect_resolves_as_confirmable():
    workspace = _workspace("sentinel-ci")

    result = resolve_action(
        workspace,
        text="AYA crée une action pour préparer une réponse presse",
        surface="voice",
        assistant_profile="vigie_executive",
    )

    assert result.matched is True
    assert result.action_id == "aya.action_plan_create"
    assert result.requires_confirmation is True


def test_octave_wake_word_resolves_mission_room_action():
    workspace = _workspace(
        "octocity-mission-room",
        settings={
            "mission_room": {"profile": "octocity_institutional_v1"},
            "assistant_profile_default": "octave_executive",
            "actions": {"enabled_packs": ["global_voice_v1", "octave_mission_room_v1", "octave_security_v1"]},
        },
    )

    result = resolve_action(
        workspace,
        text="OCTAVE, donne-moi le cockpit",
        surface="chat",
        assistant_profile="octave_executive",
    )

    assert result.matched is True
    assert result.action_id == "octave.priority_summary"
    assert result.requires_confirmation is False


def test_actions_api_exposes_effective_actions(db_session):
    workspace = _workspace("andritz")
    user = User(id="user-1", username="thib", email="thib@example.test", is_active=True)
    membership = WorkspaceMember(
        user_id=user.id,
        workspace_id=workspace.id,
        role="owner",
        role_template=WORKSPACE_OWNER,
    )
    db_session.add_all([workspace, user, membership])
    db_session.commit()

    app = FastAPI()
    app.include_router(actions.router, prefix="/api/v1/actions")
    app.dependency_overrides[actions.get_current_workspace] = lambda: workspace
    app.dependency_overrides[actions.get_current_user] = lambda: user
    app.dependency_overrides[actions.get_db] = lambda: db_session

    response = TestClient(app).get("/api/v1/actions/effective?surface=chat")

    assert response.status_code == 200
    ids = {item["action_id"] for item in response.json()["actions"]}
    assert "andritz.find_parameter_value" in ids
    assert "aya.action_plan_status" not in ids


def test_actions_api_exposes_sentinel_voice_pack_for_vigie(db_session):
    workspace = _workspace(
        "sentinel-ci",
        settings={
            "assistant_profiles": [
                {
                    "key": "vigie_executive",
                    "actions": {"enabled_packs": ["global_voice_v1", "sentinel_ci_aya_v1"]},
                }
            ]
        },
    )
    user = User(id="user-1", username="thib", email="thib@example.test", is_active=True)
    membership = WorkspaceMember(
        user_id=user.id,
        workspace_id=workspace.id,
        role="owner",
        role_template=WORKSPACE_OWNER,
    )
    db_session.add_all([workspace, user, membership])
    db_session.commit()

    app = FastAPI()
    app.include_router(actions.router, prefix="/api/v1/actions")
    app.dependency_overrides[actions.get_current_workspace] = lambda: workspace
    app.dependency_overrides[actions.get_current_user] = lambda: user
    app.dependency_overrides[actions.get_db] = lambda: db_session

    response = TestClient(app).get("/api/v1/actions/effective?surface=voice&assistant_profile=vigie_executive")

    assert response.status_code == 200
    ids = {item["action_id"] for item in response.json()["actions"]}
    assert "voice.stop" in ids
    assert "aya.map_focus" in ids
    assert "aya.action_plan_create" in ids
