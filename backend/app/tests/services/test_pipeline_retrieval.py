"""Unit tests for HAH/C-HAH-like pipeline retrieval (mocked DocumentService)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.rag.pipeline_retrieval import (
    _merge_rrf,
    _prioritise_spreadsheet_label_matches,
    _query_variants,
    retrieve_chah_like,
    retrieve_for_mode,
    retrieve_hah_like,
)


def _mk_result(content: str, score: float, rank: int = 0) -> dict:
    return {
        "content": content,
        "combined_score": score,
        "score": score,
        "metadata": {},
        "id": f"id-{rank}",
    }


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
