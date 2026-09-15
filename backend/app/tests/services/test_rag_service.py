"""Tests for RAG service"""

import os
import tempfile

import numpy as np
import pytest

from app.services.rag.document_service import DocumentService, _document_extra_metadata
from app.services.retrieval.bm25_retriever import BM25Retriever
from app.services.vector_db.factory import VectorDBFactory
from app.services.vector_db.faiss_db import FAISSVectorDB


class FakeVectorDB:
    def __init__(self):
        self.dimension = 0
        self.vectors = {}
        self.metadatas = {}

    async def create_index(self, dimension: int):
        self.dimension = dimension

    async def add_vectors(self, embeddings, metadatas, ids):
        for embedding, metadata, chunk_id in zip(embeddings, metadatas, ids):
            self.vectors[chunk_id] = np.array(embedding)
            self.metadatas[chunk_id] = dict(metadata)

    async def delete(self, ids):
        for chunk_id in ids:
            self.vectors.pop(chunk_id, None)
            self.metadatas.pop(chunk_id, None)

    async def delete_by_metadata(self, filters=None):
        matching = [
            chunk_id
            for chunk_id, metadata in self.metadatas.items()
            if all(metadata.get(key) == value for key, value in (filters or {}).items())
        ]
        await self.delete(matching)
        return True

    async def list_payloads(self, filters=None, limit=100, offset=0):
        payloads = [
            {**metadata, "chunk_id": chunk_id}
            for chunk_id, metadata in self.metadatas.items()
            if all(metadata.get(key) == value for key, value in (filters or {}).items())
        ]
        return payloads[offset : offset + limit]

    async def search(self, query_embedding, top_k: int = 10, filters=None):
        query = np.array(query_embedding)
        ranked = []
        for chunk_id, vector in self.vectors.items():
            score = float(np.dot(query, vector))
            metadata = self.metadatas[chunk_id]
            ranked.append(
                {
                    "id": chunk_id,
                    "score": score,
                    "content": metadata.get("content", ""),
                    "metadata": metadata,
                }
            )
        return sorted(ranked, key=lambda item: item["score"], reverse=True)[:top_k]

    async def get_all_ids(self):
        return list(self.vectors.keys())


@pytest.fixture
def fake_vector_db(monkeypatch):
    vector_db = FakeVectorDB()
    monkeypatch.setattr(
        VectorDBFactory,
        "get_db",
        classmethod(lambda cls, *args, **kwargs: vector_db),
    )
    return vector_db


@pytest.fixture
def sample_text_file():
    """Create a sample text file for testing"""
    content = """Machine learning is a subset of artificial intelligence.
It involves training algorithms on data to make predictions.
Deep learning uses neural networks with multiple layers.
Natural language processing helps computers understand human language."""

    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write(content)
        temp_path = f.name

    yield temp_path

    # Cleanup
    if os.path.exists(temp_path):
        os.unlink(temp_path)


def test_document_extra_metadata_adds_scope_fields_and_merges_manifest():
    metadata = _document_extra_metadata(
        "/tmp/A__ACJ100__manual.html",
        "A__ACJ100__manual.html",
        {
            "collection_slug": "andritz-spl",
            "document_metadata_by_name": {
                "A__ACJ100__manual.html": {
                    "project_code": "ACJ100",
                    "archive_name": "A",
                    "source_kind": "manual_override",
                }
            },
            "document_metadata": {
                "project_code": "ACJ100-DIRECT",
            },
        },
    )

    assert metadata["collection_slug"] == "andritz-spl"
    assert metadata["collection"] == "andritz-spl"
    assert metadata["document_filename"] == "A__ACJ100__manual.html"
    assert metadata["extension"] == "html"
    assert metadata["status"] == "ready"
    assert metadata["archive_name"] == "A"
    assert metadata["source_kind"] == "manual_override"
    assert metadata["project_code"] == "ACJ100-DIRECT"


@pytest.mark.asyncio
async def test_document_ingestion(sample_text_file, fake_vector_db):
    """Test document ingestion"""
    service = DocumentService(collection_name="test_collection")
    assert service.vector_db_type == "qdrant"
    result = await service.ingest_document(sample_text_file)

    assert result["status"] == "success"
    assert "document_id" in result
    assert result["chunks_processed"] > 0


@pytest.mark.asyncio
async def test_document_search(sample_text_file, fake_vector_db):
    """Test document search"""
    service = DocumentService(collection_name="test_collection")
    assert service.vector_db_type == "qdrant"

    # First ingest document
    await service.ingest_document(sample_text_file)

    # Then search
    results = await service.search("machine learning", top_k=5)

    assert len(results) > 0
    assert "id" in results[0]
    assert "score" in results[0]
    assert "metadata" in results[0]


@pytest.mark.asyncio
async def test_reupload_same_filename_replaces_old_chunks_and_keeps_stable_id(
    tmp_path, fake_vector_db
):
    first_dir = tmp_path / "upload-one"
    second_dir = tmp_path / "upload-two"
    first_dir.mkdir()
    second_dir.mkdir()
    first_path = first_dir / "company-policy.md"
    second_path = second_dir / "company-policy.md"
    first_path.write_text("Employees receive 25 paid working days.")
    second_path.write_text("Employees receive 27 paid working days.")

    service = DocumentService(
        collection_name="documents",
        vector_db_type="faiss",
        workspace_slug="personal-test",
        use_cache=True,
        use_hybrid=False,
        use_reranker=False,
    )
    first = await service.ingest_document(str(first_path))
    service.cache.set(
        "annual leave",
        5,
        [{"content": "25 paid working days"}],
        namespace=service.cache_namespace,
    )
    second = await service.ingest_document(str(second_path))

    assert first["status"] == "success"
    assert second["status"] == "success"
    assert first["document_id"] == second["document_id"]
    assert len(fake_vector_db.metadatas) == second["chunks_processed"]
    indexed_content = "\n".join(
        metadata["content"] for metadata in fake_vector_db.metadatas.values()
    )
    assert "27 paid working days" in indexed_content
    assert "25 paid working days" not in indexed_content
    assert (
        service.cache.get(
            "annual leave",
            5,
            namespace=service.cache_namespace,
        )
        is None
    )


@pytest.mark.asyncio
async def test_faiss_filtered_delete_rebuilds_index_without_duplicate_vectors(tmp_path):
    vector_db = FAISSVectorDB(
        persist_directory=str(tmp_path),
        collection_name="replacement-test",
    )
    await vector_db.create_index(2)
    await vector_db.add_vectors(
        np.array([[1.0, 0.0], [0.9, 0.1], [0.0, 1.0]]),
        [
            {"document_filename": "policy.md", "content": "25 days"},
            {"document_filename": "policy.md", "content": "carry over"},
            {"document_filename": "other.md", "content": "other"},
        ],
        ["old-1", "old-2", "other-1"],
    )

    assert await vector_db.delete_by_metadata({"document_filename": "policy.md"})
    assert await vector_db.get_count() == 1
    assert vector_db.index.ntotal == 1
    assert await vector_db.get_all_ids() == ["other-1"]

    reloaded = FAISSVectorDB(
        persist_directory=str(tmp_path),
        collection_name="replacement-test",
    )
    assert await reloaded.get_count() == 1
    assert reloaded.index.ntotal == 1
    assert await reloaded.get_all_ids() == ["other-1"]


@pytest.mark.asyncio
async def test_hybrid_search_does_not_runtime_bm25_when_count_unknown():
    class FakeEmbedder:
        async def embed(self, query):
            return np.array([1.0, 0.0])

    class CountUnknownVectorDb:
        async def get_count(self):
            raise RuntimeError("count unavailable")

        async def get_all_ids(self):
            raise AssertionError("search must not warm BM25 when count is unknown")

        async def search(self, query_embedding, top_k: int = 10, filters=None):
            return [
                {
                    "id": "chunk-1",
                    "score": 0.9,
                    "metadata": {"content": "vector-only evidence"},
                }
            ]

    service = object.__new__(DocumentService)
    service.collection_name = "dense-or-unknown"
    service.vector_db_type = "qdrant"
    service.workspace_slug = None
    service.vector_db = CountUnknownVectorDb()
    service.embedder = FakeEmbedder()
    service.use_hybrid = True
    service.allow_runtime_bm25 = True
    service.use_cache = False
    service.cache = None
    service.cache_namespace = "test"
    service._documents_cache = []
    service.ensemble_retriever = None
    service.contextual_retriever = None
    service.use_reranker = False
    service.reranker = None

    results = await service.search("what is available?", top_k=1, use_hybrid=True)

    assert results[0]["content"] == "vector-only evidence"
    assert results[0]["bm25_score"] == 0.0


@pytest.mark.asyncio
async def test_hybrid_search_does_not_runtime_bm25_without_explicit_opt_in():
    class FakeEmbedder:
        async def embed(self, query):
            return np.array([1.0, 0.0])

    class NoRuntimeWarmupVectorDb:
        async def get_count(self):
            raise AssertionError("search must not count vectors when runtime BM25 is disabled")

        async def get_all_ids(self):
            raise AssertionError("search must not warm BM25 without explicit opt-in")

        async def search(self, query_embedding, top_k: int = 10, filters=None):
            return [
                {
                    "id": "chunk-1",
                    "score": 0.9,
                    "metadata": {"content": "vector-only evidence"},
                }
            ]

    service = object.__new__(DocumentService)
    service.collection_name = "small-but-prod-default"
    service.vector_db_type = "qdrant"
    service.workspace_slug = None
    service.vector_db = NoRuntimeWarmupVectorDb()
    service.embedder = FakeEmbedder()
    service.use_hybrid = True
    service.allow_runtime_bm25 = False
    service.use_cache = False
    service.cache = None
    service.cache_namespace = "test"
    service._documents_cache = []
    service.ensemble_retriever = None
    service.contextual_retriever = None
    service.use_reranker = False
    service.reranker = None

    results = await service.search("what is available?", top_k=1, use_hybrid=True)

    assert results[0]["content"] == "vector-only evidence"
    assert results[0]["bm25_score"] == 0.0


@pytest.mark.asyncio
async def test_degraded_embeddings_enable_bounded_runtime_bm25_fallback():
    class DegradedEmbedder:
        def is_degraded(self):
            return True

        async def embed(self, query):  # noqa: ARG002
            return np.array([1.0, 0.0])

    class SmallVectorDb:
        metadatas = {
            "chunk-1": {"content": "generic incident summary"},
            "chunk-2": {"content": "SEAL-KIT-3309 is stocked at HUB-LYS"},
        }

        async def get_count(self):
            return 2

        async def get_all_ids(self):
            return list(self.metadatas)

        async def search(self, query_embedding, top_k: int = 10, filters=None):  # noqa: ARG002
            return [
                {
                    "id": "chunk-1",
                    "score": 0.9,
                    "metadata": self.metadatas["chunk-1"],
                    "content": self.metadatas["chunk-1"]["content"],
                },
                {
                    "id": "chunk-2",
                    "score": 0.1,
                    "metadata": self.metadatas["chunk-2"],
                    "content": self.metadatas["chunk-2"]["content"],
                },
            ][:top_k]

    service = object.__new__(DocumentService)
    service.collection_name = "small-local-demo"
    service.vector_db_type = "faiss"
    service.workspace_slug = "personal-test"
    service.vector_db = SmallVectorDb()
    service.embedder = DegradedEmbedder()
    service.use_hybrid = True
    service.allow_runtime_bm25 = False
    service.use_cache = False
    service.cache = None
    service.cache_namespace = "test"
    service._documents_cache = []
    service.bm25_retriever = BM25Retriever()
    service.ensemble_retriever = None
    service.contextual_retriever = None
    service.use_reranker = False
    service.reranker = None

    results = await service.search("Where is SEAL-KIT-3309 stocked?", top_k=2, use_hybrid=True)

    assert service.ensemble_retriever is None
    assert results[0]["content"] == "SEAL-KIT-3309 is stocked at HUB-LYS"
    assert results[0]["bm25_score"] > 0.0


@pytest.mark.asyncio
async def test_oracle_fast_search_skips_contextual_cross_encoder():
    class FakeEmbedder:
        async def embed(self, query):
            return np.array([1.0, 0.0])

    class FakeVectorDb:
        async def get_count(self):
            return 1

        async def search(self, query_embedding, top_k: int = 10, filters=None, search_params=None):  # noqa: ARG002
            return [
                {
                    "id": "chunk-1",
                    "score": 0.9,
                    "content": "ensemble passage",
                    "metadata": {"content": "ensemble passage"},
                }
            ]

    class FakeEnsemble:
        def __init__(self):
            self.calls = 0

        async def retrieve(self, query, top_k):  # noqa: ARG002
            self.calls += 1
            return ["ensemble passage"], [0.88]

    class ExplodingContextual:
        async def retrieve_and_compress(self, query, top_k):  # noqa: ARG002
            raise AssertionError("oracle_fast must not use the cross-encoder path")

    ensemble = FakeEnsemble()
    service = object.__new__(DocumentService)
    service.collection_name = "oracle-kb"
    service.vector_db_type = "qdrant"
    service.workspace_slug = None
    service.vector_db = FakeVectorDb()
    service.embedder = FakeEmbedder()
    service.use_hybrid = True
    service.allow_runtime_bm25 = True
    service.use_cache = False
    service.cache = None
    service.cache_namespace = "test"
    service._documents_cache = ["ensemble passage"]
    service.ensemble_retriever = ensemble
    service.contextual_retriever = ExplodingContextual()
    service.use_reranker = True
    service.reranker = object()

    results = await service.search(
        "oracle quick check",
        top_k=1,
        use_hybrid=True,
        search_params={"retrieval_profile": "oracle_fast"},
    )

    assert ensemble.calls == 1
    assert results[0]["content"] == "ensemble passage"


@pytest.mark.asyncio
async def test_list_documents_normalizes_chunk_count_fields():
    """Document listings expose the singular field used by the Knowledge UI."""

    class FakeVectorDb:
        async def list_documents(self):
            return [
                {"document_id": "doc-1", "filename": "one.md", "document_type": "markdown"},
                {"document_id": "doc-2", "filename": "two.md", "chunks_count": 1},
            ]

        async def get_by_document_id(self, document_id):
            return ["a", "b", "c"] if document_id == "doc-1" else ["z"]

    service = object.__new__(DocumentService)
    service.vector_db = FakeVectorDb()

    documents = await service.list_documents()

    assert documents[0]["chunk_count"] == 3
    assert documents[0]["chunks_count"] == 3
    assert documents[1]["chunk_count"] == 1
    assert documents[1]["chunks_count"] == 1
