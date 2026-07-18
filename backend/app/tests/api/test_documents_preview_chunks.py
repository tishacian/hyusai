from __future__ import annotations

import hashlib
import io
import zipfile
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import documents
from app.core.config import settings
from app.models.knowledge_collection import KnowledgeCollectionSource
from app.models.secure_deposit import DepositAccessLink, DepositFile
from app.models.user import User
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

    async def get_document_count(self):
        return len(getattr(self.vector_db, "_sample_rows", None) or getattr(self.vector_db, "_payloads", []))

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


def test_rich_preview_reads_no_copy_secure_deposit_source(
    db_session, tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "objects"))
    secure_root = tmp_path / "secure"
    monkeypatch.setattr(settings, "secure_deposit_storage_dir", str(secure_root))
    ws = Workspace(id="ws-preview-source", name="Preview source", slug="preview-source")
    user = User(id="user-preview-source", username="preview-source")
    db_session.add_all([ws, user])
    db_session.flush()
    collection = create_collection(db_session, workspace=ws, name="Manuals")
    link = DepositAccessLink(
        id="link-preview-source",
        workspace_id=ws.id,
        created_by_user_id=user.id,
        label="Needlepunch",
        access_id="preview-source",
        password_hash="hash",
        allowed_extensions=["txt"],
    )
    content = b"Needlepunch project 61035"
    object_key = "workspaces/ws-preview-source/secure-deposit/source/manual.txt"
    source_path = secure_root / object_key
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_bytes(content)
    deposit = DepositFile(
        id="deposit-preview-source",
        workspace_id=ws.id,
        access_link_id=link.id,
        filename="Notices_Techniques_Needlepunch/60000-69999/61035/manual.txt",
        object_key=object_key,
        size_bytes=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        status="promoted",
    )
    source = KnowledgeCollectionSource(
        id="source-preview-source",
        workspace_id=ws.id,
        collection_id=collection.id,
        filename="61035__manual.txt",
        normalized_name="61035__manual.txt",
        source_kind="document",
        status="ready",
        source_metadata={
            "document_id": "docN",
            "source_locator": {
                "kind": "secure_deposit_file",
                "deposit_file_id": deposit.id,
                "size_bytes": deposit.size_bytes,
                "sha256": deposit.sha256,
            },
        },
    )
    db_session.add_all([link, deposit, source])
    db_session.commit()

    _patch_doc_service(
        monkeypatch,
        FakeVectorDB([], [{"document_id": "docN", "filename": source.filename}]),
    )
    response = _client(db_session, ws).get(
        "/documents/docN/rich-preview", params={"collection_name": collection.slug}
    )

    assert response.status_code == 200
    assert response.json()["content"] == content.decode()

    monkeypatch.setattr(
        documents,
        "read_backing_source_bytes",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("raw governed delivery must stream from a file path")
        ),
    )
    raw = _client(db_session, ws).get(
        "/documents/docN/raw",
        params={"collection_name": collection.slug},
    )
    assert raw.status_code == 200
    assert raw.content == content
    assert raw.headers["content-disposition"] == 'inline; filename="61035__manual.txt"'


def test_governed_source_integrity_failure_never_falls_back_to_legacy_file(
    db_session, tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "objects"))
    secure_root = tmp_path / "secure"
    monkeypatch.setattr(settings, "secure_deposit_storage_dir", str(secure_root))
    ws = Workspace(id="ws-preview-closed", name="Preview closed", slug="preview-closed")
    user = User(id="user-preview-closed", username="preview-closed")
    db_session.add_all([ws, user])
    db_session.flush()
    collection = create_collection(db_session, workspace=ws, name="Governed source")
    link = DepositAccessLink(
        id="link-preview-closed",
        workspace_id=ws.id,
        created_by_user_id=user.id,
        label="Needlepunch",
        access_id="preview-closed",
        password_hash="hash",
        allowed_extensions=["txt"],
    )
    original = b"immutable content"
    tampered = b"tampered-content"
    object_key = "workspaces/ws-preview-closed/secure-deposit/source/manual.txt"
    source_path = secure_root / object_key
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_bytes(tampered)
    deposit = DepositFile(
        id="deposit-preview-closed",
        workspace_id=ws.id,
        access_link_id=link.id,
        filename="Notices_Techniques_Needlepunch/60000-69999/61035 A/manual.txt",
        object_key=object_key,
        size_bytes=len(tampered),
        sha256=hashlib.sha256(original).hexdigest(),
        status="promoted",
    )
    source = KnowledgeCollectionSource(
        id="source-preview-closed",
        workspace_id=ws.id,
        collection_id=collection.id,
        filename="61035__manual.txt",
        normalized_name="61035__manual.txt",
        source_kind="document",
        status="ready",
        source_metadata={
            "document_id": "docClosed",
            "source_locator": {
                "kind": "secure_deposit_file",
                "deposit_file_id": deposit.id,
                "size_bytes": deposit.size_bytes,
                "sha256": deposit.sha256,
            },
        },
    )
    db_session.add_all([link, deposit, source])
    db_session.commit()
    get_object_store().write_bytes(
        original_key(collection, source.filename),
        b"stale object-store shadow",
    )

    monkeypatch.setattr(
        documents,
        "_find_original_file",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("governed sources must never use legacy fallback")
        ),
    )
    _patch_doc_service(
        monkeypatch,
        FakeVectorDB([], [{"document_id": "docClosed", "filename": source.filename}]),
    )

    response = _client(db_session, ws).get(
        "/documents/docClosed/raw",
        params={"collection_name": collection.slug},
    )

    assert response.status_code == 404


def test_preview_and_download_read_no_copy_secure_deposit_zip_member(
    db_session, tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "objects"))
    secure_root = tmp_path / "secure"
    monkeypatch.setattr(settings, "secure_deposit_storage_dir", str(secure_root))
    ws = Workspace(id="ws-preview-zip", name="Preview zip", slug="preview-zip")
    user = User(id="user-preview-zip", username="preview-zip")
    db_session.add_all([ws, user])
    db_session.flush()
    collection = create_collection(db_session, workspace=ws, name="Needlepunch ZIP")
    link = DepositAccessLink(
        id="link-preview-zip",
        workspace_id=ws.id,
        created_by_user_id=user.id,
        label="Needlepunch ZIP",
        access_id="preview-zip",
        password_hash="hash",
        allowed_extensions=["zip"],
    )
    member_content = b"Needlepunch project 61038 from archive"
    archive_buffer = io.BytesIO()
    with zipfile.ZipFile(archive_buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manual/chapter.txt", member_content)
    archive_bytes = archive_buffer.getvalue()
    object_key = "workspaces/ws-preview-zip/secure-deposit/source/manuals.zip"
    source_path = secure_root / object_key
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_bytes(archive_bytes)
    deposit = DepositFile(
        id="deposit-preview-zip",
        workspace_id=ws.id,
        access_link_id=link.id,
        filename=(
            "Notices_Techniques_Needlepunch/60000-69999/"
            "61038 Customer/manuals.zip"
        ),
        object_key=object_key,
        size_bytes=len(archive_bytes),
        sha256=hashlib.sha256(archive_bytes).hexdigest(),
        status="promoted",
    )
    source = KnowledgeCollectionSource(
        id="source-preview-zip",
        workspace_id=ws.id,
        collection_id=collection.id,
        filename="61038__chapter.txt",
        normalized_name="61038__chapter.txt",
        source_kind="document",
        status="ready",
        source_metadata={
            "document_id": "docZip",
            "project_code": "61038",
            "source_locator": {
                "kind": "secure_deposit_zip_member",
                "deposit_file_id": deposit.id,
                "size_bytes": deposit.size_bytes,
                "sha256": deposit.sha256,
                "member_path": "manual/chapter.txt",
                "member_size_bytes": len(member_content),
                "member_sha256": hashlib.sha256(member_content).hexdigest(),
            },
        },
    )
    db_session.add_all([link, deposit, source])
    db_session.commit()

    _patch_doc_service(
        monkeypatch,
        FakeVectorDB([], [{"document_id": "docZip", "filename": source.filename}]),
    )
    client = _client(db_session, ws)
    preview = client.get(
        "/documents/docZip/rich-preview",
        params={"collection_name": collection.slug},
    )
    monkeypatch.setattr(
        documents,
        "read_backing_source_bytes",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("ZIP raw delivery must stream its bounded temp file")
        ),
    )
    raw = client.get(
        "/documents/docZip/raw",
        params={"collection_name": collection.slug},
    )

    assert preview.status_code == 200
    assert preview.json()["content"] == member_content.decode()
    assert raw.status_code == 200
    assert raw.content == member_content


def test_pdf_and_legacy_doc_previews_use_no_copy_sources(
    db_session, tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "objects"))
    secure_root = tmp_path / "secure"
    monkeypatch.setattr(settings, "secure_deposit_storage_dir", str(secure_root))
    ws = Workspace(id="ws-preview-formats", name="Preview formats", slug="preview-formats")
    user = User(id="user-preview-formats", username="preview-formats")
    db_session.add_all([ws, user])
    db_session.flush()
    collection = create_collection(db_session, workspace=ws, name="Needlepunch formats")
    link = DepositAccessLink(
        id="link-preview-formats",
        workspace_id=ws.id,
        created_by_user_id=user.id,
        label="Needlepunch formats",
        access_id="preview-formats",
        password_hash="hash",
        allowed_extensions=["pdf", "doc"],
    )
    db_session.add(link)
    documents_by_id: list[dict[str, str]] = []
    expected_by_id = {
        "docPdf": ("61001__manual.pdf", b"%PDF-1.4\nneedlepunch\n"),
        "docLegacy": ("61001__legacy.doc", b"legacy-word-content"),
    }
    for index, (document_id, (filename, content)) in enumerate(expected_by_id.items(), 1):
        object_key = f"workspaces/{ws.id}/secure-deposit/source/source-{index}"
        source_path = secure_root / object_key
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_bytes(content)
        deposit = DepositFile(
            id=f"deposit-preview-format-{index}",
            workspace_id=ws.id,
            access_link_id=link.id,
            filename=(
                "Notices_Techniques_Needlepunch/60000-69999/"
                f"61001 Customer/{filename}"
            ),
            object_key=object_key,
            size_bytes=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
            status="promoted",
        )
        source = KnowledgeCollectionSource(
            id=f"source-preview-format-{index}",
            workspace_id=ws.id,
            collection_id=collection.id,
            filename=filename,
            normalized_name=filename,
            source_kind="document",
            status="ready",
            source_metadata={
                "document_id": document_id,
                "project_code": "61001",
                "source_locator": {
                    "kind": "secure_deposit_file",
                    "deposit_file_id": deposit.id,
                    "size_bytes": deposit.size_bytes,
                    "sha256": deposit.sha256,
                },
            },
        )
        db_session.add_all([deposit, source])
        documents_by_id.append({"document_id": document_id, "filename": filename})
    db_session.commit()

    conversion_calls: list[tuple[bytes, str]] = []

    def _fake_office_conversion(source_path, filename: str):
        conversion_calls.append((source_path.read_bytes(), filename))
        converted = source_path.with_suffix(".pdf")
        converted.write_bytes(b"%PDF-converted")
        return converted

    monkeypatch.setattr(documents, "_office_preview_pdf_file", _fake_office_conversion)
    _patch_doc_service(monkeypatch, FakeVectorDB([], documents_by_id))
    client = _client(db_session, ws)

    pdf_preview = client.get(
        "/documents/docPdf/rich-preview",
        params={"collection_name": collection.slug},
    )
    pdf_raw = client.get(
        "/documents/docPdf/raw",
        params={"collection_name": collection.slug},
    )
    doc_preview = client.get(
        "/documents/docLegacy/rich-preview",
        params={"collection_name": collection.slug},
    )
    doc_converted = client.get(
        "/documents/docLegacy/converted-preview",
        params={"collection_name": collection.slug},
    )

    assert pdf_preview.status_code == 200
    assert pdf_preview.json()["kind"] == "pdf"
    assert pdf_raw.content == expected_by_id["docPdf"][1]
    assert doc_preview.status_code == 200
    assert doc_preview.json()["kind"] == "pdf"
    assert "/converted-preview" in doc_preview.json()["download_url"]
    assert doc_converted.status_code == 200
    assert doc_converted.content == b"%PDF-converted"
    assert conversion_calls == [
        (expected_by_id["docLegacy"][1], expected_by_id["docLegacy"][0])
    ]


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
