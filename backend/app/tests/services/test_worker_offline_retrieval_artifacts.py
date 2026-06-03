from __future__ import annotations

import json

from app.core.config import settings
from app.models.knowledge_collection import WorkerJob
from app.models.knowledge_document_fact import KnowledgeDocumentFact
from app.models.workspace import Workspace
from app.services.knowledge_collections import create_collection, create_worker_job, upsert_collection_source
from app.services.object_store import get_object_store
from app.services.rag.summary_artifacts import summary_index_jsonl_key, summary_index_manifest_key
from app.services.worker_offline_retrieval_artifacts import run_offline_retrieval_artifact_job


def test_summary_index_rebuild_writes_document_summary_artifact(db_session, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "store"))
    workspace = Workspace(id="ws-summary-artifact", name="Summary Artifact", slug="summary-artifact")
    db_session.add(workspace)
    db_session.commit()
    collection = create_collection(db_session, workspace=workspace, name="Dense Manuals")
    upsert_collection_source(
        db_session,
        collection=collection,
        filename="A__ACJ100__start_procedure.html",
        status="ready",
        chunk_count=42,
        source_metadata={"document_id": "doc-start", "project_code": "ACJ100", "archive_name": "A"},
    )
    db_session.add(
        KnowledgeDocumentFact(
            workspace_id=workspace.id,
            collection_id=collection.id,
            collection_slug=collection.slug,
            document_id="doc-start",
            document_filename="A__ACJ100__start_procedure.html",
            semantic_type="document_procedure_step",
            subject="start procedure",
            predicate="procedure_step",
            content="Verify safety interlocks before starting the machine.",
            section_path="I.1 Start",
            confidence=0.92,
        )
    )
    job = create_worker_job(
        db_session,
        workspace_id=workspace.id,
        collection_id=collection.id,
        kind="summary_index_rebuild",
    )
    db_session.commit()

    result = run_offline_retrieval_artifact_job(job.id)

    store = get_object_store()
    manifest = json.loads(store.read_bytes(summary_index_manifest_key(collection)).decode("utf-8"))
    rows = [
        json.loads(line)
        for line in store.read_bytes(summary_index_jsonl_key(collection)).decode("utf-8").splitlines()
        if line.strip()
    ]
    db_session.expire_all()
    refreshed = db_session.query(WorkerJob).filter(WorkerJob.id == job.id).one()
    assert refreshed.status == "completed"
    assert refreshed.progress == 100
    assert result["summary_index"]["status"] == "ready"
    assert result["summary_index"]["document_summaries"] == 1
    assert manifest["document_summaries"] == 1
    assert rows[0]["document_id"] == "doc-start"
    assert rows[0]["project_code"] == "ACJ100"
    assert rows[0]["facts_by_type"] == {"document_procedure_step": 1}
    assert "Verify safety interlocks" in rows[0]["summary_text"]


def test_sparse_offline_job_remains_manual_not_configured(db_session, monkeypatch):
    monkeypatch.setattr(settings, "rag_sparse_backend", "disabled")
    workspace = Workspace(id="ws-sparse-artifact", name="Sparse Artifact", slug="sparse-artifact")
    db_session.add(workspace)
    db_session.commit()
    collection = create_collection(db_session, workspace=workspace, name="Dense Manuals")
    job = create_worker_job(
        db_session,
        workspace_id=workspace.id,
        collection_id=collection.id,
        kind="sparse_index_rebuild",
    )
    db_session.commit()

    result = run_offline_retrieval_artifact_job(job.id)

    db_session.expire_all()
    refreshed = db_session.query(WorkerJob).filter(WorkerJob.id == job.id).one()
    assert refreshed.status == "completed"
    assert result["status"] == "skipped"
    assert result["configured"] is False
    assert result["stage"] == "not_configured"
    assert result["sparse_index"]["reason"] == "sparse_backend_not_opensearch"


def test_sparse_offline_job_indexes_summary_artifact_to_opensearch(db_session, tmp_path, monkeypatch):
    class FakeResponse:
        def __init__(self, payload=None, status_code=200):
            self._payload = payload or {}
            self.status_code = status_code

        def json(self):
            return self._payload

        def raise_for_status(self):
            if self.status_code >= 400:
                raise AssertionError(f"unexpected status {self.status_code}")

    class FakeClient:
        calls = []

        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def put(self, url, json):
            self.calls.append(("put", url, json))
            return FakeResponse()

        def post(self, url, content=None, headers=None, json=None):
            self.calls.append(("post", url, content, headers, json))
            return FakeResponse({"errors": False, "items": []})

    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "store"))
    monkeypatch.setattr(settings, "rag_sparse_backend", "opensearch")
    monkeypatch.setattr(settings, "rag_opensearch_url", "http://opensearch.test")
    monkeypatch.setattr("app.services.rag.opensearch_sparse_index.httpx.Client", FakeClient)

    workspace = Workspace(id="ws-sparse-artifact", name="Sparse Artifact", slug="sparse-artifact")
    db_session.add(workspace)
    db_session.commit()
    collection = create_collection(db_session, workspace=workspace, name="Dense Manuals")
    upsert_collection_source(
        db_session,
        collection=collection,
        filename="A__ACJ100__start_procedure.html",
        status="ready",
        chunk_count=42,
        source_metadata={"document_id": "doc-start", "project_code": "ACJ100", "archive_name": "A"},
    )
    db_session.add(
        KnowledgeDocumentFact(
            workspace_id=workspace.id,
            collection_id=collection.id,
            collection_slug=collection.slug,
            document_id="doc-start",
            document_filename="A__ACJ100__start_procedure.html",
            semantic_type="document_procedure_step",
            subject="start procedure",
            predicate="procedure_step",
            content="Verify safety interlocks before starting the machine.",
            section_path="I.1 Start",
            confidence=0.92,
        )
    )
    job = create_worker_job(
        db_session,
        workspace_id=workspace.id,
        collection_id=collection.id,
        kind="sparse_index_rebuild",
    )
    db_session.commit()

    result = run_offline_retrieval_artifact_job(job.id)

    db_session.expire_all()
    refreshed = db_session.query(WorkerJob).filter(WorkerJob.id == job.id).one()
    assert refreshed.status == "completed"
    assert refreshed.progress == 100
    assert result["status"] == "ready"
    assert result["configured"] is True
    assert result["stage"] == "sparse_ready"
    assert result["sparse_index"]["backend"] == "opensearch"
    assert result["sparse_index"]["documents_indexed"] == 1
    assert result["sparse_index"]["index_name"].startswith("agentium-rag-")
    put_call = next(call for call in FakeClient.calls if call[0] == "put")
    delete_call = next(call for call in FakeClient.calls if "_delete_by_query" in call[1])
    post_call = next(call for call in FakeClient.calls if call[1].endswith("/_bulk?refresh=true"))
    assert put_call[1].endswith(result["sparse_index"]["index_name"])
    assert delete_call[4] == {"query": {"term": {"collection": collection.slug}}}
    assert post_call[1].endswith("/_bulk?refresh=true")
    assert post_call[3] == {"Content-Type": "application/x-ndjson"}
    assert "Verify safety interlocks" in post_call[2]
    assert '"project_code": "ACJ100"' in post_call[2]
