"""The proof Work, the conversation and the API are allowed to show."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def proof_identity(card: Mapping[str, Any] | None) -> dict[str, Any]:
    """One shape. A missing proof stays absent. Source text is not copied."""

    empty = {
        "status": "absent",
        "run_id": None,
        "sealed": None,
        "called": None,
        "sources": [],
        "convention": "absent",
        "gap": "absent",
    }
    if not isinstance(card, Mapping):
        return empty
    proof = card.get("proof")
    if not isinstance(proof, Mapping) or not proof.get("run_id"):
        convention = card.get("convention") if isinstance(card.get("convention"), Mapping) else {}
        gap = card.get("gap") if isinstance(card.get("gap"), Mapping) else {}
        empty["convention"] = convention.get("status") or "absent"
        empty["gap"] = gap.get("status") or "absent"
        return empty
    sap = proof.get("sap") if isinstance(proof.get("sap"), Mapping) else None
    citations = proof.get("citations") if isinstance(proof.get("citations"), list) else []
    sources = [
        item.get("source")
        for item in citations
        if isinstance(item, Mapping) and isinstance(item.get("source"), str) and item.get("source")
    ]
    convention = card.get("convention") if isinstance(card.get("convention"), Mapping) else {}
    gap = card.get("gap") if isinstance(card.get("gap"), Mapping) else {}
    return {
        "status": "present",
        "run_id": proof.get("run_id"),
        "sealed": sap.get("sealed") is True if sap else None,
        "called": sap.get("called") is True if sap else None,
        "sources": sources,
        "convention": convention.get("status") or "absent",
        "gap": gap.get("status") or "absent",
    }


def same_proof(*cards: Mapping[str, Any] | None) -> bool:
    identities = [proof_identity(card) for card in cards]
    return all(item == identities[0] for item in identities)
