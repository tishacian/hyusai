from __future__ import annotations

import sys
from types import SimpleNamespace

from app.services.rag import context as rag_context
from app.services.rag.context import get_retrieval_profile, retrieve_rag_context


class FakeDocumentService:
    async def get_document_count(self) -> int:
        return 12

    async def search(self, query: str, top_k: int = 10, filters=None, use_hybrid=None):
        return [
            {
                "id": "chunk-1",
                "content": f"{query} context",
                "score": 0.72,
                "metadata": {"document_title": "Manual", "page": 3},
            }
        ][:top_k]


class FakeSpreadsheetDuplicateService:
    async def get_document_count(self) -> int:
        return 3

    async def search(self, query: str, top_k: int = 10, filters=None, use_hybrid=None):  # noqa: ARG002
        return [
            {
                "content": (
                    "Spreadsheet sheet: test 2 Row 2: B2=Customer Row 4: B4=Material "
                    "and blend Row 5: O5=CONFIDENTIAL Row 7: B7=Date | C7=45798 | "
                    "Date = 45798 Row 8: C8=Speed | D8=196 | E8=m/min | F8=at | G8=winder"
                ),
                "score": 0.91,
                "metadata": {
                    "document_id": "geotex-workbook",
                    "document_filename": "GEOTEX-SPL-Y25.05.22-PIL.xlsx",
                },
            },
            {
                "content": (
                    "Spreadsheet sheet: test 1 Row 2: B2=Customer Row 4: B4=Material "
                    "and blend Row 5: O5=CONFIDENTIAL Row 7: B7=Date | C7=45798 | "
                    "Date = 45798 Row 8: C8=Speed | D8=196 | E8=m/min | F8=at | G8=winder"
                ),
                "score": 0.89,
                "metadata": {
                    "document_id": "geotex-workbook",
                    "document_filename": "GEOTEX-SPL-Y25.05.22-PIL.xlsx",
                },
            },
            {
                "content": (
                    "Spreadsheet sheet: Def strips Row 1: A1=A | B1=80 | A = 80 "
                    "Row 2: A2=B | B2=85 | B = 85 Row 3: A3=C | B3=90 | C = 90"
                ),
                "score": 0.86,
                "metadata": {
                    "document_id": "geotex-workbook",
                    "document_filename": "GEOTEX-SPL-Y25.05.22-PIL.xlsx",
                },
            },
        ][:top_k]


async def test_retrieve_rag_context_returns_serialisable_contract():
    result = await retrieve_rag_context(
        {
            "query": "pump pressure",
            "rag_pipeline_mode": "naive",
            "top_k": 1,
            "workspace_slug": "andritz",
        },
        doc_svc=FakeDocumentService(),
    )

    assert result["chunks"] == ["pump pressure context"]
    assert result["scores"] == [0.72]
    assert result["pipeline"] == "naive"
    assert result["mode_label"] == "vector_only"
    assert result["metrics"]["chunks_retrieved"] == 1
    assert result["metrics"]["duration_ms"] >= 0
    assert result["metrics"]["collection"] == "documents"
    assert result["metrics"]["vector_db"] == "faiss"
    assert result["collections_touched"] == ["documents"]
    assert result["collection_errors"] == []


async def test_retrieve_rag_context_dedupes_repeated_spreadsheet_boilerplate():
    result = await retrieve_rag_context(
        {
            "query": "diametre B",
            "rag_pipeline_mode": "naive",
            "top_k": 3,
            "workspace_slug": "andritz",
        },
        doc_svc=FakeSpreadsheetDuplicateService(),
    )

    assert len(result["chunks"]) == 2
    assert result["metrics"]["raw_chunks_retrieved"] == 3
    assert result["metrics"]["duplicates_removed"] == 1
    assert "Spreadsheet sheet: test 2" in result["chunks"][0]
    assert "Spreadsheet sheet: test 1" not in "\n".join(result["chunks"])
    assert "B = 85" in result["chunks"][1]
    assert len(result["scores"]) == len(result["chunks"]) == len(result["metadatas"])


async def test_retrieve_rag_context_exposes_multi_collection_metadata(monkeypatch):
    monkeypatch.setattr(
        rag_context,
        "get_resolved_settings",
        lambda **_kwargs: {
            "ragCollectionName": "documents",
            "ragVectorDBType": "qdrant",
            "ragTopK": 2,
            "ragPipelineMode": "chah",
        },
    )
    monkeypatch.setattr(
        rag_context,
        "resolve_knowledge_scope",
        lambda **_kwargs: {
            "key": "vigie",
            "label": "VIGIE",
            "collection_slugs": ["news", "agenda"],
            "default_mode": "chah",
            "top_k": 2,
        },
    )
    monkeypatch.setattr(
        rag_context,
        "_document_service_for_profile",
        lambda _profile, collection: SimpleNamespace(collection_name=collection),
    )
    async def _fake_resolve_retrieval_mode(*_args, **_kwargs):
        return True, "hybrid", "test"

    monkeypatch.setattr(rag_context, "resolve_retrieval_mode", _fake_resolve_retrieval_mode)

    async def _fake_retrieve(doc_svc, query, *_args, **_kwargs):
        return SimpleNamespace(
            chunks=[f"{doc_svc.collection_name}:{query}"],
            scores=[0.9],
            metadatas=[{"document_title": doc_svc.collection_name}],
            pipeline="chah",
            label="test",
            reason="test",
            detail="test",
        )

    monkeypatch.setattr(rag_context, "retrieve_for_mode", _fake_retrieve)

    result = await retrieve_rag_context(
        {
            "query": "signaux cabinet",
            "workspace_id": "workspace-sentinel",
            "workspace_slug": "sentinel-ci",
            "knowledge_scope": "vigie",
        }
    )

    assert result["collections_touched"] == ["news", "agenda"]
    assert result["collection_errors"] == []
    assert result["metrics"]["collections_touched"] == ["news", "agenda"]
    assert len(result["collection_results"]) == 2


def test_rag_retrieve_context_task_delegates_to_service(monkeypatch):
    class FakeCelery:
        def __init__(self, *_args, **_kwargs):
            self.conf = SimpleNamespace(update=lambda **_kwargs: None)

        def task(self, name=None):
            def _decorator(fn):
                return SimpleNamespace(run=fn, name=name)

            return _decorator

    monkeypatch.setitem(sys.modules, "celery", SimpleNamespace(Celery=FakeCelery))
    monkeypatch.setattr(
        "app.services.rag.context.run_rag_retrieve_context",
        lambda payload: {"chunks": [payload["query"]], "metrics": {"chunks_retrieved": 1}},
    )
    sys.modules.pop("app.workers.celery_app", None)
    sys.modules.pop("app.workers.tasks", None)
    try:
        from app.workers.tasks import rag_retrieve_context

        assert rag_retrieve_context.run({"query": "worker query"}) == {
            "chunks": ["worker query"],
            "metrics": {"chunks_retrieved": 1},
        }
    finally:
        sys.modules.pop("app.workers.celery_app", None)
        sys.modules.pop("app.workers.tasks", None)


def test_retrieval_profile_uses_workspace_default_rag_mode(monkeypatch):
    monkeypatch.setattr(
        rag_context,
        "get_resolved_settings",
        lambda **_kwargs: {
            "ragCollectionName": "sentinel-ci-open-intelligence",
            "ragVectorDBType": "qdrant",
            "ragTopK": 6,
            "ragPipelineMode": "chah",
        },
    )

    profile = get_retrieval_profile(
        {
            "query": "Quels signaux presse concernent la Cote d'Ivoire ?",
            "workspace_id": "workspace-sentinel",
            "workspace_slug": "sentinel-ci",
        }
    )

    assert profile["rag_mode"] == "chah"
    assert profile["collection"] == "sentinel-ci-open-intelligence"
    assert profile["vector_db"] == "qdrant"
    assert profile["top_k"] == 6


def test_retrieval_profile_uses_workspace_knowledge_scope(monkeypatch):
    monkeypatch.setattr(
        rag_context,
        "get_resolved_settings",
        lambda **_kwargs: {
            "ragCollectionName": "documents",
            "ragVectorDBType": "qdrant",
            "ragTopK": 5,
            "ragPipelineMode": "hybrid",
        },
    )
    monkeypatch.setattr(
        rag_context,
        "resolve_knowledge_scope",
        lambda **_kwargs: {
            "key": "vigie",
            "label": "Presse + Projets + Briefings + Carte",
            "collection_slugs": [
                "sentinel-ci-open-intelligence",
                "sentinel-ci-projects",
            ],
            "default_mode": "chah",
            "top_k": 8,
        },
    )

    profile = get_retrieval_profile(
        {
            "query": "Quels arbitrages sont attendus ?",
            "workspace_id": "workspace-sentinel",
            "workspace_slug": "sentinel-ci",
            "knowledge_scope": "vigie",
        }
    )

    assert profile["knowledge_scope"] == "vigie"
    assert profile["scope_label"] == "Presse + Projets + Briefings + Carte"
    assert profile["collection"] == "sentinel-ci-open-intelligence"
    assert profile["collections"] == [
        "sentinel-ci-open-intelligence",
        "sentinel-ci-projects",
    ]
    assert profile["rag_mode"] == "chah"
    assert profile["top_k"] == 8


def test_retrieval_profile_combines_scope_and_session_context(monkeypatch):
    monkeypatch.setattr(
        rag_context,
        "get_resolved_settings",
        lambda **_kwargs: {
            "ragCollectionName": "documents",
            "ragVectorDBType": "qdrant",
            "ragTopK": 5,
            "ragPipelineMode": "hybrid",
        },
    )
    monkeypatch.setattr(
        rag_context,
        "resolve_knowledge_scope",
        lambda **_kwargs: {
            "key": "non_wovens",
            "label": "NON-WOVENS France Excel pilot",
            "collection_slugs": ["andritz-non-wovens-france-excel-pilot"],
            "default_mode": "hybrid",
            "top_k": 5,
        },
    )

    profile = get_retrieval_profile(
        {
            "query": "diametre B",
            "workspace_id": "workspace-andritz",
            "workspace_slug": "andritz",
            "knowledge_scope": "non_wovens",
            "context_id": "ctx-drop",
            "context_collection": "documents",
            "context_mode": "combine",
        }
    )

    assert profile["knowledge_scope"] == "non_wovens"
    assert profile["scope_label"] == "NON-WOVENS France Excel pilot + Session docs"
    assert profile["collections"] == [
        "andritz-non-wovens-france-excel-pilot",
        "documents",
    ]
