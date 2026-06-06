from __future__ import annotations

import asyncio
from types import SimpleNamespace

import numpy as np
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import documents
from app.core.config import settings
from app.models.knowledge_collection import KnowledgeCollection, KnowledgeCollectionSource, WorkerJob
from app.models.knowledge_document_fact import KnowledgeDocumentFact
from app.models.knowledge_table_fact import KnowledgeTableFact
from app.models.workspace import Workspace
from app.services.knowledge_collections import create_collection, create_worker_job
from app.services.object_store import get_object_store


def _client(db_session, workspace: Workspace) -> TestClient:
    app = FastAPI()
    app.include_router(documents.router, prefix="/documents")
    app.dependency_overrides[documents.get_current_workspace] = lambda: workspace
    app.dependency_overrides[documents.get_current_user] = lambda: SimpleNamespace(id="user-1")
    app.dependency_overrides[documents.get_db] = lambda: db_session
    return TestClient(app)


def test_list_collections_returns_ledger_items(db_session, monkeypatch):
    ws = Workspace(id="ws-api", name="API", slug="api")
    db_session.add(ws)
    db_session.commit()
    create_collection(db_session, workspace=ws, name="Policies")
    db_session.commit()

    monkeypatch.setattr(
        "app.services.vector_db.factory.VectorDBFactory.list_collections_for_workspace",
        classmethod(lambda cls, db_type="qdrant", workspace_slug=None: []),
    )

    response = _client(db_session, ws).get("/documents/collections")

    assert response.status_code == 200
    body = response.json()
    assert body["collections"] == ["policies"]
    assert body["items"][0]["name"] == "Policies"
    assert body["items"][0]["status"] == "created"
    assert "document_names" not in body["items"][0]


def test_collection_inventory_can_page_sources(db_session, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "objects"))
    ws = Workspace(id="ws-inventory", name="Inventory", slug="inventory")
    db_session.add(ws)
    db_session.commit()
    collection = create_collection(db_session, workspace=ws, name="Manuals")
    collection.document_count = 3
    collection.chunk_count = 33
    db_session.add_all(
        [
            KnowledgeCollectionSource(
                workspace_id=ws.id,
                collection_id=collection.id,
                filename=f"manual-{index}.pdf",
                normalized_name=f"manual-{index}.pdf",
                source_kind="pdf",
                extension="pdf",
                mime_type="application/pdf",
                origin="upload",
                chunk_count=10 + index,
                status="ready",
                source_metadata={"document_id": f"doc-{index}"},
            )
            for index in range(3)
        ]
    )
    db_session.commit()

    response = _client(db_session, ws).get(
        f"/documents/collections/{collection.id}/inventory?source_limit=2&source_offset=1"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source_count"] == 3
    assert body["chunk_count"] == 33
    assert body["sources_offset"] == 1
    assert body["sources_limit"] == 2
    assert body["sources_returned"] == 2
    assert body["sources_has_more"] is False
    assert [source["filename"] for source in body["sources"]] == ["manual-1.pdf", "manual-2.pdf"]


def test_collection_inventory_filters_sorts_and_returns_global_aggregates(db_session):
    ws = Workspace(id="ws-inventory-filter", name="Inventory Filter", slug="inventory-filter")
    db_session.add(ws)
    db_session.commit()
    collection = create_collection(db_session, workspace=ws, name="Manuals")
    db_session.add_all(
        [
            KnowledgeCollectionSource(
                workspace_id=ws.id,
                collection_id=collection.id,
                filename="manual-small.pdf",
                normalized_name="manual-small.pdf",
                source_kind="pdf",
                extension="pdf",
                mime_type="application/pdf",
                origin="upload",
                chunk_count=10,
                status="ready",
                source_metadata={"document_id": "small", "project_code": "ACJ100"},
            ),
            KnowledgeCollectionSource(
                workspace_id=ws.id,
                collection_id=collection.id,
                filename="manual-large.pdf",
                normalized_name="manual-large.pdf",
                source_kind="pdf",
                extension="pdf",
                mime_type="application/pdf",
                origin="upload",
                chunk_count=1200,
                status="ready",
                source_metadata={"document_id": "large", "project_code": "ZZZ900"},
            ),
            KnowledgeCollectionSource(
                workspace_id=ws.id,
                collection_id=collection.id,
                filename="diagram.png",
                normalized_name="diagram.png",
                source_kind="image",
                extension="png",
                mime_type="image/png",
                origin="upload",
                chunk_count=1,
                status="error",
            ),
        ]
    )
    db_session.commit()

    response = _client(db_session, ws).get(
        f"/documents/collections/{collection.slug}/inventory?source_kind=pdf&sort=chunk_count&sort_dir=desc"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source_count"] == 3
    assert body["sources_total"] == 2
    assert body["by_kind"] == {"image": 1, "pdf": 2}
    assert body["heavy_sources"] == 1
    assert body["chunk_buckets"][">1000"]["sources"] == 1
    assert [source["filename"] for source in body["sources"]] == ["manual-large.pdf", "manual-small.pdf"]

    scoped_response = _client(db_session, ws).get(
        f"/documents/collections/{collection.slug}/inventory?project_code=ACJ100"
    )
    assert scoped_response.status_code == 200
    scoped_body = scoped_response.json()
    assert scoped_body["source_count"] == 3
    assert scoped_body["sources_total"] == 1
    assert scoped_body["source_filters"]["project_code"] == "ACJ100"
    assert [source["filename"] for source in scoped_body["sources"]] == ["manual-small.pdf"]


def test_document_preview_resolves_source_from_ledger_without_vector_listing(db_session, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "objects"))
    ws = Workspace(id="ws-ledger-preview", name="Ledger Preview", slug="ledger-preview")
    db_session.add(ws)
    db_session.commit()
    collection = create_collection(db_session, workspace=ws, name="Manuals")
    filename = "manual.txt"
    db_session.add(
        KnowledgeCollectionSource(
            workspace_id=ws.id,
            collection_id=collection.id,
            filename=filename,
            normalized_name=filename,
            source_kind="text",
            extension="txt",
            mime_type="text/plain",
            origin="upload",
            chunk_count=1,
            status="ready",
            source_metadata={"document_id": "doc-ledger"},
        )
    )
    get_object_store().write_text(documents.original_key(collection, filename), "ledger preview")
    db_session.commit()

    class ExplodingDocumentService:
        def __init__(self, *args, **kwargs):  # noqa: D401, ARG002
            pass

        async def list_documents(self):
            raise AssertionError("ledger-backed preview must not list vector documents")

    monkeypatch.setattr(documents, "DocumentService", ExplodingDocumentService)

    client = _client(db_session, ws)
    preview = client.get(f"/documents/doc-ledger/rich-preview?collection_name={collection.slug}")
    assert preview.status_code == 200, preview.text
    assert preview.json()["filename"] == filename
    assert preview.json()["content"] == "ledger preview"

    raw = client.get(f"/documents/doc-ledger/raw?collection_name={collection.slug}")
    assert raw.status_code == 200
    assert raw.text == "ledger preview"


def test_list_chunks_returns_exact_ledger_total_for_document(db_session, monkeypatch):
    ws = Workspace(id="ws-chunks", name="Chunks", slug="chunks")
    db_session.add(ws)
    db_session.commit()
    collection = create_collection(db_session, workspace=ws, name="Manuals")
    db_session.add(
        KnowledgeCollectionSource(
            workspace_id=ws.id,
            collection_id=collection.id,
            filename="manual.pdf",
            normalized_name="manual.pdf",
            source_kind="pdf",
            extension="pdf",
            mime_type="application/pdf",
            origin="upload",
            chunk_count=3,
            status="ready",
            source_metadata={"document_id": "doc-1"},
        )
    )
    db_session.commit()

    class FakeVectorDB:
        async def count_payloads(self, filters=None):
            return 99

        async def list_payloads(self, filters=None, limit=100, offset=0):
            return [
                {"point_id": "p1", "document_id": "doc-1", "content": "first"},
                {"point_id": "p2", "document_id": "doc-1", "content": "second"},
            ]

    class FakeDocumentService:
        def __init__(self, *args, **kwargs):
            self.vector_db = FakeVectorDB()

        async def get_document_count(self):
            return 99

    monkeypatch.setattr(documents, "DocumentService", FakeDocumentService)

    response = _client(db_session, ws).get(
        f"/documents/chunks?collection_name={collection.slug}&document_id=doc-1&limit=2"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert body["total_is_exact"] is True
    assert body["has_more"] is True
    assert len(body["chunks"]) == 2


def test_document_search_skips_dense_unscoped_global_search(db_session, monkeypatch):
    monkeypatch.setattr(settings, "rag_dense_chunk_threshold", 100)
    monkeypatch.setattr(settings, "rag_dense_source_threshold", 2)
    ws = Workspace(id="ws-doc-search-dense", name="Doc Search Dense", slug="doc-search-dense")
    db_session.add(ws)
    db_session.commit()
    collection = create_collection(db_session, workspace=ws, name="Dense SPL")
    collection.document_count = 3
    collection.chunk_count = 150
    db_session.commit()

    class FakeDocumentService:
        def __init__(self, *args, **kwargs):
            self.collection_name = kwargs.get("collection_name")

        async def get_document_count(self):
            return 150

        async def search(self, *args, **kwargs):  # noqa: ARG002
            raise AssertionError("dense unscoped /documents/search must not search globally")

    monkeypatch.setattr(documents, "DocumentService", FakeDocumentService)

    response = _client(db_session, ws).post(
        "/documents/search",
        json={
            "query": "Analyse les procedures SPL",
            "collection_name": collection.slug,
            "use_hybrid": True,
            "top_k": 999,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["results"] == []
    assert body["total"] == 0
    assert body["dense_policy"] == "fast_sparse_direct"
    assert body["fallback_reason"] in {None, "dense_unscoped_fast_policy", "dense_unscoped_search_skipped"}
    assert body["latency_budget"]["candidate_pool_k"] <= 20
    assert body["retrieval_plan"]["guardrails"]["global_chunk_search_allowed"] is False


def test_document_search_dense_scoped_is_vector_only_and_bounded(db_session, monkeypatch):
    monkeypatch.setattr(settings, "rag_dense_chunk_threshold", 100)
    monkeypatch.setattr(settings, "rag_dense_source_threshold", 2)
    ws = Workspace(id="ws-doc-search-scoped", name="Doc Search Scoped", slug="doc-search-scoped")
    db_session.add(ws)
    db_session.commit()
    collection = create_collection(db_session, workspace=ws, name="Dense Scoped SPL")
    collection.document_count = 3
    collection.chunk_count = 150
    db_session.commit()
    captured: dict = {}

    class FakeDocumentService:
        def __init__(self, *args, **kwargs):
            captured["init"] = kwargs

        async def get_document_count(self):
            return 150

        async def search(self, query, top_k=10, filters=None, use_hybrid=None):  # noqa: ARG002
            captured["search"] = {
                "top_k": top_k,
                "filters": filters,
                "use_hybrid": use_hybrid,
            }
            return [{"content": "scoped result", "metadata": {"source_kind": "markup"}, "score": 0.8}]

    monkeypatch.setattr(documents, "DocumentService", FakeDocumentService)

    response = _client(db_session, ws).post(
        "/documents/search",
        json={
            "query": "Explique la procedure SPL",
            "collection_name": collection.slug,
            "filters": {"source_kind": "markup"},
            "use_hybrid": True,
            "top_k": 999,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["dense_policy"] == "fast_scoped_dense"
    assert captured["init"]["use_hybrid"] is False
    assert captured["search"]["use_hybrid"] is False
    assert captured["search"]["top_k"] <= 20
    assert captured["search"]["filters"] == {"source_kind": "markup"}


def test_document_search_returns_budget_fallback_on_timeout(db_session, monkeypatch):
    monkeypatch.setattr(settings, "rag_fast_retrieval_deadline_seconds", 0.01)
    ws = Workspace(id="ws-doc-search-timeout", name="Doc Search Timeout", slug="doc-search-timeout")
    db_session.add(ws)
    db_session.commit()
    collection = create_collection(db_session, workspace=ws, name="Timeout Manuals")
    collection.document_count = 1
    collection.chunk_count = 5
    db_session.commit()

    class FakeDocumentService:
        def __init__(self, *args, **kwargs):
            pass

        async def get_document_count(self):
            return 5

        async def search(self, *args, **kwargs):  # noqa: ARG002
            await asyncio.sleep(0.2)
            return [{"content": "late", "score": 0.9, "metadata": {}}]

    monkeypatch.setattr(documents, "DocumentService", FakeDocumentService)

    response = _client(db_session, ws).post(
        "/documents/search",
        json={
            "query": "Explique la procedure SPL",
            "collection_name": collection.slug,
            "use_hybrid": False,
            "top_k": 3,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["results"] == []
    assert body["fallback_reason"] == "retrieval_deadline_exceeded"
    assert body["latency_budget"]["deadline_seconds"] == 0.01


def test_document_facts_return_total_has_more_and_type_counts(db_session):
    ws = Workspace(id="ws-facts", name="Facts", slug="facts")
    db_session.add(ws)
    db_session.commit()
    collection = create_collection(db_session, workspace=ws, name="Manuals")
    db_session.add_all(
        [
            KnowledgeDocumentFact(
                workspace_id=ws.id,
                collection_id=collection.id,
                collection_slug=collection.slug,
                document_id=f"doc-{index}",
                document_filename=f"manual-{index}.pdf",
                semantic_type="document_procedure_step",
                content=f"procedure {index}",
            )
            for index in range(2)
        ]
        + [
            KnowledgeDocumentFact(
                workspace_id=ws.id,
                collection_id=collection.id,
                collection_slug=collection.slug,
                document_id="doc-warning",
                document_filename="warning.pdf",
                semantic_type="document_warning",
                content="warning",
            )
        ]
    )
    db_session.commit()

    response = _client(db_session, ws).get(
        f"/documents/document-facts?collection_name={collection.slug}&semantic_type=document_procedure_step&limit=1"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert body["has_more"] is True
    assert body["by_type"] == {"document_procedure_step": 2, "document_warning": 1}
    assert body["total_returned"] == 1


def test_collection_diagnostics_reports_drift_and_fact_coverage(db_session, monkeypatch):
    ws = Workspace(id="ws-diagnostics", name="Diagnostics", slug="diagnostics")
    db_session.add(ws)
    db_session.commit()
    collection = create_collection(db_session, workspace=ws, name="Manuals")
    db_session.add_all(
        [
            KnowledgeCollectionSource(
                workspace_id=ws.id,
                collection_id=collection.id,
                filename="manual.pdf",
                normalized_name="manual.pdf",
                source_kind="pdf",
                extension="pdf",
                mime_type="application/pdf",
                origin="upload",
                chunk_count=10,
                status="ready",
            ),
            KnowledgeDocumentFact(
                workspace_id=ws.id,
                collection_id=collection.id,
                collection_slug=collection.slug,
                document_id="doc-1",
                document_filename="manual.pdf",
                document_type="pdf",
                semantic_type="document_warning",
                content="warning",
            ),
            KnowledgeTableFact(
                workspace_id=ws.id,
                collection_id=collection.id,
                collection_slug=collection.slug,
                document_id="sheet-1",
                document_filename="sheet.xlsx",
                semantic_type="spreadsheet_cell_fact",
                content="cell",
            ),
        ]
    )
    db_session.commit()

    class FakeVectorDB:
        dimension = 1536

    class FakeDocumentService:
        def __init__(self, *args, **kwargs):
            self.vector_db = FakeVectorDB()

        async def get_document_count(self):
            return 12

    monkeypatch.setattr(documents, "DocumentService", FakeDocumentService)

    response = _client(db_session, ws).get(
        f"/documents/collections/{collection.slug}/diagnostics"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["vector_points"] == 12
    assert body["ledger_chunk_sum"] == 10
    assert body["drift"] == 2
    assert body["drift_status"] == "warning"
    assert body["document_facts"]["by_type"] == {"document_warning": 1}
    assert body["table_facts"]["by_type"] == {"spreadsheet_cell_fact": 1}
    assert body["offline_clustering"]["launch_policy"] == "manual_only"
    assert body["offline_clustering"]["auto_run"] is False
    assert body["offline_clustering"]["stores_vectors"] is False
    assert body["offline_clustering"]["artifact_key"].endswith("/derived/embedding-clusters/latest.json")
    assert body["feature_status"]["offline_clustering"]["state"] == "not_needed"


def test_embedding_graph_caps_dense_sample_and_hides_raw_vectors(db_session, monkeypatch):
    documents._GRAPH_CACHE.clear()
    ws = Workspace(id="ws-graph", name="Graph", slug="graph")
    db_session.add(ws)
    db_session.commit()
    collection = create_collection(db_session, workspace=ws, name="Manuals")
    collection.document_count = settings.rag_dense_source_threshold + 1
    collection.chunk_count = settings.rag_dense_chunk_threshold + 1
    db_session.commit()

    class FakeVectorDB:
        def __init__(self):
            self.calls = []

        async def sample_chunk_vectors(self, limit=200, filters=None):
            self.calls.append((limit, filters))
            return [
                {
                    "id": f"point-{index}",
                    "vector": [float(index), float(index + 1), 1.0],
                    "payload": {
                        "document_id": f"doc-{index}",
                        "document_filename": f"manual-{index}.pdf",
                        "chunk_index": index,
                        "content": f"chunk content {index}",
                        "source_kind": "pdf",
                    },
                }
                for index in range(4)
            ]

    fake_vector_db = FakeVectorDB()

    class FakeDocumentService:
        def __init__(self, *args, **kwargs):
            self.vector_db = fake_vector_db

        async def get_document_count(self):
            return settings.rag_dense_chunk_threshold + 1

    monkeypatch.setattr(documents, "DocumentService", FakeDocumentService)
    monkeypatch.setattr(
        documents,
        "_project_2d",
        lambda matrix: (np.asarray(matrix, dtype=float)[:, :2], "pca"),
    )

    response = _client(db_session, ws).get(
        f"/documents/graph?collection_name={collection.slug}&sample=1000"
    )

    assert response.status_code == 200
    body = response.json()
    assert fake_vector_db.calls == [(500, None)]
    assert body["sample"] == 4
    assert body["sample_requested"] == 1000
    assert body["sample_cap"] == 500
    assert body["sample_capped"] is True
    assert body["total_is_dense"] is True
    assert any("sampled and not exhaustive" in warning for warning in body["warnings"])
    assert any("capped to 500" in warning for warning in body["warnings"])
    assert body["vector_dim"] == 3
    assert body["nodes"]
    assert all("vector" not in node and "embedding" not in node for node in body["nodes"])


def test_list_documents_uses_ledger_page_without_vector_scroll(db_session, monkeypatch):
    ws = Workspace(id="ws-list", name="List", slug="list")
    db_session.add(ws)
    db_session.commit()
    collection = create_collection(db_session, workspace=ws, name="Manuals")
    db_session.add_all(
        [
            KnowledgeCollectionSource(
                workspace_id=ws.id,
                collection_id=collection.id,
                filename=f"manual-{index}.pdf",
                normalized_name=f"manual-{index}.pdf",
                source_kind="pdf",
                extension="pdf",
                mime_type="application/pdf",
                origin="upload",
                size_bytes=100 + index,
                chunk_count=index + 1,
                status="ready",
                source_metadata={"document_id": f"doc-{index}"},
            )
            for index in range(3)
        ]
    )
    db_session.commit()

    class ExplodingDocumentService:
        def __init__(self, *args, **kwargs):
            raise AssertionError("ledger-backed /list should not instantiate DocumentService")

    monkeypatch.setattr(documents, "DocumentService", ExplodingDocumentService)

    response = _client(db_session, ws).get(
        f"/documents/list?collection_name={collection.slug}&limit=2&offset=1"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "ledger"
    assert body["total"] == 3
    assert body["has_more"] is False
    assert [item["document_id"] for item in body["documents"]] == ["doc-1", "doc-2"]
    assert body["documents"][0]["chunk_count"] == 2


def test_collection_document_upload_creates_worker_job_and_stores_original(
    db_session,
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "objects"))
    ws = Workspace(id="ws-upload", name="Upload", slug="upload")
    db_session.add(ws)
    db_session.commit()
    collection = create_collection(db_session, workspace=ws, name="Manuals")
    db_session.commit()

    def fake_dispatch(db, job):
        job.celery_task_id = "task-1"
        return "task-1"

    monkeypatch.setattr(documents, "dispatch_worker_job", fake_dispatch)

    response = _client(db_session, ws).post(
        f"/documents/collections/{collection.id}/documents",
        files=[("files", ("manual.txt", b"hello", "text/plain"))],
    )

    assert response.status_code == 200
    body = response.json()
    assert body["collection_id"] == collection.id
    assert body["status"] == "queued"
    assert body["celery_task_id"] == "task-1"

    job = db_session.query(WorkerJob).filter(WorkerJob.id == body["job_id"]).one()
    assert job.collection_id == collection.id
    assert job.status == "queued"
    assert (
        tmp_path / "objects" / collection.artifact_prefix / "original" / "manual.txt"
    ).read_bytes() == b"hello"
    source = (
        db_session.query(KnowledgeCollectionSource)
        .filter(KnowledgeCollectionSource.collection_id == collection.id)
        .one()
    )
    assert source.filename == "manual.txt"
    assert source.source_kind == "text"
    assert source.extension == "txt"
    assert source.size_bytes == 5
    assert source.status == "queued"


def test_collection_detail_exposes_storage_vector_and_bm25_diagnostics(
    db_session,
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "objects"))
    monkeypatch.setattr(settings, "default_vector_db_type", "qdrant")
    ws = Workspace(id="ws-detail", name="Detail", slug="detail")
    db_session.add(ws)
    db_session.commit()
    collection = create_collection(db_session, workspace=ws, name="Manuals")
    collection.document_names = ["manual.txt"]
    collection.document_count = 1
    bm25_job = create_worker_job(
        db_session,
        workspace_id=ws.id,
        collection_id=collection.id,
        kind="bm25_rebuild",
    )
    bm25_job.status = "completed"
    bm25_job.progress = 100
    bm25_job.result = {"bm25": {"status": "ready", "chunk_count": 7}, "stage": "bm25_ready"}
    db_session.commit()

    store = get_object_store()
    store.write_bytes(f"{collection.artifact_prefix}/original/manual.txt", b"hello")
    store.write_bytes(f"{collection.artifact_prefix}/ingested/manual.txt", b"hello text")
    store.write_bytes(f"{collection.artifact_prefix}/derived/bm25_retriever.pkl", b"bm25")

    class FakeVectorDB:
        async def get_count(self):
            return 7

    monkeypatch.setattr(
        "app.services.vector_db.factory.VectorDBFactory.get_db",
        classmethod(lambda cls, *args, **kwargs: FakeVectorDB()),
    )

    response = _client(db_session, ws).get(f"/documents/collections/{collection.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["storage"]["original_bytes"] == 5
    assert body["storage"]["ingested_bytes"] == 10
    assert body["storage"]["derived_bytes"] == 4
    assert body["vector_metrics"]["points"] == 7
    assert body["inventory"]["source_count"] == 1
    assert body["inventory"]["by_kind"] == {"text": 1}
    assert body["bm25"]["status"] == "ready"
    assert body["bm25"]["job"]["id"] == bm25_job.id
    assert body["latest_job"]["kind"] == "bm25_rebuild"

    inventory_response = _client(db_session, ws).get(f"/documents/collections/{collection.id}/inventory")
    assert inventory_response.status_code == 200
    inventory = inventory_response.json()
    assert inventory["source_count"] == 1
    assert inventory["sources"][0]["filename"] == "manual.txt"


def test_collection_retrieval_artifact_job_dry_run_does_not_create_job(db_session):
    ws = Workspace(id="ws-artifact-dry-run", name="Artifact Dry Run", slug="artifact-dry-run")
    db_session.add(ws)
    db_session.commit()
    collection = create_collection(db_session, workspace=ws, name="Manuals")
    db_session.commit()

    response = _client(db_session, ws).post(
        f"/documents/collections/{collection.id}/retrieval-artifact-jobs",
        json={"kind": "summary_index_rebuild", "dry_run": True},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "dry_run"
    assert body["would_create_job"] is True
    assert body["would_dispatch"] is True
    assert body["poll_url"] is None
    assert body["collection_slug"] == collection.slug
    assert db_session.query(WorkerJob).filter(WorkerJob.collection_id == collection.id).count() == 0


def test_collection_retrieval_artifact_job_queues_manual_worker(db_session, monkeypatch):
    ws = Workspace(id="ws-artifact-job", name="Artifact Job", slug="artifact-job")
    db_session.add(ws)
    db_session.commit()
    collection = create_collection(db_session, workspace=ws, name="Manuals")
    db_session.commit()

    def fake_dispatch(_db, job, **kwargs):
        assert kwargs["allow_inline_fallback"] is False
        job.celery_task_id = "task-summary"
        return "task-summary"

    monkeypatch.setattr(documents, "dispatch_worker_job", fake_dispatch)

    response = _client(db_session, ws).post(
        f"/documents/collections/{collection.slug}/retrieval-artifact-jobs",
        json={"kind": "summary_index_rebuild"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["kind"] == "summary_index_rebuild"
    assert body["collection_id"] == collection.id
    assert body["poll_url"] == f"/documents/jobs/{body['id']}"
    assert body["task_id"] == "task-summary"
    job = db_session.query(WorkerJob).filter(WorkerJob.id == body["id"]).one()
    assert job.kind == "summary_index_rebuild"
    assert job.collection_id == collection.id
    assert job.result["launch_policy"] == "manual_only"
    assert job.result["requested_by"] == "user-1"


def test_get_worker_job_returns_poll_url_and_omits_deep_context_by_default(db_session):
    ws = Workspace(id="ws-job-poll", name="Job Poll", slug="job-poll")
    db_session.add(ws)
    db_session.commit()
    collection = create_collection(db_session, workspace=ws, name="Manuals")
    job = create_worker_job(
        db_session,
        workspace_id=ws.id,
        collection_id=collection.id,
        kind="rag_deep_retrieval",
    )
    job.status = "completed"
    job.progress = 100
    job.result = {
        "stage": "deep_completed",
        "summary": {"chunks_retrieved": 1},
        "sources_preview": [{"title": "Manual", "snippet": "preview"}],
        "retrieval_context": {"chunks": ["heavy"], "scores": [0.9], "metadatas": [{}]},
    }
    db_session.commit()

    client = _client(db_session, ws)
    light = client.get(f"/documents/jobs/{job.id}")

    assert light.status_code == 200
    light_body = light.json()
    assert light_body["poll_url"] == f"/documents/jobs/{job.id}"
    assert light_body["result"]["retrieval_context_omitted"] is True
    assert "retrieval_context" not in light_body["result"]
    assert light_body["result"]["sources_preview"][0]["title"] == "Manual"

    detailed = client.get(f"/documents/jobs/{job.id}", params={"include_context": "true"})

    assert detailed.status_code == 200
    detailed_body = detailed.json()
    assert detailed_body["poll_url"] == f"/documents/jobs/{job.id}"
    assert detailed_body["result"]["retrieval_context"]["chunks"] == ["heavy"]


def test_list_worker_jobs_filters_recent_deep_retrieval_jobs(db_session):
    ws = Workspace(id="ws-job-list", name="Job List", slug="job-list")
    other = Workspace(id="ws-job-list-other", name="Other", slug="job-list-other")
    db_session.add_all([ws, other])
    db_session.commit()
    collection = create_collection(db_session, workspace=ws, name="Manuals")
    other_collection = create_collection(db_session, workspace=other, name="Other Manuals")
    running = create_worker_job(
        db_session,
        workspace_id=ws.id,
        collection_id=collection.id,
        kind="rag_deep_retrieval",
    )
    running.status = "running"
    running.progress = 35
    running.result = {"request": {"query": "Deep question"}}
    completed = create_worker_job(
        db_session,
        workspace_id=ws.id,
        collection_id=collection.id,
        kind="rag_deep_retrieval",
    )
    completed.status = "completed"
    completed.progress = 100
    completed.result = {"request": {"query": "Finished question"}}
    hidden = create_worker_job(
        db_session,
        workspace_id=other.id,
        collection_id=other_collection.id,
        kind="rag_deep_retrieval",
    )
    hidden.status = "running"
    db_session.commit()

    response = _client(db_session, ws).get(
        f"/documents/jobs?kind=rag_deep_retrieval&status=queued,running,completed&collection_id={collection.slug}&limit=10"
    )

    assert response.status_code == 200
    body = response.json()
    ids = {item["id"] for item in body["items"]}
    assert ids == {running.id, completed.id}
    assert body["total_returned"] == 2
    assert all(item["poll_url"] == f"/documents/jobs/{item['id']}" for item in body["items"])


def test_delete_collection_removes_ledger_and_store(
    db_session,
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "objects"))
    monkeypatch.setattr(settings, "default_vector_db_type", "faiss")
    monkeypatch.setattr(settings, "faiss_persist_directory", str(tmp_path / "faiss"), raising=False)

    ws = Workspace(id="ws-delete", name="Delete", slug="delete")
    db_session.add(ws)
    db_session.commit()
    collection = create_collection(db_session, workspace=ws, name="Manuals")
    db_session.commit()
    get_object_store().write_bytes(
        f"{collection.artifact_prefix}/original/manual.txt",
        b"hello",
    )

    class FakeVectorDB:
        async def clear_collection(self):
            return None

    monkeypatch.setattr(
        "app.services.vector_db.factory.VectorDBFactory.list_collections",
        classmethod(lambda cls, db_type="faiss": [collection.vector_collection_name]),
    )
    monkeypatch.setattr(
        "app.services.vector_db.factory.VectorDBFactory.get_db",
        classmethod(lambda cls, *args, **kwargs: FakeVectorDB()),
    )
    monkeypatch.setattr(
        "app.services.vector_db.factory.VectorDBFactory.clear_instance",
        classmethod(lambda cls, *args, **kwargs: None),
    )

    response = _client(db_session, ws).delete(f"/documents/collections/{collection.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["collection_id"] == collection.id
    deleted = (
        db_session.query(KnowledgeCollection)
        .filter(KnowledgeCollection.id == collection.id)
        .first()
    )
    assert deleted is None
    assert not (tmp_path / "objects" / collection.artifact_prefix).exists()
