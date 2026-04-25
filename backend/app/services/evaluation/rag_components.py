"""RAG component attribution helpers.

The taxonomy mirrors Giskard RAGET's public mental model without taking a
runtime dependency in the chat hot path. Giskard can still be used later
through the optional adapter for offline testset generation.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Mapping, Sequence


RAG_COMPONENT_LABELS: Dict[str, str] = {
    "generator": "Generator",
    "retriever": "Retriever",
    "rewriter": "Rewriter",
    "router": "Router",
    "knowledge_base": "Knowledge Base",
}

QUESTION_TYPE_LABELS: Dict[str, str] = {
    "simple": "Simple",
    "complex": "Complex",
    "distracting": "Distracting",
    "situational": "Situational",
    "double": "Double",
    "conversational": "Conversational",
    "unknown": "Unknown",
}

# Giskard RAGET-inspired question type -> target component mapping.
QUESTION_TYPE_COMPONENTS: Dict[str, List[str]] = {
    "simple": ["generator", "retriever", "router"],
    "complex": ["generator"],
    "distracting": ["generator", "retriever", "rewriter"],
    "situational": ["generator"],
    "double": ["generator", "rewriter"],
    "conversational": ["rewriter"],
    "unknown": ["generator", "retriever"],
}


def normalize_question_type(value: Any) -> str:
    if not isinstance(value, str):
        return "unknown"
    key = value.strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "simple_question": "simple",
        "complex_question": "complex",
        "distracting_question": "distracting",
        "situational_question": "situational",
        "double_question": "double",
        "conversational_question": "conversational",
        "conversation": "conversational",
        "multi_part": "double",
        "multipart": "double",
    }
    key = aliases.get(key, key)
    return key if key in QUESTION_TYPE_LABELS else "unknown"


def heuristic_question_type(query: str, *, history_len: int = 0) -> str:
    """Cheap fallback when the judge omits ``question_type``.

    The LLM judge is expected to classify most new rows. This keeps manual
    tests and fallback judge paths useful without a second LLM call.
    """
    q = (query or "").strip().lower()
    if not q:
        return "unknown"
    if re.search(r"\b(but|however|although|ignore|irrelevant|unrelated)\b", q):
        return "distracting"
    if history_len > 0 or re.search(r"\b(it|that|those|they|them|this)\b", q):
        return "conversational"
    if q.count("?") >= 2 or re.search(r"\b(and|also)\b.+\?", q):
        return "double"
    if re.search(r"\b(i am|i'm|we are|as a|for our|planning|trying to)\b", q):
        return "situational"
    if len(q.split()) > 18:
        return "complex"
    return "simple"


def normalize_components(values: Iterable[Any]) -> List[str]:
    seen = set()
    out: List[str] = []
    for raw in values:
        if not isinstance(raw, str):
            continue
        key = raw.strip().lower().replace("-", "_").replace(" ", "_")
        if key in RAG_COMPONENT_LABELS and key not in seen:
            seen.add(key)
            out.append(key)
    return out


def targeted_components(question_type: str) -> List[str]:
    return list(QUESTION_TYPE_COMPONENTS.get(normalize_question_type(question_type), QUESTION_TYPE_COMPONENTS["unknown"]))


def infer_failed_components(
    *,
    question_type: str,
    scores: Mapping[str, Any] | None,
    composite_score: float,
    hallucination_rate: float,
    threshold_breach: bool,
) -> List[str]:
    """Infer likely failing RAG components for a breached evaluation.

    We intentionally keep this deterministic and explainable. The base
    attribution comes from Giskard's question-type mapping; metric-specific
    hints then add components that are likely involved in common failure
    shapes (e.g. hallucination -> retrieval / KB / generation).
    """
    if not threshold_breach:
        return []

    failed = targeted_components(question_type)
    scores = scores or {}

    def low(name: str, floor: float = 70.0) -> bool:
        try:
            return float(scores.get(name, 100.0)) < floor
        except (TypeError, ValueError):
            return False

    if hallucination_rate > 0.15 or low("hallucination"):
        failed.extend(["generator", "retriever", "knowledge_base"])
    if low("relevance") or low("tool_use"):
        failed.extend(["retriever", "router"])
    if low("instruction_following") or low("coherence"):
        failed.extend(["generator", "rewriter"])
    if low("safety") or low("policy") or low("manipulation"):
        failed.extend(["generator", "router"])
    if composite_score < 60:
        failed.extend(targeted_components(question_type))

    return normalize_components(failed)


def component_health(
    rows: Sequence[Any],
    *,
    composite_min: float,
    hallucination_max: float,
) -> Dict[str, Any]:
    """Aggregate component health from ``EvaluationScore`` rows."""
    buckets: Dict[str, Dict[str, Any]] = {
        key: {
            "component": key,
            "label": label,
            "evaluated": 0,
            "breaches": 0,
            "avg_composite": 0.0,
            "avg_hallucination": 0.0,
            "question_types": {},
        }
        for key, label in RAG_COMPONENT_LABELS.items()
    }

    for row in rows:
        qtype = normalize_question_type(getattr(row, "question_type", None))
        components = targeted_components(qtype)
        failed = normalize_components(getattr(row, "failed_components", None) or [])
        breached = bool(
            (getattr(row, "composite_score", 0.0) or 0.0) < composite_min
            or (getattr(row, "hallucination_rate", 0.0) or 0.0) > hallucination_max
            or failed
        )
        for component in components:
            bucket = buckets[component]
            bucket["evaluated"] += 1
            bucket["avg_composite"] += float(getattr(row, "composite_score", 0.0) or 0.0)
            bucket["avg_hallucination"] += float(getattr(row, "hallucination_rate", 0.0) or 0.0)
            qt = bucket["question_types"].setdefault(qtype, {"count": 0, "breaches": 0})
            qt["count"] += 1
            if breached and component in failed:
                bucket["breaches"] += 1
                qt["breaches"] += 1

    components_out = []
    for bucket in buckets.values():
        evaluated = int(bucket["evaluated"] or 0)
        avg_composite = bucket["avg_composite"] / evaluated if evaluated else 0.0
        avg_hallucination = bucket["avg_hallucination"] / evaluated if evaluated else 0.0
        breaches = int(bucket["breaches"] or 0)
        components_out.append(
            {
                "component": bucket["component"],
                "label": bucket["label"],
                "evaluated": evaluated,
                "breaches": breaches,
                "breach_rate": (breaches / evaluated) if evaluated else 0.0,
                "avg_composite": round(avg_composite, 1),
                "avg_hallucination": round(avg_hallucination, 3),
                "question_types": bucket["question_types"],
            }
        )

    components_out.sort(key=lambda x: (x["breach_rate"], x["breaches"]), reverse=True)
    return {
        "components": components_out,
        "taxonomy": {
            "components": RAG_COMPONENT_LABELS,
            "question_types": QUESTION_TYPE_LABELS,
            "question_type_components": QUESTION_TYPE_COMPONENTS,
        },
    }
