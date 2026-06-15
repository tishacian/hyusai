"""Bayesian reasoning-type classifier (RAGGER Eq. 7-8, Annexe C.1).

Resolves which ``SystemPromptType`` template fits a query when the caller
selected ``auto``, combining three signals:

1. pattern coverage — trilingual FR/EN/DE marker banks per type, matched on
   the accent-folded query;
2. pattern entropy — Shannon entropy over the per-type match distribution
   (many types matching at once = weak evidence);
3. semantic coherence — cosine between the query embedding and canonical
   type descriptions (FR/EN/DE), whose embeddings are computed once per
   embedding model and cached at module level.

Latency contract:
- ``classify_prompt_type_fast``: patterns + entropy only, <1 ms — the only
  version allowed on the fast profile;
- ``classify_prompt_type``: adds the embedding coherence signal under a hard
  budget; timeout falls back to the fast result.

TRIVIAL is never auto-selected (explicit only): misclassifying a real
question as small talk would skip retrieval entirely.
"""
from __future__ import annotations

import asyncio
import math
import re
import unicodedata
from dataclasses import dataclass

import numpy as np

from app.core.config import settings
from app.core.logging import get_logger
from app.services.system_prompts.types import SystemPromptType

logger = get_logger(__name__)


def _fold(text: str) -> str:
    return "".join(
        ch for ch in unicodedata.normalize("NFKD", str(text or "")) if not unicodedata.combining(ch)
    ).lower()


# Trilingual FR/EN/DE marker banks, matched on the folded query, with a weight
# per pattern: specific multi-word markers ("difference entre", "supposons")
# must dominate generic interrogatives ("quelle", "was ist") that co-occur in
# almost every question. French is the primary deployment language.
_GENERIC = 0.5
_NORMAL = 1.0
_STRONG = 1.5
_SPECIFIC = 2.0

_PATTERN_BANKS: dict[SystemPromptType, tuple[tuple[str, float], ...]] = {
    SystemPromptType.FACTUAL: (
        (r"\bwhat is\b", _GENERIC), (r"\bwho\b", _NORMAL), (r"\bwhere\b", _NORMAL),
        (r"\bwhen\b", _NORMAL), (r"\bwhich\b", _GENERIC), (r"\blist\b", _STRONG),
        (r"\bdefine\b", _STRONG), (r"\bname\b", _NORMAL), (r"\bidentify\b", _NORMAL),
        (r"\bspecify\b", _NORMAL),
        (r"\bqu'?est[- ]ce\b", _GENERIC), (r"\bqui\b", _NORMAL), (r"\bquand\b", _NORMAL),
        (r"\bquel(?:le)?s?\b", _GENERIC), (r"\bliste[rz]?\b", _STRONG),
        (r"\bdefini[srt]\b", _STRONG), (r"\bdonne[- ]moi\b", _STRONG),
        (r"\bretrouve[rz]?\b", _STRONG), (r"\bcombien\b", _STRONG),
        # Locate-a-document phrasings ("où se trouve / où trouver / où est"):
        # factual source lookups that otherwise carry no marker and fall back.
        (r"\bou se trouve", _STRONG), (r"\bou trouve[rz]?\b", _STRONG),
        (r"\bou (?:est|sont)\b", _NORMAL),
        (r"\bwas ist\b", _GENERIC), (r"\bwer\b", _NORMAL), (r"\bwo\b", _NORMAL),
        (r"\bwann\b", _NORMAL), (r"\bwelche[rsn]?\b", _GENERIC), (r"\bnenne\b", _STRONG),
    ),
    SystemPromptType.ANALYTICAL: (
        (r"\bhow\b", _NORMAL), (r"\banaly[sz]e\b", _STRONG), (r"\bexamine\b", _STRONG),
        (r"\bevaluate\b", _STRONG), (r"\bexplain\b", _STRONG), (r"\bdescribe\b", _STRONG),
        (r"\bassess\b", _STRONG), (r"\binvestigate\b", _STRONG),
        (r"\bcomment\b", _NORMAL), (r"\banalyse[rz]?\b", _STRONG), (r"\bexamine[rz]?\b", _STRONG),
        (r"\bevalue[rz]?\b", _STRONG), (r"\bexplique[rz]?\b", _STRONG), (r"\bdecri[stv]\b", _STRONG),
        (r"\bdetaille[rz]?\b", _STRONG), (r"\bprocedure\b", _NORMAL),
        (r"\bwie\b", _NORMAL), (r"\banalysiere\b", _STRONG), (r"\buntersuche\b", _STRONG),
        (r"\bbewerte\b", _STRONG), (r"\berklare\b", _STRONG), (r"\bbeschreibe\b", _STRONG),
    ),
    SystemPromptType.COMPARATIVE: (
        (r"\bcompare\b", _STRONG), (r"\bcontrast\b", _STRONG), (r"\bversus\b", _STRONG),
        (r"\bvs\.?\b", _STRONG), (r"\bdiffer", _STRONG), (r"\bsimilar\b", _NORMAL),
        (r"\bbetter\b", _NORMAL), (r"\bworse\b", _NORMAL), (r"\bdifference between\b", _SPECIFIC),
        (r"\bcompare[rz]?\b", _STRONG), (r"\bcomparaison\b", _STRONG),
        (r"\bdifference[s]? entre\b", _SPECIFIC), (r"\bpar rapport a\b", _SPECIFIC),
        (r"\bplutot que\b", _STRONG), (r"\bmeilleur(?:e)?s?\b", _NORMAL), (r"\bressemble\b", _NORMAL),
        (r"\bvergleich", _STRONG), (r"\bunterschied(?:e)? zwischen\b", _SPECIFIC),
        (r"\bgegenuber\b", _STRONG), (r"\bbesser\b", _NORMAL), (r"\bahnlich\b", _NORMAL),
    ),
    SystemPromptType.CAUSAL: (
        (r"\bwhy\b", _SPECIFIC), (r"\bbecause\b", _STRONG), (r"\bcause[sd]?\b", _STRONG),
        (r"\beffect\b", _NORMAL), (r"\bresult\b", _NORMAL), (r"\bconsequence\b", _STRONG),
        (r"\blead[s]? to\b", _STRONG), (r"\bdue to\b", _STRONG),
        (r"\bpourquoi\b", _SPECIFIC), (r"\ba cause de\b", _SPECIFIC), (r"\bcause[rs]?\b", _STRONG),
        (r"\beffet\b", _NORMAL), (r"\bconsequence[s]?\b", _STRONG), (r"\braison\b", _STRONG),
        (r"\bentraine\b", _STRONG), (r"\bprovoque\b", _STRONG), (r"\bdu a\b", _STRONG),
        (r"\borigine\b", _NORMAL),
        (r"\bwarum\b", _SPECIFIC), (r"\bweshalb\b", _SPECIFIC), (r"\bursache\b", _STRONG),
        (r"\bwirkung\b", _NORMAL), (r"\bfolge\b", _STRONG), (r"\bfuhrt zu\b", _STRONG),
        (r"\bwegen\b", _STRONG),
    ),
    SystemPromptType.HYPOTHETICAL: (
        (r"\bif\b", _GENERIC), (r"\bwould\b", _NORMAL), (r"\bcould\b", _GENERIC),
        (r"\bmight\b", _NORMAL), (r"\bassume\b", _SPECIFIC), (r"\bsuppose\b", _SPECIFIC),
        (r"\bimagine\b", _SPECIFIC), (r"\bhypothetical", _SPECIFIC), (r"\bwhat if\b", _SPECIFIC),
        (r"\bsi\b", _GENERIC), (r"\bserait\b", _NORMAL), (r"\bpourrait\b", _GENERIC),
        (r"\bsupposons\b", _SPECIFIC), (r"\bimaginons\b", _SPECIFIC), (r"\bhypothese\b", _SPECIFIC),
        (r"\bdans le cas ou\b", _SPECIFIC), (r"\bque se passerait\b", _SPECIFIC),
        (r"\badmettons\b", _SPECIFIC),
        (r"\bwenn\b", _GENERIC), (r"\bware\b", _NORMAL), (r"\bkonnte\b", _GENERIC),
        (r"\bangenommen\b", _SPECIFIC), (r"\bfalls\b", _NORMAL), (r"\bhypothetisch\b", _SPECIFIC),
    ),
}

_COMPILED_BANKS = {
    prompt_type: tuple((re.compile(pattern), weight) for pattern, weight in patterns)
    for prompt_type, patterns in _PATTERN_BANKS.items()
}

# Signal weights per type (paper Annexe C.1): (entropy, coherence, coverage).
_SIGNAL_WEIGHTS: dict[SystemPromptType, tuple[float, float, float]] = {
    SystemPromptType.FACTUAL: (0.4, 0.4, 0.2),
    SystemPromptType.ANALYTICAL: (0.3, 0.4, 0.3),
    SystemPromptType.COMPARATIVE: (0.2, 0.4, 0.4),
    SystemPromptType.CAUSAL: (0.3, 0.3, 0.4),
    SystemPromptType.HYPOTHETICAL: (0.2, 0.5, 0.3),
}

# Type-specific prevalence/reliability scaling (paper Annexe C.1).
_TYPE_SCALING: dict[SystemPromptType, float] = {
    SystemPromptType.FACTUAL: 1.4,
    SystemPromptType.ANALYTICAL: 1.25,
    SystemPromptType.COMPARATIVE: 1.0,
    SystemPromptType.CAUSAL: 1.2,
    SystemPromptType.HYPOTHETICAL: 0.8,
}

# Canonical descriptions per type (FR/EN/DE) for the coherence signal.
_CANONICAL_DESCRIPTIONS: dict[SystemPromptType, tuple[str, ...]] = {
    SystemPromptType.FACTUAL: (
        "Question factuelle demandant une information précise et vérifiable, un fait, une valeur ou une référence.",
        "A factual question asking for a specific verifiable piece of information, a value or a reference.",
        "Eine faktische Frage nach einer bestimmten überprüfbaren Information, einem Wert oder einer Referenz.",
    ),
    SystemPromptType.ANALYTICAL: (
        "Demande d'analyse ou d'explication détaillée d'un processus, d'une procédure ou d'un fonctionnement.",
        "A request to analyse or explain in detail a process, a procedure or how something works.",
        "Eine Bitte um Analyse oder ausführliche Erklärung eines Prozesses oder einer Funktionsweise.",
    ),
    SystemPromptType.COMPARATIVE: (
        "Comparaison entre plusieurs éléments, leurs similitudes, différences, avantages et inconvénients.",
        "A comparison between several items, their similarities, differences, strengths and weaknesses.",
        "Ein Vergleich mehrerer Elemente, ihrer Gemeinsamkeiten, Unterschiede, Vor- und Nachteile.",
    ),
    SystemPromptType.CAUSAL: (
        "Question sur les causes, les raisons ou les conséquences d'un phénomène ou d'un problème.",
        "A question about the causes, reasons or consequences of a phenomenon or a problem.",
        "Eine Frage nach den Ursachen, Gründen oder Folgen eines Phänomens oder Problems.",
    ),
    SystemPromptType.HYPOTHETICAL: (
        "Question conditionnelle ou spéculative explorant un scénario, une hypothèse ou un cas envisagé.",
        "A conditional or speculative question exploring a scenario, a hypothesis or a what-if case.",
        "Eine konditionale oder spekulative Frage zu einem Szenario oder einer Hypothese.",
    ),
}

_canonical_embedding_cache: dict[str, dict[SystemPromptType, np.ndarray]] = {}


@dataclass(frozen=True)
class PromptTypeDecision:
    prompt_type: SystemPromptType
    confidence: float
    posteriors: dict[str, float]
    signals: dict[str, dict[str, float]]
    fallback_applied: bool
    method: str  # "patterns" | "patterns+coherence"


def _pattern_signals(query: str) -> tuple[dict[SystemPromptType, float], dict[SystemPromptType, float]]:
    folded = _fold(query)
    coverage: dict[SystemPromptType, float] = {}
    matches: dict[SystemPromptType, float] = {}
    for prompt_type, patterns in _COMPILED_BANKS.items():
        weighted_hits = sum(weight for pattern, weight in patterns if pattern.search(folded))
        total_weight = sum(weight for _, weight in patterns)
        matches[prompt_type] = weighted_hits
        coverage[prompt_type] = weighted_hits / max(1.0, total_weight)
    return coverage, matches


def _entropy_score(matches: dict[SystemPromptType, float]) -> float:
    """1 when matches concentrate on one type, 0 when spread evenly or absent."""
    total = sum(matches.values())
    if total <= 0:
        return 0.0
    probabilities = [count / total for count in matches.values() if count > 0]
    entropy = -sum(p * math.log2(p) for p in probabilities)
    max_entropy = math.log2(len(_COMPILED_BANKS))
    return 1.0 - (entropy / max_entropy if max_entropy else 0.0)


def _posteriors(
    coverage: dict[SystemPromptType, float],
    matches: dict[SystemPromptType, float],
    coherence: dict[SystemPromptType, float] | None,
) -> dict[SystemPromptType, float]:
    concentration = _entropy_score(matches)
    total_mass = sum(matches.values())
    raw: dict[SystemPromptType, float] = {}
    for prompt_type in _COMPILED_BANKS:
        w_entropy, w_coherence, w_coverage = _SIGNAL_WEIGHTS[prompt_type]
        # Share of the weighted match mass: specific markers dominate generic
        # interrogatives that co-occur in almost every question.
        match_share = (matches.get(prompt_type, 0.0) / total_mass) if total_mass > 0 else 0.0
        score = (
            w_entropy * concentration * match_share
            + w_coverage * coverage.get(prompt_type, 0.0) * 4.0  # coverage is sparse; rescale
            + w_coherence * (coherence or {}).get(prompt_type, 0.0)
        )
        raw[prompt_type] = max(0.0, score) * _TYPE_SCALING[prompt_type]
    total = sum(raw.values())
    if total <= 0:
        return {prompt_type: 1.0 / len(raw) for prompt_type in raw}
    return {prompt_type: value / total for prompt_type, value in raw.items()}


def _decide(
    posteriors: dict[SystemPromptType, float],
    *,
    coverage: dict[SystemPromptType, float],
    coherence: dict[SystemPromptType, float] | None,
    method: str,
) -> PromptTypeDecision:
    ranked = sorted(posteriors.items(), key=lambda item: item[1], reverse=True)
    top_type, top_score = ranked[0]
    second_score = ranked[1][1] if len(ranked) > 1 else 0.0
    confidence = top_score - second_score
    min_confidence = float(settings.rag_prompt_classifier_min_confidence)
    fallback = confidence < min_confidence
    return PromptTypeDecision(
        prompt_type=SystemPromptType.ANALYTICAL if fallback else top_type,
        confidence=round(confidence, 4),
        posteriors={pt.value: round(score, 4) for pt, score in posteriors.items()},
        signals={
            "coverage": {pt.value: round(v, 4) for pt, v in coverage.items()},
            **({"coherence": {pt.value: round(v, 4) for pt, v in coherence.items()}} if coherence else {}),
        },
        fallback_applied=fallback,
        method=method,
    )


def classify_prompt_type_fast(query: str) -> PromptTypeDecision:
    """Patterns + entropy only — the fast-profile path, <1 ms."""
    coverage, matches = _pattern_signals(query)
    posteriors = _posteriors(coverage, matches, None)
    return _decide(posteriors, coverage=coverage, coherence=None, method="patterns")


async def _coherence_scores(query: str) -> dict[SystemPromptType, float]:
    from app.services.embedding.embedder import get_shared_embedder

    embedder = get_shared_embedder()
    model_name = getattr(embedder, "model_name", "default")
    canonical = _canonical_embedding_cache.get(model_name)
    if canonical is None:
        texts: list[str] = []
        spans: list[tuple[SystemPromptType, int, int]] = []
        for prompt_type, descriptions in _CANONICAL_DESCRIPTIONS.items():
            start = len(texts)
            texts.extend(descriptions)
            spans.append((prompt_type, start, len(texts)))
        vectors = np.asarray(await embedder.embed_batch(texts), dtype=np.float32)
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        vectors = vectors / norms
        canonical = {pt: vectors[start:end] for pt, start, end in spans}
        _canonical_embedding_cache[model_name] = canonical

    query_vec = np.asarray(await embedder.embed_batch([str(query or "")]), dtype=np.float32)[0]
    norm = float(np.linalg.norm(query_vec)) or 1.0
    query_vec = query_vec / norm
    return {
        prompt_type: float(np.max(vectors @ query_vec))
        for prompt_type, vectors in canonical.items()
    }


async def classify_prompt_type(
    query: str,
    *,
    latency_profile: str | None,
) -> PromptTypeDecision:
    """Full classifier: patterns + entropy + budgeted embedding coherence."""
    profile = str(latency_profile or "").strip().lower()
    fast_decision = classify_prompt_type_fast(query)
    if profile not in {"balanced", "deep"}:
        return fast_decision
    budget = None if profile == "deep" else max(0.05, float(settings.rag_prompt_classifier_budget_seconds))
    try:
        if budget is not None:
            coherence = await asyncio.wait_for(_coherence_scores(query), timeout=budget)
        else:
            coherence = await _coherence_scores(query)
    except (TimeoutError, asyncio.TimeoutError):
        return fast_decision
    except Exception as exc:  # noqa: BLE001 - classification must never break chat.
        logger.warning("Prompt classifier coherence failed", error=str(exc))
        return fast_decision
    coverage, matches = _pattern_signals(query)
    posteriors = _posteriors(coverage, matches, coherence)
    return _decide(posteriors, coverage=coverage, coherence=coherence, method="patterns+coherence")
