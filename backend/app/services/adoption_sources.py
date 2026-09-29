"""Which of the workspace's own collections a member can walk the client journey on.

The client journey (``client_sources``) is only offered on real data: a
collection of *this* workspace that the member can read (ready or still being
indexed) or fill. Nothing here grants access; it only reads what the member
could already reach through ``/documents/collections``.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session as DBSession

from app.core.iam.roles import WORKSPACE_VIEWER, normalize_role_template
from app.models.knowledge_collection import KnowledgeCollection
from app.models.workspace import Workspace, WorkspaceMember
from app.services.collection_access import (
    can_read_collection,
    can_write_collection,
    principal_for_member,
)

# A collection answers questions once ready, and is worth waiting for while
# its documents are queued or indexed. ``created`` (empty) and ``error`` only
# help a member who can add documents.
READABLE_STATUSES = ("ready", "queued", "ingesting", "embedding")
INDEXING_STATUSES = ("queued", "ingesting", "embedding")
MAX_SOURCES = 50


def can_add_documents(member: WorkspaceMember) -> bool:
    """Viewers read; every other workspace role may add documents to an open
    collection (a restricted one also needs its write grant, see L35)."""
    return normalize_role_template(member.role_template, member.role) != WORKSPACE_VIEWER


def _rank(row: KnowledgeCollection) -> tuple[int, str]:
    status = str(row.status or "")
    if status == "ready" and (row.chunk_count or 0) > 0:
        tier = 0
    elif status in INDEXING_STATUSES:
        tier = 1
    elif status == "ready":
        tier = 2
    else:
        tier = 3
    return tier, str(row.name or row.slug or "").lower()


def _serialize(row: KnowledgeCollection, *, writable: bool) -> dict[str, Any]:
    return {
        "id": row.id,
        "slug": row.slug,
        "name": row.name,
        "status": row.status,
        "document_count": int(row.document_count or 0),
        "chunk_count": int(row.chunk_count or 0),
        "can_add_documents": writable,
    }


def member_sources(
    db: DBSession,
    *,
    workspace: Workspace,
    member: WorkspaceMember,
    chosen_collection_id: str | None = None,
) -> dict[str, Any]:
    """Return availability, the usable collections and the one to start on.

    ``available`` is true when the member can read at least one collection of
    this workspace (ready or indexing) or can add documents to one. The
    candidate is the member's earlier choice when still usable, else the first
    ready collection with passages, else the first usable one.
    """
    principal = principal_for_member(member, workspace_id=workspace.id)
    rows = (
        db.query(KnowledgeCollection)
        .filter(KnowledgeCollection.workspace_id == workspace.id)
        .all()
    )
    # Underscore-prefixed collections are internal, as in the collection list.
    rows = [row for row in rows if not str(row.slug or "").startswith("_")]
    # Only collections the member reads; the unfinished ones only when they
    # can fill them (per-collection access, L35).
    writable: dict[str, bool] = {}
    usable = []
    for row in rows:
        if not can_read_collection(principal, row):
            continue
        writable[row.id] = can_write_collection(principal, row)
        if writable[row.id] or row.status in READABLE_STATUSES:
            usable.append(row)
    usable.sort(key=_rank)
    usable = usable[:MAX_SOURCES]
    candidate = next((row for row in usable if row.id == chosen_collection_id), None)
    if candidate is None and usable:
        candidate = usable[0]
    return {
        "available": bool(usable),
        # For the collection the journey starts on; each source says its own.
        "can_add_documents": writable.get(candidate.id, False) if candidate else can_add_documents(member),
        "sources": [_serialize(row, writable=writable[row.id]) for row in usable],
        "candidate_collection_id": candidate.id if candidate else None,
    }


def usable_collection(
    db: DBSession, *, workspace: Workspace, member: WorkspaceMember, collection_id: str
) -> KnowledgeCollection | None:
    """The collection by id, only if it belongs to ``workspace`` and the member can use it."""
    row = (
        db.query(KnowledgeCollection)
        .filter(
            KnowledgeCollection.workspace_id == workspace.id,
            KnowledgeCollection.id == collection_id,
        )
        .first()
    )
    if row is None or str(row.slug or "").startswith("_"):
        return None
    principal = principal_for_member(member, workspace_id=workspace.id)
    if not can_read_collection(principal, row):
        return None
    if not can_write_collection(principal, row) and row.status not in READABLE_STATUSES:
        return None
    return row
