"""Configuration-backed registry for workspace product extensions.

Extension availability is deliberately independent from workspace slugs and
deployment topology. A workspace opts into an extension through its persisted
settings, and API dependencies fail closed when the setting is absent or is
not the literal boolean ``True``.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fastapi import Depends, HTTPException

from app.core.auth import get_current_workspace
from app.models.workspace import Workspace

MISSION_ROOM_EXTENSION_ID = "mission-room"
WORKSPACE_EXTENSION_NOT_FOUND_CODE = "not_found"


@dataclass(frozen=True)
class WorkspaceExtension:
    """Declarative availability contract for one workspace extension."""

    extension_id: str
    enabled_setting_path: tuple[str, ...]

    def enabled_for(self, workspace: Workspace | None) -> bool:
        value: Any = workspace.settings if workspace is not None else None
        for key in self.enabled_setting_path:
            if not isinstance(value, dict):
                return False
            value = value.get(key)
        return value is True


class WorkspaceExtensionRegistry:
    """Small deterministic registry used by API and bootstrap boundaries."""

    def __init__(self) -> None:
        self._extensions: dict[str, WorkspaceExtension] = {}

    def register(self, extension: WorkspaceExtension) -> WorkspaceExtension:
        if extension.extension_id in self._extensions:
            raise ValueError(f"workspace extension already registered: {extension.extension_id}")
        self._extensions[extension.extension_id] = extension
        return extension

    def get(self, extension_id: str) -> WorkspaceExtension:
        try:
            return self._extensions[extension_id]
        except KeyError as exc:
            raise KeyError(f"unknown workspace extension: {extension_id}") from exc

    def enabled_for(self, extension_id: str, workspace: Workspace | None) -> bool:
        return self.get(extension_id).enabled_for(workspace)


workspace_extension_registry = WorkspaceExtensionRegistry()
workspace_extension_registry.register(
    WorkspaceExtension(
        extension_id=MISSION_ROOM_EXTENSION_ID,
        enabled_setting_path=("mission_room", "enabled"),
    )
)


def require_workspace_extension(
    extension_id: str,
) -> Callable[..., Workspace]:
    """Build a FastAPI dependency that hides unavailable extensions as 404."""

    extension = workspace_extension_registry.get(extension_id)

    def dependency(
        workspace: Workspace = Depends(get_current_workspace),
    ) -> Workspace:
        if not extension.enabled_for(workspace):
            # Keep this response identical for disabled and unavailable
            # extensions: callers must not learn deployment topology.
            raise HTTPException(
                status_code=404,
                detail={"code": WORKSPACE_EXTENSION_NOT_FOUND_CODE},
            )
        return workspace

    dependency.__name__ = f"require_{extension_id.replace('-', '_')}_extension"
    return dependency
