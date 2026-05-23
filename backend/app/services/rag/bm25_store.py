"""Persist BM25 sidecar artifacts for worker-built collections."""
from __future__ import annotations

import pickle
from io import BytesIO
from typing import Any

from app.core.config import settings
from app.models.knowledge_collection import KnowledgeCollection
from app.services.object_store import ObjectStore, get_object_store
from app.services.retrieval.bm25_retriever import BM25Retriever


async def rebuild_bm25_artifact(
    *,
    collection: KnowledgeCollection,
    vector_db: Any,
    store: ObjectStore | None = None,
    force: bool = False,
) -> dict:
    """Build and persist a BM25 artifact from the vector DB payloads.

    Qdrant remains authoritative for chunks. This sidecar is intentionally
    optional: when collections are large, rebuilding BM25 synchronously would
    dominate ingestion time, so callers can enqueue a separate bm25 job later.
    """
    store = store or get_object_store()
    count = await vector_db.get_count()
    if count <= 0:
        return {"status": "skipped", "reason": "empty_collection", "chunk_count": 0}
    if count > settings.bm25_rebuild_inline_max_chunks and not force:
        return {
            "status": "deferred",
            "reason": "collection_too_large",
            "chunk_count": count,
            "threshold": settings.bm25_rebuild_inline_max_chunks,
        }

    chunk_ids = await vector_db.get_all_ids()
    if hasattr(vector_db, "get_metadatas_for_chunk_ids"):
        metadatas = vector_db.get_metadatas_for_chunk_ids(chunk_ids)
    elif hasattr(vector_db, "metadatas"):
        metadatas = [vector_db.metadatas.get(cid, {}) for cid in chunk_ids]
    else:
        metadatas = []

    texts: list[str] = []
    ids: list[str] = []
    clean_metas: list[dict] = []
    for cid, meta in zip(chunk_ids, metadatas):
        content = (meta or {}).get("content")
        if content:
            ids.append(str(cid))
            texts.append(str(content))
            clean_metas.append(dict(meta or {}))

    if not texts:
        return {"status": "skipped", "reason": "no_payload_content", "chunk_count": count}

    retriever = BM25Retriever()
    retriever.fit(texts, ids, clean_metas)
    buf = BytesIO()
    pickle.dump(retriever, buf)

    key = bm25_artifact_key(collection, store=store)
    store.write_bytes(key, buf.getvalue())
    return {
        "status": "ready",
        "path": key,
        "chunk_count": count,
        "documents_indexed": len(texts),
        "forced": force,
    }


def bm25_artifact_key(
    collection: KnowledgeCollection,
    *,
    store: ObjectStore | None = None,
) -> str:
    """Return the canonical BM25 sidecar key for a collection."""
    return (store or get_object_store()).key(
        collection.artifact_prefix,
        "derived",
        "bm25_retriever.pkl",
    )
