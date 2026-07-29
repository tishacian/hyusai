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

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session as DBSession

from app.core.auth import get_current_workspace
from app.db.base import get_db
from app.models.workspace import Workspace
from app.services.workspace_app_runtime import (
    WorkspaceAppRuntimeError,
    installed_app_ids,
    mission_room_provider_request_allowed,
    resolve_mission_room_provider_runtime,
    workspace_app_api_path_allowed,
    workspace_app_platform_enabled,
)

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
        request: Request,
        workspace: Workspace = Depends(get_current_workspace),
        db: DBSession = Depends(get_db),
    ) -> Workspace:
        if workspace_app_platform_enabled(workspace):
            try:
                if extension_id == MISSION_ROOM_EXTENSION_ID:
                    # Installation alone is not sufficient.  Provider
                    # readiness and route ownership are separate contracts:
                    # the generic provider owns only its explicitly declared
                    # core routes, while specialized shared-prefix routes stay
                    # private to their historical provider apps.
                    runtime = resolve_mission_room_provider_runtime(workspace, db=db)
                    projection = runtime.mission_room or {}
                    provider_app_id = str(projection.get("app_id") or "")
                    enabled = (
                        bool(provider_app_id)
                        and workspace_app_api_path_allowed(
                            workspace,
                            request.url.path,
                            db=db,
                            app_ids=(provider_app_id,),
                        )
                        and mission_room_provider_request_allowed(
                            runtime,
                            request.method,
                            request.url.path,
                        )
                    )
                else:
                    installed = installed_app_ids(workspace, db=db)
                    enabled = extension_id in installed
            except WorkspaceAppRuntimeError:
                enabled = False
        else:
            enabled = extension.enabled_for(workspace)
        if not enabled:
            # Keep this response identical for disabled and unavailable
            # extensions: callers must not learn deployment topology.
            raise HTTPException(
                status_code=404,
                detail={"code": WORKSPACE_EXTENSION_NOT_FOUND_CODE},
            )
        return workspace

    dependency.__name__ = f"require_{extension_id.replace('-', '_')}_extension"
    return dependency
