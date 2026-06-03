from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta
from types import SimpleNamespace

from app.core.config import settings
from app.services.rag import context as rag_context
from app.services.rag.corpus_planner import classify_intent, is_catalogue_query, plan_corpus
from app.services.rag.context import get_retrieval_profile, retrieve_rag_context
from app.services.rag.summary_artifacts import rebuild_summary_index_artifact
from app.models.knowledge_document_fact import KnowledgeDocumentFact
from app.models.workspace import Workspace
from app.services.knowledge_collections import create_collection, upsert_collection_source


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
    assert result["metrics"]["candidate_counts"]["chunks_retrieved"] == 1
    assert result["metrics"]["candidate_counts"]["candidate_pool_k"] >= 1
    assert "exact_table_hits" in result["metrics"]["candidate_counts"]
    assert result["metrics"]["collection"] == "documents"
    assert result["metrics"]["vector_db"] == "qdrant"
    assert result["collections_touched"] == ["documents"]
    assert result["collection_errors"] == []


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
    assert classify_intent("Dans les fichiers NON-WOVENS France, que vaut le label B dans la table Def strips ?") == "content_search"


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

    for plan in (aco_plan, bba_plan, etachrom_plan, injector_plan, dci_plan):
        assert plan.dense_policy == "fast_scoped_dense"
        assert plan.fallback_reason is None
        assert "document_filename" in plan.filters
        assert plan.retrieval_plan["layers"]["dense_qdrant"]["enabled"] is True
        assert plan.retrieval_plan["layers"]["deep_async"]["enabled"] is False

    assert "spare part list ACO150.pdf" in aco_plan.filters["document_filename"]
    assert "Spare Parts List_BBA120.pdf" in bba_plan.filters["document_filename"]
    assert "Etachrom B.PDF" in etachrom_plan.filters["document_filename"]
    assert "IN 07 A- EXH injector cartridge cleaning.pdf" in injector_plan.filters["document_filename"]
    assert "DCI 110__PERFO-TE-OM-10-5 EN-C.pdf" in dci_plan.filters["document_filename"]

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


async def test_dense_collection_quick_ask_uses_coarse_inventory_without_global_search(db_session, monkeypatch):
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

    assert result["mode_label"] == "fast_scoped_dense_auto"
    assert result["dense_policy"] == "fast_scoped_dense_auto"
    assert result["pipeline"] == "dense_coarse_inventory"
    assert result["deep_retrieval_recommended"] is True
    assert result["metrics"]["dense_global_search_skipped"] is True
    assert result["retrieval_plan"]["guardrails"]["user_scope_required"] is False
    assert result["retrieval_plan"]["guardrails"]["global_chunk_search_allowed"] is False
    assert result["retrieval_plan"]["layers"]["dense_qdrant"]["enabled"] is False
    assert result["retrieval_plan"]["layers"]["deep_async"]["enabled"] is True
    assert result["candidate_pool_k"] <= 20
    assert not svc.calls


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


async def test_dense_collection_balanced_unscoped_uses_coarse_inventory_without_global_search(
    db_session,
    monkeypatch,
):
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

    assert result["dense_policy"] == "fast_scoped_dense_auto"
    assert result["pipeline"] == "dense_coarse_inventory"
    assert result["deep_retrieval_recommended"] is True
    assert result["retrieval_plan"]["guardrails"]["user_scope_required"] is False
    assert result["retrieval_plan"]["guardrails"]["global_chunk_search_allowed"] is False
    assert result["metrics"]["dense_global_search_skipped"] is True
    assert not svc.calls


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

    assert result["dense_policy"] == "fast_scoped_dense_auto"
    assert result["pipeline"] == "dense_coarse_inventory"
    assert result["retrieval_scope"]["source_count"] == 25
    assert result["retrieval_scope"]["chunk_count"] == 500
    assert result["retrieval_plan"]["guardrails"]["global_chunk_search_allowed"] is False
    assert result["metrics"]["dense_global_search_skipped"] is True
    assert not svc.calls


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
        "deadline_seconds": settings.rag_fast_retrieval_deadline_seconds,
        "top_k": 8,
        "candidate_pool_k": 20,
    }


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
