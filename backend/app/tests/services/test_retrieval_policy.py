from __future__ import annotations

from types import SimpleNamespace

from app.services.rag.retrieval_policy import (
    clarification_from_policy,
    filter_aligned_to_required_terms,
    query_variants_from_policy,
    rerank_results_with_policy,
    retrieval_policy_from_guides,
)


POLICY_GUIDE = SimpleNamespace(
    markdown="""# Guide

```agentium-retrieval-policy
{
  "query_planning": {
    "protected_terms": ["BBA120", "AKK200"],
    "require_project_code_match": true,
    "aliases": {
      "capteurs": ["sensor", "proximity switch", "XS1", "ZCT"]
    },
    "facets": [
      {
        "key": "sensor",
        "label": "Capteurs",
        "terms": ["capteurs", "sensor", "proximity switch"],
        "clarify_when_broad": true,
        "clarification_prompt": "Voulez-vous les capteurs de proximite, pression, securite ou automatisme ?"
      }
    ]
  },
  "source_quality": {
    "demote_navigation": true,
    "prefer_source_families": [
      {
        "when_terms": ["piece", "spare"],
        "source_families": ["spare_parts_list"]
      }
    ]
  },
  "answer_policy": {
    "instructions": [
      "Traiter les codes de type XXX123 comme des references projet stables."
    ]
  }
}
```
"""
)


def test_retrieval_policy_parses_guide_blocks():
    policy = retrieval_policy_from_guides([POLICY_GUIDE])

    assert policy.enabled is True
    assert policy.protected_terms == ("BBA120", "AKK200")
    assert policy.require_project_code_match is True
    assert policy.aliases[0][0] == "capteurs"
    assert policy.answer_instructions == (
        "Traiter les codes de type XXX123 comme des references projet stables.",
    )


def test_policy_adds_query_variants_only_when_alias_matches():
    policy = retrieval_policy_from_guides([POLICY_GUIDE])

    variants = query_variants_from_policy("Quels capteurs sont dans AKK200 ?", policy)

    assert any("sensor" in variant for variant in variants)
    assert any("AKK200" == variant or variant.endswith(" AKK200") for variant in variants)
    assert query_variants_from_policy("Comment demarrer la pompe ?", policy) == []


def test_policy_adds_dynamic_project_reference_variants():
    policy = retrieval_policy_from_guides([POLICY_GUIDE])

    variants = query_variants_from_policy("Liste de garniture du projet COL100", policy)

    assert "COL100" in variants
    assert "COL 100" in variants


def test_policy_rerank_boosts_exact_terms_and_demotes_navigation():
    policy = retrieval_policy_from_guides([POLICY_GUIDE])
    rows = [
        {
            "content": "Table of contents menu previous next index",
            "score": 0.99,
            "metadata": {"document_filename": "index.html"},
        },
        {
            "content": "AKK200 proximity switch XS1 sensor wiring and diagnostic procedure.",
            "score": 0.2,
            "metadata": {"project_code": "AKK200", "source_family": "operating_manual"},
        },
    ]

    ranked = rerank_results_with_policy(rows, "capteurs AKK200", policy)

    assert ranked[0]["metadata"]["project_code"] == "AKK200"
    assert ranked[0]["metadata"]["retrieval_policy_score"] > 0
    assert ranked[-1]["metadata"]["retrieval_policy_score"] < 0


def test_policy_can_request_clarification_for_broad_configured_facet():
    policy = retrieval_policy_from_guides([POLICY_GUIDE])

    clarification = clarification_from_policy("capteurs", policy)

    assert clarification is not None
    assert clarification["required"] is True
    assert clarification["facet"] == "sensor"


def test_policy_filters_other_projects_when_exact_project_reference_missing():
    policy = retrieval_policy_from_guides([POLICY_GUIDE])

    chunks, scores, metadatas, constraints = filter_aligned_to_required_terms(
        ["Spare Parts List AKK200", "Spare Parts List BBA120"],
        [0.9, 0.8],
        [{"project_code": "AKK200"}, {"project_code": "BBA120"}],
        query="Liste de garniture du projet COL100",
        policy=policy,
    )

    assert chunks == []
    assert scores == []
    assert metadatas == []
    assert constraints["required_terms"] == ["COL100"]
    assert constraints["missing_terms"] == ["COL100"]
    assert constraints["filtered_chunks_removed"] == 2
