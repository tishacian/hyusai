from __future__ import annotations

import asyncio
from types import SimpleNamespace

import numpy as np
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import documents
from app.core.config import settings
from app.models.knowledge_collection import (
    KnowledgeCollection,
    KnowledgeCollectionSource,
    WorkerJob,
)
from app.models.knowledge_document_fact import KnowledgeDocumentFact
from app.models.knowledge_table_fact import KnowledgeTableFact
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services.knowledge_collections import create_collection, create_worker_job
from app.services.object_store import get_object_store


def _client(db_session, workspace: Workspace) -> TestClient:
    if db_session.query(User).filter_by(id="user-1").first() is None:
        db_session.add(User(id="user-1", username="user-1", email="user-1@example.test"))
    if (
        db_session.query(WorkspaceMember)
        .filter_by(user_id="user-1", workspace_id=workspace.id)
        .first()
        is None
    ):
        db_session.add(
            WorkspaceMember(
                user_id="user-1",
                workspace_id=workspace.id,
                role="admin",
                role_template="workspace_admin",
            )
        )
        db_session.commit()
    app = FastAPI()
    app.include_router(documents.router, prefix="/documents")
    app.dependency_overrides[documents.get_current_workspace] = lambda: workspace
    app.dependency_overrides[documents.get_current_user] = lambda: SimpleNamespace(id="user-1")
    app.dependency_overrides[documents.get_db] = lambda: db_session
    return TestClient(app)


def _seed_workspace_user(
    db_session, workspace: Workspace, *, role: str, role_template: str | None = None
) -> User:
    user = User(
        id="user-1", username=f"user-{workspace.slug}", email=f"user-{workspace.slug}@example.test"
    )
    db_session.add(user)
    db_session.add(
        WorkspaceMember(
            user_id=user.id,
            workspace_id=workspace.id,
            role=role,
            role_template=role_template,
        )
    )
    db_session.commit()
    return user


def test_collection_model_activation_preserves_named_hub_refusal(db_session, monkeypatch):
    from app.services.huggingface.errors import HFError

    workspace = Workspace(id="ws-hf-denied", name="HF denied", slug="hf-denied")
    db_session.add(workspace)
    db_session.commit()
    collection = create_collection(db_session, workspace=workspace, name="Manuals")
    db_session.commit()

    def denied(*args, **kwargs):
        raise HFError("HF_ACCESS_REVOKED", "The workspace authorization was withdrawn.", 403)

    monkeypatch.setattr("app.services.huggingface.registry.require_artifact", denied)
    client = _client(db_session, workspace)
    for suffix in ("embedding/reindex", "reranker"):
        response = client.post(
            f"/documents/collections/{collection.id}/{suffix}", json={"artifact_id": "revoked"}
        )
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "HF_ACCESS_REVOKED"
    assert db_session.query(WorkerJob).filter_by(collection_id=collection.id).count() == 0


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


def test_list_collections_handles_large_workspace_list_without_cross_workspace_leak(
    db_session,
    monkeypatch,
):
    ws = Workspace(id="ws-api-large", name="API Large", slug="api-large")
    other_ws = Workspace(id="ws-api-other", name="API Other", slug="api-other")
    db_session.add_all([ws, other_ws])
    db_session.commit()

    for index in range(120):
        collection = create_collection(
            db_session,
            workspace=ws,
            name=f"Manuals {index:03d}",
            slug=f"manuals-{index:03d}",
        )
        collection.document_count = index % 5
        collection.chunk_count = index * 2
    create_collection(
        db_session, workspace=other_ws, name="Other Workspace Secret", slug="other-secret"
    )
    db_session.commit()

    captured: dict[str, str | None] = {}

    def fake_legacy(cls, db_type="qdrant", workspace_slug=None):
        captured["workspace_slug"] = workspace_slug
        return ["manuals-000", "_internal", "legacy-extra"]

    monkeypatch.setattr(
        "app.services.vector_db.factory.VectorDBFactory.list_collections_for_workspace",
        classmethod(fake_legacy),
    )

    response = _client(db_session, ws).get("/documents/collections")

    assert response.status_code == 200
    body = response.json()
    assert captured["workspace_slug"] == ws.slug
    assert len(body["items"]) == 120
    assert len(body["collections"]) == 121
    assert body["collections"][0] == "manuals-119"
    assert body["default"] == "manuals-119"
    assert body["collections"].count("manuals-000") == 1
    assert "legacy-extra" in body["collections"]
    assert "_internal" not in body["collections"]
    assert "other-secret" not in body["collections"]
    assert all("document_names" not in item for item in body["items"])
    assert body["items"][0]["slug"] == "manuals-119"
    assert body["items"][0]["document_count"] == 119 % 5
    assert body["items"][0]["chunk_count"] == 119 * 2


def test_collection_patch_denies_non_admin_without_mutating_metadata(db_session):
    ws = Workspace(id="ws-patch-denied", name="Patch Denied", slug="patch-denied")
    db_session.add(ws)
    db_session.commit()
    collection = create_collection(db_session, workspace=ws, name="Manuals")
    collection.description = "Original description"
    db_session.commit()
    _seed_workspace_user(
        db_session,
        ws,
        role="member",
        role_template="workspace_contributor",
    )

    response = _client(db_session, ws).patch(
        f"/documents/collections/{collection.id}",
        json={"name": "Changed", "description": "Changed description"},
    )

    assert response.status_code == 403
    db_session.refresh(collection)
    assert collection.name == "Manuals"
    assert collection.description == "Original description"


def test_collection_patch_updates_only_presentation_fields(db_session, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "objects"))
    ws = Workspace(id="ws-patch-admin", name="Patch Admin", slug="patch-admin")
    db_session.add(ws)
    db_session.commit()
    _seed_workspace_user(
        db_session,
        ws,
        role="admin",
        role_template="workspace_admin",
    )
    collection = create_collection(
        db_session,
        workspace=ws,
        name="Legacy pilot name",
        description="Legacy pilot description",
        slug="andritz-notices-techniques-spl-pilot",
    )
    collection.document_count = 12
    collection.chunk_count = 345
    db_session.commit()
    immutable = {
        "id": collection.id,
        "slug": collection.slug,
        "vector_collection_name": collection.vector_collection_name,
        "artifact_prefix": collection.artifact_prefix,
        "document_count": collection.document_count,
        "chunk_count": collection.chunk_count,
    }

    class FakeVectorDB:
        async def get_count(self):
            return immutable["chunk_count"]

    monkeypatch.setattr(
        "app.services.vector_db.factory.VectorDBFactory.get_db",
        classmethod(lambda cls, *args, **kwargs: FakeVectorDB()),
    )

    response = _client(db_session, ws).patch(
        f"/documents/collections/{collection.id}",
        json={
            "name": "ANDRITZ — Documentation technique transverse",
            "description": (
                "Notices techniques et documents projet transverses — SPL, "
                "Needlepunch et futurs périmètres."
            ),
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "ANDRITZ — Documentation technique transverse"
    assert body["description"].endswith("SPL, Needlepunch et futurs périmètres.")
    for field, value in immutable.items():
        assert body[field] == value

    db_session.refresh(collection)
    assert collection.name == body["name"]
    assert collection.description == body["description"]
    for field, value in immutable.items():
        assert getattr(collection, field) == value


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


def test_collection_inventory_rejects_invalid_pagination_without_loading_sources(db_session):
    ws = Workspace(id="ws-inventory-invalid", name="Inventory Invalid", slug="inventory-invalid")
    db_session.add(ws)
    db_session.commit()
    collection = create_collection(db_session, workspace=ws, name="Manuals")

    negative_offset = _client(db_session, ws).get(
        f"/documents/collections/{collection.id}/inventory?source_offset=-1"
    )
    excessive_limit = _client(db_session, ws).get(
        f"/documents/collections/{collection.id}/inventory?source_limit=1001"
    )

    assert negative_offset.status_code == 422
    assert excessive_limit.status_code == 422
    assert "sources" not in negative_offset.text
    assert "sources" not in excessive_limit.text


def test_empty_collection_inventory_and_diagnostics_stay_zero_when_vector_unavailable(
    db_session,
    monkeypatch,
):
    ws = Workspace(id="ws-empty-collection", name="Empty Collection", slug="empty-collection")
    db_session.add(ws)
    db_session.commit()
    collection = create_collection(db_session, workspace=ws, name="Empty Manuals")
    db_session.commit()

    inventory_response = _client(db_session, ws).get(
        f"/documents/collections/{collection.id}/inventory"
    )

    assert inventory_response.status_code == 200
    inventory = inventory_response.json()
    assert inventory["source_count"] == 0
    assert inventory["sources_total"] == 0
    assert inventory["document_count"] == 0
    assert inventory["chunk_count"] == 0
    assert inventory["sources"] == []
    assert inventory["sources_returned"] == 0
    assert inventory["sources_has_more"] is False
    assert inventory["by_kind"] == {}
    assert inventory["by_extension"] == {}
    assert inventory["by_status"] == {}
    assert inventory["top_sources"] == []
    assert inventory["zero_chunk_sources"] == 0
    assert inventory["error_sources"] == 0
    assert inventory["heavy_sources"] == 0
    assert inventory["chunk_percentiles"] == {"p50": 0, "p90": 0, "p95": 0, "p99": 0}

    class UnavailableDocumentService:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("vector store unavailable")

    monkeypatch.setattr(documents, "DocumentService", UnavailableDocumentService)

    diagnostics_response = _client(db_session, ws).get(
        f"/documents/collections/{collection.id}/diagnostics"
    )

    assert diagnostics_response.status_code == 200
    diagnostics = diagnostics_response.json()
    assert diagnostics["ledger_source_count"] == 0
    assert diagnostics["ledger_document_count"] == 0
    assert diagnostics["ledger_chunk_sum"] == 0
    assert diagnostics["vector_points"] is None
    assert diagnostics["drift"] is None
    assert diagnostics["drift_status"] == "unknown"
    assert diagnostics["dense"] is False
    assert diagnostics["top_sources"] == []
    assert diagnostics["zero_chunk_sources"] == 0
    assert diagnostics["error_sources"] == 0
    assert diagnostics["heavy_sources"] == 0
    assert diagnostics["document_facts"] == {
        "total": 0,
        "by_type": {},
        "docs_by_document_type": {},
    }
    assert diagnostics["table_facts"] == {"total": 0, "by_type": {}}
    assert diagnostics["feature_status"]["document_facts"]["state"] == "empty"
    assert diagnostics["feature_status"]["ocr"]["state"] == "empty"
    assert diagnostics["feature_status"]["table_facts"]["state"] == "empty"
    assert diagnostics["feature_status"]["graph"]["state"] == "disabled"


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
    assert [source["filename"] for source in body["sources"]] == [
        "manual-large.pdf",
        "manual-small.pdf",
    ]

    scoped_response = _client(db_session, ws).get(
        f"/documents/collections/{collection.slug}/inventory?project_code=ACJ100"
    )
    assert scoped_response.status_code == 200
    scoped_body = scoped_response.json()
    assert scoped_body["source_count"] == 3
    assert scoped_body["sources_total"] == 1
    assert scoped_body["source_filters"]["project_code"] == "ACJ100"
    assert [source["filename"] for source in scoped_body["sources"]] == ["manual-small.pdf"]


def test_collection_inventory_numeric5_project_scope_is_exact_and_source_aware(
    db_session,
):
    ws = Workspace(
        id="ws-inventory-numeric5",
        name="Inventory Numeric5",
        slug="inventory-numeric5",
    )
    db_session.add(ws)
    db_session.commit()
    collection = create_collection(db_session, workspace=ws, name="Transverse Manuals")
    db_session.add_all(
        [
            KnowledgeCollectionSource(
                workspace_id=ws.id,
                collection_id=collection.id,
                filename="opaque-needlepunch-manual.pdf",
                normalized_name="opaque-needlepunch-manual.pdf",
                source_kind="pdf",
                extension="pdf",
                status="ready",
                source_metadata={
                    "project_code": "61035",
                    "project_code_scheme": "needlepunch_numeric5",
                    "business_scope": "needlepunch",
                },
            ),
            KnowledgeCollectionSource(
                workspace_id=ws.id,
                collection_id=collection.id,
                filename="spare-part-1298561035.pdf",
                normalized_name="spare-part-1298561035.pdf",
                source_kind="pdf",
                extension="pdf",
                status="ready",
                source_metadata={
                    "project_code": "61001",
                    "project_code_scheme": "needlepunch_numeric5",
                    "business_scope": "needlepunch",
                },
            ),
            KnowledgeCollectionSource(
                workspace_id=ws.id,
                collection_id=collection.id,
                filename="unscoped-61035-manual.pdf",
                normalized_name="unscoped-61035-manual.pdf",
                source_kind="pdf",
                extension="pdf",
                status="ready",
            ),
            KnowledgeCollectionSource(
                workspace_id=ws.id,
                collection_id=collection.id,
                filename="A__BCX200__manual.html",
                normalized_name="A__BCX200__manual.html",
                source_kind="markup",
                extension="html",
                status="ready",
            ),
            KnowledgeCollectionSource(
                workspace_id=ws.id,
                collection_id=collection.id,
                filename="A__BCX200__wrong-project.html",
                normalized_name="A__BCX200__wrong-project.html",
                source_kind="markup",
                extension="html",
                status="ready",
                source_metadata={"project_code": "ZZZ900"},
            ),
        ]
    )
    db_session.commit()

    numeric_response = _client(db_session, ws).get(
        f"/documents/collections/{collection.slug}/inventory?project_code=61035"
    )
    assert numeric_response.status_code == 200
    numeric_body = numeric_response.json()
    assert numeric_body["sources_total"] == 1
    assert [source["filename"] for source in numeric_body["sources"]] == [
        "opaque-needlepunch-manual.pdf"
    ]

    legacy_response = _client(db_session, ws).get(
        f"/documents/collections/{collection.slug}/inventory?project_code=BCX200"
    )
    assert legacy_response.status_code == 200
    assert [source["filename"] for source in legacy_response.json()["sources"]] == [
        "A__BCX200__manual.html"
    ]

    generic_response = _client(db_session, ws).get(
        f"/documents/collections/{collection.slug}/inventory?q=61035"
    )
    assert generic_response.status_code == 200
    assert [source["filename"] for source in generic_response.json()["sources"]] == [
        "spare-part-1298561035.pdf",
        "unscoped-61035-manual.pdf",
    ]


def test_list_documents_does_not_return_cross_workspace_ledger_sources(db_session, monkeypatch):
    current_ws = Workspace(id="ws-list-current", name="Current", slug="list-current")
    other_ws = Workspace(id="ws-list-other", name="Other", slug="list-other")
    db_session.add_all([current_ws, other_ws])
    db_session.commit()
    other_collection = create_collection(db_session, workspace=other_ws, name="Shared Manuals")
    db_session.add(
        KnowledgeCollectionSource(
            workspace_id=other_ws.id,
            collection_id=other_collection.id,
            filename="secret-manual.pdf",
            normalized_name="secret-manual.pdf",
            source_kind="pdf",
            extension="pdf",
            mime_type="application/pdf",
            origin="upload",
            chunk_count=4,
            status="ready",
            source_metadata={"document_id": "secret-doc"},
        )
    )
    db_session.commit()
    captured: dict[str, str | None] = {}

    class ScopedDocumentService:
        def __init__(self, *args, **kwargs):
            captured["collection_name"] = kwargs.get("collection_name")
            captured["workspace_slug"] = kwargs.get("workspace_slug")

        async def list_documents(self):
            if captured["workspace_slug"] == other_ws.slug:
                return [{"document_id": "secret-doc", "filename": "secret-manual.pdf"}]
            return []

    monkeypatch.setattr(documents, "DocumentService", ScopedDocumentService)

    response = _client(db_session, current_ws).get(
        f"/documents/list?collection_name={other_collection.slug}&limit=10"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["documents"] == []
    assert body["total"] == 0
    assert body["source"] == "vector"
    assert captured == {
        "collection_name": other_collection.slug,
        "workspace_slug": current_ws.slug,
    }
    assert "secret-manual.pdf" not in str(body)


def test_document_preview_resolves_source_from_ledger_without_vector_listing(
    db_session, tmp_path, monkeypatch
):
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


def test_list_documents_returns_workspace_vector_documents_with_pagination(
    db_session,
    monkeypatch,
):
    ws = Workspace(id="ws-list-vector", name="List Vector", slug="list-vector")
    db_session.add(ws)
    db_session.commit()
    captured: dict[str, str | None] = {}

    class FakeDocumentService:
        def __init__(self, *args, **kwargs):
            captured["collection_name"] = kwargs.get("collection_name")
            captured["workspace_slug"] = kwargs.get("workspace_slug")

        async def list_documents(self):
            return [
                {"document_id": "doc-1", "filename": "manual-1.pdf"},
                {"document_id": "hidden", "filename": ".hidden.pdf"},
                {"document_id": "tmp", "filename": "upload.tmp"},
                {"filename": "missing-id.pdf"},
                {"document_id": "doc-2", "filename": "manual-2.pdf"},
                {"document_id": "doc-3", "filename": "manual-3.pdf"},
            ]

    monkeypatch.setattr(documents, "DocumentService", FakeDocumentService)

    response = _client(db_session, ws).get("/documents/list?limit=2&offset=1")

    assert response.status_code == 200
    body = response.json()
    assert captured == {
        "collection_name": "documents",
        "workspace_slug": ws.slug,
    }
    assert body["collection_name"] == "documents"
    assert body["source"] == "vector"
    assert body["total"] == 3
    assert body["limit"] == 2
    assert body["offset"] == 1
    assert body["has_more"] is False
    assert [item["document_id"] for item in body["documents"]] == ["doc-2", "doc-3"]
    assert ".hidden.pdf" not in str(body)
    assert "upload.tmp" not in str(body)
    assert "missing-id.pdf" not in str(body)


def test_list_documents_caps_large_vector_page_and_rejects_oversized_limit(
    db_session,
    monkeypatch,
):
    ws = Workspace(id="ws-list-vector-large", name="List Vector Large", slug="list-vector-large")
    db_session.add(ws)
    db_session.commit()
    calls: list[dict[str, str | None]] = []

    class FakeDocumentService:
        def __init__(self, *args, **kwargs):
            calls.append(
                {
                    "collection_name": kwargs.get("collection_name"),
                    "workspace_slug": kwargs.get("workspace_slug"),
                }
            )

        async def list_documents(self):
            return [
                {"document_id": f"doc-{index:04d}", "filename": f"manual-{index:04d}.pdf"}
                for index in range(1505)
            ]

    monkeypatch.setattr(documents, "DocumentService", FakeDocumentService)

    response = _client(db_session, ws).get("/documents/list?limit=1000&offset=250")

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "vector"
    assert body["total"] == 1505
    assert body["limit"] == 1000
    assert body["offset"] == 250
    assert body["has_more"] is True
    assert len(body["documents"]) == 1000
    assert body["documents"][0]["document_id"] == "doc-0250"
    assert body["documents"][-1]["document_id"] == "doc-1249"
    assert calls == [
        {
            "collection_name": "documents",
            "workspace_slug": ws.slug,
        }
    ]

    invalid = _client(db_session, ws).get("/documents/list?limit=1001")
    assert invalid.status_code == 422
    assert len(calls) == 1


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
    assert body["fallback_reason"] in {
        None,
        "dense_unscoped_fast_policy",
        "dense_unscoped_search_skipped",
    }
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
            return [
                {"content": "scoped result", "metadata": {"source_kind": "markup"}, "score": 0.8}
            ]

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


def test_document_facts_ocr_filter_returns_empty_state_when_unavailable(db_session):
    ws = Workspace(id="ws-ocr-empty", name="OCR Empty", slug="ocr-empty")
    db_session.add(ws)
    db_session.commit()
    collection = create_collection(db_session, workspace=ws, name="Visual Manuals")
    db_session.add(
        KnowledgeDocumentFact(
            workspace_id=ws.id,
            collection_id=collection.id,
            collection_slug=collection.slug,
            document_id="manual-doc",
            document_filename="manual.pdf",
            document_type="pdf",
            semantic_type="document_warning",
            content="Non-OCR warning fact",
        )
    )
    db_session.commit()

    response = _client(db_session, ws).get(
        f"/documents/document-facts?collection_name={collection.slug}&semantic_type=document_ocr_text"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["collection_name"] == collection.slug
    assert body["items"] == []
    assert body["total"] == 0
    assert body["total_returned"] == 0
    assert body["has_more"] is False
    assert body["limit"] == 100
    assert body["offset"] == 0
    assert body["by_type"] == {"document_warning": 1}


def test_table_facts_return_ledger_rows_with_cell_metadata(db_session):
    ws = Workspace(id="ws-table-facts", name="Table Facts", slug="table-facts")
    db_session.add(ws)
    db_session.commit()
    collection = create_collection(db_session, workspace=ws, name="Spreadsheets")
    db_session.add_all(
        [
            KnowledgeTableFact(
                workspace_id=ws.id,
                collection_id=collection.id,
                collection_slug=collection.slug,
                document_id="sheet-doc-1",
                document_filename="machine-settings.xlsx",
                sheet_name="Parameters",
                semantic_type="spreadsheet_cell_fact",
                row_index=2,
                column_index=3,
                cell_ref="C2",
                cell_range="C2:C2",
                row_label="Line speed",
                column_header="Nominal value",
                subject="DCC line",
                measure="speed",
                value_raw="1200",
                value_numeric=1200.0,
                unit="m/min",
                table_region_id="Parameters:1",
                content="Line speed nominal value is 1200 m/min",
            ),
            KnowledgeTableFact(
                workspace_id=ws.id,
                collection_id=collection.id,
                collection_slug=collection.slug,
                document_id="sheet-doc-1",
                document_filename="machine-settings.xlsx",
                sheet_name="Parameters",
                semantic_type="spreadsheet_schema",
                row_index=1,
                column_index=1,
                cell_range="A1:C1",
                content="Spreadsheet schema for parameters",
            ),
        ]
    )
    db_session.commit()

    response = _client(db_session, ws).get(
        f"/documents/table-facts?collection_name={collection.slug}&semantic_type=spreadsheet_cell_fact"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "ledger"
    assert body["total_is_exact"] is True
    assert body["total"] == 1
    assert body["total_returned"] == 1
    assert body["has_more"] is False
    assert body["by_type"] == {"spreadsheet_cell_fact": 1, "spreadsheet_schema": 1}
    item = body["items"][0]
    assert item["document_id"] == "sheet-doc-1"
    assert item["document_filename"] == "machine-settings.xlsx"
    assert item["sheet_name"] == "Parameters"
    assert item["cell_ref"] == "C2"
    assert item["cell_range"] == "C2:C2"
    assert item["row_start"] == 2
    assert item["row_end"] == 2
    assert item["row_label"] == "Line speed"
    assert item["column_header"] == "Nominal value"
    assert item["unit"] == "m/min"
    assert item["subject"] == "DCC line"
    assert item["measure"] == "speed"
    assert item["value_raw"] == "1200"
    assert item["value_numeric"] == 1200.0


def test_table_facts_filter_by_sheet_and_query_without_stale_rows(db_session):
    ws = Workspace(id="ws-table-filter", name="Table Filter", slug="table-filter")
    db_session.add(ws)
    db_session.commit()
    collection = create_collection(db_session, workspace=ws, name="Spreadsheets")
    db_session.add_all(
        [
            KnowledgeTableFact(
                workspace_id=ws.id,
                collection_id=collection.id,
                collection_slug=collection.slug,
                document_id="doc-pressure",
                document_filename="process.xlsx",
                sheet_name="Hydraulics",
                semantic_type="spreadsheet_cell_fact",
                row_index=4,
                column_index=2,
                cell_ref="B4",
                row_label="Pressure",
                value_raw="85 bar",
                value_numeric=85.0,
                unit="bar",
                content="Hydraulics pressure target 85 bar",
            ),
            KnowledgeTableFact(
                workspace_id=ws.id,
                collection_id=collection.id,
                collection_slug=collection.slug,
                document_id="doc-temperature",
                document_filename="process.xlsx",
                sheet_name="Thermal",
                semantic_type="spreadsheet_cell_fact",
                row_index=4,
                column_index=2,
                cell_ref="B4",
                row_label="Pressure",
                value_raw="85 bar",
                content="Thermal pressure note should not appear for hydraulics sheet filter",
            ),
            KnowledgeTableFact(
                workspace_id=ws.id,
                collection_id=collection.id,
                collection_slug=collection.slug,
                document_id="doc-speed",
                document_filename="process.xlsx",
                sheet_name="Hydraulics",
                semantic_type="spreadsheet_cell_fact",
                row_index=5,
                column_index=2,
                cell_ref="B5",
                row_label="Speed",
                value_raw="1200",
                content="Hydraulics speed target 1200",
            ),
        ]
    )
    db_session.commit()

    response = _client(db_session, ws).get(
        f"/documents/table-facts?collection_name={collection.slug}&sheet_name=Hydraulics&q=pressure"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "ledger"
    assert body["total"] == 1
    assert body["total_returned"] == 1
    assert body["by_type"] == {"spreadsheet_cell_fact": 1}
    assert body["items"][0]["document_id"] == "doc-pressure"
    assert body["items"][0]["sheet_name"] == "Hydraulics"
    assert body["items"][0]["row_label"] == "Pressure"
    assert "doc-temperature" not in str(body)
    assert "doc-speed" not in str(body)


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

    response = _client(db_session, ws).get(f"/documents/collections/{collection.slug}/diagnostics")

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
    assert body["offline_clustering"]["artifact_key"].endswith(
        "/derived/embedding-clusters/latest.json"
    )
    assert body["feature_status"]["offline_clustering"]["state"] == "not_needed"


def test_collection_diagnostics_keeps_ledger_visible_when_vector_service_fails(
    db_session,
    monkeypatch,
):
    ws = Workspace(
        id="ws-diagnostics-vector-fails",
        name="Diagnostics Vector Fails",
        slug="diagnostics-vector-fails",
    )
    db_session.add(ws)
    db_session.commit()
    collection = create_collection(db_session, workspace=ws, name="Manuals")
    collection.document_count = 2
    collection.chunk_count = 14
    db_session.add_all(
        [
            KnowledgeCollectionSource(
                workspace_id=ws.id,
                collection_id=collection.id,
                filename="manual-a.pdf",
                normalized_name="manual-a.pdf",
                source_kind="pdf",
                extension="pdf",
                mime_type="application/pdf",
                origin="upload",
                chunk_count=6,
                status="ready",
            ),
            KnowledgeCollectionSource(
                workspace_id=ws.id,
                collection_id=collection.id,
                filename="manual-b.pdf",
                normalized_name="manual-b.pdf",
                source_kind="pdf",
                extension="pdf",
                mime_type="application/pdf",
                origin="upload",
                chunk_count=8,
                status="ready",
            ),
            KnowledgeDocumentFact(
                workspace_id=ws.id,
                collection_id=collection.id,
                collection_slug=collection.slug,
                document_id="doc-warning",
                document_filename="manual-a.pdf",
                document_type="pdf",
                semantic_type="document_warning",
                content="warning",
            ),
        ]
    )
    db_session.commit()

    class FailingDocumentService:
        def __init__(self, *args, **kwargs):
            self.vector_db = object()

        async def get_document_count(self):
            raise RuntimeError("qdrant unavailable")

    monkeypatch.setattr(documents, "DocumentService", FailingDocumentService)

    response = _client(db_session, ws).get(f"/documents/collections/{collection.slug}/diagnostics")

    assert response.status_code == 200
    body = response.json()
    assert body["vector_points"] is None
    assert body["vector_dim"] is None
    assert body["drift"] is None
    assert body["drift_status"] == "unknown"
    assert body["ledger_source_count"] == 2
    assert body["ledger_document_count"] == 2
    assert body["ledger_chunk_sum"] == 14
    assert body["by_kind"] == {"pdf": 2}
    assert body["by_status"] == {"ready": 2}
    assert body["document_facts"]["by_type"] == {"document_warning": 1}
    assert body["feature_status"]["document_facts"]["state"] == "available"
    assert body["feature_status"]["ocr"]["state"] == "empty"


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


def test_collection_document_upload_batch_creates_sources_for_all_files(
    db_session,
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "objects"))
    ws = Workspace(id="ws-upload-batch", name="Upload Batch", slug="upload-batch")
    db_session.add(ws)
    db_session.commit()
    collection = create_collection(db_session, workspace=ws, name="Manuals")
    db_session.commit()

    def fake_dispatch(db, job):
        job.celery_task_id = "task-batch"
        return "task-batch"

    monkeypatch.setattr(documents, "dispatch_worker_job", fake_dispatch)

    response = _client(db_session, ws).post(
        f"/documents/collections/{collection.id}/documents",
        files=[
            ("files", ("manual.txt", b"hello", "text/plain")),
            ("files", ("settings.csv", b"label,value\nspeed,1200\n", "text/csv")),
            ("files", ("diagram.png", b"\x89PNG\r\n\x1a\n", "image/png")),
        ],
    )

    assert response.status_code == 200
    body = response.json()
    assert body["collection_id"] == collection.id
    assert body["collection_slug"] == collection.slug
    assert body["status"] == "queued"
    assert body["collection_status"] == "queued"
    assert body["celery_task_id"] == "task-batch"
    assert body["files"] == ["manual.txt", "settings.csv", "diagram.png"]

    job = db_session.query(WorkerJob).filter(WorkerJob.id == body["job_id"]).one()
    assert job.collection_id == collection.id
    assert job.status == "queued"

    db_session.refresh(collection)
    assert collection.document_names == ["manual.txt", "settings.csv", "diagram.png"]
    assert collection.document_count == 3
    assert (
        tmp_path / "objects" / collection.artifact_prefix / "original" / "manual.txt"
    ).read_bytes() == b"hello"
    assert (
        tmp_path / "objects" / collection.artifact_prefix / "original" / "settings.csv"
    ).read_bytes() == b"label,value\nspeed,1200\n"
    assert (
        tmp_path / "objects" / collection.artifact_prefix / "original" / "diagram.png"
    ).read_bytes() == b"\x89PNG\r\n\x1a\n"

    sources = (
        db_session.query(KnowledgeCollectionSource)
        .filter(KnowledgeCollectionSource.collection_id == collection.id)
        .order_by(KnowledgeCollectionSource.filename.asc())
        .all()
    )
    assert [(source.filename, source.source_kind, source.status) for source in sources] == [
        ("diagram.png", "image", "queued"),
        ("manual.txt", "text", "queued"),
        ("settings.csv", "spreadsheet", "queued"),
    ]

    inventory_response = _client(db_session, ws).get(
        f"/documents/collections/{collection.id}/inventory"
    )
    assert inventory_response.status_code == 200
    inventory = inventory_response.json()
    assert inventory["source_count"] == 3
    assert inventory["document_count"] == 3
    assert inventory["sources_returned"] == 3
    assert inventory["by_kind"] == {"image": 1, "spreadsheet": 1, "text": 1}


def test_upload_batch_handles_large_synthetic_batch_with_one_job(
    db_session,
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(settings, "document_ingest_async_enabled", True)
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "objects"))
    ws = Workspace(
        id="ws-upload-global-large", name="Upload Global Large", slug="upload-global-large"
    )
    db_session.add(ws)
    db_session.commit()
    filenames = [f"manual-{index:02d}.txt" for index in range(40)]

    def fake_dispatch(db, job):
        job.celery_task_id = "task-large-batch"
        return "task-large-batch"

    monkeypatch.setattr(documents, "dispatch_worker_job", fake_dispatch)

    response = _client(db_session, ws).post(
        "/documents/upload-batch",
        data={"collection_name": "large-batch"},
        files=[
            ("files", (filename, f"payload {filename}".encode(), "text/plain"))
            for filename in filenames
        ],
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "queued"
    assert body["collection_name"] == "large-batch"
    assert body["total"] == len(filenames)
    assert body["successful"] == 0
    assert body["failed"] == 0
    assert len(body["documents"]) == len(filenames)
    assert {item["filename"] for item in body["documents"]} == set(filenames)
    assert {item["status"] for item in body["documents"]} == {"queued"}

    collection = (
        db_session.query(KnowledgeCollection)
        .filter(
            KnowledgeCollection.workspace_id == ws.id, KnowledgeCollection.slug == "large-batch"
        )
        .one()
    )
    assert collection.status == "queued"
    assert collection.document_names == filenames
    assert collection.document_count == len(filenames)

    jobs = db_session.query(WorkerJob).filter(WorkerJob.collection_id == collection.id).all()
    assert len(jobs) == 1
    assert jobs[0].celery_task_id == "task-large-batch"

    sources = (
        db_session.query(KnowledgeCollectionSource)
        .filter(KnowledgeCollectionSource.collection_id == collection.id)
        .order_by(KnowledgeCollectionSource.filename.asc())
        .all()
    )
    assert [source.filename for source in sources] == filenames
    assert {source.status for source in sources} == {"queued"}
    assert all(source.chunk_count == 0 for source in sources)
    assert all(
        (tmp_path / "objects" / collection.artifact_prefix / "original" / filename).read_bytes()
        == f"payload {filename}".encode()
        for filename in filenames
    )


def test_upload_batch_rejects_mixed_unsupported_file_without_persisting_batch(
    db_session,
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(settings, "document_ingest_async_enabled", True)
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "objects"))
    ws = Workspace(
        id="ws-upload-global-mixed", name="Upload Global Mixed", slug="upload-global-mixed"
    )
    db_session.add(ws)
    db_session.commit()

    def fail_dispatch(db, job):  # pragma: no cover - assertion guard
        raise AssertionError("unsupported batch must fail before dispatch")

    monkeypatch.setattr(documents, "dispatch_worker_job", fail_dispatch)

    response = _client(db_session, ws).post(
        "/documents/upload-batch",
        data={"collection_name": "mixed-batch"},
        files=[
            ("files", ("manual.txt", b"valid manual payload", "text/plain")),
            ("files", ("blocked.exe", b"MZ", "application/octet-stream")),
        ],
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "Unsupported file extension" in detail
    assert "blocked.exe" in detail
    assert "manual.txt" not in detail
    assert (
        db_session.query(KnowledgeCollection)
        .filter(
            KnowledgeCollection.workspace_id == ws.id, KnowledgeCollection.slug == "mixed-batch"
        )
        .count()
        == 0
    )
    assert db_session.query(KnowledgeCollectionSource).count() == 0
    assert db_session.query(WorkerJob).count() == 0
    object_root = tmp_path / "objects"
    assert not object_root.exists() or not any(object_root.rglob("*"))


def test_single_upload_rejects_unsupported_file_without_wrapping_http_error(
    db_session,
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(settings, "document_ingest_async_enabled", True)
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "objects"))
    ws = Workspace(id="ws-upload-single-bad", name="Upload Single Bad", slug="upload-single-bad")
    db_session.add(ws)
    db_session.commit()

    response = _client(db_session, ws).post(
        "/documents/upload",
        data={"collection_name": "single-bad"},
        files={"file": ("blocked.exe", b"MZ", "application/octet-stream")},
    )

    assert response.status_code == 422
    assert "blocked.exe" in response.json()["detail"]
    assert (
        db_session.query(KnowledgeCollection)
        .filter(KnowledgeCollection.workspace_id == ws.id, KnowledgeCollection.slug == "single-bad")
        .count()
        == 0
    )
    assert db_session.query(KnowledgeCollectionSource).count() == 0
    assert db_session.query(WorkerJob).count() == 0


def test_collection_document_upload_extends_existing_manifest_without_overwriting_sources(
    db_session,
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "objects"))
    ws = Workspace(id="ws-upload-extend", name="Upload Extend", slug="upload-extend")
    db_session.add(ws)
    db_session.commit()
    collection = create_collection(db_session, workspace=ws, name="Manuals")
    collection.document_names = ["existing.pdf"]
    collection.document_count = 1
    db_session.add(
        KnowledgeCollectionSource(
            workspace_id=ws.id,
            collection_id=collection.id,
            filename="existing.pdf",
            normalized_name="existing.pdf",
            source_kind="pdf",
            extension="pdf",
            mime_type="application/pdf",
            origin="upload",
            size_bytes=17,
            chunk_count=4,
            status="ready",
            source_metadata={"document_id": "doc-existing"},
        )
    )
    db_session.commit()

    def fake_dispatch(db, job):
        job.celery_task_id = "task-extend"
        return "task-extend"

    monkeypatch.setattr(documents, "dispatch_worker_job", fake_dispatch)

    response = _client(db_session, ws).post(
        f"/documents/collections/{collection.id}/documents",
        files=[("files", ("new-note.txt", b"new note", "text/plain"))],
    )

    assert response.status_code == 200
    body = response.json()
    assert body["files"] == ["new-note.txt"]
    assert body["celery_task_id"] == "task-extend"

    db_session.refresh(collection)
    assert collection.document_names == ["existing.pdf", "new-note.txt"]
    assert collection.document_count == 2

    sources = (
        db_session.query(KnowledgeCollectionSource)
        .filter(KnowledgeCollectionSource.collection_id == collection.id)
        .order_by(KnowledgeCollectionSource.filename.asc())
        .all()
    )
    assert [(source.filename, source.status, source.chunk_count) for source in sources] == [
        ("existing.pdf", "ready", 4),
        ("new-note.txt", "queued", 0),
    ]
    assert (
        tmp_path / "objects" / collection.artifact_prefix / "original" / "new-note.txt"
    ).read_bytes() == b"new note"


def test_collection_document_upload_existing_filename_updates_source_without_manifest_dup(
    db_session,
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "objects"))
    ws = Workspace(
        id="ws-upload-existing-name", name="Upload Existing Name", slug="upload-existing-name"
    )
    db_session.add(ws)
    db_session.commit()
    collection = create_collection(db_session, workspace=ws, name="Manuals")
    collection.document_names = ["manual.txt"]
    collection.document_count = 1
    db_session.add(
        KnowledgeCollectionSource(
            workspace_id=ws.id,
            collection_id=collection.id,
            filename="manual.txt",
            normalized_name="manual.txt",
            source_kind="text",
            extension="txt",
            mime_type="text/plain",
            origin="upload",
            size_bytes=3,
            chunk_count=2,
            status="ready",
            source_metadata={"document_id": "doc-existing-manual"},
        )
    )
    db_session.commit()

    def fake_dispatch(db, job):
        job.celery_task_id = "task-existing-name"
        return "task-existing-name"

    monkeypatch.setattr(documents, "dispatch_worker_job", fake_dispatch)

    response = _client(db_session, ws).post(
        f"/documents/collections/{collection.id}/documents",
        files=[("files", ("manual.txt", b"new", "text/plain"))],
    )

    assert response.status_code == 200
    body = response.json()
    assert body["files"] == ["manual.txt"]

    db_session.refresh(collection)
    assert collection.document_names == ["manual.txt"]
    assert collection.document_count == 1

    sources = (
        db_session.query(KnowledgeCollectionSource)
        .filter(KnowledgeCollectionSource.collection_id == collection.id)
        .all()
    )
    assert len(sources) == 1
    assert sources[0].filename == "manual.txt"
    assert sources[0].size_bytes == 3
    assert sources[0].chunk_count == 0
    assert sources[0].status == "queued"
    assert sources[0].source_metadata == {}
    assert (
        tmp_path / "objects" / collection.artifact_prefix / "original" / "manual.txt"
    ).read_bytes() == b"new"


def test_collection_document_upload_worker_enqueue_failure_is_persisted(
    db_session,
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "objects"))
    ws = Workspace(
        id="ws-upload-dispatch-fails", name="Upload Dispatch Fails", slug="upload-dispatch-fails"
    )
    db_session.add(ws)
    db_session.commit()
    collection = create_collection(db_session, workspace=ws, name="Manuals")
    db_session.commit()

    def failing_dispatch(db, job):
        raise RuntimeError("broker offline")

    monkeypatch.setattr(documents, "dispatch_worker_job", failing_dispatch)

    response = _client(db_session, ws).post(
        f"/documents/collections/{collection.id}/documents",
        files=[("files", ("manual.txt", b"manual", "text/plain"))],
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "Worker dispatch failed"

    db_session.refresh(collection)
    assert collection.status == "error"
    assert collection.last_error == "Worker dispatch failed: broker offline"
    assert collection.document_names == ["manual.txt"]
    assert collection.document_count == 1
    assert (
        tmp_path / "objects" / collection.artifact_prefix / "original" / "manual.txt"
    ).read_bytes() == b"manual"

    job = db_session.query(WorkerJob).filter(WorkerJob.collection_id == collection.id).one()
    assert job.status == "failed"
    assert job.progress == 100
    assert job.error == "broker offline"
    assert job.result["stage"] == "dispatch_failed"

    source = (
        db_session.query(KnowledgeCollectionSource)
        .filter(KnowledgeCollectionSource.collection_id == collection.id)
        .one()
    )
    assert source.filename == "manual.txt"
    assert source.status == "queued"
    assert source.chunk_count == 0
    assert source.source_metadata == {}


def test_collection_document_upload_duplicate_filename_keeps_inventory_coherent(
    db_session,
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "objects"))
    ws = Workspace(id="ws-upload-duplicate", name="Upload Duplicate", slug="upload-duplicate")
    db_session.add(ws)
    db_session.commit()
    collection = create_collection(db_session, workspace=ws, name="Manuals")
    db_session.commit()

    def fake_dispatch(db, job):
        job.celery_task_id = "task-duplicate"
        return "task-duplicate"

    monkeypatch.setattr(documents, "dispatch_worker_job", fake_dispatch)

    response = _client(db_session, ws).post(
        f"/documents/collections/{collection.id}/documents",
        files=[
            ("files", ("manual.txt", b"first", "text/plain")),
            ("files", ("manual.txt", b"second", "text/plain")),
        ],
    )

    assert response.status_code == 200
    body = response.json()
    assert body["files"] == ["manual.txt", "manual.txt"]
    assert body["celery_task_id"] == "task-duplicate"

    db_session.refresh(collection)
    assert collection.document_names == ["manual.txt"]
    assert collection.document_count == 1
    assert (
        tmp_path / "objects" / collection.artifact_prefix / "original" / "manual.txt"
    ).read_bytes() == b"second"

    sources = (
        db_session.query(KnowledgeCollectionSource)
        .filter(KnowledgeCollectionSource.collection_id == collection.id)
        .all()
    )
    assert len(sources) == 1
    assert sources[0].filename == "manual.txt"
    assert sources[0].normalized_name == "manual.txt"
    assert sources[0].size_bytes == len(b"second")
    assert sources[0].status == "queued"

    inventory_response = _client(db_session, ws).get(
        f"/documents/collections/{collection.id}/inventory"
    )
    assert inventory_response.status_code == 200
    inventory = inventory_response.json()
    assert inventory["source_count"] == 1
    assert inventory["document_count"] == 1
    assert inventory["sources_returned"] == 1
    assert inventory["sources"][0]["filename"] == "manual.txt"


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

    inventory_response = _client(db_session, ws).get(
        f"/documents/collections/{collection.id}/inventory"
    )
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


def test_collection_retrieval_artifact_job_large_dry_run_is_read_only(
    db_session, tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "objects"))
    ws = Workspace(id="ws-artifact-large-dry", name="Artifact Large Dry", slug="artifact-large-dry")
    db_session.add(ws)
    db_session.commit()
    collection = create_collection(
        db_session,
        workspace=ws,
        name="Synthetic Large Manuals",
        slug="synthetic-large-manuals",
    )
    collection.status = "ready"
    collection.document_count = settings.rag_dense_source_threshold + 250
    collection.chunk_count = settings.rag_dense_chunk_threshold + 25_000
    db_session.add_all(
        [
            KnowledgeCollectionSource(
                workspace_id=ws.id,
                collection_id=collection.id,
                filename=f"large-manual-{index}.pdf",
                normalized_name=f"large-manual-{index}.pdf",
                source_kind="pdf",
                extension="pdf",
                mime_type="application/pdf",
                origin="upload",
                chunk_count=10_000 + index,
                status="ready",
            )
            for index in range(3)
        ]
    )
    db_session.commit()
    store = get_object_store()
    sentinel_key = f"{collection.artifact_prefix}/originals/large-manual-0.pdf"
    store.write_bytes(sentinel_key, b"synthetic-pdf")
    before_collection = {
        "status": collection.status,
        "document_count": collection.document_count,
        "chunk_count": collection.chunk_count,
    }
    before_source_count = (
        db_session.query(KnowledgeCollectionSource)
        .filter(KnowledgeCollectionSource.collection_id == collection.id)
        .count()
    )

    def fail_dispatch(*_args, **_kwargs):
        raise AssertionError("dry-run retrieval artifact assessment must not enqueue workers")

    monkeypatch.setattr(documents, "dispatch_worker_job", fail_dispatch)

    response = _client(db_session, ws).post(
        f"/documents/collections/{collection.slug}/retrieval-artifact-jobs",
        json={"kind": "qdrant_sparse_reindex", "dry_run": True},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "dry_run"
    assert body["kind"] == "qdrant_sparse_reindex"
    assert body["collection_slug"] == collection.slug
    assert body["poll_url"] is None
    assert body["would_create_job"] is True
    assert body["would_dispatch"] is True
    assert body["dry_run"] is True
    assert db_session.query(WorkerJob).filter(WorkerJob.collection_id == collection.id).count() == 0
    db_session.refresh(collection)
    assert {
        "status": collection.status,
        "document_count": collection.document_count,
        "chunk_count": collection.chunk_count,
    } == before_collection
    assert (
        db_session.query(KnowledgeCollectionSource)
        .filter(KnowledgeCollectionSource.collection_id == collection.id)
        .count()
    ) == before_source_count
    assert store.read_bytes(sentinel_key) == b"synthetic-pdf"


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


def test_clear_documents_denies_non_admin_without_touching_store(db_session, monkeypatch):
    ws = Workspace(id="ws-clear-denied", name="Clear Denied", slug="clear-denied")
    db_session.add(ws)
    db_session.commit()
    _seed_workspace_user(db_session, ws, role="member", role_template="workspace_contributor")
    calls = []

    class FakeDocumentService:
        def __init__(self, *args, **kwargs):
            calls.append(("init", args, kwargs))

        async def clear_all_documents(self):
            calls.append(("clear", (), {}))
            return True

    monkeypatch.setattr(documents, "DocumentService", FakeDocumentService)

    response = _client(db_session, ws).delete(
        "/documents/clear?collection_name=andritz-prod&confirm=true&confirm_collection_name=andritz-prod"
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "WORKSPACE_PERMISSION_DENIED"
    assert calls == []


def test_clear_documents_requires_explicit_confirmation_for_admin(db_session, monkeypatch):
    ws = Workspace(id="ws-clear-confirm", name="Clear Confirm", slug="clear-confirm")
    db_session.add(ws)
    db_session.commit()
    _seed_workspace_user(db_session, ws, role="admin", role_template="workspace_admin")
    calls = []

    class FakeDocumentService:
        def __init__(self, *args, **kwargs):
            calls.append(("init", args, kwargs))

        async def clear_all_documents(self):
            calls.append(("clear", (), {}))
            return True

    monkeypatch.setattr(documents, "DocumentService", FakeDocumentService)

    response = _client(db_session, ws).delete("/documents/clear?collection_name=andritz-synthetic")

    assert response.status_code == 400
    assert "confirm=true" in response.json()["detail"]
    assert calls == []


def test_clear_documents_requires_matching_collection_confirmation(db_session, monkeypatch):
    ws = Workspace(id="ws-clear-match", name="Clear Match", slug="clear-match")
    db_session.add(ws)
    db_session.commit()
    _seed_workspace_user(db_session, ws, role="admin", role_template="workspace_admin")
    calls = []

    class FakeDocumentService:
        def __init__(self, *args, **kwargs):
            calls.append(("init", args, kwargs))

        async def clear_all_documents(self):
            calls.append(("clear", (), {}))
            return True

    monkeypatch.setattr(documents, "DocumentService", FakeDocumentService)

    response = _client(db_session, ws).delete(
        "/documents/clear?collection_name=andritz-synthetic&confirm=true&confirm_collection_name=wrong"
    )

    assert response.status_code == 400
    assert "confirm_collection_name" in response.json()["detail"]
    assert calls == []


def test_clear_documents_confirmed_admin_does_not_delete_uploads_by_default(
    db_session,
    tmp_path,
    monkeypatch,
):
    ws = Workspace(id="ws-clear-admin", name="Clear Admin", slug="clear-admin")
    db_session.add(ws)
    db_session.commit()
    _seed_workspace_user(db_session, ws, role="admin", role_template="workspace_admin")
    uploads_dir = tmp_path / "uploads"
    uploads_dir.mkdir()
    legacy_upload = uploads_dir / "legacy-upload.txt"
    legacy_upload.write_text("keep me", encoding="utf-8")
    calls = []

    class FakeDocumentService:
        def __init__(self, *args, **kwargs):
            calls.append(("init", args, kwargs))

        async def clear_all_documents(self):
            calls.append(("clear", (), {}))
            return True

    monkeypatch.setattr(documents, "DocumentService", FakeDocumentService)
    monkeypatch.setattr(documents, "UPLOADS_DIR", str(uploads_dir))

    response = _client(db_session, ws).delete(
        "/documents/clear?collection_name=andritz-synthetic&confirm=true&confirm_collection_name=andritz-synthetic"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["message"] == "All documents cleared from collection 'andritz-synthetic'"
    assert body["deleted_upload_files"] == 0
    assert legacy_upload.exists()
    assert calls[0][2]["collection_name"] == "andritz-synthetic"
    assert calls[1][0] == "clear"


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


def _failed_ingest(db_session):
    from datetime import datetime

    ws = Workspace(id="ws-ingest-retry", name="Retry", slug="retry")
    db_session.add(ws)
    db_session.commit()
    _seed_workspace_user(db_session, ws, role="admin", role_template="workspace_admin")
    collection = create_collection(db_session, workspace=ws, name="Retained sources")
    collection.status = "error"
    job = create_worker_job(db_session, workspace_id=ws.id, collection_id=collection.id)
    job.status, job.error, job.progress = "failed", "Embedding provider unavailable", 100
    job.started_at = job.completed_at = datetime.utcnow()
    job.celery_task_id = "failed-task"
    job.result = {"stage": "embedding", "ingest_options": {"document_ocr": {"scan.pdf": True}}}
    db_session.commit()
    return ws, collection, job


def _retry_payload(job):
    from uuid import uuid4

    return {"request_id": str(uuid4()), "observed_updated_at": job.updated_at.isoformat()}


def test_ingest_retry_preserves_failure_and_is_idempotent(db_session, monkeypatch):
    ws, collection, job = _failed_ingest(db_session)
    calls = []

    def dispatch(db, row, *, allow_inline_fallback):
        assert allow_inline_fallback is False
        calls.append(row.id)
        row.celery_task_id = "new-task"
        return "new-task"

    monkeypatch.setattr(documents, "dispatch_worker_job", dispatch)
    payload = _retry_payload(job)
    client = _client(db_session, ws)
    response = client.post(f"/documents/jobs/{job.id}/retry", json=payload)
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["id"] == job.id
    assert body["status"] == "queued" and body["progress"] == 0
    assert body["error"] is None and body["started_at"] is None and body["completed_at"] is None
    assert body["result"]["ingest_options"] == {"document_ocr": {"scan.pdf": True}}
    history = body["result"]["retry_history"]
    assert len(history) == 1
    assert history[0]["error"] == "Embedding provider unavailable"
    assert history[0]["celery_task_id"] == "failed-task"
    assert history[0]["result"]["stage"] == "embedding"
    assert history[0]["retried_by"] == "user-1"
    assert client.post(f"/documents/jobs/{job.id}/retry", json=payload).status_code == 202
    assert calls == [job.id]
    # A delayed duplicate must not restart the same attempt after another failure.
    job.status, job.error = "failed", "Still unavailable"
    db_session.commit()
    replay = client.post(f"/documents/jobs/{job.id}/retry", json=payload)
    assert replay.json()["status"] == "failed"
    assert calls == [job.id]
    db_session.refresh(collection)
    assert collection.status == "queued"


def test_ingest_retry_dispatch_outage_remains_recoverable(db_session, monkeypatch):
    ws, _, job = _failed_ingest(db_session)
    calls = []

    def dispatch(db, row, **kwargs):
        calls.append(row.id)
        if len(calls) == 1:
            row.result = {
                **row.result,
                "stage": "dispatch_pending",
                "dispatch_error": "Broker unavailable",
            }
        else:
            row.celery_task_id = "delivered"

    monkeypatch.setattr(documents, "dispatch_worker_job", dispatch)
    client = _client(db_session, ws)
    payload = _retry_payload(job)
    first = client.post(f"/documents/jobs/{job.id}/retry", json=payload)
    assert first.json()["stage"] == "dispatch_pending"
    second = client.post(f"/documents/jobs/{job.id}/retry", json=payload)
    assert second.json()["celery_task_id"] == "delivered"
    assert len(second.json()["result"]["retry_history"]) == 1
    assert len(calls) == 2


def test_ingest_retry_rejects_stale_foreign_and_non_admin_requests(db_session, monkeypatch):
    ws, _, job = _failed_ingest(db_session)
    monkeypatch.setattr(
        documents,
        "dispatch_worker_job",
        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("must not dispatch")),
    )
    client = _client(db_session, ws)
    payload = _retry_payload(job)
    stale = {**payload, "observed_updated_at": "2001-01-01T00:00:00"}
    assert (
        client.post(f"/documents/jobs/{job.id}/retry", json=stale).json()["detail"]["code"]
        == "INGEST_RETRY_STALE"
    )
    other = Workspace(id="other-retry", name="Other", slug="other-retry")
    db_session.add(other)
    db_session.add(WorkspaceMember(user_id="user-1", workspace_id=other.id, role="admin"))
    db_session.commit()
    assert (
        _client(db_session, other).post(f"/documents/jobs/{job.id}/retry", json=payload).status_code
        == 404
    )
    member = db_session.query(WorkspaceMember).filter_by(workspace_id=ws.id).one()
    member.role, member.role_template = "member", "workspace_contributor"
    db_session.commit()
    assert client.post(f"/documents/jobs/{job.id}/retry", json=payload).status_code == 403
    assert job.status == "failed" and job.error == "Embedding provider unavailable"


def test_ingest_retry_rejects_terminal_active_and_governed_jobs(db_session, monkeypatch):
    ws, collection, job = _failed_ingest(db_session)
    monkeypatch.setattr(
        documents,
        "dispatch_worker_job",
        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("must not dispatch")),
    )
    client = _client(db_session, ws)
    for status in ("completed", "cancelled", "running", "queued"):
        job.status = status
        db_session.commit()
        assert (
            client.post(f"/documents/jobs/{job.id}/retry", json=_retry_payload(job)).json()[
                "detail"
            ]["code"]
            == "INGEST_RETRY_NOT_FAILED"
        )
    job.status = "failed"
    job.result = {"ingest_options": {"mode": "incremental", "source_profile": "needlepunch"}}
    db_session.commit()
    assert (
        client.post(f"/documents/jobs/{job.id}/retry", json=_retry_payload(job)).json()["detail"][
            "code"
        ]
        == "INGEST_RETRY_CAMPAIGN_REQUIRED"
    )
    job.result = {"ingest_options": {"mode": "incremental"}}
    db_session.commit()
    assert (
        client.post(f"/documents/jobs/{job.id}/retry", json=_retry_payload(job)).json()["detail"][
            "code"
        ]
        == "INGEST_RETRY_BASELINE_REQUIRED"
    )
    job.result = {}
    newer = create_worker_job(db_session, workspace_id=ws.id, collection_id=collection.id)
    db_session.commit()
    assert (
        client.post(f"/documents/jobs/{job.id}/retry", json=_retry_payload(job)).json()["detail"][
            "code"
        ]
        == "INGEST_RETRY_SUPERSEDED"
    )
    newer.status = "completed"
    db_session.commit()
    assert (
        client.post(f"/documents/jobs/{job.id}/retry", json=_retry_payload(job)).status_code == 409
    )


def test_ingest_retry_respects_deposit_rejection_and_promotion_permission(db_session, monkeypatch):
    from fastapi import HTTPException

    from app.models.secure_deposit import DepositAccessLink, DepositFile

    ws, _, job = _failed_ingest(db_session)
    link = DepositAccessLink(
        workspace_id=ws.id,
        created_by_user_id="user-1",
        access_id="retry-link",
        password_hash="unused",
    )
    db_session.add(link)
    db_session.flush()
    deposit = DepositFile(
        workspace_id=ws.id,
        access_link_id=link.id,
        filename="source.pdf",
        object_key="retained",
        sha256="a" * 64,
        worker_job_id=job.id,
        status="rejected",
    )
    db_session.add(deposit)
    db_session.commit()
    calls = []
    monkeypatch.setattr(documents, "enforce_permission", lambda *a, **kw: calls.append(kw))
    monkeypatch.setattr(
        documents,
        "dispatch_worker_job",
        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("must not dispatch")),
    )
    client = _client(db_session, ws)
    response = client.post(f"/documents/jobs/{job.id}/retry", json=_retry_payload(job))
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "INGEST_RETRY_SOURCE_UNAVAILABLE"
    assert calls[0]["resource_kind"] == "deposit_file" and calls[0]["action"] == "promote"
    deposit.status = "received"
    db_session.commit()

    def deny(*a, **kw):
        raise HTTPException(403, "promotion denied")

    monkeypatch.setattr(documents, "enforce_permission", deny)
    assert (
        client.post(f"/documents/jobs/{job.id}/retry", json=_retry_payload(job)).status_code == 403
    )
    assert job.status == "failed"
    assert deposit.worker_job_id == job.id and deposit.status == "received"


def test_ingest_retry_real_dispatch_failure_does_not_execute_inline_or_overwrite_worker(
    db_session, monkeypatch
):
    import sys

    from app.services.worker_dispatch import dispatch_worker_job

    ws, _, job = _failed_ingest(db_session)
    monkeypatch.setattr(settings, "worker_eager_mode", False)
    monkeypatch.setattr(
        "app.services.worker_dispatch.run_document_ingest_index",
        lambda *a: (_ for _ in ()).throw(AssertionError("must not run inline")),
    )

    def reject(**kwargs):
        raise ConnectionError("broker unavailable")

    fake_task = SimpleNamespace(apply_async=reject)
    tasks = SimpleNamespace(
        document_ingest_index=fake_task,
        bm25_rebuild=fake_task,
        rag_deep_retrieval=fake_task,
        offline_retrieval_artifact=fake_task,
    )
    monkeypatch.setitem(sys.modules, "app.workers.tasks", tasks)
    client = _client(db_session, ws)
    response = client.post(f"/documents/jobs/{job.id}/retry", json=_retry_payload(job))
    assert response.status_code == 202
    assert response.json()["status"] == "queued"
    assert response.json()["result"]["dispatch_warning"] == "worker_dispatch_unavailable"

    # Lost broker acknowledgement after a worker finished: preserve its evidence.
    def completed_before_ack(**kwargs):
        job.status = "completed"
        job.result = {**job.result, "stage": "ready", "chunk_count": 12}
        db_session.commit()
        raise ConnectionError("ack lost")

    fake_task.apply_async = completed_before_ack
    dispatch_worker_job(db_session, job, allow_inline_fallback=False)
    db_session.refresh(job)
    assert job.status == "completed"
    assert job.result["stage"] == "ready" and job.result["chunk_count"] == 12


def test_a_request_cannot_choose_faiss_on_a_qdrant_deployment(monkeypatch, db_session):
    """The request parameter used to bypass the FAISS suppression entirely.

    On Kubernetes the FAISS directory is per-pod and ephemeral, so a caller
    reaching it wrote an index that differed between replicas and vanished on
    restart. Documents accepted, vectors unfindable, no error raised.
    """

    from app.api.v1.endpoints.documents import _resolve_document_vector_db_type

    monkeypatch.setattr(settings, "default_vector_db_type", "qdrant")
    ws = Workspace(id="ws-vdb-guard", name="Guard", slug="vdb-guard")
    db_session.add(ws)
    db_session.commit()

    assert _resolve_document_vector_db_type(ws, "faiss") == "qdrant"
    assert _resolve_document_vector_db_type(ws, None) == "qdrant"
    assert _resolve_document_vector_db_type(ws, "qdrant") == "qdrant"

    import pytest
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as refused:
        _resolve_document_vector_db_type(ws, "faiss", destructive=True)
    assert refused.value.status_code == 409
    assert refused.value.detail["code"] == "FAISS_STORE_NOT_CONFIGURED"


def test_a_faiss_deployment_still_gets_faiss(monkeypatch, db_session):
    """Only the request is closed. A deployment configured for FAISS keeps it."""

    from app.api.v1.endpoints.documents import _resolve_document_vector_db_type

    monkeypatch.setattr(settings, "default_vector_db_type", "faiss")
    ws = Workspace(id="ws-vdb-legacy", name="Legacy", slug="vdb-legacy")
    db_session.add(ws)
    db_session.commit()

    assert _resolve_document_vector_db_type(ws, None) == "faiss"
    assert _resolve_document_vector_db_type(ws, "faiss") == "faiss"


def test_an_unknown_vector_db_type_is_a_client_error(monkeypatch, db_session):
    """It used to reach the factory and surface as a 500."""

    import pytest
    from fastapi import HTTPException

    from app.api.v1.endpoints.documents import _resolve_document_vector_db_type

    monkeypatch.setattr(settings, "default_vector_db_type", "qdrant")
    ws = Workspace(id="ws-vdb-bad", name="Bad", slug="vdb-bad")
    db_session.add(ws)
    db_session.commit()

    with pytest.raises(HTTPException) as exc:
        _resolve_document_vector_db_type(ws, "pinecone")
    assert exc.value.status_code == 400
