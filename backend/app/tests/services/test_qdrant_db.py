"""Unit tests for QdrantVectorDB with a mocked Qdrant client."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest

from app.services.vector_db.qdrant_db import QdrantVectorDB


def test_point_id_is_deterministic_per_collection():
    a = QdrantVectorDB(collection_name="c1", client=None)
    b = QdrantVectorDB(collection_name="c2", client=None)
    assert a._point_id("chunk-1") == a._point_id("chunk-1")
    assert a._point_id("chunk-1") != b._point_id("chunk-1")


@pytest.mark.asyncio
async def test_create_index_creates_when_missing():
    client = MagicMock()
    client.collection_exists.return_value = False
    db = QdrantVectorDB(collection_name="my_col", client=client)
    await db.create_index(dimension=4)
    client.collection_exists.assert_called_with("my_col")
    client.create_collection.assert_called_once()
    assert db._dimension == 4


@pytest.mark.asyncio
async def test_create_index_skips_when_exists():
    client = MagicMock()
    client.collection_exists.return_value = True
    db = QdrantVectorDB(collection_name="my_col", client=client)
    await db.create_index(dimension=8)
    client.create_collection.assert_not_called()


@pytest.mark.asyncio
async def test_add_vectors_upserts_normalized_points():
    client = MagicMock()
    client.collection_exists.return_value = True
    db = QdrantVectorDB(collection_name="col", client=client)
    vectors = np.array([[3.0, 4.0], [0.0, 2.0]], dtype=np.float32)
    metadatas = [{"content": "a", "document_id": "d1"}, {"content": "b"}]
    ids = ["id1", "id2"]
    await db.add_vectors(vectors, metadatas, ids)
    client.upsert.assert_called_once()
    call_kw = client.upsert.call_args.kwargs
    assert call_kw["collection_name"] == "col"
    assert call_kw["wait"] is True
    points = call_kw["points"]
    assert len(points) == 2
    # L2-normalized [3,4] -> [0.6, 0.8]
    assert points[0].vector == pytest.approx([0.6, 0.8], rel=1e-5)
    assert points[0].payload["chunk_id"] == "id1"
    assert points[0].payload["content"] == "a"


@pytest.mark.asyncio
async def test_search_returns_chunk_ids_and_clamps_score():
    client = MagicMock()
    client.collection_exists.return_value = True
    pid = QdrantVectorDB(collection_name="col", client=client)._point_id("chunk-a")
    hit = SimpleNamespace(
        id=pid,
        score=1.5,
        payload={"chunk_id": "chunk-a", "content": "hello", "document_id": "d1"},
    )
    client.query_points.return_value = SimpleNamespace(points=[hit])
    db = QdrantVectorDB(collection_name="col", client=client)
    q = np.array([1.0, 0.0], dtype=np.float32)
    out = await db.search(q, top_k=5)
    assert len(out) == 1
    assert out[0]["id"] == "chunk-a"
    assert out[0]["score"] == 1.0
    assert out[0]["content"] == "hello"
    assert "document_id" in out[0]["metadata"]


@pytest.mark.asyncio
async def test_search_empty_when_collection_missing():
    client = MagicMock()
    client.collection_exists.return_value = False
    db = QdrantVectorDB(collection_name="col", client=client)
    out = await db.search(np.array([1.0, 0.0]), top_k=3)
    assert out == []


@pytest.mark.asyncio
async def test_delete_maps_string_ids_to_point_uuids():
    client = MagicMock()
    db = QdrantVectorDB(collection_name="col", client=client)
    await db.delete(["x", "y"])
    from qdrant_client.models import PointIdsList

    client.delete.assert_called_once()
    kw = client.delete.call_args.kwargs
    assert kw["collection_name"] == "col"
    sel = kw["points_selector"]
    assert isinstance(sel, PointIdsList)
    assert len(sel.points) == 2
    assert sel.points[0] == db._point_id("x")


@pytest.mark.asyncio
async def test_get_count_delegates_to_client():
    client = MagicMock()
    client.collection_exists.return_value = True
    client.count.return_value = SimpleNamespace(count=42)
    db = QdrantVectorDB(collection_name="col", client=client)
    assert await db.get_count() == 42


@pytest.mark.asyncio
async def test_get_all_ids_scrolls_payload_chunk_ids():
    client = MagicMock()
    client.collection_exists.return_value = True
    r1 = SimpleNamespace(payload={"chunk_id": "c1"})
    r2 = SimpleNamespace(payload={"chunk_id": "c2"})
    client.scroll.side_effect = [([r1, r2], None)]
    db = QdrantVectorDB(collection_name="col", client=client)
    ids = await db.get_all_ids()
    assert ids == ["c1", "c2"]


def test_get_metadatas_for_chunk_ids_sync():
    client = MagicMock()
    rec = SimpleNamespace(payload={"document_id": "d", "content": "x"})
    client.retrieve.return_value = [rec]
    db = QdrantVectorDB(collection_name="col", client=client)
    out = db.get_metadatas_for_chunk_ids(["z"])
    assert out == [{"document_id": "d", "content": "x"}]
    client.retrieve.assert_called_once()


@pytest.mark.asyncio
async def test_clear_collection_deletes_when_exists():
    client = MagicMock()
    client.collection_exists.return_value = True
    db = QdrantVectorDB(collection_name="col", client=client)
    await db.clear_collection()
    client.delete_collection.assert_called_once_with("col")
