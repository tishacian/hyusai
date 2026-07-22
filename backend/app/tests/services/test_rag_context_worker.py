from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta
from types import SimpleNamespace

from app.core.config import settings
from app.models.knowledge_document_fact import KnowledgeDocumentFact
from app.models.workspace import Workspace
from app.services.knowledge_collections import create_collection, upsert_collection_source
from app.services.rag import context as rag_context
from app.services.rag import corpus_planner as rag_corpus_planner
from app.services.rag.context import get_retrieval_profile, retrieve_rag_context
from app.services.rag.corpus_planner import classify_intent, is_catalogue_query, plan_corpus
from app.services.rag.retrieval_policy import RetrievalPolicy
from app.services.rag.summary_artifacts import rebuild_summary_index_artifact


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


class RecordingDenseService:
    def __init__(self, count: int = 150):
        self.count = count
        self.calls: list[dict] = []

    async def get_document_count(self) -> int:
        return self.count

    async def search(self, query: str, top_k: int = 10, filters=None, use_hybrid=None):
        self.calls.append(
            {
                "query": query,
                "top_k": top_k,
                "filters": filters,
                "use_hybrid": use_hybrid,
            }
        )
        return [
            {
                "id": "dense-1",
                "content": "bounded dense result",
                "score": 0.77,
                "metadata": {"document_filename": "manual.html"},
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


class FakeSpreadsheetLabelService:
    def __init__(self):
        self.queries: list[str] = []

    async def get_document_count(self) -> int:
        return 26

    async def search(self, query: str, top_k: int = 10, filters=None, use_hybrid=None):  # noqa: ARG002
        self.queries.append(query)
        if "Def strips" in query or "B =" in query:
            return [
                {
                    "content": (
                        "Spreadsheet sheet: Def strips Row 1: A1=A | B1=80 | A = 80 "
                        "Row 2: A2=B | B2=85 | B = 85 Row 3: A3=C | B3=90 | C = 90"
                    ),
                    "score": 0.96,
                    "metadata": {
                        "document_id": "geotex-def-strips",
                        "document_filename": "GEOTEX-SPL-Y25.05.22-PIL.xlsx",
                        "sheet_name": "Def strips",
                        "row_start": 1,
                        "row_end": 3,
                    },
                }
            ][:top_k]
        return [
            {
                "content": (
                    "Spreadsheet sheet: CD N et % Row 3: C3=1 | D3=2 | E3=3 | "
                    "Row 4: B4=CD (N/50 mm) | C4=250.41"
                ),
                "score": 0.91,
                "metadata": {"document_id": "noise-1", "document_filename": "analyse voile.xlsx"},
            },
            {
                "content": (
                    "Spreadsheet sheet: MD N et % Row 3: C3=1 | D3=2 | E3=3 | "
                    "Row 4: B4=MD (N/50 mm) | C4=333.251"
                ),
                "score": 0.9,
                "metadata": {"document_id": "noise-2", "document_filename": "analyse voile.xlsx"},
            },
        ][:top_k]


class FakeSpreadsheetProtocolFirstService:
    async def get_document_count(self) -> int:
        return 26

    async def search(self, query: str, top_k: int = 10, filters=None, use_hybrid=None):  # noqa: ARG002
        return [
            {
                "content": (
                    "Spreadsheet sheet: Protocole essais Row 1: A1=Customer | B1=GEOTEX "
                    "Row 4: A4=trials N° | J4=3B | K4=3C Row 100: A100=I51 | B100=Strip"
                ),
                "score": 0.98,
                "metadata": {"document_id": "protocol", "document_filename": "GEOTEX-SPL-Y25.05.22-PIL.xlsx"},
            },
            {
                "content": (
                    "Spreadsheet sheet: Def strips Row 1: A1=A | B1=80 | A = 80 "
                    "Row 2: A2=B | B2=85 | B = 85 Row 3: A3=C | B3=90 | C = 90"
                ),
                "score": 0.84,
                "metadata": {
                    "document_id": "def-strips",
                    "document_filename": "GEOTEX-SPL-Y25.05.22-PIL.xlsx",
                    "sheet_name": "Def strips",
                },
            },
        ][:top_k]


class FakeEmptyRecordingService:
    def __init__(self):
        self.queries: list[str] = []

    async def get_document_count(self) -> int:
        return 1

    async def search(self, query: str, top_k: int = 10, filters=None, use_hybrid=None):  # noqa: ARG002
        self.queries.append(query)
        return []


class FakePolicyRankingService:
    async def get_document_count(self) -> int:
        return 2

    async def search(self, query: str, top_k: int = 10, filters=None, use_hybrid=None):  # noqa: ARG002
        return [
            {
                "content": "Table of contents menu previous next index",
                "score": 0.99,
                "metadata": {"document_filename": "index.html"},
            },
            {
                "content": "AKK200 proximity switch XS1 sensor wiring procedure.",
                "score": 0.2,
                "metadata": {
                    "document_filename": "AKK200 manual.html",
                    "project_code": "AKK200",
                    "source_family": "operating_manual",
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


def test_exact_match_guardrail_context_is_prepended_when_required_code_is_missing():
    chunks, scores, metadatas, count = rag_context._prepend_exact_match_guardrail_context(
        ["Dense neighbor background"],
        [0.91],
        [{"document_filename": "generic.pdf"}],
        query="Find component catalogue PRJ204",
        policy=RetrievalPolicy(),
        diagnostics={
            "exact_metadata_attempted": True,
            "exact_metadata_hits": 0,
            "exact_match_required": True,
            "exact_match_missing": True,
        },
    )

    assert count == 1
    assert chunks[0].startswith("Retrieval exact-match guardrail.")
    assert "PRJ204" in chunks[0]
    assert metadatas[0]["semantic_type"] == "exact_match_guardrail"
    assert chunks[1] == "Dense neighbor background"


def _missing_exact_metadata_diagnostics() -> dict[str, object]:
    return {
        "exact_metadata_attempted": True,
        "exact_metadata_hits": 0,
        "exact_match_required": True,
        "exact_match_missing": True,
    }


def test_empty_exact_terms_never_satisfy_project_scope_guardrail():
    assert not rag_context._requested_terms_are_only_project_scope(set(), {"61035"})


def test_exact_match_guardrail_accepts_matching_needlepunch_project_scope():
    chunks = ["Needlepunch technical notice for the requested project."]
    scores = [0.93]
    metadatas = [{"document_filename": "notice.pdf", "project_code": "61035"}]

    result = rag_context._prepend_exact_match_guardrail_context(
        chunks,
        scores,
        metadatas,
        query="Résume le projet 61035",
        policy=RetrievalPolicy(),
        diagnostics=_missing_exact_metadata_diagnostics(),
        retrieval_filters={"project_code": ["61035"]},
    )

    assert result == (chunks, scores, metadatas, 0)


def test_exact_match_guardrail_rejects_wrong_or_missing_needlepunch_project_metadata():
    for metadata in (
        {"document_filename": "wrong-project.pdf", "project_code": "61001"},
        {"document_filename": "missing-project.pdf"},
    ):
        (
            chunks,
            _scores,
            metadatas,
            count,
        ) = rag_context._prepend_exact_match_guardrail_context(
            ["Dense neighbor background"],
            [0.91],
            [metadata],
            query="Résume le projet 61035",
            policy=RetrievalPolicy(),
            diagnostics=_missing_exact_metadata_diagnostics(),
            retrieval_filters={"project_code": ["61035"]},
        )

        assert count == 1
        assert chunks[0].startswith("Retrieval exact-match guardrail.")
        assert metadatas[0]["semantic_type"] == "exact_match_guardrail"


def test_exact_match_guardrail_keeps_unmatched_document_identifier_under_project_scope():
    (
        chunks,
        _scores,
        metadatas,
        count,
    ) = rag_context._prepend_exact_match_guardrail_context(
        ["Project 61035 background without the requested document."],
        [0.91],
        [{"document_filename": "other-document.pdf", "project_code": "61035"}],
        query="Trouve TTN17829J pour le projet 61035",
        policy=RetrievalPolicy(),
        diagnostics=_missing_exact_metadata_diagnostics(),
        retrieval_filters={"project_code": ["61035"]},
    )

    assert count == 1
    assert chunks[0].startswith("Retrieval exact-match guardrail.")
    assert "TTN17829J" in chunks[0]
    assert metadatas[0]["semantic_type"] == "exact_match_guardrail"


def test_exact_match_guardrail_preserves_spl_project_metadata_match():
    chunks = ["Historical SPL project summary."]
    scores = [0.92]
    metadatas = [{"document_filename": "BAO100-manual.pdf", "project_code": "BAO100"}]

    result = rag_context._prepend_exact_match_guardrail_context(
        chunks,
        scores,
        metadatas,
        query="Résume le projet BAO100",
        policy=RetrievalPolicy(),
        diagnostics=_missing_exact_metadata_diagnostics(),
    )

    assert result == (chunks, scores, metadatas, 0)


async def test_retrieve_rag_context_applies_similarity_threshold(monkeypatch):
    monkeypatch.setattr(rag_context.settings, "rag_similarity_threshold", 0.2)

    async def _fake_retrieve(doc_svc, query, mode, **kwargs):  # noqa: ARG001
        return SimpleNamespace(
            chunks=["weak dense chunk", "strong dense chunk"],
            scores=[0.19, 0.82],
            metadatas=[
                {"document_filename": "weak.md"},
                {"document_filename": "strong.md"},
            ],
            pipeline="naive",
            label="vector_only",
            reason="fake dense",
            detail="test",
            diagnostics={},
        )

    monkeypatch.setattr(rag_context, "retrieve_for_mode", _fake_retrieve)

    result = await retrieve_rag_context(
        {
            "query": "maintenance pump",
            "latency_profile": "fast",
            "rag_pipeline_mode": "naive",
        },
        doc_svc=FakeDocumentService(),
    )

    assert result["chunks"] == ["strong dense chunk"]
    assert result["metrics"]["score_threshold_applied"] is True
    assert result["metrics"]["score_threshold_filtered"] == 1
    assert result["metrics"]["score_threshold"] == 0.2


async def test_retrieve_rag_context_skips_similarity_threshold_for_rrf(monkeypatch):
    monkeypatch.setattr(rag_context.settings, "rag_similarity_threshold", 0.2)

    async def _fake_retrieve(doc_svc, query, mode, **kwargs):  # noqa: ARG001
        return SimpleNamespace(
            chunks=["rrf sparse chunk", "rrf dense chunk"],
            scores=[0.031, 0.028],
            metadatas=[
                {"document_filename": "sparse.md"},
                {"document_filename": "dense.md"},
            ],
            pipeline="chah_backend",
            label="C-HAH",
            reason="fake rrf",
            detail="test",
            diagnostics={"sparse_backend": "opensearch", "sparse_status": "ok"},
        )

    monkeypatch.setattr(rag_context, "retrieve_for_mode", _fake_retrieve)

    result = await retrieve_rag_context(
        {
            "query": "maintenance pump",
            "latency_profile": "balanced",
            "rag_pipeline_mode": "chah",
        },
        doc_svc=FakeDocumentService(),
    )

    assert result["chunks"] == ["rrf sparse chunk", "rrf dense chunk"]
    assert result["metrics"]["score_threshold_applied"] is False
    assert result["metrics"]["score_threshold_skipped_reason"] == "non_vector_score_scale"
    assert result["metrics"]["dense_only"] is False
    assert result["metrics"]["duration_ms"] >= 0
    assert set(result["metrics"]["stage_timings"]) >= {
        "planner_ms",
        "retrieval_ms",
        "rerank_ms",
        "context_build_ms",
        "table_facts_ms",
        "total_ms",
    }
    assert result["metrics"]["stage_timings"]["retrieval_ms"] >= 0
    assert result["metrics"]["stage_timings"]["rerank_ms"] >= 0
    assert result["metrics"]["candidate_counts"]["chunks_retrieved"] == 2
    assert result["metrics"]["candidate_counts"]["candidate_pool_k"] >= 1
    assert "exact_table_hits" in result["metrics"]["candidate_counts"]
    assert result["metrics"]["collection"] == "documents"
    assert result["metrics"]["vector_db"] == "qdrant"
    assert result["collections_touched"] == ["documents"]
    assert result["collection_errors"] == []


async def test_oracle_fast_standard_scope_prefers_native_qdrant_hybrid(monkeypatch):
    monkeypatch.setattr(rag_context.settings, "rag_qdrant_sparse_enabled", True)
    monkeypatch.setattr(rag_context.settings, "rag_sparse_backend", "auto")
    monkeypatch.setattr(rag_context, "plan_corpus", lambda **_kwargs: (_ for _ in ()).throw(AssertionError("planner skipped")))
    captured = {}

    async def _fake_retrieve(doc_svc, query, mode, **kwargs):  # noqa: ARG001
        captured.update({"mode": mode, **kwargs})
        return SimpleNamespace(
            chunks=["hybrid qdrant chunk"],
            scores=[0.031],
            metadatas=[{"document_filename": "manual.md", "sparse_backend": "qdrant_sparse", "sparse_status": "ok"}],
            pipeline="hybrid",
            label="hybrid_rrf",
            reason="native qdrant hybrid",
            detail="test",
            diagnostics={"sparse_backend": "qdrant_sparse", "sparse_status": "ok"},
        )

    monkeypatch.setattr(rag_context, "retrieve_for_mode", _fake_retrieve)

    result = await retrieve_rag_context(
        {
            "query": "prélecture capture vibration",
            "retrieval_profile": "oracle_fast",
            "rag_pipeline_mode": "auto",
        },
        doc_svc=FakeDocumentService(),
    )

    assert captured["mode"] == "naive"
    assert captured["use_hybrid"] is True
    assert captured["allow_legacy_hybrid"] is False
    assert result["use_hybrid"] is True
    assert result["metrics"]["dense_only"] is False
    assert result["metrics"]["sparse_backend"] == "qdrant_sparse"


async def test_explicit_dense_mode_keeps_native_qdrant_hybrid_opt_out(monkeypatch):
    monkeypatch.setattr(rag_context.settings, "rag_qdrant_sparse_enabled", True)
    monkeypatch.setattr(rag_context.settings, "rag_sparse_backend", "auto")
    captured = {}

    async def _fake_retrieve(doc_svc, query, mode, **kwargs):  # noqa: ARG001
        captured.update({"mode": mode, **kwargs})
        return SimpleNamespace(
            chunks=["dense chunk"],
            scores=[0.72],
            metadatas=[{"document_filename": "manual.md"}],
            pipeline="naive",
            label="vector_only",
            reason="explicit dense",
            detail="test",
            diagnostics={},
        )

    monkeypatch.setattr(rag_context, "retrieve_for_mode", _fake_retrieve)

    result = await retrieve_rag_context(
        {
            "query": "prélecture capture vibration",
            "retrieval_profile": "chat",
            "rag_pipeline_mode": "dense",
        },
        doc_svc=FakeDocumentService(),
    )

    assert captured["mode"] == "dense"
    assert captured["use_hybrid"] is False
    assert captured["allow_legacy_hybrid"] is True
    assert result["use_hybrid"] is False
    assert result["metrics"]["dense_only"] is True


async def test_retrieve_rag_context_diversifies_synthesis_window_by_document(monkeypatch):
    monkeypatch.setattr(rag_context.settings, "rag_similarity_threshold", 0.0)

    async def _fake_retrieve(doc_svc, query, mode, **kwargs):  # noqa: ARG001
        return SimpleNamespace(
            chunks=[
                "doc A best",
                "doc A second",
                "doc A third",
                "doc B first",
            ],
            scores=[0.95, 0.93, 0.91, 0.55],
            metadatas=[
                {"document_id": "doc-a"},
                {"document_id": "doc-a"},
                {"document_id": "doc-a"},
                {"document_id": "doc-b"},
            ],
            pipeline="naive",
            label="vector_only",
            reason="fake dense",
            detail="test",
            diagnostics={},
        )

    monkeypatch.setattr(rag_context, "retrieve_for_mode", _fake_retrieve)

    result = await retrieve_rag_context(
        {
            "query": "maintenance pump",
            "latency_profile": "balanced",
            "rag_pipeline_mode": "naive",
            "top_k": 3,
            "source_display_k": 3,
            "synthesis_k": 3,
            "candidate_pool_k": 6,
        },
        doc_svc=FakeDocumentService(),
    )

    assert result["chunks"] == ["doc A best", "doc B first", "doc A second"]
    assert result["metrics"]["document_diversity_applied"] is True
    assert result["metrics"]["document_diversity_groups"] == 2


async def test_retrieve_rag_context_inventory_query_uses_collection_source_ledger(db_session):
    workspace = Workspace(id="ws-inventory", name="Inventory", slug="inventory")
    db_session.add(workspace)
    db_session.commit()
    collection = create_collection(db_session, workspace=workspace, name="Manuals")
    upsert_collection_source(
        db_session,
        collection=collection,
        filename="manual-bba120.pdf",
        status="ready",
        mime_type="application/pdf",
        size_bytes=1200,
        chunk_count=7,
    )
    upsert_collection_source(
        db_session,
        collection=collection,
        filename="essais-geotex.xlsx",
        status="ready",
        mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        size_bytes=2400,
        chunk_count=11,
    )
    db_session.commit()

    result = await retrieve_rag_context(
        {
            "query": "Combien de documents as-tu et quels types de sources ?",
            "context_collection": collection.slug,
            "workspace_id": workspace.id,
            "workspace_slug": workspace.slug,
        }
    )

    assert result["pipeline"] == "collection_inventory"
    assert result["inventory"]["total_sources"] == 2
    assert result["inventory"]["total_chunks"] == 18
    assert result["inventory"]["collections"][0]["by_kind"] == {"pdf": 1, "spreadsheet": 1}
    assert "Total sources: 2" in result["chunks"][0]
    assert "essais-geotex.xlsx" in result["chunks"][0]
    assert result["metrics"]["stage_timings"]["inventory_ms"] >= 0
    assert result["metrics"]["candidate_counts"]["source_count"] == 2
    assert result["metrics"]["candidate_counts"]["chunk_count"] == 18


async def test_retrieve_rag_context_data_catalogue_phrase_uses_inventory(db_session):
    workspace = Workspace(id="ws-data-catalogue", name="Data Catalogue", slug="data-catalogue")
    db_session.add(workspace)
    db_session.commit()
    collection = create_collection(db_session, workspace=workspace, name="SPL")
    upsert_collection_source(
        db_session,
        collection=collection,
        filename="A__ACJ100__manual.html",
        status="ready",
        chunk_count=3,
    )
    db_session.commit()

    result = await retrieve_rag_context(
        {
            "query": "De quelles données disposes-tu ?",
            "context_collection": collection.slug,
            "workspace_id": workspace.id,
            "workspace_slug": workspace.slug,
        }
    )

    assert result["pipeline"] == "collection_inventory"
    assert result["use_hybrid"] is False
    assert result["inventory"]["total_sources"] == 1
    assert result["metrics"]["stage_timings"]["inventory_ms"] >= 0


def test_source_lookup_questions_are_not_inventory_queries():
    assert rag_context.is_collection_inventory_query("De quelles données disposes-tu ?") is True
    assert (
        rag_context.is_collection_inventory_query(
            "Dans AKK200, je cherche la reference Filtering cartridge LM300 : quelle source faut-il ouvrir ?"
        )
        is False
    )
    assert (
        rag_context.is_collection_inventory_query(
            "AKK200 vacuum maintenance : quel document source dois-je citer ?"
        )
        is False
    )
    assert (
        rag_context.is_collection_inventory_query(
            "Je veux ouvrir la liste de pieces BBA 120, quelle source est la bonne ?"
        )
        is False
    )


async def test_retrieve_rag_context_catalogue_applies_internal_scope_filters(db_session, monkeypatch):
    workspace = Workspace(id="ws-data-catalogue-scope", name="Scoped Catalogue", slug="scoped-catalogue")
    db_session.add(workspace)
    db_session.commit()
    collection = create_collection(db_session, workspace=workspace, name="Scoped SPL")
    for filename, project, chunks in (
        ("A__ACJ100__manual.html", "ACJ100", 120_000),
        ("B__ZZZ900__manual.html", "ZZZ900", 80_000),
    ):
        upsert_collection_source(
            db_session,
            collection=collection,
            filename=filename,
            status="ready",
            chunk_count=chunks,
            source_metadata={"project_code": project, "document_id": filename},
        )
    collection.chunk_count = 200_000
    collection.document_count = 2
    db_session.commit()

    async def fail_vector_search(*args, **kwargs):
        raise AssertionError("catalogue scoped inventory must not call vector retrieval")

    monkeypatch.setattr(rag_context, "retrieve_for_mode", fail_vector_search)

    result = await retrieve_rag_context(
        {
            "query": "Quels fichiers ACJ100 as-tu dans cette collection ?",
            "context_collection": collection.slug,
            "workspace_id": workspace.id,
            "workspace_slug": workspace.slug,
            "retrieval_filters": {"project_code": "ACJ100"},
        }
    )

    assert result["pipeline"] == "collection_inventory"
    assert result["inventory"]["total_sources"] == 2
    assert result["inventory"]["collections"][0]["sources_total"] == 1
    assert result["inventory"]["collections"][0]["source_filters"]["project_code"] == "ACJ100"
    assert result["metrics"]["inventory_filtered_sources"] == 1
    assert result["metrics"]["dense_policy"] == "catalogue_inventory"
    assert "Sources matching system scope: 1" in result["chunks"][0]
    assert "A__ACJ100__manual.html" in result["chunks"][0]
    assert "B__ZZZ900__manual.html" not in result["chunks"][0]


def test_corpus_planner_uses_normalized_source_kind_aliases(db_session):
    workspace = Workspace(id="ws-planner-kind-alias", name="Planner Kind", slug="planner-kind")
    db_session.add(workspace)
    db_session.commit()
    collection = create_collection(db_session, workspace=workspace, name="Planner Kind SPL")
    upsert_collection_source(
        db_session,
        collection=collection,
        filename="manual.html",
        status="ready",
        chunk_count=3,
    )
    upsert_collection_source(
        db_session,
        collection=collection,
        filename="measurements.xls",
        status="ready",
        chunk_count=4,
    )
    db_session.commit()

    html_plan = plan_corpus(
        db=db_session,
        profile={"collection": collection.slug, "collections": [collection.slug], "workspace_id": workspace.id},
        query="Cherche dans les fichiers html",
    )
    excel_plan = plan_corpus(
        db=db_session,
        profile={"collection": collection.slug, "collections": [collection.slug], "workspace_id": workspace.id},
        query="Cherche dans les fichiers excel",
    )

    assert html_plan.filters["extension"] == "html"
    assert html_plan.filters["source_kind"] == "markup"
    assert excel_plan.filters == {"source_kind": "spreadsheet"}


def test_corpus_planner_accepts_system_scope_filter_fields(db_session):
    workspace = Workspace(id="ws-planner-system-filters", name="Planner Filters", slug="planner-filters")
    db_session.add(workspace)
    db_session.commit()
    collection = create_collection(db_session, workspace=workspace, name="Planner Filters SPL")
    upsert_collection_source(
        db_session,
        collection=collection,
        filename="manual.html",
        status="ready",
        chunk_count=3,
    )
    db_session.commit()

    plan = plan_corpus(
        db=db_session,
        profile={"collection": collection.slug, "collections": [collection.slug], "workspace_id": workspace.id},
        query="Explique la procédure",
        request={
            "retrieval_filters": {
                "collection": collection.slug,
                "collection_slug": collection.slug,
                "language": "fr",
                "ignored": "nope",
            }
        },
    )

    assert plan.filters == {
        "collection": collection.slug,
        "collection_slug": collection.slug,
        "language": "fr",
    }
    assert plan.scope_confidence == 0.95


def test_catalogue_query_accepts_docs_abbreviation():
    assert is_catalogue_query("combien de docs as tu ?")
    assert is_catalogue_query("quels types de docs as-tu ?")
    assert not is_catalogue_query("quelle source contient Filtering cartridge LM 300 ?")
    assert classify_intent("Dans les fichiers NON-WOVENS France, que vaut le label B dans la table Def strips ?") == "content_search"
    assert classify_intent("Dans le projet AKK200, quelle source contient Filtering cartridge LM 300 ?") == "source_lookup"


def test_project_summary_with_citation_words_is_not_catalogue():
    queries = (
        # Needlepunch numeric5 project reference (live regression).
        "Résume le projet 61035 en citant précisément les documents utilisés.",
        # Historical SPL project reference, including polite source wording
        # that would otherwise hit the source-lookup branch first.
        "Peux-tu résumer le projet BAO100 avec les sources et documents utilisés ?",
    )

    for query in queries:
        assert not is_catalogue_query(query), query
        assert classify_intent(query) == "content_search", query
        assert not rag_context.is_collection_inventory_query(query), query


def test_explicit_project_catalogue_requests_remain_catalogue():
    queries = (
        "Combien de documents sont disponibles pour le projet 61035 ?",
        "Dresse l'inventaire des sources du projet BAO100.",
        "Quel catalogue de documents existe pour le projet 61035 ?",
    )

    for query in queries:
        assert is_catalogue_query(query), query
        assert classify_intent(query) == "catalogue", query
        assert rag_context.is_collection_inventory_query(query), query


def test_table_value_lookup_scopes_to_spreadsheets_without_payload_kind_filter(db_session):
    workspace = Workspace(id="ws-planner-table-spreadsheet", name="Planner Tables", slug="planner-tables")
    db_session.add(workspace)
    db_session.commit()
    manuals_collection = create_collection(db_session, workspace=workspace, name="Manuals")
    spreadsheet_collection = create_collection(db_session, workspace=workspace, name="NON-WOVENS France Excel")
    upsert_collection_source(
        db_session,
        collection=manuals_collection,
        filename="BBA120 manual.pdf",
        status="ready",
        chunk_count=12,
    )
    upsert_collection_source(
        db_session,
        collection=spreadsheet_collection,
        filename="1-NON-WOVENS/FRANCE/GEOTEX/GEOTEX-SPL-Y25.05.22-PIL.xlsx",
        status="ready",
        chunk_count=80,
    )
    db_session.commit()

    plan = plan_corpus(
        db=db_session,
        profile={
            "collection": manuals_collection.slug,
            "collections": [manuals_collection.slug],
            "workspace_id": workspace.id,
            "latency_profile": "fast",
            "rag_mode": "chah",
        },
        query="Dans les fichiers NON-WOVENS France, que vaut le label B dans la table Def strips ?",
    )

    assert plan.retrieval_scope["collections"] == [spreadsheet_collection.slug]
    assert plan.filters == {}


def test_ledger_source_scope_drops_legacy_payload_status_filter(db_session, monkeypatch):
    monkeypatch.setattr(rag_context.settings, "rag_dense_chunk_threshold", 100)
    monkeypatch.setattr(rag_context.settings, "rag_dense_source_threshold", 2)
    workspace = Workspace(id="ws-planner-ledger-status", name="Planner Ledger Status", slug="planner-ledger-status")
    db_session.add(workspace)
    db_session.commit()
    collection = create_collection(db_session, workspace=workspace, name="Dense SPL")
    for filename in (
        "ARA200__fichiers__users manual__section 3__conveyor.html",
        "ARA200__fichiers__users manual__Annexes__520-convoyeur__conveyor-jetlace-gb b.pdf",
        "ARA200__fichiers__menu__index.html",
    ):
        upsert_collection_source(
            db_session,
            collection=collection,
            filename=filename,
            status="ready",
            chunk_count=150,
        )
    db_session.commit()

    plan = plan_corpus(
        db=db_session,
        profile={
            "collection": collection.slug,
            "collections": [collection.slug],
            "workspace_id": workspace.id,
            "latency_profile": "fast",
            "rag_mode": "chah",
        },
        query="Quels documents de convoyeur sont indexés pour ARA200 ?",
    )

    assert plan.dense_policy == "fast_scoped_dense"
    assert "status" not in plan.filters
    assert "document_filename" in plan.filters
    assert "ARA200__fichiers__users manual__section 3__conveyor.html" in plan.filters["document_filename"]


def test_scoped_dense_naive_uses_single_pass_hybrid_unless_dense_only_requested(db_session, monkeypatch):
    monkeypatch.setattr(rag_context.settings, "rag_dense_chunk_threshold", 100)
    monkeypatch.setattr(rag_context.settings, "rag_dense_source_threshold", 2)
    workspace = Workspace(id="ws-planner-oracle-hybrid", name="Planner Oracle Hybrid", slug="planner-oracle-hybrid")
    db_session.add(workspace)
    db_session.commit()
    collection = create_collection(db_session, workspace=workspace, name="Dense SPL")
    for filename in (
        "ARA200__fichiers__users manual__section 3__conveyor.html",
        "ARA200__fichiers__users manual__Annexes__520-convoyeur__conveyor-jetlace-gb b.pdf",
        "ARA200__fichiers__menu__index.html",
    ):
        upsert_collection_source(
            db_session,
            collection=collection,
            filename=filename,
            status="ready",
            chunk_count=150,
        )
    db_session.commit()
    base_profile = {
        "collection": collection.slug,
        "collections": [collection.slug],
        "workspace_id": workspace.id,
        "latency_profile": "fast",
    }

    oracle_plan = plan_corpus(
        db=db_session,
        profile={**base_profile, "rag_mode": "naive"},
        query="Find the ARA200 conveyor procedure",
    )
    dense_plan = plan_corpus(
        db=db_session,
        profile={**base_profile, "rag_mode": "dense"},
        query="Find the ARA200 conveyor procedure",
    )

    assert oracle_plan.dense_policy == "fast_scoped_dense"
    assert oracle_plan.allow_legacy_hybrid is False
    assert oracle_plan.allow_hah_chah is False
    assert oracle_plan.use_hybrid is True
    assert "document_filename" in oracle_plan.filters
    assert dense_plan.use_hybrid is False


def test_dense_planner_scopes_golden_source_lookup_from_ledger(db_session, monkeypatch):
    monkeypatch.setattr(rag_context.settings, "rag_dense_chunk_threshold", 100)
    monkeypatch.setattr(rag_context.settings, "rag_dense_source_threshold", 2)
    workspace = Workspace(id="ws-planner-golden-spl", name="Planner Golden SPL", slug="planner-golden")
    db_session.add(workspace)
    db_session.commit()
    spl_collection = create_collection(db_session, workspace=workspace, name="Dense SPL")
    bba_collection = create_collection(db_session, workspace=workspace, name="Manuals BBA120")
    injector_collection = create_collection(db_session, workspace=workspace, name="Injectors DCI110 ACO")
    for collection, filename in (
        (spl_collection, "spare part list ACO150.pdf"),
        (spl_collection, "ACO150__fichiers__menu__index.html"),
        (spl_collection, "ACO150__fichiers__pictures__fond.jpg"),
        (spl_collection, "AKK200__English version__files__section_IV__Hydroentanglement-unit__sub-section_6__Spare Parts List AKK200_Ind A.pdf"),
        (spl_collection, "AKK200__English version__files__section_IV__Hydroentanglement-unit__sub-section_4__Filtration_maintenance.html"),
        (bba_collection, "Spare Parts List_BBA120.pdf"),
        (bba_collection, "Etachrom B.PDF"),
        (injector_collection, "IN 07 A- EXH injector cartridge cleaning.pdf"),
        (injector_collection, "DCI 110__PERFO-TE-OM-10-5 EN-C.pdf"),
    ):
        upsert_collection_source(
            db_session,
            collection=collection,
            filename=filename,
            status="ready",
            chunk_count=150,
        )
    db_session.commit()
    profile = {
        "collection": spl_collection.slug,
        "collections": [spl_collection.slug, bba_collection.slug, injector_collection.slug],
        "workspace_id": workspace.id,
        "latency_profile": "fast",
        "rag_mode": "chah",
    }

    aco_plan = plan_corpus(
        db=db_session,
        profile=profile,
        query="Peux-tu retrouver la Spare Parts List du projet ACO150 ?",
    )
    bba_plan = plan_corpus(
        db=db_session,
        profile=profile,
        query="Peux-tu retrouver la Spare Parts List du projet BBA120 ?",
    )
    etachrom_plan = plan_corpus(
        db=db_session,
        profile=profile,
        query="Quel document couvre la pompe KSB Etachrom dans BBA120 ?",
    )
    injector_plan = plan_corpus(
        db=db_session,
        profile=profile,
        query="Comment dois-je nettoyer les cartouches d'injecteurs ?",
    )
    dci_plan = plan_corpus(
        db=db_session,
        profile=profile,
        query="Comment retirer le strip-carrier d'un injecteur dans DCI110 ?",
    )
    akk_parts_plan = plan_corpus(
        db=db_session,
        profile=profile,
        query="Dans le projet AKK200, quelle source contient Filtering cartridge LM 300 et O-ring string D. 3,6 ?",
    )

    for plan in (aco_plan, bba_plan, etachrom_plan, injector_plan, dci_plan, akk_parts_plan):
        assert plan.dense_policy == "fast_scoped_dense"
        assert plan.fallback_reason is None
        assert "document_filename" in plan.filters
        assert plan.retrieval_plan["layers"]["dense_qdrant"]["enabled"] is True
        assert plan.retrieval_plan["layers"]["deep_async"]["enabled"] is False

    assert "spare part list ACO150.pdf" in aco_plan.filters["document_filename"]
    assert "ACO150__fichiers__menu__index.html" not in aco_plan.filters["document_filename"]
    assert "ACO150__fichiers__pictures__fond.jpg" not in aco_plan.filters["document_filename"]
    assert "Spare Parts List_BBA120.pdf" in bba_plan.filters["document_filename"]
    assert "Etachrom B.PDF" in etachrom_plan.filters["document_filename"]
    assert "IN 07 A- EXH injector cartridge cleaning.pdf" in injector_plan.filters["document_filename"]
    assert "DCI 110__PERFO-TE-OM-10-5 EN-C.pdf" in dci_plan.filters["document_filename"]
    assert (
        "AKK200__English version__files__section_IV__Hydroentanglement-unit__sub-section_6__Spare Parts List AKK200_Ind A.pdf"
        in akk_parts_plan.filters["document_filename"]
    )
    assert (
        "AKK200__English version__files__section_IV__Hydroentanglement-unit__sub-section_4__Filtration_maintenance.html"
        not in akk_parts_plan.filters["document_filename"]
    )

    narrow_plan = plan_corpus(
        db=db_session,
        profile={
            "collection": bba_collection.slug,
            "collections": [bba_collection.slug],
            "workspace_id": workspace.id,
            "latency_profile": "fast",
            "rag_mode": "auto",
        },
        query="Peux-tu retrouver la Spare Parts List du projet ACO150 ?",
    )
    assert narrow_plan.retrieval_scope["collections"] == [spl_collection.slug]
    assert narrow_plan.dense_policy == "fast_scoped_dense"
    assert "spare part list ACO150.pdf" in narrow_plan.filters["document_filename"]
    assert "ACO150__fichiers__menu__index.html" not in narrow_plan.filters["document_filename"]

    legacy_collection = create_collection(db_session, workspace=workspace, name="Legacy Document Names")
    legacy_collection.document_names = ["Legacy Spare Parts List ACO999.pdf"]
    legacy_collection.document_count = 1
    legacy_collection.chunk_count = 150
    db_session.commit()
    legacy_plan = plan_corpus(
        db=db_session,
        profile={
            "collection": bba_collection.slug,
            "collections": [bba_collection.slug],
            "workspace_id": workspace.id,
            "latency_profile": "fast",
            "rag_mode": "auto",
        },
        query="Peux-tu retrouver la Spare Parts List du projet ACO999 ?",
    )
    assert legacy_plan.retrieval_scope["collections"] == [legacy_collection.slug]
    assert legacy_plan.dense_policy == "fast_scoped_dense"
    assert "Legacy Spare Parts List ACO999.pdf" in legacy_plan.filters["document_filename"]


def test_large_collection_balanced_scopes_project_code_from_document_names(db_session, monkeypatch):
    """Regression for the BBA120 "trop dense" bail.

    On a large/ledger-backed collection a project's documents can live only in
    collection.document_names (and Qdrant), never in knowledge_collection_sources.
    The bounded interactive targeting must still consult document_names so a
    project-scoped question infers a document scope instead of bailing to the
    dense_unscoped_fast_policy degraded reply.
    """
    monkeypatch.setattr(rag_context.settings, "rag_dense_chunk_threshold", 100)
    monkeypatch.setattr(rag_context.settings, "rag_dense_source_threshold", 2)
    workspace = Workspace(id="ws-planner-large-docnames", name="Planner Large DocNames", slug="planner-large-docnames")
    db_session.add(workspace)
    db_session.commit()
    collection = create_collection(db_session, workspace=workspace, name="Dense SPL DocNames")
    # A genuinely large collection (> _LEDGER_TARGETING_MIN_CHUNKS) so the
    # planner takes the bounded targeting path, with BBA120 present only in
    # document_names — exactly the production shape on andritz-notices-spl-pilot.
    collection.document_names = [
        "Manual_BBA120__PHP _URACA___KD724-G - PHP11__Chapter 01.pdf",
        "Manual_BBA120__Spare part list__Spare Parts List_BBA120.pdf",
        "R__RCZ100__RCZ100__fichiers__users manual__conveyor.pdf",
    ]
    collection.document_count = 99481
    collection.chunk_count = 1489764
    db_session.commit()

    plan = plan_corpus(
        db=db_session,
        profile={
            "collection": collection.slug,
            "collections": [collection.slug],
            "workspace_id": workspace.id,
            "latency_profile": "balanced",
            "rag_mode": "chah",
        },
        query="resume le projet BBA120",
    )

    assert plan.dense_policy == "fast_scoped_dense"
    assert plan.fallback_reason is None
    assert "document_filename" in plan.filters
    scoped = plan.filters["document_filename"]
    assert "Manual_BBA120__PHP _URACA___KD724-G - PHP11__Chapter 01.pdf" in scoped
    assert "Manual_BBA120__Spare part list__Spare Parts List_BBA120.pdf" in scoped
    # An unrelated project must not be pulled into a BBA120-scoped question.
    assert "R__RCZ100__RCZ100__fichiers__users manual__conveyor.pdf" not in scoped


def test_large_collection_validates_bare_numeric_project_from_source_metadata(
    db_session,
    monkeypatch,
):
    monkeypatch.setattr(rag_context.settings, "rag_dense_chunk_threshold", 100)
    monkeypatch.setattr(rag_context.settings, "rag_dense_source_threshold", 2)
    workspace = Workspace(
        id="ws-planner-numeric5",
        name="Planner numeric5",
        slug="planner-numeric5",
    )
    db_session.add(workspace)
    db_session.flush()
    collection = create_collection(
        db_session,
        workspace=workspace,
        name="Dense Needlepunch",
    )
    collection.document_count = 100_000
    collection.chunk_count = 1_000_000
    upsert_collection_source(
        db_session,
        collection=collection,
        filename="opaque-manual.pdf",
        status="ready",
        chunk_count=8,
        source_metadata={"project_code": "61038"},
    )
    db_session.commit()

    plan = plan_corpus(
        db=db_session,
        profile={
            "collection": collection.slug,
            "collections": [collection.slug],
            "workspace_id": workspace.id,
            "latency_profile": "balanced",
            "rag_mode": "chah",
        },
        query="61038",
    )

    project_filter = plan.filters.get("project_code")
    assert project_filter == "61038" or "61038" in project_filter


def test_balanced_fact_scope_soft_boost_on_large_collections(db_session, monkeypatch):
    """Contract for the balanced fact-scope SOFT BOOST on large collections.

    Supersedes the earlier "deep-only on large collections" gate (b7a6646d
    hunk #2). That gate left balanced fact queries in the unscoped dense
    fallback, which is guardrailed against a global chunk search on large
    ledger-backed collections (``notices``) — so fact-backed answers living only
    there (the Ø1500 tambour weight) were never retrieved.

    New behaviour:
      - Small balanced collection: fact-scope is the precise HARD
        ``document_filename`` filter (unchanged).
      - Large balanced collection: fact-scope is ADDITIVE — ``filters`` stays
        empty (the unscoped fast_sparse_direct path is preserved so non-fact
        answers are not starved) and the fact docs are exposed as
        ``soft_scope_filters`` for an extra payload-filtered pass that retrieval
        unions in. The bounded scan is index-backed (pg_trgm GIN, migration 045).
      - Deep runs the precise HARD filter regardless of collection size.
    """
    monkeypatch.setattr(rag_context.settings, "rag_dense_chunk_threshold", 100)
    monkeypatch.setattr(rag_context.settings, "rag_dense_source_threshold", 2)
    workspace = Workspace(id="ws-fact-scope-bound", name="Fact Scope Bound", slug="fact-scope-bound")
    db_session.add(workspace)
    db_session.commit()

    # Distinctive fact content that does NOT appear in any filename, so the only
    # way to scope this query is the fact-table inference (never the ledger /
    # source-name targeting). Filenames stay deliberately generic.
    fact_query = "Explique la calibration thermique du palier"
    fact_filename = "A__ACJ100__manuel_chapitre_0.html"

    def _seed(name: str, *, document_count: int, chunk_count: int):
        collection = create_collection(db_session, workspace=workspace, name=name)
        for index in range(3):
            upsert_collection_source(
                db_session,
                collection=collection,
                filename=f"A__ACJ100__manuel_chapitre_{index}.html",
                status="ready",
                chunk_count=120,
            )
        collection.document_count = document_count
        collection.chunk_count = chunk_count
        db_session.add(
            KnowledgeDocumentFact(
                workspace_id=workspace.id,
                collection_id=collection.id,
                collection_slug=collection.slug,
                document_id="doc-calibration",
                document_filename=fact_filename,
                semantic_type="document_procedure_step",
                subject="calibration thermique",
                predicate="procedure_step",
                content="Procédure de calibration thermique du palier: vérifier la sonde.",
                confidence=0.9,
            )
        )
        db_session.commit()
        return collection

    small = _seed("Fact Scope Small", document_count=3, chunk_count=360)
    # Genuinely large: > _LEDGER_TARGETING_MIN_SOURCES and > _LEDGER_TARGETING_MIN_CHUNKS.
    large = _seed("Fact Scope Large", document_count=99481, chunk_count=1489764)

    def _plan(collection, latency_profile: str):
        return plan_corpus(
            db=db_session,
            profile={
                "collection": collection.slug,
                "collections": [collection.slug],
                "workspace_id": workspace.id,
                "latency_profile": latency_profile,
                "rag_mode": "chah",
            },
            query=fact_query,
        )

    # Small collection: balanced keeps the precise HARD fact-table scope.
    small_balanced = _plan(small, "balanced")
    assert small_balanced.filters.get("document_filename") == [fact_filename]
    assert not small_balanced.soft_scope_filters

    # Large collection: balanced must NOT hard-restrict the query (the unscoped
    # path stays alive for non-fact answers) but DOES expose the fact docs as an
    # additive soft scope so the guardrailed large collection still gets touched.
    large_balanced = _plan(large, "balanced")
    assert "document_filename" not in large_balanced.filters
    assert large_balanced.soft_scope_filters.get("document_filename") == [fact_filename]
    # The large collection is flagged for the scoped (soft) retrieval pass.
    assert large.slug in large_balanced.soft_scope_collections

    # Deep runs the precise HARD fact-table scope regardless of collection size.
    large_deep = _plan(large, "deep")
    assert large_deep.filters.get("document_filename") == [fact_filename]
    assert not large_deep.soft_scope_filters
    assert not large_deep.soft_scope_collections


def test_deep_planner_bounds_large_collection_ledger_load(db_session, monkeypatch):
    """Regression: deep must not Python-scan the full source ledger on large corpora.

    The full-ledger load + scoring was measured at ~55-120s on the andritz SPL
    pilot (~99k sources / ~1.49M chunks) and dominated the 120s deep deadline, so
    broad/unscoped deep jobs timed out with 0 passages while Qdrant retrieval was
    sub-second. Deep now takes the same bounded DB-side targeting as fast/balanced
    on large collections, while small-corpus deep keeps its exhaustive scan.
    """
    monkeypatch.setattr(rag_context.settings, "rag_dense_chunk_threshold", 100)
    monkeypatch.setattr(rag_context.settings, "rag_dense_source_threshold", 2)
    workspace = Workspace(id="ws-deep-bound", name="Deep Bound", slug="deep-bound")
    db_session.add(workspace)
    db_session.commit()

    full_load_calls: list[str] = []
    original_full_load = rag_corpus_planner.collection_source_rows

    def _tracking_full_load(db, *, collection):
        full_load_calls.append(collection.slug)
        return original_full_load(db, collection=collection)

    monkeypatch.setattr(rag_corpus_planner, "collection_source_rows", _tracking_full_load)

    def _seed(name: str, *, document_count: int, chunk_count: int):
        collection = create_collection(db_session, workspace=workspace, name=name)
        for index in range(3):
            upsert_collection_source(
                db_session,
                collection=collection,
                filename=f"A__AKK200__manuel_chapitre_{index}.html",
                status="ready",
                chunk_count=120,
            )
        collection.document_count = document_count
        collection.chunk_count = chunk_count
        db_session.commit()
        return collection

    small = _seed("Deep Bound Small", document_count=3, chunk_count=360)
    large = _seed("Deep Bound Large", document_count=99481, chunk_count=1489764)

    assert rag_corpus_planner._deep_ledger_is_large(db_session, [large.slug], workspace.id) is True
    assert rag_corpus_planner._deep_ledger_is_large(db_session, [small.slug], workspace.id) is False

    def _plan(collection):
        return plan_corpus(
            db=db_session,
            profile={
                "collection": collection.slug,
                "collections": [collection.slug],
                "workspace_id": workspace.id,
                "latency_profile": "deep",
                "rag_mode": "chah",
            },
            query="resume le projet AKK200",
        )

    # Large collection: deep must take the bounded path — the full-ledger loader
    # is never invoked, yet the project scope is still inferred.
    full_load_calls.clear()
    large_plan = _plan(large)
    assert large.slug not in full_load_calls
    assert large_plan.filters.get("document_filename")

    # Small collection: deep keeps the exhaustive full-ledger scan unchanged.
    full_load_calls.clear()
    _plan(small)
    assert small.slug in full_load_calls


async def test_dense_collection_quick_ask_uses_bounded_fast_sparse_direct(db_session, monkeypatch):
    monkeypatch.setattr(rag_context.settings, "rag_dense_chunk_threshold", 100)
    monkeypatch.setattr(rag_context.settings, "rag_dense_source_threshold", 2)
    workspace = Workspace(id="ws-dense-policy", name="Dense Policy", slug="dense-policy")
    db_session.add(workspace)
    db_session.commit()
    collection = create_collection(db_session, workspace=workspace, name="Dense SPL")
    for index in range(3):
        upsert_collection_source(
            db_session,
            collection=collection,
            filename=f"A__ACJ100__section_{index}.html",
            status="ready",
            chunk_count=50,
        )
    db_session.commit()
    svc = RecordingDenseService(count=150)

    result = await retrieve_rag_context(
        {
            "query": "Explique la procédure de démarrage",
            "context_collection": collection.slug,
            "workspace_id": workspace.id,
            "workspace_slug": workspace.slug,
            "rag_pipeline_mode": "chah",
            "top_k": 50,
            "candidate_pool_k": 120,
        },
        doc_svc=svc,
    )

    assert result["mode_label"] == "fast_sparse_direct"
    assert result["dense_policy"] == "fast_sparse_direct"
    assert result["pipeline"] == "hybrid"
    assert result["deep_retrieval_recommended"] is True
    assert result["retrieval_plan"]["guardrails"]["user_scope_required"] is False
    assert result["retrieval_plan"]["guardrails"]["global_chunk_search_allowed"] is False
    assert result["retrieval_plan"]["layers"]["dense_qdrant"]["enabled"] is False
    assert result["retrieval_plan"]["layers"]["sparse"]["enabled"] is True
    assert result["retrieval_plan"]["layers"]["deep_async"]["enabled"] is True
    assert result["candidate_pool_k"] <= 20
    assert svc.calls
    assert svc.calls[0]["top_k"] <= 30


async def test_system_collection_scope_is_not_sent_as_payload_filter(db_session):
    workspace = Workspace(id="ws-system-scope-filter", name="System Scope", slug="system-scope")
    db_session.add(workspace)
    db_session.commit()
    collection = create_collection(db_session, workspace=workspace, name="System Scope SPL")
    upsert_collection_source(
        db_session,
        collection=collection,
        filename="A__ACJ100__manual.html",
        status="ready",
        chunk_count=4,
    )
    db_session.commit()
    svc = RecordingDenseService(count=4)

    result = await retrieve_rag_context(
        {
            "query": "Explique la procedure",
            "workspace_id": workspace.id,
            "workspace_slug": workspace.slug,
            "retrieval_filters": {
                "collection_slug": collection.slug,
                "source_kind": "markup",
            },
        },
        doc_svc=svc,
    )

    assert result["collection"] == collection.slug
    assert result["retrieval_scope"]["collections"] == [collection.slug]
    assert svc.calls
    assert svc.calls[0]["filters"] == {"source_kind": "markup"}


async def test_dense_collection_balanced_unscoped_runs_real_bounded_dense(
    db_session,
    monkeypatch,
):
    # Post-4fe46c0 contract: balanced on an unscoped dense collection runs the
    # SAME real bounded vector/sparse search as fast (fast_sparse_direct) and
    # queues deep refinement, instead of the former coarse-inventory guardrail
    # that returned only a synthetic inventory (strictly worse than fast). This
    # supersedes the old "uses_coarse_inventory_without_global_search" assertion.
    monkeypatch.setattr(rag_context.settings, "rag_dense_chunk_threshold", 100)
    monkeypatch.setattr(rag_context.settings, "rag_dense_source_threshold", 2)
    workspace = Workspace(id="ws-dense-balanced-policy", name="Dense Balanced", slug="dense-balanced")
    db_session.add(workspace)
    db_session.commit()
    collection = create_collection(db_session, workspace=workspace, name="Dense Balanced SPL")
    for index in range(3):
        upsert_collection_source(
            db_session,
            collection=collection,
            filename=f"A__ACJ100__balanced_{index}.html",
            status="ready",
            chunk_count=50,
        )
    db_session.commit()
    svc = RecordingDenseService(count=150)

    result = await retrieve_rag_context(
        {
            "query": "Compare les procédures de maintenance",
            "context_collection": collection.slug,
            "workspace_id": workspace.id,
            "workspace_slug": workspace.slug,
            "latency_profile": "balanced",
            "rag_pipeline_mode": "chah",
            "top_k": 50,
            "candidate_pool_k": 120,
        },
        doc_svc=svc,
    )

    assert result["dense_policy"] == "fast_sparse_direct"
    assert result["deep_retrieval_recommended"] is True
    assert result["retrieval_plan"]["guardrails"]["user_scope_required"] is False
    assert result["retrieval_plan"]["guardrails"]["global_chunk_search_allowed"] is False
    assert result["retrieval_plan"]["layers"]["sparse"]["enabled"] is True
    assert result["retrieval_plan"]["layers"]["deep_async"]["enabled"] is True
    assert svc.calls


async def test_dense_collection_balanced_large_runs_scoped_soft_fact_scope(
    db_session,
    monkeypatch,
):
    """Balanced + large ledger-backed corpus: fact-scope becomes a SOFT scope.

    The planner does NOT hard-restrict the query (``filters`` stays empty, so the
    query is not gated to the fact docs — D.60 stays answerable). Instead it
    exposes the fact-matched documents as ``soft_scope_filters`` and flags the
    large collection in ``soft_scope_collections``. Retrieval then searches that
    large collection WITH the scoped filter rather than an unscoped global chunk
    search (which is guardrailed/too slow on it and would time out, starving the
    Ø1500 tambour weight that only lives there). Small collections in a
    multi-collection scope keep the unscoped pass and the results are unioned;
    here a single large collection is searched scoped. Replaces the b7a6646d
    hunk #2 hard-gate that left these queries unscoped (Ø1500 tambour regression).
    """
    monkeypatch.setattr(rag_context.settings, "rag_dense_chunk_threshold", 100)
    monkeypatch.setattr(rag_context.settings, "rag_dense_source_threshold", 2)
    workspace = Workspace(id="ws-soft-boost", name="Soft Boost", slug="soft-boost")
    db_session.add(workspace)
    db_session.commit()
    collection = create_collection(db_session, workspace=workspace, name="Soft Boost SPL")
    fact_filename = "A__ACJ100__manuel_chapitre_0.html"
    for index in range(3):
        upsert_collection_source(
            db_session,
            collection=collection,
            filename=f"A__ACJ100__manuel_chapitre_{index}.html",
            status="ready",
            chunk_count=120,
        )
    # Genuinely large: above both ledger-targeting thresholds.
    collection.document_count = 99481
    collection.chunk_count = 1489764
    db_session.add(
        KnowledgeDocumentFact(
            workspace_id=workspace.id,
            collection_id=collection.id,
            collection_slug=collection.slug,
            document_id="doc-calibration",
            document_filename=fact_filename,
            semantic_type="document_procedure_step",
            subject="calibration thermique",
            predicate="procedure_step",
            content="Procédure de calibration thermique du palier: vérifier la sonde.",
            confidence=0.9,
        )
    )
    db_session.commit()
    svc = RecordingDenseService(count=360)

    result = await retrieve_rag_context(
        {
            "query": "Explique la calibration thermique du palier",
            "context_collection": collection.slug,
            "workspace_id": workspace.id,
            "workspace_slug": workspace.slug,
            "latency_profile": "balanced",
            "rag_pipeline_mode": "chah",
        },
        doc_svc=svc,
    )

    # Query is NOT hard-restricted (no HARD filter); fact docs are a soft scope,
    # and the large collection is flagged for the scoped pass.
    assert result["dense_policy"] == "fast_sparse_direct"
    assert result["retrieval_scope"]["filters"] == {}
    assert result["retrieval_scope"]["soft_scope_filters"] == {"document_filename": [fact_filename]}
    assert collection.slug in result["retrieval_scope"]["soft_scope_collections"]
    # The large collection was searched WITH the scoped filter (not unscoped):
    # every real retrieval call carried the fact-doc filter, and the soft boost
    # metric records that the collection was scoped.
    assert svc.calls
    assert all(
        (call["filters"] or {}).get("document_filename") == [fact_filename]
        for call in svc.calls
    )
    assert result["metrics"]["soft_scope_boost"]["applied"] is True
    assert collection.slug in result["metrics"]["soft_scope_boost"]["scoped_collections"]


class RecallFloorAnswerService:
    """Returns a generic chunk for the scoped pass and the *missed* answer doc
    only for the UNSCOPED recall-floor pass (filters is None). It models the
    live bug: the answer chunk is reachable by unscoped dense search but its
    filename is absent from the hard document_filename allowlist.
    """

    def __init__(self, count: int = 360):
        self.count = count
        self.calls: list[dict] = []

    async def get_document_count(self) -> int:
        return self.count

    async def search(self, query: str, top_k: int = 10, filters=None, use_hybrid=None):
        self.calls.append({"query": query, "top_k": top_k, "filters": filters, "use_hybrid": use_hybrid})
        if filters and (filters or {}).get("document_filename"):
            return [
                {
                    "id": "scoped-generic",
                    "content": "Generic scoped passage without the greasing quantity.",
                    "score": 0.55,
                    "metadata": {"document_filename": "A__ACJ100__manuel_chapitre_0.html"},
                }
            ][:top_k]
        return [
            {
                "id": "recall-floor-answer",
                "content": "GRAISSE POUR LUBRIFICATION palier moteur 40 g puis 125 g.",
                "score": 0.68,
                "metadata": {"document_filename": "A__ACJ100__structure_notice_section7.pdf"},
            }
        ][:top_k]


def _large_ledger_collection(db_session, *, workspace, name):
    collection = create_collection(db_session, workspace=workspace, name=name)
    for index in range(3):
        upsert_collection_source(
            db_session,
            collection=collection,
            filename=f"A__ACJ100__manuel_chapitre_{index}.html",
            status="ready",
            chunk_count=120,
        )
    # Above both ledger-targeting thresholds: a genuinely large collection.
    collection.document_count = 99481
    collection.chunk_count = 1489764
    db_session.commit()
    return collection


async def test_recall_floor_activates_on_large_hard_document_scope(db_session, monkeypatch):
    # Req 1: a HARD document_filename ledger scope on a LARGE collection arms the
    # additive recall floor — the hard filter stays the primary scope AND the
    # planner flags the large collection for a bounded unscoped dense pass.
    monkeypatch.setattr(rag_context.settings, "rag_dense_chunk_threshold", 100)
    monkeypatch.setattr(rag_context.settings, "rag_dense_source_threshold", 2)
    workspace = Workspace(id="ws-recall-floor", name="Recall Floor", slug="recall-floor")
    db_session.add(workspace)
    db_session.commit()
    collection = _large_ledger_collection(db_session, workspace=workspace, name="Recall Floor SPL")

    plan = plan_corpus(
        db=db_session,
        profile={
            "collection": collection.slug,
            "collections": [collection.slug],
            "workspace_id": workspace.id,
            "latency_profile": "balanced",
            "rag_mode": "chah",
        },
        query="Peux-tu retrouver la Spare Parts List du projet ACJ100 ?",
    )

    # Hard scope still present (precision layer unchanged).
    assert "document_filename" in plan.filters
    # Recall floor armed and bounded to N in [10, 20].
    assert plan.recall_floor_collections
    assert collection.slug in plan.recall_floor_collections
    assert 10 <= plan.recall_floor_top_n <= 20
    assert plan.retrieval_scope["recall_floor_collections"]
    # Soft fact-scope is mutually exclusive with the recall floor (hard filter present).
    assert plan.soft_scope_filters == {}


async def test_recall_floor_unions_missed_answer_doc_on_large_collection(db_session, monkeypatch):
    # Req 4: the answer doc whose filename misses the query surface terms is NOT
    # in the hard allowlist, yet the bounded UNSCOPED dense pass surfaces it and
    # the union puts it into the final context.
    monkeypatch.setattr(rag_context.settings, "rag_dense_chunk_threshold", 100)
    monkeypatch.setattr(rag_context.settings, "rag_dense_source_threshold", 2)
    workspace = Workspace(id="ws-recall-union", name="Recall Union", slug="recall-union")
    db_session.add(workspace)
    db_session.commit()
    collection = _large_ledger_collection(db_session, workspace=workspace, name="Recall Union SPL")
    svc = RecallFloorAnswerService()

    result = await retrieve_rag_context(
        {
            "query": "Quelle quantité de graisse pour le palier moteur du projet ACJ100 ?",
            "context_collection": collection.slug,
            "workspace_id": workspace.id,
            "workspace_slug": workspace.slug,
            "latency_profile": "balanced",
            "rag_pipeline_mode": "chah",
        },
        doc_svc=svc,
    )

    # The hard scope was applied AND an UNSCOPED (filters=None) pass also ran.
    assert any((call["filters"] or {}).get("document_filename") for call in svc.calls)
    assert any(call["filters"] in (None, {}) for call in svc.calls)
    # The missed answer doc reached the final context via the recall floor.
    assert result["metrics"]["recall_floor"]["applied"] is True
    assert result["metrics"]["recall_floor"]["candidates_added"] >= 1
    assert any(
        "structure_notice_section7.pdf" in str((meta or {}).get("document_filename") or "")
        for meta in result["metadatas"]
    )
    assert any("GRAISSE POUR LUBRIFICATION" in str(chunk) for chunk in result["chunks"])
    assert any(bool((meta or {}).get("recall_floor")) for meta in result["metadatas"])


async def test_recall_floor_noop_on_small_collection(db_session, monkeypatch):
    # Req 3 (strict gate) + Etachrom-style scoped non-regression: the SAME hard
    # document_filename scope on a SMALL collection is a no-op — no recall floor
    # is armed and retrieval never runs an extra unscoped pass.
    monkeypatch.setattr(rag_context.settings, "rag_dense_chunk_threshold", 100)
    monkeypatch.setattr(rag_context.settings, "rag_dense_source_threshold", 2)
    workspace = Workspace(id="ws-recall-noop", name="Recall Noop", slug="recall-noop")
    db_session.add(workspace)
    db_session.commit()
    collection = create_collection(db_session, workspace=workspace, name="Recall Noop SPL")
    for index in range(3):
        upsert_collection_source(
            db_session,
            collection=collection,
            filename=f"A__ACJ100__manuel_chapitre_{index}.html",
            status="ready",
            chunk_count=150,
        )
    db_session.commit()

    plan = plan_corpus(
        db=db_session,
        profile={
            "collection": collection.slug,
            "collections": [collection.slug],
            "workspace_id": workspace.id,
            "latency_profile": "balanced",
            "rag_mode": "chah",
        },
        query="Peux-tu retrouver la Spare Parts List du projet ACJ100 ?",
    )
    assert "document_filename" in plan.filters
    assert plan.recall_floor_collections == []
    assert plan.recall_floor_top_n == 0

    svc = RecallFloorAnswerService(count=4)
    result = await retrieve_rag_context(
        {
            "query": "Peux-tu retrouver la Spare Parts List du projet ACJ100 ?",
            "context_collection": collection.slug,
            "workspace_id": workspace.id,
            "workspace_slug": workspace.slug,
            "latency_profile": "balanced",
            "rag_pipeline_mode": "chah",
        },
        doc_svc=svc,
    )
    # No unscoped recall-floor pass: every retrieval call carried the hard scope.
    assert svc.calls
    assert all((call["filters"] or {}).get("document_filename") for call in svc.calls)
    assert "recall_floor" not in result["metrics"]


async def test_recall_floor_keeps_tight_project_scope_on_large_collection(db_session, monkeypatch):
    # Req 2 (CU250S-2 non-regression): when the query code lives only inside
    # filenames (documents carry a parent project_code in metadata), the planner
    # keeps the precise document_filename allowlist instead of a broad
    # project_code filter. The recall floor stays purely additive: it never
    # rewrites the hard scope, so the tight project scope stays tight.
    monkeypatch.setattr(rag_context.settings, "rag_dense_chunk_threshold", 100)
    monkeypatch.setattr(rag_context.settings, "rag_dense_source_threshold", 2)
    workspace = Workspace(id="ws-recall-tight", name="Recall Tight", slug="recall-tight")
    db_session.add(workspace)
    db_session.commit()
    collection = create_collection(db_session, workspace=workspace, name="Recall Tight SPL")
    for index in range(3):
        upsert_collection_source(
            db_session,
            collection=collection,
            filename=f"A__CU250S__Notice technique CU250S doc{index}.pdf",
            status="ready",
            chunk_count=120,
            source_metadata={"project_code": "ACJ100"},
        )
    collection.document_count = 99481
    collection.chunk_count = 1489764
    db_session.commit()

    plan = plan_corpus(
        db=db_session,
        profile={
            "collection": collection.slug,
            "collections": [collection.slug],
            "workspace_id": workspace.id,
            "latency_profile": "balanced",
            "rag_mode": "chah",
        },
        query="Configuration generale du systeme CU250S",
    )

    # Tight scope preserved: document_filename allowlist, NOT a broad project_code.
    assert "document_filename" in plan.filters
    assert "project_code" not in plan.filters
    # Recall floor is armed (large + hard document scope) but purely additive —
    # the hard filters are unchanged by it.
    assert plan.recall_floor_collections
    assert collection.slug in plan.recall_floor_collections


async def test_recall_floor_pass_embeds_raw_query_without_guide_hint(monkeypatch):
    # Regression: the UNSCOPED recall-floor pass must embed the RAW user query
    # with NO guide-hint suffix. Appending the workspace guide hint dilutes a
    # terse question's embedding enough to push the missed answer doc out of the
    # unscoped top-N (live D.60 'palier D.60 ?' phrasing) — exactly the chunk the
    # floor exists to recover. It must also stay dense-only and unscoped.
    captured: dict = {}

    async def fake_retrieve_for_mode(doc_svc, query, mode, **kwargs):  # noqa: ARG001
        captured["query"] = query
        captured["mode"] = mode
        captured["use_hybrid"] = kwargs.get("use_hybrid")
        captured["query_hints"] = kwargs.get("query_hints")
        captured["filters"] = kwargs.get("filters")
        return SimpleNamespace(chunks=[], scores=[], metadatas=[], pipeline="naive", label="recall_floor", detail={})

    monkeypatch.setattr(rag_context, "retrieve_for_mode", fake_retrieve_for_mode)

    await rag_context._retrieve_recall_floor_pass(
        object(),
        retrieval_query="palier D.60 ?",
        top_n=15,
        retrieval_policy=None,
        deadline_seconds=2.0,
        max_candidates=40,
        retrieval_profile="balanced",
        latency_profile="balanced",
    )

    assert captured["query"] == "palier D.60 ?"
    assert captured["query_hints"] == ""
    assert captured["use_hybrid"] is False
    assert captured["filters"] is None
    assert captured["mode"] == "naive"


async def test_dense_planner_uses_collection_totals_when_source_ledger_is_partial(db_session, monkeypatch):
    monkeypatch.setattr(rag_context.settings, "rag_dense_chunk_threshold", 100)
    monkeypatch.setattr(rag_context.settings, "rag_dense_source_threshold", 2)
    workspace = Workspace(id="ws-dense-partial-ledger", name="Dense Partial", slug="dense-partial")
    db_session.add(workspace)
    db_session.commit()
    collection = create_collection(db_session, workspace=workspace, name="Dense Partial SPL")
    collection.document_count = 25
    collection.chunk_count = 500
    upsert_collection_source(
        db_session,
        collection=collection,
        filename="partial-ledger-source.html",
        status="ready",
        chunk_count=1,
    )
    db_session.commit()
    svc = RecordingDenseService(count=500)

    result = await retrieve_rag_context(
        {
            "query": "Explique la procédure de maintenance",
            "context_collection": collection.slug,
            "workspace_id": workspace.id,
            "workspace_slug": workspace.slug,
            "rag_pipeline_mode": "hybrid",
        },
        doc_svc=svc,
    )

    assert result["dense_policy"] == "fast_sparse_direct"
    assert result["pipeline"] == "hybrid"
    assert result["retrieval_scope"]["source_count"] == 25
    assert result["retrieval_scope"]["chunk_count"] == 500
    assert result["retrieval_plan"]["guardrails"]["global_chunk_search_allowed"] is False
    assert result["retrieval_plan"]["layers"]["sparse"]["enabled"] is True
    assert svc.calls


async def test_dense_collection_quick_ask_uses_fact_scoped_document_filter(db_session, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "store"))
    monkeypatch.setattr(rag_context.settings, "rag_dense_chunk_threshold", 100)
    monkeypatch.setattr(rag_context.settings, "rag_dense_source_threshold", 2)
    workspace = Workspace(id="ws-dense-facts", name="Dense Facts", slug="dense-facts")
    db_session.add(workspace)
    db_session.commit()
    collection = create_collection(db_session, workspace=workspace, name="Dense Facts SPL")
    upsert_collection_source(
        db_session,
        collection=collection,
        filename="A__ACJ100__start_procedure.html",
        status="ready",
        chunk_count=120,
    )
    upsert_collection_source(
        db_session,
        collection=collection,
        filename="A__ACJ100__maintenance.html",
        status="ready",
        chunk_count=120,
    )
    upsert_collection_source(
        db_session,
        collection=collection,
        filename="A__ACJ100__menu.html",
        status="ready",
        chunk_count=120,
    )
    db_session.add(
        KnowledgeDocumentFact(
            workspace_id=workspace.id,
            collection_id=collection.id,
            collection_slug=collection.slug,
            document_id="doc-start",
            document_filename="A__ACJ100__start_procedure.html",
            semantic_type="document_procedure_step",
            subject="démarrage ACJ100",
            predicate="procedure_step",
            content="Procédure de démarrage: vérifier les sécurités puis lancer la machine.",
            confidence=0.9,
        )
    )
    db_session.commit()
    rebuild_summary_index_artifact(db=db_session, collection=collection)
    svc = RecordingDenseService(count=360)

    result = await retrieve_rag_context(
        {
            "query": "Explique la procédure de démarrage",
            "context_collection": collection.slug,
            "workspace_id": workspace.id,
            "workspace_slug": workspace.slug,
            "rag_pipeline_mode": "chah",
        },
        doc_svc=svc,
    )

    assert result["dense_policy"] == "fast_scoped_dense"
    assert result["pipeline"] != "dense_coarse_inventory"
    assert svc.calls
    assert svc.calls[0]["use_hybrid"] is False
    assert svc.calls[0]["filters"] == {"document_filename": ["A__ACJ100__start_procedure.html"]}
    assert result["retrieval_scope"]["filters"] == {"document_filename": ["A__ACJ100__start_procedure.html"]}
    assert result["retrieval_plan"]["guardrails"]["user_scope_required"] is False
    assert result["retrieval_plan"]["layers"]["facts"]["enabled"] is True
    assert result["retrieval_plan"]["layers"]["dense_qdrant"]["enabled"] is True
    assert result["retrieval_plan"]["layers"]["hah_chah"]["enabled"] is False
    assert result["metrics"]["summary_artifact_status"] == "ready"
    assert result["metrics"]["summary_artifact_evidence"] >= 1
    assert any(meta.get("source_type") == "summary_artifact" for meta in result["metadatas"])


async def test_dense_collection_balanced_scoped_chah_uses_external_sparse_not_legacy_bm25(
    db_session,
    monkeypatch,
):
    monkeypatch.setattr(rag_context.settings, "rag_dense_chunk_threshold", 100)
    monkeypatch.setattr(rag_context.settings, "rag_dense_source_threshold", 2)
    workspace = Workspace(id="ws-dense-balanced-facts", name="Dense Balanced Facts", slug="dense-balanced-facts")
    db_session.add(workspace)
    db_session.commit()
    collection = create_collection(db_session, workspace=workspace, name="Dense Balanced Facts SPL")
    for filename in (
        "A__ACJ100__start_procedure.html",
        "A__ACJ100__maintenance.html",
        "A__ACJ100__menu.html",
    ):
        upsert_collection_source(
            db_session,
            collection=collection,
            filename=filename,
            status="ready",
            chunk_count=120,
        )
    db_session.add(
        KnowledgeDocumentFact(
            workspace_id=workspace.id,
            collection_id=collection.id,
            collection_slug=collection.slug,
            document_id="doc-start",
            document_filename="A__ACJ100__start_procedure.html",
            semantic_type="document_procedure_step",
            subject="démarrage ACJ100",
            predicate="procedure_step",
            content="Procédure de démarrage: vérifier les sécurités puis lancer la machine.",
            confidence=0.9,
        )
    )
    db_session.commit()
    captured: dict = {}

    async def _fake_retrieve(doc_svc, query, mode, **kwargs):  # noqa: ARG001
        captured.update(kwargs)
        captured["mode"] = mode
        return SimpleNamespace(
            chunks=["balanced scoped chunk"],
            scores=[0.82],
            metadatas=[{"document_filename": "A__ACJ100__start_procedure.html"}],
            pipeline="chah_backend",
            label="C-HAH",
            reason="balanced scoped",
            detail="test",
            diagnostics={"sparse_backend": "opensearch", "sparse_status": "empty"},
        )

    monkeypatch.setattr(rag_context, "retrieve_for_mode", _fake_retrieve)

    result = await retrieve_rag_context(
        {
            "query": "Explique la procédure de démarrage",
            "context_collection": collection.slug,
            "workspace_id": workspace.id,
            "workspace_slug": workspace.slug,
            "latency_profile": "balanced",
            "rag_pipeline_mode": "chah",
        },
        doc_svc=RecordingDenseService(count=360),
    )

    assert result["dense_policy"] == "fast_scoped_dense"
    assert result["pipeline"] == "chah_backend"
    assert captured["mode"] == "chah"
    assert captured["hah_chah_enabled"] is True
    assert captured["use_hybrid"] is True
    assert captured["allow_legacy_hybrid"] is False
    assert captured["max_variants"] == 3
    assert captured["max_candidates"] <= 80
    assert captured["filters"] == {"document_filename": ["A__ACJ100__start_procedure.html"]}
    assert result["retrieval_plan"]["layers"]["sparse"]["enabled"] is True
    assert result["retrieval_plan"]["layers"]["hah_chah"]["enabled"] is True
    assert result["retrieval_plan"]["guardrails"]["user_scope_required"] is False


async def test_dense_deep_chah_uses_summary_scope_without_legacy_hybrid(db_session, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "store"))
    monkeypatch.setattr(rag_context.settings, "rag_dense_chunk_threshold", 100)
    monkeypatch.setattr(rag_context.settings, "rag_dense_source_threshold", 2)
    workspace = Workspace(id="ws-dense-deep-summary", name="Dense Deep", slug="dense-deep")
    db_session.add(workspace)
    db_session.commit()
    collection = create_collection(db_session, workspace=workspace, name="Dense Deep SPL")
    for filename in (
        "A__ACJ100__maintenance.html",
        "A__ACJ100__start_procedure.html",
        "A__ACJ100__menu.html",
    ):
        upsert_collection_source(
            db_session,
            collection=collection,
            filename=filename,
            status="ready",
            chunk_count=140,
        )
    db_session.commit()
    rebuild_summary_index_artifact(db=db_session, collection=collection)
    captured: dict = {}

    async def _fake_retrieve(doc_svc, query, mode, **kwargs):  # noqa: ARG001
        captured.update(kwargs)
        captured["mode"] = mode
        return SimpleNamespace(
            chunks=["deep scoped chunk"],
            scores=[0.88],
            metadatas=[{"document_filename": "A__ACJ100__maintenance.html"}],
            pipeline="chah_backend",
            label="C-HAH",
            reason="deep scoped",
            detail="test",
            diagnostics={"sparse_backend": "disabled", "sparse_status": "disabled"},
        )

    monkeypatch.setattr(rag_context, "retrieve_for_mode", _fake_retrieve)

    result = await retrieve_rag_context(
        {
            "query": "Audit profond maintenance ACJ100",
            "context_collection": collection.slug,
            "workspace_id": workspace.id,
            "workspace_slug": workspace.slug,
            "latency_profile": "deep",
            "deep_retrieval": True,
            "rag_pipeline_mode": "chah",
        },
        doc_svc=RecordingDenseService(count=420),
    )

    assert result["dense_policy"] == "deep_hierarchical_dense"
    assert result["pipeline"] == "chah_backend"
    assert captured["mode"] == "chah"
    assert captured["use_hybrid"] is True
    assert captured["allow_legacy_hybrid"] is False
    assert captured["max_variants"] == 6
    assert captured["max_candidates"] <= 200
    assert captured["filters"]["document_filename"]
    assert "A__ACJ100__maintenance.html" in captured["filters"]["document_filename"]
    assert result["retrieval_plan"]["layers"]["summaries"]["enabled"] is True
    assert result["retrieval_plan"]["layers"]["sparse"]["enabled"] is True
    assert result["retrieval_plan"]["guardrails"]["user_scope_required"] is False


async def test_dense_deep_without_system_scope_returns_coarse_inventory_not_global_search(
    db_session,
    monkeypatch,
):
    monkeypatch.setattr(rag_context.settings, "rag_dense_chunk_threshold", 100)
    monkeypatch.setattr(rag_context.settings, "rag_dense_source_threshold", 2)
    workspace = Workspace(id="ws-dense-deep-unscoped", name="Dense Deep Unscoped", slug="dense-deep-unscoped")
    db_session.add(workspace)
    db_session.commit()
    collection = create_collection(db_session, workspace=workspace, name="Dense Deep Unscoped SPL")
    for index in range(3):
        upsert_collection_source(
            db_session,
            collection=collection,
            filename=f"A__ACJ100__deep_unscoped_{index}.html",
            status="ready",
            chunk_count=60,
        )
    db_session.commit()
    svc = RecordingDenseService(count=180)

    result = await retrieve_rag_context(
        {
            "query": "Audit profond du corpus SPL",
            "context_collection": collection.slug,
            "workspace_id": workspace.id,
            "workspace_slug": workspace.slug,
            "latency_profile": "deep",
            "deep_retrieval": True,
            "rag_pipeline_mode": "chah",
        },
        doc_svc=svc,
    )

    assert result["dense_policy"] == "deep_hierarchical_dense"
    assert result["pipeline"] == "dense_coarse_inventory"
    assert result["mode_label"] == "deep_hierarchical_dense"
    assert result["fallback_reason"] == "dense_unscoped_deep_policy"
    assert result["deep_retrieval_recommended"] is False
    assert result["retrieval_plan"]["layers"]["dense_qdrant"]["enabled"] is False
    assert result["retrieval_plan"]["layers"]["sparse"]["enabled"] is False
    assert result["retrieval_plan"]["layers"]["hah_chah"]["enabled"] is False
    assert result["retrieval_plan"]["guardrails"]["global_chunk_search_allowed"] is False
    assert result["metrics"]["dense_global_search_skipped"] is True
    assert not svc.calls


async def test_deep_scope_miss_recovery_retries_without_doc_filters(db_session, monkeypatch):
    """Deep must not return 0 passages when an inferred document scope is empty.

    The SQL ledger is a superset of the vector store on partially-ingested corpora:
    a ledger-inferred document_filename scope can point at documents that were never
    vectorised, so the payload filter excludes every candidate and deep would return
    0 passages (the empty grounding fallback the user sees). Deep has ample deadline
    headroom, so it retries once over the collection without the doc-level filters.
    """
    monkeypatch.setattr(rag_context.settings, "rag_cross_encoder_enabled", False)
    monkeypatch.setattr(rag_context.settings, "rag_dense_chunk_threshold", 100)
    monkeypatch.setattr(rag_context.settings, "rag_dense_source_threshold", 2)
    workspace = Workspace(id="ws-scope-miss", name="Scope Miss", slug="scope-miss")
    db_session.add(workspace)
    db_session.commit()
    collection = create_collection(db_session, workspace=workspace, name="Scope Miss SPL")
    upsert_collection_source(
        db_session,
        collection=collection,
        filename="A__ACJ100__scope_miss.html",
        status="ready",
        chunk_count=60,
    )
    db_session.commit()

    seen_filters: list[dict] = []

    async def _fake_retrieve(doc_svc, query, mode, **kwargs):  # noqa: ARG001
        filters = dict(kwargs.get("filters") or {})
        seen_filters.append(filters)
        # First (scoped) call: the inferred document scope is absent from the
        # vector store, so retrieval finds nothing.
        if "document_filename" in filters:
            return SimpleNamespace(
                chunks=[], scores=[], metadatas=[],
                pipeline="chah_backend", label="C-HAH", reason="empty", detail="",
                diagnostics={"sparse_backend": "disabled", "sparse_status": "disabled"},
            )
        # Relaxed retry over the collection returns real passages.
        return SimpleNamespace(
            chunks=["pompe centrifuge Etachrom B passage"],
            scores=[0.81],
            metadatas=[{"document_filename": "H__HYD100__pompe.pdf"}],
            pipeline="chah_backend", label="C-HAH", reason="recovered", detail="",
            diagnostics={"sparse_backend": "disabled", "sparse_status": "disabled"},
        )

    monkeypatch.setattr(rag_context, "retrieve_for_mode", _fake_retrieve)

    result = await retrieve_rag_context(
        {
            "query": "quelles sont toutes les pompes utilisées dans tous les projets ?",
            "context_collection": collection.slug,
            "workspace_id": workspace.id,
            "workspace_slug": workspace.slug,
            "latency_profile": "deep",
            "deep_retrieval": True,
            "rag_pipeline_mode": "chah",
            "retrieval_filters": {"document_filename": ["H__HYD100__only_in_ledger.pdf"]},
        },
        doc_svc=RecordingDenseService(count=420),
    )

    # Two retrieval attempts: the empty scoped call, then the relaxed retry.
    assert len(seen_filters) == 2
    assert "document_filename" in seen_filters[0]
    assert "document_filename" not in seen_filters[1]
    assert result["metrics"].get("scope_miss_recovery") is True
    assert result["chunks"], "deep scope-miss recovery must return grounded passages, not 0"


async def test_retrieve_rag_context_cache_reuses_fast_context(db_session, monkeypatch):
    rag_context._RETRIEVAL_CONTEXT_CACHE.clear()
    monkeypatch.setattr(rag_context.settings, "rag_context_cache_enabled", True)
    monkeypatch.setattr(rag_context.settings, "rag_context_cache_ttl_seconds", 90)
    monkeypatch.setattr(rag_context.settings, "rag_context_cache_max_entries", 10)
    workspace = Workspace(id="ws-cache", name="Cache", slug="cache")
    db_session.add(workspace)
    db_session.commit()
    collection = create_collection(db_session, workspace=workspace, name="Documents")
    upsert_collection_source(
        db_session,
        collection=collection,
        filename="manual-cache.html",
        status="ready",
        chunk_count=2,
        source_metadata={"document_id": "doc-cache"},
    )
    db_session.commit()
    svc = RecordingDenseService(count=12)
    request = {
        "query": "Cache cette procédure de test",
        "workspace_id": workspace.id,
        "workspace_slug": workspace.slug,
        "context_collection": collection.slug,
        "rag_pipeline_mode": "naive",
        "top_k": 5,
    }

    first = await retrieve_rag_context(request, doc_svc=svc)
    second = await retrieve_rag_context(request, doc_svc=svc)

    assert len(svc.calls) == 1
    assert first["chunks"] == second["chunks"]
    assert second["metrics"]["retrieval_context_cache_hit"] is True


async def test_retrieve_rag_context_cache_skips_unknown_corpus_version(monkeypatch):
    rag_context._RETRIEVAL_CONTEXT_CACHE.clear()
    monkeypatch.setattr(rag_context.settings, "rag_context_cache_enabled", True)
    monkeypatch.setattr(rag_context.settings, "rag_context_cache_ttl_seconds", 90)
    monkeypatch.setattr(rag_context.settings, "rag_context_cache_max_entries", 10)
    svc = RecordingDenseService(count=12)
    request = {
        "query": "Cache cette procédure de test",
        "workspace_id": "ws-cache-unknown",
        "workspace_slug": "cache-unknown",
        "context_collection": "documents",
        "rag_pipeline_mode": "naive",
        "top_k": 5,
    }

    first = await retrieve_rag_context(request, doc_svc=svc)
    second = await retrieve_rag_context(request, doc_svc=svc)

    assert len(svc.calls) == 2
    assert first["retrieval_scope"]["corpus_version"] == "unknown"
    assert second["metrics"]["retrieval_context_cache_hit"] is False
    assert second["metrics"]["retrieval_context_cache_skipped_reason"] == "corpus_version_unknown"


async def test_retrieve_rag_context_cache_invalidates_on_collection_version(db_session, monkeypatch):
    rag_context._RETRIEVAL_CONTEXT_CACHE.clear()
    monkeypatch.setattr(rag_context.settings, "rag_context_cache_enabled", True)
    monkeypatch.setattr(rag_context.settings, "rag_context_cache_ttl_seconds", 90)
    monkeypatch.setattr(rag_context.settings, "rag_context_cache_max_entries", 10)
    workspace = Workspace(id="ws-cache-version", name="Cache Version", slug="cache-version")
    db_session.add(workspace)
    db_session.commit()
    collection = create_collection(db_session, workspace=workspace, name="Manuals")
    upsert_collection_source(
        db_session,
        collection=collection,
        filename="manual-cache.html",
        status="ready",
        chunk_count=2,
        source_metadata={"document_id": "doc-cache"},
    )
    db_session.commit()
    svc = RecordingDenseService(count=2)
    request = {
        "query": "Cache cette procédure de test",
        "workspace_id": workspace.id,
        "workspace_slug": workspace.slug,
        "context_collection": collection.slug,
        "rag_pipeline_mode": "naive",
        "top_k": 5,
    }

    first = await retrieve_rag_context(request, doc_svc=svc)
    second = await retrieve_rag_context(request, doc_svc=svc)
    collection.updated_at = datetime.utcnow() + timedelta(seconds=30)
    db_session.commit()
    third = await retrieve_rag_context(request, doc_svc=svc)

    assert len(svc.calls) == 2
    assert second["metrics"]["retrieval_context_cache_hit"] is True
    assert third["metrics"]["retrieval_context_cache_hit"] is False
    assert first["retrieval_scope"]["corpus_version"] != third["retrieval_scope"]["corpus_version"]


async def test_retrieve_rag_context_cache_separates_latency_budgets(monkeypatch):
    rag_context._RETRIEVAL_CONTEXT_CACHE.clear()
    monkeypatch.setattr(rag_context.settings, "rag_context_cache_enabled", True)
    monkeypatch.setattr(rag_context.settings, "rag_context_cache_ttl_seconds", 90)
    monkeypatch.setattr(rag_context.settings, "rag_context_cache_max_entries", 10)
    svc = RecordingDenseService(count=12)
    base_request = {
        "query": "Cache cette procédure de test",
        "workspace_id": "ws-cache-budget",
        "workspace_slug": "cache-budget",
        "context_collection": "documents",
        "rag_pipeline_mode": "naive",
    }

    fast = await retrieve_rag_context({**base_request, "latency_profile": "fast"}, doc_svc=svc)
    balanced = await retrieve_rag_context({**base_request, "latency_profile": "balanced"}, doc_svc=svc)

    assert len(svc.calls) == 2
    assert fast["latency_budget"]["profile"] == "fast"
    assert balanced["latency_budget"]["profile"] == "balanced"
    assert balanced["metrics"].get("retrieval_context_cache_hit") is False


async def test_multi_collection_retrieval_uses_shared_latency_deadline(monkeypatch):
    monkeypatch.setattr(rag_context.settings, "rag_fast_retrieval_deadline_seconds", 0.06)
    monkeypatch.setattr(
        rag_context,
        "resolve_knowledge_scope",
        lambda **_kwargs: {
            "key": "multi",
            "label": "Multi",
            "collection_slugs": ["manuals-a", "manuals-b", "manuals-c"],
        },
    )
    monkeypatch.setattr(
        rag_context,
        "_document_service_for_profile",
        lambda _profile, collection: SimpleNamespace(collection=collection),
    )

    async def fake_resolve_mode(*_args, **_kwargs):
        return False, "vector_only", "test"

    calls: list[tuple[str, float]] = []

    async def slow_retrieve(doc_svc, _query, _mode, **kwargs):
        calls.append((doc_svc.collection, float(kwargs.get("deadline_seconds") or 0.0)))
        await asyncio.sleep(0.04)
        return SimpleNamespace(
            chunks=[f"{doc_svc.collection} chunk"],
            scores=[0.9],
            metadatas=[{"document_filename": f"{doc_svc.collection}.html"}],
            pipeline="naive",
            label="Vector",
            reason="test",
            detail="test",
            diagnostics={},
        )

    monkeypatch.setattr(rag_context, "resolve_retrieval_mode", fake_resolve_mode)
    monkeypatch.setattr(rag_context, "retrieve_for_mode", slow_retrieve)

    result = await retrieve_rag_context(
        {
            "query": "Explique les procédures",
            "workspace_slug": "multi-deadline",
            "knowledge_scope": "multi",
            "rag_pipeline_mode": "naive",
        }
    )

    assert 1 <= len(calls) <= 2
    assert calls[0][1] <= 0.06
    assert result["metrics"]["deadline_exceeded"] is True
    assert result["fallback_reason"] == "retrieval_deadline_exceeded"
    assert result["collections_touched"] == ["manuals-a"]


async def test_retrieve_rag_context_uses_published_guides_as_hint_and_advisory_source(monkeypatch):
    guide = SimpleNamespace(
        title="Excel data dictionary",
        markdown="Column A contains labels. Column B contains numeric values. Def strips maps B to 85.",
        guide_key="guide-1",
        version=2,
        target_type="scope",
        target_ref="excel_pilot",
    )
    monkeypatch.setattr(rag_context, "_effective_guides_for_profile", lambda _profile: [guide])
    doc_svc = FakeEmptyRecordingService()

    result = await retrieve_rag_context(
        {
            "query": "Quel est le diamètre B ?",
            "rag_pipeline_mode": "chah",
            "top_k": 3,
            "workspace_id": "workspace-andritz",
            "workspace_slug": "andritz",
            "knowledge_scope": "excel_pilot",
        },
        doc_svc=doc_svc,
    )

    assert any("Knowledge guide hints" in query for query in doc_svc.queries)
    assert result["chunks"][-1].startswith("Knowledge guide: Excel data dictionary")
    assert result["scores"][-1] < 0.1
    assert result["metadatas"][-1]["source_type"] == "knowledge_guide"
    assert result["metadatas"][-1]["retrieval_role"] == "advisory_context"
    assert result["metadatas"][-1]["guide_version"] == 2
    assert result["metrics"]["knowledge_guides"] == 1


async def test_retrieve_rag_context_applies_knowledge_guide_retrieval_policy(monkeypatch):
    guide = SimpleNamespace(
        title="Andritz retrieval policy",
        markdown="""```agentium-retrieval-policy
{
  "query_planning": {
    "protected_terms": ["AKK200"],
    "aliases": {"capteurs": ["sensor", "proximity switch", "XS1"]},
    "facets": [
      {
        "key": "sensor",
        "label": "Capteurs",
        "terms": ["capteurs", "sensor"],
        "clarify_when_broad": true,
        "clarification_prompt": "Voulez-vous les capteurs de proximite, pression, securite ou automatisme ?"
      }
    ]
  },
  "source_quality": {"demote_navigation": true},
  "answer_policy": {
    "instructions": ["Traiter les codes de type XXX123 comme des references projet stables."]
  }
}
```""",
        guide_key="guide-policy",
        version=1,
        target_type="collection",
        target_ref="andritz",
    )
    monkeypatch.setattr(rag_context, "_effective_guides_for_profile", lambda _profile: [guide])

    result = await retrieve_rag_context(
        {
            "query": "Quels capteurs dans AKK200 ?",
            "rag_pipeline_mode": "naive",
            "top_k": 2,
            "workspace_id": "workspace-andritz",
            "workspace_slug": "andritz",
        },
        doc_svc=FakePolicyRankingService(),
    )

    assert result["chunks"][0].startswith("AKK200 proximity switch")
    assert result["metadatas"][0]["retrieval_policy_score"] > 0
    assert result["metrics"]["retrieval_policy_enabled"] is True
    assert result["retrieval_policy"]["enabled"] is True
    assert "references projet stables" in result["retrieval_policy"]["prompt"]


async def test_retrieve_rag_context_filters_other_projects_for_missing_exact_project(monkeypatch):
    guide = SimpleNamespace(
        title="Andritz retrieval policy",
        markdown="""```agentium-retrieval-policy
{
  "query_planning": {
    "require_project_code_match": true,
    "protected_terms": ["BBA120", "AKK200"]
  },
  "answer_policy": {
    "instructions": ["Ne pas repondre depuis un autre projet si la reference exacte est absente."]
  }
}
```""",
        guide_key="guide-policy",
        version=1,
        target_type="collection",
        target_ref="andritz",
    )
    monkeypatch.setattr(rag_context, "_effective_guides_for_profile", lambda _profile: [guide])

    result = await retrieve_rag_context(
        {
            "query": "Liste de garniture de la carde 1 du projet COL100",
            "rag_pipeline_mode": "naive",
            "top_k": 2,
            "workspace_id": "workspace-andritz",
            "workspace_slug": "andritz",
        },
        doc_svc=FakePolicyRankingService(),
    )

    assert not any(meta.get("project_code") == "AKK200" for meta in result["metadatas"])
    assert result["metrics"]["document_chunks_retrieved"] == 0
    assert result["retrieval_constraints"]["required_terms"] == ["COL100"]
    assert result["retrieval_constraints"]["missing_terms"] == ["COL100"]
    assert result["metrics"]["retrieval_constraints"]["filtered_chunks_removed"] == 2


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
    assert "B = 85" in result["chunks"][0]
    assert "Spreadsheet sheet: test 1" not in "\n".join(result["chunks"])
    assert "Spreadsheet sheet: test 2" in result["chunks"][1]
    assert len(result["scores"]) == len(result["chunks"]) == len(result["metadatas"])


async def test_retrieve_rag_context_expands_spreadsheet_label_queries():
    doc_svc = FakeSpreadsheetLabelService()

    result = await retrieve_rag_context(
        {
            "query": "Quel est le diamètre B ?",
            "rag_pipeline_mode": "chah",
            "top_k": 3,
            "workspace_slug": "andritz",
        },
        doc_svc=doc_svc,
    )

    assert any("Def strips" in query for query in doc_svc.queries)
    assert any("B =" in query for query in doc_svc.queries)
    assert any("B = 85" in chunk for chunk in result["chunks"])
    assert result["pipeline"] == "chah_backend"


async def test_retrieve_rag_context_prioritises_exact_spreadsheet_label_value():
    result = await retrieve_rag_context(
        {
            "query": "dans les non tissés quel est le diamètre B ?",
            "rag_pipeline_mode": "chah",
            "top_k": 2,
            "workspace_slug": "andritz",
        },
        doc_svc=FakeSpreadsheetProtocolFirstService(),
    )

    assert "Spreadsheet sheet: Def strips" in result["chunks"][0]
    assert "B = 85" in result["chunks"][0]


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


# --- Expert-fiche always a candidate under a hard scope ------------------------
#
# Regression for: when the corpus planner applies a HARD knowledge scope (a
# ledger/table document_filename narrowing), it OVERWRITES the collection list —
# dropping the expert-fiche collection that ``get_retrieval_profile`` appended.
# With ``expert_fiche_correction_enabled`` on, the fiche collection must be
# re-unioned AFTER all narrowing and searched UNSCOPED so the planner's hard
# document_filename filter (scoped to the other collections' docs) can no longer
# exclude it. The weight-18 boost then reorders it; here we only prove candidacy.

_ANDRITZ_NOTICES = "andritz-notices-techniques-spl-pilot"
_ANDRITZ_ARCHIVE = "andritz-notices-archive-spl-pilot"
_ANDRITZ_FICHE = "andritz-expert-fiche"


def _plan_corpus_narrowing_to(collections, filters):
    """Fake ``plan_corpus`` that emulates a HARD scope narrowing.

    Returns a CorpusPlan whose ``retrieval_scope['collections']`` is exactly the
    narrowed non-fiche set (as the ledger/table planner does), carrying the hard
    ``document_filename`` filter — reproducing the gate that dropped the fiche.
    """

    def _fake(*, db, profile, query, request=None, retrieval_policy=None):
        return rag_corpus_planner.CorpusPlan(
            intent="content_search",
            dense=False,
            source_count=1,
            chunk_count=1,
            latency_profile="fast",
            deadline_seconds=2.5,
            top_k=profile["top_k"],
            candidate_pool_k=profile["candidate_pool_k"],
            synthesis_k=profile["synthesis_k"],
            source_display_k=profile["source_display_k"],
            retrieval_scope={"collections": list(collections)},
            filters=dict(filters),
        )

    return _fake


def _install_multi_collection_capture(monkeypatch):
    """Wire the fan-out fakes and return the per-collection filter capture dict."""
    monkeypatch.setattr(
        rag_context,
        "get_resolved_settings",
        lambda **_kwargs: {
            "ragCollectionName": "documents",
            "ragVectorDBType": "qdrant",
            "ragTopK": 5,
            "ragPipelineMode": "chah",
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

    captured_filters: dict = {}

    async def _fake_retrieve(doc_svc, query, _mode, **kwargs):
        captured_filters[doc_svc.collection_name] = dict(kwargs.get("filters") or {})
        metadata = {"document_title": doc_svc.collection_name}
        if doc_svc.collection_name == _ANDRITZ_FICHE:
            metadata["source_type"] = "expert_fiche"
        return SimpleNamespace(
            chunks=[f"{doc_svc.collection_name}:{query}"],
            scores=[0.9],
            metadatas=[metadata],
            pipeline="chah",
            label="test",
            reason="test",
            detail="test",
        )

    monkeypatch.setattr(rag_context, "retrieve_for_mode", _fake_retrieve)
    return captured_filters


async def test_hard_scope_still_includes_expert_fiche_collection_unscoped(monkeypatch):
    monkeypatch.setattr(
        rag_context,
        "resolve_knowledge_scope",
        lambda **_kwargs: {
            "key": "andritz_spl",
            "label": "Andritz SPL",
            "collection_slugs": [_ANDRITZ_NOTICES, _ANDRITZ_ARCHIVE],
            "default_mode": "chah",
            "top_k": 5,
        },
    )
    # Planner narrows to a single non-fiche collection with a HARD doc filter
    # (drops both the scope's archive collection AND the appended fiche).
    hard_filter = {"document_filename": ["Notice_convoyeur_J1.pdf"]}
    monkeypatch.setattr(
        rag_context,
        "plan_corpus",
        _plan_corpus_narrowing_to([_ANDRITZ_NOTICES], hard_filter),
    )
    captured_filters = _install_multi_collection_capture(monkeypatch)

    result = await retrieve_rag_context(
        {
            "query": "réglage bande convoyeur J1 pointe unique",
            "workspace_id": "workspace-andritz",
            "workspace_slug": "andritz",
            "knowledge_scope": "andritz_spl",
            "source_policy": {"expert_fiche_correction_enabled": True},
        }
    )

    # The fiche collection survives the hard scope and is a candidate...
    assert _ANDRITZ_FICHE in result["collections_touched"]
    assert _ANDRITZ_NOTICES in result["collections_touched"]
    # ...and the planner's non-fiche narrowing is NOT broadened (archive dropped).
    assert _ANDRITZ_ARCHIVE not in result["collections_touched"]
    # The notices collection keeps the planner's hard document scope...
    assert captured_filters[_ANDRITZ_NOTICES] == hard_filter
    # ...but the fiche overlay is searched UNSCOPED so the hard filter can't
    # exclude its chunks.
    assert captured_filters[_ANDRITZ_FICHE] == {}
    assert result["metrics"]["expert_fiche_collection"] == _ANDRITZ_FICHE
    assert result["metrics"]["expert_fiche_collection_included"] is True
    assert result["metrics"]["expert_fiche_collection_searched"] is True


async def test_hard_scope_without_expert_fiche_flag_does_not_broaden(monkeypatch):
    monkeypatch.setattr(
        rag_context,
        "resolve_knowledge_scope",
        lambda **_kwargs: {
            "key": "andritz_spl",
            "label": "Andritz SPL",
            "collection_slugs": [_ANDRITZ_NOTICES, _ANDRITZ_ARCHIVE],
            "default_mode": "chah",
            "top_k": 5,
        },
    )
    hard_filter = {"document_filename": ["Notice_convoyeur_J1.pdf"]}
    monkeypatch.setattr(
        rag_context,
        "plan_corpus",
        _plan_corpus_narrowing_to([_ANDRITZ_NOTICES, _ANDRITZ_ARCHIVE], hard_filter),
    )
    captured_filters = _install_multi_collection_capture(monkeypatch)

    result = await retrieve_rag_context(
        {
            "query": "maintenance archive notice technique planning",
            "workspace_id": "workspace-andritz",
            "workspace_slug": "andritz",
            "knowledge_scope": "andritz_spl",
            # No expert_fiche_correction_enabled -> feature OFF.
            "source_policy": {"industrial_grounding": True},
        }
    )

    # Feature OFF: the candidate set is exactly the planner's narrowed scope; the
    # fiche collection is never added and nothing is broadened.
    assert result["collections_touched"] == [_ANDRITZ_NOTICES, _ANDRITZ_ARCHIVE]
    assert _ANDRITZ_FICHE not in result["collections_touched"]
    assert captured_filters[_ANDRITZ_NOTICES] == hard_filter
    assert captured_filters[_ANDRITZ_ARCHIVE] == hard_filter
    assert _ANDRITZ_FICHE not in captured_filters
    assert result["metrics"]["expert_fiche_collection"] is None
    assert result["metrics"]["expert_fiche_collection_included"] is False
    assert "expert_fiche_collection_searched" not in result["metrics"]


async def test_expert_fiche_compat_overlay_survives_derived_membrane_allowlist(monkeypatch):
    monkeypatch.setattr(
        rag_context,
        "resolve_knowledge_scope",
        lambda **_kwargs: {
            "key": "andritz_spl",
            "label": "Andritz SPL",
            "collection_slugs": [_ANDRITZ_NOTICES],
            "default_mode": "chah",
            "top_k": 5,
        },
    )
    # Planner is a passthrough here: the ONLY collection-narrowing gate under
    # test is the authoritative membrane inbound allowlist (which excludes the
    # fiche). Proves the post-planner union restores it after that filter too.
    def _passthrough_plan_corpus(*, db, profile, query, request=None, retrieval_policy=None):
        return rag_corpus_planner.CorpusPlan(
            intent="content_search",
            dense=False,
            source_count=1,
            chunk_count=1,
            latency_profile="fast",
            deadline_seconds=2.5,
            top_k=profile["top_k"],
            candidate_pool_k=profile["candidate_pool_k"],
            synthesis_k=profile["synthesis_k"],
            source_display_k=profile["source_display_k"],
            retrieval_scope={"collections": list(profile.get("collections") or [])},
            filters={},
        )

    monkeypatch.setattr(rag_context, "plan_corpus", _passthrough_plan_corpus)
    _install_multi_collection_capture(monkeypatch)

    request = {
        "query": "membrane allowlist convoyeur J1 correction experte",
        "workspace_id": "workspace-andritz",
        "workspace_slug": "andritz",
        "knowledge_scope": "andritz_spl",
        "source_policy": {
            "expert_fiche_correction_enabled": True,
            # A derived/v1 compatibility spec keeps the historical correction
            # overlay even when its advisory allowlist omits the fiche.
            "membrane_spec": {"inbound": {"collection_allowlist": [_ANDRITZ_NOTICES]}},
        },
    }

    # The membrane inbound filter (in get_retrieval_profile) drops the fiche...
    profile = get_retrieval_profile(dict(request))
    assert profile["collections"] == [_ANDRITZ_NOTICES]

    # ...but the post-narrowing union restores it as an authoritative candidate.
    result = await retrieve_rag_context(request)
    assert _ANDRITZ_FICHE in result["collections_touched"]
    assert _ANDRITZ_NOTICES in result["collections_touched"]


async def test_expert_fiche_cannot_bypass_v2_enforce_membrane_allowlist(monkeypatch):
    monkeypatch.setattr(
        rag_context,
        "resolve_knowledge_scope",
        lambda **_kwargs: {
            "key": "andritz_spl",
            "label": "Andritz SPL",
            "collection_slugs": [_ANDRITZ_NOTICES],
            "default_mode": "chah",
            "top_k": 5,
        },
    )

    def _passthrough_plan_corpus(*, db, profile, query, request=None, retrieval_policy=None):
        return rag_corpus_planner.CorpusPlan(
            intent="content_search",
            dense=False,
            source_count=1,
            chunk_count=1,
            latency_profile="fast",
            deadline_seconds=2.5,
            top_k=profile["top_k"],
            candidate_pool_k=profile["candidate_pool_k"],
            synthesis_k=profile["synthesis_k"],
            source_display_k=profile["source_display_k"],
            retrieval_scope={"collections": list(profile.get("collections") or [])},
            filters={},
        )

    monkeypatch.setattr(rag_context, "plan_corpus", _passthrough_plan_corpus)
    captured_filters = _install_multi_collection_capture(monkeypatch)
    result = await retrieve_rag_context(
        {
            "query": "membrane v2 correction boundary",
            "workspace_id": "workspace-andritz",
            "workspace_slug": "andritz",
            "knowledge_scope": "andritz_spl",
            "source_policy": {
                "expert_fiche_correction_enabled": True,
                "membrane_spec": {
                    "version": 2,
                    "enforcement_mode": "enforce",
                    "inbound": {"collection_allowlist": [_ANDRITZ_NOTICES]},
                },
            },
        }
    )

    assert result["collections_touched"] == [_ANDRITZ_NOTICES]
    assert _ANDRITZ_FICHE not in captured_filters
    assert result["metrics"]["expert_fiche_collection"] is None
    assert result["metrics"]["expert_fiche_collection_included"] is False


# --- Document-discovery widen-then-rerank-then-truncate -------------------------

_DISCOVERY_POLICY_GUIDE = SimpleNamespace(
    title="Andritz",
    markdown=(
        "```agentium-retrieval-policy\n"
        '{"query_planning": {"require_project_code_match": true}}\n'
        "```"
    ),
    guide_key="discovery-policy",
    version=1,
    target_type="collection",
    target_ref="andritz",
)


def _ara200_pool(top_k: int, conveyor_index: int = 20):
    """Synthetic candidate pool: generic ARA200 covers, with the specific
    operating_manual conveyor doc buried at ``conveyor_index`` so it is only
    reachable when the pool is widened past the default top_k."""
    chunks: list[str] = []
    scores: list[float] = []
    metas: list[dict] = []
    for i in range(top_k):
        if i == conveyor_index:
            chunks.append("Conveyor jetlace operating description for ARA200.")
            scores.append(0.40)
            metas.append(
                {
                    "project_code": "ARA200",
                    "source_family": "operating_manual",
                    "document_filename": "conveyor.html",
                    "inner_document_path": "ARA200/fichiers/users manual/section 3/conveyor.html",
                }
            )
        else:
            chunks.append(f"ARA200 Part's Manual. Printable version cover page {i}.")
            scores.append(0.99 - i * 0.001)
            metas.append(
                {
                    "project_code": "ARA200",
                    "source_family": "html_manual",
                    "document_filename": "printable version.pdf",
                    "inner_document_path": f"ARA200/fichiers/printable version/p{i}.pdf",
                }
            )
    return chunks, scores, metas


def test_discovery_pool_top_k_helper():
    # Non-discovery: pool size is exactly the requested top_k.
    assert rag_context._discovery_pool_top_k(6, False) == 6
    assert rag_context._discovery_pool_top_k(50, False) == 50
    # Discovery: widened to at least the discovery floor, never narrowed.
    assert rag_context._discovery_pool_top_k(6, True) == rag_context._DISCOVERY_POOL_K
    assert rag_context._discovery_pool_top_k(rag_context._DISCOVERY_POOL_K + 5, True) == (
        rag_context._DISCOVERY_POOL_K + 5
    )


async def test_discovery_widens_pool_then_truncates_single_collection(monkeypatch):
    monkeypatch.setattr(rag_context, "_effective_guides_for_profile", lambda _p: [_DISCOVERY_POLICY_GUIDE])
    captured: dict = {}

    async def _fake_resolve(*_a, **_k):
        return True, "chah", "test"

    monkeypatch.setattr(rag_context, "resolve_retrieval_mode", _fake_resolve)

    async def _fake_retrieve(doc_svc, query, mode, *, top_k, **_k):  # noqa: ARG001
        captured["top_k"] = top_k
        chunks, scores, metas = _ara200_pool(top_k, conveyor_index=2)
        return SimpleNamespace(
            chunks=chunks, scores=scores, metadatas=metas,
            pipeline="chah_backend", label="t", reason="r", detail="d",
        )

    monkeypatch.setattr(rag_context, "retrieve_for_mode", _fake_retrieve)

    result = await retrieve_rag_context(
        {
            "query": "Quels documents de convoyeur sont indexés pour ARA200 ?",
            "rag_pipeline_mode": "chah",
            "top_k": 6,
            "workspace_id": "workspace-andritz",
            "workspace_slug": "andritz",
        },
        doc_svc=FakeDocumentService(),
    )

    # Fast profile keeps discovery bounded instead of widening to the old 120 pool.
    assert captured["top_k"] <= 20
    # ...and the relevant operating_manual candidate remains in the bounded context.
    assert any(chunk.startswith("Conveyor jetlace") for chunk in result["chunks"])
    # ...and the returned document payload is truncated back to top_k.
    assert result["metrics"]["document_chunks_retrieved"] == 6


async def test_non_discovery_pool_size_and_absence_unchanged(monkeypatch):
    monkeypatch.setattr(rag_context, "_effective_guides_for_profile", lambda _p: [_DISCOVERY_POLICY_GUIDE])
    captured: dict = {}

    async def _fake_resolve(*_a, **_k):
        return True, "chah", "test"

    monkeypatch.setattr(rag_context, "resolve_retrieval_mode", _fake_resolve)

    async def _fake_retrieve(doc_svc, query, mode, *, top_k, **_k):  # noqa: ARG001
        captured["top_k"] = top_k
        chunks, scores, metas = _ara200_pool(top_k)
        return SimpleNamespace(
            chunks=chunks, scores=scores, metadatas=metas,
            pipeline="chah_backend", label="t", reason="r", detail="d",
        )

    monkeypatch.setattr(rag_context, "retrieve_for_mode", _fake_retrieve)

    result = await retrieve_rag_context(
        {
            "query": "Comment nettoyer le convoyeur ARA200 ?",
            "rag_pipeline_mode": "chah",
            "top_k": 6,
            "workspace_id": "workspace-andritz",
            "workspace_slug": "andritz",
        },
        doc_svc=FakeDocumentService(),
    )

    # No widening for a factual query: pool size equals the requested top_k...
    assert captured["top_k"] == 6
    # ...so the buried conveyor doc was never retrieved, and no extra truncation
    # step changes the (already top_k-sized) result.
    assert all(not c.startswith("Conveyor jetlace") for c in result["chunks"])
    assert result["metrics"]["document_chunks_retrieved"] == 6


async def test_multi_collection_discovery_widens_and_surfaces_preferred(monkeypatch):
    monkeypatch.setattr(
        rag_context,
        "get_resolved_settings",
        lambda **_kwargs: {
            "ragCollectionName": "documents",
            "ragVectorDBType": "qdrant",
            "ragTopK": 6,
            "ragPipelineMode": "chah",
        },
    )
    monkeypatch.setattr(
        rag_context,
        "resolve_knowledge_scope",
        lambda **_kwargs: {
            "key": "andritz-spl",
            "label": "Andritz SPL",
            "collection_slugs": ["andritz-manuals", "andritz-notices"],
            "default_mode": "chah",
            "top_k": 6,
        },
    )
    monkeypatch.setattr(rag_context, "_effective_guides_for_profile", lambda _p: [_DISCOVERY_POLICY_GUIDE])
    monkeypatch.setattr(
        rag_context,
        "_document_service_for_profile",
        lambda _profile, collection: SimpleNamespace(collection_name=collection),
    )

    async def _fake_resolve(*_a, **_k):
        return True, "chah", "test"

    monkeypatch.setattr(rag_context, "resolve_retrieval_mode", _fake_resolve)

    captured_top_ks: list[int] = []

    async def _fake_retrieve(doc_svc, query, mode, *, top_k, **_k):  # noqa: ARG001
        captured_top_ks.append(top_k)
        chunks, scores, metas = _ara200_pool(top_k, conveyor_index=10)
        return SimpleNamespace(
            chunks=chunks, scores=scores, metadatas=metas,
            pipeline="chah_backend", label="t", reason="r", detail="d",
        )

    monkeypatch.setattr(rag_context, "retrieve_for_mode", _fake_retrieve)

    result = await retrieve_rag_context(
        {
            "query": "Quels documents de convoyeur sont indexés pour ARA200 ?",
            "workspace_id": "workspace-andritz",
            "workspace_slug": "andritz",
            "knowledge_scope": "andritz-spl",
        }
    )

    assert result["pipeline"].startswith("multi_")
    # Fast profile keeps every per-collection retrieval bounded.
    assert captured_top_ks and all(k <= 20 for k in captured_top_ks)
    # The conveyor operating_manual doc, fused from a wide pool, wins the rerank.
    assert result["chunks"][0].startswith("Conveyor jetlace")
    assert result["metadatas"][0]["document_filename"] == "conveyor.html"
    # Final document payload is truncated to the synthesis budget, not the
    # compact source-display top_k.
    assert result["metrics"]["document_chunks_retrieved"] == 12
    assert result["metrics"]["source_display_k"] == 6


async def test_multi_collection_balanced_scoped_uses_planner_sparse_decisions(
    db_session,
    monkeypatch,
):
    monkeypatch.setattr(rag_context.settings, "rag_dense_chunk_threshold", 100)
    monkeypatch.setattr(rag_context.settings, "rag_dense_source_threshold", 2)
    workspace = Workspace(id="ws-multi-balanced", name="Multi Balanced", slug="multi-balanced")
    db_session.add(workspace)
    db_session.commit()
    collection_a = create_collection(db_session, workspace=workspace, name="Multi Balanced A")
    collection_b = create_collection(db_session, workspace=workspace, name="Multi Balanced B")
    for collection, suffix in ((collection_a, "a"), (collection_b, "b")):
        upsert_collection_source(
            db_session,
            collection=collection,
            filename=f"A__ACJ100__start_procedure_{suffix}.html",
            status="ready",
            chunk_count=120,
        )
    db_session.add(
        KnowledgeDocumentFact(
            workspace_id=workspace.id,
            collection_id=collection_a.id,
            collection_slug=collection_a.slug,
            document_id="doc-start-a",
            document_filename="A__ACJ100__start_procedure_a.html",
            semantic_type="document_procedure_step",
            subject="démarrage ACJ100",
            predicate="procedure_step",
            content="Procédure de démarrage: vérifier les sécurités puis lancer la machine.",
            confidence=0.9,
        )
    )
    db_session.commit()
    monkeypatch.setattr(
        rag_context,
        "get_resolved_settings",
        lambda **_kwargs: {
            "ragCollectionName": collection_a.slug,
            "ragVectorDBType": "qdrant",
            "ragTopK": 6,
            "ragPipelineMode": "chah",
        },
    )
    monkeypatch.setattr(
        rag_context,
        "resolve_knowledge_scope",
        lambda **_kwargs: {
            "key": "multi-balanced-spl",
            "label": "Multi Balanced SPL",
            "collection_slugs": [collection_a.slug, collection_b.slug],
            "default_mode": "chah",
            "top_k": 6,
        },
    )
    monkeypatch.setattr(rag_context, "_effective_guides_for_profile", lambda _p: [])

    class MultiDenseService:
        def __init__(self, collection_name: str):
            self.collection_name = collection_name

        async def get_document_count(self) -> int:
            return 240

    monkeypatch.setattr(
        rag_context,
        "_document_service_for_profile",
        lambda _profile, collection: MultiDenseService(collection),
    )
    captured: list[dict] = []

    async def _fake_retrieve(doc_svc, query, mode, **kwargs):  # noqa: ARG001
        captured.append({"collection": doc_svc.collection_name, "mode": mode, **kwargs})
        return SimpleNamespace(
            chunks=[f"balanced scoped chunk {doc_svc.collection_name}"],
            scores=[0.82],
            metadatas=[{"document_filename": "A__ACJ100__start_procedure_a.html"}],
            pipeline="chah_backend",
            label="C-HAH",
            reason="balanced scoped",
            detail="test",
            diagnostics={"sparse_backend": "opensearch", "sparse_status": "empty"},
        )

    monkeypatch.setattr(rag_context, "retrieve_for_mode", _fake_retrieve)

    result = await retrieve_rag_context(
        {
            "query": "Explique la procédure de démarrage",
            "workspace_id": workspace.id,
            "workspace_slug": workspace.slug,
            "knowledge_scope": "multi-balanced-spl",
            "latency_profile": "balanced",
            "rag_pipeline_mode": "chah",
        }
    )

    assert result["pipeline"].startswith("multi_")
    assert result["dense_policy"] == "fast_scoped_dense"
    assert len(captured) == 2
    assert {item["collection"] for item in captured} == {collection_a.slug, collection_b.slug}
    assert all(item["mode"] == "chah" for item in captured)
    assert all(item["hah_chah_enabled"] is True for item in captured)
    assert all(item["use_hybrid"] is True for item in captured)
    assert all(item["allow_legacy_hybrid"] is False for item in captured)
    assert all(item["max_variants"] == 3 for item in captured)
    assert all(item["max_candidates"] <= 80 for item in captured)
    assert all(item["filters"] == {"document_filename": ["A__ACJ100__start_procedure_a.html"]} for item in captured)
    assert result["retrieval_plan"]["layers"]["sparse"]["enabled"] is True
    assert result["retrieval_plan"]["layers"]["hah_chah"]["enabled"] is True


def test_rag_retrieve_context_task_delegates_to_service(monkeypatch):
    import app.workers as workers_package

    class FakeCelery:
        def __init__(self, *_args, **_kwargs):
            self.conf = SimpleNamespace(update=lambda **_kwargs: None)

        def task(self, name=None, **_options):
            def _decorator(fn):
                return SimpleNamespace(run=fn, name=name)

            return _decorator

    monkeypatch.setitem(sys.modules, "celery", SimpleNamespace(Celery=FakeCelery))
    monkeypatch.setattr(
        "app.services.rag.context.run_rag_retrieve_context",
        lambda payload: {"chunks": [payload["query"]], "metrics": {"chunks_retrieved": 1}},
    )
    # Isolate both import caches. Importing a submodule also stores it as an
    # attribute on its parent package; clearing only ``sys.modules`` leaves the
    # FakeCelery module visible to tests collected later in the same process.
    missing = object()
    module_names = ("app.workers.celery_app", "app.workers.tasks")
    package_attrs = ("celery_app", "tasks")
    saved_modules = {name: sys.modules.get(name, missing) for name in module_names}
    saved_attrs = {
        name: getattr(workers_package, name, missing) for name in package_attrs
    }
    for name in module_names:
        sys.modules.pop(name, None)
    for name in package_attrs:
        if hasattr(workers_package, name):
            delattr(workers_package, name)

    try:
        from app.workers.tasks import rag_retrieve_context

        assert rag_retrieve_context.run({"query": "worker query"}) == {
            "chunks": ["worker query"],
            "metrics": {"chunks_retrieved": 1},
        }
    finally:
        for name, value in saved_modules.items():
            if value is missing:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = value
        for name, value in saved_attrs.items():
            if value is missing:
                if hasattr(workers_package, name):
                    delattr(workers_package, name)
            else:
                setattr(workers_package, name, value)


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


def test_retrieval_profile_treats_ui_auto_as_unset(monkeypatch):
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
            "key": "andritz_non_wovens_france_excel_pilot",
            "label": "NON-WOVENS France Excel pilot",
            "collection_slugs": ["andritz-non-wovens-france-excel-pilot"],
            "default_mode": "chah",
            "top_k": 5,
        },
    )

    profile = get_retrieval_profile(
        {
            "query": "dans les non tissés quel est le diamètre B ?",
            "workspace_id": "workspace-andritz",
            "workspace_slug": "andritz",
            "knowledge_scope": "andritz_non_wovens_france_excel_pilot",
            "rag_pipeline_mode": "auto",
            "agent_preferences": {"rag_pipeline_mode": "auto"},
        }
    )

    assert profile["rag_mode"] == "chah"


def test_retrieval_profile_defaults_to_fast_and_clamps_untrusted_budget(monkeypatch):
    monkeypatch.setattr(
        rag_context,
        "get_resolved_settings",
        lambda **_kwargs: {
            "ragCollectionName": "documents",
            "ragVectorDBType": "qdrant",
            "ragTopK": 50,
            "ragCandidatePoolK": 500,
            "ragSynthesisK": 200,
            "ragSourceDisplayK": 100,
            "ragPipelineMode": "chah",
        },
    )

    profile = get_retrieval_profile(
        {
            "query": "Analyse globale SPL",
            "workspace_id": "workspace-andritz",
            "workspace_slug": "andritz",
            "top_k": 999,
            "candidate_pool_k": 999,
            "synthesis_k": 999,
            "source_display_k": 999,
        }
    )

    assert profile["latency_profile"] == "fast"
    assert profile["top_k"] == 8
    assert profile["source_display_k"] == 8
    assert profile["synthesis_k"] == 12
    assert profile["candidate_pool_k"] == 20
    assert profile["deadline_seconds"] == settings.rag_fast_retrieval_deadline_seconds
    assert profile["latency_budget"] == {
        "profile": "fast",
        "retrieval_profile": "chat",
        "allow_cross_encoder": True,
        "deadline_seconds": settings.rag_fast_retrieval_deadline_seconds,
        "top_k": 8,
        "candidate_pool_k": 20,
    }


def test_retrieval_profile_oracle_fast_forces_bounded_single_pass(monkeypatch):
    monkeypatch.setattr(rag_context, "get_resolved_settings", lambda **kwargs: {"ragVectorDBType": "qdrant"})

    profile = get_retrieval_profile(
        {
            "query": "prélecture capture vibration",
            "retrieval_profile": "oracle_fast",
            "latency_profile": "deep",
            "rag_pipeline_mode": "auto",
            "top_k": 12,
            "candidate_pool_k": 200,
        }
    )

    assert profile["retrieval_profile"] == "oracle_fast"
    assert profile["latency_profile"] == "fast"
    assert profile["rag_mode"] == "naive"
    assert profile["top_k"] == 8
    assert profile["candidate_pool_k"] == 20
    assert profile["deadline_seconds"] == 2.5
    assert profile["latency_budget"]["retrieval_profile"] == "oracle_fast"
    assert profile["latency_budget"]["allow_cross_encoder"] is False
    assert profile["retrieval_profile_contract"]["allow_hah_chah"] is False


def test_retrieval_profile_oracle_live_fast_is_tightly_bounded(monkeypatch):
    monkeypatch.setattr(rag_context, "get_resolved_settings", lambda **kwargs: {"ragVectorDBType": "qdrant"})

    profile = get_retrieval_profile(
        {
            "query": "prélecture capture vibration",
            "retrieval_profile": "oracle_live_fast",
            "latency_profile": "deep",
            "rag_pipeline_mode": "auto",
            "top_k": 12,
            "candidate_pool_k": 200,
        }
    )

    assert profile["retrieval_profile"] == "oracle_live_fast"
    assert profile["latency_profile"] == "fast"
    assert profile["rag_mode"] == "naive"
    assert profile["top_k"] == 3
    assert profile["source_display_k"] == 3
    assert profile["synthesis_k"] == 3
    assert profile["candidate_pool_k"] == 12
    assert profile["deadline_seconds"] == 1.8
    assert profile["latency_budget"]["allow_cross_encoder"] is False


def test_retrieval_profile_oracle_grounded_async_keeps_quality_budget_without_cross_encoder(monkeypatch):
    monkeypatch.setattr(rag_context, "get_resolved_settings", lambda **kwargs: {"ragVectorDBType": "qdrant"})

    profile = get_retrieval_profile(
        {
            "query": "questions fondées SPL",
            "retrieval_profile": "oracle_grounded_async",
            "latency_profile": "deep",
            "rag_pipeline_mode": "auto",
            "top_k": 12,
            "candidate_pool_k": 200,
            "synthesis_k": 200,
            "source_display_k": 200,
        }
    )

    assert profile["retrieval_profile"] == "oracle_grounded_async"
    assert profile["latency_profile"] == "balanced"
    assert profile["rag_mode"] == "naive"
    assert profile["top_k"] == 6
    assert profile["source_display_k"] == 6
    assert profile["synthesis_k"] == 8
    assert profile["candidate_pool_k"] == 24
    assert profile["deadline_seconds"] == 6.0
    assert profile["latency_budget"]["allow_cross_encoder"] is False


def test_retrieval_profile_uses_system_collection_filter_as_scope(monkeypatch):
    monkeypatch.setattr(
        rag_context,
        "get_resolved_settings",
        lambda **_kwargs: {
            "ragCollectionName": "documents",
            "ragVectorDBType": "qdrant",
            "ragTopK": 5,
            "ragPipelineMode": "chah",
        },
    )

    profile = get_retrieval_profile(
        {
            "query": "Analyse les procédures SPL",
            "workspace_id": "workspace-andritz",
            "workspace_slug": "andritz",
            "retrieval_filters": {
                "collection_slug": "andritz-notices-techniques-spl-pilot",
                "source_kind": "markup",
            },
        }
    )

    assert profile["collection"] == "andritz-notices-techniques-spl-pilot"
    assert profile["collections"] == ["andritz-notices-techniques-spl-pilot"]
    assert profile["scope_label"] == "System retrieval scope"
    assert profile["retrieval_filters"] == {"source_kind": "markup"}


def test_retrieval_profile_deep_allows_wider_but_bounded_budget(monkeypatch):
    monkeypatch.setattr(
        rag_context,
        "get_resolved_settings",
        lambda **_kwargs: {
            "ragCollectionName": "documents",
            "ragVectorDBType": "qdrant",
            "ragTopK": 50,
            "ragCandidatePoolK": 500,
            "ragSynthesisK": 200,
            "ragSourceDisplayK": 100,
            "ragPipelineMode": "chah",
        },
    )

    profile = get_retrieval_profile(
        {
            "query": "Audit profond SPL",
            "workspace_id": "workspace-andritz",
            "workspace_slug": "andritz",
            "latency_profile": "deep",
            "deep_retrieval": True,
            "top_k": 999,
            "candidate_pool_k": 999,
            "synthesis_k": 999,
            "source_display_k": 999,
        }
    )

    assert profile["latency_profile"] == "deep"
    assert profile["top_k"] == 24
    assert profile["source_display_k"] == 24
    assert profile["synthesis_k"] == 48
    assert profile["candidate_pool_k"] == 200
    assert profile["deadline_seconds"] == settings.rag_deep_retrieval_deadline_seconds
    assert profile["latency_budget"] == {
        "profile": "deep",
        "retrieval_profile": "deep_async",
        "allow_cross_encoder": True,
        "deadline_seconds": settings.rag_deep_retrieval_deadline_seconds,
        "top_k": 24,
        "candidate_pool_k": 200,
    }


def test_retrieval_profile_augments_spreadsheet_follow_up_from_history(monkeypatch):
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
            "key": "andritz_non_wovens_france_excel_pilot",
            "label": "NON-WOVENS France Excel pilot",
            "collection_slugs": ["andritz-non-wovens-france-excel-pilot"],
            "default_mode": "chah",
            "top_k": 5,
        },
    )

    profile = get_retrieval_profile(
        {
            "query": "ok et vois tu des valeurs différentes dans plusieurs documents ?",
            "workspace_id": "workspace-andritz",
            "workspace_slug": "andritz",
            "knowledge_scope": "andritz_non_wovens_france_excel_pilot",
            "context": {
                "conversation_history": [
                    {
                        "role": "user",
                        "content": "dans la feuille def strips vois tu la valeur du label B ?",
                    },
                    {"role": "assistant", "content": "Le label B vaut 85."},
                ]
            },
        }
    )

    assert "valeurs différentes" in profile["query"]
    assert "def strips" in profile["query"]
    assert "label B" in profile["query"]


def test_retrieval_profile_preserves_raw_query_over_rewrite(monkeypatch):
    monkeypatch.setattr(
        rag_context,
        "get_resolved_settings",
        lambda **_kwargs: {
            "ragCollectionName": "documents",
            "ragVectorDBType": "qdrant",
            "ragTopK": 5,
            "ragPipelineMode": "chah",
        },
    )
    monkeypatch.setattr(
        rag_context,
        "resolve_knowledge_scope",
        lambda **_kwargs: {
            "key": "andritz_spl",
            "label": "Andritz SPL",
            "collection_slugs": ["andritz-notices-techniques-spl-pilot"],
            "default_mode": "chah",
            "top_k": 5,
        },
    )

    profile = get_retrieval_profile(
        {
            "query": "Peux-tu retrouver la liste de garniture de la carde numero 1 du projet COL100 ?",
            "rewritten_query": "Retrouver la liste de garniture de la carte numero 1 du projet COL100",
            "workspace_id": "workspace-andritz",
            "workspace_slug": "andritz",
            "knowledge_scope": "andritz_spl",
        }
    )

    assert "carde numero 1" in profile["query"]
    assert "carte numero 1" not in profile["query"]
    assert "COL100" in profile["query"]


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


def test_single_project_inventory_evidence_spec_is_scope_locked_and_policy_neutral():
    policy = RetrievalPolicy(
        aliases=(
            ("pompe", ("pump", "custom supplier model")),
            ("PRJ204", ("unrelated project alias",)),
        ),
    )

    spec = rag_context._single_project_inventory_evidence_spec(
        "Quelles sont les pompes du projet PRJ204 ?",
        {"project_code": ["PRJ204"]},
        policy,
    )

    assert spec is not None
    assert spec["project_code"] == "PRJ204"
    assert "pompes" in spec["terms"]
    assert "pump" in spec["terms"]
    assert "custom supplier model" not in spec["terms"]
    assert "unrelated project alias" not in spec["terms"]
    assert len(spec["terms"]) <= 12

    generic_spec = rag_context._single_project_inventory_evidence_spec(
        "Quels sont les brûleurs du projet PRJ204 ?",
        {"project_code": ["PRJ204"]},
        policy,
    )
    assert generic_spec is not None
    assert generic_spec["project_code"] == "PRJ204"
    assert "brûleurs" in generic_spec["terms"]

    for category_query in (
        "List safety valves for project PRJ204",
        "Inventory of repair kits for project PRJ204",
        "List installation tools for project PRJ204",
        "Liste des modules de diagnostic du projet PRJ204",
    ):
        category_spec = rag_context._single_project_inventory_evidence_spec(
            category_query,
            {"project_code": ["PRJ204"]},
            policy,
        )
        assert category_spec is not None
        assert category_spec["project_code"] == "PRJ204"

    assert (
        rag_context._single_project_inventory_evidence_spec(
            "Quelles sont les pompes du projet PRJ204 ?",
            {"project_code": ["OTHER999"]},
            policy,
        )
        is None
    )
    assert (
        rag_context._single_project_inventory_evidence_spec(
            "Quelles sont les pompes du projet PRJ204 ?",
            {
                "project_code": ["PRJ204"],
                "document_id": ["restricted-document"],
            },
            policy,
        )
        is None
    )
    assert (
        rag_context._single_project_inventory_evidence_spec(
            "Quelles sont les pompes des projets PRJ204 et XYZ300 ?",
            {"project_code": ["PRJ204", "XYZ300"]},
            policy,
        )
        is None
    )
    assert (
        rag_context._single_project_inventory_evidence_spec(
            "Quelles precautions de maintenance pour les pompes du projet PRJ204 ?",
            {"project_code": ["PRJ204"]},
            policy,
        )
        is None
    )
    assert (
        rag_context._single_project_inventory_evidence_spec(
            "Quelles pompes du projet PRJ204 et comment les installer ?",
            {"project_code": ["PRJ204"]},
            policy,
        )
        is None
    )

    english_spec = rag_context._single_project_inventory_evidence_spec(
        "Inventory of injectors for project PRJ204",
        {"project_code": ["PRJ204"]},
        policy,
    )
    assert english_spec is not None
    assert english_spec["project_code"] == "PRJ204"
    assert "injectors" in english_spec["terms"]


def test_inventory_evidence_coverage_survives_compression_without_growing_budget():
    chunks, scores, metadatas, diag = rag_context._ensure_inventory_evidence_coverage(
        ["semantic primary", "semantic tail"],
        [0.9, 0.7],
        [
            {"document_id": "primary"},
            {"document_id": "tail"},
        ],
        [
            {
                "content": "Complete pump P-101 in the spare parts list.",
                "score": 0.6,
                "metadata": {
                    "document_id": "spare",
                    "source_family": "spare_parts_list",
                },
            },
            {
                "content": "Centrifugal pump model Z-9 service manual.",
                "score": 0.55,
                "metadata": {"document_id": "supplier"},
            },
        ],
        synthesis_k=3,
        collection="notices",
    )

    assert len(chunks) == len(scores) == len(metadatas) == 3
    assert "Complete pump P-101" in " ".join(chunks)
    assert "Centrifugal pump model Z-9" in " ".join(chunks)
    assert sum(bool(meta.get("inventory_evidence")) for meta in metadatas) == 2
    assert all(
        meta.get("collection") == "notices"
        for meta in metadatas
        if meta.get("inventory_evidence")
    )
    assert diag == {"admission_cap": 2, "inserted": 1, "replaced": 1}
    assert metadatas[0]["source_family"] == "spare_parts_list"


def test_inventory_evidence_coverage_prioritizes_authority_then_score():
    rows = [
        {
            "content": "Authoritative complete pump list.",
            "score": 0.6,
            "metadata": {"source_family": "spare_parts_list", "document_id": "spl"},
        },
        {
            "content": "Low-value navigation pump row.",
            "score": 0.2,
            "metadata": {"document_id": "nav"},
        },
        {
            "content": "High-confidence second pump family.",
            "score": 0.9,
            "metadata": {"document_id": "manual"},
        },
    ]

    chunks, _scores, metadatas, diag = rag_context._ensure_inventory_evidence_coverage(
        [f"semantic {index}" for index in range(9)],
        [0.8] * 9,
        [{"document_id": f"semantic-{index}"} for index in range(9)],
        rows,
        synthesis_k=9,
        collection="notices",
    )

    assert chunks[:3] == [
        "Authoritative complete pump list.",
        "High-confidence second pump family.",
        "Low-value navigation pump row.",
    ]
    assert all(metadata.get("inventory_evidence") for metadata in metadatas[:3])
    assert diag == {"admission_cap": 3, "inserted": 0, "replaced": 3}


def test_inventory_evidence_coverage_reserves_sibling_family_and_eight_slots():
    rows = [
        {
            "content": "Authoritative complete equipment list.",
            "score": 0.95,
            "metadata": {"source_family": "spare_parts_list", "document_id": "spl"},
        },
        *[
            {
                "content": f"Attested model manual {index}.",
                "score": 0.9 - (index * 0.01),
                "metadata": {
                    "document_id": f"attested-{index}",
                    "inventory_family_attested_by_spare": True,
                    "inventory_functional_category": "process-line",
                },
            }
            for index in range(5)
        ],
        {
            "content": "Distinct sibling supplier family.",
            "score": 0.4,
            "metadata": {
                "document_id": "sibling",
                "inventory_family_attested_by_spare": False,
                "inventory_functional_category": "process-line",
            },
        },
        {
            "content": "Unrelated low-score family.",
            "score": 0.3,
            "metadata": {
                "document_id": "other",
                "inventory_family_attested_by_spare": False,
                "inventory_functional_category": "utilities",
            },
        },
    ]

    chunks, _scores, metadatas, diag = rag_context._ensure_inventory_evidence_coverage(
        [f"semantic {index}" for index in range(18)],
        [0.8] * 18,
        [{"document_id": f"semantic-{index}"} for index in range(18)],
        rows,
        synthesis_k=18,
        collection="notices",
    )

    assert len(chunks) == 18
    assert chunks[0] == "Authoritative complete equipment list."
    assert chunks[1] == "Distinct sibling supplier family."
    assert sum(bool(metadata.get("inventory_evidence")) for metadata in metadatas) == 8
    assert diag == {"admission_cap": 8, "inserted": 0, "replaced": 8}
