from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.models.knowledge_collection import KnowledgeCollection, WorkerJob
from app.models.workspace import Workspace
from app.services.knowledge_collections import (
    create_collection,
    create_worker_job,
    document_manifest_key,
    original_key,
    update_job,
)
from app.services.object_store import get_object_store
from app.services.worker_bm25 import run_bm25_rebuild
from app.services.worker_ingest import run_document_ingest_index


def _workspace(db_session, *, slug: str = "acme") -> Workspace:
    ws = Workspace(id="ws-1", name="Acme", slug=slug)
    db_session.add(ws)
    db_session.commit()
    return ws


def test_collection_slug_is_workspace_unique(db_session):
    ws = _workspace(db_session)

    first = create_collection(db_session, workspace=ws, name="Policies")
    second = create_collection(db_session, workspace=ws, name="Policies")
    db_session.commit()

    assert first.slug == "policies"
    assert second.slug == "policies-2"
    assert first.vector_collection_name == "acme__policies"


def test_worker_job_lifecycle_update(db_session):
    ws = _workspace(db_session)
    collection = create_collection(db_session, workspace=ws, name="Docs")
    job = create_worker_job(
        db_session,
        workspace_id=ws.id,
        collection_id=collection.id,
        kind="document_ingest_index",
    )

    update_job(db_session, job.id, status="running", progress=50)
    update_job(db_session, job.id, status="completed", progress=100, result={"ok": True})
    db_session.commit()

    refreshed = db_session.query(WorkerJob).filter(WorkerJob.id == job.id).one()
    assert refreshed.status == "completed"
    assert refreshed.progress == 100
    assert refreshed.started_at is not None
    assert refreshed.completed_at is not None
    assert refreshed.result == {"ok": True}


def test_worker_ingest_indexes_collection_and_writes_ingested_text(
    db_session,
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "store"))
    monkeypatch.setattr(settings, "default_vector_db_type", "faiss")

    ws = _workspace(db_session)
    collection = create_collection(db_session, workspace=ws, name="Manuals")
    collection.document_names = ["manual.txt"]
    job = create_worker_job(
        db_session,
        workspace_id=ws.id,
        collection_id=collection.id,
        kind="document_ingest_index",
    )
    get_object_store().write_bytes(original_key(collection, "manual.txt"), b"hello world")
    get_object_store().write_text(
        document_manifest_key(collection),
        json.dumps({"manual.txt": {"project_code": "BBA120", "source_family": "operating_manual"}}),
    )
    db_session.commit()

    class FakeParser:
        async def parse(self, _path):
            return SimpleNamespace(chunks=[{"content": "hello world"}])

    class FakeDocumentService:
        def __init__(self, *args, **kwargs):
            self.vector_db = object()
            self.cleared = False

        async def clear_all_documents(self):
            self.cleared = True
            return True

        async def ingest_documents_batch(self, paths, **_kwargs):
            assert self.cleared is True
            assert _kwargs["document_metadata_by_name"]["manual.txt"]["project_code"] == "BBA120"
            return {
                "total": len(paths),
                "successful": len(paths),
                "failed": 0,
                "results": [{"status": "success", "chunks_processed": 1}],
            }

        async def get_document_count(self):
            return 1

        async def list_documents(self):
            return [{"document_id": "doc-1", "filename": "manual.txt"}]

    async def fake_bm25(**_kwargs):
        return {"status": "ready", "chunk_count": 1}

    monkeypatch.setattr(
        "app.services.worker_ingest.DocumentParserFactory.get_parser",
        lambda _path: FakeParser(),
    )
    monkeypatch.setattr("app.services.worker_ingest.DocumentService", FakeDocumentService)
    monkeypatch.setattr("app.services.worker_ingest.rebuild_bm25_artifact", fake_bm25)

    result = run_document_ingest_index(job.id)

    db_session.expire_all()
    refreshed_collection = (
        db_session.query(KnowledgeCollection).filter(KnowledgeCollection.id == collection.id).one()
    )
    refreshed_job = db_session.query(WorkerJob).filter(WorkerJob.id == job.id).one()
    assert result["chunk_count"] == 1
    assert refreshed_collection.status == "ready"
    assert refreshed_collection.document_count == 1
    assert refreshed_job.status == "completed"
    assert get_object_store().read_bytes(
        f"{collection.artifact_prefix}/ingested/manual.txt"
    ) == b"hello world"


def test_worker_ingest_defers_large_bm25_to_worker_job(
    db_session,
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "store"))
    monkeypatch.setattr(settings, "default_vector_db_type", "faiss")

    ws = _workspace(db_session, slug="defer")
    collection = create_collection(db_session, workspace=ws, name="Large Manuals")
    collection.document_names = ["manual.txt"]
    job = create_worker_job(
        db_session,
        workspace_id=ws.id,
        collection_id=collection.id,
        kind="document_ingest_index",
    )
    get_object_store().write_bytes(original_key(collection, "manual.txt"), b"hello world")
    db_session.commit()

    class FakeParser:
        async def parse(self, _path):
            return SimpleNamespace(chunks=[{"content": "hello world"}])

    class FakeDocumentService:
        def __init__(self, *args, **kwargs):
            self.vector_db = object()

        async def clear_all_documents(self):
            return True

        async def ingest_documents_batch(self, paths, **_kwargs):
            return {
                "total": len(paths),
                "successful": len(paths),
                "failed": 0,
                "results": [{"status": "success", "chunks_processed": 10}],
            }

        async def get_document_count(self):
            return 75000

        async def list_documents(self):
            return [{"document_id": "doc-1", "filename": "manual.txt"}]

    async def fake_bm25(**_kwargs):
        return {
            "status": "deferred",
            "reason": "collection_too_large",
            "chunk_count": 75000,
            "threshold": 50000,
        }

    def fake_dispatch(_db, bm25_job):
        assert bm25_job.kind == "bm25_rebuild"
        bm25_job.celery_task_id = "task-bm25"
        return "task-bm25"

    monkeypatch.setattr(
        "app.services.worker_ingest.DocumentParserFactory.get_parser",
        lambda _path: FakeParser(),
    )
    monkeypatch.setattr("app.services.worker_ingest.DocumentService", FakeDocumentService)
    monkeypatch.setattr("app.services.worker_ingest.rebuild_bm25_artifact", fake_bm25)
    monkeypatch.setattr("app.services.worker_dispatch.dispatch_worker_job", fake_dispatch)

    result = run_document_ingest_index(job.id)

    db_session.expire_all()
    bm25_job = (
        db_session.query(WorkerJob)
        .filter(WorkerJob.collection_id == collection.id, WorkerJob.kind == "bm25_rebuild")
        .one()
    )
    refreshed_ingest = db_session.query(WorkerJob).filter(WorkerJob.id == job.id).one()
    assert result["bm25"]["status"] == "queued"
    assert result["bm25"]["worker_job_id"] == bm25_job.id
    assert bm25_job.status == "queued"
    assert bm25_job.celery_task_id == "task-bm25"
    assert refreshed_ingest.result["stage"] == "ready"


def test_bm25_rebuild_worker_forces_sidecar_rebuild(db_session, monkeypatch):
    ws = _workspace(db_session, slug="bm25")
    collection = create_collection(db_session, workspace=ws, name="Manuals")
    job = create_worker_job(
        db_session,
        workspace_id=ws.id,
        collection_id=collection.id,
        kind="bm25_rebuild",
    )
    db_session.commit()

    class FakeDocumentService:
        def __init__(self, *args, **kwargs):
            self.vector_db = object()

    async def fake_rebuild_bm25_artifact(**kwargs):
        assert kwargs["force"] is True
        return {"status": "ready", "chunk_count": 75000, "forced": True}

    monkeypatch.setattr("app.services.worker_bm25.DocumentService", FakeDocumentService)
    monkeypatch.setattr(
        "app.services.worker_bm25.rebuild_bm25_artifact",
        fake_rebuild_bm25_artifact,
    )

    result = run_bm25_rebuild(job.id)

    db_session.expire_all()
    refreshed = db_session.query(WorkerJob).filter(WorkerJob.id == job.id).one()
    assert refreshed.status == "completed"
    assert refreshed.progress == 100
    assert refreshed.result["bm25"]["forced"] is True
    assert result["bm25"]["status"] == "ready"
