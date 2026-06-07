"""Unit tests for HAH/C-HAH-like pipeline retrieval (mocked DocumentService)."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest

from app.services.rag import pipeline_retrieval
from app.services.rag.pipeline_retrieval import (
    _merge_rrf,
    _prioritise_exact_project_reference_matches,
    _prioritise_spreadsheet_label_matches,
    _query_variants,
    _search_documents,
    retrieve_chah_like,
    retrieve_for_mode,
    retrieve_hah_like,
)
from app.services.rag.retrieval_policy import (
    RetrievalPolicy,
    evidence_coverage_details,
    rerank_results_with_policy,
)


def _mk_result(content: str, score: float, rank: int = 0) -> dict:
    return {
        "content": content,
        "combined_score": score,
        "score": score,
        "metadata": {},
        "id": f"id-{rank}",
    }


def test_evidence_coverage_matches_aliases_and_dimension_forms():
    policy = RetrievalPolicy(
        protected_terms=("AKK200", "LM 300"),
        aliases=(
            ("joint", ("O-ring", "O ring", "oring", "joint torique")),
            ("cartouche", ("Filtering cartridge", "filtering cartridge", "LM300", "LM 300")),
        ),
    )

    details = evidence_coverage_details(
        query="Quel fichier contient Filtering cartridge LM300 et O-ring string D. 3,6 pour AKK200 ?",
        content="Spare list AKK200: filtering cartridge LM 300, O ring string diameter 3.6.",
        metadata={"document_filename": "Spare Parts List.pdf"},
        policy=policy,
    )

    assert details["coverage"] >= 0.75
    assert "AKK200" in details["matched"]
    assert "joint" in details["matched"]
    assert "cartouche" in details["matched"]


def test_policy_rerank_prefers_evidence_complete_parent_over_raw_score():
    policy = RetrievalPolicy(
        protected_terms=("AKK200",),
        aliases=(
            ("joint", ("O-ring", "O ring", "oring")),
            ("cartouche", ("Filtering cartridge", "filtering cartridge", "LM300", "LM 300")),
        ),
    )
    rows = [
        {
            "content": "AKK200 spare list overview without the item labels.",
            "score": 0.99,
            "combined_score": 0.99,
            "metadata": {"document_filename": "overview.pdf"},
        },
        {
            "content": "AKK200 filtering cartridge LM 300 and O ring string D 3.6.",
            "score": 0.2,
            "combined_score": 0.2,
            "metadata": {"document_filename": "parts.pdf"},
        },
    ]

    out = rerank_results_with_policy(
        rows,
        "Quelle SPL AKK200 contient a la fois Filtering cartridge et O-ring ?",
        policy,
    )

    assert out[0]["metadata"]["document_filename"] == "parts.pdf"
    assert out[0]["metadata"]["retrieval_evidence_coverage"] > out[1]["metadata"]["retrieval_evidence_coverage"]


def test_prioritise_exact_project_reference_matches_before_near_codes():
    rows = [
        {
            "content": "near code evidence",
            "score": 0.99,
            "combined_score": 0.99,
            "metadata": {"document_filename": "TTN22077J Card control desk.pdf"},
        },
        {
            "content": "exact code evidence",
            "score": 0.2,
            "combined_score": 0.2,
            "metadata": {"document_filename": "TTN20777J card documentation.pdf"},
        },
    ]

    out = _prioritise_exact_project_reference_matches(rows, "Que dit TTN20777J ?")

    assert out[0]["metadata"]["document_filename"] == "TTN20777J card documentation.pdf"


class ExactTableFactService:
    async def list_table_facts(self, **kwargs):
        if kwargs.get("sheet_name") == "Def strips" and kwargs.get("row_label") == "B":
            return [
                {
                    "chunk_id": "def-b",
                    "semantic_type": "spreadsheet_cell_fact",
                    "document_filename": "GEOTEX-SPL-Y25.05.22-PIL.xlsx",
                    "sheet_name": "Def strips",
                    "row_index": 2,
                    "cell_ref": "B2",
                    "row_label": "B",
                    "value": "85",
                    "content": (
                        'Spreadsheet cell fact: sheet="Def strips" row=2 '
                        'label="B" value="85" label_cell=A2 value_cell=B2 '
                        'cell=B2 row_label="B" | B = 85'
                    ),
                }
            ]
        if kwargs.get("row_label") == "B":
            return [
                {
                    "chunk_id": "noise-b",
                    "semantic_type": "spreadsheet_cell_fact",
                    "document_filename": "other.xlsx",
                    "sheet_name": "Sheet1",
                    "row_label": "B",
                    "value": "7.8",
                    "content": (
                        'Spreadsheet cell fact: sheet="Sheet1" row=9 label="B" '
                        'value="7.8" cell=G9 row_label="B" | B = 7.8'
                    ),
                }
            ]
        return []

    async def search(self, query: str, top_k: int = 10, use_hybrid: bool = True):  # noqa: ARG002
        return [
            _mk_result(
                "Spreadsheet sheet: Sheet1 Row 9: F9=B | G9=7.8 | B = 7.8",
                0.98,
                0,
            ),
            _mk_result(
                "Spreadsheet sheet: unrelated Row 4: B4=CD (N/50 mm) | C4=250",
                0.95,
                1,
            ),
        ][:top_k]


class ExactMetadataService:
    collection_name = "generic-kb"

    def __init__(self, exact_rows: list[dict] | None = None, search_rows: list[dict] | None = None):
        self.exact_rows = exact_rows or []
        self.search_rows = search_rows or []
        self.exact_calls: list[dict] = []
        self.search_calls: list[dict] = []

    async def search_exact_metadata(
        self,
        query: str,
        top_k: int = 10,
        filters=None,
        lexical_config=None,
    ):
        self.exact_calls.append(
            {
                "query": query,
                "top_k": top_k,
                "filters": filters,
                "lexical_config": lexical_config,
            }
        )
        return self.exact_rows[:top_k]

    async def search(self, query: str, top_k: int = 10, filters=None, use_hybrid: bool = True):  # noqa: ARG002
        self.search_calls.append(
            {
                "query": query,
                "top_k": top_k,
                "filters": filters,
                "use_hybrid": use_hybrid,
            }
        )
        return self.search_rows[:top_k]


class DisabledSparseBackend:
    name = "disabled"

    async def search(self, *args, **kwargs):  # noqa: ARG002
        return []


class SparseOkBackend:
    name = "opensearch"

    async def search(self, *args, **kwargs):  # noqa: ARG002
        return [
            _mk_result("sparse opensearch evidence long enough for rrf merge", 1.2, 10)
        ]


class OpenSearchUnconfiguredBackend:
    name = "opensearch"
    base_url = ""

    def __init__(self):
        self.calls = 0

    async def search(self, *args, **kwargs):  # noqa: ARG002
        self.calls += 1
        return [_mk_result("should not be called without opensearch url", 1.0, 0)]


class QdrantSparseBackendFake:
    name = "qdrant_sparse"

    def __init__(self):
        self.calls = 0

    async def search(self, *args, **kwargs):  # noqa: ARG002
        self.calls += 1
        return [_mk_result("client sparse fallback should not run", 0.8, 0)]


class FastChatSparseBackendFake:
    name = "qdrant_sparse"

    def __init__(self):
        self.calls = 0

    async def search(self, *args, **kwargs):  # noqa: ARG002
        self.calls += 1
        return [
            {
                "id": "sparse-fast-1",
                "content": "fast sparse direct evidence long enough",
                "score": 0.88,
                "combined_score": 0.88,
                "metadata": {"document_id": "sparse-doc-1"},
            }
        ]


class FakeEmbedder:
    async def embed(self, query: str):  # noqa: ARG002
        return np.array([1.0, 0.0], dtype=np.float32)


class QdrantServerHybridVectorDb:
    collection_name = "andritz__docs"

    def __init__(self):
        self.calls = []

    async def search_hybrid(self, query_vector, query_text, top_k=10, filters=None, search_params=None):
        self.calls.append((query_vector, query_text, top_k, filters, search_params))
        return [
            {
                "id": "server-1",
                "content": "qdrant server fused evidence long enough",
                "score": 0.91,
                "combined_score": 0.91,
                "metadata": {
                    "document_id": "doc-1",
                    "sparse_backend": "qdrant_sparse",
                    "sparse_status": "ok",
                    "sparse_fusion": "server_rrf",
                },
            }
        ]


class QdrantServerHybridDocService:
    collection_name = "logical-docs"

    def __init__(self):
        self.embedder = FakeEmbedder()
        self.vector_db = QdrantServerHybridVectorDb()
        self.search = AsyncMock(return_value=[_mk_result("dense fallback should not run", 0.4, 0)])


class SlowFastChatDocService:
    collection_name = "logical-docs"

    def __init__(self):
        self.embedder = FakeEmbedder()
        self.vector_db = QdrantServerHybridVectorDb()
        self.cancelled = 0

    async def search_exact_metadata(self, *args, **kwargs):  # noqa: ARG002
        return []

    async def search(self, *args, **kwargs):  # noqa: ARG002
        try:
            await asyncio.sleep(5.0)
        except asyncio.CancelledError:
            self.cancelled += 1
            raise
        return [_mk_result("late dense evidence", 0.4, 0)]


class SlowSearchService:
    def __init__(self, delay: float = 0.2):
        self.delay = delay
        self.calls: list[str] = []

    async def search(self, query: str, top_k: int = 10, filters=None, use_hybrid: bool = True):  # noqa: ARG002
        self.calls.append(query)
        await asyncio.sleep(self.delay)
        return [_mk_result("slow evidence that should miss tiny deadline", 0.7, 0)][:top_k]


class CancellableSearchService:
    collection_name = "dense-kb"

    def __init__(self):
        self.cancelled = 0

    async def search(self, query: str, top_k: int = 10, filters=None, use_hybrid: bool = True):  # noqa: ARG002
        try:
            await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            self.cancelled += 1
            raise
        return [_mk_result("late dense evidence", 0.4, 0)]


class CancellableSparseBackend:
    name = "opensearch"

    def __init__(self):
        self.cancelled = 0

    async def search(self, *args, **kwargs):  # noqa: ARG002
        try:
            await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            self.cancelled += 1
            raise
        return [_mk_result("late sparse evidence", 0.9, 0)]


def test_merge_rrf_dedupes_and_orders():
    a = [
        _mk_result("chunk a unique longer text", 0.9, 0),
        _mk_result("chunk b longer text here", 0.5, 1),
    ]
    b = [
        _mk_result("chunk a unique longer text", 0.4, 0),
        _mk_result("chunk c longer text here ok", 0.8, 1),
    ]
    merged = _merge_rrf([a, b], top_k=3)
    assert len(merged) == 3
    contents = [m["content"] for m in merged]
    assert "chunk a unique longer text" in contents
    assert "chunk b longer text here" in contents
    assert "chunk c longer text here ok" in contents


def test_query_variants_short_query():
    assert _query_variants("hello") == ["hello"]


def test_query_variants_long_splits():
    long_q = "word " * 20
    v = _query_variants(long_q)
    assert len(v) >= 2
    assert v[0] == long_q.strip()


def test_query_variants_keep_guide_hints_separate_from_label_targets():
    variants = _query_variants(
        "Quel est le diamètre B ?",
        query_hints="Column A contains labels A, B, C. Column B contains values.",
    )

    assert any("Knowledge guide hints" in variant for variant in variants)
    assert any("Def strips label B value B =" in variant for variant in variants)
    assert any("Spreadsheet cell fact Def strips" in variant for variant in variants)
    assert not any("Def strips label A value A =" in variant for variant in variants)
    assert not any("Def strips label C value C =" in variant for variant in variants)


def test_query_variants_add_protocol_matrix_hints():
    variants = _query_variants(
        "Sur le test 2A du 21/05/2025 pour GEOTEX, quelle était la valeur du poids ?"
    )

    assert any("Protocole essais trials N° 2A" in variant for variant in variants)
    assert any("Spreadsheet sheet test 2 Weight Poids" in variant for variant in variants)
    assert any("2025-05-21" in variant for variant in variants)
    assert any("Poids Weight" in variant for variant in variants)
    assert any("Customer GEOTEX" in variant for variant in variants)


def test_query_variants_add_configured_knowledge_guide_policy_aliases():
    policy = RetrievalPolicy(
        protected_terms=("AKK200",),
        aliases=(("capteurs", ("sensor", "proximity switch", "XS1", "ZCT")),),
    )

    variants = _query_variants("Quels capteurs sont documentes dans AKK200 ?", retrieval_policy=policy)

    assert any("AKK200" == variant or variant.endswith(" AKK200") for variant in variants)
    assert any("proximity switch" in variant for variant in variants)


def test_spreadsheet_protocol_rerank_prioritises_trial_matrix():
    query = "Sur le test 2A du 21/05/2025 pour GEOTEX, quelle était la valeur du poids ?"
    rows = [
        _mk_result(
            "Spreadsheet sheet: Sheet1 Row 1: A1=Poids | B1=random unrelated weight table",
            0.9,
            0,
        ),
        _mk_result(
            "Spreadsheet sheet: Protocole essais Row 1: A1=Customer | B1=GEOTEX | C1=DATE | "
            "D1=2025-05-21 00:00:00 Row 4: A4=trials N° | I4=2A | J4=3B "
            "Row 12: A12=Poids | I12=42.5",
            0.2,
            1,
        ),
    ]

    reranked = _prioritise_spreadsheet_label_matches(rows, query)

    assert reranked[0]["content"].startswith("Spreadsheet sheet: Protocole essais")


def test_spreadsheet_protocol_rerank_prioritises_numbered_test_sheet():
    query = "Sur le test 2A du 21/05/2025 pour GEOTEX, quelle était la valeur du poids ?"
    rows = [
        _mk_result(
            "Spreadsheet sheet: Sheet1 Row 1: A1=Poids | B1=random unrelated weight table",
            0.9,
            0,
        ),
        _mk_result(
            "Spreadsheet sheet: test 2 Row 14: B14=Weight (g/m²) | I14=#DIV/0! "
            "Row 26: B26=Weight (g/m²) | D26=#DIV/0!",
            0.2,
            1,
        ),
    ]

    reranked = _prioritise_spreadsheet_label_matches(rows, query)

    assert reranked[0]["content"].startswith("Spreadsheet sheet: test 2")


def test_spreadsheet_protocol_rerank_prioritises_hemp_strip_sheet():
    query = "Quel est le strip standard utilisé pour la production de chanvre ?"
    rows = [
        _mk_result(
            "Spreadsheet sheet: Sheet1 Row 2: B2=Production | C2=generic run summary",
            0.9,
            0,
        ),
        _mk_result(
            "Spreadsheet sheet: STRIP GB434 100% CHANVRE Row 1: A1=Strip GB434 100% CHANVRE "
            "550g/m² Row 2: B2=Résistance en traction",
            0.2,
            1,
        ),
    ]

    reranked = _prioritise_spreadsheet_label_matches(rows, query)

    assert "CHANVRE" in reranked[0]["content"]


def test_spreadsheet_rerank_prioritises_interpreted_cell_facts():
    query = "Sur le test 2A du 21/05/2025 pour GEOTEX, quelle était la valeur du poids ?"
    rows = [
        _mk_result(
            "Spreadsheet sheet: Sheet1 Row 1: A1=Poids | B1=random unrelated weight table",
            0.9,
            0,
        ),
        _mk_result(
            'Spreadsheet interpreted cells: sheet="Protocole essais" row=12 | '
            'cell=I12 value="42.5" row_label="Poids" metric="Poids" parameter="Poids" '
            'column_header="2A" trial_or_sample="2A"',
            0.2,
            1,
        ),
    ]

    reranked = _prioritise_spreadsheet_label_matches(rows, query)

    assert reranked[0]["content"].startswith("Spreadsheet interpreted cells")


def test_spreadsheet_label_rerank_prioritises_label_value_facts():
    query = "Peux-tu retrouver le diamètre labellisé par la lettre B ?"
    rows = [
        _mk_result(
            "Spreadsheet sheet: generic Row 1: A1=B | B1=unrelated text",
            0.9,
            0,
        ),
        _mk_result(
            'Spreadsheet label-value fact: sheet="Def strips" row=2 '
            'label="B" value="85" label_cell=A2 value_cell=B2 | B = 85',
            0.2,
            1,
        ),
    ]

    reranked = _prioritise_spreadsheet_label_matches(rows, query)

    assert reranked[0]["content"].startswith("Spreadsheet label-value fact")


@pytest.mark.asyncio
async def test_retrieve_for_mode_prepends_exact_table_payload_before_noisy_search():
    out = await retrieve_for_mode(
        ExactTableFactService(),
        "Peux-tu me dire quel est le diamètre B ?",
        "auto",
        top_k=3,
    )

    assert out.chunks[0].startswith("Spreadsheet cell fact")
    assert "sheet=\"Def strips\"" in out.chunks[0]
    assert "B = 85" in out.chunks[0]
    assert out.metadatas[0]["cell_ref"] == "B2"
    assert "exact_table_hits=" in out.detail
    assert out.diagnostics["exact_table_attempted"] is True
    assert out.diagnostics["exact_table_hits"] >= 1
    assert out.diagnostics["exact_table_elapsed_ms"] >= 0


@pytest.mark.asyncio
async def test_retrieve_for_mode_prepends_exact_metadata_before_noisy_dense_neighbor():
    exact = {
        "id": "exact-prj204",
        "content": "Exact component catalogue for PRJ204.",
        "score": 12.0,
        "combined_score": 12.0,
        "metadata": {
            "document_id": "doc-prj204",
            "document_filename": "PRJ204 component catalogue.pdf",
            "project_code": "PRJ204",
            "exact_metadata_match": True,
            "retrieval_exact_terms_matched": ["prj204"],
        },
    }
    noisy = _mk_result("High-scoring semantic neighbor for PRJ205.", 0.99, 0)
    noisy["metadata"] = {"document_id": "doc-prj205", "document_filename": "PRJ205 catalogue.pdf"}
    doc = ExactMetadataService(exact_rows=[exact], search_rows=[noisy])

    out = await retrieve_for_mode(
        doc,
        "Find the component catalogue for PRJ204",
        "hybrid",
        top_k=2,
        use_hybrid=True,
    )

    assert out.chunks[0] == "Exact component catalogue for PRJ204."
    assert out.metadatas[0]["exact_metadata_match"] is True
    assert out.diagnostics["exact_metadata_attempted"] is True
    assert out.diagnostics["exact_metadata_hits"] == 1
    assert out.diagnostics["exact_match_missing"] is False
    assert doc.exact_calls[0]["top_k"] == 4


@pytest.mark.asyncio
async def test_retrieve_for_mode_marks_missing_required_exact_metadata_match():
    noisy = _mk_result("Generic component catalogue without the requested identifier.", 0.99, 0)
    noisy["metadata"] = {"document_id": "doc-generic", "document_filename": "generic catalogue.pdf"}
    doc = ExactMetadataService(exact_rows=[], search_rows=[noisy])

    out = await retrieve_for_mode(
        doc,
        "Find the component catalogue for PRJ204",
        "hybrid",
        top_k=1,
        use_hybrid=True,
    )

    assert out.chunks == ["Generic component catalogue without the requested identifier."]
    assert out.diagnostics["exact_metadata_attempted"] is True
    assert out.diagnostics["exact_metadata_hits"] == 0
    assert out.diagnostics["exact_match_required"] is True
    assert out.diagnostics["exact_match_missing"] is True


@pytest.mark.asyncio
async def test_retrieve_hah_like_keeps_exact_metadata_when_first_pass_is_empty():
    exact = {
        "id": "exact-prj204",
        "content": "Exact metadata-only evidence for PRJ204.",
        "score": 12.0,
        "combined_score": 12.0,
        "metadata": {
            "document_id": "doc-prj204",
            "document_filename": "PRJ204 manual.pdf",
            "exact_metadata_match": True,
        },
    }
    doc = ExactMetadataService(exact_rows=[exact], search_rows=[])

    out = await retrieve_hah_like(
        doc,
        "Open PRJ204 manual",
        top_k=2,
    )

    assert out.chunks == ["Exact metadata-only evidence for PRJ204."]
    assert out.reason.startswith("Exact metadata retrieval returned evidence")
    assert out.diagnostics["exact_metadata_hits"] == 1


@pytest.mark.asyncio
async def test_retrieve_hah_like_two_passes():
    doc = MagicMock()
    pass1 = [_mk_result("first pass context about policy", 0.8, 0)]
    pass2 = [_mk_result("second pass refinement", 0.7, 0)]
    doc.search = AsyncMock(side_effect=[pass1, pass2])

    out = await retrieve_hah_like(doc, "What is the policy?", top_k=2)
    assert out.pipeline == "hah_backend"
    assert doc.search.await_count == 2
    assert len(out.chunks) >= 1


@pytest.mark.asyncio
async def test_retrieve_chah_like_parallel():
    doc = MagicMock()
    r1 = [_mk_result("alpha chunk content long enough for merge", 0.9, 0)]
    # parallel: one call per variant — mock returns same for simplicity
    doc.search = AsyncMock(return_value=r1)

    out = await retrieve_chah_like(doc, "What are the requirements for deployment?", top_k=3)
    assert out.pipeline == "chah_backend"
    assert doc.search.called
    assert len(out.chunks) >= 1


@pytest.mark.asyncio
async def test_chah_exact_table_facts_receive_payload_scope():
    class ScopedTableFactService:
        def __init__(self):
            self.fact_calls: list[dict] = []

        async def list_table_facts(self, **kwargs):
            self.fact_calls.append(dict(kwargs))
            return []

        async def search(self, query: str, top_k: int = 10, filters=None, use_hybrid: bool = True):  # noqa: ARG002
            return [_mk_result("scoped vector result long enough for merge", 0.7, 0)]

    doc = ScopedTableFactService()
    filters = {"document_id": ["doc-1"], "project_code": "ACJ100"}

    await retrieve_chah_like(
        doc,
        "Quel est le diamètre B dans Def strips ?",
        top_k=3,
        filters=filters,
    )

    assert doc.fact_calls
    assert all(call.get("payload_filters") == filters for call in doc.fact_calls)


@pytest.mark.asyncio
async def test_chah_exact_table_facts_share_deadline_budget():
    class SlowFactAndSearchService:
        def __init__(self):
            self.fact_calls = 0
            self.search_calls: list[str] = []

        async def list_table_facts(self, **kwargs):  # noqa: ARG002
            self.fact_calls += 1
            await asyncio.sleep(0.2)
            return [
                {
                    "chunk_id": "late-fact",
                    "semantic_type": "spreadsheet_cell_fact",
                    "sheet_name": "Def strips",
                    "row_label": "B",
                    "content": 'Spreadsheet cell fact: sheet="Def strips" label="B" value="85"',
                }
            ]

        async def search(self, query: str, top_k: int = 10, filters=None, use_hybrid: bool = True):  # noqa: ARG002
            self.search_calls.append(query)
            await asyncio.sleep(0.2)
            return [_mk_result("slow vector result should miss deadline", 0.6, 0)]

    doc = SlowFactAndSearchService()
    started = time.perf_counter()

    out = await retrieve_chah_like(
        doc,
        "Quel est le diamètre B dans Def strips ?",
        top_k=3,
        use_hybrid=False,
        deadline_seconds=0.01,
        max_variants=3,
    )

    assert out.chunks == []
    assert doc.fact_calls == 1
    assert out.diagnostics["exact_table_attempted"] is True
    assert out.diagnostics["exact_table_hits"] == 0
    assert out.diagnostics["exact_table_elapsed_ms"] >= 0
    assert time.perf_counter() - started < 0.12


@pytest.mark.asyncio
async def test_search_documents_honors_sub_200ms_deadline():
    doc = SlowSearchService(delay=0.2)
    started = time.perf_counter()

    rows = await _search_documents(
        doc,
        "slow query",
        top_k=1,
        use_hybrid=False,
        deadline_seconds=0.01,
    )

    assert rows == []
    assert doc.calls == ["slow query"]
    assert time.perf_counter() - started < 0.12


@pytest.mark.asyncio
async def test_chah_uses_shared_variant_deadline():
    doc = SlowSearchService(delay=0.2)
    started = time.perf_counter()

    out = await retrieve_chah_like(
        doc,
        "What are the requirements for deployment?",
        top_k=3,
        use_hybrid=False,
        deadline_seconds=0.01,
        max_variants=3,
    )

    assert out.chunks == []
    assert len(doc.calls) <= 3
    assert time.perf_counter() - started < 0.12


@pytest.mark.asyncio
async def test_sparse_dense_fanout_cleans_up_pending_tasks(monkeypatch):
    doc = CancellableSearchService()
    sparse = CancellableSparseBackend()
    monkeypatch.setattr(pipeline_retrieval, "get_sparse_backend", lambda: sparse)

    started = time.perf_counter()
    rows = await _search_documents(
        doc,
        "slow query",
        top_k=2,
        use_hybrid=True,
        allow_legacy_hybrid=False,
        deadline_seconds=0.01,
    )

    assert rows == []
    assert doc.cancelled == 1
    assert sparse.cancelled == 1
    assert time.perf_counter() - started < 0.12


@pytest.mark.asyncio
async def test_retrieve_chah_like_uses_policy_variants_and_rerank():
    policy = RetrievalPolicy(
        protected_terms=("AKK200",),
        aliases=(("capteurs", ("sensor", "proximity switch", "XS1")),),
    )
    doc = MagicMock()

    async def _search(query: str, top_k: int = 10, use_hybrid: bool = True):  # noqa: ARG001
        if "sensor" in query or "AKK200" in query:
            return [
                {
                    "content": "AKK200 proximity switch XS1 sensor wiring procedure.",
                    "combined_score": 0.2,
                    "score": 0.2,
                    "metadata": {"project_code": "AKK200"},
                    "id": "akk200-sensor",
                }
            ]
        return [
            {
                "content": "Generic unrelated manual page with enough text.",
                "combined_score": 0.9,
                "score": 0.9,
                "metadata": {},
                "id": "noise",
            }
        ]

    doc.search = AsyncMock(side_effect=_search)

    out = await retrieve_chah_like(doc, "Quels capteurs dans AKK200 ?", top_k=3, retrieval_policy=policy)
    queries = [call.args[0] for call in doc.search.await_args_list]

    assert any("proximity switch" in query for query in queries)
    assert "AKK200 proximity switch" in out.chunks[0]
    assert out.metadatas[0]["retrieval_policy_score"] > 0


@pytest.mark.asyncio
async def test_retrieve_chah_like_reranks_protocol_candidate_pool():
    doc = MagicMock()
    protocol = _mk_result(
        "Spreadsheet sheet: Protocole essais Row 1: A1=Customer | B1=GEOTEX | C1=DATE | "
        "D1=2025-05-21 00:00:00 Row 4: A4=trials N° | I4=2A "
        "Row 12: A12=Poids | I12=42.5",
        0.2,
        9,
    )
    noisy_results = [
        _mk_result(f"generic spreadsheet result {i} with enough text", 0.9 - i / 100, i)
        for i in range(8)
    ] + [protocol]
    doc.search = AsyncMock(return_value=noisy_results)

    out = await retrieve_chah_like(
        doc,
        "Sur le test 2A du 21/05/2025 pour GEOTEX, quelle était la valeur du poids ?",
        top_k=3,
    )

    assert out.chunks[0].startswith("Spreadsheet sheet: Protocole essais")


@pytest.mark.asyncio
async def test_retrieve_for_mode_hah_disabled_falls_back():
    doc = MagicMock()
    doc.search = AsyncMock(return_value=[_mk_result("x", 0.5, 0)])

    out = await retrieve_for_mode(
        doc,
        "q",
        "hah",
        top_k=3,
        use_hybrid=True,
        hah_chah_enabled=False,
    )
    assert out.pipeline == "hybrid"
    doc.search.assert_awaited_once()


@pytest.mark.asyncio
async def test_retrieve_for_mode_naive():
    doc = MagicMock()
    doc.search = AsyncMock(return_value=[_mk_result("n", 0.3, 0)])

    out = await retrieve_for_mode(
        doc,
        "q",
        "naive",
        top_k=2,
        use_hybrid=False,
        hah_chah_enabled=True,
    )
    assert out.pipeline == "naive"
    doc.search.assert_awaited_once_with("q", top_k=2, use_hybrid=False)


@pytest.mark.asyncio
async def test_dense_guardrail_hybrid_marks_disabled_sparse(monkeypatch):
    monkeypatch.setattr(pipeline_retrieval, "get_sparse_backend", lambda: DisabledSparseBackend())
    doc = MagicMock()
    doc.collection_name = "dense-kb"
    doc.search = AsyncMock(return_value=[_mk_result("dense vector evidence long enough", 0.7, 0)])

    out = await retrieve_for_mode(
        doc,
        "q",
        "hybrid",
        top_k=2,
        use_hybrid=True,
        allow_legacy_hybrid=False,
    )

    assert out.pipeline == "hybrid"
    assert out.diagnostics["sparse_backend"] == "disabled"
    assert out.diagnostics["sparse_status"] == "disabled"
    assert out.diagnostics["sparse_fallback_reason"] == "sparse_disabled"
    assert out.diagnostics["dense_elapsed_ms"] >= 0
    assert out.diagnostics["retrieval_elapsed_ms"] >= 0
    assert "retrieval_deadline_seconds" not in out.metadatas[0]
    assert out.metadatas[0]["sparse_fallback_reason"] == "sparse_disabled"
    assert "sparse=disabled:disabled" in out.detail
    doc.search.assert_awaited_once()
    assert doc.search.await_args.kwargs["use_hybrid"] is False


@pytest.mark.asyncio
async def test_dense_guardrail_hybrid_marks_unconfigured_opensearch_sparse(monkeypatch):
    sparse = OpenSearchUnconfiguredBackend()
    monkeypatch.setattr(pipeline_retrieval, "get_sparse_backend", lambda: sparse)
    doc = MagicMock()
    doc.collection_name = "dense-kb"
    doc.search = AsyncMock(return_value=[_mk_result("dense vector evidence long enough", 0.7, 0)])

    out = await retrieve_for_mode(
        doc,
        "q",
        "hybrid",
        top_k=2,
        use_hybrid=True,
        allow_legacy_hybrid=False,
    )

    assert out.diagnostics["sparse_backend"] == "opensearch"
    assert out.diagnostics["sparse_status"] == "unavailable"
    assert out.diagnostics["sparse_fallback_reason"] == "sparse_unavailable"
    assert out.metadatas[0]["sparse_fallback_reason"] == "sparse_unavailable"
    assert sparse.calls == 0


@pytest.mark.asyncio
async def test_dense_guardrail_qdrant_sparse_uses_server_prefetch_fusion(monkeypatch):
    sparse = QdrantSparseBackendFake()
    doc = QdrantServerHybridDocService()
    monkeypatch.setattr(pipeline_retrieval, "get_sparse_backend", lambda: sparse)

    out = await retrieve_for_mode(
        doc,
        "KD724 pump",
        "hybrid",
        top_k=2,
        use_hybrid=True,
        allow_legacy_hybrid=False,
        retrieval_profile="chat",
    )

    assert out.pipeline == "hybrid"
    assert out.chunks == ["qdrant server fused evidence long enough"]
    assert out.diagnostics["sparse_backend"] == "qdrant_sparse"
    assert out.diagnostics["sparse_status"] == "ok"
    assert out.diagnostics["sparse_fusion"] == "server_rrf"
    assert out.metadatas[0]["sparse_fusion"] == "server_rrf"
    assert doc.vector_db.calls[0][4] == {
        "retrieval_profile": "chat",
        "group_by": "document_id",
        "group_size": 1,
    }
    doc.search.assert_not_awaited()
    assert sparse.calls == 0


@pytest.mark.asyncio
async def test_fast_chat_skips_unbounded_qdrant_server_hybrid(monkeypatch):
    sparse = FastChatSparseBackendFake()
    doc = SlowFastChatDocService()
    monkeypatch.setattr(pipeline_retrieval, "get_sparse_backend", lambda: sparse)
    monkeypatch.setattr(pipeline_retrieval, "FAST_CHAT_SPARSE_WAIT_SECONDS", 0.05)

    started = time.perf_counter()
    out = await retrieve_for_mode(
        doc,
        "KD724 pump",
        "hybrid",
        top_k=2,
        use_hybrid=True,
        allow_legacy_hybrid=False,
        retrieval_profile="chat",
        latency_profile="fast",
        deadline_seconds=8,
    )
    elapsed = time.perf_counter() - started

    assert elapsed < 0.5
    assert out.pipeline == "hybrid"
    assert out.chunks == ["fast sparse direct evidence long enough"]
    assert out.diagnostics["sparse_backend"] == "qdrant_sparse"
    assert out.diagnostics["sparse_status"] == "ok"
    assert sparse.calls == 1
    assert doc.vector_db.calls == []
    assert doc.cancelled == 1


@pytest.mark.asyncio
async def test_dense_guardrail_hybrid_marks_sparse_ok(monkeypatch):
    monkeypatch.setattr(pipeline_retrieval, "get_sparse_backend", lambda: SparseOkBackend())
    doc = MagicMock()
    doc.collection_name = "dense-kb"
    doc.search = AsyncMock(return_value=[_mk_result("dense vector evidence long enough", 0.7, 0)])

    out = await retrieve_for_mode(
        doc,
        "q",
        "hybrid",
        top_k=2,
        use_hybrid=True,
        allow_legacy_hybrid=False,
        deadline_seconds=3,
    )

    assert out.pipeline == "hybrid"
    assert out.diagnostics["sparse_backend"] == "opensearch"
    assert out.diagnostics["sparse_status"] == "ok"
    assert out.diagnostics["sparse_results"] == 1
    assert out.diagnostics["dense_elapsed_ms"] >= 0
    assert out.diagnostics["sparse_elapsed_ms"] >= 0
    assert out.diagnostics["retrieval_elapsed_ms"] >= 0
    assert 2.9 <= out.diagnostics["retrieval_deadline_seconds"] <= 3
    assert "sparse=ok:opensearch" in out.detail
