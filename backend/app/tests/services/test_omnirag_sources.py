"""Unit tests for the OmniRAG sources/citation assembly.

These guard the live UX-audit fixes on the Andritz workspace:
  1. scaffolding Knowledge Guides are excluded from the citable Sources panel
  2. duplicate / cross-collection document copies are collapsed
  3. placeholder titles fall back to the real filename
  4. real retrieved passages win over synthetic analysis-evidence summaries
  5. citation numbering maps 1:1 to the displayed sources list
"""
from __future__ import annotations

import re

from app.agents.procurement_agent import (
    _assemble_context_and_sources,
    _clean_source_snippet,
    _display_title,
    _is_placeholder_title,
    _select_citation_entries,
)


# ── Item 3: placeholder titles ────────────────────────────────────────────
def test_placeholder_titles_detected():
    for value in ["Document1", "Document", "document 12", "Untitled document", "Documentation", "", "  "]:
        assert _is_placeholder_title(value), value
    for value in ["Spare Parts List AKK200", "Conveyor JETLACE", "ARA200 manual"]:
        assert not _is_placeholder_title(value), value


def test_display_title_falls_back_to_filename_for_placeholders():
    meta = {"title": "Document1", "document_filename": "spare part list ACO140 ind a.xls"}
    assert _display_title(meta) == "spare part list ACO140 ind a.xls"


def test_display_title_unwraps_archive_flattened_filename():
    meta = {
        "title": "Untitled document",
        "document_filename": "Manual_BBA120__Spare part list__Spare Parts List_BBA120.pdf",
    }
    assert _display_title(meta) == "Spare Parts List_BBA120.pdf"


def test_display_title_prefers_real_title():
    meta = {"title": "Spare Parts List AKK200", "document_filename": "x.pdf"}
    assert _display_title(meta) == "Spare Parts List AKK200"


# ── Item 1: Knowledge Guide excluded from the citable sources ──────────────
def test_knowledge_guide_excluded_from_sources_but_kept_as_context():
    chunks = [
        "Spare Parts List AKK200 — Filtering cartridge LM 300; O-ring string D. 3,6.",
        "Knowledge guide: ANDRITZ Notices Techniques SPL - Knowledge Guide\n\nStatut : brouillon pret a publier.",
    ]
    scores = [0.42, 0.01]
    metadatas = [
        {"document_filename": "Spare Parts List AKK200_Ind A.pdf", "document_id": "doc-1", "page": 4},
        {"source_type": "knowledge_guide", "retrieval_role": "advisory_context", "title": "ANDRITZ Notices Techniques SPL - Knowledge Guide", "guide_version": 1},
    ]

    context_text, sources, has_citable = _assemble_context_and_sources(chunks, scores, metadatas)

    assert has_citable
    assert len(sources) == 1
    titles = [s["title"] for s in sources]
    assert "ANDRITZ Notices Techniques SPL - Knowledge Guide" not in titles
    # The guide still informs the model, but in a clearly non-citable block.
    assert "do not cite" in context_text.lower()
    assert "ANDRITZ Notices Techniques SPL - Knowledge Guide" in context_text


# ── Item 2: de-duplication ─────────────────────────────────────────────────
def test_same_file_across_collections_is_deduped():
    chunks = ["Spare parts list BBA120 page 4 content."] * 2
    scores = [0.5, 0.6]
    metadatas = [
        {
            "document_filename": "Manual_BBA120__Spare part list__Spare Parts List_BBA120.pdf",
            "document_id": "pilot-1",
            "page": 4,
            "collection": "ANDRITZ-NOTICES-TECHNIQUES-SPL-PILOT",
        },
        {
            "document_filename": "Spare Parts List_BBA120.pdf",
            "document_id": "manuals-1",
            "page": 4,
            "collection": "ANDRITZ-MANUALS-BBA120-PILOT",
        },
    ]
    _context, sources, _ = _assemble_context_and_sources(chunks, scores, metadatas)
    assert len(sources) == 1
    # Highest-scoring copy wins.
    assert sources[0]["relevance_score"] == 0.6


def test_distinct_pages_are_preserved_but_exact_dup_removed():
    chunks = ["page 4 a", "page 4 a", "page 5 b"]
    scores = [0.5, 0.5, 0.4]
    metadatas = [
        {"document_filename": "Spare Parts List_BBA120.pdf", "page": 4},
        {"document_filename": "Spare Parts List_BBA120.pdf", "page": 4},
        {"document_filename": "Spare Parts List_BBA120.pdf", "page": 5},
    ]
    _context, sources, _ = _assemble_context_and_sources(chunks, scores, metadatas)
    pages = sorted(s.get("page") for s in sources)
    assert pages == [4, 5]


def test_per_document_passage_cap():
    chunks = [f"passage {p}" for p in range(6)]
    scores = [0.5] * 6
    metadatas = [{"document_filename": "big.pdf", "page": p} for p in range(6)]
    _context, sources, _ = _assemble_context_and_sources(chunks, scores, metadatas)
    assert len(sources) == 3  # _MAX_PASSAGES_PER_DOCUMENT


# ── Item 4: raw passage preferred over synthetic evidence summary ──────────
def test_raw_passage_wins_over_evidence_summary_same_page():
    evidence = (
        'Document analysis evidence: document_heading; '
        'file="Spare Parts List AKK200_Ind A.pdf", locator="page 4". '
        "Document heading: Spare Parts List AKK200 (LM 300)"
    )
    raw = "Filtering cartridge LM 300; O-ring string D. 3,6; quantity 2."
    chunks = [evidence, raw]
    scores = [1.15, 0.41]  # evidence has an artificially high score
    metadatas = [
        {
            "source_type": "document_analysis",
            "document_filename": "Spare Parts List AKK200_Ind A.pdf",
            "page": 4,
        },
        {
            "document_filename": "Spare Parts List AKK200_Ind A.pdf",
            "page": 4,
        },
    ]
    context_text, sources, _ = _assemble_context_and_sources(chunks, scores, metadatas)
    assert len(sources) == 1
    # The model must see the actual rows, not the heading summary.
    assert "Filtering cartridge LM 300" in context_text
    assert "Filtering cartridge LM 300" in sources[0]["snippet"]


def test_clean_source_snippet_strips_evidence_prefix():
    text = (
        'Document analysis evidence: document_procedure_step; '
        'file="x.pdf", locator="page 2". Procedure step: tighten bolt to 40 Nm.'
    )
    assert _clean_source_snippet(text) == "Procedure step: tighten bolt to 40 Nm."


def test_evidence_only_passage_snippet_still_useful():
    # When no raw passage exists for the doc, the evidence row remains but its
    # snippet shows the fact, not the bureaucratic header.
    text = (
        'Table analysis evidence: B = 85; file="trials.xls", sheet="Def strips", '
        'cell="C4". Def strips B = 85 mm.'
    )
    chunks = [text]
    metadatas = [{"source_type": "table_analysis", "document_filename": "trials.xls", "cell_ref": "C4"}]
    _context, sources, _ = _assemble_context_and_sources(chunks, [1.2], metadatas)
    assert len(sources) == 1
    assert "Def strips B = 85 mm." in sources[0]["snippet"]
    assert not sources[0]["snippet"].lower().startswith("table analysis evidence")


# ── Item 5: citation numbering maps 1:1 to displayed sources ───────────────
def test_citation_numbering_matches_sources_count():
    # 6 distinct documents + 1 advisory guide. Old code numbered context over
    # all 7 entries but only listed 5 sources, so [6]/[7] were out of range.
    chunks = [f"doc {i} body" for i in range(6)] + [
        "Knowledge guide: SPL guide\n\nadvisory text"
    ]
    scores = [0.9 - i * 0.1 for i in range(6)] + [0.01]
    metadatas = [{"document_filename": f"doc{i}.pdf", "document_id": f"d{i}", "page": i} for i in range(6)] + [
        {"source_type": "knowledge_guide", "title": "SPL guide", "guide_version": 2}
    ]

    context_text, sources, _ = _assemble_context_and_sources(chunks, scores, metadatas)

    # Every numbered citation marker in the context resolves to a source.
    markers = {int(m) for m in re.findall(r"^\[(\d+)\]", context_text, flags=re.MULTILINE)}
    assert markers, "expected numbered context blocks"
    assert max(markers) <= len(sources)
    assert markers == set(range(1, len(sources) + 1))
    # Advisory guide is not one of the numbered, citable sources.
    assert all(s["type"] != "knowledge_guide" for s in sources)


def test_select_citation_entries_partitions_advisory():
    chunks = ["real doc", "guide body"]
    metadatas = [
        {"document_filename": "real.pdf"},
        {"source_type": "knowledge_guide"},
    ]
    citable, advisory = _select_citation_entries(chunks, [0.5, 0.01], metadatas)
    assert len(citable) == 1
    assert len(advisory) == 1
