"""Optional integration tests against a live Qdrant instance (e.g. docker-compose qdrant)."""

from __future__ import annotations

import os
import socket
import uuid

import numpy as np
import pytest

pytestmark = pytest.mark.integration


def _qdrant_host() -> str:
    return os.getenv("QDRANT_HOST", "localhost")


def _qdrant_port() -> int:
    return int(os.getenv("QDRANT_PORT", "6333"))


def _qdrant_reachable() -> bool:
    if os.getenv("QDRANT_INTEGRATION") == "0":
        return False
    try:
        with socket.create_connection((_qdrant_host(), _qdrant_port()), timeout=0.75):
            return True
    except OSError:
        return False


@pytest.fixture
def require_qdrant():
    if not _qdrant_reachable():
        pytest.skip(
            f"Qdrant not reachable at {_qdrant_host()}:{_qdrant_port()} "
            "(start docker compose qdrant or set QDRANT_HOST / QDRANT_PORT)"
        )


@pytest.mark.asyncio
async def test_qdrant_lifecycle(require_qdrant):
    pytest.importorskip("qdrant_client")
    from qdrant_client import QdrantClient

    collection = f"itest_agentium_{uuid.uuid4().hex[:12]}"
    client = QdrantClient(
        host=_qdrant_host(),
        port=_qdrant_port(),
        api_key=os.getenv("QDRANT_API_KEY") or None,
        https=os.getenv("QDRANT_HTTPS", "").lower() in ("1", "true", "yes"),
    )

    from app.services.vector_db.qdrant_db import QdrantVectorDB

    db = QdrantVectorDB(collection_name=collection, client=client)
    try:
        await db.create_index(dimension=4)
        vecs = np.array([[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0]], dtype=np.float32)
        meta = [
            {"content": "alpha", "document_id": "doc1", "document_filename": "a.txt"},
            {"content": "beta", "document_id": "doc1", "document_filename": "b.txt"},
        ]
        ids = ["chunk-1", "chunk-2"]
        await db.add_vectors(vecs, meta, ids)
        assert await db.get_count() == 2
        q = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
        hits = await db.search(q, top_k=5)
        assert len(hits) >= 1
        assert hits[0]["id"] in ids
        listed = await db.list_documents()
        assert len(listed) == 1
        assert listed[0]["document_id"] == "doc1"
        mets = db.get_metadatas_for_chunk_ids(["chunk-1"])
        assert len(mets) == 1
        assert mets[0].get("content") == "alpha"
        await db.delete(["chunk-1"])
        assert await db.get_count() == 1
    finally:
        await db.clear_collection()
        if client.collection_exists(collection):
            client.delete_collection(collection_name=collection)
