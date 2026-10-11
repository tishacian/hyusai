"""Explainable scenario scoring for advisory decision support."""
from __future__ import annotations

from typing import Any, Optional


RISK_MULTIPLIER = {"critical": 1.25, "high": 1.1, "medium": 0.9, "low": 0.72, "red": 1.15, "orange": 0.95, "green": 0.7}


BASE_SCENARIOS = [
    {
        "id": "communication",
        "label": "Option communication",
        "summary": "Message public prudent, source et limite aux faits consolides.",
        "cost_score": 18,
        "impact_score": 58,
        "confidence": 0.78,
        "time_sensitivity": 82,
        "risk_reduction": 46,
        "rationale": "Action rapide, peu intrusive, utile si le risque principal est la perception publique.",
    },
    {
        "id": "terrain",
        "label": "Option terrain",
        "summary": "Mission locale non militaire avec autorites habilitees et retour cabinet.",
        "cost_score": 62,
        "impact_score": 76,
        "confidence": 0.68,
        "time_sensitivity": 61,
        "risk_reduction": 72,
        "rationale": "Renforce la presence institutionnelle et objectivise l'etat terrain.",
    },
    {
        "id": "cabinet",
        "label": "Option arbitrage cabinet",
        "summary": "Instruction Directeur de cabinet pour obtenir options budgetaires, delais et porteur.",
        "cost_score": 34,
        "impact_score": 69,
        "confidence": 0.82,
        "time_sensitivity": 74,
        "risk_reduction": 59,
        "rationale": "Produit une trace decisionnelle et force la clarification des responsabilites.",
    },
    {
        "id": "interministerial",
        "label": "Option coordination interministerielle",
        "summary": "Point court avec les ministeres contributeurs et cellule territoriale.",
        "cost_score": 71,
        "impact_score": 83,
        "confidence": 0.62,
        "time_sensitivity": 52,
        "risk_reduction": 78,
        "rationale": "Fort potentiel d'alignement, mais plus lourd a declencher et a cadrer.",
    },
]


def generate_scenarios(
    *,
    target_kind: str = "cabinet",
    target_id: str = "",
    risk_level: str = "medium",
    source_refs: Optional[list[str]] = None,
    agenda_pressure: int = 0,
    signal_strength: int = 50,
    context: Optional[dict[str, Any]] = None,
) -> list[dict[str, Any]]:
    """Generate deterministic, comparable options for a ministerial target."""

    source_refs = source_refs or []
    context = context or {}
    multiplier = RISK_MULTIPLIER.get(str(risk_level).lower(), 0.9)
    options: list[dict[str, Any]] = []
    for base in BASE_SCENARIOS:
        item = dict(base)
        item["target_kind"] = target_kind
        item["target_id"] = target_id
        item["risk_level"] = risk_level
        item["sources"] = source_refs
        _tune_for_target(item, target_kind=target_kind, target_id=target_id, context=context)
        item["impact_score"] = _cap(item["impact_score"] * multiplier + signal_strength * 0.08)
        item["time_sensitivity"] = _cap(item["time_sensitivity"] + agenda_pressure * 0.18)
        item["risk_reduction"] = _cap(item["risk_reduction"] * multiplier)
        item["decision_score"] = _decision_score(item)
        item["impact"] = _impact_sentence(item)
        item["confidence_label"] = _confidence_label(item["confidence"])
        options.append(item)
    options.sort(key=lambda row: row["decision_score"], reverse=True)
    for idx, option in enumerate(options):
        option["rank"] = idx + 1
        option["recommended"] = idx == 0 or (idx == 1 and option["decision_score"] >= options[0]["decision_score"] - 6)
    return options


def compare_scenarios(options: list[dict[str, Any]]) -> dict[str, Any]:
    if not options:
        return {"best": None, "tradeoffs": []}
    ordered = sorted(options, key=lambda row: row.get("decision_score", 0), reverse=True)
    best = ordered[0]
    tradeoffs = [
        {
            "id": option["id"],
            "label": option["label"],
            "score": option.get("decision_score", 0),
            "tradeoff": _tradeoff(option),
        }
        for option in ordered
    ]
    return {"best": best, "tradeoffs": tradeoffs}


def recommend_scenario(**kwargs: Any) -> dict[str, Any]:
    options = generate_scenarios(**kwargs)
    comparison = compare_scenarios(options)
    return {"recommended": comparison["best"], "options": options, "comparison": comparison}


def _tune_for_target(item: dict[str, Any], *, target_kind: str, target_id: str, context: dict[str, Any]) -> None:
    target = f"{target_kind} {target_id}".lower()
    if "zone" in target or "nord" in target or "north" in target:
        if item["id"] == "terrain":
            item["impact_score"] += 10
            item["risk_reduction"] += 8
        if item["id"] == "communication":
            item["time_sensitivity"] += 8
    if "press" in target or "radio" in target or "communication" in target:
        if item["id"] == "communication":
            item["impact_score"] += 12
            item["cost_score"] -= 4
        if item["id"] == "terrain":
            item["cost_score"] += 8
    if "project" in target or "health" in target or "sante" in target:
        if item["id"] == "cabinet":
            item["impact_score"] += 10
            item["confidence"] += 0.05
        if item["id"] == "interministerial":
            item["risk_reduction"] += 7
    if context.get("requires_visibility") and item["id"] == "communication":
        item["impact_score"] += 8


def _decision_score(item: dict[str, Any]) -> int:
    score = (
        item["impact_score"] * 0.34
        + item["risk_reduction"] * 0.28
        + item["time_sensitivity"] * 0.16
        + item["confidence"] * 100 * 0.18
        - item["cost_score"] * 0.18
    )
    return int(round(_cap(score)))


def _impact_sentence(item: dict[str, Any]) -> str:
    return (
        f"Impact {int(item['impact_score'])}/100, effort {int(item['cost_score'])}/100, "
        f"confiance {int(item['confidence'] * 100)}%."
    )


def _tradeoff(item: dict[str, Any]) -> str:
    if item["cost_score"] >= 65:
        return "Fort impact potentiel, mais coordination lourde."
    if item["time_sensitivity"] >= 75:
        return "Action rapide adaptee a une fenetre decisionnelle courte."
    if item["confidence"] >= 0.78:
        return "Option robuste et facilement justifiable."
    return "Option utile, a consolider par sources ou arbitrage complementaire."


def _confidence_label(value: float) -> str:
    if value >= 0.78:
        return "haute"
    if value >= 0.62:
        return "moyenne"
    return "a consolider"


def _cap(value: float, low: int = 0, high: int = 100) -> int:
    return max(low, min(high, int(round(value))))
