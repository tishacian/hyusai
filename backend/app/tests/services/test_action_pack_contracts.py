"""Canonical action-pack identifiers at every mutable API boundary."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.api.v1.endpoints.admin import ResetActionsRequest
from app.api.v1.endpoints.auth import WorkspaceUpdate
from app.api.v1.endpoints.systems import SystemCreate, SystemUpdate
from app.services.actions.contracts import (
    ACTION_PACK_IDS,
    ActionPack,
    normalize_action_pack_ids,
)


def test_action_pack_enum_and_order_are_stable():
    assert tuple(pack.value for pack in ActionPack) == ACTION_PACK_IDS


def test_action_pack_list_is_trimmed_deduplicated_and_ordered():
    assert normalize_action_pack_ids(
        [" global_voice_v1 ", "andritz_industrial_v1", "global_voice_v1"],
        path="test.packs",
    ) == ["global_voice_v1", "andritz_industrial_v1"]


@pytest.mark.parametrize(
    "value",
    ["global_voice_v1", ["unknown_pack"], [42]],
)
def test_action_pack_list_rejects_noncanonical_values(value):
    with pytest.raises(ValueError):
        normalize_action_pack_ids(value, path="test.packs")


@pytest.mark.parametrize(
    ("schema", "payload"),
    [
        (
            WorkspaceUpdate,
            {"settings": {"actions": {"enabled_packs": ["unknown_pack"]}}},
        ),
        (
            WorkspaceUpdate,
            {
                "settings": {
                    "assistant_profiles": [
                        {"key": "expert", "actions": {"hidden_packs": ["unknown_pack"]}}
                    ]
                }
            },
        ),
        (
            SystemCreate,
            {"name": "Bad packs", "settings": {"actions": {"action_packs": ["unknown_pack"]}}},
        ),
        (
            SystemUpdate,
            {"execution_profile": {"action_packs": ["unknown_pack"]}},
        ),
        (ResetActionsRequest, {"enabled_packs": ["unknown_pack"]}),
    ],
)
def test_mutable_api_schemas_reject_unknown_action_packs(schema, payload):
    with pytest.raises(ValidationError, match="Unknown action pack"):
        schema.model_validate(payload)


def test_mutable_api_schemas_accept_canonical_action_packs():
    workspace = WorkspaceUpdate.model_validate(
        {
            "settings": {
                "actions": {"enabled_packs": ["andritz_industrial_v1"]},
                "voice_loop": {"command_packs": ["global_voice_v1"]},
            }
        }
    )
    system = SystemCreate.model_validate(
        {
            "name": "Canonical packs",
            "execution_profile": {"action_packs": ["octave_mission_room_v1"]},
        }
    )
    reset = ResetActionsRequest.model_validate(
        {"enabled_packs": ["global_voice_v1", "global_voice_v1"]}
    )

    assert workspace.settings["actions"]["enabled_packs"] == ["andritz_industrial_v1"]
    assert system.execution_profile["action_packs"] == ["octave_mission_room_v1"]
    assert reset.enabled_packs == ["global_voice_v1"]


def test_mutable_api_schemas_persist_normalized_action_pack_lists():
    workspace = WorkspaceUpdate.model_validate(
        {
            "settings": {
                "actions": {
                    "enabled_packs": [
                        " global_voice_v1 ",
                        "global_voice_v1",
                    ]
                },
                "assistant_profiles": [
                    {
                        "key": "expert",
                        "actions": {"enabled_packs": [" andritz_industrial_v1 "]},
                    }
                ],
            }
        }
    )
    system = SystemUpdate.model_validate(
        {
            "execution_profile": {
                "action_packs": [
                    " octave_mission_room_v1 ",
                    "octave_mission_room_v1",
                ]
            }
        }
    )

    assert workspace.settings["actions"]["enabled_packs"] == ["global_voice_v1"]
    assert workspace.settings["assistant_profiles"][0]["actions"]["enabled_packs"] == [
        "andritz_industrial_v1"
    ]
    assert system.execution_profile["action_packs"] == ["octave_mission_room_v1"]
