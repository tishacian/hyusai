from __future__ import annotations

from pathlib import Path

from app.services.rag.retrieval_golden import (
    RetrievalGoldenCase,
    _content_key,
    _distinct_content_count,
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


def test_diversity_batch_gates_on_distinct_content():
    cases = load_retrieval_golden_cases(_batch_path("andritz_spl_diversity.json"))
    # Diversity is gated on CONTENT, not on the project-prefixed filename: the
    # vacuous document-level gate is disabled (0) and every case sets a content
    # expectation, several demanding 3+ genuinely distinct manuals.
    assert all(case.expected_distinct_documents == 0 for case in cases)
    assert all(case.expected_distinct_content >= 1 for case in cases)
    assert any(case.expected_distinct_content >= 3 for case in cases)


def test_hard_intents_batch_mixes_languages_and_hard_shapes():
    cases = load_retrieval_golden_cases(_batch_path("andritz_spl_hard_intents.json"))
    assert {case.language for case in cases} == {"fr", "en", "de"}
    # Comparative cases require evidence from 2+ documents.
    assert any(case.min_expected_sources >= 2 and len(case.expected_sources) >= 2 for case in cases)
    # At least one exclusion case exercises forbidden_sources.
    assert any(case.forbidden_sources for case in cases)


def _diversity_case(**overrides):
    payload = {
        "id": "synthetic_diversity",
        "query": "Where can I find the G150 speed controller operating instructions?",
        "collection": "andritz-notices-techniques-spl-pilot",
        "expected_sources": ["g150 operating instructions"],
        "expected_evidence_terms": ["G150", "operating instructions"],
        "expected_intent": "source_lookup",
        "forbidden_route": "catalogue_inventory",
    }
    payload.update(overrides)
    return RetrievalGoldenCase.from_mapping(payload)


def _diversity_context(filenames):
    return {
        "chunks": ["G150 operating instructions content"] * len(filenames),
        "metadatas": [{"document_filename": name} for name in filenames],
        "metrics": {},
    }


def test_evaluator_enforces_expected_distinct_documents():
    # The document-level gate (kept for diagnostics, disabled in the live batch)
    # still works when a case opts in. It counts the project-prefixed filename,
    # so three copies of one manual clear it — which is exactly why the live
    # batch gates on content instead.
    case = _diversity_case(expected_distinct_documents=3)

    redundant = _diversity_context(
        ["A__ACJ100__V.5.Vacuum set__CBI-GVC1C2C3__g150-operating-instructions-0312-en.pdf"] * 8
    )
    result = evaluate_retrieval_golden_case(case, redundant)
    assert result["distinct_documents"] == 1
    assert result["diversity_shortfall"] is True
    assert result["passed"] is False

    same_manual_copies = _diversity_context(
        [
            "A__ACJ100__V.5.Vacuum set__CBI-GVC1C2C3__g150-operating-instructions-0312-en.pdf",
            "A__AKI300__V.5.Vacuum set__POLLRICH - GVJ1__g150-operating-instructions-0312-en.pdf",
            "B__BFG100__V.7.High pressure set__g150-operating-instructions-0312-en.pdf",
        ]
    )
    result = evaluate_retrieval_golden_case(case, same_manual_copies)
    assert result["distinct_documents"] == 3
    assert result["diversity_shortfall"] is False
    # Vacuous: three copies of one manual are a single content document.
    assert result["distinct_content"] == 1
    assert result["passed"] is True


def test_content_key_collapses_per_project_copies_of_one_manual():
    # Three project copies of the SAME manual: distinct filenames (project
    # prefix differs) but one content identity.
    copies = [
        "A__ACJ100__V.5.Vacuum set__CBI-GVC1C2C3__g150-operating-instructions-0312-en.pdf",
        "A__AKI300__V.5.Vacuum set__POLLRICH - GVJ1__g150-operating-instructions-0312-en.pdf",
        "B__BFG100__V.7.High pressure set__g150-operating-instructions-0312-en.pdf",
    ]
    keys = {_content_key({"document_filename": fn}) for fn in copies}
    assert len(keys) == 1, keys

    # A genuinely different manual yields a different content key.
    other = _content_key(
        {"document_filename": "H__HYD100__HYD100__fichiers__MasterDrive_motioncontrole de.pdf"}
    )
    assert other not in keys

    # Inner archive paths (slash separators) reduce to the same basename.
    assert _content_key({"inner_document_path": "ACJ100/.../g150-operating-instructions-0312-en.pdf"}) in keys

    # Graceful fallbacks: legacy_document_name, then content_sha256, then label.
    assert _content_key({"legacy_document_name": "ACJ100__lh2_0113_eng.pdf"}) == _content_key(
        {"document_filename": "B__BFG100__lh2_0113_eng.pdf"}
    )
    assert _content_key({"content_sha256": "abc123"}) == "sha:abc123"
    assert _content_key({"document_id": "doc-42"}) == "doc 42"


def test_distinct_content_count_vs_distinct_document_count():
    # All chunks are copies of one manual under three projects: round-robin by
    # document_id sees three "documents", but the content count is one.
    context = {
        "metadatas": [
            {"document_filename": "A__ACJ100__g150-operating-instructions-0312-en.pdf"},
            {"document_filename": "A__AKI300__g150-operating-instructions-0312-en.pdf"},
            {"document_filename": "B__BFG100__g150-operating-instructions-0312-en.pdf"},
        ]
    }
    assert _distinct_content_count(context, top_n=8) == 1

    # Two genuinely different manuals -> two distinct content documents.
    context = {
        "metadatas": [
            {"document_filename": "A__ACJ100__g150-operating-instructions-0312-en.pdf"},
            {"document_filename": "A__ACJ100__lh2_0113_eng.pdf"},
        ]
    }
    assert _distinct_content_count(context, top_n=8) == 2


def test_evaluator_enforces_expected_distinct_content():
    case = _diversity_case(expected_distinct_content=3)

    # 8 copies of one manual under 8 projects: distinct_documents looks high
    # (the bug the old metric fell for), distinct_content collapses to 1.
    redundant = _diversity_context(
        [f"A__PROJ{i}__g150-operating-instructions-0312-en.pdf" for i in range(8)]
    )
    result = evaluate_retrieval_golden_case(case, redundant)
    assert result["distinct_documents"] == 8
    assert result["distinct_content"] == 1
    assert result["content_diversity_shortfall"] is True
    assert result["passed"] is False

    # Three genuinely distinct manuals: content diversity satisfied.
    diverse = _diversity_context(
        [
            "A__PROJ0__g150-operating-instructions-0312-en.pdf",
            "A__PROJ1__lh2_0113_eng.pdf",
            "B__PROJ2__kd724.pdf",
        ]
    )
    result = evaluate_retrieval_golden_case(case, diverse)
    assert result["distinct_content"] == 3
    assert result["content_diversity_shortfall"] is False
    assert result["passed"] is True


# --- positive project-inventory expectation (transversal_inventory facet) -----


def _inventory_case(expected_inventory, **overrides):
    payload = {
        "id": "synthetic_inventory",
        "query": "Quels projets utilisent une pompe URACA ?",
        "collection": "andritz-notices-techniques-spl-pilot",
        "expected_sources": ["uraca"],
        "expected_evidence_terms": ["uraca"],
        "expected_intent": "transversal_inventory",
        "answer_profile": "transversal_inventory",
        "expected_inventory": expected_inventory,
    }
    payload.update(overrides)
    return RetrievalGoldenCase.from_mapping(payload)


def _inventory_context(inventory):
    # Satisfies the source + evidence + route checks so ONLY the inventory branch
    # decides pass/fail.
    context = {
        "chunks": ["URACA pump documentation across multiple projects"],
        "metadatas": [{"document_filename": "uraca pump overview.pdf"}],
        "retrieval_trace": {"selected_sources": [{"document_filename": "uraca pump overview.pdf"}]},
        "metrics": {"dense_policy": "fast_scoped_dense"},
    }
    if inventory is not None:
        context["project_inventory"] = inventory
    return context


def _uraca_inventory(total=133, codes=("AVA100", "NAN330", "NBD100", "BHX100"), terms=("uraca",)):
    return {
        "terms": list(terms),
        "total_projects": total,
        "projects": [{"project_code": code, "chunk_count": 1} for code in codes],
        "collections_faceted": 1,
    }


def test_evaluator_passes_when_inventory_meets_expectation():
    # Project codes are matched case-insensitively (lowercase expectation clears
    # the upper-cased payload codes), terms equal, total above the floor, no
    # forbidden member present.
    case = _inventory_case(
        {
            "min_total_projects": 100,
            "must_include_projects": ["ava100", "NAN330"],
            "must_exclude_projects": ["KUT100", "MOG400"],
            "expected_terms": ["uraca"],
        }
    )
    result = evaluate_retrieval_golden_case(case, _inventory_context(_uraca_inventory()))

    assert result["passed"] is True
    assert result["inventory_shortfall"] is False
    report = result["inventory_report"]
    assert report["present"] is True
    assert report["total_projects"] == 133
    assert report["missing_projects"] == []
    assert report["forbidden_projects"] == []
    assert report["terms_mismatch"] is False


def test_evaluator_fails_when_inventory_missing():
    # Opting into expected_inventory asserts the facet is PRESENT: a context with
    # no project_inventory (facet did not fire) is a shortfall even though every
    # other signal is satisfied.
    case = _inventory_case({"min_total_projects": 100, "must_include_projects": ["AVA100"]})
    result = evaluate_retrieval_golden_case(case, _inventory_context(None))

    assert result["passed"] is False
    assert result["inventory_shortfall"] is True
    assert result["inventory_report"]["present"] is False


def test_evaluator_fails_on_total_below_floor():
    case = _inventory_case({"min_total_projects": 100})
    result = evaluate_retrieval_golden_case(case, _inventory_context(_uraca_inventory(total=40)))

    assert result["passed"] is False
    assert result["inventory_report"]["total_shortfall"] is True


def test_evaluator_fails_on_missing_required_project():
    case = _inventory_case({"must_include_projects": ["ZZZ999"]})
    result = evaluate_retrieval_golden_case(case, _inventory_context(_uraca_inventory()))

    assert result["passed"] is False
    assert result["inventory_report"]["missing_projects"] == ["ZZZ999"]


def test_evaluator_fails_on_forbidden_project_present():
    case = _inventory_case({"must_exclude_projects": ["KUT100"]})
    inventory = _uraca_inventory(codes=("AVA100", "KUT100", "NBD100"))
    result = evaluate_retrieval_golden_case(case, _inventory_context(inventory))

    assert result["passed"] is False
    assert result["inventory_report"]["forbidden_projects"] == ["KUT100"]


def test_evaluator_fails_on_terms_mismatch():
    case = _inventory_case({"expected_terms": ["uraca", "kd724"]})
    result = evaluate_retrieval_golden_case(case, _inventory_context(_uraca_inventory()))

    assert result["passed"] is False
    assert result["inventory_report"]["terms_mismatch"] is True


def test_inventory_expectation_is_backward_compatible_noop():
    # A case WITHOUT expected_inventory never trips the branch, even when a
    # project_inventory payload happens to be present (and when it is absent).
    plain = _diversity_case()
    assert plain.expected_inventory is None

    with_facet = evaluate_retrieval_golden_case(
        plain, dict(_diversity_context(["g150 operating instructions.pdf"]), project_inventory=_uraca_inventory())
    )
    assert with_facet["inventory_shortfall"] is False
    assert with_facet["inventory_report"] is None

    without_facet = evaluate_retrieval_golden_case(
        plain, _diversity_context(["g150 operating instructions.pdf"])
    )
    assert without_facet["inventory_shortfall"] is False
    assert without_facet["inventory_report"] is None


def test_to_request_forwards_answer_profile_only_when_set():
    inventory_case = _inventory_case({"min_total_projects": 1})
    assert inventory_case.to_request()["answer_profile"] == "transversal_inventory"
    # A plain case does not inject the key (no serving-path perturbation).
    assert "answer_profile" not in _diversity_case().to_request()


def test_inventory_batches_carry_positive_contract_and_keep_forbidden_route():
    # div_009 and hi_002 genuinely enumerate projects: they now carry the
    # positive expected_inventory AND keep forbidden_route (the additive facet
    # does not change dense_policy, so catalogue_inventory stays a valid guard).
    diversity = {c.id: c for c in load_retrieval_golden_cases(_batch_path("andritz_spl_diversity.json"))}
    hard = {c.id: c for c in load_retrieval_golden_cases(_batch_path("andritz_spl_hard_intents.json"))}

    div_009 = diversity["div_009_uraca_kd724_chapters_multiproject"]
    assert div_009.answer_profile == "transversal_inventory"
    assert div_009.forbidden_route == "catalogue_inventory"
    assert div_009.expected_inventory["min_total_projects"] == 3
    assert div_009.expected_inventory["must_include_projects"] == ("TEK100", "COL100", "PHP02")
    assert div_009.expected_inventory["must_exclude_projects"] == ("KUT100", "MOG400")

    hi_002 = hard["hi_002_ambiguous_kd724_partial_ref"]
    assert hi_002.answer_profile == "transversal_inventory"
    assert hi_002.forbidden_route == "catalogue_inventory"
    assert hi_002.expected_inventory["min_total_projects"] == 100
    assert set(hi_002.expected_inventory["must_include_projects"]) == {"BHX100", "AKI500", "TEK100"}
    # KUT100 legitimately appears for bare KD724 -> not excluded here.
    assert "KUT100" not in hi_002.expected_inventory["must_exclude_projects"]


def test_source_facets_are_family_rules_not_answer_mappings(andritz_tenant):
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
