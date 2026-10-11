from __future__ import annotations

import pytest

from app.extensions.registry import (
    MISSION_ROOM_EXTENSION_ID,
    WorkspaceExtension,
    WorkspaceExtensionRegistry,
    workspace_extension_registry,
)
from app.models.workspace import Workspace


@pytest.mark.parametrize(
    ("mission_room_settings", "expected"),
    [
        ({"enabled": True}, True),
        ({"enabled": False}, False),
        ({"enabled": "true"}, False),
        ({"enabled": 1}, False),
        ({}, False),
        (None, False),
    ],
)
def test_mission_room_extension_requires_literal_enabled_true(
    mission_room_settings,
    expected,
):
    settings = {"mission_room": mission_room_settings} if mission_room_settings is not None else {}
    workspace = Workspace(
        id="workspace-extension-test",
        slug="renamed-workspace",
        name="Renamed Workspace",
        settings=settings,
    )

    assert (
        workspace_extension_registry.enabled_for(
            MISSION_ROOM_EXTENSION_ID,
            workspace,
        )
        is expected
    )


def test_workspace_extension_selection_does_not_depend_on_slug_or_profile():
    enabled = Workspace(
        id="workspace-enabled",
        slug="ordinary-workspace",
        name="Ordinary Workspace",
        settings={"mission_room": {"enabled": True, "profile": "custom_v1"}},
    )
    disabled = Workspace(
        id="workspace-disabled",
        slug="sentinel-ci",
        name="SENTINEL-CI",
        settings={"mission_room": {"enabled": False}},
    )

    assert workspace_extension_registry.enabled_for(MISSION_ROOM_EXTENSION_ID, enabled)
    assert not workspace_extension_registry.enabled_for(
        MISSION_ROOM_EXTENSION_ID,
        disabled,
    )


def test_workspace_extension_registry_rejects_duplicate_ids():
    registry = WorkspaceExtensionRegistry()
    extension = WorkspaceExtension(
        extension_id="example",
        enabled_setting_path=("example", "enabled"),
    )
    registry.register(extension)

    with pytest.raises(ValueError, match="already registered"):
        registry.register(extension)
