from __future__ import annotations

from pathlib import Path

from app.services.rag.retrieval_golden import (
    evaluate_retrieval_golden_case,
    load_retrieval_golden_cases,
)
from app.services.rag.source_facets import active_source_family_facets, score_source_family_match


def test_andritz_spl_golden_batch_is_retrieval_contract():
    cases = load_retrieval_golden_cases()

    assert len(cases) >= 30
    assert all(case.query for case in cases)
    assert all(case.expected_sources for case in cases)
    assert all(case.expected_evidence_terms for case in cases)
    assert all(case.forbidden_route == "catalogue_inventory" for case in cases)
    assert {
        "spl_013_akk200_filtration_vacuum_expert",
        "spl_016_bba120_hp_pump_kd724_vendor",
        "spl_021_injector_autoclamped_cartridge_clean",
    }.issubset({case.id for case in cases})


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


_EXTENDED_BATCHES = {
    "andritz_spl_multilingual.json": {"min_cases": 6},
    "andritz_spl_multiturn.json": {"min_cases": 3},
    "andritz_spl_scope_filters.json": {"min_cases": 3},
    "andritz_spl_sparse_only.json": {"min_cases": 3},
    "andritz_spl_fallbacks.json": {"min_cases": 3},
    "andritz_spl_diversity.json": {"min_cases": 8},
    "andritz_spl_hard_intents.json": {"min_cases": 8},
}


def _batch_path(name: str) -> Path:
    return Path(__file__).resolve().parents[2] / "resources" / "retrieval_golden" / name


def test_extended_golden_batches_are_structurally_valid():
    for name, expectations in _EXTENDED_BATCHES.items():
        cases = load_retrieval_golden_cases(_batch_path(name))
        assert len(cases) >= expectations["min_cases"], name
        assert all(case.query for case in cases), name
        assert all(case.expected_sources for case in cases), name
        assert all(case.language in {"fr", "en", "de"} for case in cases), name


def test_multilingual_batch_covers_same_fact_in_three_languages():
    cases = load_retrieval_golden_cases(_batch_path("andritz_spl_multilingual.json"))
    languages = {case.language for case in cases}
    assert languages == {"fr", "en", "de"}
    # The injector-cleaning fact is asked in all three languages against the
    # same source — a per-language pass-rate gap flags a multilingual bias.
    injector = [case for case in cases if "injector" in " ".join(case.expected_evidence_terms).lower()]
    assert {case.language for case in injector} == {"fr", "en", "de"}
    assert len({case.expected_sources for case in injector}) == 1


def test_multiturn_batch_carries_conversation_history_into_request():
    cases = load_retrieval_golden_cases(_batch_path("andritz_spl_multiturn.json"))
    for case in cases:
        assert case.conversation_history, case.id
        request = case.to_request()
        history = request["context"]["conversation_history"]
        assert history and history[0]["role"] == "user"


def test_scope_filter_batch_forwards_retrieval_filters():
    cases = load_retrieval_golden_cases(_batch_path("andritz_spl_scope_filters.json"))
    filtered = [case for case in cases if case.retrieval_filters]
    assert filtered
    request = filtered[0].to_request()
    assert request["retrieval_filters"] == dict(filtered[0].retrieval_filters)


def test_evaluator_enforces_forbidden_sources_and_diagnostics():
    cases = load_retrieval_golden_cases(_batch_path("andritz_spl_multiturn.json"))
    case = next(case for case in cases if case.id == "mt_002_followup_switch_project")

    # Cross-project contamination: the forbidden source appears in the labels.
    contaminated = {
        "chunks": ["Spare Parts List ACO150 content"],
        "metadatas": [
            {"document_filename": "spare part list ACO150.pdf"},
            {"document_filename": "Spare Parts List AKK200_Ind A.pdf"},
        ],
        "metrics": {},
    }
    result = evaluate_retrieval_golden_case(case, contaminated)
    assert result["forbidden_source_hits"] == ["Spare Parts List AKK200_Ind A.pdf"]
    assert result["passed"] is False

    # Diagnostics contract: expected_diagnostics must match metrics.
    sparse_cases = load_retrieval_golden_cases(_batch_path("andritz_spl_sparse_only.json"))
    sparse_case = sparse_cases[0]
    good = {
        "chunks": ["URACA KD724 pump documentation"],
        "metadatas": [{"document_filename": "URACA KD724"}],
        "metrics": {"sparse_status": "ok"},
    }
    assert evaluate_retrieval_golden_case(sparse_case, good)["passed"] is True
    degraded = dict(good, metrics={"sparse_status": "timeout"})
    result = evaluate_retrieval_golden_case(sparse_case, degraded)
    assert result["passed"] is False
    assert result["diagnostic_mismatches"]["sparse_status"]["actual"] == "timeout"


def test_diversity_batch_requires_distinct_documents():
    cases = load_retrieval_golden_cases(_batch_path("andritz_spl_diversity.json"))
    assert all(case.expected_distinct_documents >= 2 for case in cases)
    assert any(case.expected_distinct_documents >= 3 for case in cases)


def test_hard_intents_batch_mixes_languages_and_hard_shapes():
    cases = load_retrieval_golden_cases(_batch_path("andritz_spl_hard_intents.json"))
    assert {case.language for case in cases} == {"fr", "en", "de"}
    # Comparative cases require evidence from 2+ documents.
    assert any(case.min_expected_sources >= 2 and len(case.expected_sources) >= 2 for case in cases)
    # At least one exclusion case exercises forbidden_sources.
    assert any(case.forbidden_sources for case in cases)


def test_evaluator_enforces_expected_distinct_documents():
    case = next(
        case
        for case in load_retrieval_golden_cases(_batch_path("andritz_spl_diversity.json"))
        if case.id == "div_001_g150_operating_instructions_multiproject"
    )
    assert case.expected_distinct_documents == 3

    def _context(filenames):
        return {
            "chunks": ["G150 operating instructions content"] * len(filenames),
            "metadatas": [{"document_filename": name} for name in filenames],
            "metrics": {},
        }

    # All top-k chunks from one document: source matches but diversity fails.
    redundant = _context(
        ["A__ACJ100__V.5.Vacuum set__CBI-GVC1C2C3__g150-operating-instructions-0312-en.pdf"] * 8
    )
    result = evaluate_retrieval_golden_case(case, redundant)
    assert result["distinct_documents"] == 1
    assert result["diversity_shortfall"] is True
    assert result["passed"] is False

    # Chunks spread over three documents: diversity satisfied.
    diverse = _context(
        [
            "A__ACJ100__V.5.Vacuum set__CBI-GVC1C2C3__g150-operating-instructions-0312-en.pdf",
            "A__AKI300__V.5.Vacuum set__POLLRICH - GVJ1__g150-operating-instructions-0312-en.pdf",
            "B__BFG100__V.7.High pressure set__g150-operating-instructions-0312-en.pdf",
        ]
    )
    result = evaluate_retrieval_golden_case(case, diverse)
    assert result["distinct_documents"] == 3
    assert result["diversity_shortfall"] is False
    assert result["passed"] is True


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
