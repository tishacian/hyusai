"""Tenant boundaries for the bidirectional Context/System binding."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.v1.endpoints import contexts
from app.models.context import Context
from app.models.system import System
from app.models.workspace import Workspace


def _workspace(db, key: str) -> Workspace:
    row = Workspace(
        id=str(uuid4()),
        name=f"Context tenant {key}",
        slug=f"context-tenant-{key}-{uuid4().hex[:8]}",
    )
    db.add(row)
    db.flush()
    return row


@pytest.mark.asyncio
async def test_context_create_and_update_reject_system_from_another_workspace(db_session):
    workspace = _workspace(db_session, "owner")
    other = _workspace(db_session, "other")
    foreign_system = System(
        id=str(uuid4()),
        workspace_id=other.id,
        name="Foreign System",
        objective="must remain isolated",
    )
    local_context = Context(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name="Local Context",
    )
    db_session.add_all([foreign_system, local_context])
    db_session.commit()

    with pytest.raises(HTTPException) as create_error:
        await contexts.create_context(
            contexts.ContextBody(
                name="Cross-tenant Context",
                system_id=foreign_system.id,
            ),
            workspace,
            db_session,
        )
    assert create_error.value.status_code == 400

    with pytest.raises(HTTPException) as update_error:
        await contexts.update_context(
            local_context.id,
            contexts.ContextUpdate(system_id=foreign_system.id),
            workspace,
            db_session,
        )
    assert update_error.value.status_code == 400
    db_session.refresh(local_context)
    assert local_context.system_id is None
