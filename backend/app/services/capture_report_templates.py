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
    plan_section = _plan_restitution_section(session, facts)
    question_lines = _open_question_lines(open_questions or [])

    markdown = (
        f"# Fiche connaissance — {session.title}\n\n"
        f"## Contexte\n{contexte}\n\n"
        f"{plan_section}\n\n"
        f"## Décision\n{_bullet_lines(decisions, 'Aucune décision structurée.')}\n\n"
        f"## Conditions\n{_bullet_lines(conditions, 'Non précisées.')}\n\n"
        f"## Exceptions\n{_bullet_lines(exceptions, 'Aucune exception signalée.')}\n\n"
        f"## Sources\n{_bullet_lines(sources, 'Aucune source documentaire attachée.')}\n\n"
        f"## Owner\n- {owner}\n"
    )
    if question_lines:
        markdown += "\n## Questions ouvertes\n" + "\n".join(question_lines) + "\n"
    return markdown


def _plan_restitution_section(session: ExpertCaptureSession, facts: List[Dict[str, Any]]) -> str:
    topics = [topic for topic in (session.plan or {}).get("topics") or [] if isinstance(topic, dict)]
    if not topics:
        return "## Rapport structuré\n" + _bullet_lines(facts, "Aucune information exploitable capturée.")

    lines: List[str] = ["## Rapport structuré selon le plan"]
    assigned: set[int] = set()
    for index, topic in enumerate(topics, start=1):
        topic_id = str(topic.get("id") or index)
        topic_title = str(topic.get("title") or f"Sujet {index}").strip()
        lines.append(f"### {index}. {topic_title}")
        subtopics = [item for item in topic.get("subtopics") or [] if isinstance(item, dict)]
        topic_facts = _facts_for_plan_node(facts, topic_id=topic_id, subtopic_id=None, title=topic_title)
        for fact_index, fact in topic_facts:
            assigned.add(fact_index)
        if subtopics:
            direct_topic_facts = [
                fact
                for fact_index, fact in topic_facts
                if fact_index not in {
                    idx
                    for subtopic in subtopics
                    for idx, _ in _facts_for_plan_node(
                        facts,
                        topic_id=topic_id,
                        subtopic_id=str(subtopic.get("id") or ""),
                        title=str(subtopic.get("title") or ""),
                    )
                }
            ]
            if direct_topic_facts:
                lines.extend(_fact_bullets(direct_topic_facts))
            for sub_index, subtopic in enumerate(subtopics, start=1):
                subtopic_id = str(subtopic.get("id") or f"{topic_id}.{sub_index}")
                subtopic_title = str(subtopic.get("title") or f"Sous-partie {sub_index}").strip()
                sub_facts = _facts_for_plan_node(
                    facts,
                    topic_id=topic_id,
                    subtopic_id=subtopic_id,
                    title=subtopic_title,
                )
                lines.append(f"#### {index}.{sub_index}. {subtopic_title}")
                if sub_facts:
                    for fact_index, _fact in sub_facts:
                        assigned.add(fact_index)
                    lines.extend(_fact_bullets([fact for _fact_index, fact in sub_facts]))
                else:
                    lines.append("- À compléter.")
        elif topic_facts:
            lines.extend(_fact_bullets([fact for _fact_index, fact in topic_facts]))
        else:
            lines.append("- À compléter.")

    unassigned = [fact for fact_index, fact in enumerate(facts) if fact_index not in assigned]
    if unassigned:
        lines.append("### Points hors plan")
        lines.extend(_fact_bullets(unassigned))
    return "\n".join(lines)


def _facts_for_plan_node(
    facts: List[Dict[str, Any]],
    *,
    topic_id: str,
    subtopic_id: Optional[str],
    title: str,
) -> List[tuple[int, Dict[str, Any]]]:
    title_norm = _norm(title)
    selected: List[tuple[int, Dict[str, Any]]] = []
    for index, fact in enumerate(facts):
        fact_topic = str(fact.get("topic_id") or "")
        fact_subtopic = str(fact.get("subtopic_id") or "")
        path = str(fact.get("topic_path") or "")
        if subtopic_id:
            if fact_subtopic == subtopic_id or (title_norm and title_norm in _norm(path)):
                selected.append((index, fact))
            continue
        if fact_topic == topic_id or (title_norm and title_norm in _norm(path)):
            selected.append((index, fact))
    return selected


def _fact_bullets(facts: Iterable[Dict[str, Any]]) -> List[str]:
    lines: List[str] = []
    for fact in facts:
        text = str(fact.get("text") or fact.get("statement") or "").strip()
        if text:
            lines.append(f"- {text}")
    return lines or ["- À compléter."]


def _norm(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip().lower()


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


def _open_question_lines(open_questions: Iterable[Dict[str, Any]]) -> List[str]:
    closed_statuses = {"answered", "dismissed", "closed", "resolved"}
    lines: List[str] = []
    seen: set[str] = set()
    for item in open_questions:
        status = str(item.get("status") or "open").strip().lower()
        if status in closed_statuses:
            continue
        label = str(
            item.get("follow_up")
            or item.get("reason")
            or item.get("text")
            or item.get("gap_id")
            or ""
        ).strip()
        if not label or label in seen:
            continue
        seen.add(label)
        lines.append(f"- {label}")
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
