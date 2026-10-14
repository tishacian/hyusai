"""Rollouts use persisted workspace policy; caller flags have no authority."""

from app.core.config import settings
from app.models.workspace import Workspace


def enabled(db, workspace_id, feature):
    if getattr(settings, feature, False):
        return True
    workspace = db.get(Workspace, workspace_id)
    return bool(workspace and (workspace.settings or {}).get("features", {}).get(feature) is True)
