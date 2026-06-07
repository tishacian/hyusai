from __future__ import annotations

from types import SimpleNamespace

from app.services.rag.retrieval_policy import (
    clarification_from_policy,
    evidence_coverage_details,
    filter_aligned_to_required_terms,
    is_document_discovery_query,
    query_variants_from_policy,
    rerank_aligned_with_policy,
    rerank_results_with_policy,
    retrieval_policy_from_guides,
    score_result_with_policy,
)
from app.services.rag.source_facets import score_source_family_match

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
  "lexical_retrieval": {
    "document_types": {
      "parts_catalog": {
        "aliases": ["parts list", "component catalogue"]
      }
    },
    "metadata_fields": {
      "document_filename": 5,
      "project_code": 7
    }
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
    assert policy.lexical_config.document_types["parts_catalog"] == (
        "parts list",
        "component catalogue",
    )
    assert policy.lexical_config.metadata_field_weights["project_code"] == 7
    assert policy.answer_instructions == (
        "Traiter les codes de type XXX123 comme des references projet stables.",
    )


def test_policy_adds_query_variants_only_when_alias_matches():
    policy = retrieval_policy_from_guides([POLICY_GUIDE])

    variants = query_variants_from_policy("Quels capteurs sont dans AKK200 ?", policy)

    assert any("sensor" in variant for variant in variants)
    assert any("AKK200" == variant or variant.endswith(" AKK200") for variant in variants)
    assert query_variants_from_policy("Comment demarrer la pompe ?", policy) == []


def test_policy_evidence_matches_bilingual_cleaning_alias():
    guide = SimpleNamespace(
        markdown="""```agentium-retrieval-policy
{
  "query_planning": {
    "aliases": {
      "nettoyage": ["cleaning", "clean", "injector cartridge cleaning"],
      "nettoyer": ["cleaning", "clean", "injector cartridge cleaning"],
      "injecteur": ["injector", "injector cartridge"],
      "cartouche": ["cartridge", "injector cartridge"]
    }
  }
}
```"""
    )
    policy = retrieval_policy_from_guides([guide])

    details = evidence_coverage_details(
        content="IN 07 A - EXH injector cartridge cleaning procedure.",
        metadata={"document_filename": "IN 07 A- EXH injector cartridge cleaning.pdf"},
        query="Comment nettoyer les cartouches d'injecteurs ?",
        policy=policy,
    )

    assert "nettoyer" in details["matched"]
    assert "injecteur" in details["matched"]
    assert "cartouche" in details["matched"]
    assert "comment" not in {term.lower() for term in details["groups"]}


def test_source_family_prefers_cleaning_procedure_over_spare_list():
    query = "Quelle procedure parle du nettoyage des cartridges d'autoclamped injector ?"

    procedure_score, procedure_matches = score_source_family_match(
        query=query,
        row_text="BEX200 section IV IN 07 A EXH injector cartridge cleaning.pdf",
        metadata={"source_family": "unknown"},
        policy=None,
    )
    spare_score, spare_matches = score_source_family_match(
        query=query,
        row_text="AMM100 Hydroentanglement unit Spare Parts List AMM100.pdf",
        metadata={"source_family": "spare_parts_list"},
        policy=None,
    )

    assert "maintenance_procedure" in procedure_matches
    assert "injector_notice" in procedure_matches
    assert "spare_parts_list" in spare_matches
    assert procedure_score > spare_score


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


def test_policy_rerank_boosts_validated_provenance_without_guide():
    rows = [
        {
            "content": "Same pump maintenance evidence.",
            "score": 0.71,
            "metadata": {"document_filename": "draft-note.md", "status": "draft"},
        },
        {
            "content": "Same pump maintenance evidence from official manual.",
            "score": 0.70,
            "metadata": {"document_filename": "manual.pdf", "status": "reviewed", "source_kind": "manual"},
        },
    ]

    ranked = rerank_results_with_policy(rows, "pump maintenance", None)

    assert ranked[0]["metadata"]["document_filename"] == "manual.pdf"
    assert ranked[0]["metadata"]["retrieval_policy_score"] > 0


def test_policy_rerank_uses_generic_lexical_exact_match_without_guide():
    rows = [
        {
            "content": "Wrong project component list.",
            "score": 0.99,
            "metadata": {"document_filename": "Component list PRJ999.pdf", "project_code": "PRJ999"},
        },
        {
            "content": "Right project component list.",
            "score": 0.2,
            "metadata": {"document_filename": "Component list PRJ204.pdf", "project_code": "PRJ204"},
        },
    ]

    ranked = rerank_results_with_policy(rows, "Find component list for PRJ204", None)

    assert ranked[0]["metadata"]["project_code"] == "PRJ204"
    assert ranked[0]["metadata"]["retrieval_lexical_score"] > 0
    assert ranked[-1]["metadata"]["retrieval_exact_match_missing"] is True


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


# --- Document-discovery intent detection -----------------------------------

DISCOVERY_POLICY_GUIDE = SimpleNamespace(
    markdown="""# Andritz

```agentium-retrieval-policy
{
  "query_planning": {
    "require_project_code_match": true
  },
  "source_quality": {
    "demote_navigation": true
  }
}
```
"""
)


def test_intent_detector_positive_cases():
    positives = [
        # The two confirmed under-performing audit queries.
        "Quels documents de convoyeur sont indexés pour ARA200 ?",
        "Quel document décrit l'armoire pneumatique de ARA200 ?",
        # SPL-list style discovery queries (Q3-Q6 are fine to count as discovery).
        "Quelles sources documentent le projet AKK200 ?",
        "Liste des documents SPL pour BBA120",
        "Retrouve la liste des documents indexés",
        "Which documents are indexed for ARA200?",
        "What document describes the pneumatic cabinet?",
        "List of documents about the conveyor",
        "Find the operating manual document for ARA200",
    ]
    for query in positives:
        assert is_document_discovery_query(query) is True, query


def test_intent_detector_negative_cases():
    # Q1/Q2/Q7/Q8/Q11/Q12 style ordinary factual questions must NOT be discovery.
    negatives = [
        "Comment nettoyer les injecteurs ?",
        "Que vaut le label B sur la feuille Def strips ?",
        "Quelle est la valeur du diamètre pour LM300 ?",
        "Comment fonctionne la filtration sous vide ?",
        "Quel est le diamètre du strip pour DCI110 ?",
        "How do I clean the injectors?",
        "",
    ]
    for query in negatives:
        assert is_document_discovery_query(query) is False, query


# --- Discovery-gated ranking using realistic ARA200 payloads ----------------

# Synthetic chunks mimicking the confirmed live Qdrant payloads.
_CONVEYOR_HTML = {
    "content": "Conveyor ARA200 operating notes. table of contents previous next home menu",
    "metadata": {
        "project_code": "ARA200",
        "source_family": "operating_manual",
        "inner_document_path": "ARA200/fichiers/users manual/section 3/conveyor.html",
        "document_filename": "conveyor.html",
        "document_title": "Conveyor",
    },
}
_CONVEYOR_ANNEX = {
    "content": "Conveyor jetlace operating description and maintenance for ARA200.",
    "metadata": {
        "project_code": "ARA200",
        "source_family": "annex",
        "inner_document_path": "ARA200/fichiers/users manual/Annexes/520-convoyeur/conveyor-jetlace-gb b.pdf",
        "document_filename": "conveyor-jetlace-gb b.pdf",
        "document_title": "Conveyor Jetlace",
    },
}
_PRINTABLE_COVER = {
    "content": "ARA200 cover page. Printable version of the manual.",
    "metadata": {
        "project_code": "ARA200",
        "source_family": "html_manual",
        "document_filename": "printable version.pdf",
        "document_title": "ARA200 Part's Manual",
    },
}
_PART_MANUAL_INDEX = {
    "content": "table of contents index home previous next menu navigation. "
    "href= href= href= href= href= href= href= href= href=",
    "metadata": {
        "project_code": "ARA200",
        "source_family": "html_manual",
        "document_filename": "index.html",
        "document_title": "ARA200 Part's Manual",
    },
}


def _ranked_paths(chunks, metadatas, query):
    policy = retrieval_policy_from_guides([DISCOVERY_POLICY_GUIDE])
    ranked_chunks, _scores, ranked_metas = rerank_aligned_with_policy(
        list(chunks),
        [0.5] * len(chunks),
        list(metadatas),
        query=query,
        policy=policy,
    )
    return [m.get("document_filename") for m in ranked_metas]


def test_discovery_intent_ranks_specific_docs_above_generic_cover():
    samples = [_PART_MANUAL_INDEX, _PRINTABLE_COVER, _CONVEYOR_HTML, _CONVEYOR_ANNEX]
    chunks = [s["content"] for s in samples]
    metadatas = [dict(s["metadata"]) for s in samples]

    order = _ranked_paths(chunks, metadatas, "Quels documents de convoyeur sont indexés pour ARA200 ?")

    # The specific annex/operating_manual conveyor docs must outrank the generic
    # cover/index pages under discovery intent.
    assert order.index("conveyor.html") < order.index("printable version.pdf")
    assert order.index("conveyor-jetlace-gb b.pdf") < order.index("printable version.pdf")
    assert order.index("conveyor.html") < order.index("index.html")
    assert order.index("conveyor-jetlace-gb b.pdf") < order.index("index.html")


def test_discovery_intent_surfaces_pneumatic_annex():
    pneumatic = {
        "content": "Pneumatic cabinet description and wiring for ARA200.",
        "metadata": {
            "project_code": "ARA200",
            "source_family": "annex",
            "inner_document_path": "ARA200/fichiers/users manual/Annexes/535-commande machine/pneumatic cabinet.pdf",
            "document_filename": "pneumatic cabinet.pdf",
            "document_title": "Pneumatic Cabinet",
        },
    }
    samples = [_PART_MANUAL_INDEX, _PRINTABLE_COVER, pneumatic]
    chunks = [s["content"] for s in samples]
    metadatas = [dict(s["metadata"]) for s in samples]

    order = _ranked_paths(chunks, metadatas, "Quel document décrit l'armoire pneumatique de ARA200 ?")

    assert order.index("pneumatic cabinet.pdf") < order.index("printable version.pdf")
    assert order.index("pneumatic cabinet.pdf") < order.index("index.html")


def test_non_discovery_scores_are_unchanged_vs_baseline():
    policy = retrieval_policy_from_guides([DISCOVERY_POLICY_GUIDE])
    factual_query = "Comment nettoyer le convoyeur ARA200 ?"
    assert is_document_discovery_query(factual_query) is False

    for sample in (_CONVEYOR_HTML, _CONVEYOR_ANNEX, _PRINTABLE_COVER, _PART_MANUAL_INDEX):
        # The flag rerank computes for a factual query is False, so the live score
        # equals the explicit no-discovery baseline: the pre-change code path,
        # byte-for-byte.
        baseline = score_result_with_policy(
            content=sample["content"],
            metadata=sample["metadata"],
            query=factual_query,
            policy=policy,
            is_document_discovery=False,
        )
        live = score_result_with_policy(
            content=sample["content"],
            metadata=sample["metadata"],
            query=factual_query,
            policy=policy,
            is_document_discovery=is_document_discovery_query(factual_query),
        )
        assert live == baseline


def test_non_discovery_ranking_matches_baseline_ordering():
    policy = retrieval_policy_from_guides([DISCOVERY_POLICY_GUIDE])
    samples = [_PART_MANUAL_INDEX, _PRINTABLE_COVER, _CONVEYOR_HTML, _CONVEYOR_ANNEX]
    chunks = [s["content"] for s in samples]
    metadatas = [dict(s["metadata"]) for s in samples]
    factual_query = "Comment nettoyer le convoyeur ARA200 ?"

    # Live ordering for a factual query.
    live_chunks, live_scores, live_metas = rerank_aligned_with_policy(
        list(chunks), [0.5] * len(chunks), [dict(m) for m in metadatas],
        query=factual_query, policy=policy,
    )
    # Baseline scores computed with the discovery flag forced off (old behaviour).
    baseline_scores = [
        score_result_with_policy(
            content=s["content"], metadata=s["metadata"], query=factual_query,
            policy=policy, is_document_discovery=False,
        )
        for s in samples
    ]
    live_score_by_file = {
        m["document_filename"]: m.get("retrieval_policy_score", 0) for m in live_metas
    }
    for sample, baseline in zip(samples, baseline_scores):
        fname = sample["metadata"]["document_filename"]
        # retrieval_policy_score is only stamped when non-zero, so compare via 0.
        assert live_score_by_file.get(fname, 0) == baseline


def test_discovery_flag_actually_changes_preferred_family_score():
    policy = retrieval_policy_from_guides([DISCOVERY_POLICY_GUIDE])
    discovery_query = "Quels documents de convoyeur sont indexés pour ARA200 ?"

    off = score_result_with_policy(
        content=_CONVEYOR_ANNEX["content"], metadata=_CONVEYOR_ANNEX["metadata"],
        query=discovery_query, policy=policy, is_document_discovery=False,
    )
    on = score_result_with_policy(
        content=_CONVEYOR_ANNEX["content"], metadata=_CONVEYOR_ANNEX["metadata"],
        query=discovery_query, policy=policy, is_document_discovery=True,
    )
    # +12 preferred-family boost only under discovery intent.
    assert on - off == 12
