from __future__ import annotations

import sys
from types import SimpleNamespace

from app.services.rag import context as rag_context
from app.services.rag.context import get_retrieval_profile, retrieve_rag_context
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
        chunks, scores, metas = _ara200_pool(top_k)
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

    # Pool was widened before rerank...
    assert captured["top_k"] == rag_context._DISCOVERY_POOL_K
    # ...the buried operating_manual conveyor doc is promoted to the very top...
    assert result["chunks"][0].startswith("Conveyor jetlace")
    assert result["metadatas"][0]["document_filename"] == "conveyor.html"
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
    # Every per-collection retrieval was widened.
    assert captured_top_ks and all(k == rag_context._DISCOVERY_POOL_K for k in captured_top_ks)
    # The conveyor operating_manual doc, fused from a wide pool, wins the rerank.
    assert result["chunks"][0].startswith("Conveyor jetlace")
    assert result["metadatas"][0]["document_filename"] == "conveyor.html"
    # Final document payload is truncated to the synthesis budget, not the
    # compact source-display top_k.
    assert result["metrics"]["document_chunks_retrieved"] == 12
    assert result["metrics"]["source_display_k"] == 6


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
