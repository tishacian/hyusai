"""Canonical granular authorization boundary for starting a System execution.

Every surface that creates a real System-backed Run must cross this helper
before persisting the Run or dispatching work.  Keeping the boundary outside
the HTTP routers prevents Chat, Intelligence, or a future Workspace App from
silently bypassing an enforced ``system.engine.run`` decision.
"""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session as DBSession

from app.models.system import System
from app.models.user import User
from app.models.workspace import Workspace
from app.services.iam.decision_plane import ActionResolution, enforce_action


def enforce_system_engine_run(
    db: DBSession,
    *,
    user: User,
    workspace: Workspace,
    system: System,
    source: str,
) -> ActionResolution:
    """Authorize one real execution without widening the legacy surface gate.

    ``legacy_allowed=True`` preserves the existing Chat/Intelligence contract
    in compat and shadow modes.  An exact, attested enforcement promotion is
    nevertheless authoritative and fail-closed through ``enforce_action``.
    """

    if str(system.workspace_id or "") != str(workspace.id):
        raise HTTPException(status_code=404, detail="System not found")
    return enforce_action(
        db,
        user=user,
        workspace=workspace,
        resource_kind="system",
        action="engine.run",
        legacy_allowed=True,
        resource_attrs={
            "system_id": system.id,
            "capability_id": system.capability_id,
            "execution_source": source,
        },
    )
