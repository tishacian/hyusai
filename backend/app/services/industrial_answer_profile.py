"""Industrial answer profiling and response-policy guards.

This module keeps answer-shaping policy separate from retrieval routing. It is
generic enough for industrial workspaces, while Andritz can instantiate it via
the workspace chat flow definition.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping


DEFAULT_INDUSTRIAL_ANSWER_PROFILES: dict[str, dict[str, Any]] = {
    "precise_fact": {
        "label": "Precise fact",
        "instructions": [
            "Answer only the asked fact.",
            "Return the value with its unit and condition when available.",
            "Do not add project history, neighbouring equipment or general context unless asked.",
        ],
    },
    "project_summary": {
        "label": "Project summary",
        "instructions": [
            "Produce a complete structured synthesis of the available project information.",
            "Group similar facts by theme and remove repetitions.",
            "Cover objective, customer, equipment, key technical characteristics, operating data and maintenance when present.",
        ],
    },
    "transversal_inventory": {
        "label": "Transversal inventory",
        "requires_exhaustive_retrieval": True,
        "instructions": [
            "Return the exhaustive list identified across projects and manuals.",
            "Merge duplicates and keep equipment references when available.",
            "Do not present a partial top-results list as exhaustive.",
        ],
    },
    "equipment_detail": {
        "label": "Equipment detail",
        "instructions": [
            "Build a consolidated technical sheet for the requested equipment, part or procedure.",
            "Include values, units, applicability and document-backed conditions when present.",
            "Do not infer missing references or part numbers.",
        ],
    },
    "comparison": {
        "label": "Comparison",
        "instructions": [
            "Compare the requested projects or equipment in a concise table.",
            "Only compare dimensions that are available in the provided context.",
            "Name gaps instead of filling them by analogy.",
        ],
    },
    "insufficient_context": {
        "label": "Insufficient context",
        "instructions": [
            "State clearly that no exploitable documentary information is available.",
            "Do not add facts after an absence statement.",
            "Do not invent values, references, projects or part numbers.",
        ],
    },
}


DEFAULT_INDUSTRIAL_ANSWER_POLICY: dict[str, Any] = {
    "key": "industrial_answer_profile_v1",
    "default_answer_profile": "precise_fact",
    "principles": [
        "Answer only the user question.",
        "Use documentary context as the only source for workspace/project/equipment facts.",
        "Consolidate multi-document facts into one coherent answer and remove duplicates.",
        "Never invent a value, part number, equipment reference or project relationship.",
    ],
    "forbidden_internal_terms": [
        "chunk",
        "chunks",
        "score",
        "score vectoriel",
        "vectoriel",
        "base vectorielle",
        "rag",
        "llm",
        "moteur llm",
        "moteur rag",
        "base indexée",
        "documents indexés",
        "occurrence",
        "occurrences",
        "taux de confiance",
        "confidence",
        "retrieval",
        "qdrant",
    ],
    "no_internal_mechanics": True,
    "no_absence_then_answer": True,
    "citation_policy": "numeric_source_ids_only",
    "profiles": DEFAULT_INDUSTRIAL_ANSWER_PROFILES,
}


_PROJECT_SUMMARY_RE = re.compile(
    r"\b(r[eé]sume|synth[eè]se|summary|summari[sz]e)\b.*\b(projet|project)\b"
    r"|\b(projet|project)\b.*\b(r[eé]sume|synth[eè]se|summary|summari[sz]e)\b",
    re.IGNORECASE,
)
_TRANSVERSAL_RE = re.compile(
    r"\b(quels?|quelles?|liste|list|tous|toutes|all|which)\b.*\b(projets?|projects?|manuels?|manuals?)\b"
    r"|\b(dans quels?|where)\b.*\b(projets?|projects?)\b"
    r"|\b(utilisent|using|use|retrouve|retrouve-t-on|installed|install[eé])\b.*\b(projets?|projects?)\b"
    r"|\b(liste|list|tous|toutes|all)\b.*\b(pompes?|pumps?|moteurs?|motors?|injecteurs?|buses?|nozzles?|rouleaux?|s[ée]cheurs?|dryers?|filtres?|filters?|pi[eè]ces?|parts?)\b",
    re.IGNORECASE,
)
_COMPARISON_RE = re.compile(r"\b(compare|compar[ea]|diff[ée]rence|versus| vs\.? )\b", re.IGNORECASE)
_EQUIPMENT_DETAIL_RE = re.compile(
    r"\b(d[ée]tails?|fiche|caract[ée]ristiques?|sp[ée]cifications?|details?|datasheet)\b.*"
    r"\b([A-Z]{2,}\d{2,}|pompe|pump|moteur|motor|injecteur|buse|nozzle|rouleau|dryer|s[ée]cheur|filtre)\b",
    re.IGNORECASE,
)
_PRECISE_FACT_RE = re.compile(
    r"^\s*(quelle?|quels?|quelles?|what|which|combien|how\s+much|how\s+many|pression|pressure|largeur|width|vitesse|speed)\b",
    re.IGNORECASE,
)
_ABSENCE_RE = re.compile(
    r"(je\s+n['’]ai\s+(?:pas|aucune)|aucune\s+(?:information|donn[ée]e)|no\s+(?:information|data|source))",
    re.IGNORECASE,
)
_FACT_AFTER_ABSENCE_RE = re.compile(r"\b(est de|utilise|comprend|inclut|is|uses|includes)\b", re.IGNORECASE)


@dataclass(frozen=True)
class AnswerProfileDecision:
    profile: str
    reason: str
    requires_exhaustive_retrieval: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "profile": self.profile,
            "reason": self.reason,
            "requires_exhaustive_retrieval": self.requires_exhaustive_retrieval,
        }


def industrial_answer_policy() -> dict[str, Any]:
    return {
        **DEFAULT_INDUSTRIAL_ANSWER_POLICY,
        "profiles": {key: dict(value) for key, value in DEFAULT_INDUSTRIAL_ANSWER_PROFILES.items()},
    }


def resolve_answer_profile(query: str, answer_policy: Mapping[str, Any] | None = None) -> AnswerProfileDecision:
    text = str(query or "").strip()
    if not text:
        return AnswerProfileDecision("insufficient_context", "empty_query")
    if _PROJECT_SUMMARY_RE.search(text):
        return AnswerProfileDecision("project_summary", "project_summary_query")
    if _COMPARISON_RE.search(text):
        return AnswerProfileDecision("comparison", "comparison_query")
    if _TRANSVERSAL_RE.search(text):
        return AnswerProfileDecision("transversal_inventory", "cross_project_inventory_query", True)
    if _EQUIPMENT_DETAIL_RE.search(text):
        return AnswerProfileDecision("equipment_detail", "equipment_detail_query")
    if _PRECISE_FACT_RE.search(text) or text.endswith("?"):
        return AnswerProfileDecision("precise_fact", "precise_fact_query")
    default_profile = str((answer_policy or {}).get("default_answer_profile") or "precise_fact")
    return AnswerProfileDecision(default_profile, "default_answer_profile")


def answer_policy_prompt(
    *,
    answer_policy: Mapping[str, Any] | None,
    profile_decision: Mapping[str, Any] | None,
    language: str | None = None,
) -> str:
    policy = dict(answer_policy or industrial_answer_policy())
    profiles = policy.get("profiles") if isinstance(policy.get("profiles"), Mapping) else {}
    profile_key = str((profile_decision or {}).get("profile") or policy.get("default_answer_profile") or "precise_fact")
    profile = profiles.get(profile_key) if isinstance(profiles, Mapping) else {}
    profile_instructions = profile.get("instructions") if isinstance(profile, Mapping) else None
    if not isinstance(profile_instructions, list):
        profile_instructions = DEFAULT_INDUSTRIAL_ANSWER_PROFILES.get(profile_key, {}).get("instructions", [])
    principles = policy.get("principles") if isinstance(policy.get("principles"), list) else []
    forbidden = policy.get("forbidden_internal_terms")
    forbidden_terms = ", ".join(str(term) for term in forbidden[:16]) if isinstance(forbidden, list) else ""
    heading = "Politique de réponse industrielle" if language == "fr" else "Industrial answer policy"
    lines = [f"{heading}:"]
    for item in principles:
        lines.append(f"- {item}")
    lines.extend(
        [
            "- Never mention internal mechanics such as document counts, chunk counts, relevance scores, vector search, databases, LLM/RAG engines, confidence rates or retrieval methods.",
            "- Never say no exploitable information is available and then continue with factual project/equipment claims.",
            "- Keep citations as numeric source ids when sources exist; do not expose raw retrieval diagnostics in the answer text.",
        ]
    )
    if forbidden_terms:
        lines.append(f"- Forbidden internal vocabulary in the user-facing answer includes: {forbidden_terms}.")
    if profile_instructions:
        lines.append(f"Answer profile: {profile_key} ({(profile_decision or {}).get('reason') or 'default'}).")
        for item in profile_instructions:
            lines.append(f"- {item}")
    if profile_key == "transversal_inventory":
        lines.append("- This is an exhaustive inventory question: if evidence is insufficient, say which information is documented and what remains unavailable; do not call a partial sample exhaustive.")
    return "\n".join(lines)


def apply_answer_policy_to_text(
    text: str,
    *,
    answer_policy: Mapping[str, Any] | None = None,
    profile_decision: Mapping[str, Any] | None = None,
) -> tuple[str, list[str]]:
    """Return user-facing text plus policy violation codes.

    The guard is deliberately conservative: it removes obvious mechanics leaks
    and flags contradictions, but it does not try to fabricate missing facts.
    """
    out = str(text or "")
    policy = answer_policy or industrial_answer_policy()
    forbidden = policy.get("forbidden_internal_terms")
    violations: list[str] = []
    if re.search(r"\((?:retrieval|fallback|worker|dense|sparse)\s*:", out, flags=re.IGNORECASE):
        violations.append("internal_diagnostic_parenthetical")
        out = re.sub(
            r"\s*\((?:retrieval|fallback|worker|dense|sparse)\s*:[^)]+\)",
            "",
            out,
            flags=re.IGNORECASE,
        )
    if isinstance(forbidden, list):
        for raw in forbidden:
            term = str(raw or "").strip()
            if not term:
                continue
            if re.search(rf"\b{re.escape(term)}\b", out, flags=re.IGNORECASE):
                violations.append(f"internal_term:{term.lower()}")
                out = re.sub(rf"\b{re.escape(term)}s?\b", "source", out, flags=re.IGNORECASE)
    if _ABSENCE_RE.search(out):
        after = out[_ABSENCE_RE.search(out).end() :]  # type: ignore[union-attr]
        if _FACT_AFTER_ABSENCE_RE.search(after):
            violations.append("absence_then_answer")
            sentences = re.split(r"(?<=[.!?])\s+", out.strip())
            kept = [sentence for sentence in sentences if not _ABSENCE_RE.search(sentence)]
            out = " ".join(kept).strip() or out
    if violations:
        out = re.sub(r"\s{2,}", " ", out).strip()
    return out, sorted(set(violations))
