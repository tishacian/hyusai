from __future__ import annotations

import pytest

from app.core.config import settings
from app.services.rag import comparative_retrieval as cr
from app.services.rag.comparative_retrieval import (
    ComparativePlan,
    _SubResult,
    build_comparative_plan,
    ensure_entity_coverage,
    merge_comparative_results,
    parse_comparative_entities,
)


@pytest.mark.parametrize(
    "query,left_token,right_token",
    [
        # EN: difference between … and …
        ("What is the difference between the CONTINENTAL GVJS and POLLRICH GVJ1 blowers on AKI300?",
         "continental", "pollrich"),
        # EN: compare X and Y
        ("Compare the Wilo Drain SP and the Wilo NOLH pump manuals available for BEX200.",
         "drain", "nolh"),
        # EN: X vs Y
        ("G150 vs S120 commissioning parameters", "g150", "s120"),
        # FR: différences entre X et Y
        ("Quelles differences de parametres entre les variateurs SINAMICS G150 et SINAMICS S120 ?",
         "g150", "s120"),
        # DE: Unterschied zwischen X und Y
        ("Was ist der Unterschied zwischen dem KD716 und dem KD724 Modell?", "kd716", "kd724"),
    ],
)
def test_parse_comparative_entities_trilingual(query, left_token, right_token):
    entities = parse_comparative_entities(query)
    assert entities is not None, query
    left, right = entities
    assert left_token in left.lower(), (left, query)
    assert right_token in right.lower(), (right, query)


@pytest.mark.parametrize(
    "query",
    [
        "Ou se trouve le parts manual ?",
        "Quelle est la pression nominale de la pompe ?",
        "Liste des pieces de rechange du filtre",
        "What does document LH2 0113 cover?",
    ],
)
def test_non_comparative_queries_do_not_parse(query):
    assert parse_comparative_entities(query) is None


def test_build_plan_flag_gating(monkeypatch):
    query = "Compare the Wilo Drain SP and the Wilo NOLH pump for BEX200."
    monkeypatch.setattr(settings, "rag_comparative_decompose_enabled", True)
    monkeypatch.setattr(settings, "rag_comparative_decompose_balanced", False)

    # fast: never
    assert build_comparative_plan(query, latency_profile="fast") is None
    # balanced: off by default
    assert build_comparative_plan(query, latency_profile="balanced") is None
    # deep: on by default
    plan = build_comparative_plan(query, latency_profile="deep")
    assert plan is not None and len(plan.entities) == 2

    # balanced flips on
    monkeypatch.setattr(settings, "rag_comparative_decompose_balanced", True)
    assert build_comparative_plan(query, latency_profile="balanced") is not None

    # master kill-switch
    monkeypatch.setattr(settings, "rag_comparative_decompose_enabled", False)
    assert build_comparative_plan(query, latency_profile="deep") is None


def test_master_flag_off_means_no_plan_even_for_clear_comparative(monkeypatch):
    monkeypatch.setattr(settings, "rag_comparative_decompose_enabled", False)
    assert build_comparative_plan("X vs Y", latency_profile="deep") is None


def test_merge_dedupes_and_surfaces_second_entity():
    primary = (
        ["CONTINENTAL GVJS blower spec sheet for AKI300 vacuum set"],
        [0.9],
        [{"document_filename": "A__AKI300__continental_gvjs.pdf"}],
    )
    subs = [
        _SubResult(
            "CONTINENTAL GVJS",
            ["CONTINENTAL GVJS blower spec sheet for AKI300 vacuum set"],  # duplicate of primary
            [0.8],
            [{"document_filename": "A__AKI300__continental_gvjs.pdf"}],
        ),
        _SubResult(
            "POLLRICH GVJ1",
            ["POLLRICH GVJ1 maintenance manual AKI300 vacuum"],
            [0.7],
            [{"document_filename": "A__AKI300__pollrich_gvj1.pdf"}],
        ),
    ]
    chunks, scores, metas, diag = merge_comparative_results(primary, subs, limit=10)
    # Duplicate content collapsed: 2 distinct chunks, both entities present.
    assert len(chunks) == 2
    joined = " ".join(chunks).lower()
    assert "continental" in joined and "pollrich" in joined
    assert diag["comparative_subquery_hits"] == {"CONTINENTAL GVJS": 1, "POLLRICH GVJ1": 1}


def test_ensure_coverage_promotes_missing_entity():
    plan = ComparativePlan(
        entities=("CONTINENTAL GVJS", "POLLRICH GVJ1"),
        subqueries=("CONTINENTAL GVJS AKI300", "POLLRICH GVJ1 AKI300"),
    )
    # Final top-k has only the dominant entity (3 CONTINENTAL chunks).
    chunks = [f"CONTINENTAL GVJS detail {i}" for i in range(3)]
    scores = [0.9, 0.8, 0.7]
    metas = [{"document_filename": "continental.pdf"} for _ in range(3)]
    subs = [
        _SubResult("CONTINENTAL GVJS", ["CONTINENTAL GVJS detail 0"], [0.9], [{}]),
        _SubResult("POLLRICH GVJ1", ["POLLRICH GVJ1 maintenance manual"], [0.6],
                   [{"document_filename": "pollrich.pdf"}]),
    ]
    out_chunks, _, out_metas, diag = ensure_entity_coverage(
        chunks, scores, metas, plan=plan, sub_results=subs, limit=3
    )
    joined = " ".join(out_chunks).lower()
    assert "pollrich" in joined, out_chunks
    assert "POLLRICH GVJ1" in diag["comparative_entities_promoted"]
    # The dominant entity is still represented.
    assert "continental" in joined


def test_ensure_coverage_no_hits_does_not_crash():
    plan = ComparativePlan(entities=("A100", "B200"), subqueries=("A100", "B200"))
    chunks = ["A100 only content here"]
    scores = [0.9]
    metas = [{"document_filename": "a100.pdf"}]
    subs = [
        _SubResult("A100", ["A100 only content here"], [0.9], [{}]),
        _SubResult("B200", [], [], []),  # no hits for the second entity
    ]
    out_chunks, out_scores, out_metas, diag = ensure_entity_coverage(
        chunks, scores, metas, plan=plan, sub_results=subs, limit=5
    )
    assert out_chunks == ["A100 only content here"]
    assert "B200" not in diag["comparative_entities_promoted"]


def test_ensure_coverage_both_present_is_noop():
    plan = ComparativePlan(entities=("G150", "S120"), subqueries=("G150", "S120"))
    chunks = ["SINAMICS G150 commissioning", "SINAMICS S120 commissioning"]
    scores = [0.9, 0.8]
    metas = [{}, {}]
    subs = [
        _SubResult("G150", ["SINAMICS G150 commissioning"], [0.9], [{}]),
        _SubResult("S120", ["SINAMICS S120 commissioning"], [0.8], [{}]),
    ]
    out_chunks, _, _, diag = ensure_entity_coverage(
        chunks, scores, metas, plan=plan, sub_results=subs, limit=5
    )
    assert out_chunks == chunks
    assert diag["comparative_entities_promoted"] == []


@pytest.mark.asyncio
async def test_augment_merges_subquery_results(monkeypatch):
    monkeypatch.setattr(settings, "rag_comparative_decompose_max_subqueries", 2)
    plan = ComparativePlan(
        entities=("CONTINENTAL GVJS", "POLLRICH GVJ1"),
        subqueries=("CONTINENTAL GVJS", "POLLRICH GVJ1"),
    )

    class _Res:
        def __init__(self, chunks, metas):
            self.chunks = chunks
            self.scores = [0.5] * len(chunks)
            self.metadatas = metas

    async def fake_retrieve(subquery, deadline):
        if "POLLRICH" in subquery:
            return _Res(["POLLRICH GVJ1 manual"], [{"document_filename": "pollrich.pdf"}])
        return _Res(["CONTINENTAL GVJS manual"], [{"document_filename": "continental.pdf"}])

    primary = (["CONTINENTAL GVJS manual"], [0.9], [{"document_filename": "continental.pdf"}])
    chunks, scores, metas, diag = await cr.augment_with_comparative_subqueries(
        plan=plan, primary=primary, retrieve=fake_retrieve, deadline_seconds=2.0, pool_limit=10
    )
    assert diag["comparative_decompose"] is True
    assert "pollrich" in " ".join(chunks).lower()
    assert "_sub_results" in diag  # consumed by the caller, stripped before metrics
