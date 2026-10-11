"""Offline loader/parse test for the synthetic showcase golden batch.

Mirrors the loader half of ``test_retrieval_golden_batch.py`` (no live
retrieval): it loads ``showcase_notices.json`` and asserts the cases parse,
exercise the UNIVERSAL answer profiles, and carry NO inventory/project
expectations. The default batch stays Andritz — this batch is loaded by path.
"""
from __future__ import annotations

from pathlib import Path

from app.services.rag.retrieval_golden import (
    DEFAULT_GOLDEN_BATCH,
    load_retrieval_golden_cases,
)

_NEUTRAL_PROFILES = {"precise_fact", "summary", "comparison", "insufficient_context"}


def _batch_path() -> Path:
    return (
        Path(__file__).resolve().parents[2]
        / "resources"
        / "retrieval_golden"
        / "showcase_notices.json"
    )


def _cases():
    return load_retrieval_golden_cases(_batch_path())


def test_showcase_notices_batch_parses_and_is_structurally_valid():
    cases = _cases()

    assert len(cases) >= 12
    assert all(case.query for case in cases)
    assert all(case.expected_sources for case in cases)
    assert all(case.expected_evidence_terms for case in cases)
    assert all(case.collection == "agentium-showcase-notices" for case in cases)
    assert all(case.language in {"fr", "en", "de"} for case in cases)
    # Multilingual axis is genuinely exercised.
    assert {case.language for case in cases} == {"fr", "en", "de"}


def test_showcase_notices_batch_uses_universal_answer_profiles():
    cases = _cases()

    profiles = {case.answer_profile for case in cases if case.answer_profile}
    # The neutral baseline profiles the task requires are all represented.
    assert {"precise_fact", "summary", "comparison"}.issubset(profiles)
    # Only neutral profiles appear; no industrial profile leaks in.
    assert profiles.issubset(_NEUTRAL_PROFILES)


def test_showcase_notices_batch_has_no_inventory_or_project_expectations():
    cases = _cases()

    for case in cases:
        # No additive project-inventory facet expectation anywhere.
        assert case.expected_inventory is None, case.id
        # The transversal_inventory facet is never armed (that is the industrial
        # opt-in, not the universal baseline).
        assert case.answer_profile != "transversal_inventory", case.id
        # No catalogue_inventory route guard (an industrial-corpus concept).
        assert case.forbidden_route is None, case.id
        # No project-code (or any) metadata filter leaks the project concept.
        assert case.retrieval_filters is None, case.id
        # The "project" word never appears in the showcase expectations.
        haystack = " ".join(
            [*case.expected_sources, *case.expected_evidence_terms]
        ).lower()
        assert "project" not in haystack, case.id


def test_showcase_notices_batch_covers_comparison_and_diversity():
    cases = _cases()

    # At least one genuine multi-document comparison case.
    assert any(
        case.min_expected_sources >= 2 and len(case.expected_sources) >= 2
        for case in cases
    )
    # At least one diversity case gated on distinct CONTENT (not the vacuous
    # document-prefix gate).
    assert any(case.expected_distinct_content >= 2 for case in cases)
    assert all(case.expected_distinct_documents == 0 for case in cases)


def test_showcase_batch_is_not_the_default_batch():
    # DEFAULT_GOLDEN_BATCH must stay Andritz; the showcase batch is opt-in.
    assert DEFAULT_GOLDEN_BATCH.name == "andritz_spl_dense.json"
    assert _batch_path().name == "showcase_notices.json"
    assert _batch_path() != DEFAULT_GOLDEN_BATCH
