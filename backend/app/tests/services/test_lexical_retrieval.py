from __future__ import annotations

from app.services.rag.lexical_retrieval import (
    SPARSE_SCHEMA_VERSION,
    analyze_query,
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
