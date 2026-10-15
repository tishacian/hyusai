"""New work is canaried; existing work follows its persisted controller."""

from app.core.config import settings
from app.models.workspace import Workspace


def enabled_for(db, workspace_id, flag):
    if not getattr(settings, flag, False):
        return False
    scopes = {
        value.strip() for value in settings.execution_canary_workspaces.split(",") if value.strip()
    }
    if "*" in scopes or workspace_id in scopes:
        return True
    workspace = db.get(Workspace, workspace_id)
    return bool(workspace and workspace.slug in scopes)


def durable_for(db, workspace_id):
    return not settings.worker_eager_mode and any(
        enabled_for(db, workspace_id, flag)
        for flag in ("execution_control_enabled", "execution_durable_dispatch_enabled")
    )
