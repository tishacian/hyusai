"""L36 — a cited passage, readable in place from Work.

One read behind the Work source panel: is the cited document still readable,
its name and collection, the passage in full with a little of the text around
it, and whether its original can be previewed. Nothing is inferred here: a
document the member can no longer read answers 404, and the panel says so
instead of showing an excerpt.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session as DBSession

from app.api.v1.endpoints import documents as documents_api
from app.core.auth import get_current_user, get_current_workspace
from app.core.logging import get_logger
from app.db.base import get_db
from app.models.knowledge_collection import KnowledgeCollection
from app.models.user import User
from app.models.workspace import Workspace
from app.services.knowledge_collections import get_collection_or_404

logger = get_logger(__name__)
router = APIRouter()

PASSAGE_MAX_CHARS = 4000
CONTEXT_CHARS = 280
SCAN_LIMIT = 500
MIN_OVERLAP = 12
MAX_OVERLAP = 600


def readable_collection(
    db: DBSession,
    *,
    workspace: Workspace,
    user: User,
    collection_ref: str,
) -> Optional[KnowledgeCollection]:
    """The collection read gate of the Work source panel.

    Today a member reads every collection of the workspace, which is exactly
    what the preview and download endpoints check (workspace membership, then
    a workspace-scoped lookup). Per-collection access (L35) hooks in here:
    call ``can_read_collection`` and raise 404 when the member may not read
    it, so a removed access reads like a deleted source. Returns ``None`` for
    a store that has no ledger row (session documents), which stays scoped to
    the workspace's own vector store.
    """
    del user  # Used by the per-collection check once it lands.
    try:
        return get_collection_or_404(db, workspace_id=workspace.id, collection_ref=collection_ref)
    except HTTPException:
        return None


def _chunk_index(payload: dict[str, Any]) -> Optional[int]:
    value = payload.get("chunk_index")
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _page(payload: dict[str, Any]) -> Optional[int]:
    raw = payload.get("page")
    if raw in (None, ""):
        raw = payload.get("page_number")
    try:
        value = int(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _content(payload: dict[str, Any]) -> str:
    return str(payload.get("content") or payload.get("text") or "").strip()


def _normalize(text: str) -> str:
    folded = unicodedata.normalize("NFKC", text or "").casefold()
    return re.sub(r"\s+", " ", folded).strip()


async def _document_payloads(vector_db: Any, document_id: str, chunk_index: Optional[int]) -> list[dict[str, Any]]:
    """The document's chunks in reading order (only its neighbours when we can)."""
    rows: list[dict[str, Any]] = []
    if chunk_index is not None:
        wanted = [index for index in (chunk_index - 1, chunk_index, chunk_index + 1) if index >= 0]
        rows = await vector_db.list_payloads(
            filters={"document_id": document_id, "chunk_index": wanted},
            limit=8,
        )
        if not any(_chunk_index(row) == chunk_index for row in rows):
            rows = []
    if not rows:
        rows = await vector_db.list_payloads(filters={"document_id": document_id}, limit=SCAN_LIMIT)
    rows = [dict(row) for row in rows if str(row.get("document_id") or document_id) == str(document_id)]
    return sorted(rows, key=lambda row: (_chunk_index(row) is None, _chunk_index(row) or 0))


def _locate(
    payloads: list[dict[str, Any]],
    *,
    chunk_index: Optional[int],
    page: Optional[int],
    hint: Optional[str],
) -> Optional[int]:
    """Index of the cited chunk: by its index, else by the text the answer quoted."""
    if chunk_index is not None:
        for position, row in enumerate(payloads):
            if _chunk_index(row) == chunk_index:
                return position
    needle = _normalize(hint or "")[:160]
    if len(needle) < MIN_OVERLAP:
        return None
    same_page = [i for i, row in enumerate(payloads) if page is None or _page(row) in (None, page)]
    others = [i for i in range(len(payloads)) if i not in same_page]
    for position in same_page + others:
        if needle in _normalize(_content(payloads[position])):
            return position
    return None


def _overlap(left: str, right: str) -> int:
    """Length of the longest suffix of ``left`` that starts ``right`` (chunk overlap)."""
    upper = min(len(left), len(right), MAX_OVERLAP)
    for size in range(upper, MIN_OVERLAP - 1, -1):
        if left.endswith(right[:size]):
            return size
    return 0


def _tail(text: str) -> str:
    if len(text) <= CONTEXT_CHARS:
        return text.strip()
    cut = text[-CONTEXT_CHARS:]
    space = cut.find(" ")
    return (cut[space + 1 :] if 0 <= space < 40 else cut).strip()


def _head(text: str) -> str:
    if len(text) <= CONTEXT_CHARS:
        return text.strip()
    cut = text[:CONTEXT_CHARS]
    space = cut.rfind(" ")
    return (cut[:space] if space > CONTEXT_CHARS - 40 else cut).strip()


def _neighbours(payloads: list[dict[str, Any]], position: int) -> tuple[Optional[str], Optional[str]]:
    """A little text on each side, only from the chunks really next to it."""
    current = payloads[position]
    index = _chunk_index(current)
    text = _content(current)
    if index is None:
        return None, None
    before = after = None
    if position > 0 and _chunk_index(payloads[position - 1]) == index - 1:
        previous = _content(payloads[position - 1])
        previous = previous[: len(previous) - _overlap(previous, text)]
        before = _tail(previous) or None
    if position + 1 < len(payloads) and _chunk_index(payloads[position + 1]) == index + 1:
        following = _content(payloads[position + 1])
        following = following[_overlap(text, following) :]
        after = _head(following) or None
    return before, after


@router.get("/{document_id}/passage")
async def read_cited_passage(
    document_id: str,
    collection_name: str = Query(..., min_length=1, max_length=255),
    chunk_index: Optional[int] = Query(None, ge=0),
    page: Optional[int] = Query(None, ge=1),
    hint: Optional[str] = Query(None, max_length=400, description="Start of the passage the answer cited."),
    db: DBSession = Depends(get_db),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
):
    """The cited passage in full, its neighbours and the document it comes from."""
    collection = readable_collection(db, workspace=workspace, user=user, collection_ref=collection_name)
    doc_service = documents_api.DocumentService(
        collection_name=collection_name,
        vector_db_type=documents_api._resolve_document_vector_db_type(workspace),
        workspace_slug=workspace.slug,
    )
    filename = await documents_api._document_filename_for_id(
        db, workspace, collection_name, document_id, doc_service
    )
    if filename is None:
        raise HTTPException(status_code=404, detail="Document not found")

    passage: Optional[dict[str, Any]] = None
    before = after = None
    try:
        payloads = await _document_payloads(doc_service.vector_db, document_id, chunk_index)
        position = _locate(payloads, chunk_index=chunk_index, page=page, hint=hint)
        if position is not None:
            row = payloads[position]
            text = _content(row)
            passage = {
                "text": text[:PASSAGE_MAX_CHARS],
                "truncated": len(text) > PASSAGE_MAX_CHARS,
                "chunk_index": _chunk_index(row),
                "page": _page(row),
            }
            before, after = _neighbours(payloads, position)
    except Exception as exc:  # noqa: BLE001 - the panel falls back to the streamed passage.
        logger.warning("Cited passage lookup failed", document_id=document_id, error=str(exc))

    preview_available = False
    if filename:
        exists, _size = documents_api._resolve_original_meta(db, workspace, collection_name, document_id, filename)
        preview_available = bool(exists)

    return {
        "document_id": document_id,
        "filename": filename or None,
        "collection": {
            "id": collection.id if collection else None,
            "slug": collection.slug if collection else collection_name,
            "name": collection.name if collection else None,
        },
        "passage": passage,
        "before": before,
        "after": after,
        "preview_available": preview_available,
    }
