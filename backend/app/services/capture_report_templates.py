"""Markdown templates for expert capture publish and export flows."""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional

from app.models.expert_capture import ExpertCaptureSession

ANDRITZ_TEMPLATE_ID = "andritz_knowledge_v1"
DEFAULT_TEMPLATE_ID = "default"

_CONDITION_TERMS = re.compile(
    r"\b(si|lorsque|quand|condition|paramètre|parametre|seuil|minimum|maximum|doit|nécessite|necessite)\b",
    re.IGNORECASE,
)
_EXCEPTION_TERMS = re.compile(
    r"\b(exception|sauf|sinon|cas particulier|edge|contre-indication|contre indication|hors norme)\b",
    re.IGNORECASE,
)
_DECISION_TERMS = re.compile(
    r"\b(décision|decision|arbitrage|choisir|privilégier|privilegier|retenir|valider|rejeter)\b",
    re.IGNORECASE,
)


def resolve_knowledge_sheet_template(session: ExpertCaptureSession) -> str:
    metrics = session.metrics or {}
    domain = str(metrics.get("capture_domain") or "").strip().lower()
    plan_domain = str((session.plan or {}).get("capture_domain") or "").strip().lower()
    if domain in {"technical", "andritz", "industrial"} or plan_domain in {
        "technical",
        "andritz",
        "industrial",
    }:
        return ANDRITZ_TEMPLATE_ID
    return DEFAULT_TEMPLATE_ID


def build_knowledge_sheet_content(
    template_id: str,
    session: ExpertCaptureSession,
    captured_facts: List[Dict[str, Any]],
    open_questions: List[Dict[str, Any]],
    *,
    transcript: Optional[List[Dict[str, Any]]] = None,
) -> str:
    if template_id == ANDRITZ_TEMPLATE_ID:
        return build_andritz_knowledge_sheet(
            session,
            captured_facts,
            transcript=transcript,
            open_questions=open_questions,
        )
    return _default_knowledge_sheet(session, captured_facts, open_questions)


def build_andritz_knowledge_sheet(
    session: ExpertCaptureSession,
    captured_facts: Iterable[Dict[str, Any]],
    *,
    transcript: Optional[List[Dict[str, Any]]] = None,
    open_questions: Optional[Iterable[Dict[str, Any]]] = None,
) -> str:
    facts = [fact for fact in captured_facts if (fact.get("text") or "").strip()]
    contexte = _andritz_contexte(session, facts, transcript or [])
    decisions = _facts_matching(facts, _DECISION_TERMS) or facts[:2]
    conditions = _facts_matching(facts, _CONDITION_TERMS)
    exceptions = _facts_matching(facts, _EXCEPTION_TERMS)
    if open_questions:
        for item in open_questions:
            label = (item.get("follow_up") or item.get("reason") or "").strip()
            if label and _EXCEPTION_TERMS.search(label):
                exceptions.append({"text": label})
    sources = _collect_sources(facts)
    owner = (session.expert_profile or "Expert métier").strip()

    return (
        f"# Fiche connaissance — {session.title}\n\n"
        f"## Contexte\n{contexte}\n\n"
        f"## Décision\n{_bullet_lines(decisions, 'Aucune décision structurée.')}\n\n"
        f"## Conditions\n{_bullet_lines(conditions, 'Non précisées.')}\n\n"
        f"## Exceptions\n{_bullet_lines(exceptions, 'Aucune exception signalée.')}\n\n"
        f"## Sources\n{_bullet_lines(sources, 'Aucune source documentaire attachée.')}\n\n"
        f"## Owner\n- {owner}\n"
    )


def _default_knowledge_sheet(
    session: ExpertCaptureSession,
    captured_facts: List[Dict[str, Any]],
    open_questions: List[Dict[str, Any]],
) -> str:
    fact_lines = "\n".join(f"- {fact.get('text', '').strip()}" for fact in captured_facts if fact.get("text"))
    open_lines = "\n".join(
        f"- {item.get('gap_id')}: {item.get('follow_up') or item.get('reason')}" for item in open_questions
    )
    return (
        f"# {session.title}\n\n"
        f"Objective: {session.objective}\n\n"
        "## Captured Facts\n"
        f"{fact_lines or '- No validated fact yet.'}\n\n"
        "## Open Questions\n"
        f"{open_lines or '- None recorded.'}\n"
    )


def _andritz_contexte(
    session: ExpertCaptureSession,
    facts: List[Dict[str, Any]],
    transcript: List[Dict[str, Any]],
) -> str:
    parts = [session.objective.strip()] if session.objective else []
    topic_paths = sorted(
        {
            str(fact.get("topic_path") or "").strip()
            for fact in facts
            if fact.get("topic_path")
        }
    )
    if topic_paths:
        parts.append("Sujets couverts : " + ", ".join(topic_paths))
    elif transcript:
        expert_lines = [
            str(turn.get("text") or "").strip()
            for turn in transcript
            if turn.get("speaker") == "expert" and str(turn.get("text") or "").strip()
        ]
        if expert_lines:
            parts.append(f"Échange initial : {expert_lines[0][:240]}")
    return "\n".join(f"- {part}" for part in parts if part) or "- Contexte non renseigné."


def _facts_matching(facts: List[Dict[str, Any]], pattern: re.Pattern[str]) -> List[Dict[str, Any]]:
    return [fact for fact in facts if pattern.search(str(fact.get("text") or ""))]


def _collect_sources(facts: List[Dict[str, Any]]) -> List[str]:
    seen: set[str] = set()
    lines: List[str] = []
    for fact in facts:
        for ref in fact.get("retrieval_refs") or []:
            label = str(ref.get("title") or ref.get("source") or ref.get("ref") or "").strip()
            if not label or label in seen:
                continue
            seen.add(label)
            lines.append(label)
    return lines


def _bullet_lines(items: Iterable[Any], empty_label: str) -> str:
    lines: List[str] = []
    for item in items:
        if isinstance(item, dict):
            text = str(item.get("text") or item.get("label") or "").strip()
        else:
            text = str(item).strip()
        if text:
            lines.append(f"- {text}")
    return "\n".join(lines) if lines else f"- {empty_label}"
