from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import documents
from app.core.config import settings
from app.models.knowledge_collection import KnowledgeCollection, WorkerJob
from app.models.workspace import Workspace
from app.services.knowledge_collections import create_collection
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
        classmethod(lambda cls, db_type="faiss", workspace_slug=None: []),
    )

    response = _client(db_session, ws).get("/documents/collections")

    assert response.status_code == 200
    body = response.json()
    assert body["collections"] == ["policies"]
    assert body["items"][0]["name"] == "Policies"
    assert body["items"][0]["status"] == "created"


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
