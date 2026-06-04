from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import documents
from app.core.config import settings
from app.models.workspace import Workspace
from app.services.knowledge_collections import create_collection, original_key
from app.services.object_store import get_object_store


def _client(db_session, workspace: Workspace) -> TestClient:
    app = FastAPI()
    app.include_router(documents.router, prefix="/documents")
    app.dependency_overrides[documents.get_current_workspace] = lambda: workspace
    app.dependency_overrides[documents.get_current_user] = lambda: SimpleNamespace(id="user-1")
    app.dependency_overrides[documents.get_db] = lambda: db_session
    return TestClient(app)


class FakeVectorDB:
    def __init__(self, payloads, docs, sample_rows=None):
        self._payloads = payloads
        self._docs = docs
        self._sample_rows = sample_rows or []

    async def list_payloads(self, filters=None, limit=100, offset=0):
        rows = self._payloads
        if filters:
            rows = [p for p in rows if all(p.get(k) == v for k, v in filters.items())]
        return rows[offset : offset + limit]

    async def list_documents(self):
        return list(self._docs)

    async def get_by_document_id(self, document_id):
        return [p for p in self._payloads if p.get("document_id") == document_id]

    async def sample_chunk_vectors(self, limit=200, filters=None):
        rows = self._sample_rows
        if filters:
            rows = [
                r
                for r in rows
                if all(r.get("payload", {}).get(k) == v for k, v in filters.items())
            ]
        return rows[:limit]


class FakeDocService:
    def __init__(self, vector_db):
        self.vector_db = vector_db

    async def list_documents(self):
        out = []
        for doc in await self.vector_db.list_documents():
            row = dict(doc)
            chunks = await self.vector_db.get_by_document_id(row.get("document_id"))
            row.setdefault("chunk_count", len(chunks))
            out.append(row)
        return out


def _patch_doc_service(monkeypatch, vector_db):
    monkeypatch.setattr(documents, "DocumentService", lambda **kwargs: FakeDocService(vector_db))


def test_list_document_chunks_truncates_and_filters(db_session, monkeypatch):
    ws = Workspace(id="ws-chunks", name="Chunks", slug="chunks")
    db_session.add(ws)
    db_session.commit()

    payloads = [
        {
            "point_id": "p1",
            "document_id": "d1",
            "document_filename": "a.txt",
            "chunk_index": 0,
            "section_path": "S1",
            "content": "x" * 1000,
        },
        {
            "point_id": "p2",
            "document_id": "d2",
            "document_filename": "b.txt",
            "chunk_index": 0,
            "content": "short",
        },
    ]
    _patch_doc_service(monkeypatch, FakeVectorDB(payloads, []))

    resp = _client(db_session, ws).get(
        "/documents/chunks", params={"collection_name": "col", "max_chars": 100}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 2
    first = body["chunks"][0]
    assert first["content_length"] == 1000
    assert len(first["content"]) == 100
    assert first["truncated"] is True
    assert first["section_path"] == "S1"

    resp_filtered = _client(db_session, ws).get(
        "/documents/chunks", params={"collection_name": "col", "document_id": "d2"}
    )
    filtered = resp_filtered.json()
    assert filtered["count"] == 1
    assert filtered["chunks"][0]["document_id"] == "d2"
    assert filtered["chunks"][0]["truncated"] is False


def test_rich_preview_reads_original_from_object_store(db_session, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "objects"))
    ws = Workspace(id="ws-preview", name="Preview", slug="preview")
    db_session.add(ws)
    db_session.commit()
    collection = create_collection(db_session, workspace=ws, name="Manuals")
    db_session.commit()

    get_object_store().write_bytes(original_key(collection, "note.txt"), b"hello world")
    _patch_doc_service(
        monkeypatch,
        FakeVectorDB([], [{"document_id": "docA", "filename": "note.txt"}]),
    )

    resp = _client(db_session, ws).get(
        "/documents/docA/rich-preview", params={"collection_name": collection.slug}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["kind"] == "text"
    assert body["content"] == "hello world"
    assert body["filename"] == "note.txt"
    assert "/raw" in body["download_url"]


def test_rich_preview_missing_original_returns_404(db_session, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "objects"))
    ws = Workspace(id="ws-preview2", name="Preview2", slug="preview2")
    db_session.add(ws)
    db_session.commit()
    create_collection(db_session, workspace=ws, name="Manuals")
    db_session.commit()

    _patch_doc_service(
        monkeypatch,
        FakeVectorDB([], [{"document_id": "ghost", "filename": "missing.txt"}]),
    )

    resp = _client(db_session, ws).get(
        "/documents/ghost/rich-preview", params={"collection_name": "manuals"}
    )
    assert resp.status_code == 404


def test_embedding_graph_returns_nodes_and_edges(db_session, monkeypatch):
    ws = Workspace(id="ws-graph", name="Graph", slug="graph")
    db_session.add(ws)
    db_session.commit()

    # Two tight clusters so similarity edges are deterministic.
    sample_rows = [
        {"id": "p1", "vector": [1.0, 0.0, 0.0], "payload": {"document_id": "d1", "document_filename": "a.txt", "chunk_index": 0, "content": "alpha"}},
        {"id": "p2", "vector": [0.98, 0.02, 0.0], "payload": {"document_id": "d1", "document_filename": "a.txt", "chunk_index": 1, "content": "alpha2"}},
        {"id": "p3", "vector": [0.0, 1.0, 0.0], "payload": {"document_id": "d2", "document_filename": "b.txt", "chunk_index": 0, "content": "beta"}},
        {"id": "p4", "vector": [0.0, 0.97, 0.05], "payload": {"document_id": "d2", "document_filename": "b.txt", "chunk_index": 1, "content": "beta2"}},
    ]
    _patch_doc_service(monkeypatch, FakeVectorDB([], [], sample_rows=sample_rows))

    resp = _client(db_session, ws).get(
        "/documents/graph",
        params={"collection_name": "col", "sample": 50, "neighbors": 1, "min_score": 0.5},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["sample"] == 4
    assert body["vector_dim"] == 3
    assert len(body["nodes"]) == 4
    for node in body["nodes"]:
        assert 0.0 <= node["x"] <= 1.0
        assert 0.0 <= node["y"] <= 1.0
    assert len(body["edges"]) >= 2
    # The two alpha vectors (indices 0,1) should be connected.
    pairs = {(e["source"], e["target"]) for e in body["edges"]}
    assert (0, 1) in pairs


def test_embedding_graph_empty_collection(db_session, monkeypatch):
    ws = Workspace(id="ws-graph-empty", name="GraphE", slug="graphe")
    db_session.add(ws)
    db_session.commit()
    _patch_doc_service(monkeypatch, FakeVectorDB([], [], sample_rows=[]))

    resp = _client(db_session, ws).get(
        "/documents/graph", params={"collection_name": "col"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["sample"] == 0
    assert body["nodes"] == []
    assert body["edges"] == []


def test_serve_document_raw_streams_bytes(db_session, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "objects"))
    ws = Workspace(id="ws-raw", name="Raw", slug="raw")
    db_session.add(ws)
    db_session.commit()
    collection = create_collection(db_session, workspace=ws, name="Manuals")
    db_session.commit()

    get_object_store().write_bytes(original_key(collection, "note.txt"), b"raw-bytes")
    _patch_doc_service(
        monkeypatch,
        FakeVectorDB([], [{"document_id": "docR", "filename": "note.txt"}]),
    )

    resp = _client(db_session, ws).get(
        "/documents/docR/raw", params={"collection_name": collection.slug}
    )
    assert resp.status_code == 200
    assert resp.content == b"raw-bytes"
    assert "inline" in resp.headers.get("content-disposition", "")
