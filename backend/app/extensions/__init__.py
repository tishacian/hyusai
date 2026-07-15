"""Workspace-scoped product extension contracts."""

from app.extensions.registry import (
    MISSION_ROOM_EXTENSION_ID,
    WORKSPACE_EXTENSION_NOT_FOUND_CODE,
    WorkspaceExtension,
    WorkspaceExtensionRegistry,
    require_workspace_extension,
    workspace_extension_registry,
)

__all__ = [
    "MISSION_ROOM_EXTENSION_ID",
    "WORKSPACE_EXTENSION_NOT_FOUND_CODE",
    "WorkspaceExtension",
    "WorkspaceExtensionRegistry",
    "require_workspace_extension",
    "workspace_extension_registry",
]
