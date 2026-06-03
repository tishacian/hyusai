from __future__ import annotations

from types import SimpleNamespace

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
                source_metadata={"document_id": "small"},
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
                source_metadata={"document_id": "large"},
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
