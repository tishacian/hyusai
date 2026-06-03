from __future__ import annotations

from pathlib import Path

from app.services.rag.retrieval_golden import (
    evaluate_retrieval_golden_case,
    load_retrieval_golden_cases,
)
from app.services.rag.source_facets import active_source_family_facets, score_source_family_match


def test_andritz_spl_golden_batch_is_retrieval_contract():
    cases = load_retrieval_golden_cases()

    assert len(cases) == 12
    assert all(case.query for case in cases)
    assert all(case.expected_sources for case in cases)
    assert all(case.expected_evidence_terms for case in cases)
    assert all(case.forbidden_route == "catalogue_inventory" for case in cases)


def test_golden_case_evaluates_sources_and_evidence_not_answer_text():
    case = next(case for case in load_retrieval_golden_cases() if case.id == "spl_004_aco150_spl")
    context = {
        "chunks": ["Spare Parts List for ACO150 includes mechanical spare part references."],
        "metadatas": [{"document_filename": "Manual__spare part list ACO150.pdf"}],
        "retrieval_trace": {
            "selected_sources": [
                {
                    "document_filename": "Manual__spare part list ACO150.pdf",
                    "snippet": "Spare Parts List for ACO150",
                }
            ]
        },
        "metrics": {"dense_policy": "fast_scoped_dense"},
    }

    result = evaluate_retrieval_golden_case(case, context)

    assert result["passed"] is True
    assert result["matched_sources"] == ["spare part list ACO150.pdf"]


def test_golden_case_rejects_inventory_route_and_missing_evidence():
    case = next(case for case in load_retrieval_golden_cases() if case.id == "spl_011_akk200_filtering_cartridge_oring")
    context = {
        "chunks": ["Inventory summary only"],
        "metadatas": [{"document_filename": "Spare Parts List AKK200_Ind A.pdf"}],
        "metrics": {"dense_policy": "catalogue_inventory"},
    }

    result = evaluate_retrieval_golden_case(case, context)

    assert result["passed"] is False
    assert result["forbidden_route_hit"] is True
    assert result["missing_evidence_terms"]


def test_source_facets_are_family_rules_not_answer_mappings():
    facets = active_source_family_facets("Peux-tu retrouver la Spare Parts List du projet ACO150 ?")
    assert {facet.key for facet in facets} >= {"spare_parts_list"}

    score, matched = score_source_family_match(
        query="Peux-tu retrouver la Spare Parts List du projet ACO150 ?",
        row_text="Archived manual folder / spare parts list / maintenance references",
        metadata={},
    )
    assert score > 0
    assert matched == ["spare_parts_list"]

    app_root = Path(__file__).resolve().parents[2]
    planner_text = (app_root / "services" / "rag" / "corpus_planner.py").read_text(encoding="utf-8")
    facet_text = (app_root / "services" / "rag" / "source_facets.py").read_text(encoding="utf-8")
    forbidden_answer_mappings = [
        "spare part list ACO150.pdf",
        "Spare Parts List_BBA120.pdf",
        "GEOTEX-SPL-Y25.05.22-PIL.xlsx",
        "Etachrom B.PDF",
    ]
    for needle in forbidden_answer_mappings:
        assert needle not in planner_text
        assert needle not in facet_text
