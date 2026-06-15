from pathlib import Path

import numpy as np
import pytest

from app.services.rag.retrieval_golden import (
    evaluate_prompt_type_case,
    load_retrieval_golden_cases,
)
from app.services.system_prompts import classifier as classifier_module
from app.services.system_prompts.classifier import (
    PromptTypeDecision,
    classify_prompt_type,
    classify_prompt_type_fast,
)
from app.services.system_prompts.types import SystemPromptType


_HARD_INTENTS = (
    Path(__file__).resolve().parents[2]
    / "resources"
    / "retrieval_golden"
    / "andritz_spl_hard_intents.json"
)
_HARD_INTENT_CASES = [
    case
    for case in load_retrieval_golden_cases(_HARD_INTENTS)
    if case.expected_prompt_type or case.prompt_type_ambiguous
]


# (query, language, expected type) — markers must survive accent folding.
_CASES = [
    # FACTUAL
    ("Quelle est la pression nominale de la pompe ?", "fr", SystemPromptType.FACTUAL),
    ("Combien de cartouches contient le filtre ?", "fr", SystemPromptType.FACTUAL),
    ("Donne-moi la liste des pièces de rechange", "fr", SystemPromptType.FACTUAL),
    ("What is the nominal pressure of the pump?", "en", SystemPromptType.FACTUAL),
    ("Which spare parts are listed for the filter?", "en", SystemPromptType.FACTUAL),
    ("Was ist der Nenndruck der Pumpe?", "de", SystemPromptType.FACTUAL),
    ("Welche Ersatzteile sind aufgeführt?", "de", SystemPromptType.FACTUAL),
    # ANALYTICAL
    ("Comment fonctionne le circuit de filtration sous vide ?", "fr", SystemPromptType.ANALYTICAL),
    ("Explique la procédure de nettoyage des injecteurs", "fr", SystemPromptType.ANALYTICAL),
    ("How does the vacuum filtration circuit work?", "en", SystemPromptType.ANALYTICAL),
    ("Explain the injector cleaning procedure", "en", SystemPromptType.ANALYTICAL),
    ("Wie funktioniert der Vakuumfilterkreislauf?", "de", SystemPromptType.ANALYTICAL),
    # COMPARATIVE
    ("Quelle est la différence entre les modèles KD716 et KD724 ?", "fr", SystemPromptType.COMPARATIVE),
    ("Compare les performances des deux lignes", "fr", SystemPromptType.COMPARATIVE),
    ("What is the difference between the two filter models?", "en", SystemPromptType.COMPARATIVE),
    ("Compare the maintenance costs versus the old line", "en", SystemPromptType.COMPARATIVE),
    ("Was ist der Unterschied zwischen den beiden Modellen?", "de", SystemPromptType.COMPARATIVE),
    # CAUSAL
    ("Pourquoi la pompe perd-elle de la pression ?", "fr", SystemPromptType.CAUSAL),
    ("Quelle est la cause de la surchauffe du moteur ?", "fr", SystemPromptType.CAUSAL),
    ("Why does the pump lose pressure?", "en", SystemPromptType.CAUSAL),
    ("Warum verliert die Pumpe Druck?", "de", SystemPromptType.CAUSAL),
    # HYPOTHETICAL
    ("Que se passerait-il si on doublait la cadence ?", "fr", SystemPromptType.HYPOTHETICAL),
    ("Supposons que la machine soit à l'arrêt, peut-on imaginer un remplacement ?", "fr", SystemPromptType.HYPOTHETICAL),
    ("What if we doubled the line speed?", "en", SystemPromptType.HYPOTHETICAL),
    ("Angenommen die Maschine steht still, könnte man hypothetisch tauschen?", "de", SystemPromptType.HYPOTHETICAL),
]

# Genuinely mixed queries (hypothetical scenario asking for causal
# consequences): either label is acceptable, never something else.
_AMBIGUOUS_CASES = [
    ("Supposons que le filtre soit colmaté, quelles conséquences ?", "fr"),
    ("Angenommen der Filter ist verstopft, was wäre die Folge?", "de"),
]


@pytest.mark.parametrize("query,lang,expected", _CASES, ids=[f"{l}:{q[:36]}" for q, l, e in _CASES for _ in [0]][: len(_CASES)])
def test_fast_classifier_trilingual_table(query, lang, expected):
    decision = classify_prompt_type_fast(query)
    if decision.fallback_applied:
        # Ambiguous queries may legitimately fall back; but the expected type
        # must at least be the top non-fallback posterior.
        top = max(decision.posteriors, key=decision.posteriors.get)
        assert top == expected.value, f"{lang}: {query} -> {decision.posteriors}"
    else:
        assert decision.prompt_type == expected, f"{lang}: {query} -> {decision.posteriors}"


@pytest.mark.parametrize("query,lang", _AMBIGUOUS_CASES)
def test_ambiguous_hypothetical_causal_resolves_to_either(query, lang):
    decision = classify_prompt_type_fast(query)
    acceptable = {SystemPromptType.HYPOTHETICAL, SystemPromptType.CAUSAL, SystemPromptType.ANALYTICAL}
    assert decision.prompt_type in acceptable, f"{lang}: {query} -> {decision.posteriors}"


@pytest.mark.parametrize(
    "case", _HARD_INTENT_CASES, ids=[c.id for c in _HARD_INTENT_CASES]
)
def test_hard_intent_prompt_types_fast(case):
    """The fast classifier matches the hard-intent ground-truth labels.

    Ambiguous cases (imperative retrieval commands) are not held to a strict
    label — they only must not land on an obviously wrong reasoning type.
    """
    result = evaluate_prompt_type_case(case)
    assert result is not None
    if case.prompt_type_ambiguous:
        accepted = set(case.acceptable_prompt_types) or {"factual", "analytical"}
        assert result["predicted"] in accepted, result
    else:
        assert result["correct"], result


def test_hard_intent_fast_accuracy_meets_threshold():
    results = [r for c in _HARD_INTENT_CASES if (r := evaluate_prompt_type_case(c))]
    strict = [r for r in results if not r["ambiguous"]]
    accuracy = sum(1 for r in strict if r["correct"]) / len(strict)
    assert accuracy >= 0.8, [r for r in strict if not r["correct"]]


def test_hard_intent_comparative_and_causal_cases_classify():
    # At least two comparative/analytical/causal cases must land on a reasoning
    # type (not fall back to a generic factual lookup).
    reasoning = {
        SystemPromptType.COMPARATIVE.value,
        SystemPromptType.ANALYTICAL.value,
        SystemPromptType.CAUSAL.value,
    }
    hits = [
        r
        for c in _HARD_INTENT_CASES
        if (r := evaluate_prompt_type_case(c))
        and not r["ambiguous"]
        and r["expected_prompt_type"] in reasoning
        and r["predicted"] in reasoning
        and r["correct"]
    ]
    assert len(hits) >= 2, hits


def test_locate_phrasings_classify_as_factual():
    # The minimal FR "locate-a-document" markers added to the FACTUAL bank.
    for query in (
        "Ou se trouve le parts manual ?",
        "Ou trouver la notice etachrom bc du circuit HP ?",
        "Ou est la documentation de la pompe ?",
    ):
        decision = classify_prompt_type_fast(query)
        assert decision.prompt_type == SystemPromptType.FACTUAL, f"{query} -> {decision.posteriors}"


def test_trivial_is_never_auto_selected():
    for query in ("Bonjour", "Merci beaucoup", "Hello there", "Danke"):
        decision = classify_prompt_type_fast(query)
        assert decision.prompt_type != SystemPromptType.TRIVIAL


def test_no_signal_falls_back_to_analytical():
    decision = classify_prompt_type_fast("xyzzy plugh 12")
    assert decision.fallback_applied is True
    assert decision.prompt_type == SystemPromptType.ANALYTICAL


@pytest.mark.asyncio
async def test_fast_profile_never_embeds(monkeypatch):
    async def boom(_query):
        raise AssertionError("fast profile must not compute coherence")

    monkeypatch.setattr(classifier_module, "_coherence_scores", boom)
    decision = await classify_prompt_type("Pourquoi la pompe fuit ?", latency_profile="fast")
    assert isinstance(decision, PromptTypeDecision)
    assert decision.method == "patterns"


@pytest.mark.asyncio
async def test_balanced_uses_coherence_and_budget_falls_back(monkeypatch):
    calls = {"n": 0}

    async def fake_coherence(_query):
        calls["n"] += 1
        return {pt: (0.9 if pt == SystemPromptType.CAUSAL else 0.1) for pt in classifier_module._COMPILED_BANKS}

    monkeypatch.setattr(classifier_module, "_coherence_scores", fake_coherence)
    decision = await classify_prompt_type("Pourquoi la pompe fuit ?", latency_profile="balanced")
    assert calls["n"] == 1
    assert decision.method == "patterns+coherence"
    assert decision.prompt_type == SystemPromptType.CAUSAL

    import asyncio

    async def slow_coherence(_query):
        await asyncio.sleep(1.0)
        return {}

    monkeypatch.setattr(classifier_module.settings, "rag_prompt_classifier_budget_seconds", 0.05)
    monkeypatch.setattr(classifier_module, "_coherence_scores", slow_coherence)
    decision = await classify_prompt_type("Pourquoi la pompe fuit ?", latency_profile="balanced")
    assert decision.method == "patterns"


@pytest.mark.asyncio
async def test_canonical_embeddings_cached_per_model(monkeypatch):
    embed_calls = {"n": 0}

    class FakeEmbedder:
        model_name = "fake-model"

        async def embed_batch(self, texts):
            embed_calls["n"] += 1
            rng = np.random.default_rng(42)
            return rng.normal(size=(len(texts), 8)).astype(np.float32)

    monkeypatch.setattr(
        "app.services.embedding.embedder.get_shared_embedder", lambda: FakeEmbedder()
    )
    classifier_module._canonical_embedding_cache.pop("fake-model", None)

    await classifier_module._coherence_scores("première requête")
    first_calls = embed_calls["n"]
    await classifier_module._coherence_scores("deuxième requête")
    # First run: canonical batch + query; second run: query only.
    assert first_calls == 2
    assert embed_calls["n"] == 3
