"""L36 — the cited passage behind the Work source panel."""

from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import document_passages, documents
from app.core.config import settings
from app.models.workspace import Workspace, WorkspaceMember
from app.services.knowledge_collections import create_collection, original_key
from app.services.object_store import get_object_store


def _client(db_session, workspace: Workspace) -> TestClient:
    app = FastAPI()
    app.include_router(document_passages.router, prefix="/documents")
    app.dependency_overrides[document_passages.get_current_workspace] = lambda: workspace
    app.dependency_overrides[document_passages.get_current_user] = lambda: SimpleNamespace(id="user-1")
    app.dependency_overrides[document_passages.get_db] = lambda: db_session
    return TestClient(app)


class FakeVectorDB:
    """Equality filters only, like the simplest store: a list filter matches nothing."""

    def __init__(self, payloads, docs, fail=False):
        self._payloads = payloads
        self._docs = docs
        self._fail = fail
        self.calls: list[dict] = []

    async def list_payloads(self, filters=None, limit=100, offset=0):
        self.calls.append(dict(filters or {}))
        if self._fail:
            raise RuntimeError("vector store down")
        rows = self._payloads
        if filters:
            rows = [p for p in rows if all(p.get(k) == v for k, v in filters.items())]
        return rows[offset : offset + limit]

    async def list_documents(self):
        return list(self._docs)


class FakeDocService:
    def __init__(self, vector_db):
        self.vector_db = vector_db

    async def list_documents(self):
        return await self.vector_db.list_documents()


def _patch(monkeypatch, vector_db):
    monkeypatch.setattr(documents, "DocumentService", lambda **kwargs: FakeDocService(vector_db))


def _workspace(db_session, slug: str) -> Workspace:
    ws = Workspace(id=f"ws-{slug}", name=slug, slug=slug)
    db_session.add(ws)
    # The reader is a plain member: open collections are read by members only (L35).
    db_session.add(
        WorkspaceMember(
            user_id="user-1", workspace_id=ws.id, role="member", role_template="workspace_contributor"
        )
    )
    db_session.commit()
    return ws


CHUNKS = [
    {"document_id": "doc-atex", "chunk_index": 2, "page": 2, "content": "2.9 Les fournisseurs sont référencés par le service achats."},
    {
        "document_id": "doc-atex",
        "chunk_index": 3,
        "page": 3,
        # Starts with the end of chunk 2: the chunker overlaps neighbours.
        "content": "par le service achats. 3.1 Tout dépassement du plafond exige la validation écrite de l’acheteur.",
    },
    {"document_id": "doc-atex", "chunk_index": 4, "page": 3, "content": "3.2 La validation est archivée avec la commande."},
    {"document_id": "doc-other", "chunk_index": 3, "page": 1, "content": "Autre document."},
]


def test_passage_in_full_with_neighbours_collection_and_preview(db_session, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "objects"))
    ws = _workspace(db_session, "passage")
    collection = create_collection(db_session, workspace=ws, name="Contrats fournisseurs")
    db_session.commit()
    get_object_store().write_bytes(original_key(collection, "atex.pdf"), b"%PDF-1.4")
    vector_db = FakeVectorDB(CHUNKS, [{"document_id": "doc-atex", "filename": "atex.pdf"}])
    _patch(monkeypatch, vector_db)

    resp = _client(db_session, ws).get(
        "/documents/doc-atex/passage",
        params={"collection_name": collection.slug, "chunk_index": 3, "page": 3},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["filename"] == "atex.pdf"
    assert body["collection"] == {"id": collection.id, "slug": collection.slug, "name": "Contrats fournisseurs"}
    assert body["passage"]["text"].startswith("par le service achats. 3.1 Tout dépassement")
    assert body["passage"]["chunk_index"] == 3
    assert body["passage"]["page"] == 3
    assert body["passage"]["truncated"] is False
    # The overlap is not repeated before the passage.
    assert body["before"] == "2.9 Les fournisseurs sont référencés"
    assert body["after"] == "3.2 La validation est archivée avec la commande."
    assert body["preview_available"] is True
    # The neighbour query came first; this store could not answer it.
    assert vector_db.calls[0] == {"document_id": "doc-atex", "chunk_index": [2, 3, 4]}


def test_passage_found_by_the_quoted_text_without_chunk_index(db_session, monkeypatch):
    ws = _workspace(db_session, "passage-hint")
    create_collection(db_session, workspace=ws, name="Contrats fournisseurs")
    db_session.commit()
    _patch(monkeypatch, FakeVectorDB(CHUNKS, [{"document_id": "doc-atex", "filename": "atex.pdf"}]))

    resp = _client(db_session, ws).get(
        "/documents/doc-atex/passage",
        params={"collection_name": "contrats-fournisseurs", "hint": "3.2  La VALIDATION est archivée"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["passage"]["chunk_index"] == 4
    assert body["after"] is None
    # No original stored: the panel falls back to the text, it does not promise a page.
    assert body["preview_available"] is False


def test_a_deleted_document_is_not_readable(db_session, monkeypatch):
    ws = _workspace(db_session, "passage-gone")
    create_collection(db_session, workspace=ws, name="Contrats fournisseurs")
    db_session.commit()
    _patch(monkeypatch, FakeVectorDB(CHUNKS, []))

    resp = _client(db_session, ws).get(
        "/documents/doc-atex/passage",
        params={"collection_name": "contrats-fournisseurs", "chunk_index": 3},
    )

    assert resp.status_code == 404


def test_a_failing_index_still_answers_without_a_passage(db_session, monkeypatch):
    ws = _workspace(db_session, "passage-down")
    create_collection(db_session, workspace=ws, name="Contrats fournisseurs")
    db_session.commit()
    _patch(monkeypatch, FakeVectorDB([], [{"document_id": "doc-atex", "filename": "atex.pdf"}], fail=True))

    resp = _client(db_session, ws).get(
        "/documents/doc-atex/passage",
        params={"collection_name": "contrats-fournisseurs", "chunk_index": 3},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["passage"] is None
    assert body["before"] is None and body["after"] is None


def test_the_collection_gate_is_the_single_access_hook(db_session, monkeypatch):
    ws = _workspace(db_session, "passage-gate")
    create_collection(db_session, workspace=ws, name="Contrats fournisseurs")
    db_session.commit()
    _patch(monkeypatch, FakeVectorDB(CHUNKS, [{"document_id": "doc-atex", "filename": "atex.pdf"}]))
    seen: list[str] = []

    def deny(db, *, workspace, user, collection_ref):
        seen.append(collection_ref)
        raise documents.HTTPException(status_code=404, detail="Collection not found")

    monkeypatch.setattr(document_passages, "readable_collection", deny)

    resp = _client(db_session, ws).get(
        "/documents/doc-atex/passage",
        params={"collection_name": "contrats-fournisseurs", "chunk_index": 3},
    )

    assert resp.status_code == 404
    assert seen == ["contrats-fournisseurs"]


def test_a_restricted_collection_reads_like_a_deleted_source(db_session, monkeypatch):
    ws = _workspace(db_session, "passage-restricted")
    collection = create_collection(db_session, workspace=ws, name="Contrats fournisseurs")
    collection.access = {"read": ["role:workspace_admin"], "write": ["role:workspace_admin"]}
    db_session.commit()
    vector_db = FakeVectorDB(CHUNKS, [{"document_id": "doc-atex", "filename": "atex.pdf"}])
    _patch(monkeypatch, vector_db)

    resp = _client(db_session, ws).get(
        "/documents/doc-atex/passage",
        params={"collection_name": "contrats-fournisseurs", "chunk_index": 3},
    )

    # Same answer as a missing collection, and the store is never read.
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Collection not found"
    assert "3.1 Tout dépassement" not in resp.text
    assert vector_db.calls == []
