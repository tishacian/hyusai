"""Exact-reference grounding for the first-use golden path.

A question that names a literal reference ("in evidence AGX-EN-…") must be
answered from the document that actually carries it.  Dense retrieval cannot
make that distinction: on a workspace that already holds an earlier run's
near-identical document, every candidate is equally *about* the question and
the embedding of a random reference carries no meaning.  The two mechanisms
covered here are deliberately narrow — reorder evidence that was retrieved, and
repair a citation only when the evidence is identified rather than guessed.
"""

from app.agents.procurement_agent import (
    _ensure_grounded_citation,
    _exact_identifier_context_note,
    _exact_query_identifiers,
    _exact_reference_output_budget,
    _pin_exact_identifier_evidence,
)

MARKER = "AGX-EN-MU0W13QO-887QTU"
STALE_MARKER = "AGX-EN-MT9P42XZ-118KKR"


# ── Identifier detection ───────────────────────────────────────────────────
def test_run_marker_is_recognised_as_an_exact_identifier():
    identifiers = _exact_query_identifiers(
        f"In evidence {MARKER}, what does the Agentium first-use path do?"
    )

    assert identifiers == [MARKER]


def test_ordinary_words_dates_and_short_codes_are_not_identifiers():
    # No digits, no letters, or too short to be improbable — none of these may
    # start pinning evidence, or every ordinary question would be reordered.
    assert _exact_query_identifiers("Quelle est la pression nominale de la pompe ?") == []
    assert _exact_query_identifiers("Que s'est-il passé le 2026-09-14 ?") == []
    assert _exact_query_identifiers("Où est le lot A1 ?") == []


def test_procurement_style_references_are_identifiers_too():
    # The same mechanism serves order numbers and part codes, which is the
    # everyday version of the golden path's run marker.
    assert _exact_query_identifiers("Statut de la commande PO-2024-8841 ?") == ["PO-2024-8841"]


def test_identifier_detection_is_bounded_and_deduplicated():
    query = " ".join(f"REF-{index}00A" for index in range(9)) + " REF-100A"

    identifiers = _exact_query_identifiers(query)

    assert identifiers == ["REF-000A", "REF-100A", "REF-200A", "REF-300A"]


def test_exact_reference_lookup_has_a_bounded_interactive_answer_budget():
    assert (
        _exact_reference_output_budget(
            2048,
            identifiers=[MARKER],
            wants_more_detail=False,
        )
        == 256
    )


def test_multi_reference_lookup_scales_the_compact_answer_budget():
    assert (
        _exact_reference_output_budget(
            2048,
            identifiers=["NVX-INC-4821", "NVX-PUMP-7742", "SLA-PLATINUM-04"],
            wants_more_detail=False,
        )
        == 1536
    )


def test_exact_reference_budget_preserves_explicit_detail_and_normal_questions():
    assert (
        _exact_reference_output_budget(
            2048,
            identifiers=[MARKER],
            wants_more_detail=True,
        )
        == 2048
    )
    assert (
        _exact_reference_output_budget(
            2048,
            identifiers=[],
            wants_more_detail=False,
        )
        == 2048
    )


# ── Evidence pinning ───────────────────────────────────────────────────────
def test_the_passage_carrying_the_named_reference_is_ranked_first():
    chunks = [
        f"Agentium first-use evidence {STALE_MARKER}. The path opens a cited source.",
        f"Agentium first-use evidence {MARKER}. The path opens a cited source.",
    ]
    scores = [0.91, 0.72]
    metadatas = [
        {"filename": "agentium-golden-stale.pdf"},
        {"filename": f"agentium-golden-{MARKER.lower()}.pdf"},
    ]

    pinned_chunks, pinned_scores, pinned_metadatas, matches = _pin_exact_identifier_evidence(
        chunks, scores, metadatas, [MARKER]
    )

    assert matches == 1
    assert pinned_chunks[0] == chunks[1], "the named evidence outranks the better dense score"
    assert pinned_scores == [0.72, 0.91], "scores travel with their own passage"
    assert pinned_metadatas[0]["filename"] == f"agentium-golden-{MARKER.lower()}.pdf"


def test_a_reference_that_only_appears_in_the_filename_still_pins():
    chunks = ["Agentium first-use evidence. The path opens a cited source.", "Unrelated passage."]

    pinned_chunks, _, _, matches = _pin_exact_identifier_evidence(
        chunks,
        [0.4, 0.9],
        [{}, {"filename": f"agentium-golden-{MARKER.lower()}.pdf"}],
        [MARKER],
    )

    assert matches == 1
    assert pinned_chunks[0] == "Unrelated passage."


def test_ordering_is_untouched_when_the_reference_separates_nothing():
    chunks = ["a", "b", "c"]
    scores = [0.9, 0.8, 0.7]
    metadatas = [{"filename": "x.pdf"}, {}, {}]

    # No identifier at all.
    assert _pin_exact_identifier_evidence(chunks, scores, metadatas, []) == (
        chunks,
        scores,
        metadatas,
        0,
    )
    # An identifier no passage carries.
    assert _pin_exact_identifier_evidence(chunks, scores, metadatas, [MARKER])[:3] == (
        chunks,
        scores,
        metadatas,
    )
    # An identifier every passage carries.
    everywhere = [f"{chunk} {MARKER}" for chunk in chunks]
    assert _pin_exact_identifier_evidence(everywhere, scores, metadatas, [MARKER])[0] == everywhere


def test_the_context_note_names_the_reference_it_ordered_on():
    note = _exact_identifier_context_note([MARKER])

    assert MARKER in note
    assert _exact_identifier_context_note([]) == ""


# ── Citation repair ────────────────────────────────────────────────────────
def _source(marker: str, index: int) -> dict:
    return {
        "id": f"chunk-{index}",
        "title": f"agentium-golden-{marker.lower()}",
        "filename": f"agentium-golden-{marker.lower()}.pdf",
        "snippet": f"Agentium first-use evidence {marker}. The path opens a cited source.",
    }


def test_an_answer_about_a_named_reference_cites_the_one_source_carrying_it():
    answer, repaired = _ensure_grounded_citation(
        f"In evidence {MARKER}, the Agentium first-use path opens the cited source.",
        [_source(MARKER, 0), _source(STALE_MARKER, 1)],
        is_followup=False,
        has_citable_context=True,
        query=f"In evidence {MARKER}, what does the Agentium first-use path do?",
    )

    assert repaired is True
    assert answer.endswith(" [1].")


def test_the_repaired_citation_points_at_the_real_position_of_that_source():
    answer, repaired = _ensure_grounded_citation(
        f"In evidence {MARKER}, the Agentium first-use path opens the cited source.",
        [_source(STALE_MARKER, 0), _source("PO-2024-0001", 1), _source(MARKER, 2)],
        is_followup=False,
        has_citable_context=True,
        query=f"In evidence {MARKER}, what does the Agentium first-use path do?",
    )

    assert repaired is True
    assert answer.endswith(" [3].")


def test_no_citation_when_several_sources_carry_the_named_reference():
    original = f"In evidence {MARKER}, the Agentium first-use path opens the cited source."

    answer, repaired = _ensure_grounded_citation(
        original,
        [_source(MARKER, 0), _source(MARKER, 1)],
        is_followup=False,
        has_citable_context=True,
        query=f"In evidence {MARKER}, what does the path do?",
    )

    assert (answer, repaired) == (original, False), "which copy was used is unknown"


def test_no_citation_when_the_answer_never_mentions_the_named_reference():
    original = "The first-use path opens a cited source."

    answer, repaired = _ensure_grounded_citation(
        original,
        [_source(MARKER, 0), {"title": "Pump manual", "snippet": "Nominal pressure is 40 bar."}],
        is_followup=False,
        has_citable_context=True,
        query=f"In evidence {MARKER}, what does the path do?",
    )

    assert (answer, repaired) == (original, False)


def test_no_citation_when_no_source_carries_the_named_reference():
    original = f"In evidence {MARKER}, the first-use path opens a cited source."

    answer, repaired = _ensure_grounded_citation(
        original,
        [
            _source(STALE_MARKER, 0),
            {"title": "Pump manual", "snippet": "Nominal pressure is 40 bar."},
        ],
        is_followup=False,
        has_citable_context=True,
        query=f"In evidence {MARKER}, what does the path do?",
    )

    assert (answer, repaired) == (original, False)


def test_an_answer_that_already_cites_is_left_alone():
    original = f"In evidence {MARKER}, the path opens the cited source [2]."

    answer, repaired = _ensure_grounded_citation(
        original,
        [_source(STALE_MARKER, 0), _source(MARKER, 1)],
        is_followup=False,
        has_citable_context=True,
        query=f"In evidence {MARKER}, what does the path do?",
    )

    assert (answer, repaired) == (original, False)


def test_follow_up_turns_and_uncitable_retrieval_stay_uncited():
    original = f"In evidence {MARKER}, the path opens the cited source."
    sources = [_source(MARKER, 0)]
    query = f"In evidence {MARKER}, what does the path do?"

    assert _ensure_grounded_citation(
        original, sources, is_followup=True, has_citable_context=True, query=query
    ) == (original, False)
    assert _ensure_grounded_citation(
        original, sources, is_followup=False, has_citable_context=False, query=query
    ) == (original, False)
    assert _ensure_grounded_citation(
        original, [], is_followup=False, has_citable_context=True, query=query
    ) == (original, False)
