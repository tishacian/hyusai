from __future__ import annotations

import pytest

from app.core.config import settings
from app.services.rag.sparse_backends import (
    OpenSearchSparseBackend,
    QdrantSparseBackend,
    get_sparse_backend,
    sparse_runtime_config,
)


@pytest.mark.asyncio
async def test_opensearch_sparse_backend_uses_exact_filter_fields(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"hits": {"hits": []}}

    class FakeAsyncClient:
        requests = []

        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, json):
            self.requests.append((url, json))
            return FakeResponse()

    monkeypatch.setattr("app.services.rag.sparse_backends.httpx.AsyncClient", FakeAsyncClient)
    backend = OpenSearchSparseBackend(base_url="http://opensearch.test", index_prefix="agentium-rag")

    await backend.search(
        "start procedure",
        collection="Dense Manuals",
        filters={
            "document_filename": ["A__ACJ100__start_procedure.html", "B__ACJ100__stop.html"],
            "project_code": "ACJ100",
            "source_kind": "manual",
        },
        top_k=5,
        deadline_seconds=3,
    )

    assert FakeAsyncClient.requests
    url, body = FakeAsyncClient.requests[0]
    assert url == "http://opensearch.test/agentium-rag-dense-manuals/_search"
    assert body["size"] == 5
    filters = body["query"]["bool"]["filter"]
    assert {"terms": {"document_filename.keyword": ["A__ACJ100__start_procedure.html", "B__ACJ100__stop.html"]}} in filters
    assert {"term": {"project_code": "ACJ100"}} in filters
    assert {"term": {"source_kind": "manual"}} in filters


@pytest.mark.asyncio
async def test_opensearch_sparse_backend_preserves_tiny_deadlines(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"hits": {"hits": []}}

    class FakeAsyncClient:
        timeouts = []

        def __init__(self, *args, **kwargs):
            self.timeouts.append(kwargs.get("timeout"))

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, json):  # noqa: ARG002
            return FakeResponse()

    monkeypatch.setattr("app.services.rag.sparse_backends.httpx.AsyncClient", FakeAsyncClient)
    backend = OpenSearchSparseBackend(base_url="http://opensearch.test", index_prefix="agentium-rag")

    await backend.search("start procedure", collection="dense", top_k=5, deadline_seconds=0.01)

    assert FakeAsyncClient.timeouts == [0.01]


@pytest.mark.asyncio
async def test_opensearch_sparse_backend_returns_metadata(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "hits": {
                    "hits": [
                        {
                            "_id": "sparse-doc-1",
                            "_score": 2.5,
                            "_source": {
                                "content": "Sparse summary evidence",
                                "collection": "dense",
                                "document_filename": "manual.html",
                                "project_code": "ACJ100",
                                "language": "fr",
                                "status": "ready",
                                "metadata": {"retrieval_artifact": "summary_sparse"},
                            },
                        }
                    ]
                }
            }

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, json):  # noqa: ARG002
            return FakeResponse()

    monkeypatch.setattr("app.services.rag.sparse_backends.httpx.AsyncClient", FakeAsyncClient)
    backend = OpenSearchSparseBackend(base_url="http://opensearch.test", index_prefix="agentium-rag")

    out = await backend.search("procedure", collection="dense", top_k=1)

    assert out[0]["id"] == "sparse-doc-1"
    assert out[0]["content"] == "Sparse summary evidence"
    assert out[0]["metadata"]["retrieval_artifact"] == "summary_sparse"
    assert out[0]["metadata"]["document_filename"] == "manual.html"
    assert out[0]["metadata"]["project_code"] == "ACJ100"
    assert out[0]["metadata"]["collection"] == "dense"
    assert out[0]["metadata"]["language"] == "fr"
    assert out[0]["metadata"]["status"] == "ready"
    assert out[0]["sparse_backend"] == "opensearch"


def test_sparse_backend_auto_prefers_qdrant_then_opensearch(monkeypatch):
    monkeypatch.setattr(settings, "rag_sparse_backend", "auto")
    monkeypatch.setattr(settings, "rag_qdrant_sparse_enabled", True)
    monkeypatch.setattr(settings, "rag_opensearch_url", "http://opensearch.test")
    assert isinstance(get_sparse_backend(), QdrantSparseBackend)

    monkeypatch.setattr(settings, "rag_qdrant_sparse_enabled", False)
    assert isinstance(get_sparse_backend(), OpenSearchSparseBackend)


def test_readiness_auto_qdrant_sparse_not_dense_only(monkeypatch):
    monkeypatch.setattr(settings, "rag_sparse_backend", "auto")
    monkeypatch.setattr(settings, "rag_qdrant_sparse_enabled", True)
    monkeypatch.setattr(settings, "rag_opensearch_url", None)
    monkeypatch.setattr(settings, "rag_allow_runtime_bm25", False)

    config = sparse_runtime_config()

    assert config["dense_only_by_default"] is False


@pytest.mark.asyncio
async def test_qdrant_sparse_backend_delegates_to_vector_store(monkeypatch):
    class FakeVectorDb:
        calls = []

        async def search_sparse(self, query, top_k=10, filters=None):
            self.calls.append((query, top_k, filters))
            return [
                {
                    "id": "chunk-1",
                    "content": "KD724 sparse evidence",
                    "score": 0.5,
                    "metadata": {"document_filename": "manual.pdf"},
                }
            ]

    fake_db = FakeVectorDb()
    monkeypatch.setattr(settings, "rag_qdrant_sparse_enabled", True)
    monkeypatch.setattr(
        "app.services.vector_db.factory.VectorDBFactory.get_db",
        lambda collection, db_type="qdrant", workspace_slug=None: fake_db,
    )

    out = await QdrantSparseBackend().search(
        "KD724",
        collection="andritz__docs",
        filters={"project_code": "KD724"},
        top_k=4,
    )

    assert fake_db.calls == [("KD724", 4, {"project_code": "KD724"})]
    assert out[0]["sparse_backend"] == "qdrant_sparse"
    assert out[0]["metadata"]["sparse_backend"] == "qdrant_sparse"
