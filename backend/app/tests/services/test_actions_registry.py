from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import actions
from app.core.iam.roles import WORKSPACE_OWNER
from app.models.capability import Capability
from app.models.system import System
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services.action_plans import list_action_items
from app.services.actions import (
    effective_action_manifests,
    execute_action,
    handle_transverse_chat_action,
    resolve_action,
)
from app.services.actions import registry as action_registry
from app.services.actions.contracts import ACTION_PACK_IDS
from app.services.actions.registry import PACKS


def _workspace(slug: str, *, settings: dict | None = None) -> Workspace:
    return Workspace(
        id=f"ws-{slug}", slug=slug, name=slug.title(), settings=settings or {}, mode="builder"
    )


def _actions_api_client(db_session, workspace: Workspace, *, user_id: str) -> TestClient:
    user = User(
        id=user_id,
        username=user_id,
        email=f"{user_id}@example.test",
        is_active=True,
    )
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
    return TestClient(app)


def test_andritz_inherits_industrial_actions_but_not_aya():
    workspace = _workspace("andritz", settings={"family": "andritz"})

    ids = {action.action_id for action in effective_action_manifests(workspace, surface="chat")}

    assert "andritz.find_parameter_value" in ids
    assert "andritz.locate_evidence_table" in ids
    assert "aya.action_plan_status" not in ids


def test_sentinel_inherits_aya_actions_without_andritz_pack():
    workspace = _workspace(
        "sentinel-ci",
        settings={"family": "sentinel_ci"},
    )

    ids = {action.action_id for action in effective_action_manifests(workspace, surface="chat")}

    assert "aya.action_plan_status" in ids
    assert "andritz.find_parameter_value" not in ids


def test_octocity_inherits_octave_actions_without_aya_pack():
    workspace = _workspace(
        "octocity-mission-room",
        settings={
            "mission_room": {"profile": "octocity_institutional_v1"},
            "assistant_profile_default": "octave_executive",
            "actions": {
                "enabled_packs": ["global_voice_v1", "octave_mission_room_v1", "octave_security_v1"]
            },
            "assistant_profiles": [
                {
                    "key": "octave_executive",
                    "actions": {
                        "enabled_packs": [
                            "global_voice_v1",
                            "octave_mission_room_v1",
                            "octave_security_v1",
                        ]
                    },
                }
            ],
        },
    )

    ids = {
        action.action_id
        for action in effective_action_manifests(
            workspace, surface="chat", assistant_profile="octave_executive"
        )
    }

    assert "octave.priority_summary" in ids
    assert "octave.show_security_posture" in ids
    assert "aya.priority_summary" not in ids


def test_octocity_effective_action_contract_is_neutral_and_keeps_legacy_handler(db_session):
    workspace = _workspace(
        "octocity-mission-room",
        settings={
            "mission_room": {"profile": "octocity_institutional_v1"},
            "assistant_profile_default": "octave_executive",
            "actions": {
                "enabled_packs": ["global_voice_v1", "octave_mission_room_v1", "octave_security_v1"]
            },
            "assistant_profiles": [
                {
                    "key": "octave_executive",
                    "actions": {
                        "enabled_packs": [
                            "global_voice_v1",
                            "octave_mission_room_v1",
                            "octave_security_v1",
                        ]
                    },
                }
            ],
        },
    )
    workspace.mode = "demo"
    client = _actions_api_client(db_session, workspace, user_id="octocity-actions-owner")

    response = client.get("/api/v1/actions/effective?assistant_profile=octave_executive")

    assert response.status_code == 200
    payload = response.json()
    action_ids = {item["action_id"] for item in payload["actions"]}
    packs = {item["pack"] for item in payload["actions"]}
    assert packs == {"global_voice_v1", "octave_mission_room_v1", "octave_security_v1"}
    assert "octave.recommend_diversification" in action_ids
    assert "octave.recommend_cacao" not in action_ids
    assert not any(action_id.startswith("aya.") for action_id in action_ids)

    execute_response = client.post(
        "/api/v1/actions/execute",
        json={
            "action_id": "octave.recommend_diversification",
            "surface": "chat",
            "assistant_profile": "octave_executive",
            "confirm": True,
        },
    )
    assert execute_response.status_code == 200
    execute_payload = execute_response.json()
    assert execute_payload["result"]["handler"] == {"kind": "managed", "name": "managed"}

    manifests_response = client.get("/api/v1/actions/manifests")
    assert manifests_response.status_code == 200
    manifests_payload = manifests_response.json()
    assert not any(item["action_id"].startswith("aya.") for item in manifests_payload["manifests"])

    serialized = json.dumps(
        [payload, execute_payload, manifests_payload],
        ensure_ascii=False,
    ).casefold()
    for forbidden in (
        "sentinel",
        "aya",
        "cacao",
        "cocoa",
        "anacarde",
        "nawa",
        "abidjan",
        "cedeao",
        "fanci",
        "cote d'ivoire",
        "côte d'ivoire",
        "vice premier ministre",
        "prefet",
        "préfet",
        "sahel",
        "napié",
        "napie",
    ):
        assert forbidden not in serialized

    public_manifest = next(
        manifest
        for manifest in effective_action_manifests(
            workspace,
            assistant_profile="octave_executive",
        )
        if manifest.action_id == "octave.recommend_diversification"
    )
    assert public_manifest.handler.name == "recommend_cacao"


def test_sentinel_effective_action_contract_remains_isolated_from_octocity(db_session):
    workspace = _workspace(
        "sentinel-ci",
        settings={
            "mission_room": {"profile": "sentinel_government_v1"},
            "assistant_profile_default": "vigie_executive",
            "actions": {
                "enabled_packs": [
                    "global_voice_v1",
                    "sentinel_ci_aya_v1",
                    "sentinel_ci_aya_security_v1",
                ]
            },
            "assistant_profiles": [
                {
                    "key": "vigie_executive",
                    "actions": {
                        "enabled_packs": [
                            "global_voice_v1",
                            "sentinel_ci_aya_v1",
                            "sentinel_ci_aya_security_v1",
                        ]
                    },
                }
            ],
        },
    )
    workspace.mode = "demo"
    client = _actions_api_client(db_session, workspace, user_id="sentinel-actions-owner")

    response = client.get("/api/v1/actions/effective?assistant_profile=vigie_executive")

    assert response.status_code == 200
    payload = response.json()
    action_ids = {item["action_id"] for item in payload["actions"]}
    packs = {item["pack"] for item in payload["actions"]}
    assert packs == {"global_voice_v1", "sentinel_ci_aya_v1", "sentinel_ci_aya_security_v1"}
    assert "aya.recommend_cacao" in action_ids
    assert not any(action_id.startswith("octave.") for action_id in action_ids)

    manifests_response = client.get("/api/v1/actions/manifests")
    assert manifests_response.status_code == 200
    manifests_payload = manifests_response.json()
    assert not any(
        item["action_id"].startswith("octave.") for item in manifests_payload["manifests"]
    )

    serialized = json.dumps([payload, manifests_payload], ensure_ascii=False).casefold()
    for forbidden in (
        "octocity",
        "octave",
        "asteria",
        "meridian",
        "liora",
        "auralis",
        "alliance aurora",
        "bio-composites",
        "fibre solaire",
    ):
        assert forbidden not in serialized


def test_global_voice_actions_are_trans_workspace():
    andritz = _workspace("andritz")
    sentinel = _workspace("sentinel-ci")

    andritz_ids = {
        action.action_id for action in effective_action_manifests(andritz, surface="voice")
    }
    sentinel_ids = {
        action.action_id for action in effective_action_manifests(sentinel, surface="voice")
    }

    assert "voice.stop" in andritz_ids
    assert "voice.stop" in sentinel_ids
    assert (
        resolve_action(andritz, text="on peut s'arrêter là", surface="voice").action_id
        == "voice.stop"
    )


def test_registry_exactly_matches_the_canonical_action_pack_contract():
    assert tuple(PACKS) == ACTION_PACK_IDS
    assert all(
        manifest.pack == pack_id for pack_id, manifests in PACKS.items() for manifest in manifests
    )


def test_workspace_slug_and_name_do_not_implicitly_enable_tenant_packs():
    workspaces = (
        _workspace("andritz"),
        _workspace("sentinel-ci"),
        _workspace("octocity-mission-room"),
    )

    for workspace in workspaces:
        ids = {action.action_id for action in effective_action_manifests(workspace, surface="chat")}
        assert not any(action_id.startswith(("andritz.", "aya.", "octave.")) for action_id in ids)


def test_catalog_override_can_enable_aya_in_andritz():
    workspace = _workspace(
        "andritz",
        settings={
            "family": "andritz",
            "catalog": {"enabled_capabilities": ["aya_voice_command"]},
        },
    )

    ids = {action.action_id for action in effective_action_manifests(workspace, surface="chat")}

    assert "aya.action_plan_status" in ids
    assert "andritz.find_parameter_value" in ids


def test_resolver_matches_andritz_parameter_action():
    workspace = _workspace("andritz", settings={"family": "andritz"})

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
        settings={
            "mission_room": {"profile": "sentinel_government_v1"},
            "action_planner": {"write_policy": "direct"},
        },
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
        settings={
            "mission_room": {"profile": "sentinel_government_v1"},
            "action_planner": {"write_policy": "direct"},
        },
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


def test_chat_manifest_execution_resolves_its_declared_permission(
    db_session,
    monkeypatch,
):
    workspace = _workspace(
        "sentinel-chat-authz",
        settings={
            "family": "sentinel_ci",
            "mission_room": {"profile": "sentinel_government_v1"},
        },
    )
    user = User(
        id="user-chat-authz",
        username="chat-authz",
        email="chat-authz@example.test",
        is_active=True,
    )
    db_session.add_all([workspace, user])
    db_session.commit()
    calls: list[dict] = []

    def _resolve(*_args, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            effective_allowed=True,
            reason="candidate_allowed",
            mode="shadow",
            policy_id="aya_voice_command:action.execute",
        )

    monkeypatch.setattr(action_registry, "resolve_manifest_permission", _resolve)

    result = handle_transverse_chat_action(
        db_session,
        workspace,
        user,
        query="statut des actions",
        assistant_profile="vigie_executive",
    )

    assert result is not None
    assert result["action_manifest_id"] == "aya.action_plan_status"
    assert len(calls) == 1
    assert calls[0]["required_permission"] == "action.execute"
    assert calls[0]["capability_manifest"] == "aya_voice_command"
    assert calls[0]["action_id"] == "aya.action_plan_status"


def test_chat_manifest_execution_stops_when_candidate_is_denied_in_enforce(
    db_session,
    monkeypatch,
):
    workspace = _workspace(
        "sentinel-chat-denied",
        settings={
            "family": "sentinel_ci",
            "mission_room": {"profile": "sentinel_government_v1"},
        },
    )
    user = User(
        id="user-chat-denied",
        username="chat-denied",
        email="chat-denied@example.test",
        is_active=True,
    )
    db_session.add_all([workspace, user])
    db_session.commit()
    monkeypatch.setattr(
        action_registry,
        "resolve_manifest_permission",
        lambda *_args, **_kwargs: SimpleNamespace(
            effective_allowed=False,
            reason="role_denied",
            mode="enforce",
            policy_id="aya_voice_command:action.execute",
        ),
    )
    executed: list[str] = []
    monkeypatch.setattr(
        action_registry,
        "execute_action",
        lambda *_args, **_kwargs: executed.append("executed"),
    )

    result = handle_transverse_chat_action(
        db_session,
        workspace,
        user,
        query="statut des actions",
        assistant_profile="vigie_executive",
    )

    assert result is not None
    assert result["action"] == "action_denied"
    assert result["authorization"]["mode"] == "enforce"
    assert executed == []


@pytest.mark.parametrize("mode", ["compat", "shadow"])
def test_unmanifested_chat_fallback_remains_compatible_before_enforce(
    db_session,
    monkeypatch,
    mode,
):
    workspace = _workspace("legacy-chat-fallback")
    user = User(
        id=f"user-legacy-chat-{mode}",
        username=f"legacy-chat-{mode}",
        email=f"legacy-chat-{mode}@example.test",
        is_active=True,
    )
    db_session.add_all([workspace, user])
    db_session.commit()
    monkeypatch.setattr(
        action_registry,
        "resolve_manifest_permission",
        lambda *_args, **_kwargs: SimpleNamespace(
            effective_allowed=True,
            reason="legacy_allowed",
            mode=mode,
            policy_id="agentium_actions:action.execute",
        ),
    )
    calls: list[str] = []

    def _fallback(*_args, query: str, **_kwargs):
        calls.append(query)
        return {"action": "legacy", "applied": True, "content": "legacy result"}

    monkeypatch.setattr(action_registry, "handle_action_plan_chat_action", _fallback)
    query = "état des instructions hors manifeste"
    assert (
        resolve_action(
            workspace,
            text=query,
            surface="chat",
            assistant_profile="vigie_executive",
        ).matched
        is False
    )

    result = handle_transverse_chat_action(
        db_session,
        workspace,
        user,
        query=query,
        assistant_profile="vigie_executive",
    )

    assert result == {"action": "legacy", "applied": True, "content": "legacy result"}
    assert calls == [query]


def test_unmanifested_chat_fallback_cannot_act_in_enforce(
    db_session,
    monkeypatch,
):
    workspace = _workspace("enforce-chat-fallback")
    user = User(
        id="user-enforce-chat-fallback",
        username="enforce-chat-fallback",
        email="enforce-chat-fallback@example.test",
        is_active=True,
    )
    db_session.add_all([workspace, user])
    db_session.commit()
    monkeypatch.setattr(
        action_registry,
        "resolve_manifest_permission",
        lambda *_args, **_kwargs: SimpleNamespace(
            effective_allowed=True,
            reason="candidate_allowed",
            mode="enforce",
            policy_id="agentium_actions:action.execute",
        ),
    )
    calls: list[str] = []
    monkeypatch.setattr(
        action_registry,
        "handle_action_plan_chat_action",
        lambda *_args, **_kwargs: calls.append("executed"),
    )
    query = "état des instructions hors manifeste"
    assert (
        resolve_action(
            workspace,
            text=query,
            surface="chat",
            assistant_profile="vigie_executive",
        ).matched
        is False
    )

    result = handle_transverse_chat_action(
        db_session,
        workspace,
        user,
        query=query,
        assistant_profile="vigie_executive",
    )

    assert result is not None
    assert result["action"] == "action_denied"
    assert result["authorization"] == {
        "mode": "enforce",
        "reason": "manifest_required_in_enforce",
        "policy_id": "agentium_actions:action.execute",
    }
    assert calls == []


def test_unmanifested_chat_fallback_fails_closed_when_enforce_attestation_drifts(
    db_session,
    monkeypatch,
):
    workspace = _workspace("invalid-enforce-chat-fallback")
    user = User(
        id="user-invalid-enforce-chat-fallback",
        username="invalid-enforce-chat-fallback",
        email="invalid-enforce-chat-fallback@example.test",
        is_active=True,
    )
    db_session.add_all([workspace, user])
    db_session.commit()
    monkeypatch.setattr(
        action_registry,
        "resolve_manifest_permission",
        lambda *_args, **_kwargs: SimpleNamespace(
            effective_allowed=False,
            reason="authorization_enforcement_attestation_invalid",
            mode="invalid_enforce",
            policy_id="agentium_actions:action.execute",
        ),
    )
    calls: list[str] = []
    monkeypatch.setattr(
        action_registry,
        "handle_action_plan_chat_action",
        lambda *_args, **_kwargs: calls.append("executed"),
    )

    result = handle_transverse_chat_action(
        db_session,
        workspace,
        user,
        query="état des instructions hors manifeste",
        assistant_profile="vigie_executive",
    )

    assert result is not None
    assert result["action"] == "action_denied"
    assert result["authorization"] == {
        "mode": "invalid_enforce",
        "reason": "authorization_enforcement_attestation_invalid",
        "policy_id": "agentium_actions:action.execute",
    }
    assert calls == []


def test_aya_voice_side_effect_resolves_as_confirmable():
    workspace = _workspace(
        "sentinel-ci",
        settings={"mission_room": {"profile": "sentinel_government_v1"}},
    )

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
            "actions": {
                "enabled_packs": ["global_voice_v1", "octave_mission_room_v1", "octave_security_v1"]
            },
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
    workspace = _workspace("andritz", settings={"family": "andritz"})
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


def test_action_execute_binds_manifest_permission_to_scoped_system(
    db_session,
    monkeypatch,
):
    workspace = _workspace("andritz-action-scope", settings={"family": "andritz"})
    client = _actions_api_client(
        db_session,
        workspace,
        user_id="andritz-action-scope-owner",
    )
    capability = Capability(
        id="capability-action-scope",
        workspace_id=workspace.id,
        slug="action_scope_capability",
        name="Action scope capability",
    )
    system = System(
        id="system-action-scope",
        workspace_id=workspace.id,
        capability_id=capability.id,
        name="Action scope system",
        objective="Bind an action authorization to its real object",
        status="active",
        flow_definition={"nodes": [], "edges": []},
    )
    other_workspace = _workspace("other-action-scope")
    other_system = System(
        id="system-other-action-scope",
        workspace_id=other_workspace.id,
        name="Other workspace system",
        objective="Must stay invisible",
        status="active",
        flow_definition={"nodes": [], "edges": []},
    )
    db_session.add_all([capability, system, other_workspace, other_system])
    db_session.commit()
    calls: list[dict] = []

    def _allow(*_args, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            effective_allowed=True,
            reason="candidate_allowed",
            mode="shadow",
            policy_id="agentium_actions:action.execute",
        )

    monkeypatch.setattr(actions, "resolve_manifest_permission", _allow)
    response = client.post(
        "/api/v1/actions/execute",
        json={
            "action_id": "andritz.find_parameter_value",
            "surface": "chat",
            "system_id": system.id,
            "confirm": True,
        },
    )

    assert response.status_code == 200
    assert calls[0]["resource_attrs"] == {
        "workspace_id": workspace.id,
        "system_id": system.id,
        "capability_id": capability.id,
        "capability": "expert_knowledge_capture",
        "action_id": "andritz.find_parameter_value",
    }
    assert (
        client.post(
            "/api/v1/actions/execute",
            json={
                "action_id": "andritz.find_parameter_value",
                "surface": "chat",
                "system_id": other_system.id,
                "confirm": True,
            },
        ).status_code
        == 404
    )


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

    response = TestClient(app).get(
        "/api/v1/actions/effective?surface=voice&assistant_profile=vigie_executive"
    )

    assert response.status_code == 200
    ids = {item["action_id"] for item in response.json()["actions"]}
    assert "voice.stop" in ids
    assert "aya.map_focus" in ids
    assert "aya.action_plan_create" in ids
