"""Persist BM25 sidecar artifacts for worker-built collections."""
from __future__ import annotations

import pickle
from datetime import datetime
from io import BytesIO
from typing import Any

from app.core.config import settings
from app.models.knowledge_collection import KnowledgeCollection
from app.services.object_store import ObjectStore, get_object_store
from app.services.retrieval.bm25_retriever import BM25Retriever

BM25_ARTIFACT_FORMAT_VERSION = 1


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
    if settings.bm25_rebuild_max_chunks > 0 and count > settings.bm25_rebuild_max_chunks:
        return {
            "status": "skipped",
            "reason": "collection_too_large",
            "chunk_count": count,
            "max_chunks": settings.bm25_rebuild_max_chunks,
            "forced": force,
        }
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
    pickle.dump(
        {
            "format_version": BM25_ARTIFACT_FORMAT_VERSION,
            "built_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "collection_id": collection.id,
            "chunk_count": count,
            "documents_indexed": len(texts),
            "retriever": retriever,
        },
        buf,
    )

    key = bm25_artifact_key(collection, store=store)
    store.write_bytes(key, buf.getvalue())
    return {
        "status": "ready",
        "path": key,
        "chunk_count": count,
        "documents_indexed": len(texts),
        "forced": force,
    }


def load_bm25_artifact(
    collection: KnowledgeCollection,
    *,
    store: ObjectStore | None = None,
    current_chunk_count: int | None = None,
) -> tuple[BM25Retriever | None, dict]:
    """Load the BM25 sidecar, tolerating the legacy bare-retriever format.

    Returns ``(retriever, info)``; ``info["status"]`` is one of
    missing | ready | legacy | stale | error. ``stale`` means the envelope's
    chunk_count no longer matches the vector store (sparse results would be
    incomplete) — callers should enqueue a ``bm25`` rebuild job.
    """
    store = store or get_object_store()
    key = bm25_artifact_key(collection, store=store)
    if not store.exists(key):
        return None, {"status": "missing", "path": key}
    try:
        payload = pickle.loads(store.read_bytes(key))
    except Exception as exc:  # noqa: BLE001
        return None, {"status": "error", "path": key, "error": str(exc)}
    if isinstance(payload, BM25Retriever):
        return payload, {"status": "legacy", "path": key, "format_version": 0}
    if not isinstance(payload, dict) or not isinstance(payload.get("retriever"), BM25Retriever):
        return None, {"status": "error", "path": key, "error": "unrecognised_artifact_format"}
    info = {
        "status": "ready",
        "path": key,
        "format_version": payload.get("format_version"),
        "built_at": payload.get("built_at"),
        "chunk_count": payload.get("chunk_count"),
        "documents_indexed": payload.get("documents_indexed"),
    }
    if (
        current_chunk_count is not None
        and isinstance(payload.get("chunk_count"), int)
        and payload["chunk_count"] != current_chunk_count
    ):
        info["status"] = "stale"
        info["current_chunk_count"] = current_chunk_count
    return payload["retriever"], info


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
