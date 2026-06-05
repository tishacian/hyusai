from __future__ import annotations

from app.services.rag.lexical_retrieval import (
    SPARSE_SCHEMA_VERSION,
    analyze_query,
    derived_industrial_metadata,
    enrich_payload_for_lexical_sparse,
    identifier_variants,
    lexical_match_details,
    metadata_search_text,
    parse_lexical_config,
)


def test_identifier_variants_are_generic_for_code_like_terms():
    variants = identifier_variants("ABC-123")

    assert "ABC123" in variants
    assert "ABC 123" in variants
    assert "ABC-123" in variants
    assert "ABC_123" in variants


def test_query_analysis_uses_configured_document_type_aliases():
    config = parse_lexical_config(
        {
            "document_types": {
                "parts_catalog": {
                    "aliases": ["parts list", "component catalogue"],
                }
            }
        }
    )

    signals = analyze_query("Find the parts list for PRJ-204", config)

    assert signals.requires_exact_match is True
    assert "PRJ204" in signals.exact_terms
    assert "parts_catalog" in signals.document_type_intents


def test_query_analysis_does_not_treat_hyphenated_words_as_exact_identifiers():
    signals = analyze_query("Peux-tu retrouver la Spare Parts List du projet ACO140 ?")

    assert "ACO140" in signals.exact_terms
    assert "PEUXTU" not in signals.exact_terms


def test_metadata_sparse_text_enriches_filename_and_code_without_domain_terms():
    payload = {
        "content": "A generic chunk.",
        "document_filename": "Component list PRJ204.pdf",
        "project_code": "PRJ204",
        "archive_name": "PRJ204.zip",
    }

    text = metadata_search_text(payload)
    enriched = enrich_payload_for_lexical_sparse(payload)

    assert text.count("PRJ204") >= 3
    assert "Component list PRJ204.pdf" in text
    assert enriched["sparse_schema_version"] == SPARSE_SCHEMA_VERSION
    assert "prj204" in enriched["retrieval_identifiers"]
    assert "component" in enriched["retrieval_terms"]


def test_sparse_enrichment_derives_generic_industrial_metadata_hints():
    payload = {
        "content": "Maintenance note. Part no LM 300 filtering cartridge.",
        "document_filename": "Manual_BHX100__Chapter 08__section IV.pdf",
        "inner_document_path": "BHX100/files/section_IV/Filtration_vacuum_maintenance.html",
        "project_code": "BHX100",
    }

    derived = derived_industrial_metadata(payload)
    enriched = enrich_payload_for_lexical_sparse(payload)

    assert derived["chapter"] == "Chapter 08"
    assert derived["section"] == "Section IV"
    assert derived["family"] == "filtration"
    assert enriched["part_number"] == "LM 300 filtering cartridge"
    assert "lm300filteringcartridge" in enriched["retrieval_identifiers"]
    assert "filtration" in enriched["retrieval_terms"]


def test_sparse_enrichment_requires_part_as_a_word_before_part_number_derivation():
    payload = {
        "content": "La particule M est decrite ici sans reference de piece.",
        "document_filename": "Manual_ACJ200.pdf",
    }

    derived = derived_industrial_metadata(payload)

    assert "part_number" not in derived


def test_lexical_match_boosts_exact_metadata_and_demotes_other_identifiers():
    matching = lexical_match_details(
        content="",
        metadata={"document_filename": "Component list PRJ204.pdf", "project_code": "PRJ204"},
        query="Find component list for PRJ204",
    )
    other = lexical_match_details(
        content="",
        metadata={"document_filename": "Component list PRJ999.pdf", "project_code": "PRJ999"},
        query="Find component list for PRJ204",
    )

    assert matching["score"] > 0
    assert matching["matched_exact_terms"] == ["PRJ204"]
    assert other["missing_exact_match"] is True
    assert other["score"] < matching["score"]


def test_lexical_match_prefers_document_type_in_metadata_over_incidental_content():
    config = parse_lexical_config({"document_types": {"parts_catalog": ["spare parts list"]}})
    metadata_match = lexical_match_details(
        content="Generic spare information.",
        metadata={"document_filename": "Spare Parts List PRJ204.pdf", "project_code": "PRJ204"},
        query="Find the spare parts list for PRJ204",
        config=config,
    )
    content_only = lexical_match_details(
        content="This chapter mentions a spare parts list in passing.",
        metadata={"document_filename": "Chapter 01 PRJ204.pdf", "project_code": "PRJ204"},
        query="Find the spare parts list for PRJ204",
        config=config,
    )

    assert metadata_match["score"] > content_only["score"]
