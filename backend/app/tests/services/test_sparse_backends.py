from __future__ import annotations

import pytest

from app.services.rag.sparse_backends import OpenSearchSparseBackend


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
