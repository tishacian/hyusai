"""Unit tests for QdrantVectorDB with a mocked Qdrant client."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest

from app.core.config import settings
from app.services.rag.lexical_retrieval import parse_lexical_config
from app.services.vector_db.qdrant_db import _PAYLOAD_INDEX_FIELDS, QdrantVectorDB


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
async def test_create_index_builds_content_full_text_index():
    client = MagicMock()
    client.collection_exists.return_value = False
    db = QdrantVectorDB(collection_name="my_col", client=client)
    await db.create_index(dimension=4)
    content_calls = [
        call for call in client.create_payload_index.call_args_list if call.kwargs.get("field_name") == "content"
    ]
    assert len(content_calls) == 1
    schema = content_calls[0].kwargs["field_schema"]
    # Phase 0 decided params: multilingual tokenizer, lowercase, on_disk, 2..30.
    assert str(getattr(schema.tokenizer, "value", schema.tokenizer)) == "multilingual"
    assert schema.lowercase is True
    assert schema.on_disk is True
    assert schema.min_token_len == 2
    assert schema.max_token_len == 30
    # Lazy ensure path must not block on the heavy build.
    assert content_calls[0].kwargs["wait"] is False
    # ``content`` is a separate text index, never added to the KEYWORD loop.
    assert "content" not in _PAYLOAD_INDEX_FIELDS


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
    metadatas = [{"content": "Pump KD724 pump", "document_filename": "KD724 manual.pdf", "project_code": "PRJ204"}]

    await db.add_vectors(vectors, metadatas, ["id1"])

    point = client.upsert.call_args.kwargs["points"][0]
    assert set(point.vector.keys()) == {"dense", "sparse"}
    assert point.vector["dense"] == pytest.approx([1.0, 0.0])
    assert point.vector["sparse"].indices
    assert point.vector["sparse"].values
    assert point.payload["sparse_schema_version"] == "metadata_v1"
    assert "prj204" in point.payload["retrieval_identifiers"]
    assert "kd724" in point.payload["retrieval_terms"]


@pytest.mark.asyncio
async def test_search_exact_metadata_uses_retrieval_identifier_payload_index(monkeypatch):
    monkeypatch.setattr(settings, "rag_qdrant_sparse_enabled", True)
    client = MagicMock()
    client.collection_exists.return_value = True
    db = QdrantVectorDB(collection_name="col", client=client)
    hit = SimpleNamespace(
        id="point-1",
        payload={
            "chunk_id": "chunk-1",
            "content": "Component list content",
            "document_id": "doc-1",
            "document_filename": "Component list PRJ204.pdf",
            "project_code": "PRJ204",
            "retrieval_identifiers": ["prj204"],
            "retrieval_terms": ["component", "list", "prj204"],
            "sparse_schema_version": "metadata_v1",
        },
    )
    client.scroll.return_value = ([hit], None)

    out = await db.search_exact_metadata("Find component list for PRJ204", top_k=5)

    assert out[0]["id"] == "chunk-1"
    assert out[0]["metadata"]["exact_metadata_match"] is True
    assert out[0]["metadata"]["retrieval_exact_terms_matched"] == ["PRJ204"]
    scroll_filter = client.scroll.call_args.kwargs["scroll_filter"]
    assert scroll_filter.must[0].key == "retrieval_identifiers"


@pytest.mark.asyncio
async def test_search_exact_metadata_requires_each_identifier_group(monkeypatch):
    monkeypatch.setattr(settings, "rag_qdrant_sparse_enabled", True)
    client = MagicMock()
    client.collection_exists.return_value = True
    db = QdrantVectorDB(collection_name="col", client=client)
    hit = SimpleNamespace(
        id="point-1",
        payload={
            "chunk_id": "chunk-1",
            "content": "AKK200 Filtering cartridge LM 300 spare part.",
            "document_id": "doc-1",
            "document_filename": "Spare Parts List AKK200.pdf",
            "retrieval_identifiers": ["akk200", "lm300"],
            "retrieval_terms": ["filtering", "cartridge", "spare", "part"],
            "sparse_schema_version": "metadata_v1",
        },
    )
    client.scroll.return_value = ([hit], None)

    out = await db.search_exact_metadata("AKK200 Filtering cartridge LM300", top_k=5)

    assert out[0]["id"] == "chunk-1"
    scroll_filter = client.scroll.call_args.kwargs["scroll_filter"]
    identifier_conditions = [condition for condition in scroll_filter.must if condition.key == "retrieval_identifiers"]
    assert len(identifier_conditions) == 2


@pytest.mark.asyncio
async def test_search_exact_metadata_combines_identifier_and_document_type_terms(monkeypatch):
    monkeypatch.setattr(settings, "rag_qdrant_sparse_enabled", True)
    client = MagicMock()
    client.collection_exists.return_value = True
    db = QdrantVectorDB(collection_name="col", client=client)
    hit = SimpleNamespace(
        id="point-1",
        payload={
            "chunk_id": "chunk-1",
            "content": "Spare parts list for PRJ204.",
            "document_id": "doc-1",
            "document_filename": "Spare Parts List PRJ204.pdf",
            "retrieval_identifiers": ["prj204"],
            "retrieval_terms": ["spare", "parts", "list", "prj204"],
            "sparse_schema_version": "metadata_v1",
        },
    )
    client.scroll.return_value = ([hit], None)

    config = parse_lexical_config({"document_types": {"parts_catalog": ["parts list"]}})
    out = await db.search_exact_metadata("Find parts list for PRJ-204", top_k=5, lexical_config=config)

    assert out[0]["id"] == "chunk-1"
    scroll_filter = client.scroll.call_args.kwargs["scroll_filter"]
    assert [condition.key for condition in scroll_filter.must] == ["retrieval_identifiers", "retrieval_terms"]


@pytest.mark.asyncio
async def test_parent_contexts_for_hits_expands_by_document_and_section():
    client = MagicMock()
    client.collection_exists.return_value = True
    db = QdrantVectorDB(collection_name="col", client=client)
    records = [
        SimpleNamespace(
            id="point-2",
            payload={
                "chunk_id": "chunk-2",
                "content": "Second parent paragraph about filtering cartridge.",
                "document_id": "doc-1",
                "document_filename": "Spare Parts List AKK200_Ind A.pdf",
                "section_path": "section IV",
                "chunk_index": 12,
            },
        ),
        SimpleNamespace(
            id="point-1",
            payload={
                "chunk_id": "chunk-1",
                "content": "First parent paragraph about AKK200 O-ring.",
                "document_id": "doc-1",
                "document_filename": "Spare Parts List AKK200_Ind A.pdf",
                "section_path": "section IV",
                "chunk_index": 11,
            },
        ),
    ]
    client.scroll.return_value = (records, None)

    out = await db.parent_contexts_for_hits(
        [
            {
                "document_id": "doc-1",
                "document_filename": "Spare Parts List AKK200_Ind A.pdf",
                "section_path": "section IV",
                "chunk_index": 12,
            }
        ],
        max_parents=1,
        max_chars=500,
    )

    assert len(out) == 1
    assert "First parent paragraph" in out[0]["content"]
    assert "Second parent paragraph" in out[0]["content"]
    assert out[0]["metadata"]["parent_context"] is True
    assert out[0]["metadata"]["parent_context_chunk_count"] == 2
    scroll_filter = client.scroll.call_args.kwargs["scroll_filter"]
    assert {condition.key for condition in scroll_filter.must} >= {"document_id", "section_path"}


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
async def test_reindex_sparse_vectors_streams_to_hybrid_alias(monkeypatch):
    monkeypatch.setattr(settings, "rag_qdrant_sparse_enabled", True)
    client = MagicMock()
    client.collection_exists.side_effect = lambda name: name == "col"
    client.get_collection.return_value = SimpleNamespace(
        config=SimpleNamespace(params=SimpleNamespace(vectors=SimpleNamespace(size=2), sparse_vectors=None))
    )
    client.count.return_value = SimpleNamespace(count=1)
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
    assert result["alias_cutover"] is True
    assert result["physical_collection"].startswith("col__hybrid_")
    client.delete_collection.assert_called_once_with(collection_name="col")
    client.create_collection.assert_called_once()
    client.update_collection_aliases.assert_called_once()
    point = client.upsert.call_args.kwargs["points"][0]
    assert point.id == "legacy-point"
    assert set(point.vector.keys()) == {"dense", "sparse"}
    assert point.vector["dense"] == pytest.approx([0.6, 0.8], rel=1e-5)
    assert point.vector["sparse"].indices
    assert point.payload["sparse_schema_version"] == "metadata_v1"
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
async def test_search_can_group_results_by_document_id():
    client = MagicMock()
    client.collection_exists.return_value = True
    client.query_points_groups.return_value = SimpleNamespace(
        groups=[
            SimpleNamespace(
                id="doc-a",
                hits=[
                    SimpleNamespace(
                        id="a1",
                        score=0.91,
                        payload={"chunk_id": "chunk-a1", "content": "doc A first", "document_id": "doc-a"},
                    ),
                    SimpleNamespace(
                        id="a2",
                        score=0.88,
                        payload={"chunk_id": "chunk-a2", "content": "doc A second", "document_id": "doc-a"},
                    ),
                ],
            ),
            SimpleNamespace(
                id="doc-b",
                hits=[
                    SimpleNamespace(
                        id="b1",
                        score=0.83,
                        payload={"chunk_id": "chunk-b1", "content": "doc B first", "document_id": "doc-b"},
                    )
                ],
            ),
        ]
    )
    db = QdrantVectorDB(collection_name="col", client=client)

    out = await db.search(
        np.array([1.0, 0.0], dtype=np.float32),
        top_k=3,
        search_params={"retrieval_profile": "chat", "group_by": "document_id", "group_size": 2},
    )

    assert [row["id"] for row in out] == ["chunk-a1", "chunk-b1", "chunk-a2"]
    assert out[0]["metadata"]["qdrant_group_by"] == "document_id"
    call_kw = client.query_points_groups.call_args.kwargs
    assert call_kw["group_by"] == "document_id"
    assert call_kw["group_size"] == 2
    client.query_points.assert_not_called()


@pytest.mark.asyncio
async def test_search_hybrid_can_group_server_fusion_results(monkeypatch):
    monkeypatch.setattr(settings, "rag_qdrant_sparse_enabled", True)
    client = MagicMock()
    client.collection_exists.return_value = True
    client.query_points_groups.return_value = SimpleNamespace(
        groups=[
            SimpleNamespace(
                id="doc-a",
                hits=[
                    SimpleNamespace(
                        id="a1",
                        score=0.74,
                        payload={"chunk_id": "chunk-a1", "content": "Pump KD724 A", "document_id": "doc-a"},
                    )
                ],
            )
        ]
    )
    db = QdrantVectorDB(collection_name="col", client=client)

    out = await db.search_hybrid(
        np.array([1.0, 0.0], dtype=np.float32),
        "KD724 pump",
        top_k=4,
        search_params={"retrieval_profile": "oracle_fast", "group_by": "document_id", "group_size": 1},
    )

    assert out is not None
    assert out[0]["metadata"]["sparse_backend"] == "qdrant_sparse"
    assert out[0]["metadata"]["qdrant_group_by"] == "document_id"
    call_kw = client.query_points_groups.call_args.kwargs
    assert len(call_kw["prefetch"]) == 2
    assert call_kw["group_by"] == "document_id"
    assert call_kw["group_size"] == 1


@pytest.mark.asyncio
async def test_search_hybrid_falls_back_to_ungrouped_query_when_grouping_fails(monkeypatch):
    monkeypatch.setattr(settings, "rag_qdrant_sparse_enabled", True)
    client = MagicMock()
    client.collection_exists.return_value = True
    client.query_points_groups.side_effect = RuntimeError("group payload index unavailable")
    client.query_points.return_value = SimpleNamespace(
        points=[
            SimpleNamespace(
                id="a1",
                score=0.74,
                payload={"chunk_id": "chunk-a1", "content": "Pump KD724 A", "document_id": "doc-a"},
            )
        ]
    )
    db = QdrantVectorDB(collection_name="col", client=client)

    out = await db.search_hybrid(
        np.array([1.0, 0.0], dtype=np.float32),
        "KD724 pump",
        top_k=4,
        search_params={"retrieval_profile": "oracle_fast", "group_by": "document_id", "group_size": 1},
    )

    assert out is not None
    assert out[0]["metadata"]["sparse_backend"] == "qdrant_sparse"
    assert "qdrant_group_by" not in out[0]["metadata"]
    client.query_points_groups.assert_called_once()
    client.query_points.assert_called_once()


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


@pytest.mark.asyncio
async def test_inventory_evidence_is_project_scoped_source_diverse_and_spare_first(
    monkeypatch,
):
    monkeypatch.setattr(settings, "rag_qdrant_sparse_enabled", False)
    client = MagicMock()
    client.collection_exists.return_value = True
    content_rows = [
        SimpleNamespace(
            id="manual-a-1",
            payload={
                "chunk_id": "manual-a-1",
                "content": "Centrifugal pump model MIX-900 service manual.",
                "document_id": "manual-a",
                "document_filename": "MIX-900 manual.pdf",
                "project_code": "PRJ204",
                "source_family": "unknown",
            },
        ),
        SimpleNamespace(
            id="manual-a-2",
            payload={
                "chunk_id": "manual-a-2",
                "content": "Pump MIX-900 installation and operation.",
                "document_id": "manual-a",
                "document_filename": "MIX-900 manual.pdf",
                "project_code": "PRJ204",
                "source_family": "unknown",
            },
        ),
        SimpleNamespace(
            id="manual-b-1",
            payload={
                "chunk_id": "manual-b-1",
                "content": "Pompe verticale model VTX-4.",
                "document_id": "manual-b",
                "document_filename": "VTX-4.pdf",
                "project_code": "PRJ204",
                "source_family": "supplier_manual",
            },
        ),
        SimpleNamespace(
            id="wrong-project",
            payload={
                "chunk_id": "wrong-project",
                "content": "Pump model SHOULD-NOT-LEAK service manual.",
                "document_id": "other-project-manual",
                "document_filename": "OTHER999 pump manual.pdf",
                "project_code": "OTHER999",
                "source_family": "supplier_manual",
            },
        ),
    ]
    spare_rows = [
        SimpleNamespace(
            id="spare-4",
            payload={
                "chunk_id": "spare-4",
                "content": "Complete pump motor location: P-101, P-102 and PF-3.",
                "document_id": "spare-list",
                "document_filename": "Spare Parts List PRJ204.pdf",
                "project_code": "PRJ204",
                "source_family": "spare_parts_list",
            },
        )
    ]
    client.scroll.side_effect = [(content_rows, None), (spare_rows, None)]
    db = QdrantVectorDB(collection_name="col", client=client)

    rows = await db.search_inventory_evidence(
        project_code="PRJ204",
        content_terms=["pompe", "pump"],
        limit=3,
    )

    assert len(rows) == 3
    assert rows[0]["metadata"]["source_family"] == "spare_parts_list"
    assert {row["metadata"]["document_id"] for row in rows} == {
        "spare-list",
        "manual-a",
        "manual-b",
    }
    assert all(row["metadata"]["inventory_match_terms"] for row in rows)
    assert all(
        row["metadata"]["inventory_evidence_backend"] == "qdrant_payload_fulltext"
        for row in rows
    )

    assert client.scroll.call_count == 2
    content_filter = client.scroll.call_args_list[0].kwargs["scroll_filter"]
    spare_filter = client.scroll.call_args_list[1].kwargs["scroll_filter"]
    assert content_filter.must[0].key == "project_code"
    assert content_filter.must[0].match.value == "PRJ204"
    assert content_filter.min_should.min_count == 1
    assert {condition.key for condition in content_filter.min_should.conditions} == {"content"}
    assert [condition.key for condition in spare_filter.must] == [
        "project_code",
        "source_family",
    ]
    assert spare_filter.must[1].match.value == "spare_parts_list"


@pytest.mark.asyncio
async def test_inventory_evidence_uses_grouped_sparse_and_keeps_two_complementary_spare_chunks(
    monkeypatch,
):
    monkeypatch.setattr(settings, "rag_qdrant_sparse_enabled", True)
    client = MagicMock()
    client.collection_exists.return_value = True
    manual_a = SimpleNamespace(
        id="manual-a",
        score=0.8,
        payload={
            "chunk_id": "manual-a",
            "content": "Centrifugal pump model MIX-900 service manual.",
            "document_id": "manual-a-doc",
            "document_filename": "MIX-900 manual.pdf",
            "inner_document_path": "PRJ204/files/section_7/mixing/MIX-900/FR/manual.pdf",
            "project_code": "PRJ204",
            "source_family": "supplier_manual",
        },
    )
    manual_b = SimpleNamespace(
        id="manual-b",
        score=0.7,
        payload={
            "chunk_id": "manual-b",
            "content": "Vertical pump model VTX-4 operating manual.",
            "document_id": "manual-b-doc",
            "document_filename": "VTX-4 manual.pdf",
            "inner_document_path": "PRJ204/files/section_7/vertical/VTX-4/FR/manual.pdf",
            "project_code": "PRJ204",
            "source_family": "supplier_manual",
        },
    )
    manual_a_translation = SimpleNamespace(
        id="manual-a-es",
        score=0.6,
        payload={
            "chunk_id": "manual-a-es",
            "content": "Pump model MIX-900 translated service manual.",
            "document_id": "manual-a-es-doc",
            "document_filename": "MIX-900 ES manual.pdf",
            "inner_document_path": "PRJ204-ES/files/section_7/mixing/MIX-900/ES/manual.pdf",
            "project_code": "PRJ204",
            "source_family": "supplier_manual",
        },
    )
    spare_a = SimpleNamespace(
        id="spare-a",
        score=0.95,
        payload={
            "chunk_id": "spare-a",
            "content": "Complete pump P-101 and pump P-102.",
            "document_id": "spare-doc",
            "document_filename": "Spare Parts List PRJ204.pdf",
            "project_code": "PRJ204",
            "source_family": "spare_parts_list",
        },
    )
    spare_b = SimpleNamespace(
        id="spare-b",
        score=0.9,
        payload={
            "chunk_id": "spare-b",
            "content": "Process pump PF-3 and pump PP-4 locations.",
            "document_id": "spare-doc",
            "document_filename": "Spare Parts List PRJ204.pdf",
            "project_code": "PRJ204",
            "source_family": "spare_parts_list",
        },
    )
    client.query_points_groups.return_value = SimpleNamespace(
        groups=[
            SimpleNamespace(hits=[manual_a]),
            SimpleNamespace(hits=[manual_a_translation]),
            SimpleNamespace(hits=[manual_b]),
        ]
    )
    client.query_points.return_value = SimpleNamespace(points=[spare_a, spare_b])
    db = QdrantVectorDB(collection_name="col", client=client)

    rows = await db.search_inventory_evidence(
        project_code="PRJ204",
        content_terms=["pump"],
        limit=4,
    )

    assert [row["id"] for row in rows[:2]] == ["spare-a", "spare-b"]
    assert {row["metadata"]["document_id"] for row in rows[2:]} == {
        "manual-a-doc",
        "manual-b-doc",
    }
    assert all(row["metadata"]["inventory_sparse_score"] > 0 for row in rows)
    grouped_kwargs = client.query_points_groups.call_args.kwargs
    assert grouped_kwargs["group_by"] == "document_id"
    assert grouped_kwargs["group_size"] == 1
    assert grouped_kwargs["using"] == "sparse"
    assert grouped_kwargs["timeout"] == 1
    client.collection_exists.assert_not_called()
    client.scroll.assert_not_called()


@pytest.mark.asyncio
async def test_inventory_evidence_reserves_unattested_family_within_category(
    monkeypatch,
):
    monkeypatch.setattr(settings, "rag_qdrant_sparse_enabled", True)
    client = MagicMock()
    client.collection_exists.return_value = True

    def manual(
        chunk_id: str,
        model: str,
        category: str,
        score: float,
    ) -> SimpleNamespace:
        return SimpleNamespace(
            id=chunk_id,
            score=score,
            payload={
                "chunk_id": chunk_id,
                "content": f"Pump {model} operating and service manual.",
                "document_id": f"{chunk_id}-doc",
                "document_filename": f"{model} manual.pdf",
                "inner_document_path": (
                    f"PRJ204/files/section_7/{category}/{model}/FR/manual.pdf"
                ),
                "project_code": "PRJ204",
                "source_family": "supplier_manual",
            },
        )

    attested_a = manual("attested-a", "AX-10", "high-pressure", 0.9)
    attested_b = manual("attested-b", "AX10-20", "high-pressure", 0.85)
    novel_family = manual("novel", "ZX-900", "high-pressure", 0.4)
    filter_a = manual("filter-a", "FL-1", "filtration", 0.8)
    cooling = manual("cooling", "CL-7", "cooling", 0.75)
    drainage = manual("drainage", "DR-5", "drainage", 0.7)
    spare = SimpleNamespace(
        id="spare",
        score=0.95,
        payload={
            "chunk_id": "spare",
            "content": "HP pumps: complete pump AX 10 and complete pump AX 20.",
            "document_id": "spare-doc",
            "document_filename": "Spare Parts List PRJ204.pdf",
            "project_code": "PRJ204",
            "source_family": "spare_parts_list",
        },
    )
    client.query_points_groups.return_value = SimpleNamespace(
        groups=[
            SimpleNamespace(hits=[row])
            for row in [
                attested_a,
                attested_b,
                filter_a,
                cooling,
                drainage,
                novel_family,
            ]
        ]
    )
    client.query_points.return_value = SimpleNamespace(points=[spare])
    db = QdrantVectorDB(collection_name="col", client=client)

    rows = await db.search_inventory_evidence(
        project_code="PRJ204",
        content_terms=["pump"],
        limit=5,
    )

    assert [row["id"] for row in rows] == [
        "spare",
        "attested-a",
        "filter-a",
        "novel",
        "attested-b",
    ]
    assert "cooling" not in {row["id"] for row in rows}
    assert "drainage" not in {row["id"] for row in rows}
    by_id = {row["id"]: row["metadata"] for row in rows}
    assert by_id["attested-a"]["inventory_equipment_family"] == "ax-10"
    assert by_id["attested-a"]["inventory_functional_category"] == "high-pressure"
    assert by_id["attested-a"]["inventory_family_attested_by_spare"] is True
    assert by_id["attested-a"]["inventory_category_has_spare_attested_family"] is True
    assert by_id["novel"]["inventory_equipment_family"] == "zx-900"
    assert by_id["novel"]["inventory_functional_category"] == "high-pressure"
    assert by_id["novel"]["inventory_family_attested_by_spare"] is False
    assert by_id["novel"]["inventory_category_has_spare_attested_family"] is True

    # If the only unattested family was already admitted by the primary pass,
    # the final fallback must reclaim the reserved slot for the next candidate.
    client.query_points_groups.return_value = SimpleNamespace(
        groups=[
            SimpleNamespace(hits=[row])
            for row in [attested_a, attested_b, filter_a]
        ]
    )
    fallback_rows = await db.search_inventory_evidence(
        project_code="PRJ204",
        content_terms=["pump"],
        limit=4,
    )
    assert [row["id"] for row in fallback_rows] == [
        "spare",
        "attested-a",
        "filter-a",
        "attested-b",
    ]


@pytest.mark.asyncio
async def test_inventory_evidence_fails_soft_when_fulltext_indexes_are_unavailable(
    monkeypatch,
):
    monkeypatch.setattr(settings, "rag_qdrant_sparse_enabled", False)
    client = MagicMock()
    client.collection_exists.return_value = True
    client.scroll.side_effect = RuntimeError("full-text index unavailable")
    db = QdrantVectorDB(collection_name="col", client=client)

    rows = await db.search_inventory_evidence(
        project_code="PRJ204",
        content_terms=["pump"],
    )

    assert rows == []


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
