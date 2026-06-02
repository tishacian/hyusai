"""Tests for the hybrid voice transcript glossary resolver."""
from __future__ import annotations

from types import SimpleNamespace

from app.services.voice_transcript_glossary import (
    Glossary,
    build_glossary_from_terms,
    extract_acronyms,
    extract_distinctive_terms,
    resolve_glossary,
)


def _workspace(glossary_terms=None):
    settings = {}
    if glossary_terms is not None:
        settings = {"voice": {"transcript_glossary": list(glossary_terms)}}
    return SimpleNamespace(id="ws-1", slug="andritz", settings=settings)


def _capture_session(plan=None):
    return SimpleNamespace(plan=plan or {}, metrics={})


def test_extract_acronyms_finds_codes_and_allcaps():
    text = "Le BOM et la machine JETLACE utilisent KD724, XS1 et ZCT."
    acronyms = extract_acronyms(text)
    for expected in ("BOM", "JETLACE", "KD724", "XS1", "ZCT"):
        assert expected in acronyms
    # Sentence-initial capitalized words are not acronyms.
    assert "Le" not in acronyms


def test_extract_distinctive_terms_skips_stopwords_and_acronyms():
    text = "le cadre passe sous les injecteurs et la carde tourne"
    terms = [t.lower() for t in extract_distinctive_terms(text)]
    assert "injecteurs" in terms
    assert "carde" in terms
    # Common function words are dropped.
    assert "les" not in terms
    assert "sous" not in terms


def test_resolve_glossary_merges_workspace_plan_and_chunks():
    workspace = _workspace(glossary_terms=["Carde", "BOM"])
    plan = {
        "topics": [
            {"title": "Préparation", "subtopics": [{"title": "Réglage tambour"}]},
        ]
    }
    capture_session = _capture_session(plan=plan)
    chunks = ["La machine JETLACE et le KD724 alimentent les injecteurs."]

    glossary = resolve_glossary(workspace, capture_session, chunks)
    lowered = {t.lower() for t in glossary.terms}

    # Workspace terms
    assert "carde" in lowered
    assert "bom" in lowered
    # Plan labels
    assert "préparation" in lowered
    assert "réglage tambour" in lowered
    # Chunk-extracted acronyms + distinctive terms
    assert "jetlace" in lowered
    assert "kd724" in lowered
    assert "injecteurs" in lowered
    # Acronyms classified
    assert "BOM" in glossary.acronyms
    assert "KD724" in glossary.acronyms


def test_resolve_glossary_dedupes_case_insensitively():
    workspace = _workspace(glossary_terms=["Carde", "carde", "CARDE"])
    glossary = resolve_glossary(workspace, _capture_session(), [])
    lowered = [t.lower() for t in glossary.terms]
    assert lowered.count("carde") == 1
    # First surface wins as canonical.
    assert glossary.canonical_for("carde") == "Carde"


def test_resolve_glossary_respects_cap_authority_first():
    workspace = _workspace(glossary_terms=["AlphaTerm", "BetaTerm"])
    plan = {"topics": [{"title": "GammaTopic", "subtopics": []}]}
    chunks = ["deltaword epsilonword zetaword"]
    glossary = resolve_glossary(workspace, _capture_session(plan), chunks, max_terms=3)
    assert len(glossary.terms) == 3
    lowered = [t.lower() for t in glossary.terms]
    # Workspace + plan are authority-first and survive the cap.
    assert lowered[:3] == ["alphaterm", "betaterm", "gammatopic"]


def test_resolve_glossary_handles_none_capture_session():
    workspace = _workspace(glossary_terms=["Carde"])
    glossary = resolve_glossary(workspace, None, None)
    assert "carde" in {t.lower() for t in glossary.terms}


def test_resolve_glossary_tolerates_dict_term_entries():
    workspace = SimpleNamespace(
        id="ws",
        slug="andritz",
        settings={"voice": {"transcript_glossary": [{"term": "Carde"}, {"surface": "BOM"}]}},
    )
    glossary = resolve_glossary(workspace, None, [])
    lowered = {t.lower() for t in glossary.terms}
    assert {"carde", "bom"} <= lowered


def test_build_glossary_from_terms_is_pure():
    g = build_glossary_from_terms(["BOM", "Carde", "bom"], max_terms=10)
    assert isinstance(g, Glossary)
    assert g.terms == ["BOM", "Carde"]
    assert g.acronyms == {"BOM"}
