"""Unit tests for QdrantVectorDB with a mocked Qdrant client."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest

from app.core.config import settings
from app.services.vector_db.qdrant_db import QdrantVectorDB, _PAYLOAD_INDEX_FIELDS


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
    indexed_fields = {call.kwargs["field_name"] for call in client.create_payload_index.call_args_list}
    assert set(_PAYLOAD_INDEX_FIELDS) <= indexed_fields
    assert db._dimension == 4


@pytest.mark.asyncio
async def test_create_index_can_create_dense_sparse_named_vectors(monkeypatch):
    monkeypatch.setattr(settings, "rag_qdrant_sparse_enabled", True)
    client = MagicMock()
    client.collection_exists.return_value = False
    db = QdrantVectorDB(collection_name="my_col", client=client)

    await db.create_index(dimension=4)

    call_kw = client.create_collection.call_args.kwargs
    assert set(call_kw["vectors_config"].keys()) == {"dense"}
    assert set(call_kw["sparse_vectors_config"].keys()) == {"sparse"}


@pytest.mark.asyncio
async def test_create_index_skips_when_exists():
    client = MagicMock()
    client.collection_exists.return_value = True
    db = QdrantVectorDB(collection_name="my_col", client=client)
    await db.create_index(dimension=8)
    client.create_collection.assert_not_called()
    assert client.create_payload_index.call_count >= 1


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
async def test_add_vectors_upserts_sparse_named_vector_when_enabled(monkeypatch):
    monkeypatch.setattr(settings, "rag_qdrant_sparse_enabled", True)
    client = MagicMock()
    client.collection_exists.return_value = True
    db = QdrantVectorDB(collection_name="col", client=client)
    vectors = np.array([[1.0, 0.0]], dtype=np.float32)
    metadatas = [{"content": "Pump KD724 pump"}]

    await db.add_vectors(vectors, metadatas, ["id1"])

    point = client.upsert.call_args.kwargs["points"][0]
    assert set(point.vector.keys()) == {"dense", "sparse"}
    assert point.vector["dense"] == pytest.approx([1.0, 0.0])
    assert point.vector["sparse"].indices
    assert point.vector["sparse"].values


@pytest.mark.asyncio
async def test_add_vectors_batches_large_upserts(monkeypatch):
    monkeypatch.setattr(settings, "qdrant_upsert_batch_size", 2)
    client = MagicMock()
    client.collection_exists.return_value = True
    db = QdrantVectorDB(collection_name="col", client=client)
    vectors = np.ones((5, 2), dtype=np.float32)
    metadatas = [{"content": f"chunk {index}"} for index in range(5)]
    ids = [f"id{index}" for index in range(5)]

    await db.add_vectors(vectors, metadatas, ids)

    assert client.upsert.call_count == 3
    sizes = [len(call.kwargs["points"]) for call in client.upsert.call_args_list]
    assert sizes == [2, 2, 1]


@pytest.mark.asyncio
async def test_reindex_sparse_vectors_recreates_legacy_collection(monkeypatch):
    monkeypatch.setattr(settings, "rag_qdrant_sparse_enabled", True)
    client = MagicMock()
    client.collection_exists.return_value = True
    client.get_collection.return_value = SimpleNamespace(
        config=SimpleNamespace(params=SimpleNamespace(vectors=SimpleNamespace(size=2), sparse_vectors=None))
    )
    db = QdrantVectorDB(collection_name="col", client=client)
    record = SimpleNamespace(
        id="legacy-point",
        payload={"chunk_id": "chunk-a", "content": "Pump KD724 pump"},
        vector=[3.0, 4.0],
    )
    client.scroll.side_effect = [([record], None)]

    result = await db.reindex_sparse_vectors(batch_size=1)

    assert result["status"] == "ready"
    assert result["points_reindexed"] == 1
    assert result["recreated_collection"] is True
    client.delete_collection.assert_called_once_with(collection_name="col")
    client.create_collection.assert_called_once()
    point = client.upsert.call_args.kwargs["points"][0]
    assert point.id == db._point_id("chunk-a")
    assert set(point.vector.keys()) == {"dense", "sparse"}
    assert point.vector["dense"] == pytest.approx([0.6, 0.8], rel=1e-5)
    assert point.vector["sparse"].indices
    assert point.payload["chunk_id"] == "chunk-a"


@pytest.mark.asyncio
async def test_list_documents_aggregates_chunk_counts_in_one_scroll():
    client = MagicMock()
    client.collection_exists.return_value = True
    client.scroll.side_effect = [
        (
            [
                SimpleNamespace(payload={"document_id": "doc-a", "document_filename": "a.pdf", "document_type": "pdf"}),
                SimpleNamespace(payload={"document_id": "doc-a", "document_filename": "a.pdf", "document_type": "pdf"}),
                SimpleNamespace(payload={"document_id": "doc-b", "document_filename": "b.txt", "document_type": "text"}),
            ],
            None,
        )
    ]
    db = QdrantVectorDB(collection_name="col", client=client)

    docs = await db.list_documents()

    assert docs == [
        {"document_id": "doc-a", "filename": "a.pdf", "document_type": "pdf", "chunk_count": 2, "chunks_count": 2},
        {"document_id": "doc-b", "filename": "b.txt", "document_type": "text", "chunk_count": 1, "chunks_count": 1},
    ]
    client.scroll.assert_called_once()


@pytest.mark.asyncio
async def test_list_documents_keeps_duplicate_document_ids_with_distinct_filenames():
    client = MagicMock()
    client.collection_exists.return_value = True
    client.scroll.return_value = (
        [
            SimpleNamespace(payload={"document_id": "same-doc", "document_filename": "first.pdf", "document_type": "pdf"}),
            SimpleNamespace(payload={"document_id": "same-doc", "document_filename": "second.pdf", "document_type": "pdf"}),
        ],
        None,
    )
    db = QdrantVectorDB(collection_name="col", client=client)

    docs = await db.list_documents()

    assert [doc["filename"] for doc in docs] == ["first.pdf", "second.pdf"]
    assert [doc["chunk_count"] for doc in docs] == [1, 1]


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
async def test_search_sparse_queries_sparse_named_vector(monkeypatch):
    monkeypatch.setattr(settings, "rag_qdrant_sparse_enabled", True)
    client = MagicMock()
    client.collection_exists.return_value = True
    pid = QdrantVectorDB(collection_name="col", client=client)._point_id("chunk-a")
    hit = SimpleNamespace(
        id=pid,
        score=0.42,
        payload={"chunk_id": "chunk-a", "content": "Pump KD724", "document_id": "d1"},
    )
    client.query_points.return_value = SimpleNamespace(points=[hit])
    db = QdrantVectorDB(collection_name="col", client=client)

    out = await db.search_sparse("KD724 pump", top_k=3)

    assert out[0]["id"] == "chunk-a"
    assert out[0]["sparse_backend"] == "qdrant_sparse"
    call_kw = client.query_points.call_args.kwargs
    assert call_kw["using"] == "sparse"
    assert call_kw["limit"] == 3


@pytest.mark.asyncio
async def test_search_hybrid_uses_qdrant_prefetch_fusion(monkeypatch):
    monkeypatch.setattr(settings, "rag_qdrant_sparse_enabled", True)
    monkeypatch.setattr(settings, "rag_qdrant_hybrid_fusion", "dbsf")
    client = MagicMock()
    client.collection_exists.return_value = True
    pid = QdrantVectorDB(collection_name="col", client=client)._point_id("chunk-a")
    hit = SimpleNamespace(
        id=pid,
        score=0.73,
        payload={"chunk_id": "chunk-a", "content": "Pump KD724", "document_id": "d1"},
    )
    client.query_points.return_value = SimpleNamespace(points=[hit])
    db = QdrantVectorDB(collection_name="col", client=client)

    out = await db.search_hybrid(
        np.array([1.0, 0.0], dtype=np.float32),
        "KD724 pump",
        top_k=4,
        search_params={"retrieval_profile": "chat"},
    )

    assert out is not None
    assert out[0]["metadata"]["sparse_backend"] == "qdrant_sparse"
    assert out[0]["metadata"]["sparse_fusion"] == "server_dbsf"
    call_kw = client.query_points.call_args.kwargs
    assert len(call_kw["prefetch"]) == 2
    assert call_kw["prefetch"][0].using == "dense"
    assert call_kw["prefetch"][1].using == "sparse"
    assert call_kw["query"].fusion.value == "dbsf"
    assert call_kw["limit"] == 4


@pytest.mark.asyncio
async def test_search_applies_profile_search_params(monkeypatch):
    monkeypatch.setattr(settings, "rag_qdrant_chat_hnsw_ef", 77)
    client = MagicMock()
    client.collection_exists.return_value = True
    client.query_points.return_value = SimpleNamespace(points=[])
    db = QdrantVectorDB(collection_name="col", client=client)
    q = np.array([1.0, 0.0], dtype=np.float32)

    await db.search(q, top_k=5, search_params={"retrieval_profile": "chat"})

    params = client.query_points.call_args.kwargs["search_params"]
    assert params.hnsw_ef == 77
    assert params.quantization.rescore is True


@pytest.mark.asyncio
async def test_search_uses_full_precision_for_deep_profile(monkeypatch):
    monkeypatch.setattr(settings, "rag_qdrant_deep_hnsw_ef", 144)
    client = MagicMock()
    client.collection_exists.return_value = True
    client.query_points.return_value = SimpleNamespace(points=[])
    db = QdrantVectorDB(collection_name="col", client=client)
    q = np.array([1.0, 0.0], dtype=np.float32)

    await db.search(q, top_k=5, search_params={"retrieval_profile": "deep_async"})

    params = client.query_points.call_args.kwargs["search_params"]
    assert params.hnsw_ef == 144
    assert params.quantization.ignore is True


@pytest.mark.asyncio
async def test_filtered_search_lazily_ensures_payload_indexes_once():
    client = MagicMock()
    client.collection_exists.return_value = True
    client.query_points.return_value = SimpleNamespace(points=[])
    db = QdrantVectorDB(collection_name="col", client=client)
    q = np.array([1.0, 0.0], dtype=np.float32)

    await db.search(q, top_k=5, filters={"document_id": ["a", "b"]})
    first_count = client.create_payload_index.call_count
    await db.search(q, top_k=5, filters={"document_id": ["c"]})

    assert first_count >= len(_PAYLOAD_INDEX_FIELDS)
    assert client.create_payload_index.call_count == first_count


@pytest.mark.asyncio
async def test_search_empty_when_collection_missing():
    client = MagicMock()
    client.collection_exists.return_value = False
    db = QdrantVectorDB(collection_name="col", client=client)
    out = await db.search(np.array([1.0, 0.0]), top_k=3)
    assert out == []


def test_filters_to_qdrant_supports_match_any_lists():
    db = QdrantVectorDB(collection_name="col", client=MagicMock())
    qfilter = db._filters_to_qdrant({"document_id": ["a", "b"], "source_kind": "html"})

    assert qfilter is not None
    assert len(qfilter.must) == 2
    doc_condition = next(item for item in qfilter.must if item.key == "document_id")
    kind_condition = next(item for item in qfilter.must if item.key == "source_kind")
    assert list(doc_condition.match.any) == ["a", "b"]
    assert kind_condition.match.value == "html"


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


@pytest.mark.asyncio
async def test_get_by_document_id_ensures_payload_indexes():
    client = MagicMock()
    client.collection_exists.return_value = True
    client.scroll.return_value = (
        [
            SimpleNamespace(id="p1", payload={"chunk_id": "c1"}),
            SimpleNamespace(id="p2", payload={"chunk_id": "c2"}),
        ],
        None,
    )
    db = QdrantVectorDB(collection_name="col", client=client)

    ids = await db.get_by_document_id("doc-1")

    assert ids == ["c1", "c2"]
    indexed_fields = {call.kwargs["field_name"] for call in client.create_payload_index.call_args_list}
    assert "document_id" in indexed_fields


@pytest.mark.asyncio
async def test_get_document_metadata_ensures_payload_indexes():
    client = MagicMock()
    client.collection_exists.return_value = True
    client.scroll.return_value = (
        [SimpleNamespace(id="p1", payload={"document_id": "doc-1", "title": "Manual"})],
        None,
    )
    db = QdrantVectorDB(collection_name="col", client=client)

    metadata = await db.get_document_metadata("doc-1")

    assert metadata["title"] == "Manual"
    indexed_fields = {call.kwargs["field_name"] for call in client.create_payload_index.call_args_list}
    assert "document_id" in indexed_fields


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
