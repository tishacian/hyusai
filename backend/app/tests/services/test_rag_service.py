"""Tests for RAG service"""
import pytest
import asyncio
import tempfile
import os
import numpy as np
from app.services.rag.document_service import DocumentService, _document_extra_metadata
from app.services.vector_db.factory import VectorDBFactory


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
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
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
