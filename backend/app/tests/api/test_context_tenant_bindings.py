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


@pytest.mark.asyncio
async def test_context_freshness_uses_source_dates_without_crossing_tenants(db_session):
    from datetime import datetime

    from app.models.knowledge_collection import KnowledgeCollection, KnowledgeCollectionSource

    workspace = _workspace(db_session, "freshness")
    foreign = _workspace(db_session, "foreign-freshness")
    old, recent = datetime(2026, 1, 1), datetime(2026, 10, 20)
    local = KnowledgeCollection(
        id=str(uuid4()),
        workspace_id=workspace.id,
        slug="manual",
        name="Manual",
        vector_collection_name="manual-local",
        artifact_prefix="test/manual",
    )
    other = KnowledgeCollection(
        id=str(uuid4()),
        workspace_id=foreign.id,
        slug="foreign-only",
        name="Hidden",
        vector_collection_name="manual-foreign",
        artifact_prefix="test/hidden",
    )
    db_session.add_all([local, other])
    db_session.flush()
    source = KnowledgeCollectionSource(
        id=str(uuid4()),
        workspace_id=workspace.id,
        collection_id=local.id,
        filename="manual.pdf",
        normalized_name="manual.pdf",
        status="ready",
        updated_at=old,
    )
    hidden = KnowledgeCollectionSource(
        id=str(uuid4()),
        workspace_id=foreign.id,
        collection_id=other.id,
        filename="hidden.pdf",
        normalized_name="hidden.pdf",
        status="ready",
        updated_at=old,
    )
    context = Context(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name="Fresh edit",
        version=7,
        updated_at=recent,
        data_refs=["collection:manual", "collection:foreign-only"],
    )
    db_session.add_all([source, hidden, context])
    db_session.commit()
    result = await contexts.get_context(context.id, workspace, db_session)
    assert result["updated_at"] == recent.isoformat()
    assert result["source_dates"] == [
        {"ref": "collection:manual", "updated_at": old.isoformat()},
        {"ref": "collection:foreign-only", "updated_at": None},
    ]
