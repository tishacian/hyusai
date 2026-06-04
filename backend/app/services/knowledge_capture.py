"""Expert knowledge capture planning, session runtime and review output."""
from __future__ import annotations

import re
import asyncio
import json
import logging
import tempfile
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote

from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy.orm import Session as DBSession

from app.models.capability import Capability
from app.models.context import Context
from app.models.expert_capture import (
    ExpertCaptureEvent,
    ExpertCaptureSession,
    KnowledgeUpdateProposal,
)
from app.models.run import Run, SkillInvocation
from app.models.system import System
from app.services.audit_logger import emit_audit_event
from app.services.capture_knowledge_oracle import (
    CaptureSessionContext,
    analyze_plan_oracle_async,
    evaluate_capture_partial,
    generate_question_bank_entry_async,
    broad_presentation_prompt,
    merge_topic_proposals,
    normalize_outline_points,
    plan_dialogue_probe,
    presentation_prompt,
    score_gaps_with_rag,
    session_context_from_capture,
    _model_chat_kwargs,
    _resolve_llm_config,
)

CAPABILITY_SLUG = "expert_knowledge_capture"
TOPIC_PLAN_SCHEMA_VERSION = "topic_plan_v1"
FREE_CONVERSATION_SCHEMA_VERSION = "free_conversation_v1"
PLAN_BUILD_SCHEMA_VERSION = "plan_build_v1"
PLAN_BUILD_V2_SCHEMA_VERSION = "plan_build_v2"
PLAN_BUILD_SCHEMA_VERSIONS = frozenset({PLAN_BUILD_SCHEMA_VERSION, PLAN_BUILD_V2_SCHEMA_VERSION})
VALID_PLAN_MODES = frozenset({"ai_plan", "provided_plan", "free_conversation", "plan_build"})
_PLAN_DIALOGUE_STEPS = (
    "Collez ou dictez le plan à suivre. Je garde vos rubriques et votre ordre, sans ajouter d'axes non demandés.",
    "Ajoutez seulement les rubriques manquantes ou les sous-parties à intégrer.",
    "Précisez les cas concrets, exceptions terrain ou décisions difficiles à rattacher au plan.",
)
_MIN_PLAN_DIALOGUE_TURNS = 1
_MIN_PLAN_SUBJECT_CHARS = 12
RETRIEVAL_PREFETCH_TIMEOUT_SECONDS = 2.5
ORACLE_QUESTION_STATUSES = frozenset({"open", "active", "answered", "dismissed", "deferred", "addressed"})
PROPOSAL_OPEN_QUESTION_STATUSES = frozenset({"open", "dismissed", "deferred"})

_logger = logging.getLogger(__name__)
POSITIVE_CONFIRMATION_TERMS = (
    "oui",
    "valide",
    "confirme",
    "c'est bon",
    "c est bon",
    "go",
    "accept",
)
FINAL_ACCEPTANCE_TERMS = (
    "oui valide",
    "je valide",
    "valide",
    "validation finale",
    "j'accepte",
    "j accepte",
    "accepte",
    "accept",
)
NEGATIVE_CONFIRMATION_TERMS = (
    "non",
    "attends",
    "corrige",
    "pas encore",
)
PROPOSAL_REQUEST_TERMS = (
    "synthèse",
    "synthese",
    "proposition",
    "crée la proposition",
    "cree la proposition",
    "créer la proposition",
    "creer la proposition",
    "prépare la proposition",
    "prepare la proposition",
    "crée proposition",
    "cree proposition",
    "on peut conclure",
)
_STT_HALLUCINATION_TERMS = (
    "пентак",
    "сексуаль",
    "карты",
    "масти",
    "выпадает",
)
SESSION_END_TERMS = (
    "c'est terminé",
    "c est terminé",
    "c'est termine",
    "c est termine",
    "session terminée",
    "session terminee",
    "on a fini",
    "c'est fini",
    "c est fini",
    "on termine",
)
SESSION_EXTENSION_MINUTES = 15
SESSION_LAST_MINUTES_ALERT = 5
CORRECTION_TERMS = (
    "correction",
    "en fait",
    "je corrige",
    "plutôt",
    "plutot",
    "remplace",
)
MORE_DETAIL_TERMS = (
    "ajoute",
    "complète",
    "complete",
    "je précise",
    "je precise",
    "plus de détail",
    "plus de detail",
)
VOICE_CONTROL_TERMS = (
    "attends",
    "attend",
    "arrête-toi",
    "arrete-toi",
    "arrête toi",
    "arrete toi",
    "stop",
    "je ne comprends pas ce que tu fais",
)
DEFER_VOCAL_TERMS = (
    "je traiterai plus tard",
    "je traiterais plus tard",
    "pas maintenant",
    "pas pour l'instant",
    "pas pour linstant",
    "on verra en fin de session",
    "en fin de session",
    "on verra plus tard",
    "plus tard",
    "reporter",
    "reporte",
    "on reprendra",
)
LEADING_DISCOURSE_MARKERS = (
    "ok",
    "okay",
    "donc",
    "euh",
    "heu",
    "hum",
    "alors",
    "maintenant",
)
BUSINESS_EVENT_TYPES = {
    "capture_plan_created",
    "capture_session_started",
    "expert_turn_finalized",
    "transcript_amended",
    "conversation_intent_detected",
    "proposal_generated",
    "proposal_reviewed",
    "ai_speech_interrupted",
}

_BASE_GAPS = [
    {
        "slug": "decision_rationale",
        "title": "Decision rationale",
        "description": "Capture why an expert chooses one action, parameter, offer, or diagnosis over another.",
        "priority": 0.95,
    },
    {
        "slug": "exception_handling",
        "title": "Exceptions and edge cases",
        "description": "Identify cases where the documented process is insufficient or misleading.",
        "priority": 0.88,
    },
    {
        "slug": "signals_and_symptoms",
        "title": "Tacit signals",
        "description": "Elicit sensory, operational, customer, or machine signals experts use but documents rarely capture.",
        "priority": 0.82,
    },
    {
        "slug": "source_provenance",
        "title": "Source provenance",
        "description": "Clarify which document, dataset, person, or field evidence supports the expert answer.",
        "priority": 0.76,
    },
    {
        "slug": "validation_and_ownership",
        "title": "Validation and ownership",
        "description": "Define who can validate the captured knowledge and when it should be revisited.",
        "priority": 0.70,
    },
    {
        "slug": "open_questions",
        "title": "Remaining unknowns",
        "description": "Make missing documents, missing data, and unresolved assumptions explicit.",
        "priority": 0.64,
    },
]

_TOPIC_GROUPS = [
    {
        "id": "topic-01",
        "title": "Décisions et arbitrages métier",
        "objective": "Capturer les décisions expertes difficiles à retrouver dans les documents.",
        "slugs": ["decision_rationale", "exception_handling"],
    },
    {
        "id": "topic-02",
        "title": "Signaux terrain et diagnostic",
        "objective": "Relier symptômes, signaux faibles et raisonnement de diagnostic.",
        "slugs": ["signals_and_symptoms"],
    },
    {
        "id": "topic-03",
        "title": "Preuves documentaires et sources",
        "objective": "Identifier les documents, traces et preuves qui valident la connaissance.",
        "slugs": ["source_provenance"],
    },
    {
        "id": "topic-04",
        "title": "Validation et intégration Knowledge",
        "objective": "Préparer la revue humaine, les zones d'incertitude et l'intégration en base.",
        "slugs": ["validation_and_ownership", "open_questions"],
    },
]


def _words(text: str) -> List[str]:
    return re.findall(r"[\wÀ-ÿ'-]+", text or "")


def _context_snapshot(ctx: Optional[Context]) -> Dict[str, Any]:
    if not ctx:
        return {}
    return {
        "id": ctx.id,
        "name": ctx.name,
        "data_refs": ctx.data_refs or [],
        "memory_refs": ctx.memory_refs or [],
        "history_refs": ctx.history_refs or [],
        "environment_state": ctx.environment_state or {},
        "business_constraints": ctx.business_constraints or {},
        "permissions": ctx.permissions or {},
    }


def build_knowledge_gaps(
    *,
    objective: str,
    expert_profile: Optional[str] = None,
    context_snapshot: Optional[Dict[str, Any]] = None,
    knowledge_refs: Optional[List[str]] = None,
    rag_chunks: Optional[List[str]] = None,
    rag_metadatas: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Return prioritized gaps to resolve during an expert capture session.

    The Phase 0 implementation is deterministic so demos remain robust even
    without an LLM key. It can later be augmented by RAG/LLM scoring while
    keeping the same contract.
    """
    context_snapshot = context_snapshot or {}
    knowledge_refs = knowledge_refs or []
    objective_l = (objective or "").lower()
    expert_l = (expert_profile or "").lower()
    refs = [
        *context_snapshot.get("data_refs", []),
        *context_snapshot.get("memory_refs", []),
        *context_snapshot.get("history_refs", []),
        *knowledge_refs,
    ]

    gaps: List[Dict[str, Any]] = []
    for index, template in enumerate(_BASE_GAPS, start=1):
        priority = float(template["priority"])
        if template["slug"] in {"decision_rationale", "signals_and_symptoms"} and any(
            token in objective_l for token in ("expert", "capture", "diagnostic", "troubleshoot", "maintenance")
        ):
            priority += 0.05
        if template["slug"] == "source_provenance" and refs:
            priority += 0.03
        if template["slug"] == "validation_and_ownership" and any(
            token in expert_l for token in ("senior", "lead", "owner", "manager")
        ):
            priority += 0.02

        gaps.append(
            {
                "id": f"gap-{index:02d}-{template['slug']}",
                "slug": template["slug"],
                "title": template["title"],
                "description": template["description"],
                "priority": round(min(priority, 1.0), 2),
                "status": "open",
                "evidence_refs": refs[:5],
            }
        )
    if rag_chunks:
        return score_gaps_with_rag(gaps, rag_chunks, rag_metadatas=rag_metadatas)
    return sorted(gaps, key=lambda item: item["priority"], reverse=True)


def build_interview_plan(
    *,
    objective: str,
    expert_profile: Optional[str],
    duration_minutes: int,
    gaps: List[Dict[str, Any]],
    context_snapshot: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    duration = _planning_duration_minutes(int(duration_minutes or 20), int(duration_minutes or 20) <= 0)
    available_question_minutes = max(3, duration - 4)
    question_count = max(2, min(len(gaps), available_question_minutes // 3 or 2))
    selected = gaps[:question_count]
    per_question = max(2, available_question_minutes // max(1, len(selected)))

    selected_by_slug = {gap.get("slug"): gap for gap in selected}
    topics: List[Dict[str, Any]] = []
    question_index = 1
    for topic_index, group in enumerate(_TOPIC_GROUPS, start=1):
        grouped_gaps = [selected_by_slug[slug] for slug in group["slugs"] if slug in selected_by_slug]
        if not grouped_gaps:
            continue
        subtopics: List[Dict[str, Any]] = []
        for subtopic_index, gap in enumerate(grouped_gaps, start=1):
            topic_id = group["id"]
            subtopic_id = f"{topic_id}-sub-{subtopic_index:02d}"
            path_label = f"{group['title']} / {gap['title']}"
            question = {
                "id": f"q-{question_index:02d}",
                "target_gap_id": gap["id"],
                "topic_id": topic_id,
                "subtopic_id": subtopic_id,
                "path_label": path_label,
                "title": gap["title"],
                "question": _question_for_gap(gap, objective, context_snapshot),
                "follow_ups": _followups_for_gap(gap),
                "estimated_minutes": per_question,
                "completion_criteria": [
                    "answer names a concrete situation or decision",
                    "answer explains the why, not only the what",
                    "answer identifies evidence, owner, or validation path when possible",
                ],
            }
            subtopics.append(
                {
                    "id": subtopic_id,
                    "title": gap["title"],
                    "objective": gap.get("description"),
                    "target_gap_ids": [gap["id"]],
                    "knowledge_refs": _knowledge_refs_for_topic(context_snapshot, [gap]),
                    "questions": [question],
                }
            )
            question_index += 1
        topics.append(
            {
                "id": group["id"],
                "title": group["title"],
                "objective": group["objective"],
                "estimated_minutes": sum(
                    int(q.get("estimated_minutes") or per_question)
                    for subtopic in subtopics
                    for q in subtopic.get("questions", [])
                ),
                "knowledge_refs": _knowledge_refs_for_topic(context_snapshot, grouped_gaps),
                "subtopics": subtopics,
            }
        )

    plan = {
        "schema_version": TOPIC_PLAN_SCHEMA_VERSION,
        "objective": objective,
        "expert_profile": expert_profile,
        "duration_minutes": duration,
        "voice_runtime": "cascade_openai",
        "agenda": [
            {"label": "Frame objective and scope", "estimated_minutes": 2},
            {"label": "Resolve prioritized knowledge gaps", "estimated_minutes": available_question_minutes},
            {"label": "Confirm open questions and validation owner", "estimated_minutes": 2},
        ],
        "topics": topics,
        "questions": [],
        "context": context_snapshot or {},
        "review": {
            "status": "draft",
            "revision": 1,
            "created_at": datetime.utcnow().isoformat(),
            "approved_at": None,
            "approved_by_user_id": None,
        },
        "success_metrics": [
            "coverage of prioritized gaps",
            "number of usable captured facts",
            "manual transcript correction rate",
            "estimated vs actual duration",
        ],
    }
    plan["questions"] = _flatten_plan_questions(plan)
    return plan


def _free_conversation_plan(
    *,
    objective: str,
    expert_profile: Optional[str],
    duration_minutes: int,
    context_snapshot: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Create a capture plan that deliberately contains no interviewer agenda."""
    return {
        "schema_version": FREE_CONVERSATION_SCHEMA_VERSION,
        "mode": "free_conversation",
        "objective": objective,
        "expert_profile": expert_profile,
        "duration_minutes": duration_minutes,
        "voice_runtime": "cascade_openai",
        "knowledge_target": _knowledge_target_for_prompt(context_snapshot),
        "agenda": [],
        "topics": [],
        "questions": [],
        "context": context_snapshot or {},
        "review": {"status": "not_required", "reason": "free_conversation"},
        "capture_policy": {
            "planned_questions": False,
            "coverage_metric": False,
            "expert_controls_flow": True,
        },
        "success_metrics": [
            "substantive expert facts captured",
            "manual transcript correction rate",
            "reviewable proposal quality",
        ],
    }


def _normalize_duration_minutes(duration_minutes: Optional[int]) -> Tuple[int, bool]:
    """Return stored minutes and whether the session has no time limit."""
    if duration_minutes is None:
        return 0, True
    value = int(duration_minutes)
    if value <= 0:
        return 0, True
    return max(5, min(value, 90)), False


def _planning_duration_minutes(stored_minutes: int, unlimited: bool) -> int:
    if unlimited or stored_minutes <= 0:
        return 60
    return stored_minutes


def _session_unlimited_duration(session: ExpertCaptureSession) -> bool:
    metrics = session.metrics or {}
    if metrics.get("unlimited_duration"):
        return True
    plan = session.plan or {}
    if plan.get("unlimited_duration"):
        return True
    return int(session.duration_minutes or 0) <= 0


def _session_effective_duration_minutes(session: ExpertCaptureSession) -> int:
    if _session_unlimited_duration(session):
        return 0
    extension = int((session.metrics or {}).get("duration_extension_minutes") or 0)
    return max(5, int(session.duration_minutes or 0) + extension)


def _session_elapsed_seconds(session: ExpertCaptureSession, *, now: Optional[datetime] = None) -> int:
    if not session.started_at:
        return 0
    reference = now or datetime.utcnow()
    elapsed = max(0, int((reference - session.started_at).total_seconds()))
    paused_at = (session.metrics or {}).get("paused_at")
    if paused_at and session.status == "paused":
        try:
            paused_ts = datetime.fromisoformat(str(paused_at))
            elapsed = max(0, int((paused_ts - session.started_at).total_seconds()))
        except ValueError:
            pass
    return elapsed


def _compute_timer_metrics(session: ExpertCaptureSession, *, now: Optional[datetime] = None) -> Dict[str, Any]:
    unlimited = _session_unlimited_duration(session)
    effective_minutes = _session_effective_duration_minutes(session)
    elapsed_seconds = _session_elapsed_seconds(session, now=now)
    if session.status not in {"active", "paused"} or not session.started_at:
        return {
            "unlimited_duration": unlimited,
            "duration_limit_minutes": 0 if unlimited else effective_minutes,
            "duration_extension_minutes": int((session.metrics or {}).get("duration_extension_minutes") or 0),
            "elapsed_seconds": elapsed_seconds,
            "remaining_seconds": None,
            "timer_phase": "inactive",
            "session_end_pending": False,
            "last_minutes_alert": False,
        }
    if unlimited:
        return {
            "unlimited_duration": True,
            "duration_limit_minutes": 0,
            "duration_extension_minutes": int((session.metrics or {}).get("duration_extension_minutes") or 0),
            "elapsed_seconds": elapsed_seconds,
            "remaining_seconds": None,
            "timer_phase": "running",
            "session_end_pending": False,
            "last_minutes_alert": False,
        }
    limit_seconds = effective_minutes * 60
    remaining_seconds = max(0, limit_seconds - elapsed_seconds)
    alert_seconds = SESSION_LAST_MINUTES_ALERT * 60
    if remaining_seconds <= 0:
        timer_phase = "ended"
    elif remaining_seconds <= alert_seconds:
        timer_phase = "last_5_minutes"
    else:
        timer_phase = "running"
    return {
        "unlimited_duration": False,
        "duration_limit_minutes": effective_minutes,
        "duration_extension_minutes": int((session.metrics or {}).get("duration_extension_minutes") or 0),
        "elapsed_seconds": elapsed_seconds,
        "remaining_seconds": remaining_seconds,
        "timer_phase": timer_phase,
        "session_end_pending": bool((session.metrics or {}).get("session_end_pending")) or timer_phase == "ended",
        "last_minutes_alert": timer_phase == "last_5_minutes",
    }


def _resolve_capture_context(
    db: DBSession,
    *,
    workspace_id: str,
    context_id: Optional[str],
) -> Tuple[Optional[str], Optional[Context]]:
    if context_id:
        ctx = _load_context(db, workspace_id, context_id)
        return context_id, ctx
    ctx = (
        db.query(Context)
        .filter(Context.workspace_id == workspace_id)
        .order_by(Context.updated_at.desc())
        .first()
    )
    return (ctx.id if ctx else None), ctx


def _content_tokens(text: str) -> set[str]:
    return {token.lower() for token in _words(text) if len(token) >= 4}


def _outline_indent_level(indent_stack: List[int], indent: int) -> int:
    """Resolve a 0-based depth for ``indent`` against a running indent stack.

    Deeper leading whitespace pushes a new level; equal whitespace stays on the
    same level; shallower whitespace pops back. Used for indentation-driven
    pastes (bullets / plain lines), independent of markdown/numbering markers.
    """
    while indent_stack and indent < indent_stack[-1]:
        indent_stack.pop()
    if indent_stack and indent == indent_stack[-1]:
        return len(indent_stack) - 1
    indent_stack.append(indent)
    return len(indent_stack) - 1


_PLAN_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$")
_PLAN_DOTTED_RE = re.compile(r"^(\d+(?:\.\d+)+)[.)]?\s+(.+)$")
_PLAN_NUMBER_RE = re.compile(r"^\d+[.)]\s+(.+)$")
_PLAN_BULLET_RE = re.compile(r"^[-*•·▪◦]\s+(.+)$")
_PLAN_ALPHA_RE = re.compile(r"^[a-zA-Z][.)]\s+(.+)$")


def _outline_items_from_text(seed: str) -> List[Tuple[int, str]]:
    """Turn raw plan text into ``(level, title)`` rows (level 0 = top section).

    Honors, in order of precedence: markdown heading depth (#, ##, ### ...),
    nested numbering (1 / 1.1 / 1.1.1), and leading-whitespace indentation for
    bullets / plain lines. Bullets and plain lines nest one level under the most
    recent explicit marker so mixed documents (## heading + "- point") work.
    """
    items: List[Tuple[int, str]] = []
    indent_stack: List[int] = []
    last_marker_level = -1
    for raw_line in seed.splitlines():
        if not raw_line.strip():
            continue
        expanded = raw_line.replace("\t", "    ")
        indent = len(expanded) - len(expanded.lstrip(" "))
        line = raw_line.strip()

        heading = _PLAN_HEADING_RE.match(line)
        if heading:
            level = len(heading.group(1)) - 1
            items.append((level, heading.group(2).strip()))
            last_marker_level = level
            indent_stack = []
            continue

        dotted = _PLAN_DOTTED_RE.match(line)
        if dotted:
            level = dotted.group(1).count(".")
            items.append((level, dotted.group(2).strip()))
            last_marker_level = level
            indent_stack = []
            continue

        numbered = _PLAN_NUMBER_RE.match(line)
        if numbered:
            # A plain enumerator ("1." / "2)") is a top-level section; deeper
            # numbering is expressed with dots (1.1 / 1.1.1), handled above.
            items.append((0, numbered.group(1).strip()))
            last_marker_level = 0
            indent_stack = []
            continue

        alpha = _PLAN_ALPHA_RE.match(line)
        if alpha:
            items.append((1, alpha.group(1).strip()))
            last_marker_level = 1
            indent_stack = []
            continue

        bullet = _PLAN_BULLET_RE.match(line)
        title = bullet.group(1).strip() if bullet else line[:240]

        relative = _outline_indent_level(indent_stack, indent)
        level = max(0, last_marker_level + 1) + relative if last_marker_level >= 0 else relative
        items.append((level, title))
    return items


def parse_provided_plan_text(text: str) -> List[Dict[str, Any]]:
    """Parse pasted or uploaded plan text into a 3-level plan_build_v2 tree.

    Level 0 -> topic (section), level 1 -> subtopic (subsection), level >= 2 ->
    presentation point (subtopic.questions). Leading-whitespace indentation,
    nested markdown headings and nested numbering are all honored, so a richly
    structured paste keeps its hierarchy instead of collapsing to one topic.
    """
    seed = (text or "").strip()
    if not seed:
        return []

    items = _outline_items_from_text(seed)
    topics: List[Dict[str, Any]] = []
    current_topic: Optional[Dict[str, Any]] = None
    current_sub: Optional[Dict[str, Any]] = None
    topic_index = 0

    def _new_topic(title: str) -> Dict[str, Any]:
        nonlocal topic_index, current_topic, current_sub
        topic_index += 1
        current_topic = {
            "id": f"t-{topic_index:02d}",
            "title": title.strip() or f"Sujet {topic_index}",
            "objective": "",
            "status": "draft",
            "knowledge_refs": [],
            "subtopics": [],
        }
        current_sub = None
        topics.append(current_topic)
        return current_topic

    def _new_subtopic(title: str) -> Dict[str, Any]:
        nonlocal current_sub
        assert current_topic is not None
        sub_index = len(current_topic["subtopics"]) + 1
        current_sub = {
            "id": f"{current_topic['id']}-sub-{sub_index:02d}",
            "title": title.strip() or current_topic["title"],
            "objective": "",
            "status": "pending",
            "questions": [],
        }
        current_topic["subtopics"].append(current_sub)
        return current_sub

    def _add_point(title: str) -> None:
        assert current_sub is not None
        point_index = len(current_sub["questions"]) + 1
        clean = title.strip()
        current_sub["questions"].append(
            {
                "id": f"{current_sub['id']}-pt-{point_index:02d}",
                "title": clean,
                "prompt": presentation_prompt(clean),
                "status": "pending",
            }
        )

    for level, title in items:
        if not title:
            continue
        if level <= 0:
            _new_topic(title)
        elif level == 1:
            if current_topic is None:
                _new_topic(title)
            else:
                _new_subtopic(title)
        else:  # level >= 2 -> presentation point
            if current_topic is None:
                _new_topic(title)
            elif current_sub is None:
                _new_subtopic(current_topic["title"])
                _add_point(title)
            else:
                _add_point(title)

    # Every topic needs at least one subtopic for downstream normalization.
    for topic in topics:
        if not topic["subtopics"]:
            topic["subtopics"].append(
                {
                    "id": f"{topic['id']}-sub-01",
                    "title": topic["title"],
                    "objective": "",
                    "status": "pending",
                    "questions": [],
                }
            )

    if not topics and len(_words(seed)) >= 6:
        topics.append(
            {
                "id": "t-01",
                "title": "Plan importé",
                "objective": seed[:240],
                "status": "draft",
                "knowledge_refs": [],
                "subtopics": [
                    {
                        "id": "t-01-sub-01",
                        "title": "Sujet principal",
                        "objective": seed[:500],
                        "status": "pending",
                        "questions": [],
                    }
                ],
            }
        )
    return topics


def _apply_provided_plan_seed(plan: Dict[str, Any], seed: Optional[str]) -> Dict[str, Any]:
    clean_seed = (seed or "").strip()
    if not clean_seed:
        return plan
    parsed = parse_provided_plan_text(clean_seed)
    if not parsed:
        return plan
    plan["topics"] = parsed
    dialogue = dict(plan.get("dialogue") or {})
    dialogue["ready_to_finalize"] = True
    dialogue["status"] = "seed_parsed"
    plan["dialogue"] = dialogue
    plan["review"] = {**(plan.get("review") or {}), "status": "draft", "reason": "provided_plan_seed"}
    return plan


def _normalize_plan_source_kind(kind: Optional[str], *, has_seed: bool, filename: Optional[str]) -> str:
    clean = (kind or "").strip().lower()
    if clean in {"manual", "pasted_text", "uploaded_file", "conversation"}:
        return clean
    if filename:
        return "uploaded_file"
    if has_seed:
        return "pasted_text"
    return "manual"


def _outline_from_plan_topics(topics: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    outline: List[Dict[str, Any]] = []
    for topic in topics[:80]:
        title = str(topic.get("title") or "").strip()
        if not title:
            continue
        subtopics = []
        for subtopic in (topic.get("subtopics") or [])[:80]:
            subtitle = str(subtopic.get("title") or "").strip()
            if subtitle:
                subtopics.append(subtitle)
        outline.append({"title": title, "subtopics": subtopics})
    return outline


def _attach_plan_source_metadata(
    plan: Dict[str, Any],
    *,
    kind: Optional[str],
    filename: Optional[str],
    seed: Optional[str],
    replaces_existing_plan: bool = False,
) -> Dict[str, Any]:
    clean_seed = (seed or "").strip()
    if not clean_seed and not filename:
        return plan
    source_kind = _normalize_plan_source_kind(kind, has_seed=bool(clean_seed), filename=filename)
    metadata: Dict[str, Any] = {
        "kind": source_kind,
        "filename": (filename or "").strip() or None,
        "extracted_outline": _outline_from_plan_topics(plan.get("topics") or []),
        "replaces_existing_plan": bool(replaces_existing_plan),
    }
    metadata["chars"] = len(clean_seed)
    metadata["line_count"] = len([line for line in clean_seed.splitlines() if line.strip()])
    plan["plan_source"] = metadata
    return plan


def _plan_build_shell(
    *,
    objective: str,
    expert_profile: Optional[str],
    duration_minutes: int,
    unlimited_duration: bool,
    context_snapshot: Optional[Dict[str, Any]],
    provided_seed: Optional[str] = None,
) -> Dict[str, Any]:
    seed = (provided_seed or "").strip()
    return {
        "schema_version": PLAN_BUILD_V2_SCHEMA_VERSION,
        "mode": "plan_build",
        "objective": objective,
        "expert_profile": expert_profile,
        "duration_minutes": duration_minutes,
        "unlimited_duration": unlimited_duration,
        "voice_runtime": "cascade_openai",
        "knowledge_target": _knowledge_target_for_prompt(context_snapshot),
        "agenda": [],
        "topics": [],
        "questions": [],
        "question_bank": [],
        "question_bank_status": "idle",
        "hint_queue": {},
        "context": context_snapshot or {},
        "dialogue": {
            "turns": [],
            "status": "in_progress",
            "provided_seed": seed,
            "ready_to_finalize": bool(seed and len(_words(seed)) >= 12),
        },
        "review": {"status": "draft", "reason": "plan_build"},
        "capture_policy": {
            "planned_questions": True,
            "coverage_metric": True,
            "expert_controls_flow": True,
            "visible_interview_questions": False,
        },
    }


def _dialogue_subject_text(plan: Dict[str, Any]) -> str:
    dialogue = plan.get("dialogue") or {}
    parts = [str(dialogue.get("provided_seed") or "").strip()]
    for turn in dialogue.get("turns") or []:
        text = str(turn.get("text") or "").strip()
        if text:
            parts.append(text)
    return " ".join(part for part in parts if part).strip()


def _plan_dialogue_ready(plan: Dict[str, Any]) -> bool:
    dialogue = plan.get("dialogue") or {}
    if dialogue.get("ready_to_finalize"):
        return True
    # A plan is ready to finalize as soon as it has at least one topic — the
    # dialogue turn already builds the topic tree. This aligns the backend gate
    # with the frontend (planTopics().length > 0) and supersedes the legacy
    # word-count threshold below, which now only acts as an oracle-fallback hint
    # when no topics have been produced yet.
    if plan.get("topics"):
        return True
    turns = dialogue.get("turns") or []
    subject = _dialogue_subject_text(plan)
    return len(turns) >= _MIN_PLAN_DIALOGUE_TURNS and len(_words(subject)) >= _MIN_PLAN_SUBJECT_CHARS


def _next_plan_dialogue_prompt(plan: Dict[str, Any]) -> Optional[str]:
    turns = (plan.get("dialogue") or {}).get("turns") or []
    if len(turns) >= len(_PLAN_DIALOGUE_STEPS):
        return None
    return _PLAN_DIALOGUE_STEPS[len(turns)]


def _clean_optional_string(value: Any) -> Optional[str]:
    text = str(value or "").strip()
    return text or None


def _normalize_oracle_question_status(value: Any) -> str:
    status = str(value or "open").strip().lower()
    if status == "active":
        return "open"
    if status not in ORACLE_QUESTION_STATUSES:
        return "open"
    return status


def _oracle_question_status_key(
    *,
    question_id: Optional[str],
    question_text: Optional[str],
) -> Optional[str]:
    clean_id = _clean_optional_string(question_id)
    if clean_id:
        return f"id:{clean_id}"
    clean_text = _clean_optional_string(question_text)
    if clean_text:
        return f"text:{clean_text.lower()}"
    return None


def _proposal_open_question_keys(question: Dict[str, Any], index: Optional[int] = None) -> set[str]:
    keys: set[str] = set()
    for field in ("gap_id", "follow_up", "reason"):
        value = _clean_optional_string(question.get(field))
        if value:
            keys.add(value)
            keys.add(value.lower())
    if index is not None:
        keys.add(f"question-{index}")
    return keys


def _normalize_proposal_open_question_status(value: Any) -> str:
    status = str(value or "open").strip().lower()
    if status not in PROPOSAL_OPEN_QUESTION_STATUSES:
        return "open"
    return status


def _stored_oracle_question_status(
    plan: Dict[str, Any],
    *,
    question_id: Optional[str],
    question_text: Optional[str],
) -> Optional[str]:
    statuses = plan.get("oracle_question_statuses") or {}
    if not isinstance(statuses, dict):
        return None
    keys = [
        _oracle_question_status_key(question_id=_clean_optional_string(question_id), question_text=None),
        _oracle_question_status_key(question_id=None, question_text=_clean_optional_string(question_text)),
    ]
    for key in keys:
        if not key:
            continue
        entry = statuses.get(key)
        if isinstance(entry, dict):
            return _normalize_oracle_question_status(entry.get("status"))
        if isinstance(entry, str):
            return _normalize_oracle_question_status(entry)
    return None


def build_quality_backlog(
    session: ExpertCaptureSession,
    events: Optional[List[ExpertCaptureEvent]] = None,
) -> Dict[str, Any]:
    """Map evaluations and capture events to pilot-facing quality lists."""
    defer_weak = bool((session.metrics or {}).get("defer_weak_contradictions"))
    imprecisions: List[Dict[str, Any]] = []
    contradictions: List[Dict[str, Any]] = []
    open_questions: List[Dict[str, Any]] = []
    seen: set[str] = set()

    for evaluation in session.evaluations or []:
        verdict = str(evaluation.get("verdict") or "")
        follow_up = evaluation.get("follow_up")
        item_id = str(evaluation.get("id") or evaluation.get("question_id") or uuid.uuid4())
        if item_id in seen:
            continue
        seen.add(item_id)
        base = {
            "id": item_id,
            "question_id": evaluation.get("question_id"),
            "score": evaluation.get("score"),
            "follow_up": follow_up,
            "status": "open",
            "deferred_reason": None,
        }
        if verdict in {"needs_precision", "partial"}:
            imprecisions.append({**base, "label": follow_up or "Réponse à préciser"})
        elif verdict == "contradiction_or_update":
            severity = "weak" if float(evaluation.get("score") or 0) < 0.45 else "strong"
            if defer_weak and severity == "weak":
                continue
            contradictions.append(
                {
                    **base,
                    "label": follow_up or "Contradiction ou mise à jour à clarifier",
                    "severity": severity,
                }
            )

    for event in events or []:
        meta = event.meta_data or {}
        deferred = meta.get("deferred_reason")
        if deferred and event.event_type in {"quality_item_deferred", "capture_quality_deferred"}:
            label = meta.get("label") or _effective_event_text(event) or "Élément reporté"
            bucket = meta.get("bucket") or "open_questions"
            payload = {
                "id": event.id,
                "label": label,
                "status": "deferred",
                "deferred_reason": deferred,
            }
            if bucket == "contradictions":
                contradictions.append(payload)
            elif bucket == "imprecisions":
                imprecisions.append(payload)
            else:
                open_questions.append(payload)

    plan = session.plan or {}
    for question in plan.get("open_questions") or []:
        if not isinstance(question, dict):
            continue
        label = question.get("follow_up") or question.get("reason") or "Question ouverte"
        status = _stored_oracle_question_status(
            plan,
            question_id=question.get("gap_id") or question.get("id"),
            question_text=label,
        ) or "open"
        if status in {"answered", "dismissed", "addressed"}:
            continue
        open_questions.append(
            {
                "id": question.get("gap_id") or str(uuid.uuid4()),
                "label": label,
                "status": "open" if status == "active" else status,
                "deferred_reason": None,
            }
        )

    return {
        "imprecisions": imprecisions,
        "contradictions": contradictions,
        "open_questions": open_questions,
        "defer_weak_contradictions": defer_weak,
    }


def defer_quality_item(
    db: DBSession,
    *,
    workspace_id: str,
    session_id: str,
    item_id: str,
    bucket: str,
    deferred_reason: str,
    actor_user_id: Optional[str] = None,
) -> Dict[str, Any]:
    session = get_session(db, workspace_id=workspace_id, session_id=session_id)
    reason = (deferred_reason or "end_of_session").strip()
    _record_capture_event(
        db,
        session=session,
        event_type="quality_item_deferred",
        source="operator_edit",
        status="deferred",
        created_by=actor_user_id,
        meta_data={
            "item_id": item_id,
            "bucket": bucket,
            "deferred_reason": reason,
            "label": reason,
        },
    )
    db.commit()
    events = list_capture_events(db, workspace_id=workspace_id, session_id=session_id)
    return build_quality_backlog(session, events)


def update_oracle_question_statuses(
    db: DBSession,
    *,
    workspace_id: str,
    session_id: str,
    items: List[Dict[str, Any]],
    actor_user_id: Optional[str] = None,
) -> ExpertCaptureSession:
    session = get_session(db, workspace_id=workspace_id, session_id=session_id)
    plan = dict(session.plan or {})
    status_map = dict(plan.get("oracle_question_statuses") or {})
    if not items:
        return session

    for raw in items:
        if not isinstance(raw, dict):
            continue
        question_id = _clean_optional_string(raw.get("question_id") or raw.get("id"))
        question_text = _clean_optional_string(raw.get("question_text") or raw.get("text"))
        key = _oracle_question_status_key(question_id=question_id, question_text=question_text)
        if not key:
            continue
        status = _normalize_oracle_question_status(raw.get("status"))
        status_map[key] = {
            "status": status,
            "question_id": question_id,
            "question_text": question_text,
            "updated_at": datetime.utcnow().isoformat(),
            "updated_by_user_id": actor_user_id,
        }
        _record_capture_event(
            db,
            session=session,
            event_type="oracle_question_status_updated",
            source="operator_edit",
            status=status,
            created_by=actor_user_id,
            meta_data={
                "question_id": question_id,
                "question_text": question_text,
                "status": status,
            },
        )

    plan["oracle_question_statuses"] = status_map
    session.plan = plan
    flag_modified(session, "plan")
    db.commit()
    db.refresh(session)
    return session


def update_capture_session_flags(
    db: DBSession,
    *,
    workspace_id: str,
    session_id: str,
    defer_weak_contradictions: Optional[bool] = None,
    suppress_oracle_questions: Optional[bool] = None,
    capture_domain: Optional[str] = None,
    focused_quality_question_id: Optional[str] = None,
    focused_quality_evaluation_id: Optional[str] = None,
) -> ExpertCaptureSession:
    session = get_session(db, workspace_id=workspace_id, session_id=session_id)
    metrics = dict(session.metrics or {})
    if defer_weak_contradictions is not None:
        metrics["defer_weak_contradictions"] = bool(defer_weak_contradictions)
    if suppress_oracle_questions is not None:
        metrics["suppress_oracle_questions"] = bool(suppress_oracle_questions)
    if capture_domain:
        metrics["capture_domain"] = capture_domain.strip().lower()
    if focused_quality_question_id is not None:
        metrics["focused_quality_question_id"] = focused_quality_question_id or None
    if focused_quality_evaluation_id is not None:
        metrics["focused_quality_evaluation_id"] = focused_quality_evaluation_id or None
    session.metrics = metrics
    flag_modified(session, "metrics")
    db.commit()
    db.refresh(session)
    return session


def _is_plan_build_schema(plan: Dict[str, Any]) -> bool:
    return plan.get("schema_version") in PLAN_BUILD_SCHEMA_VERSIONS or plan.get("mode") in {
        "plan_build",
        "provided_plan",
    }


async def _retrieve_context_chunks_async(
    db: DBSession,
    *,
    workspace_id: str,
    workspace_slug: Optional[str],
    session: ExpertCaptureSession,
    query: str,
    top_k: int = 4,
) -> Tuple[List[str], List[Dict[str, Any]], List[float]]:
    text = (query or "").strip()
    if not text:
        return [], [], []
    try:
        ctx = _load_context(db, workspace_id, session.context_id)
        collection_name = _resolve_collection_name(ctx)
        from app.services.rag.context import retrieve_rag_context

        result = await retrieve_rag_context(
            {
                "query": text,
                "workspace_id": workspace_id,
                "workspace_slug": workspace_slug,
                "capability_id": session.capability_id,
                "system_id": session.system_id,
                "context_collection": collection_name,
                "latency_profile": "fast",
                "rag_pipeline_mode": "auto",
                "top_k": max(1, min(top_k, 8)),
                "source_display_k": max(1, min(top_k, 8)),
                "candidate_pool_k": 20,
            }
        )
        return (
            list(result.get("chunks") or []),
            list(result.get("metadatas") or []),
            list(result.get("scores") or []),
        )
    except Exception:
        return [], [], []


def _retrieve_context_chunks(
    db: DBSession,
    *,
    workspace_id: str,
    workspace_slug: Optional[str],
    session: ExpertCaptureSession,
    query: str,
    top_k: int = 4,
) -> Tuple[List[str], List[Dict[str, Any]], List[float]]:
    return asyncio.run(
        _retrieve_context_chunks_async(
            db,
            workspace_id=workspace_id,
            workspace_slug=workspace_slug,
            session=session,
            query=query,
            top_k=top_k,
        )
    )


def _sync_plan_rag_chunks(
    db: DBSession,
    *,
    workspace_id: str,
    workspace_slug: Optional[str],
    session: ExpertCaptureSession,
    query: str,
    top_k: int = 4,
) -> Tuple[List[str], List[Dict[str, Any]]]:
    chunks, metadatas, _scores = _retrieve_context_chunks(
        db,
        workspace_id=workspace_id,
        workspace_slug=workspace_slug,
        session=session,
        query=query,
        top_k=top_k,
    )
    return chunks, metadatas


def _invoke_plan_oracle(
    context: CaptureSessionContext,
    *,
    rag_chunks: Optional[List[str]] = None,
    rag_metadatas: Optional[List[Dict[str, Any]]] = None,
    base_gaps: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    return asyncio.run(
        analyze_plan_oracle_async(
            context,
            rag_chunks=rag_chunks,
            rag_metadatas=rag_metadatas,
            base_gaps=base_gaps,
        )
    )


def process_plan_dialogue_turn(
    db: DBSession,
    *,
    workspace_id: str,
    session_id: str,
    text: str,
    actor_user_id: Optional[str] = None,
    confirm_finalize: bool = False,
    workspace_slug: Optional[str] = None,
) -> Dict[str, Any]:
    session = get_session(db, workspace_id=workspace_id, session_id=session_id)
    if session.status != "planned":
        raise ValueError("Plan dialogue is only available before the session starts")
    plan = dict(session.plan or {})
    if not _is_plan_build_schema(plan):
        raise ValueError("Session is not in plan co-construction mode")
    dialogue = dict(plan.get("dialogue") or {})
    turns = list(dialogue.get("turns") or [])
    clean = (text or "").strip()
    if clean:
        turns.append(
            {
                "id": str(uuid.uuid4()),
                "text": clean,
                "created_at": datetime.utcnow().isoformat(),
            }
        )
    dialogue["turns"] = turns
    plan["dialogue"] = dialogue
    plan["schema_version"] = PLAN_BUILD_V2_SCHEMA_VERSION

    subject = _dialogue_subject_text(plan)
    rag_chunks, rag_metadatas = _sync_plan_rag_chunks(
        db,
        workspace_id=workspace_id,
        workspace_slug=workspace_slug,
        session=session,
        query=f"{session.objective} {subject}".strip(),
    )
    gaps = build_knowledge_gaps(
        objective=f"{session.objective} {subject}".strip(),
        expert_profile=session.expert_profile,
        context_snapshot=plan.get("context") or {},
        knowledge_refs=list(plan.get("knowledge_refs") or []),
        rag_chunks=rag_chunks,
        rag_metadatas=rag_metadatas,
    )
    context = session_context_from_capture(session=session, plan=plan)
    oracle = _invoke_plan_oracle(
        context,
        rag_chunks=rag_chunks,
        rag_metadatas=rag_metadatas,
        base_gaps=gaps,
    )
    plan["topics"] = merge_topic_proposals(plan, oracle.get("topic_proposals") or [])
    plan["oracle"] = {
        "coverage_gaps": oracle.get("coverage_gaps") or [],
        "contradiction_candidates": oracle.get("contradiction_candidates") or [],
        "last_refreshed_at": datetime.utcnow().isoformat(),
    }
    dialogue["ready_to_finalize"] = _plan_dialogue_ready(plan) or confirm_finalize
    plan["dialogue"] = dialogue
    session.plan = plan
    session.knowledge_gaps = gaps
    flag_modified(session, "plan")
    flag_modified(session, "knowledge_gaps")
    _record_capture_event(
        db,
        session=session,
        event_type="plan_dialogue_turn",
        speaker="expert",
        text_raw=clean or None,
        source="capture_engine",
        status="accepted",
        created_by=actor_user_id,
        meta_data={"turn_count": len(turns), "ready_to_finalize": dialogue["ready_to_finalize"]},
    )
    _record_capture_event(
        db,
        session=session,
        event_type="oracle_topic_refresh",
        source="capture_engine",
        status="accepted",
        created_by=actor_user_id,
        meta_data={
            "topic_count": len(plan.get("topics") or []),
            "kb_chunk_count": len(rag_chunks),
            "contradiction_count": len(oracle.get("contradiction_candidates") or []),
        },
    )
    db.commit()
    db.refresh(session)
    next_prompt = plan_dialogue_probe(oracle, ready_to_finalize=bool(dialogue["ready_to_finalize"]))
    return {
        "session": serialize_session(session, surface="plan_build"),
        "next_prompt": next_prompt,
        "ready_to_finalize": dialogue["ready_to_finalize"],
        "turn_count": len(turns),
        "oracle": oracle,
    }


def finalize_plan_from_dialogue(
    db: DBSession,
    *,
    workspace_id: str,
    session_id: str,
    actor_user_id: Optional[str] = None,
    workspace_slug: Optional[str] = None,
) -> ExpertCaptureSession:
    session = get_session(db, workspace_id=workspace_id, session_id=session_id)
    plan = dict(session.plan or {})
    if not _is_plan_build_schema(plan):
        raise ValueError("Session is not in plan co-construction mode")
    if not _plan_dialogue_ready(plan):
        raise ValueError("Plan dialogue is not complete enough to finalize")
    subject = _dialogue_subject_text(plan)
    enriched_objective = f"{session.objective.strip()} {subject}".strip()
    existing_topics = plan.get("topics") or []
    if existing_topics:
        # The dialogue already built (and the user may have edited) the topic tree.
        # Preserve it verbatim — re-invoking the oracle / merge_topic_proposals here
        # reshuffles and duplicates the plan the user already saw (QA #2) and adds a
        # redundant ~17s oracle call. Only finalize: status, enriched objective, surface.
        gaps = list(session.knowledge_gaps or [])
        plan["topics"] = existing_topics
    else:
        # Fall back to the oracle only when no topics exist yet.
        rag_chunks, rag_metadatas = _sync_plan_rag_chunks(
            db,
            workspace_id=workspace_id,
            workspace_slug=workspace_slug,
            session=session,
            query=enriched_objective,
        )
        gaps = build_knowledge_gaps(
            objective=enriched_objective,
            expert_profile=session.expert_profile,
            context_snapshot=(plan.get("context") or {}),
            knowledge_refs=list(plan.get("knowledge_refs") or []),
            rag_chunks=rag_chunks,
            rag_metadatas=rag_metadatas,
        )
        context = session_context_from_capture(session=session, plan=plan)
        oracle = _invoke_plan_oracle(
            context,
            rag_chunks=rag_chunks,
            rag_metadatas=rag_metadatas,
            base_gaps=gaps,
        )
        plan["topics"] = merge_topic_proposals(plan, oracle.get("topic_proposals") or [])
        plan["oracle"] = {
            "coverage_gaps": oracle.get("coverage_gaps") or [],
            "contradiction_candidates": oracle.get("contradiction_candidates") or [],
            "last_refreshed_at": datetime.utcnow().isoformat(),
        }
    plan["schema_version"] = PLAN_BUILD_V2_SCHEMA_VERSION
    plan["dialogue"] = {**(plan.get("dialogue") or {}), "status": "finalized"}
    plan["objective"] = enriched_objective
    plan["questions"] = []
    plan["question_bank"] = list(plan.get("question_bank") or [])
    # Auto-schedule question-bank generation: the launch screen no longer needs an
    # explicit "confirm" button. The endpoint kicks off generate_question_bank in the
    # background once it sees the status flip from idle to generating.
    if (plan.get("question_bank_status") or "idle") == "idle":
        plan["question_bank_status"] = "generating"
    else:
        plan["question_bank_status"] = plan.get("question_bank_status") or "idle"
    plan["mode"] = "plan_build"
    plan["voice_runtime"] = session.voice_runtime
    plan["knowledge_refs"] = list(plan.get("knowledge_refs") or [])
    plan["review"] = {**(plan.get("review") or {}), "status": "draft", "reason": "topics_pending_validation"}
    session.objective = enriched_objective
    session.plan = plan
    session.knowledge_gaps = gaps
    flag_modified(session, "plan")
    flag_modified(session, "knowledge_gaps")
    _record_capture_event(
        db,
        session=session,
        event_type="capture_plan_created",
        source="capture_engine",
        status="accepted",
        created_by=actor_user_id,
        meta_data={
            "schema_version": plan.get("schema_version"),
            "from_plan_build": True,
            "topic_count": len(plan.get("topics") or []),
            "visible_questions": False,
        },
    )
    db.commit()
    db.refresh(session)
    return session


def _normalize_plan_build_topics(
    incoming: Dict[str, Any],
    *,
    fallback: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    fallback = fallback or {}
    raw_topics = incoming.get("topics") if isinstance(incoming.get("topics"), list) else fallback.get("topics")
    if not isinstance(raw_topics, list) or not raw_topics:
        raise ValueError("Plan must contain at least one topic")
    topic_ids: set[str] = set()
    subtopic_ids: set[str] = set()
    normalized_topics: List[Dict[str, Any]] = []
    for topic_index, raw_topic in enumerate(raw_topics, start=1):
        if not isinstance(raw_topic, dict):
            raise ValueError("Each topic must be an object")
        topic_id = str(raw_topic.get("id") or f"t-{topic_index:02d}").strip()
        topic_title = str(raw_topic.get("title") or f"Topic {topic_index}").strip()
        if not topic_id or topic_id in topic_ids:
            raise ValueError("Topic ids must be unique")
        topic_ids.add(topic_id)
        raw_subtopics = raw_topic.get("subtopics") or []
        if not isinstance(raw_subtopics, list) or not raw_subtopics:
            raise ValueError(f"Topic '{topic_title}' must contain at least one subtopic")
        normalized_subtopics: List[Dict[str, Any]] = []
        for subtopic_index, raw_subtopic in enumerate(raw_subtopics, start=1):
            if not isinstance(raw_subtopic, dict):
                raise ValueError("Each subtopic must be an object")
            subtopic_id = str(raw_subtopic.get("id") or f"{topic_id}-sub-{subtopic_index:02d}").strip()
            subtopic_title = str(raw_subtopic.get("title") or f"Subtopic {subtopic_index}").strip()
            if not subtopic_id or subtopic_id in subtopic_ids:
                raise ValueError("Subtopic ids must be unique")
            subtopic_ids.add(subtopic_id)
            points = normalize_outline_points(
                subtopic_id,
                raw_subtopic.get("questions") or raw_subtopic.get("points"),
            )
            normalized_subtopics.append(
                {
                    **raw_subtopic,
                    "id": subtopic_id,
                    "title": subtopic_title,
                    "objective": str(raw_subtopic.get("objective") or "").strip(),
                    "status": raw_subtopic.get("status") or "pending",
                    "questions": points,
                }
            )
        normalized_topics.append(
            {
                **raw_topic,
                "id": topic_id,
                "title": topic_title,
                "objective": str(raw_topic.get("objective") or "").strip(),
                "status": raw_topic.get("status") or "draft",
                "knowledge_refs": list(raw_topic.get("knowledge_refs") or []),
                "subtopics": normalized_subtopics,
            }
        )
    return normalized_topics


def get_plan_topics(
    db: DBSession,
    *,
    workspace_id: str,
    session_id: str,
) -> Dict[str, Any]:
    session = get_session(db, workspace_id=workspace_id, session_id=session_id)
    plan = session.plan or {}
    return {
        "schema_version": plan.get("schema_version"),
        "topics": plan.get("topics") or [],
        "question_bank_status": plan.get("question_bank_status") or "idle",
        "review": plan.get("review") or {},
    }


def update_plan_topics(
    db: DBSession,
    *,
    workspace_id: str,
    session_id: str,
    topics: List[Dict[str, Any]],
    actor_user_id: Optional[str] = None,
) -> ExpertCaptureSession:
    session = get_session(db, workspace_id=workspace_id, session_id=session_id)
    if session.status != "planned":
        raise ValueError("Plan topics can only be edited before the session starts")
    plan = dict(session.plan or {})
    if not _is_plan_build_schema(plan):
        raise ValueError("Session plan does not support topic-only editing")
    normalized_topics = _normalize_plan_build_topics({"topics": topics}, fallback=plan)
    plan["topics"] = normalized_topics
    plan["schema_version"] = PLAN_BUILD_V2_SCHEMA_VERSION
    plan["questions"] = []
    session.plan = plan
    flag_modified(session, "plan")
    _record_capture_event(
        db,
        session=session,
        event_type="capture_plan_amended",
        source="operator_edit",
        status="accepted",
        created_by=actor_user_id,
        meta_data={"topic_count": len(normalized_topics), "topic_only": True},
    )
    db.commit()
    db.refresh(session)
    return session


def validate_plan_topics(
    db: DBSession,
    *,
    workspace_id: str,
    session_id: str,
    actor_user_id: Optional[str] = None,
) -> ExpertCaptureSession:
    session = get_session(db, workspace_id=workspace_id, session_id=session_id)
    plan = dict(session.plan or {})
    if not _is_plan_build_schema(plan):
        raise ValueError("Session is not in plan co-construction mode")
    topics = _normalize_plan_build_topics(plan, fallback=plan)
    plan["topics"] = [{**topic, "status": "validated"} for topic in topics]
    plan["review"] = {**(plan.get("review") or {}), "status": "topics_validated"}
    plan["question_bank_status"] = "generating"
    session.plan = plan
    flag_modified(session, "plan")
    _record_capture_event(
        db,
        session=session,
        event_type="question_bank_generating",
        source="capture_engine",
        status="running",
        created_by=actor_user_id,
        meta_data={"topic_count": len(topics)},
    )
    db.commit()
    db.refresh(session)
    return session


def generate_question_bank(
    db: DBSession,
    *,
    workspace_id: str,
    session_id: str,
    workspace_slug: Optional[str] = None,
) -> ExpertCaptureSession:
    session = get_session(db, workspace_id=workspace_id, session_id=session_id)
    plan = dict(session.plan or {})
    topics = plan.get("topics") or []
    bank: List[Dict[str, Any]] = []
    priority = 80
    for topic in topics:
        for subtopic in topic.get("subtopics") or []:
            subtopic_id = str(subtopic.get("id") or "")
            title = str(subtopic.get("title") or "Sujet")
            objective = str(subtopic.get("objective") or session.objective or "")
            query = f"{title} {objective}".strip()
            chunks, metadatas, _scores = _retrieve_context_chunks(
                db,
                workspace_id=workspace_id,
                workspace_slug=workspace_slug,
                session=session,
                query=query,
                top_k=3,
            )
            kb_refs = []
            for index, chunk in enumerate(chunks[:2]):
                md = metadatas[index] if index < len(metadatas) and isinstance(metadatas[index], dict) else {}
                kb_refs.append(
                    {
                        "ref": md.get("source") or md.get("document_id") or f"chunk-{index + 1}",
                        "title": md.get("title") or md.get("filename"),
                        "preview": str(chunk)[:160],
                    }
                )
            generated = asyncio.run(
                generate_question_bank_entry_async(
                    workspace_id=workspace_id,
                    subtopic_title=title,
                    subtopic_objective=objective,
                    session_objective=str(session.objective or ""),
                    rag_chunks=chunks,
                    rag_metadatas=metadatas,
                )
            )
            full_question = generated["full_question"]
            hint = generated["hint"][:80]
            presentation = generated.get("prompt") or presentation_prompt(title)
            bank.append(
                {
                    "id": f"qb-{uuid.uuid4()}",
                    "subtopic_id": subtopic_id,
                    "full_question": full_question,
                    "prompt": presentation,
                    "hint": hint[:80],
                    "priority": priority,
                    "source": "planned",
                    "visibility": "hidden",
                    "kb_refs": kb_refs,
                }
            )
            priority -= 5
    plan["question_bank"] = bank
    plan["questions"] = [
        {
            "id": item["id"],
            "subtopic_id": item["subtopic_id"],
            "question": item["full_question"],
            "prompt": item["prompt"],
            "hint": item["hint"],
            "visibility": "hidden",
        }
        for item in bank
    ]
    plan["question_bank_status"] = "ready"
    session.plan = plan
    flag_modified(session, "plan")
    _record_capture_event(
        db,
        session=session,
        event_type="question_bank_ready",
        source="capture_engine",
        status="accepted",
        meta_data={"question_count": len(bank)},
    )
    db.commit()
    db.refresh(session)
    return session


def _hint_queue_for_plan(plan: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    raw = plan.get("hint_queue")
    if isinstance(raw, dict):
        return {str(key): list(value or []) for key, value in raw.items() if isinstance(value, list)}
    return {}


def _save_hint_queue(plan: Dict[str, Any], queue: Dict[str, List[Dict[str, Any]]]) -> None:
    plan["hint_queue"] = queue


def prepend_hint_to_queue(
    plan: Dict[str, Any],
    *,
    subtopic_id: Optional[str],
    hint_entry: Dict[str, Any],
) -> Dict[str, Any]:
    queue = _hint_queue_for_plan(plan)
    key = str(subtopic_id or "_global")
    entries = list(queue.get(key) or [])
    hint_id = str(hint_entry.get("id") or f"qb-live-{uuid.uuid4()}")
    normalized = {
        **hint_entry,
        "id": hint_id,
        "created_at": hint_entry.get("created_at") or datetime.utcnow().isoformat(),
        "visibility": hint_entry.get("visibility") or "hint",
    }
    entries = [normalized, *[item for item in entries if item.get("id") != hint_id]]
    entries.sort(key=lambda item: (-int(item.get("priority") or 0), str(item.get("created_at") or "")), reverse=False)
    entries.sort(key=lambda item: -int(item.get("priority") or 0))
    queue[key] = entries
    bank = list(plan.get("question_bank") or [])
    bank = [normalized, *[item for item in bank if item.get("id") != hint_id]]
    plan["question_bank"] = bank
    _save_hint_queue(plan, queue)
    return normalized


def get_hint_queue(
    db: DBSession,
    *,
    workspace_id: str,
    session_id: str,
    subtopic_id: Optional[str] = None,
) -> Dict[str, Any]:
    session = get_session(db, workspace_id=workspace_id, session_id=session_id)
    plan = session.plan or {}
    queue = _hint_queue_for_plan(plan)
    if subtopic_id:
        items = list(queue.get(subtopic_id) or [])
        items = [
            item
            for item in items
            if item.get("visibility") not in {"resolved", "deferred"}
        ]
        items.sort(key=lambda item: (-int(item.get("priority") or 0), str(item.get("created_at") or "")))
        return {"subtopic_id": subtopic_id, "hints": items}
    aggregated: List[Dict[str, Any]] = []
    for key, items in queue.items():
        for item in items:
            if item.get("visibility") in {"resolved", "deferred"}:
                continue
            aggregated.append({**item, "subtopic_id": item.get("subtopic_id") or key})
    aggregated.sort(key=lambda item: (-int(item.get("priority") or 0), str(item.get("created_at") or "")))
    return {"hints": aggregated}


def _coerce_priority(value: Any) -> float:
    try:
        return round(float(value), 4)
    except (TypeError, ValueError):
        return 0.0


def build_open_questions(
    session: ExpertCaptureSession,
    *,
    plan: Optional[Dict[str, Any]] = None,
    contradiction_candidates: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """The oracle's OWN open questions — the curiosities and gaps it tracks while
    listening, NOT questions imposed on the expert.

    Derived from the internal ``coverage_gaps`` and contradiction tracking already
    computed. Returns a list of ``{id, text, topic_id, priority, status}`` sorted by
    ``priority`` descending (higher = more pressing). Marked ``addressed`` when the
    expert's free expression already overlaps the gap.
    """
    plan = plan if plan is not None else (session.plan or {})
    gaps = list(((plan.get("oracle") or {}).get("coverage_gaps")) or [])
    if not gaps:
        gaps = list(session.knowledge_gaps or [])
    if not gaps:
        # Free-conversation (and any plan that never seeded gaps) still has internal
        # oracle curiosities: fall back to the generic prioritized gap taxonomy so the
        # "questions de l'oracle" panel reflects what the AI is tracking internally.
        gaps = build_knowledge_gaps(
            objective=session.objective or "",
            expert_profile=session.expert_profile,
            context_snapshot=plan.get("context") or {},
            knowledge_refs=list(plan.get("knowledge_refs") or []),
        )

    expert_text = " ".join(
        str(turn.get("text") or "")
        for turn in (session.transcript or [])
        if turn.get("speaker") == "expert"
    )
    expert_tokens = _content_tokens(expert_text)

    items: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for gap in gaps:
        if not isinstance(gap, dict):
            continue
        slug = str(gap.get("slug") or gap.get("id") or "").strip()
        title = str(gap.get("title") or "").strip()
        description = str(gap.get("description") or "").strip()
        text = description or title
        if not text:
            continue
        key = slug or text.lower()
        if key in seen:
            continue
        seen.add(key)
        gap_tokens = _content_tokens(f"{title} {description}")
        addressed = bool(
            gap_tokens
            and expert_tokens
            and len(gap_tokens & expert_tokens) / max(1, len(gap_tokens)) >= 0.5
        )
        base_status = "addressed" if addressed else "open"
        items.append(
            {
                "id": slug or f"open-{len(items) + 1:02d}",
                "text": text,
                "topic_id": gap.get("topic_id"),
                "priority": _coerce_priority(gap.get("priority")),
                "status": _stored_oracle_question_status(
                    plan,
                    question_id=slug or f"open-{len(items) + 1:02d}",
                    question_text=text,
                )
                or base_status,
            }
        )

    for candidate in contradiction_candidates or []:
        if not isinstance(candidate, dict):
            continue
        hint = str(candidate.get("suggested_hint") or "").strip()
        if not hint:
            continue
        key = f"contradiction:{hint.lower()}"
        if key in seen:
            continue
        seen.add(key)
        items.append(
            {
                "id": f"contradiction-{len(items) + 1:02d}",
                "text": hint,
                "topic_id": candidate.get("topic_id"),
                # Above the 0..1 coverage-gap range so a detected contradiction is the
                # most pressing open question the oracle is tracking.
                "priority": 2.0,
                "status": _stored_oracle_question_status(
                    plan,
                    question_id=f"contradiction-{len(items) + 1:02d}",
                    question_text=hint,
                )
                or "open",
            }
        )

    items.sort(key=lambda item: item.get("priority") or 0.0, reverse=True)
    return items


def process_capture_partial_hints(
    db: DBSession,
    *,
    workspace_id: str,
    session_id: str,
    partial_text: str,
    retrieval_chunks: List[str],
    retrieval_metadatas: Optional[List[Dict[str, Any]]] = None,
    client_turn_id: Optional[str] = None,
    actor_user_id: Optional[str] = None,
) -> Dict[str, Any]:
    session = get_session(db, workspace_id=workspace_id, session_id=session_id)
    if is_capture_text_noise(partial_text):
        return {"hints": [], "active_subtopic_id": None, "session": session, "ignored_reason": "stt_noise"}
    plan = dict(session.plan or {})
    metrics = dict(session.metrics or {})
    context = session_context_from_capture(
        session=session,
        plan=plan,
        active_subtopic_id=metrics.get("active_subtopic_id"),
        recent_transcript=session.transcript or [],
    )
    evaluation = evaluate_capture_partial(
        context,
        partial_text,
        retrieval_chunks,
        retrieval_metadatas=retrieval_metadatas,
        plan_topics=plan.get("topics") or [],
    )
    pushed: List[Dict[str, Any]] = []
    active_subtopic_id = evaluation.get("active_subtopic_id")
    if active_subtopic_id and active_subtopic_id != metrics.get("active_subtopic_id"):
        metrics["active_subtopic_id"] = active_subtopic_id
        session.metrics = metrics
        flag_modified(session, "metrics")
        _record_capture_event(
            db,
            session=session,
            event_type="subtopic_focus_changed",
            source="capture_engine",
            status="accepted",
            meta_data={"active_subtopic_id": active_subtopic_id, "client_turn_id": client_turn_id},
        )
    for hint in evaluation.get("hints") or []:
        subtopic_id = hint.get("subtopic_id") or active_subtopic_id
        normalized = prepend_hint_to_queue(plan, subtopic_id=subtopic_id, hint_entry=hint)
        pushed.append(normalized)
        _record_capture_event(
            db,
            session=session,
            event_type="hint_pushed",
            source="capture_engine",
            status="accepted",
            created_by=actor_user_id,
            meta_data={
                "hint": normalized.get("hint"),
                "subtopic_id": subtopic_id,
                "oracle_id": normalized.get("oracle_id"),
                "kb_excerpt": hint.get("kb_excerpt"),
                "client_turn_id": client_turn_id,
            },
        )
    if pushed:
        session.plan = plan
        flag_modified(session, "plan")
    resolve_hints_from_expert_text(
        db,
        workspace_id=workspace_id,
        session_id=session_id,
        text=partial_text,
        actor_user_id=actor_user_id,
    )
    db.commit()
    db.refresh(session)
    return {"hints": pushed, "active_subtopic_id": active_subtopic_id, "session": session}


def _hint_overlap_score(hint_text: str, expert_text: str) -> float:
    hint_tokens = _content_tokens(hint_text)
    expert_tokens = _content_tokens(expert_text)
    if not hint_tokens or not expert_tokens:
        return 0.0
    overlap = hint_tokens & expert_tokens
    return len(overlap) / max(1, len(hint_tokens))


def _update_hint_visibility(
    plan: Dict[str, Any],
    *,
    hint_id: str,
    visibility: str,
    subtopic_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    queue = _hint_queue_for_plan(plan)
    updated: Optional[Dict[str, Any]] = None
    for key, entries in queue.items():
        if subtopic_id and key != subtopic_id:
            continue
        for index, entry in enumerate(entries):
            if str(entry.get("id")) != hint_id:
                continue
            merged = {**entry, "visibility": visibility, "resolved_at": datetime.utcnow().isoformat()}
            entries[index] = merged
            updated = merged
            break
        if updated:
            queue[key] = entries
            break
    if not updated:
        bank = list(plan.get("question_bank") or [])
        for index, entry in enumerate(bank):
            if str(entry.get("id")) != hint_id:
                continue
            bank[index] = {
                **entry,
                "visibility": visibility,
                "resolved_at": datetime.utcnow().isoformat(),
            }
            updated = bank[index]
            break
        plan["question_bank"] = bank
    if updated:
        _save_hint_queue(plan, queue)
    return updated


def resolve_hints_from_expert_text(
    db: DBSession,
    *,
    workspace_id: str,
    session_id: str,
    text: str,
    actor_user_id: Optional[str] = None,
    overlap_threshold: float = 0.34,
) -> List[Dict[str, Any]]:
    """Mark queued hints resolved when expert speech overlaps hint topics."""
    clean = (text or "").strip()
    if len(_words(clean)) < 4:
        return []
    session = get_session(db, workspace_id=workspace_id, session_id=session_id)
    plan = dict(session.plan or {})
    queue = _hint_queue_for_plan(plan)
    resolved: List[Dict[str, Any]] = []
    for subtopic_id, entries in queue.items():
        for entry in entries:
            visibility = entry.get("visibility") or "hint"
            if visibility in {"resolved", "deferred"}:
                continue
            hint_text = str(entry.get("hint") or entry.get("full_question") or "")
            score = _hint_overlap_score(hint_text, clean)
            if score < overlap_threshold:
                continue
            updated = _update_hint_visibility(
                plan,
                hint_id=str(entry.get("id")),
                visibility="resolved",
                subtopic_id=subtopic_id,
            )
            if not updated:
                continue
            resolved.append(updated)
            _record_capture_event(
                db,
                session=session,
                event_type="hint_resolved",
                source="capture_engine",
                status="accepted",
                created_by=actor_user_id,
                meta_data={
                    "hint_id": updated.get("id"),
                    "subtopic_id": subtopic_id,
                    "overlap_score": round(score, 2),
                },
            )
    if resolved:
        session.plan = plan
        flag_modified(session, "plan")
        db.commit()
        db.refresh(session)
    return resolved


def defer_active_hint(
    db: DBSession,
    *,
    workspace_id: str,
    session_id: str,
    deferred_reason: str = "end_of_session",
    actor_user_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    session = get_session(db, workspace_id=workspace_id, session_id=session_id)
    plan = dict(session.plan or {})
    metrics = dict(session.metrics or {})
    active_subtopic_id = metrics.get("active_subtopic_id")
    queue = _hint_queue_for_plan(plan)
    target_key: Optional[str] = None
    target_entry: Optional[Dict[str, Any]] = None
    for key, entries in queue.items():
        if active_subtopic_id and key != active_subtopic_id:
            continue
        for entry in sorted(
            entries,
            key=lambda item: (-int(item.get("priority") or 0), str(item.get("created_at") or "")),
        ):
            if (entry.get("visibility") or "hint") in {"resolved", "deferred"}:
                continue
            target_key = key
            target_entry = entry
            break
        if target_entry:
            break
    if not target_entry or not target_key:
        return None
    updated = _update_hint_visibility(
        plan,
        hint_id=str(target_entry.get("id")),
        visibility="deferred",
        subtopic_id=target_key,
    )
    if not updated:
        return None
    session.plan = plan
    flag_modified(session, "plan")
    _record_capture_event(
        db,
        session=session,
        event_type="hint_deferred",
        source="expert_live",
        status="deferred",
        created_by=actor_user_id,
        meta_data={
            "hint_id": updated.get("id"),
            "subtopic_id": target_key,
            "deferred_reason": deferred_reason,
        },
    )
    db.commit()
    db.refresh(session)
    return updated


def defer_open_quality_from_voice(
    db: DBSession,
    *,
    workspace_id: str,
    session_id: str,
    deferred_reason: str = "end_of_session",
    actor_user_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    session = get_session(db, workspace_id=workspace_id, session_id=session_id)
    events = list_capture_events(db, workspace_id=workspace_id, session_id=session_id)
    backlog = build_quality_backlog(session, events)
    deferred_ids = {
        str(item.get("id"))
        for bucket in (backlog.get("imprecisions") or [], backlog.get("contradictions") or [])
        for item in bucket
        if item.get("status") == "deferred"
    }
    candidate: Optional[Dict[str, Any]] = None
    for evaluation in reversed(session.evaluations or []):
        verdict = str(evaluation.get("verdict") or "")
        if verdict not in {"needs_precision", "partial", "contradiction_or_update"}:
            continue
        item_id = str(evaluation.get("id") or evaluation.get("question_id") or "")
        if not item_id or item_id in deferred_ids:
            continue
        bucket = "contradictions" if verdict == "contradiction_or_update" else "imprecisions"
        candidate = {
            "item_id": item_id,
            "bucket": bucket,
            "label": evaluation.get("follow_up") or "Élément reporté",
            "evaluation_id": evaluation.get("id"),
            "question_id": evaluation.get("question_id"),
        }
        break
    if not candidate:
        return None
    defer_quality_item(
        db,
        workspace_id=workspace_id,
        session_id=session_id,
        item_id=candidate["item_id"],
        bucket=candidate["bucket"],
        deferred_reason=deferred_reason,
        actor_user_id=actor_user_id,
    )
    return candidate


def pause_capture_session(
    db: DBSession,
    *,
    workspace_id: str,
    session_id: str,
    actor_user_id: Optional[str] = None,
) -> ExpertCaptureSession:
    session = get_session(db, workspace_id=workspace_id, session_id=session_id)
    if session.status not in {"active", "planned"}:
        raise ValueError("Only active or planned sessions can be paused")
    session.status = "paused"
    metrics = dict(session.metrics or {})
    metrics["paused_at"] = datetime.utcnow().isoformat()
    metrics["resume_summary"] = _build_resume_summary(session)
    session.metrics = metrics
    flag_modified(session, "metrics")
    _record_capture_event(
        db,
        session=session,
        event_type="capture_session_paused",
        source="capture_engine",
        status="accepted",
        created_by=actor_user_id,
        meta_data={"resume_summary": metrics.get("resume_summary")},
    )
    db.commit()
    db.refresh(session)
    return session


def resume_capture_session(
    db: DBSession,
    *,
    workspace_id: str,
    session_id: str,
    actor_user_id: Optional[str] = None,
) -> ExpertCaptureSession:
    session = get_session(db, workspace_id=workspace_id, session_id=session_id)
    if session.status != "paused":
        raise ValueError("Session is not paused")
    session.status = "active" if session.started_at else "planned"
    metrics = dict(session.metrics or {})
    metrics.pop("paused_at", None)
    session.metrics = metrics
    flag_modified(session, "metrics")
    _record_capture_event(
        db,
        session=session,
        event_type="capture_session_resumed",
        source="capture_engine",
        status="accepted",
        created_by=actor_user_id,
        meta_data={"resume_summary": metrics.get("resume_summary")},
    )
    db.commit()
    db.refresh(session)
    return session


def _build_resume_summary(session: ExpertCaptureSession) -> str:
    facts = len(session.captured_facts or [])
    turns = len(session.transcript or [])
    coverage = (session.metrics or {}).get("coverage")
    coverage_label = "sans couverture" if coverage is None else f"{int(float(coverage) * 100)} % couverts"
    timer = _compute_timer_metrics(session)
    timer_hint = ""
    if not timer.get("unlimited_duration") and timer.get("timer_phase") == "last_5_minutes":
        timer_hint = " Il reste moins de cinq minutes planifiées."
    elif timer.get("session_end_pending"):
        timer_hint = " La durée planifiée est écoulée — choisissez terminer, prolonger ou replanifier."
    return (
        f"Reprise de « {session.title} » : {turns} échanges, {facts} faits structurés, {coverage_label}.{timer_hint} "
        "Vous pouvez continuer la conversation ou demander la synthèse."
    )


def _closure_topics_covered(session: ExpertCaptureSession) -> List[str]:
    topics: List[str] = []
    seen: set[str] = set()
    for fact in session.captured_facts or []:
        label = str(fact.get("topic_path") or fact.get("subtopic_id") or "").strip()
        if label and label not in seen:
            seen.add(label)
            topics.append(label)
    if topics:
        return topics
    for topic in (session.plan or {}).get("topics") or []:
        if not isinstance(topic, dict):
            continue
        title = str(topic.get("title") or "").strip()
        if title and title not in seen:
            seen.add(title)
            topics.append(title)
    return topics


def build_session_closure_sheet(
    session: ExpertCaptureSession,
    events: Optional[List[ExpertCaptureEvent]] = None,
) -> Dict[str, Any]:
    """Structured end-of-session sheet for review or export."""
    backlog = build_quality_backlog(session, events)
    topics = _closure_topics_covered(session)
    facts = list(session.captured_facts or [])
    if not facts:
        facts = [
            {"text": str(turn.get("text") or "").strip(), "topic_path": turn.get("topic_path")}
            for turn in (session.transcript or [])
            if turn.get("speaker") == "expert" and str(turn.get("text") or "").strip()
        ]
    unresolved: List[Dict[str, Any]] = []
    for bucket in ("imprecisions", "contradictions", "open_questions"):
        for item in backlog.get(bucket) or []:
            if not isinstance(item, dict):
                continue
            if item.get("status") not in {None, "open", "deferred"}:
                continue
            unresolved.append(
                {
                    "bucket": bucket,
                    "label": item.get("label") or item.get("follow_up") or "Point ouvert",
                    "status": item.get("status") or "open",
                }
            )
    fact_lines = "\n".join(
        f"- {str(fact.get('text') or '').strip()}" for fact in facts if str(fact.get("text") or "").strip()
    )
    topic_lines = "\n".join(f"- {topic}" for topic in topics) if topics else "- Aucun sujet identifié."
    unresolved_lines = "\n".join(
        f"- [{item['bucket']}] {item['label']}" for item in unresolved
    )
    markdown = (
        f"# Fiche fin de session — {session.title}\n\n"
        f"## Sujets abordés\n{topic_lines}\n\n"
        f"## Faits capturés\n{fact_lines or '- Aucun fait structuré.'}\n\n"
        f"## Points non résolus\n{unresolved_lines or '- Aucun point ouvert.'}\n"
    )
    return {
        "markdown": markdown,
        "topics": topics,
        "captured_facts": facts,
        "unresolved": unresolved,
    }


def generate_session_closure_sheet(
    db: DBSession,
    *,
    workspace_id: str,
    session_id: str,
    actor_user_id: Optional[str] = None,
) -> Dict[str, Any]:
    session = get_session(db, workspace_id=workspace_id, session_id=session_id)
    events = list_capture_events(db, workspace_id=workspace_id, session_id=session_id)
    payload = build_session_closure_sheet(session, events)
    metrics = dict(session.metrics or {})
    metrics.update(_compute_timer_metrics(session))
    metrics["closure_sheet"] = payload["markdown"]
    metrics["session_end_pending"] = True
    session.metrics = metrics
    flag_modified(session, "metrics")
    _record_capture_event(
        db,
        session=session,
        event_type="session_closure_sheet_generated",
        source="capture_engine",
        status="accepted",
        created_by=actor_user_id,
        meta_data={
            "topic_count": len(payload.get("topics") or []),
            "fact_count": len(payload.get("captured_facts") or []),
            "unresolved_count": len(payload.get("unresolved") or []),
        },
    )
    db.commit()
    db.refresh(session)
    return payload


def extend_capture_session(
    db: DBSession,
    *,
    workspace_id: str,
    session_id: str,
    extension_minutes: int = SESSION_EXTENSION_MINUTES,
    actor_user_id: Optional[str] = None,
) -> ExpertCaptureSession:
    session = get_session(db, workspace_id=workspace_id, session_id=session_id)
    if _session_unlimited_duration(session):
        raise ValueError("Unlimited sessions do not require duration extension")
    if session.status not in {"active", "paused"}:
        raise ValueError("Only active or paused sessions can be extended")
    minutes = max(5, min(int(extension_minutes or SESSION_EXTENSION_MINUTES), 60))
    metrics = dict(session.metrics or {})
    metrics["duration_extension_minutes"] = int(metrics.get("duration_extension_minutes") or 0) + minutes
    metrics["session_end_pending"] = False
    metrics.pop("closure_sheet", None)
    session.metrics = metrics
    flag_modified(session, "metrics")
    metrics = dict(session.metrics or {})
    metrics.update(_compute_timer_metrics(session))
    session.metrics = metrics
    flag_modified(session, "metrics")
    _record_capture_event(
        db,
        session=session,
        event_type="capture_session_extended",
        source="operator_edit",
        status="accepted",
        created_by=actor_user_id,
        meta_data={"extension_minutes": minutes, "effective_duration_minutes": _session_effective_duration_minutes(session)},
    )
    db.commit()
    db.refresh(session)
    return session


def apply_session_closure_action(
    db: DBSession,
    *,
    workspace_id: str,
    session_id: str,
    action: str,
    actor_user_id: Optional[str] = None,
    extension_minutes: int = SESSION_EXTENSION_MINUTES,
) -> Dict[str, Any]:
    normalized = (action or "finish").strip().lower()
    if normalized == "extend":
        session = extend_capture_session(
            db,
            workspace_id=workspace_id,
            session_id=session_id,
            extension_minutes=extension_minutes,
            actor_user_id=actor_user_id,
        )
        return {
            "action": normalized,
            "session": serialize_session(session),
            "closure_sheet": None,
            "proposal": None,
        }
    session = get_session(db, workspace_id=workspace_id, session_id=session_id)
    closure = build_session_closure_sheet(session, list_capture_events(db, workspace_id=workspace_id, session_id=session_id))
    metrics = dict(session.metrics or {})
    metrics["closure_sheet"] = closure["markdown"]
    metrics["session_end_pending"] = False
    session.metrics = metrics
    flag_modified(session, "metrics")
    if normalized == "schedule":
        if session.status in {"active", "planned"}:
            session.status = "paused"
            metrics = dict(session.metrics or {})
            metrics["paused_at"] = datetime.utcnow().isoformat()
            metrics["resume_summary"] = _build_resume_summary(session)
            metrics["scheduled_follow_up"] = True
            session.metrics = metrics
            flag_modified(session, "metrics")
        _record_capture_event(
            db,
            session=session,
            event_type="capture_session_scheduled",
            source="operator_edit",
            status="accepted",
            created_by=actor_user_id,
            meta_data={"closure_sheet": closure["markdown"]},
        )
        db.commit()
        db.refresh(session)
        return {
            "action": normalized,
            "session": serialize_session(session),
            "closure_sheet": closure,
            "proposal": None,
        }
    proposal = None
    if _session_has_proposal_material(db, workspace_id=workspace_id, session=session):
        proposal = create_update_proposal(
            db,
            workspace_id=workspace_id,
            session_id=session_id,
            complete_session=True,
            created_by_user_id=actor_user_id,
        )
        session = get_session(db, workspace_id=workspace_id, session_id=session_id)
    else:
        session.status = "completed"
        session.completed_at = datetime.utcnow()
        _record_capture_event(
            db,
            session=session,
            event_type="capture_session_completed",
            source="operator_edit",
            status="accepted",
            created_by=actor_user_id,
            meta_data={"closure_sheet": closure["markdown"], "proposal_created": False},
        )
        db.commit()
        db.refresh(session)
    return {
        "action": "finish",
        "session": serialize_session(session),
        "closure_sheet": closure,
        "proposal": serialize_proposal(proposal) if proposal else None,
    }


def export_session_proposal_markdown(
    db: DBSession,
    *,
    workspace_id: str,
    session_id: str,
    proposal_id: Optional[str] = None,
    executive_summary: Optional[str] = None,
) -> str:
    session = get_session(db, workspace_id=workspace_id, session_id=session_id)
    proposal = _load_active_proposal(db, workspace_id=workspace_id, proposal_id=proposal_id, session_id=session_id)
    if not proposal:
        raise ValueError("No proposal available for export")
    payload = dict(proposal.proposal or {})
    if executive_summary is not None:
        payload["executive_summary"] = executive_summary.strip()
        proposal.proposal = payload
        flag_modified(proposal, "proposal")
        db.commit()
    captured = payload.get("captured_facts") or []
    open_questions = payload.get("open_questions") or []
    summary = payload.get("executive_summary") or session.title
    body = (
        payload.get("report_markdown")
        or ((payload.get("recommended_ingestion") or {}).get("content"))
        or _proposal_markdown(session, captured, open_questions)
    )
    return f"## Résumé exécutif\n\n{summary}\n\n{body}"


async def publish_proposal_to_knowledge(
    db: DBSession,
    *,
    workspace: Any,
    proposal_id: str,
    actor_label: str,
    category: Optional[str] = None,
    destination: Optional[str] = None,
    final_title: Optional[str] = None,
    include_unresolved_questions: Optional[bool] = None,
) -> Dict[str, Any]:
    proposal = (
        db.query(KnowledgeUpdateProposal)
        .filter(
            KnowledgeUpdateProposal.id == proposal_id,
            KnowledgeUpdateProposal.workspace_id == workspace.id,
        )
        .first()
    )
    if not proposal:
        raise ValueError("Knowledge update proposal not found")
    if proposal.status != "accepted":
        raise ValueError("Proposal must be accepted before publication")
    session = get_session(db, workspace_id=workspace.id, session_id=proposal.session_id)
    ctx = _load_context(db, workspace.id, session.context_id)
    collection_name = _resolve_collection_name(ctx)
    proposal_payload = dict(proposal.proposal or {})
    recommended = dict(proposal_payload.get("recommended_ingestion") or {})
    metadata = dict(recommended.get("metadata") or {})
    publication_meta = dict(proposal_payload.get("publication") or {})
    publication_category = (
        _clean_optional_string(category)
        or _clean_optional_string(publication_meta.get("category"))
        or _suggest_publication_category(session, proposal_payload)
    )
    publication_destination = (
        _clean_optional_string(destination)
        or _clean_optional_string(publication_meta.get("destination"))
        or _clean_optional_string(publication_meta.get("destination_scope"))
        or _resolve_collection_name(ctx)
    )
    publication_title = (
        _clean_optional_string(final_title)
        or _clean_optional_string(publication_meta.get("final_title"))
        or _clean_optional_string(recommended.get("title"))
        or proposal_payload.get("title")
        or session.title
    )
    if publication_category:
        publication_meta["category"] = publication_category
        metadata["publication_category"] = publication_category
    if publication_destination:
        publication_meta["destination"] = publication_destination
        publication_meta["destination_scope"] = publication_destination
        metadata["publication_destination"] = publication_destination
        metadata["publication_destination_scope"] = publication_destination
    if publication_title:
        publication_meta["final_title"] = publication_title
        metadata["publication_final_title"] = publication_title
        recommended["title"] = publication_title
    publication_meta["updated_at"] = datetime.utcnow().isoformat()
    publication_meta["updated_by"] = actor_label
    if include_unresolved_questions is None:
        publication_meta.setdefault("include_unresolved_questions", True)
    else:
        publication_meta["include_unresolved_questions"] = bool(include_unresolved_questions)
    recommended["metadata"] = metadata
    proposal_payload["recommended_ingestion"] = recommended
    proposal_payload["publication"] = publication_meta
    proposal.proposal = proposal_payload
    flag_modified(proposal, "proposal")
    db.flush()
    content = ((proposal.proposal or {}).get("recommended_ingestion") or {}).get("content")
    if not content:
        events = list_capture_events(db, workspace_id=workspace.id, session_id=session.id)
        content = export_session_proposal_markdown(
            db,
            workspace_id=workspace.id,
            session_id=session.id,
            proposal_id=proposal.id,
        )
        if not ((proposal.proposal or {}).get("captured_facts")):
            payload = structure_capture_payload(session, events)
            content = (payload.get("recommended_ingestion") or {}).get("content") or content

    from app.services.knowledge_collections import create_or_get_collection
    from app.services.object_store import get_object_store
    from app.services.knowledge_collections import ingested_key, original_key
    from app.core.settings_manager import get_resolved_settings
    from app.services.rag.vector_store_config import resolve_vector_db_type
    from app.services.rag.document_service import DocumentService

    slug = collection_name.replace("_", "-")[:80] or "expert-capture"
    collection = create_or_get_collection(
        db,
        workspace=workspace,
        slug=slug,
        name=collection_name,
        description="Expert capture publications",
    )
    db.flush()
    filename = f"capture-{session.id[:8]}.md"
    store = get_object_store()
    store.write_text(original_key(collection, filename), content)
    store.write_text(ingested_key(collection, filename), content)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / filename
        path.write_text(content, encoding="utf-8")
        app_settings = get_resolved_settings(workspace_id=workspace.id)
        doc_service = DocumentService(
            collection_name=collection.slug,
            vector_db_type=resolve_vector_db_type(app_settings),
            workspace_slug=workspace.slug,
        )
        result = await doc_service.ingest_document(str(path), collection_name=collection.slug)
    document_id = result.get("document_id")
    export_urls: Dict[str, str] = {}
    if document_id:
        raw_url = f"/api/v1/documents/{quote(str(document_id), safe='')}/raw"
        export_urls = {
            "download_url": raw_url,
            "raw_url": raw_url,
        }
        publication_meta["export_urls"] = export_urls
        proposal_payload["publication"] = publication_meta
        proposal.proposal = proposal_payload
        flag_modified(proposal, "proposal")
        db.flush()
    emit_audit_event(
        db=db,
        workspace_id=workspace.id,
        event_type="kc.proposal.published",
        actor=actor_label,
        details={
            "proposal_id": proposal.id,
            "session_id": session.id,
            "collection": collection.slug,
            "category": publication_category,
            "destination": publication_destination,
            "destination_scope": publication_destination,
            "final_title": publication_title,
            "export_urls": export_urls,
        },
    )
    db.commit()
    return {
        "proposal_id": proposal.id,
        "collection": collection.slug,
        "document_id": document_id,
        "chunks_processed": result.get("chunks_processed", 0),
        "status": result.get("status"),
        "category": publication_category,
        "destination": publication_destination,
        "destination_scope": publication_destination,
        "final_title": publication_title,
        "export_urls": export_urls,
    }


def _knowledge_refs_for_topic(
    context_snapshot: Optional[Dict[str, Any]],
    gaps: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    context_snapshot = context_snapshot or {}
    environment_state = context_snapshot.get("environment_state") or {}
    refs: List[Dict[str, Any]] = []
    collection = environment_state.get("collection") or environment_state.get("collection_name")
    if collection:
        refs.append({"kind": "collection", "label": str(collection), "ref": str(collection)})
    for ref in context_snapshot.get("data_refs") or []:
        refs.append({"kind": "data_ref", "label": str(ref), "ref": str(ref)})
    for gap in gaps:
        for ref in gap.get("evidence_refs") or []:
            refs.append({"kind": "evidence_ref", "label": str(ref), "ref": str(ref)})

    seen: set[str] = set()
    unique: List[Dict[str, Any]] = []
    for ref in refs:
        key = f"{ref.get('kind')}:{ref.get('ref')}"
        if key in seen:
            continue
        seen.add(key)
        unique.append(ref)
    return unique[:5]


def _knowledge_target_for_prompt(context_snapshot: Optional[Dict[str, Any]]) -> str:
    context_snapshot = context_snapshot or {}
    environment_state = context_snapshot.get("environment_state") or {}
    target = (
        environment_state.get("collection")
        or context_snapshot.get("name")
        or "la base de connaissances connectée"
    )
    if target == "la base de connaissances connectée":
        return target
    return f"la base de connaissances « {target} »"


def _question_for_gap(
    gap: Dict[str, Any],
    objective: str,
    context_snapshot: Optional[Dict[str, Any]] = None,
) -> str:
    title = gap.get("title", "Knowledge gap")
    knowledge_target = _knowledge_target_for_prompt(context_snapshot)
    if gap.get("slug") == "decision_rationale":
        return (
            f"Au regard de {knowledge_target}, quelle décision métier ou terrain "
            "reste difficile à retrouver dans la documentation, et comment "
            "l’expert la prend-il en pratique ?"
        )
    if gap.get("slug") == "exception_handling":
        return "Dans quels cas la procédure documentée ne suffit-elle pas, et comment décidez-vous quoi faire ?"
    if gap.get("slug") == "signals_and_symptoms":
        return "Quels signaux faibles ou symptômes vous font changer de diagnostic ou de recommandation ?"
    if gap.get("slug") == "source_provenance":
        return "Quelles sources ou traces utilisez-vous pour confirmer cette connaissance ?"
    if gap.get("slug") == "validation_and_ownership":
        return "Qui devrait valider cette connaissance avant qu’elle soit ajoutée à la base ?"
    return f"Qu’est-ce qui manque encore pour rendre « {title} » exploitable par un autre expert ?"


def _followups_for_gap(gap: Dict[str, Any]) -> List[str]:
    common = [
        "Pouvez-vous donner un exemple concret ?",
        "Quel indice vous fait choisir cette option ?",
        "Comment un nouvel arrivant pourrait-il vérifier cela ?",
    ]
    if gap.get("slug") == "source_provenance":
        return ["Dans quel document ou système chercher cette preuve ?", "La source est-elle à jour et validée ?"]
    if gap.get("slug") == "exception_handling":
        return ["Quelle exception arrive le plus souvent ?", "Quelle erreur faut-il absolument éviter ?"]
    return common


def evaluate_expert_answer(
    *,
    answer: str,
    question: Optional[Dict[str, Any]] = None,
    gap: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    tokens = _words(answer)
    word_count = len(tokens)
    lower = (answer or "").lower()
    has_reason = any(marker in lower for marker in ("parce que", "car ", "donc", "why", "because", "afin de"))
    has_example = any(marker in lower for marker in ("exemple", "cas ", "lorsque", "quand", "sur ", "client", "machine"))
    has_source = any(marker in lower for marker in ("document", "rapport", "crm", "sharepoint", "source", "ticket", "email"))
    uncertainty = any(marker in lower for marker in ("je ne sais", "pas sûr", "incertain", "à vérifier", "i don't know"))
    contradiction = any(marker in lower for marker in ("contrairement", "mais en réalité", "en fait", "contradiction"))

    score = 0.25
    if word_count >= 25:
        score += 0.25
    elif word_count >= 12:
        score += 0.12
    if has_reason:
        score += 0.18
    if has_example:
        score += 0.16
    if has_source:
        score += 0.10
    if uncertainty:
        score -= 0.18
    score = max(0.0, min(score, 1.0))

    if contradiction:
        verdict = "contradiction_or_update"
    elif score >= 0.68:
        verdict = "sufficient"
    elif uncertainty or word_count < 12:
        verdict = "needs_precision"
    else:
        verdict = "partial"

    return {
        "id": str(uuid.uuid4()),
        "gap_id": (gap or {}).get("id") or (question or {}).get("target_gap_id"),
        "question_id": (question or {}).get("id"),
        "verdict": verdict,
        "score": round(score, 2),
        "signals": {
            "word_count": word_count,
            "has_reason": has_reason,
            "has_example": has_example,
            "has_source": has_source,
            "uncertainty": uncertainty,
            "contradiction": contradiction,
        },
        "follow_up": None,
        "relance": {"kind": None, "text": None},
    }


def classify_conversation_intent(
    *,
    text: str,
    last_proposal: Optional[KnowledgeUpdateProposal] = None,
) -> Dict[str, Any]:
    clean = (text or "").strip()
    lower = clean.lower()
    words = _words(clean)

    has_positive = any(term in lower for term in POSITIVE_CONFIRMATION_TERMS)
    has_negative = any(term in lower for term in NEGATIVE_CONFIRMATION_TERMS)
    has_proposal = any(term in lower for term in PROPOSAL_REQUEST_TERMS)
    has_correction = any(term in lower for term in CORRECTION_TERMS)
    has_more_detail = any(term in lower for term in MORE_DETAIL_TERMS)
    has_defer = any(term in lower for term in DEFER_VOCAL_TERMS)
    active_proposal = last_proposal if last_proposal and last_proposal.status == "pending_review" else None
    proposal_confirmed = _proposal_conversation_confirmed(active_proposal)

    if has_defer and not has_proposal:
        return {"intent": "defer_vocal", "confidence": 0.86, "signals": {"term": "defer"}}

    if any(term in lower for term in SESSION_END_TERMS):
        return {"intent": "session_complete", "confidence": 0.91, "signals": {"term": "session_end"}}

    if active_proposal and has_positive:
        if proposal_confirmed:
            has_final_acceptance = any(term in lower for term in FINAL_ACCEPTANCE_TERMS)
            intent = "accept_confirmed" if has_final_acceptance else "proposal_confirmed"
            confidence = 0.92 if has_final_acceptance else 0.70
            return {
                "intent": intent,
                "confidence": confidence,
                "signals": {
                    "proposal_confirmed": proposal_confirmed,
                    "final_acceptance": has_final_acceptance,
                },
            }
        return {"intent": "proposal_confirmed", "confidence": 0.92, "signals": {"proposal_confirmed": proposal_confirmed}}
    if active_proposal and has_negative:
        intent = "accept_rejected" if proposal_confirmed else "proposal_rejected"
        return {"intent": intent, "confidence": 0.90, "signals": {"proposal_confirmed": proposal_confirmed}}
    if has_proposal:
        return {"intent": "proposal_requested", "confidence": 0.88, "signals": {"term": "proposal"}}
    if has_correction:
        return {"intent": "correction", "confidence": 0.84, "signals": {"term": "correction"}}
    if has_more_detail:
        return {"intent": "more_detail", "confidence": 0.74, "signals": {"term": "more_detail"}}
    if len(words) >= 8:
        return {"intent": "answer_ready", "confidence": 0.72, "signals": {"word_count": len(words)}}
    return {"intent": "more_detail", "confidence": 0.45, "signals": {"word_count": len(words)}}


def _clean_conversation_fact_text(text: str, intent: str) -> str:
    """Remove voice-control utterances before a transcript becomes a fact."""
    clean = (text or "").strip()
    if not clean or is_capture_text_noise(clean):
        return ""

    segments = re.split(r"(?<=[.!?])\s+", clean)
    kept: List[str] = []
    for segment in segments:
        part = segment.strip(" ,;:")
        if not part:
            continue
        lower = part.lower()
        if any(term in lower for term in VOICE_CONTROL_TERMS):
            continue
        if intent in {"proposal_requested", "proposal_confirmed", "accept_confirmed"}:
            if any(term in lower for term in PROPOSAL_REQUEST_TERMS):
                part = _strip_proposal_request_clause(part).strip(" ,;:")
        if any(term in part.lower() for term in POSITIVE_CONFIRMATION_TERMS) and len(_words(part)) <= 5:
            continue
        if any(term in part.lower() for term in NEGATIVE_CONFIRMATION_TERMS) and len(_words(part)) <= 5:
            continue
        part = _strip_leading_discourse_markers(part)
        part = re.sub(r"\b(?:euh|heu|hum)\b", " ", part, flags=re.IGNORECASE)
        part = re.sub(r"\s+", " ", part).strip(" ,;:")
        if part:
            kept.append(part)

    return " ".join(kept).strip()


def _strip_leading_discourse_markers(text: str) -> str:
    out = text.strip()
    marker_pattern = "|".join(re.escape(marker) for marker in LEADING_DISCOURSE_MARKERS)
    while True:
        stripped = re.sub(
            rf"^(?:{marker_pattern})[\s,;:.-]+",
            "",
            out,
            count=1,
            flags=re.IGNORECASE,
        ).strip()
        if stripped == out:
            return out
        out = stripped


def _strip_proposal_request_clause(text: str) -> str:
    out = text
    proposal_patterns = [
        r"\b(?:crée|cree|créer|creer|prépare|prepare|préparer|preparer)\s+la\s+proposition\b.*$",
        r"\b(?:crée|cree|créer|creer|prépare|prepare|préparer|preparer)\s+proposition\b.*$",
        r"\bconclu(?:re|s|ez)?\s+(?:par|pas)?\s*(?:crée|cree|créer|creer)\s+la\s+proposition\b.*$",
        r"\bon\s+peut\s+(?:faire|créer|creer)\s+une\s+proposition\b.*$",
        r"\bje\s+pense\s+qu['’]?\s*on\s+peut\s+.*proposition\b.*$",
        r"\bon\s+peut\s+conclure\b.*$",
        r"\b(?:synthèse|synthese)\b.*$",
    ]
    for pattern in proposal_patterns:
        out = re.sub(pattern, "", out, flags=re.IGNORECASE).strip(" ,;:")
    return out


def is_capture_text_noise(text: str) -> bool:
    """Detect STT hallucinations/control-only text before they become knowledge."""
    clean = (text or "").strip()
    if not clean:
        return False
    if _looks_like_stt_hallucination(clean):
        return True
    return False


def _looks_like_stt_hallucination(text: str) -> bool:
    lowered = (text or "").lower()
    if any(term in lowered for term in _STT_HALLUCINATION_TERMS):
        return True
    letters = [char for char in text if char.isalpha()]
    if not letters:
        return False
    cyrillic = sum(1 for char in letters if "\u0400" <= char <= "\u04ff")
    latin = sum(1 for char in letters if ("A" <= char <= "Z") or ("a" <= char <= "z") or ("\u00c0" <= char <= "\u024f"))
    if cyrillic >= 8 and cyrillic / max(1, len(letters)) >= 0.18:
        return True
    return cyrillic >= 4 and latin == 0 and len(letters) >= 8


def _sanitize_capture_fact_text(text: str) -> str:
    clean = (text or "").strip()
    if not clean or is_capture_text_noise(clean) or _is_voice_control_residue(clean):
        return ""
    clean = _strip_proposal_request_clause(clean).strip(" ,;:")
    if not clean or is_capture_text_noise(clean) or _is_voice_control_residue(clean):
        return ""
    return clean


def _is_voice_control_residue(text: str) -> bool:
    lower = re.sub(r"\s+", " ", (text or "").strip().lower().strip(" .,!?:;"))
    if lower in {"conclure pas", "conclure par", "créer la proposition", "creer la proposition", "crée la proposition", "cree la proposition"}:
        return True
    words = _words(lower)
    return len(words) <= 4 and any(term in lower for term in ("proposition", "conclure", "valider le plan"))


def _sanitize_captured_fact(fact: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    text = _sanitize_capture_fact_text(str(fact.get("text") or fact.get("statement") or ""))
    if not text:
        return None
    cleaned = dict(fact)
    cleaned["text"] = text
    cleaned["statement"] = text
    return cleaned


def _sanitize_captured_facts(facts: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    cleaned: List[Dict[str, Any]] = []
    for fact in facts:
        item = _sanitize_captured_fact(fact)
        if item:
            cleaned.append(item)
    return cleaned


def process_conversation_step(
    db: DBSession,
    *,
    workspace_id: str,
    session_id: str,
    client_turn_id: Optional[str],
    text: str,
    question_id: Optional[str],
    retrieval_event_id: Optional[str],
    interruption_of_event_id: Optional[str],
    last_proposal_id: Optional[str],
    actor_user_id: Optional[str] = None,
    actor_label: Optional[str] = None,
    contradiction_candidates: Optional[List[Dict[str, Any]]] = None,
    proposal_acceptance_validator: Optional[Callable[[KnowledgeUpdateProposal], None]] = None,
) -> Dict[str, Any]:
    session = get_session(db, workspace_id=workspace_id, session_id=session_id)
    last_proposal = _load_active_proposal(
        db,
        workspace_id=workspace_id,
        proposal_id=last_proposal_id,
        session_id=session_id,
    )
    classification = classify_conversation_intent(text=text, last_proposal=last_proposal)
    intent = classification["intent"]
    confidence = classification["confidence"]
    fact_text = _clean_conversation_fact_text(text, intent)
    stt_noise_ignored = is_capture_text_noise(text)
    action_taken = "none"
    next_prompt: Optional[str] = None
    proposal: Optional[KnowledgeUpdateProposal] = None
    requires_confirmation = False
    confirmation_target: Optional[str] = None
    turn_payload: Optional[Dict[str, Any]] = None

    if stt_noise_ignored:
        action_taken = "stt_noise_ignored"
        confidence = min(confidence, 0.25)
        next_prompt = "Je n’ai pas compris cette prise de parole. Pouvez-vous reformuler en français ?"
    elif intent in {"answer_ready", "correction", "more_detail"}:
        turn_kind = "correction" if intent == "correction" else ("complement" if intent == "more_detail" else "answer")
        turn_payload = append_turn(
            db,
            workspace_id=workspace_id,
            session_id=session_id,
            speaker="expert",
            text=fact_text or text,
            question_id=question_id,
            client_turn_id=client_turn_id,
            retrieval_event_id=retrieval_event_id,
            interruption_of_event_id=interruption_of_event_id,
            turn_kind=turn_kind,
            actor_user_id=actor_user_id,
            contradiction_candidates=contradiction_candidates,
        )
        action_taken = "turn_appended"
        next_prompt = turn_payload.get("next_prompt")
    elif intent == "proposal_requested":
        if _has_substantive_answer_text(fact_text):
            turn_payload = append_turn(
                db,
                workspace_id=workspace_id,
                session_id=session_id,
                speaker="expert",
                text=fact_text,
                question_id=question_id,
                client_turn_id=client_turn_id,
                retrieval_event_id=retrieval_event_id,
                interruption_of_event_id=interruption_of_event_id,
                turn_kind="answer",
                actor_user_id=actor_user_id,
                contradiction_candidates=contradiction_candidates,
            )
        session = get_session(db, workspace_id=workspace_id, session_id=session_id)
        if _session_has_proposal_material(db, workspace_id=workspace_id, session=session):
            proposal = create_update_proposal(
                db,
                workspace_id=workspace_id,
                session_id=session_id,
                complete_session=False,
                created_by_user_id=actor_user_id,
            )
            action_taken = "proposal_created"
            requires_confirmation = True
            confirmation_target = "proposal"
            next_prompt = (
                "J’ai préparé la proposition de mise à jour. Dites « oui je confirme » "
                "pour la confirmer, ou « non corrige » pour la retravailler."
            )
        else:
            action_taken = "proposal_deferred_insufficient_facts"
            next_prompt = (
                "Je n’ai pas encore assez de matière pour préparer une proposition utile. "
                "Donnez d’abord une décision experte concrète ou une correction à capturer."
            )
    elif intent == "proposal_confirmed":
        proposal = last_proposal
        if not proposal:
            raise ValueError("No proposal available to confirm")
        _mark_proposal_conversation_state(
            proposal,
            state="proposal_confirmed",
            note="Confirmed by conversation-only voice flow.",
        )
        db.commit()
        db.refresh(proposal)
        action_taken = "proposal_confirmed"
        requires_confirmation = True
        confirmation_target = "acceptance"
        next_prompt = "Proposition confirmée. Dites « oui valide » pour l’accepter définitivement."
    elif intent == "proposal_rejected":
        proposal = last_proposal
        if proposal:
            _mark_proposal_conversation_state(
                proposal,
                state="proposal_rejected",
                note="Rejected by conversation-only voice flow.",
            )
            db.commit()
            db.refresh(proposal)
        action_taken = "proposal_rejected"
        next_prompt = "D’accord, la proposition reste en attente. Donnez la correction à intégrer."
    elif intent == "accept_confirmed":
        if not last_proposal:
            raise ValueError("No proposal available to accept")
        if proposal_acceptance_validator:
            proposal_acceptance_validator(last_proposal)
        proposal = review_proposal(
            db,
            workspace_id=workspace_id,
            proposal_id=last_proposal.id,
            status="accepted",
            reviewer=actor_label or "conversation-only",
            reviewer_user_id=actor_user_id,
            review_notes="Accepted by explicit voice confirmation.",
        )
        action_taken = "proposal_accepted"
        next_prompt = "La proposition est acceptée."
    elif intent == "accept_rejected":
        proposal = last_proposal
        action_taken = "acceptance_rejected"
        next_prompt = "D’accord, je ne valide pas encore. Indiquez ce qu’il faut corriger."
    elif intent == "defer_vocal":
        hint_payload = defer_active_hint(
            db,
            workspace_id=workspace_id,
            session_id=session_id,
            deferred_reason="end_of_session",
            actor_user_id=actor_user_id,
        )
        if hint_payload:
            action_taken = "hint_deferred"
            next_prompt = "D’accord, on reprendra ce point plus tard."
        else:
            quality_payload = defer_open_quality_from_voice(
                db,
                workspace_id=workspace_id,
                session_id=session_id,
                deferred_reason="end_of_session",
                actor_user_id=actor_user_id,
            )
            if quality_payload:
                action_taken = "quality_item_deferred"
                session = get_session(db, workspace_id=workspace_id, session_id=session_id)
                metrics = dict(session.metrics or {})
                if quality_payload.get("question_id"):
                    metrics["focused_quality_question_id"] = quality_payload["question_id"]
                if quality_payload.get("evaluation_id"):
                    metrics["focused_quality_evaluation_id"] = quality_payload["evaluation_id"]
                session.metrics = metrics
                flag_modified(session, "metrics")
                db.commit()
                next_prompt = "Point reporté en fin de session."
            else:
                action_taken = "defer_no_target"
                next_prompt = "Rien à reporter pour l’instant."
    elif intent == "session_complete":
        closure = generate_session_closure_sheet(
            db,
            workspace_id=workspace_id,
            session_id=session_id,
            actor_user_id=actor_user_id,
        )
        action_taken = "closure_sheet_generated"
        requires_confirmation = True
        confirmation_target = "session_closure"
        next_prompt = None

    session = get_session(db, workspace_id=workspace_id, session_id=session_id)
    _record_capture_event(
        db,
        session=session,
        event_type="conversation_intent_detected",
        speaker="expert",
        question_id=question_id,
        text_raw=text,
        source="conversation_only",
        status="accepted",
        parent_event_id=interruption_of_event_id or retrieval_event_id,
        meta_data={
            "intent": intent,
            "confidence": confidence,
            "action_taken": action_taken,
            "client_turn_id": client_turn_id,
            "retrieval_event_id": retrieval_event_id,
            "last_proposal_id": last_proposal_id,
            "requires_confirmation": requires_confirmation,
            "confirmation_target": confirmation_target,
            "signals": classification.get("signals") or {},
            "fact_text": fact_text,
        },
    )
    db.commit()
    db.refresh(session)
    if proposal:
        db.refresh(proposal)
    closure_sheet = None
    if action_taken == "closure_sheet_generated":
        session = get_session(db, workspace_id=workspace_id, session_id=session_id)
        closure_sheet = build_session_closure_sheet(
            session,
            list_capture_events(db, workspace_id=workspace_id, session_id=session_id),
        )
    return {
        "intent": intent,
        "confidence": confidence,
        "action_taken": action_taken,
        "session": serialize_session(session),
        "proposal": serialize_proposal(proposal) if proposal else None,
        "turn": (turn_payload or {}).get("turn"),
        "evaluation": (turn_payload or {}).get("evaluation"),
        "next_prompt": next_prompt,
        "next_question_id": (turn_payload or {}).get("next_question_id"),
        "system_prompt_event_id": (turn_payload or {}).get("system_prompt_event_id"),
        "requires_confirmation": requires_confirmation,
        "confirmation_target": confirmation_target,
        "closure_sheet": closure_sheet,
    }


def _select_follow_up(
    question: Optional[Dict[str, Any]],
    *,
    has_reason: bool,
    has_example: bool,
    has_source: bool,
) -> str:
    if not has_reason:
        return "Qu’est-ce qui justifie ce choix dans la pratique ?"
    if not has_example:
        return "Pouvez-vous illustrer avec un cas réel ou typique ?"
    if not has_source:
        return "Quelle source ou trace permettrait de valider cette réponse ?"
    follow_ups = (question or {}).get("follow_ups") or []
    return follow_ups[0] if follow_ups else "Quelle précision manque encore pour rendre cette réponse réutilisable ?"


def build_relance(
    *,
    answer: str,
    evaluation: Dict[str, Any],
    question: Optional[Dict[str, Any]] = None,
    topic_label: Optional[str] = None,
    contradiction_candidates: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Optional[str]]:
    """Build a non-blocking live suggestion from the latest expert answer."""
    del answer, topic_label
    for candidate in contradiction_candidates or []:
        if not isinstance(candidate, dict):
            continue
        hint = str(candidate.get("suggested_hint") or candidate.get("hint") or candidate.get("text") or "").strip()
        if hint:
            return {"kind": "contradiction", "text": hint}

    verdict = str(evaluation.get("verdict") or "")
    if verdict == "contradiction_or_update":
        return {"kind": "contradiction", "text": "Clarifier ce qui contredit ou met à jour la source existante."}
    if verdict not in {"needs_precision", "partial"}:
        return {"kind": None, "text": None}

    signals = evaluation.get("signals") if isinstance(evaluation.get("signals"), dict) else {}
    follow_up = _select_follow_up(
        question,
        has_reason=bool(signals.get("has_reason")),
        has_example=bool(signals.get("has_example")),
        has_source=bool(signals.get("has_source")),
    )
    return {"kind": "relance", "text": follow_up}


def relance_to_suggestions(relance: Optional[Dict[str, Optional[str]]]) -> List[Dict[str, str]]:
    if not relance:
        return []
    text = str(relance.get("text") or "").strip()
    if not text:
        return []
    kind = str(relance.get("kind") or "relance")
    return [
        {
            "kind": kind,
            "text": text,
        }
    ]


def format_retrieval_chunks(
    chunks: Optional[List[str]],
    metadatas: Optional[List[Dict[str, Any]]] = None,
    scores: Optional[List[float]] = None,
) -> List[Dict[str, Any]]:
    """Shape live retrieval chunks for the oracle payload, preserving the metadata
    that powers the existing document source-preview (document_id/source_id +
    collection)."""
    metadatas = metadatas or []
    scores = scores or []
    formatted: List[Dict[str, Any]] = []
    for index, chunk in enumerate(chunks or []):
        md = metadatas[index] if index < len(metadatas) and isinstance(metadatas[index], dict) else {}
        formatted.append(
            {
                "rank": index + 1,
                "text": str(chunk),
                "preview": str(chunk)[:360],
                "score": scores[index] if index < len(scores) else None,
                "document_id": md.get("document_id") or md.get("doc_id") or md.get("id"),
                "source_id": md.get("source_id") or md.get("source"),
                "source": md.get("source") or md.get("filename") or md.get("document_id"),
                "title": md.get("title") or md.get("filename") or md.get("source"),
                "collection": md.get("collection") or md.get("collection_name"),
                "metadata": md,
            }
        )
    return formatted


def structure_capture_payload(
    session: ExpertCaptureSession,
    transcript_events: Optional[List[ExpertCaptureEvent]] = None,
) -> Dict[str, Any]:
    transcript = session.transcript or []
    evaluations = session.evaluations or []
    expert_turns = [turn for turn in transcript if turn.get("speaker") == "expert"]
    captured = [_fact_from_turn(turn, evaluations) for turn in expert_turns]
    event_rows = transcript_events or []
    captured = _merge_event_facts(captured, _facts_from_events(event_rows, evaluations))
    captured = _sanitize_captured_facts(captured)
    event_evidence = [_serialize_event(event) for event in event_rows]
    amendments = [
        _serialize_event(event)
        for event in event_rows
        if event.event_type == "transcript_amended" or event.text_amended
    ]

    open_questions = [
        {
            "gap_id": ev.get("gap_id"),
            "reason": ev.get("verdict"),
            "follow_up": ev.get("follow_up"),
        }
        for ev in evaluations
        if ev.get("verdict") != "sufficient"
    ]
    from app.services.capture_report_templates import (
        build_knowledge_sheet_content,
        resolve_knowledge_sheet_template,
    )

    template_id = resolve_knowledge_sheet_template(session)
    markdown = build_knowledge_sheet_content(
        template_id,
        session,
        captured,
        open_questions,
        transcript=transcript,
    )
    transcript_segments = _build_transcript_segments(transcript, event_rows)
    return {
        "session_id": session.id,
        "title": session.title,
        "objective": session.objective,
        "context_id": session.context_id,
        "captured_facts": captured,
        "open_questions": open_questions,
        "transcript": [],
        "transcript_events": [],
        "transcript_segments": transcript_segments,
        "amendments": amendments,
        "knowledge_sheet_template": template_id,
        "report_markdown": markdown,
        "recommended_ingestion": {
            "title": f"Expert capture - {session.title}",
            "content": markdown,
            "metadata": {
                "source": "expert_capture_session",
                "session_id": session.id,
                "voice_runtime": session.voice_runtime,
                "event_count": len(event_evidence),
                "amendment_count": len(amendments),
                "knowledge_sheet_template": template_id,
            },
        },
        "audit": {
            "event_count": len(event_evidence),
            "amendment_count": len(amendments),
            "source_of_truth": "expert_capture_events",
        },
        "review": {
            "required": True,
            "reason": "Expert captures can change operational knowledge and must be validated before ingestion.",
        },
    }


_TRANSCRIPT_SEGMENT_EVENT_TYPES = {
    "expert_turn_finalized",
    "stt_final",
    "transcript_turn_recorded",
    "transcript_amended",
}


def _build_transcript_segments(
    transcript: List[Dict[str, Any]],
    event_rows: List[ExpertCaptureEvent],
) -> List[Dict[str, Any]]:
    """Compact audit contract for raw/refined/amended transcript segments."""

    segments: List[Dict[str, Any]] = []
    seen_event_ids: set[str] = set()
    for index, turn in enumerate(transcript or [], start=1):
        raw = str(turn.get("text_raw") or turn.get("text") or "").strip()
        refined = str(turn.get("text") or raw).strip()
        amended = str(turn.get("text_amended") or "").strip()
        text = amended or refined or raw
        if not text:
            continue
        source_event_id = str(turn.get("source_event_id") or "").strip() or None
        if source_event_id:
            seen_event_ids.add(source_event_id)
        segments.append(
            {
                "id": str(turn.get("id") or f"turn-{index:03d}"),
                "source": "session_transcript",
                "source_event_id": source_event_id,
                "speaker": turn.get("speaker") or "expert",
                "status": "amended" if amended else "refined",
                "raw_segment": raw or None,
                "refined_segment": refined or None,
                "amended_segment": amended or None,
                "text": text,
                "turn_kind": turn.get("turn_kind") or "answer",
                "topic_id": turn.get("topic_id"),
                "subtopic_id": turn.get("subtopic_id"),
                "topic_path": turn.get("topic_path"),
            }
        )

    for event in sorted(event_rows or [], key=lambda item: (item.sequence, item.created_at)):
        if event.id in seen_event_ids:
            continue
        if event.event_type not in _TRANSCRIPT_SEGMENT_EVENT_TYPES and not event.text_amended:
            continue
        raw = str(event.text_raw or "").strip()
        amended = str(event.text_amended or "").strip()
        text = amended or raw
        if not text:
            continue
        status = "amended" if amended or event.event_type == "transcript_amended" else "refined"
        segments.append(
            {
                "id": event.id,
                "source": "event_ledger",
                "source_event_id": event.id,
                "speaker": event.speaker or "expert",
                "status": status,
                "raw_segment": raw or None,
                "refined_segment": None if amended else text,
                "amended_segment": amended or None,
                "text": text,
                "turn_kind": (event.meta_data or {}).get("turn_kind") or "answer",
                "topic_id": (event.meta_data or {}).get("topic_id"),
                "subtopic_id": (event.meta_data or {}).get("subtopic_id"),
                "topic_path": (event.meta_data or {}).get("topic_path"),
                "created_at": event.created_at.isoformat() if event.created_at else None,
            }
        )
    return segments


_PUBLICATION_CATEGORIES = {"technical", "commercial", "innovation", "maintenance", "operation", "other"}


def _suggest_publication_category(session: ExpertCaptureSession, payload: Dict[str, Any]) -> str:
    metrics = session.metrics or {}
    domain = str(metrics.get("capture_domain") or "").strip().lower()
    if domain in _PUBLICATION_CATEGORIES:
        return domain
    recommended = payload.get("recommended_ingestion") if isinstance(payload.get("recommended_ingestion"), dict) else {}
    text = " ".join(
        [
            str(session.title or ""),
            str(session.objective or ""),
            str(payload.get("title") or ""),
            str(payload.get("report_markdown") or ""),
            str(recommended.get("content") or ""),
        ]
    ).lower()
    category_terms = [
        ("commercial", ("commercial", "client", "marché", "market", "sales", "account", "offre", "devis")),
        ("innovation", ("innovation", "prototype", "r&d", "recherche", "roadmap", "essai", "pilote")),
        ("maintenance", ("maintenance", "entretien", "dépannage", "troubleshoot", "repair", "inspection")),
        ("operation", ("operation", "opération", "process", "procédé", "production", "runbook", "exploitation")),
    ]
    for category, terms in category_terms:
        if any(term in text for term in terms):
            return category
    return "technical"


def _apply_publication_defaults(
    payload: Dict[str, Any],
    *,
    session: ExpertCaptureSession,
    ctx: Optional[Context],
    previous_publication: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    publication = dict(previous_publication or {})
    existing = payload.get("publication")
    if isinstance(existing, dict):
        publication.update(existing)
    category = _clean_optional_string(publication.get("category")) or _suggest_publication_category(session, payload)
    destination = (
        _clean_optional_string(publication.get("destination"))
        or _clean_optional_string(publication.get("destination_scope"))
        or _resolve_collection_name(ctx)
    )
    recommended = payload.get("recommended_ingestion") if isinstance(payload.get("recommended_ingestion"), dict) else {}
    final_title = (
        _clean_optional_string(publication.get("final_title"))
        or _clean_optional_string(recommended.get("title"))
        or _clean_optional_string(payload.get("title"))
        or session.title
    )
    publication.update(
        {
            "category": category,
            "destination": destination,
            "destination_scope": destination,
            "final_title": final_title,
            "include_unresolved_questions": True,
            "suggested": bool(not previous_publication),
        }
    )
    payload["publication"] = publication
    metadata = dict(recommended.get("metadata") or {})
    metadata.setdefault("publication_category_suggested", category)
    metadata.setdefault("publication_destination_suggested", destination)
    metadata.setdefault("publication_destination_scope_suggested", destination)
    recommended["metadata"] = metadata
    payload["recommended_ingestion"] = recommended
    return payload


def _fact_from_turn(turn: Dict[str, Any], evaluations: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    related = next((ev for ev in evaluations if ev.get("turn_id") == turn.get("id")), None)
    turn_kind = turn.get("turn_kind") or "answer"
    text = turn.get("text", "")
    return {
        "id": f"fact-{turn.get('id')}",
        "type": _proposal_fact_type(turn_kind, bool(turn.get("text_amended"))),
        "status": "pending",
        "text": text,
        "statement": text,
        "source": "expert_session",
        "source_event_id": turn.get("source_event_id"),
        "retrieval_event_id": turn.get("retrieval_event_id"),
        "retrieval_refs": turn.get("retrieval_refs") or [],
        "interruption_of_event_id": turn.get("interruption_of_event_id"),
        "turn_kind": turn_kind,
        "topic_id": turn.get("topic_id") or (related or {}).get("topic_id"),
        "subtopic_id": turn.get("subtopic_id") or (related or {}).get("subtopic_id"),
        "topic_path": turn.get("topic_path") or (related or {}).get("topic_path"),
        "raw_text": turn.get("text_raw") or turn.get("text"),
        "amended_text": turn.get("text_amended"),
        "amended": bool(turn.get("text_amended")),
        "confidence": (related or {}).get("score", 0.5),
        "needs_review": True,
    }


def _facts_from_events(
    event_rows: List[ExpertCaptureEvent],
    evaluations: Iterable[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Recover proposal facts from the event ledger when no finalized turn exists.

    This keeps demos robust when an operator amends a live transcript and
    immediately creates a proposal without pressing the explicit evaluation
    button first.
    """
    if not event_rows:
        return []

    by_id = {event.id: event for event in event_rows}
    latest_by_key: Dict[str, ExpertCaptureEvent] = {}
    transcript_types = {
        "expert_turn_finalized",
        "stt_final",
        "transcript_turn_recorded",
        "transcript_amended",
    }
    fallback_types = {"stt_partial"}
    for event in sorted(event_rows, key=lambda item: (item.sequence, item.created_at)):
        text = _effective_event_text(event)
        if not text:
            continue
        if event.event_type.startswith("retrieval_") or event.event_type == "system_prompt_prepared":
            continue
        if event.event_type not in transcript_types and not (event.event_type in fallback_types and event.text_amended):
            continue
        if event.speaker and event.speaker != "expert":
            continue
        key = _event_text_key(event, by_id)
        current = latest_by_key.get(key)
        if current is None or _event_fact_priority(event) >= _event_fact_priority(current):
            latest_by_key[key] = event

    retrieval_by_client = _latest_retrieval_by_client_turn(event_rows)
    facts: List[Dict[str, Any]] = []
    for event in sorted(latest_by_key.values(), key=lambda item: item.sequence):
        text = _effective_event_text(event)
        if not text:
            continue
        related = next((ev for ev in evaluations if ev.get("question_id") == event.question_id), None)
        client_turn_id = _event_client_turn_id(event, by_id)
        retrieval_event = retrieval_by_client.get(client_turn_id or "")
        turn_kind = (event.meta_data or {}).get("turn_kind") or "answer"
        facts.append(
            {
                "id": f"fact-event-{event.id}",
                "type": _proposal_fact_type(turn_kind, bool(event.text_amended or event.event_type == "transcript_amended")),
                "status": "pending",
                "text": text,
                "statement": text,
                "source": "expert_event_ledger",
                "source_event_id": event.id,
                "retrieval_event_id": retrieval_event.id if retrieval_event else None,
                "retrieval_refs": _retrieval_refs_from_event(retrieval_event) if retrieval_event else [],
                "interruption_of_event_id": event.parent_event_id,
                "turn_kind": turn_kind,
                "raw_text": event.text_raw or text,
                "amended_text": event.text_amended,
                "amended": bool(event.text_amended or event.event_type == "transcript_amended"),
                "confidence": (related or {}).get("score", 0.5),
                "needs_review": True,
            }
        )
    return facts


def _proposal_fact_type(turn_kind: str, amended: bool) -> str:
    if amended or turn_kind == "correction":
        return "update"
    if turn_kind == "complement":
        return "detail"
    return "new"


def _merge_event_facts(
    transcript_facts: List[Dict[str, Any]],
    event_facts: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    merged: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for fact in [*transcript_facts, *event_facts]:
        text = (fact.get("text") or "").strip()
        if not text:
            continue
        key = re.sub(r"\s+", " ", text.lower())
        if key in seen:
            continue
        seen.add(key)
        merged.append(fact)
    return merged


def _event_fact_priority(event: ExpertCaptureEvent) -> int:
    if event.event_type == "transcript_amended":
        return 50
    if event.event_type == "expert_turn_finalized":
        return 40
    if event.event_type == "stt_final":
        return 30
    if event.text_amended:
        return 20
    return 10


def _event_client_turn_id(
    event: ExpertCaptureEvent,
    by_id: Dict[str, ExpertCaptureEvent],
) -> Optional[str]:
    meta = event.meta_data or {}
    client_turn_id = meta.get("client_turn_id")
    if client_turn_id:
        return str(client_turn_id)
    parent = by_id.get(event.parent_event_id or "")
    if parent:
        return _event_client_turn_id(parent, by_id)
    return None


def _event_text_key(
    event: ExpertCaptureEvent,
    by_id: Dict[str, ExpertCaptureEvent],
) -> str:
    client_turn_id = _event_client_turn_id(event, by_id)
    if client_turn_id:
        return f"client:{client_turn_id}"
    if event.parent_event_id:
        return f"parent:{event.parent_event_id}"
    if event.question_id:
        return f"question:{event.question_id}"
    return f"event:{event.id}"


def _latest_retrieval_by_client_turn(
    event_rows: List[ExpertCaptureEvent],
) -> Dict[str, ExpertCaptureEvent]:
    out: Dict[str, ExpertCaptureEvent] = {}
    for event in event_rows:
        if event.event_type != "retrieval_prefetch_completed":
            continue
        client_turn_id = (event.meta_data or {}).get("client_turn_id")
        if not client_turn_id:
            continue
        current = out.get(str(client_turn_id))
        if current is None or event.sequence > current.sequence:
            out[str(client_turn_id)] = event
    return out


def _retrieval_refs_from_event(event: Optional[ExpertCaptureEvent]) -> List[Dict[str, Any]]:
    if not event:
        return []
    meta = event.meta_data or {}
    chunks = meta.get("chunks") or []
    scores = meta.get("scores") or []
    metadatas = meta.get("metadatas") or []
    refs: List[Dict[str, Any]] = []
    for index, chunk in enumerate(chunks[:4]):
        md = metadatas[index] if index < len(metadatas) and isinstance(metadatas[index], dict) else {}
        refs.append(
            {
                "event_id": event.id,
                "rank": index + 1,
                "score": scores[index] if index < len(scores) else None,
                "title": md.get("title") or md.get("filename") or md.get("source"),
                "source": md.get("source") or md.get("document_id") or md.get("filename"),
                "preview": str(chunk)[:360],
                "metadata": md,
            }
        )
    return refs


def _structure_facts_by_plan(
    plan: Dict[str, Any],
    captured_facts: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Group captured facts under the plan's topics/subtopics so the plan can act as
    the final structuring frame. Facts that do not map to any plan node are returned
    under ``unassigned``."""
    topics = (plan or {}).get("topics") or []
    facts = list(captured_facts or [])
    assigned: set[int] = set()
    structured_topics: List[Dict[str, Any]] = []
    for topic in topics:
        if not isinstance(topic, dict):
            continue
        topic_id = topic.get("id")
        subtopic_nodes: List[Dict[str, Any]] = []
        for subtopic in topic.get("subtopics") or []:
            if not isinstance(subtopic, dict):
                continue
            subtopic_id = subtopic.get("id")
            sub_facts = [fact for fact in facts if fact.get("subtopic_id") == subtopic_id]
            for fact in sub_facts:
                assigned.add(id(fact))
            subtopic_nodes.append(
                {
                    "subtopic_id": subtopic_id,
                    "title": subtopic.get("title"),
                    "prompt": subtopic.get("prompt"),
                    "facts": sub_facts,
                }
            )
        topic_facts = [
            fact
            for fact in facts
            if fact.get("topic_id") == topic_id and not fact.get("subtopic_id")
        ]
        for fact in topic_facts:
            assigned.add(id(fact))
        structured_topics.append(
            {
                "topic_id": topic_id,
                "title": topic.get("title"),
                "prompt": topic.get("prompt"),
                "facts": topic_facts,
                "subtopics": subtopic_nodes,
            }
        )
    unassigned = [fact for fact in facts if id(fact) not in assigned]
    return {"topics": structured_topics, "unassigned": unassigned}


def _plan_framed_markdown(
    session: ExpertCaptureSession,
    plan_structure: Dict[str, Any],
    open_questions: List[Dict[str, Any]],
) -> str:
    lines: List[str] = [f"# {session.title}", "", f"Objectif : {session.objective}", ""]
    for topic in plan_structure.get("topics") or []:
        lines.append(f"## {topic.get('title') or 'Sujet'}")
        for fact in topic.get("facts") or []:
            statement = str(fact.get("text") or "").strip()
            if statement:
                lines.append(f"- {statement}")
        for subtopic in topic.get("subtopics") or []:
            lines.append(f"### {subtopic.get('title') or 'Sous-sujet'}")
            sub_facts = [str(f.get("text") or "").strip() for f in subtopic.get("facts") or []]
            sub_facts = [item for item in sub_facts if item]
            if sub_facts:
                lines.extend(f"- {item}" for item in sub_facts)
            else:
                lines.append("- (à compléter)")
        lines.append("")
    unassigned = plan_structure.get("unassigned") or []
    if unassigned:
        lines.append("## Points hors plan")
        for fact in unassigned:
            statement = str(fact.get("text") or "").strip()
            if statement:
                lines.append(f"- {statement}")
        lines.append("")
    if open_questions:
        lines.append("## Questions ouvertes")
        for item in open_questions:
            label = item.get("follow_up") or item.get("reason") or item.get("gap_id")
            if label:
                lines.append(f"- {label}")
    return "\n".join(lines).rstrip() + "\n"


def _proposal_markdown(
    session: ExpertCaptureSession,
    captured: List[Dict[str, Any]],
    open_questions: List[Dict[str, Any]],
) -> str:
    fact_lines = "\n".join(f"- {fact.get('text', '').strip()}" for fact in captured if fact.get("text"))
    open_lines = "\n".join(
        f"- {item.get('gap_id')}: {item.get('follow_up') or item.get('reason')}" for item in open_questions
    )
    retrieval_lines = "\n".join(
        f"- {ref.get('title') or ref.get('source') or 'Retrieved context'}"
        for fact in captured
        for ref in (fact.get("retrieval_refs") or [])[:3]
    )
    return (
        f"# {session.title}\n\n"
        f"Objective: {session.objective}\n\n"
        "## Captured Facts\n"
        f"{fact_lines or '- No validated fact yet.'}\n\n"
        "## Retrieval Evidence\n"
        f"{retrieval_lines or '- No retrieval evidence attached.'}\n\n"
        "## Open Questions\n"
        f"{open_lines or '- None recorded.'}\n"
    )


def create_capture_plan(
    db: DBSession,
    *,
    workspace_id: str,
    title: Optional[str],
    objective: str,
    expert_profile: Optional[str],
    duration_minutes: Optional[int],
    context_id: Optional[str],
    system_id: Optional[str],
    knowledge_refs: Optional[List[str]],
    voice_runtime: str = "cascade_openai",
    plan_mode: str = "ai_plan",
    allow_ai_plan: bool = False,
    capture_domain: Optional[str] = None,
    provided_plan_text: Optional[str] = None,
    plan_source_kind: Optional[str] = None,
    plan_source_filename: Optional[str] = None,
    plan_source_replaces_existing_plan: bool = False,
    created_by_user_id: Optional[str] = None,
) -> ExpertCaptureSession:
    stored_duration, unlimited_duration = _normalize_duration_minutes(duration_minutes)
    resolved_context_id, ctx = _resolve_capture_context(
        db,
        workspace_id=workspace_id,
        context_id=context_id,
    )
    snapshot = _context_snapshot(ctx)
    clean_objective = (objective or "").strip() or (
        f"Capturer les savoirs métier liés à : {(title or '').strip()}."
        if (title or "").strip()
        else "Capturer les savoirs métier et retours d'expérience de l'expert."
    )
    normalized_plan_mode = (plan_mode or "ai_plan").strip().lower()
    if normalized_plan_mode not in VALID_PLAN_MODES:
        normalized_plan_mode = "plan_build"
    if normalized_plan_mode == "ai_plan" and not allow_ai_plan:
        normalized_plan_mode = "plan_build"
    gaps: List[Dict[str, Any]] = []
    if normalized_plan_mode == "free_conversation":
        plan = _free_conversation_plan(
            objective=clean_objective,
            expert_profile=expert_profile,
            duration_minutes=stored_duration,
            context_snapshot=snapshot,
        )
    elif normalized_plan_mode in {"plan_build", "provided_plan"}:
        plan = _plan_build_shell(
            objective=clean_objective,
            expert_profile=expert_profile,
            duration_minutes=stored_duration,
            unlimited_duration=unlimited_duration,
            context_snapshot=snapshot,
            provided_seed=provided_plan_text,
        )
        if normalized_plan_mode == "provided_plan":
            plan["mode"] = "provided_plan"
            plan = _apply_provided_plan_seed(plan, provided_plan_text)
    elif normalized_plan_mode == "ai_plan" and allow_ai_plan:
        gaps = build_knowledge_gaps(
            objective=clean_objective,
            expert_profile=expert_profile,
            context_snapshot=snapshot,
            knowledge_refs=knowledge_refs,
        )
        plan = build_interview_plan(
            objective=clean_objective,
            expert_profile=expert_profile,
            duration_minutes=_planning_duration_minutes(stored_duration, unlimited_duration),
            gaps=gaps,
            context_snapshot=snapshot,
        )
    else:
        normalized_plan_mode = "plan_build"
        plan = _plan_build_shell(
            objective=clean_objective,
            expert_profile=expert_profile,
            duration_minutes=stored_duration,
            unlimited_duration=unlimited_duration,
            context_snapshot=snapshot,
            provided_seed=provided_plan_text,
        )
    plan["mode"] = normalized_plan_mode
    plan["knowledge_refs"] = knowledge_refs or []
    plan["voice_runtime"] = voice_runtime
    plan = _attach_plan_source_metadata(
        plan,
        kind=plan_source_kind,
        filename=plan_source_filename,
        seed=provided_plan_text,
        replaces_existing_plan=plan_source_replaces_existing_plan,
    )
    if unlimited_duration:
        plan["unlimited_duration"] = True

    capability = db.query(Capability).filter(Capability.slug == CAPABILITY_SLUG).first()
    resolved_system_id = system_id
    if not resolved_system_id and capability:
        default_system = (
            db.query(System)
            .filter(
                System.workspace_id == workspace_id,
                System.capability_id == capability.id,
                System.name == "Expert Knowledge Capture",
            )
            .first()
        )
        resolved_system_id = default_system.id if default_system else None
    session_metrics: Dict[str, Any] = {
        "estimated_minutes": stored_duration,
        "unlimited_duration": unlimited_duration,
        "coverage": None
        if normalized_plan_mode in {"free_conversation", "plan_build"}
        else 0.0,
        "plan_mode": normalized_plan_mode,
    }
    if capture_domain:
        session_metrics["capture_domain"] = capture_domain.strip().lower()
    session = ExpertCaptureSession(
        id=str(uuid.uuid4()),
        workspace_id=workspace_id,
        capability_id=capability.id if capability else None,
        context_id=resolved_context_id,
        system_id=resolved_system_id,
        created_by_user_id=created_by_user_id,
        title=title or "Expert Knowledge Capture",
        objective=clean_objective,
        expert_profile=expert_profile,
        duration_minutes=stored_duration,
        voice_runtime=voice_runtime,
        status="planned",
        plan=plan,
        knowledge_gaps=gaps,
        metrics=session_metrics,
    )
    db.add(session)
    db.flush()
    run_id = _record_capture_run(
        db,
        workspace_id=workspace_id,
        capability_id=session.capability_id,
        trigger="knowledge_capture_plan",
        input_ref={
            "objective": clean_objective,
            "duration_minutes": stored_duration,
            "context_id": resolved_context_id,
            "plan_mode": normalized_plan_mode,
        },
        output_ref={"plan": plan, "knowledge_gaps": gaps},
        skill_slugs=["knowledge_gap_analysis_v1", "expert_interview_plan_v1"],
        initiated_by_user_id=created_by_user_id,
    )
    session.run_id = run_id
    _record_capture_event(
        db,
        session=session,
        event_type="capture_plan_created",
        source="capture_engine",
        status="accepted",
        created_by=created_by_user_id,
        meta_data={
            "run_id": run_id,
            "schema_version": plan.get("schema_version"),
            "topic_count": len(plan.get("topics") or []),
            "question_count": len(plan.get("questions") or []),
        },
    )
    db.commit()
    db.refresh(session)
    return session


def amend_capture_plan(
    db: DBSession,
    *,
    workspace_id: str,
    session_id: str,
    plan: Dict[str, Any],
    actor_user_id: Optional[str] = None,
) -> ExpertCaptureSession:
    session = get_session(db, workspace_id=workspace_id, session_id=session_id)
    if session.status != "planned":
        raise ValueError("Capture plan can only be edited before the session starts")
    normalized = _normalize_topic_plan(
        plan,
        fallback=session.plan or {},
        review_status="edited",
        actor_user_id=actor_user_id,
    )
    session.plan = normalized
    session.duration_minutes = int(normalized.get("duration_minutes") or session.duration_minutes or 20)
    session.metrics = {
        **(session.metrics or {}),
        "estimated_minutes": session.duration_minutes,
        "coverage": 0.0,
    }
    _record_capture_event(
        db,
        session=session,
        event_type="capture_plan_amended",
        source="capture_engine",
        status="accepted",
        created_by=actor_user_id,
        meta_data={
            "question_count": len(normalized.get("questions") or []),
            "topic_count": len(normalized.get("topics") or []),
            "revision": (normalized.get("review") or {}).get("revision"),
        },
    )
    db.commit()
    db.refresh(session)
    return session


def approve_capture_plan(
    db: DBSession,
    *,
    workspace_id: str,
    session_id: str,
    actor_user_id: Optional[str] = None,
) -> ExpertCaptureSession:
    session = get_session(db, workspace_id=workspace_id, session_id=session_id)
    if session.status != "planned":
        raise ValueError("Capture plan can only be approved before the session starts")
    plan = session.plan or {}
    if plan.get("schema_version") == TOPIC_PLAN_SCHEMA_VERSION:
        plan = _normalize_topic_plan(plan, fallback=plan)
        review = {
            **(plan.get("review") or {}),
            "status": "approved",
            "approved_by_user_id": actor_user_id,
            "approved_at": datetime.utcnow().isoformat(),
        }
        plan["review"] = review
        plan["questions"] = _flatten_plan_questions(plan)
        session.plan = plan
    _record_capture_event(
        db,
        session=session,
        event_type="capture_plan_approved",
        source="capture_engine",
        status="accepted",
        created_by=actor_user_id,
        meta_data={
            "question_count": len((session.plan or {}).get("questions") or []),
            "topic_count": len((session.plan or {}).get("topics") or []),
            "revision": ((session.plan or {}).get("review") or {}).get("revision"),
        },
    )
    db.commit()
    db.refresh(session)
    return session


def _plan_build_ready_to_start(plan: Dict[str, Any]) -> bool:
    if not _is_plan_build_schema(plan):
        return True
    # Outline-driven capture does not depend on a pre-generated question bank: a
    # validated topic outline (or any topics already present) is enough to start.
    review_status = (plan.get("review") or {}).get("status")
    if review_status in {"topics_validated", "topics_pending_validation"}:
        return True
    return bool(plan.get("topics"))


def start_session(db: DBSession, *, workspace_id: str, session_id: str) -> ExpertCaptureSession:
    session = get_session(db, workspace_id=workspace_id, session_id=session_id)
    plan = dict(session.plan or {})
    if _topic_plan_requires_approval(plan):
        raise ValueError("Capture plan must be approved before the session starts")
    if _is_plan_build_schema(plan) and not _plan_build_ready_to_start(plan):
        raise ValueError("Plan must contain at least one topic before capture starts")
    if session.status == "planned":
        # Persist the current topics and auto-start question-bank generation when it
        # has not run yet (guided mode). This removes the need for an explicit
        # "validate topics" confirmation before starting the conversation. The
        # endpoint schedules generate_question_bank in the background when it sees the
        # status flip to "generating".
        if _is_plan_build_schema(plan):
            plan["topics"] = list(plan.get("topics") or [])
            if (plan.get("question_bank_status") or "idle") == "idle":
                plan["question_bank_status"] = "generating"
            session.plan = plan
            flag_modified(session, "plan")
        session.status = "active"
        session.started_at = datetime.utcnow()
        _record_capture_event(
            db,
            session=session,
            event_type="capture_session_started",
            source="capture_engine",
            status="accepted",
        )
    db.commit()
    db.refresh(session)
    return session


def append_turn(
    db: DBSession,
    *,
    workspace_id: str,
    session_id: str,
    speaker: str,
    text: str,
    question_id: Optional[str] = None,
    audio_ref: Optional[str] = None,
    client_turn_id: Optional[str] = None,
    retrieval_event_id: Optional[str] = None,
    interruption_of_event_id: Optional[str] = None,
    turn_kind: str = "answer",
    actor_user_id: Optional[str] = None,
    text_partials: Optional[List[str]] = None,
    latency_ms: Optional[Dict[str, Any]] = None,
    contradiction_candidates: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    session = get_session(db, workspace_id=workspace_id, session_id=session_id)
    if session.status == "planned" and _topic_plan_requires_approval(session.plan or {}):
        raise ValueError("Capture plan must be approved before the session starts")
    if session.status == "planned":
        session.status = "active"
        session.started_at = session.started_at or datetime.utcnow()

    question_meta = _question_trace_metadata(session.plan or {}, question_id)
    retrieval_refs = _retrieval_refs_for_event(
        db,
        workspace_id=workspace_id,
        session_id=session_id,
        retrieval_event_id=retrieval_event_id,
    )
    if interruption_of_event_id:
        _record_capture_event(
            db,
            session=session,
            event_type="ai_speech_interrupted",
            speaker="expert",
            question_id=question_id,
            source="expert_live",
            status="accepted",
            parent_event_id=interruption_of_event_id,
            created_by=actor_user_id,
            meta_data={"client_turn_id": client_turn_id, "turn_kind": turn_kind, **question_meta},
        )
    if speaker == "expert":
        _record_capture_event(
            db,
            session=session,
            event_type="stt_final",
            speaker="expert",
            question_id=question_id,
            audio_ref=audio_ref,
            text_raw=text,
            source="browser_voice" if audio_ref or client_turn_id else "operator_edit",
            status="accepted",
            parent_event_id=retrieval_event_id,
            created_by=actor_user_id,
            meta_data={"client_turn_id": client_turn_id, "turn_kind": turn_kind, **question_meta},
        )

    turn = {
        "id": client_turn_id or str(uuid.uuid4()),
        "speaker": speaker,
        "text": text,
        "question_id": question_id,
        "topic_id": question_meta.get("topic_id"),
        "subtopic_id": question_meta.get("subtopic_id"),
        "topic_path": question_meta.get("topic_path"),
        "audio_ref": audio_ref,
        "client_turn_id": client_turn_id,
        "retrieval_event_id": retrieval_event_id,
        "retrieval_refs": retrieval_refs,
        "interruption_of_event_id": interruption_of_event_id,
        "turn_kind": turn_kind,
        "text_partials": text_partials or [],
        "latency_ms": latency_ms or {},
        "created_at": datetime.utcnow().isoformat(),
    }
    event = _record_capture_event(
        db,
        session=session,
        event_type="expert_turn_finalized" if speaker == "expert" else "transcript_turn_recorded",
        speaker=speaker,
        question_id=question_id,
        audio_ref=audio_ref,
        text_raw=text,
        source="expert_live" if speaker == "expert" else "operator_edit",
        status="accepted",
        parent_event_id=interruption_of_event_id,
        created_by=actor_user_id,
        meta_data={
            "turn_id": turn["id"],
            "client_turn_id": client_turn_id,
            "retrieval_event_id": retrieval_event_id,
            "retrieval_refs": retrieval_refs,
            "interruption_of_event_id": interruption_of_event_id,
            "turn_kind": turn_kind,
            "text_partials": text_partials or [],
            "latency_ms": latency_ms or {},
            **question_meta,
        },
    )
    turn["source_event_id"] = event.id
    turn["text_raw"] = text
    turn["text_status"] = event.status
    transcript = list(session.transcript or [])
    transcript.append(turn)
    session.transcript = transcript

    evaluation: Optional[Dict[str, Any]] = None
    relance: Dict[str, Optional[str]] = {"kind": None, "text": None}
    suggestions: List[Dict[str, str]] = []
    open_questions: List[Dict[str, Any]] = []
    next_prompt: Optional[str] = None
    next_question: Optional[Dict[str, Any]] = None
    system_prompt_event_id: Optional[str] = None
    if speaker == "expert":
        question = _find_question(session.plan or {}, question_id)
        gap = _find_gap(session.knowledge_gaps or [], (question or {}).get("target_gap_id"))
        evaluation = evaluate_expert_answer(answer=text, question=question, gap=gap)
        evaluation["id"] = evaluation.get("id") or str(uuid.uuid4())
        evaluation["turn_id"] = turn["id"]
        evaluation["retrieval_event_id"] = retrieval_event_id
        evaluation["turn_kind"] = turn_kind
        evaluation.update(question_meta)

        topic_label = (question or {}).get("title") or question_meta.get("topic_path")
        # The relance is still computed for internal tracking, but it is delivered as a
        # NON-BLOCKING, optional suggestion. The expert drives: we never force an answer
        # and never auto-advance the outline. The plan is a passive reminder + retrieval
        # frame, not a script.
        relance = build_relance(
            answer=text,
            evaluation=evaluation,
            question=question,
            topic_label=topic_label,
            contradiction_candidates=contradiction_candidates,
        )
        evaluation["relance"] = relance
        evaluation["follow_up"] = relance.get("text")

        evaluations = list(session.evaluations or [])
        evaluations.append(evaluation)
        session.evaluations = evaluations

        # Record the expert's free expression regardless of verdict — the plan no
        # longer gates what is captured.
        if _has_substantive_answer_text(text):
            captured = list(session.captured_facts or [])
            captured.append(_fact_from_turn(turn, evaluations))
            session.captured_facts = captured

        session.metrics = _metrics_for_session(session)
        resolve_hints_from_expert_text(
            db,
            workspace_id=workspace_id,
            session_id=session_id,
            text=text,
            actor_user_id=actor_user_id,
        )
        session = get_session(db, workspace_id=workspace_id, session_id=session_id)

        suggestions = relance_to_suggestions(relance)
        open_questions = build_open_questions(
            session,
            contradiction_candidates=contradiction_candidates,
        )

        _record_capture_run(
            db,
            workspace_id=workspace_id,
            capability_id=session.capability_id,
            trigger="knowledge_capture_turn",
            input_ref={"session_id": session.id, "turn": turn},
            output_ref={"evaluation": evaluation, "suggestions": suggestions},
            skill_slugs=["expert_answer_evaluator_v1"],
            initiated_by_user_id=actor_user_id,
        )
        # Intentionally no system prompt is prepared and no next_prompt is emitted:
        # the AI listens and tracks, it does not push the expert to a next outline item.

    db.commit()
    db.refresh(session)
    return {
        "session": serialize_session(session),
        "turn": turn,
        "evaluation": evaluation,
        "relance": relance,
        "suggestions": suggestions,
        "open_questions": open_questions,
        "next_prompt": next_prompt,
        "next_question_id": (next_question or {}).get("id") if speaker == "expert" else None,
        "system_prompt_event_id": system_prompt_event_id,
    }


def create_update_proposal(
    db: DBSession,
    *,
    workspace_id: str,
    session_id: str,
    complete_session: bool = True,
    created_by_user_id: Optional[str] = None,
) -> KnowledgeUpdateProposal:
    session = get_session(db, workspace_id=workspace_id, session_id=session_id)
    events = list_capture_events(db, workspace_id=workspace_id, session_id=session_id)
    payload = structure_capture_payload(session, events)
    proposal = _latest_pending_proposal_for_session(db, workspace_id=workspace_id, session_id=session_id)
    previous_publication = (
        dict((proposal.proposal or {}).get("publication") or {})
        if proposal and isinstance((proposal.proposal or {}).get("publication"), dict)
        else {}
    )
    ctx = _load_context(db, workspace_id, session.context_id)
    payload = _apply_publication_defaults(payload, session=session, ctx=ctx, previous_publication=previous_publication)
    operation = "updated" if proposal else "created"
    if proposal:
        conversation_state = ((proposal.proposal or {}).get("conversation") or {}).copy()
        if conversation_state:
            payload["conversation"] = conversation_state
        proposal.proposal = payload
        flag_modified(proposal, "proposal")
    else:
        proposal = KnowledgeUpdateProposal(
            id=str(uuid.uuid4()),
            workspace_id=workspace_id,
            session_id=session.id,
            status="pending_review",
            proposal=payload,
            created_by_user_id=created_by_user_id or session.created_by_user_id,
        )
        db.add(proposal)
    if created_by_user_id and not proposal.created_by_user_id:
        proposal.created_by_user_id = created_by_user_id
    if complete_session:
        session.status = "completed"
        session.completed_at = datetime.utcnow()
        events = list_capture_events(db, workspace_id=workspace_id, session_id=session_id)
        closure = build_session_closure_sheet(session, events)
        metrics = dict(session.metrics or {})
        metrics["closure_sheet"] = closure["markdown"]
        metrics["session_end_pending"] = False
        metrics.update(_compute_timer_metrics(session))
        session.metrics = metrics
        flag_modified(session, "metrics")
    db.flush()
    _record_capture_event(
        db,
        session=session,
        event_type="proposal_generated",
        source="capture_engine",
        status="accepted",
        created_by=created_by_user_id,
        meta_data={
            "proposal_id": proposal.id,
            "operation": operation,
            "fact_count": len(payload.get("captured_facts") or []),
        },
    )
    _record_capture_run(
        db,
        workspace_id=workspace_id,
        capability_id=session.capability_id,
        trigger="knowledge_capture_structuring",
        input_ref={"session_id": session.id},
        output_ref={"proposal": payload},
        skill_slugs=["capture_structuring_v1", "audit_log_v1"],
        initiated_by_user_id=created_by_user_id or session.created_by_user_id,
    )
    db.commit()
    db.refresh(proposal)
    return proposal


def review_proposal(
    db: DBSession,
    *,
    workspace_id: str,
    proposal_id: str,
    status: str,
    reviewer: Optional[str],
    review_notes: Optional[str],
    reviewer_user_id: Optional[str] = None,
) -> KnowledgeUpdateProposal:
    proposal = (
        db.query(KnowledgeUpdateProposal)
        .filter(KnowledgeUpdateProposal.id == proposal_id, KnowledgeUpdateProposal.workspace_id == workspace_id)
        .first()
    )
    if not proposal:
        raise ValueError("Knowledge update proposal not found")
    proposal.status = status
    proposal.reviewer = reviewer
    proposal.reviewer_user_id = reviewer_user_id
    proposal.review_notes = review_notes
    proposal.reviewed_at = datetime.utcnow()
    session = (
        db.query(ExpertCaptureSession)
        .filter(
            ExpertCaptureSession.id == proposal.session_id,
            ExpertCaptureSession.workspace_id == workspace_id,
        )
        .first()
    )
    if session:
        _record_capture_event(
            db,
            session=session,
            event_type="proposal_reviewed",
            source="operator_edit" if reviewer else "capture_engine",
            status=status,
            created_by=reviewer,
            meta_data={
                "proposal_id": proposal.id,
                "review_notes": review_notes,
                "reviewer_user_id": reviewer_user_id,
            },
        )
    emit_audit_event(
        db=db,
        workspace_id=workspace_id,
        event_type=f"kc.proposal.review.{status}",
        actor=reviewer or reviewer_user_id or "system",
        details={
            "proposal_id": proposal.id,
            "session_id": proposal.session_id,
            "reviewer_user_id": reviewer_user_id,
            "outcome": status,
        },
    )
    db.commit()
    db.refresh(proposal)
    return proposal


def update_proposal_open_question_statuses(
    db: DBSession,
    *,
    workspace_id: str,
    proposal_id: str,
    items: List[Dict[str, Any]],
    actor_user_id: Optional[str] = None,
    actor_label: Optional[str] = None,
) -> KnowledgeUpdateProposal:
    proposal = (
        db.query(KnowledgeUpdateProposal)
        .filter(KnowledgeUpdateProposal.id == proposal_id, KnowledgeUpdateProposal.workspace_id == workspace_id)
        .first()
    )
    if not proposal:
        raise ValueError("Knowledge update proposal not found")
    if not items:
        return proposal

    payload = dict(proposal.proposal or {})
    questions = [
        dict(question)
        for question in (payload.get("open_questions") or [])
        if isinstance(question, dict)
    ]
    if not questions:
        raise ValueError("Knowledge update proposal has no open questions")

    status_map: Dict[str, str] = {}
    raw_items: List[Dict[str, Any]] = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        status = _normalize_proposal_open_question_status(raw.get("status"))
        aliases = [
            raw.get("question_key"),
            raw.get("key"),
            raw.get("gap_id"),
            raw.get("question_text"),
            raw.get("follow_up"),
            raw.get("reason"),
        ]
        clean_aliases = [
            alias
            for alias in (_clean_optional_string(value) for value in aliases)
            if alias
        ]
        if not clean_aliases:
            continue
        for alias in clean_aliases:
            status_map[alias] = status
            status_map[alias.lower()] = status
        raw_items.append(
            {
                "question_key": clean_aliases[0],
                "question_text": _clean_optional_string(raw.get("question_text")),
                "status": status,
            }
        )

    if not status_map:
        return proposal

    updated_count = 0
    updated_at = datetime.utcnow().isoformat()
    for index, question in enumerate(questions):
        question_status = None
        for key in _proposal_open_question_keys(question, index):
            if key in status_map:
                question_status = status_map[key]
                break
        if not question_status:
            continue
        question["status"] = question_status
        question["status_updated_at"] = updated_at
        question["status_updated_by_user_id"] = actor_user_id
        updated_count += 1

    if not updated_count:
        return proposal

    payload["open_questions"] = questions
    proposal.proposal = payload
    flag_modified(proposal, "proposal")

    session = (
        db.query(ExpertCaptureSession)
        .filter(
            ExpertCaptureSession.id == proposal.session_id,
            ExpertCaptureSession.workspace_id == workspace_id,
        )
        .first()
    )
    if session:
        _record_capture_event(
            db,
            session=session,
            event_type="proposal_open_question_status_updated",
            source="operator_edit",
            status="updated",
            created_by=actor_user_id or actor_label,
            meta_data={
                "proposal_id": proposal.id,
                "items": raw_items,
                "updated_count": updated_count,
            },
        )

    db.commit()
    db.refresh(proposal)
    return proposal


def update_proposal_report_content(
    db: DBSession,
    *,
    workspace_id: str,
    proposal_id: str,
    content: str,
    actor_user_id: Optional[str] = None,
    actor_label: Optional[str] = None,
) -> KnowledgeUpdateProposal:
    proposal = (
        db.query(KnowledgeUpdateProposal)
        .filter(KnowledgeUpdateProposal.id == proposal_id, KnowledgeUpdateProposal.workspace_id == workspace_id)
        .first()
    )
    if not proposal:
        raise ValueError("Knowledge update proposal not found")
    clean = (content or "").strip()
    if not clean:
        raise ValueError("Proposal report content cannot be empty")
    payload = dict(proposal.proposal or {})
    recommended = dict(payload.get("recommended_ingestion") or {})
    metadata = dict(recommended.get("metadata") or {})
    metadata.update(
        {
            "edited_by_user_id": actor_user_id,
            "edited_at": datetime.utcnow().isoformat(),
        }
    )
    recommended["content"] = clean
    recommended["metadata"] = metadata
    payload["recommended_ingestion"] = recommended
    payload["report_markdown"] = clean
    proposal.proposal = payload
    flag_modified(proposal, "proposal")

    session = (
        db.query(ExpertCaptureSession)
        .filter(
            ExpertCaptureSession.id == proposal.session_id,
            ExpertCaptureSession.workspace_id == workspace_id,
        )
        .first()
    )
    if session:
        _record_capture_event(
            db,
            session=session,
            event_type="proposal_report_edited",
            source="operator_edit",
            status="accepted",
            created_by=actor_label or actor_user_id,
            meta_data={
                "proposal_id": proposal.id,
                "content_chars": len(clean),
                "actor_user_id": actor_user_id,
            },
        )
    db.commit()
    db.refresh(proposal)
    return proposal


async def _rewrite_report_with_instruction_async(
    *,
    workspace_id: str,
    session: ExpertCaptureSession,
    current_report: str,
    instruction: str,
    open_questions: Optional[List[Dict[str, Any]]] = None,
    use_llm: bool = True,
) -> Tuple[str, Dict[str, Any]]:
    fallback = _append_report_instruction_fallback(current_report=current_report, instruction=instruction)
    if not use_llm:
        return fallback, {"status": "instruction_recorded_fallback", "provider": "deterministic"}
    api_key, model = _resolve_llm_config(workspace_id)
    if not api_key:
        return fallback, {"status": "instruction_recorded_fallback", "provider": "deterministic"}
    try:
        from openai import AsyncOpenAI

        payload = {
            "session_title": session.title,
            "session_objective": session.objective,
            "current_report_markdown": current_report,
            "instruction": instruction,
            "open_questions": open_questions or [],
            "rules": [
                "Return the full updated Markdown report, not a diff.",
                "Preserve existing factual content unless the instruction explicitly asks to remove it.",
                "Keep unresolved questions visible near the end if they remain unresolved.",
                "Do not invent facts, sources, names, dates or measurements.",
                "Do not add meta commentary about the editing process.",
            ],
        }
        client = AsyncOpenAI(api_key=api_key)
        response = await asyncio.wait_for(
            client.chat.completions.create(
                model=model,
                **_model_chat_kwargs(model, temperature=0.2),
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Tu es un éditeur de rapport Markdown pour une capture de connaissances. "
                            "Retourne uniquement le rapport Markdown complet et révisé. "
                            "Ne crée aucune information non présente dans le rapport ou l'instruction."
                        ),
                    },
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
            ),
            timeout=20,
        )
        content = response.choices[0].message.content if response.choices else None
        updated = (content or "").strip()
        if len(updated) < max(80, len(current_report.strip()) // 4):
            return fallback, {"status": "instruction_recorded_fallback", "provider": "deterministic"}
        return updated, {
            "status": "llm_applied",
            "provider": "openai",
            "model": model,
        }
    except Exception as exc:
        _logger.warning("knowledge_capture_report_instruction_llm_failed: %s", exc)
        return fallback, {"status": "instruction_recorded_fallback", "provider": "deterministic"}


def _append_report_instruction_fallback(*, current_report: str, instruction: str) -> str:
    report = current_report.strip()
    note = (
        "## Modification demandée\n\n"
        "Cette consigne doit être prise en compte à la relecture finale :\n\n"
        f"> {instruction.strip()}\n"
    )
    if "## Modification demandée" in report:
        return f"{report}\n\n> {instruction.strip()}"
    return f"{report}\n\n{note}".strip()


async def apply_proposal_report_instruction(
    db: DBSession,
    *,
    workspace_id: str,
    proposal_id: str,
    instruction: str,
    current_content: Optional[str] = None,
    actor_user_id: Optional[str] = None,
    actor_label: Optional[str] = None,
    use_llm: bool = True,
) -> KnowledgeUpdateProposal:
    proposal = (
        db.query(KnowledgeUpdateProposal)
        .filter(KnowledgeUpdateProposal.id == proposal_id, KnowledgeUpdateProposal.workspace_id == workspace_id)
        .first()
    )
    if not proposal:
        raise ValueError("Knowledge update proposal not found")
    session = get_session(db, workspace_id=workspace_id, session_id=proposal.session_id)
    clean_instruction = (instruction or "").strip()
    if not clean_instruction:
        raise ValueError("Report instruction cannot be empty")
    payload = dict(proposal.proposal or {})
    recommended = dict(payload.get("recommended_ingestion") or {})
    base_content = (
        (current_content or "").strip()
        or str(payload.get("report_markdown") or "").strip()
        or str(recommended.get("content") or "").strip()
    )
    if not base_content:
        raise ValueError("Proposal report content cannot be empty")
    open_questions = payload.get("open_questions") if isinstance(payload.get("open_questions"), list) else []
    updated_content, edit_meta = await _rewrite_report_with_instruction_async(
        workspace_id=workspace_id,
        session=session,
        current_report=base_content,
        instruction=clean_instruction,
        open_questions=open_questions,
        use_llm=use_llm,
    )
    metadata = dict(recommended.get("metadata") or {})
    metadata.update(
        {
            "edited_by_user_id": actor_user_id,
            "edited_at": datetime.utcnow().isoformat(),
            "last_instruction": clean_instruction,
            "last_instruction_status": edit_meta.get("status"),
            "last_instruction_provider": edit_meta.get("provider"),
            "last_instruction_model": edit_meta.get("model"),
        }
    )
    recommended["content"] = updated_content
    recommended["metadata"] = metadata
    payload["recommended_ingestion"] = recommended
    payload["report_markdown"] = updated_content
    payload["report_edit"] = {
        "instruction": clean_instruction,
        **edit_meta,
        "updated_at": datetime.utcnow().isoformat(),
        "updated_by_user_id": actor_user_id,
    }
    proposal.proposal = payload
    flag_modified(proposal, "proposal")

    _record_capture_event(
        db,
        session=session,
        event_type="proposal_report_instruction_applied",
        source="operator_edit",
        status=str(edit_meta.get("status") or "accepted"),
        created_by=actor_label or actor_user_id,
        meta_data={
            "proposal_id": proposal.id,
            "instruction": clean_instruction,
            "content_chars": len(updated_content),
            "actor_user_id": actor_user_id,
            **edit_meta,
        },
    )
    db.commit()
    db.refresh(proposal)
    return proposal


async def prefetch_capture_retrieval(
    db: DBSession,
    *,
    workspace_id: str,
    workspace_slug: Optional[str],
    session_id: str,
    client_turn_id: Optional[str],
    question_id: Optional[str],
    partial_text: str,
    mode: str = "chah",
    top_k: int = 4,
    timeout_seconds: float = RETRIEVAL_PREFETCH_TIMEOUT_SECONDS,
) -> Dict[str, Any]:
    session = get_session(db, workspace_id=workspace_id, session_id=session_id)
    text = (partial_text or "").strip()
    if not text:
        raise ValueError("partial_text cannot be empty")
    if is_capture_text_noise(text):
        return {
            "event_id": None,
            "status": "ignored",
            "latency_ms": 0,
            "chunks": [],
            "scores": [],
            "metadatas": [],
            "stale": False,
            "collection_name": "documents",
            "hints": [],
            "active_subtopic_id": None,
            "ignored_reason": "stt_noise",
        }

    question_meta = _question_trace_metadata(session.plan or {}, question_id)
    partial_event = _record_capture_event(
        db,
        session=session,
        event_type="stt_partial",
        speaker="expert",
        question_id=question_id,
        text_raw=text,
        source="browser_voice",
        status="accepted",
        meta_data={"client_turn_id": client_turn_id, "words": len(_words(text)), **question_meta},
    )
    started_event = _record_capture_event(
        db,
        session=session,
        event_type="retrieval_prefetch_started",
        speaker="expert",
        question_id=question_id,
        text_raw=text,
        source="capture_engine",
        status="running",
        parent_event_id=partial_event.id,
        meta_data={"client_turn_id": client_turn_id, "mode": mode, "top_k": top_k, **question_meta},
    )
    db.commit()

    started = time.perf_counter()
    chunks: List[str] = []
    scores: List[float] = []
    metadatas: List[Dict[str, Any]] = []
    status = "completed"
    detail: Dict[str, Any] = {}
    event_type = "retrieval_prefetch_completed"
    collection_name = "documents"

    try:
        ctx = _load_context(db, workspace_id, session.context_id)
        collection_name = _resolve_collection_name(ctx)
        from app.services.rag.context import retrieve_rag_context

        retrieval_context = await asyncio.wait_for(
            retrieve_rag_context(
                {
                    "query": text,
                    "workspace_id": workspace_id,
                    "workspace_slug": workspace_slug,
                    "capability_id": session.capability_id,
                    "system_id": session.system_id,
                    "context_collection": collection_name,
                    "latency_profile": "fast",
                    "rag_pipeline_mode": "auto",
                    "top_k": max(1, min(top_k, 8)),
                    "source_display_k": max(1, min(top_k, 8)),
                    "candidate_pool_k": 20,
                }
            ),
            timeout=timeout_seconds,
        )
        metrics = retrieval_context.get("metrics") if isinstance(retrieval_context.get("metrics"), dict) else {}
        chunks = list(retrieval_context.get("chunks") or [])
        scores = list(retrieval_context.get("scores") or [])
        metadatas = list(retrieval_context.get("metadatas") or [])
        detail = {
            "pipeline": retrieval_context.get("pipeline"),
            "label": retrieval_context.get("label"),
            "reason": retrieval_context.get("reason"),
            "detail": retrieval_context.get("detail"),
            "vector_db_type": metrics.get("vector_db_type"),
            "dense_policy": metrics.get("dense_policy"),
            "scope_confidence": metrics.get("scope_confidence"),
            "fallback_reason": metrics.get("fallback_reason"),
        }
    except TimeoutError:
        status = "timeout"
        event_type = "retrieval_prefetch_timeout"
        detail = {"reason": f"retrieval exceeded {timeout_seconds:.1f}s"}
    except Exception as exc:
        status = "error"
        event_type = "retrieval_prefetch_timeout"
        detail = {"reason": str(exc)}

    latency_ms = int((time.perf_counter() - started) * 1000)
    final_event = _record_capture_event(
        db,
        session=session,
        event_type=event_type,
        speaker="expert",
        question_id=question_id,
        text_raw=text,
        source="capture_engine",
        status=status,
        parent_event_id=started_event.id,
        meta_data={
            "client_turn_id": client_turn_id,
            "collection_name": collection_name,
            "mode": mode,
            "top_k": top_k,
            "latency_ms": latency_ms,
            "chunks": chunks,
            "scores": scores,
            "metadatas": metadatas,
            "stale": False,
            **question_meta,
            **detail,
        },
    )
    db.commit()
    db.refresh(final_event)

    hint_payload: Dict[str, Any] = {}
    if chunks and len(_words(text)) >= 6:
        hint_payload = process_capture_partial_hints(
            db,
            workspace_id=workspace_id,
            session_id=session_id,
            partial_text=text,
            retrieval_chunks=chunks,
            retrieval_metadatas=metadatas,
            client_turn_id=client_turn_id,
        )

    return {
        "event_id": final_event.id,
        "status": status,
        "latency_ms": latency_ms,
        "chunks": chunks,
        "scores": scores,
        "metadatas": metadatas,
        "stale": False,
        "collection_name": collection_name,
        "hints": hint_payload.get("hints") or [],
        "active_subtopic_id": hint_payload.get("active_subtopic_id"),
        **question_meta,
    }


def list_capture_events(
    db: DBSession,
    *,
    workspace_id: str,
    session_id: str,
    event_type: Optional[str] = None,
    status: Optional[str] = None,
    after_sequence: Optional[int] = None,
    business_only: bool = False,
) -> List[ExpertCaptureEvent]:
    q = db.query(ExpertCaptureEvent).filter(
        ExpertCaptureEvent.workspace_id == workspace_id,
        ExpertCaptureEvent.session_id == session_id,
    )
    if business_only:
        q = q.filter(ExpertCaptureEvent.event_type.in_(BUSINESS_EVENT_TYPES))
    if event_type:
        q = q.filter(ExpertCaptureEvent.event_type == event_type)
    if status:
        q = q.filter(ExpertCaptureEvent.status == status)
    if after_sequence is not None:
        q = q.filter(ExpertCaptureEvent.sequence > after_sequence)
    return q.order_by(ExpertCaptureEvent.sequence.asc(), ExpertCaptureEvent.created_at.asc()).all()


def amend_capture_event(
    db: DBSession,
    *,
    workspace_id: str,
    session_id: str,
    event_id: str,
    text_amended: str,
    actor: Optional[str] = None,
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    session = get_session(db, workspace_id=workspace_id, session_id=session_id)
    event = (
        db.query(ExpertCaptureEvent)
        .filter(
            ExpertCaptureEvent.id == event_id,
            ExpertCaptureEvent.workspace_id == workspace_id,
            ExpertCaptureEvent.session_id == session_id,
        )
        .first()
    )
    if not event:
        raise ValueError("Expert capture event not found")
    if not (text_amended or "").strip():
        raise ValueError("Amended text cannot be empty")

    previous_text = _effective_event_text(event)
    event.text_amended = text_amended.strip()
    event.status = "amended"
    event.created_by = event.created_by or actor
    event.meta_data = {
        **(event.meta_data or {}),
        "last_amended_by": actor,
        "last_amended_at": datetime.utcnow().isoformat(),
        "last_amend_reason": reason,
    }

    amendment = _record_capture_event(
        db,
        session=session,
        event_type="transcript_amended",
        speaker=event.speaker,
        question_id=event.question_id,
        audio_ref=event.audio_ref,
        text_raw=previous_text,
        text_amended=event.text_amended,
        source="operator_edit",
        status="accepted",
        parent_event_id=event.id,
        created_by=actor,
        meta_data={"reason": reason},
    )

    _sync_session_transcript_from_event(session, event)
    db.commit()
    db.refresh(event)
    db.refresh(amendment)
    return {
        "event": _serialize_event(event),
        "amendment": _serialize_event(amendment),
        "session": serialize_session(session),
    }


def get_session(db: DBSession, *, workspace_id: str, session_id: str) -> ExpertCaptureSession:
    session = (
        db.query(ExpertCaptureSession)
        .filter(ExpertCaptureSession.id == session_id, ExpertCaptureSession.workspace_id == workspace_id)
        .first()
    )
    if not session:
        raise ValueError("Expert capture session not found")
    return session


def _compact_text(value: Any, *, limit: int = 180) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    if len(text) <= limit:
        return text
    return f"{text[: max(0, limit - 1)].rstrip()}…"


def _session_summary_short(session: ExpertCaptureSession) -> str:
    metrics = session.metrics or {}
    existing = _clean_optional_string(metrics.get("summary_short"))
    if existing:
        return _compact_text(existing)
    for fact in session.captured_facts or []:
        if not isinstance(fact, dict):
            continue
        text = fact.get("text") or fact.get("statement")
        if _clean_optional_string(text):
            return _compact_text(text)
    expert_turns = [
        str(turn.get("text") or "").strip()
        for turn in (session.transcript or [])
        if isinstance(turn, dict) and turn.get("speaker") == "expert" and str(turn.get("text") or "").strip()
    ]
    if expert_turns:
        return _compact_text(" ".join(expert_turns[-2:]))
    if session.objective:
        return _compact_text(session.objective)
    return "Session de capture."


def _session_open_questions_count(session: ExpertCaptureSession) -> int:
    try:
        open_questions = build_open_questions(session)
    except Exception:
        return 0
    return len(
        [
            item
            for item in open_questions
            if item.get("status") not in {"addressed", "answered", "dismissed", "deferred"}
        ]
    )


def serialize_session(session: ExpertCaptureSession, *, surface: Optional[str] = None) -> Dict[str, Any]:
    plan = dict(session.plan or {})
    if surface in {"plan_build", "plan"} or _is_plan_build_schema(plan):
        plan = _serialize_plan_for_ui(plan, surface=surface)
    timer_metrics = _compute_timer_metrics(session)
    summary_short = _session_summary_short(session)
    open_questions_count = _session_open_questions_count(session)
    last_activity = (session.updated_at or session.completed_at or session.started_at or session.created_at)
    return {
        "id": session.id,
        "workspace_id": session.workspace_id,
        "capability_id": session.capability_id,
        "context_id": session.context_id,
        "system_id": session.system_id,
        "run_id": session.run_id,
        "created_by_user_id": session.created_by_user_id,
        "title": session.title,
        "objective": session.objective,
        "expert_profile": session.expert_profile,
        "duration_minutes": session.duration_minutes,
        "voice_runtime": session.voice_runtime,
        "status": session.status,
        "plan": plan,
        "knowledge_gaps": session.knowledge_gaps or [],
        "transcript": session.transcript or [],
        "evaluations": session.evaluations or [],
        "captured_facts": session.captured_facts or [],
        "metrics": {
            **(session.metrics or {}),
            **timer_metrics,
            "summary_short": summary_short,
            "open_questions_count": open_questions_count,
            "last_activity": last_activity.isoformat() if last_activity else None,
        },
        "summary_short": summary_short,
        "open_questions_count": open_questions_count,
        "last_activity": last_activity.isoformat() if last_activity else None,
        "started_at": session.started_at.isoformat() if session.started_at else None,
        "completed_at": session.completed_at.isoformat() if session.completed_at else None,
        "created_at": session.created_at.isoformat() if session.created_at else None,
        "updated_at": session.updated_at.isoformat() if session.updated_at else None,
    }


def _serialize_plan_for_ui(plan: Dict[str, Any], *, surface: Optional[str] = None) -> Dict[str, Any]:
    serialized = dict(plan)
    serialized["questions"] = []
    topics: List[Dict[str, Any]] = []
    for topic in plan.get("topics") or []:
        if not isinstance(topic, dict):
            continue
        subtopics: List[Dict[str, Any]] = []
        for subtopic in topic.get("subtopics") or []:
            if not isinstance(subtopic, dict):
                continue
            cleaned = {key: value for key, value in subtopic.items() if key != "questions"}
            subtopics.append(cleaned)
        cleaned_topic = {key: value for key, value in topic.items() if key != "questions"}
        cleaned_topic["subtopics"] = subtopics
        topics.append(cleaned_topic)
    serialized["topics"] = topics
    if surface in {"plan_build", "plan", None}:
        serialized["question_bank"] = []
    return serialized


def serialize_proposal(proposal: KnowledgeUpdateProposal) -> Dict[str, Any]:
    return {
        "id": proposal.id,
        "workspace_id": proposal.workspace_id,
        "session_id": proposal.session_id,
        "status": proposal.status,
        "proposal": proposal.proposal or {},
        "review_notes": proposal.review_notes,
        "reviewer": proposal.reviewer,
        "created_by_user_id": proposal.created_by_user_id,
        "reviewer_user_id": proposal.reviewer_user_id,
        "created_at": proposal.created_at.isoformat() if proposal.created_at else None,
        "reviewed_at": proposal.reviewed_at.isoformat() if proposal.reviewed_at else None,
    }


def serialize_event(event: ExpertCaptureEvent) -> Dict[str, Any]:
    return _serialize_event(event)


def _serialize_event(event: ExpertCaptureEvent) -> Dict[str, Any]:
    return {
        "id": event.id,
        "workspace_id": event.workspace_id,
        "session_id": event.session_id,
        "parent_event_id": event.parent_event_id,
        "event_type": event.event_type,
        "speaker": event.speaker,
        "sequence": event.sequence,
        "question_id": event.question_id,
        "audio_ref": event.audio_ref,
        "text_raw": event.text_raw,
        "text_amended": event.text_amended,
        "text": _effective_event_text(event),
        "confidence": event.confidence,
        "language": event.language,
        "source": event.source,
        "status": event.status,
        "metadata": event.meta_data or {},
        "created_by": event.created_by,
        "started_at": event.started_at.isoformat() if event.started_at else None,
        "ended_at": event.ended_at.isoformat() if event.ended_at else None,
        "created_at": event.created_at.isoformat() if event.created_at else None,
    }


def _effective_event_text(event: ExpertCaptureEvent) -> str:
    return (event.text_amended or event.text_raw or "").strip()


def _record_capture_event(
    db: DBSession,
    *,
    session: ExpertCaptureSession,
    event_type: str,
    speaker: Optional[str] = None,
    question_id: Optional[str] = None,
    audio_ref: Optional[str] = None,
    text_raw: Optional[str] = None,
    text_amended: Optional[str] = None,
    confidence: Optional[str] = None,
    language: Optional[str] = None,
    source: str = "capture_engine",
    status: str = "accepted",
    parent_event_id: Optional[str] = None,
    created_by: Optional[str] = None,
    meta_data: Optional[Dict[str, Any]] = None,
    started_at: Optional[datetime] = None,
    ended_at: Optional[datetime] = None,
) -> ExpertCaptureEvent:
    sequence = _next_event_sequence(db, session.id)
    event = ExpertCaptureEvent(
        id=str(uuid.uuid4()),
        workspace_id=session.workspace_id,
        session_id=session.id,
        parent_event_id=parent_event_id,
        event_type=event_type,
        speaker=speaker,
        sequence=sequence,
        question_id=question_id,
        audio_ref=audio_ref,
        text_raw=text_raw,
        text_amended=text_amended,
        confidence=confidence,
        language=language,
        source=source,
        status=status,
        meta_data=meta_data or {},
        created_by=created_by,
        started_at=started_at,
        ended_at=ended_at,
    )
    db.add(event)
    db.flush()
    return event


def _next_event_sequence(db: DBSession, session_id: str) -> int:
    last = (
        db.query(ExpertCaptureEvent.sequence)
        .filter(ExpertCaptureEvent.session_id == session_id)
        .order_by(ExpertCaptureEvent.sequence.desc())
        .first()
    )
    return int(last[0]) + 1 if last else 1


def _sync_session_transcript_from_event(
    session: ExpertCaptureSession,
    event: ExpertCaptureEvent,
) -> None:
    transcript = list(session.transcript or [])
    for turn in transcript:
        if turn.get("source_event_id") != event.id:
            continue
        turn["text_raw"] = event.text_raw
        turn["text_amended"] = event.text_amended
        turn["text"] = _effective_event_text(event)
        turn["text_status"] = event.status
        turn["amended_at"] = datetime.utcnow().isoformat()
        _sync_captured_fact(session, turn)
        break
    session.transcript = transcript
    flag_modified(session, "transcript")


def _sync_captured_fact(session: ExpertCaptureSession, turn: Dict[str, Any]) -> None:
    captured = list(session.captured_facts or [])
    target_id = f"fact-{turn.get('id')}"
    changed = False
    for fact in captured:
        if fact.get("id") != target_id:
            continue
        fact["text"] = turn.get("text", "")
        fact["source_event_id"] = turn.get("source_event_id")
        fact["amended"] = bool(turn.get("text_amended"))
        changed = True
    if changed:
        session.captured_facts = captured
        flag_modified(session, "captured_facts")


def _load_context(db: DBSession, workspace_id: str, context_id: Optional[str]) -> Optional[Context]:
    if not context_id:
        return None
    return db.query(Context).filter(Context.id == context_id, Context.workspace_id == workspace_id).first()


def _load_proposal(
    db: DBSession,
    *,
    workspace_id: str,
    proposal_id: Optional[str],
    session_id: Optional[str] = None,
) -> Optional[KnowledgeUpdateProposal]:
    if not proposal_id:
        return None
    q = db.query(KnowledgeUpdateProposal).filter(
        KnowledgeUpdateProposal.id == proposal_id,
        KnowledgeUpdateProposal.workspace_id == workspace_id,
    )
    if session_id:
        q = q.filter(KnowledgeUpdateProposal.session_id == session_id)
    return q.first()


def _latest_pending_proposal_for_session(
    db: DBSession,
    *,
    workspace_id: str,
    session_id: str,
) -> Optional[KnowledgeUpdateProposal]:
    return (
        db.query(KnowledgeUpdateProposal)
        .filter(
            KnowledgeUpdateProposal.workspace_id == workspace_id,
            KnowledgeUpdateProposal.session_id == session_id,
            KnowledgeUpdateProposal.status == "pending_review",
        )
        .order_by(KnowledgeUpdateProposal.created_at.desc())
        .first()
    )


def _load_active_proposal(
    db: DBSession,
    *,
    workspace_id: str,
    proposal_id: Optional[str],
    session_id: str,
) -> Optional[KnowledgeUpdateProposal]:
    proposal = _load_proposal(
        db,
        workspace_id=workspace_id,
        proposal_id=proposal_id,
        session_id=session_id,
    )
    if proposal:
        return proposal
    return _latest_pending_proposal_for_session(db, workspace_id=workspace_id, session_id=session_id)


def _proposal_conversation_confirmed(proposal: Optional[KnowledgeUpdateProposal]) -> bool:
    if not proposal:
        return False
    return ((proposal.proposal or {}).get("conversation") or {}).get("state") == "proposal_confirmed"


def _mark_proposal_conversation_state(
    proposal: KnowledgeUpdateProposal,
    *,
    state: str,
    note: str,
) -> None:
    payload = dict(proposal.proposal or {})
    payload["conversation"] = {
        **(payload.get("conversation") or {}),
        "state": state,
        "note": note,
        "updated_at": datetime.utcnow().isoformat(),
    }
    proposal.proposal = payload
    flag_modified(proposal, "proposal")


def _has_substantive_answer_text(text: str) -> bool:
    if is_capture_text_noise(text):
        return False
    lower = (text or "").lower()
    stripped = lower
    for term in PROPOSAL_REQUEST_TERMS:
        stripped = stripped.replace(term, " ")
    return len(_words(stripped)) >= 8


def _session_has_proposal_material(db: DBSession, *, workspace_id: str, session: ExpertCaptureSession) -> bool:
    if session.captured_facts:
        return True
    events = list_capture_events(db, workspace_id=workspace_id, session_id=session.id)
    payload = structure_capture_payload(session, events)
    return bool(payload.get("captured_facts"))


def _resolve_collection_name(ctx: Optional[Context]) -> str:
    state = (ctx.environment_state or {}) if ctx else {}
    collection = state.get("collection") or state.get("collection_name") or state.get("rag_collection")
    return str(collection).strip() if collection else "documents"


def _retrieval_refs_for_event(
    db: DBSession,
    *,
    workspace_id: str,
    session_id: str,
    retrieval_event_id: Optional[str],
) -> List[Dict[str, Any]]:
    if not retrieval_event_id:
        return []
    event = (
        db.query(ExpertCaptureEvent)
        .filter(
            ExpertCaptureEvent.id == retrieval_event_id,
            ExpertCaptureEvent.workspace_id == workspace_id,
            ExpertCaptureEvent.session_id == session_id,
        )
        .first()
    )
    if not event:
        return []
    meta = event.meta_data or {}
    chunks = meta.get("chunks") or []
    scores = meta.get("scores") or []
    metadatas = meta.get("metadatas") or []
    refs: List[Dict[str, Any]] = []
    for index, chunk in enumerate(chunks[:4]):
        md = metadatas[index] if index < len(metadatas) and isinstance(metadatas[index], dict) else {}
        refs.append(
            {
                "event_id": event.id,
                "rank": index + 1,
                "score": scores[index] if index < len(scores) else None,
                "title": md.get("title") or md.get("filename") or md.get("source"),
                "source": md.get("source") or md.get("document_id") or md.get("filename"),
                "preview": str(chunk)[:360],
                "metadata": md,
            }
        )
    return refs


def _flatten_plan_questions(plan: Dict[str, Any]) -> List[Dict[str, Any]]:
    topics = plan.get("topics") or []
    if not topics:
        return list(plan.get("questions") or [])

    questions: List[Dict[str, Any]] = []
    for topic in topics:
        topic_id = topic.get("id")
        topic_title = topic.get("title") or "Topic"
        subtopics = topic.get("subtopics") or []
        # Broad-first: open an outline-driven topic with its wide, topic-level
        # presentation prompt before descending into the narrower subtopic prompts.
        # Legacy guided plans (subtopics carry authored questions) keep their order.
        topic_is_outline = not any((subtopic.get("questions") or []) for subtopic in subtopics)
        if subtopics and topic_is_outline:
            topic_prompt = str(topic.get("prompt") or "").strip() or broad_presentation_prompt(topic_title)
            questions.append(
                {
                    "id": f"{topic_id}-overview" if topic_id else None,
                    "topic_id": topic_id,
                    "subtopic_id": None,
                    "path_label": topic_title,
                    "title": topic_title,
                    "prompt": topic_prompt,
                    "question": topic_prompt,
                    "level": "topic",
                    "visibility": "outline",
                }
            )
        for subtopic in subtopics:
            subtopic_id = subtopic.get("id")
            subtopic_title = subtopic.get("title") or topic_title
            path_label = f"{topic_title} / {subtopic_title}"
            sub_prompt = str(subtopic.get("prompt") or "").strip() or presentation_prompt(subtopic_title)
            sub_questions = subtopic.get("questions") or []
            if sub_questions:
                for question in sub_questions:
                    q = dict(question)
                    q["topic_id"] = q.get("topic_id") or topic_id
                    q["subtopic_id"] = q.get("subtopic_id") or subtopic_id
                    q["path_label"] = q.get("path_label") or path_label
                    q["title"] = q.get("title") or subtopic_title
                    q["prompt"] = str(q.get("prompt") or "").strip() or sub_prompt
                    q.setdefault("level", "subtopic")
                    questions.append(q)
            else:
                # Outline-driven capture: the subtopic itself is the unit to present,
                # even when no internal question bank has been generated.
                questions.append(
                    {
                        "id": f"{subtopic_id}-present" if subtopic_id else None,
                        "topic_id": topic_id,
                        "subtopic_id": subtopic_id,
                        "path_label": path_label,
                        "title": subtopic_title,
                        "prompt": sub_prompt,
                        "question": sub_prompt,
                        "level": "subtopic",
                        "visibility": "outline",
                    }
                )
    return questions


def _normalize_topic_plan(
    incoming: Dict[str, Any],
    *,
    fallback: Optional[Dict[str, Any]] = None,
    review_status: Optional[str] = None,
    actor_user_id: Optional[str] = None,
) -> Dict[str, Any]:
    fallback = fallback or {}
    if not isinstance(incoming, dict):
        raise ValueError("Plan payload must be an object")
    raw_topics = incoming.get("topics") or []
    if not isinstance(raw_topics, list) or not raw_topics:
        raise ValueError("Plan must contain at least one topic")

    topic_ids: set[str] = set()
    subtopic_ids: set[str] = set()
    question_ids: set[str] = set()
    normalized_topics: List[Dict[str, Any]] = []
    question_counter = 1

    for topic_index, raw_topic in enumerate(raw_topics, start=1):
        if not isinstance(raw_topic, dict):
            raise ValueError("Each topic must be an object")
        topic_id = str(raw_topic.get("id") or f"topic-{topic_index:02d}").strip()
        topic_title = str(raw_topic.get("title") or f"Topic {topic_index}").strip()
        if not topic_id or topic_id in topic_ids:
            raise ValueError("Topic ids must be unique")
        topic_ids.add(topic_id)

        raw_subtopics = raw_topic.get("subtopics") or []
        if not isinstance(raw_subtopics, list) or not raw_subtopics:
            raise ValueError(f"Topic '{topic_title}' must contain at least one subtopic")

        normalized_subtopics: List[Dict[str, Any]] = []
        topic_minutes = 0
        for subtopic_index, raw_subtopic in enumerate(raw_subtopics, start=1):
            if not isinstance(raw_subtopic, dict):
                raise ValueError("Each subtopic must be an object")
            subtopic_id = str(raw_subtopic.get("id") or f"{topic_id}-sub-{subtopic_index:02d}").strip()
            subtopic_title = str(raw_subtopic.get("title") or f"Subtopic {subtopic_index}").strip()
            if not subtopic_id or subtopic_id in subtopic_ids:
                raise ValueError("Subtopic ids must be unique")
            subtopic_ids.add(subtopic_id)

            raw_questions = raw_subtopic.get("questions") or []
            if not isinstance(raw_questions, list) or not raw_questions:
                raise ValueError(f"Subtopic '{subtopic_title}' must contain at least one question")

            normalized_questions: List[Dict[str, Any]] = []
            for raw_question in raw_questions:
                if not isinstance(raw_question, dict):
                    raise ValueError("Each question must be an object")
                question_text = str(raw_question.get("question") or "").strip()
                if not question_text:
                    raise ValueError("Each question must contain text")
                question_id = str(raw_question.get("id") or f"q-{question_counter:02d}").strip()
                if not question_id or question_id in question_ids:
                    raise ValueError("Question ids must be unique")
                question_ids.add(question_id)

                minutes = int(raw_question.get("estimated_minutes") or 3)
                minutes = max(1, min(minutes, 30))
                topic_minutes += minutes
                normalized_questions.append(
                    {
                        **raw_question,
                        "id": question_id,
                        "topic_id": topic_id,
                        "subtopic_id": subtopic_id,
                        "path_label": f"{topic_title} / {subtopic_title}",
                        "title": str(raw_question.get("title") or subtopic_title).strip(),
                        "question": question_text,
                        "follow_ups": list(raw_question.get("follow_ups") or []),
                        "estimated_minutes": minutes,
                        "completion_criteria": list(raw_question.get("completion_criteria") or []),
                    }
                )
                question_counter += 1

            normalized_subtopics.append(
                {
                    **raw_subtopic,
                    "id": subtopic_id,
                    "title": subtopic_title,
                    "objective": raw_subtopic.get("objective") or "",
                    "target_gap_ids": list(raw_subtopic.get("target_gap_ids") or []),
                    "knowledge_refs": list(raw_subtopic.get("knowledge_refs") or []),
                    "questions": normalized_questions,
                }
            )

        normalized_topics.append(
            {
                **raw_topic,
                "id": topic_id,
                "title": topic_title,
                "objective": raw_topic.get("objective") or "",
                "estimated_minutes": int(raw_topic.get("estimated_minutes") or topic_minutes or 1),
                "knowledge_refs": list(raw_topic.get("knowledge_refs") or []),
                "subtopics": normalized_subtopics,
            }
        )

    previous_review = fallback.get("review") or {}
    revision = int(previous_review.get("revision") or 0) + (1 if review_status == "edited" else 0)
    review = {
        **previous_review,
        "status": review_status or previous_review.get("status") or "draft",
        "revision": max(1, revision),
    }
    if review_status == "edited":
        review.update(
            {
                "edited_by_user_id": actor_user_id,
                "edited_at": datetime.utcnow().isoformat(),
                "approved_at": None,
                "approved_by_user_id": None,
            }
        )

    plan = {
        **fallback,
        **incoming,
        "schema_version": TOPIC_PLAN_SCHEMA_VERSION,
        "topics": normalized_topics,
        "review": review,
    }
    plan["questions"] = _flatten_plan_questions(plan)
    if not plan["questions"]:
        raise ValueError("Plan must contain at least one question")
    return plan


def _plan_questions(plan: Dict[str, Any]) -> List[Dict[str, Any]]:
    if plan.get("topics"):
        return _flatten_plan_questions(plan)
    return list(plan.get("questions") or [])


def _topic_plan_requires_approval(plan: Dict[str, Any]) -> bool:
    return False


def _question_trace_metadata(plan: Dict[str, Any], question_id: Optional[str]) -> Dict[str, Any]:
    question = _find_question(plan, question_id)
    if not question:
        return {}
    return {
        "topic_id": question.get("topic_id"),
        "subtopic_id": question.get("subtopic_id"),
        "topic_path": question.get("path_label"),
    }


def _find_question(plan: Dict[str, Any], question_id: Optional[str]) -> Optional[Dict[str, Any]]:
    questions = _plan_questions(plan)
    if question_id:
        return next((q for q in questions if q.get("id") == question_id), None)
    return questions[0] if questions else None


def _find_gap(gaps: List[Dict[str, Any]], gap_id: Optional[str]) -> Optional[Dict[str, Any]]:
    if not gap_id:
        return None
    return next((gap for gap in gaps if gap.get("id") == gap_id), None)


def _next_plan_question(plan: Dict[str, Any], evaluations: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    questions = _plan_questions(plan)
    if not questions:
        return None
    sufficiently_answered = {
        ev.get("question_id") for ev in evaluations if ev.get("verdict") == "sufficient"
    }
    for question in questions:
        if question.get("id") not in sufficiently_answered:
            return question
    return {
        "id": None,
        "prompt": "Nous avons parcouru l'arborescence. Souhaitez-vous présenter un autre point avant la synthèse ?",
        "question": "Nous avons parcouru l'arborescence. Souhaitez-vous présenter un autre point avant la synthèse ?",
    }


def _metrics_for_session(session: ExpertCaptureSession) -> Dict[str, Any]:
    evaluations = session.evaluations or []
    sufficient = [ev for ev in evaluations if ev.get("verdict") == "sufficient"]
    questions = _plan_questions(session.plan or {})
    coverage = (
        len({ev.get("question_id") for ev in sufficient if ev.get("question_id")}) / len(questions)
        if questions
        else None
    )
    last_activity = session.updated_at or session.completed_at or session.started_at or session.created_at
    return {
        **(session.metrics or {}),
        "turns": len(session.transcript or []),
        "answers_evaluated": len(evaluations),
        "captured_facts": len(session.captured_facts or []),
        "coverage": round(coverage, 2) if coverage is not None else None,
        "plan_mode": (session.plan or {}).get("mode") or (session.metrics or {}).get("plan_mode"),
        "summary_short": _session_summary_short(session),
        "open_questions_count": _session_open_questions_count(session),
        "last_activity": last_activity.isoformat() if last_activity else None,
        **_compute_timer_metrics(session),
    }


def _record_capture_run(
    db: DBSession,
    *,
    workspace_id: str,
    capability_id: Optional[str],
    trigger: str,
    input_ref: Dict[str, Any],
    output_ref: Dict[str, Any],
    skill_slugs: List[str],
    initiated_by_user_id: Optional[str] = None,
) -> str:
    now = datetime.utcnow()
    run = Run(
        id=str(uuid.uuid4()),
        workspace_id=workspace_id,
        initiated_by_user_id=initiated_by_user_id,
        capability_id=capability_id,
        status="completed",
        input_ref=input_ref,
        output_ref=output_ref,
        trigger=trigger,
        started_at=now,
        completed_at=now,
        duration_ms=0.0,
        confidence=_confidence_from_output(output_ref),
    )
    db.add(run)
    db.flush()
    for slug in skill_slugs:
        db.add(
            SkillInvocation(
                id=str(uuid.uuid4()),
                run_id=run.id,
                skill_slug=slug,
                input_ref=input_ref,
                output_ref=output_ref,
                status="completed",
                started_at=now,
                completed_at=now,
                latency_ms=0.0,
                cost=0.0,
                metrics={"phase": trigger},
            )
        )
    return run.id


def _confidence_from_output(output_ref: Dict[str, Any]) -> Optional[float]:
    evaluation = output_ref.get("evaluation") or {}
    if isinstance(evaluation, dict) and evaluation.get("score") is not None:
        return float(evaluation["score"])
    return None
