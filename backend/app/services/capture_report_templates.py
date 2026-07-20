"""Markdown templates for expert capture publish and export flows."""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional

from app.models.expert_capture import ExpertCaptureSession

# Canonical id for the industrial knowledge sheet. ``andritz_knowledge_v1`` is
# kept as a backward-compatible alias so legacy/stored ids still resolve to the
# same industrial sheet.
INDUSTRIAL_TEMPLATE_ID = "industrial_v1"
ANDRITZ_TEMPLATE_ID = "andritz_knowledge_v1"
_INDUSTRIAL_TEMPLATE_IDS = frozenset({INDUSTRIAL_TEMPLATE_ID, ANDRITZ_TEMPLATE_ID})
FSE_INTERVENTION_REPORT_TEMPLATE_ID = "fse_intervention_report_v1"
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
    from app.services.capture_templates import resolve_session_capture_template

    capture_template = resolve_session_capture_template(
        plan=session.plan or {},
        metrics=session.metrics or {},
    )
    if capture_template:
        report_id = str(capture_template.get("report_template_id") or "").strip()
        if report_id:
            return report_id
    metrics = session.metrics or {}
    domain = str(metrics.get("capture_domain") or "").strip().lower()
    plan_domain = str((session.plan or {}).get("capture_domain") or "").strip().lower()
    if domain in {"technical", "andritz", "industrial"} or plan_domain in {
        "technical",
        "andritz",
        "industrial",
    }:
        return INDUSTRIAL_TEMPLATE_ID
    return DEFAULT_TEMPLATE_ID


def build_knowledge_sheet_content(
    template_id: str,
    session: ExpertCaptureSession,
    captured_facts: List[Dict[str, Any]],
    open_questions: List[Dict[str, Any]],
    *,
    transcript: Optional[List[Dict[str, Any]]] = None,
    plan_structure: Optional[Dict[str, Any]] = None,
) -> str:
    if template_id == FSE_INTERVENTION_REPORT_TEMPLATE_ID:
        return build_fse_intervention_report(
            session,
            captured_facts,
            open_questions=open_questions,
            plan_structure=plan_structure,
        )
    if template_id in _INDUSTRIAL_TEMPLATE_IDS:
        return build_andritz_knowledge_sheet(
            session,
            captured_facts,
            transcript=transcript,
            open_questions=open_questions,
        )
    return _default_knowledge_sheet(session, captured_facts, open_questions)


def build_fse_intervention_report(
    session: ExpertCaptureSession,
    captured_facts: Iterable[Dict[str, Any]],
    *,
    open_questions: Optional[Iterable[Dict[str, Any]]] = None,
    plan_structure: Optional[Dict[str, Any]] = None,
) -> str:
    """Fixed-section Visit Report–style sheet (little free synthesis)."""
    from app.services.capture_templates import (
        header_fields_from_plan,
        intervention_type_id_from_header,
    )

    plan = session.plan or {}
    header = header_fields_from_plan(plan)
    snapshot = plan.get("capture_template") if isinstance(plan.get("capture_template"), dict) else {}
    intervention_type = intervention_type_id_from_header(header) or str(
        snapshot.get("intervention_type") or ""
    ).strip()
    doc_ref = str(snapshot.get("doc_ref") or "").strip()
    type_label = str(snapshot.get("intervention_type_label") or intervention_type or "").strip()
    facts = [fact for fact in captured_facts if (fact.get("text") or "").strip()]
    question_lines = _open_question_lines(open_questions or [])

    cartouche = _fse_cartouche_table(
        header,
        issued_by=(session.expert_profile or "Expert métier").strip(),
        type_label=type_label,
        doc_ref=doc_ref,
    )
    hse_section = _fse_hse_chapter(header)
    sections: List[str] = [
        f"# Rapport d'intervention FSE — {session.title}",
        f"## Cartouche\n{cartouche}",
        hse_section,
    ]
    # EX70 003 (field service) has no equipment progress table.
    if intervention_type != "field_service":
        sections.append(_fse_equipment_progress_table(header))
    sections.append(_fse_site_modifications_section(header))
    sections.append(
        "## Sujets\n"
        + _fse_subject_sections(
            session,
            facts,
            intervention_type=intervention_type,
            plan_structure=plan_structure,
        )
    )
    markdown = "\n\n".join(sections) + "\n"
    if question_lines:
        markdown += "\n## Questions ouvertes (bloquantes)\n" + "\n".join(question_lines) + "\n"
    return markdown


def _fse_option_label(options: List[Dict[str, Any]], value: str) -> str:
    for opt in options:
        if str(opt.get("value") or "").strip() == value:
            label = str(opt.get("label") or "").strip()
            if label:
                return label
    return value


def _fse_display(
    value: Any,
    *,
    empty: str = "À compléter",
    options: Optional[List[Dict[str, Any]]] = None,
) -> str:
    if value is None:
        return empty
    if isinstance(value, list):
        parts = [str(item).strip() for item in value if str(item).strip()]
        if options:
            parts = [_fse_option_label(options, part) for part in parts]
        return ", ".join(parts) if parts else empty
    if isinstance(value, dict):
        selected = value.get("selected") or value.get("values")
        if isinstance(selected, list):
            parts = [str(item).strip() for item in selected if str(item).strip()]
            if options:
                parts = [_fse_option_label(options, part) for part in parts]
            desc = str(value.get("description") or "").strip()
            base = ", ".join(parts) if parts else empty
            return f"{base} — {desc}" if desc else base
        return empty
    text = str(value).strip()
    if text and options:
        return _fse_option_label(options, text)
    return text or empty


def _fse_cartouche_table(
    header: Dict[str, Any],
    *,
    issued_by: str,
    type_label: str,
    doc_ref: str,
) -> str:
    from app.services.capture_templates import _DISTRIBUTION_OPTIONS

    issued = str(header.get("issued_by") or "").strip() or issued_by
    distribution = _fse_display(header.get("distribution"), options=list(_DISTRIBUTION_OPTIONS))
    rows = [
        ("Type d'intervention", type_label or "À compléter"),
        ("Réf. qualité", doc_ref or "—"),
        ("Client", _fse_display(header.get("customer"))),
        ("Pays", _fse_display(header.get("country"))),
        ("Site / machine", _fse_display(header.get("site_or_machine"))),
        ("Référence", _fse_display(header.get("reference"))),
        ("Participants", _fse_display(header.get("participants"))),
        ("Date d'intervention", _fse_display(header.get("intervention_date"))),
        ("Semaine", _fse_display(header.get("week"), empty=_fse_display(header.get("intervention_date")))),
        ("Diffusion", distribution),
        ("Émis par", issued or "À compléter"),
    ]
    lines = [
        "| Champ | Valeur |",
        "| --- | --- |",
        *[f"| **{label}** | {value} |" for label, value in rows],
    ]
    return "\n".join(lines)


def _fse_hse_chapter(header: Dict[str, Any]) -> str:
    from app.services.capture_templates import HSE_SAFETY_DEFAULT

    hse = _fse_display(header.get("hse_safety"), empty=HSE_SAFETY_DEFAULT)
    nothing = hse.strip().lower() in {
        HSE_SAFETY_DEFAULT.lower(),
        "none",
        "rien à signaler",
        "rien a signaler",
    }
    # Institutional EX70 default when nothing happened; otherwise point to the
    # synthesis rather than inventing sub-counts.
    detail = "None" if nothing else "Voir synthèse HSE"
    return (
        "## 1. HSE — Health Safety and Environment\n"
        f"- **Synthèse HSE** : {hse}\n"
        f"- **Incidents (new/total)** : {detail}\n"
        f"- **Accidents (new/total)** : {detail}\n"
        f"- **Safety deviation** : {detail}\n"
        f"- **Environmental measures & deviation** : {detail}"
    )


def _fse_equipment_progress_table(header: Dict[str, Any]) -> str:
    from app.services.capture_templates import equipment_progress_rows

    rows = equipment_progress_rows(header.get("progress"))
    lines = [
        "## Avancement par équipement",
        "| Équipement | % | Problem / Risk | Measure | Responsible |",
        "| --- | --- | --- | --- | --- |",
    ]
    if not rows:
        lines.append("| À compléter | — | — | — | — |")
        return "\n".join(lines)
    for row in rows:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row.get("equipment") or "—").strip() or "—",
                    str(row.get("percent") if row.get("percent") is not None else "—").strip() or "—",
                    str(row.get("problem_risk") or "—").strip() or "—",
                    str(row.get("measure") or "—").strip() or "—",
                    str(row.get("responsible") or "—").strip() or "—",
                ]
            )
            + " |"
        )
    return "\n".join(lines)


def _fse_site_modifications_section(header: Dict[str, Any]) -> str:
    from app.services.capture_templates import (
        _SITE_MODIFICATION_OPTIONS,
        checkbox_group_payload,
    )

    selected, description = checkbox_group_payload(header.get("site_modifications"))
    declared = (
        ", ".join(_fse_option_label(list(_SITE_MODIFICATION_OPTIONS), item) for item in selected)
        if selected
        else "Non déclaré"
    )
    lines = [
        "## Modifications sur site",
        f"- **Déclaration** : {declared}",
    ]
    if description:
        lines.append(f"- **Description** : {description}")
    elif selected and selected != ["none"]:
        lines.append("- **Description** : À compléter")
    return "\n".join(lines)


def _fse_subject_sections(
    session: ExpertCaptureSession,
    facts: List[Dict[str, Any]],
    *,
    intervention_type: str = "",
    plan_structure: Optional[Dict[str, Any]] = None,
) -> str:
    topics = [topic for topic in (session.plan or {}).get("topics") or [] if isinstance(topic, dict)]
    if not topics:
        return _bullet_lines(facts, "Aucun sujet capturé.")

    field_service = intervention_type == "field_service"
    lines: List[str] = []
    assigned: set[int] = set()
    for index, topic in enumerate(topics, start=1):
        topic_id = str(topic.get("id") or index)
        topic_title = str(topic.get("title") or f"Sujet {index}").strip()
        lines.append(f"### {index}. {topic_title}")
        subtopics = [item for item in topic.get("subtopics") or [] if isinstance(item, dict)]
        if subtopics:
            for sub_index, subtopic in enumerate(subtopics, start=1):
                subtopic_id = str(subtopic.get("id") or f"{topic_id}.{sub_index}")
                subtopic_title = str(subtopic.get("title") or f"Point {sub_index}").strip()
                sub_facts = _facts_for_plan_node(
                    facts,
                    topic_id=topic_id,
                    subtopic_id=subtopic_id,
                    title=subtopic_title,
                )
                for fact_index, _fact in sub_facts:
                    assigned.add(fact_index)
                lines.append(f"- **{subtopic_title}** : {_fse_inline_fact_text(sub_facts)}")
        else:
            topic_facts = _facts_for_plan_node(
                facts,
                topic_id=topic_id,
                subtopic_id=None,
                title=topic_title,
            )
            for fact_index, _fact in topic_facts:
                assigned.add(fact_index)
            lines.append(f"- {_fse_inline_fact_text(topic_facts)}")
        if field_service:
            # Explicit Day / Concern / Action by-until framing for field service.
            lines.append(
                "- **Cadre** : Constat / Action / Responsable / Échéance "
                "(Day · Concern · Action by-until · as Info to)"
            )
        lines.append("")

    # Prefer filtered hors-plan from structure_capture_payload when available.
    if isinstance(plan_structure, dict) and "unassigned" in plan_structure:
        unassigned = [
            fact
            for fact in (plan_structure.get("unassigned") or [])
            if isinstance(fact, dict) and str(fact.get("text") or "").strip()
        ]
    else:
        unassigned = [fact for fact_index, fact in enumerate(facts) if fact_index not in assigned]
    if unassigned:
        lines.append("### Points hors plan")
        lines.extend(_fact_bullets(unassigned))
    return "\n".join(lines).strip()


def _fse_inline_fact_text(facts: List[tuple[int, Dict[str, Any]]]) -> str:
    texts = [
        str(fact.get("text") or fact.get("statement") or "").strip()
        for _index, fact in facts
        if str(fact.get("text") or fact.get("statement") or "").strip()
    ]
    return " ; ".join(texts) if texts else "À compléter."


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
