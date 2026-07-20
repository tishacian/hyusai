"""Expert knowledge capture planning, session runtime and review output."""
from __future__ import annotations

import re
import asyncio
import json
import logging
import tempfile
import time
import unicodedata
import uuid
from collections import OrderedDict
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote

from sqlalchemy.orm.attributes import flag_modified, set_committed_value
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
from app.services.rag.knowledge_scopes import resolve_expert_fiche_collection
from app.services.capture_knowledge_oracle import (
    CaptureSessionContext,
    analyze_plan_oracle_async,
    compose_plan_oracle,
    plan_structure_llm_async,
    dedupe_statements,
    derive_thematic_blocks_async,
    evaluate_capture_partial,
    generate_question_bank_entry_async,
    broad_presentation_prompt,
    merge_topic_proposals,
    normalize_outline_points,
    plan_dialogue_probe,
    presentation_prompt,
    score_gaps_with_rag,
    session_context_from_capture,
    sparse_exact_match_evidence,
    _model_chat_kwargs,
    _resolve_llm_config,
)

# Async callback receiving FINAL-phase progress payloads
# ({stage, label, current?, total?, section_label?}) so transports (WS gateway)
# can stream honest progress to the loader while the heavy pass runs.
FinalizeProgressCallback = Callable[[Dict[str, Any]], Any]

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
CAPTURE_RETRIEVAL_WARM_CACHE_TTL_SECONDS = 300
CAPTURE_RETRIEVAL_WARM_CACHE_MAX_ENTRIES = 128
ORACLE_QUESTION_STATUSES = frozenset({"open", "active", "answered", "dismissed", "deferred", "addressed"})
CAPTURE_INPUT_MODALITIES = frozenset({"voice", "text"})
CAPTURE_DOCUMENT_SOURCE_KIND = "capture_document_ref"
CAPTURE_DOCUMENT_COLLECTION_PREFIX = "capture-session"
# Unified proposal open-question lifecycle. ``invalid`` is the delete/exclude
# status (replaces the legacy ``dismissed``); ``answered`` marks a question that
# was resolved via the targeted answer endpoint; ``deferred`` keeps it open for
# later / another user (publishable when ``include_unresolved_questions``).
PROPOSAL_OPEN_QUESTION_STATUSES = frozenset({"open", "answered", "invalid", "deferred"})
# Legacy aliases accepted on input and mapped into the unified set so older
# clients / stored payloads keep working.
_PROPOSAL_OPEN_QUESTION_STATUS_ALIASES = {"dismissed": "invalid", "addressed": "answered"}
# Statuses excluded from the publishable knowledge sheet.
PROPOSAL_OPEN_QUESTION_EXCLUDED_STATUSES = frozenset({"invalid", "answered"})
# Generic evaluation relance copied into session.evaluations — must not replace
# grounded/live oracle questions in the proposal report.
_GENERIC_CONTRADICTION_FOLLOWUP = "Clarifier ce qui contredit ou met à jour la source existante."
_GENERIC_EVALUATION_OPEN_QUESTIONS = frozenset(
    {
        _GENERIC_CONTRADICTION_FOLLOWUP.lower(),
        "contradiction ou mise à jour à clarifier",
    }
)

_logger = logging.getLogger(__name__)
_CAPTURE_RETRIEVAL_WARM_CACHE: OrderedDict[str, tuple[float, Dict[str, Any]]] = OrderedDict()
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
            "session_end_pending": bool((session.metrics or {}).get("session_end_pending")),
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


def _warm_cache_key(session_id: str) -> str:
    return str(session_id or "").strip()


def _set_capture_warm_cache(session_id: str, payload: Dict[str, Any]) -> None:
    key = _warm_cache_key(session_id)
    if not key:
        return
    _CAPTURE_RETRIEVAL_WARM_CACHE[key] = (time.time(), payload)
    _CAPTURE_RETRIEVAL_WARM_CACHE.move_to_end(key)
    while len(_CAPTURE_RETRIEVAL_WARM_CACHE) > CAPTURE_RETRIEVAL_WARM_CACHE_MAX_ENTRIES:
        _CAPTURE_RETRIEVAL_WARM_CACHE.popitem(last=False)


def _get_capture_warm_cache(session_id: str) -> Optional[Dict[str, Any]]:
    key = _warm_cache_key(session_id)
    item = _CAPTURE_RETRIEVAL_WARM_CACHE.get(key)
    if not item:
        return None
    created_at, payload = item
    if time.time() - created_at > CAPTURE_RETRIEVAL_WARM_CACHE_TTL_SECONDS:
        _CAPTURE_RETRIEVAL_WARM_CACHE.pop(key, None)
        return None
    _CAPTURE_RETRIEVAL_WARM_CACHE.move_to_end(key)
    return dict(payload)


def _compact_retrieval_context(retrieval_context: Mapping[str, Any]) -> Dict[str, Any]:
    chunks = list(retrieval_context.get("chunks") or [])[:4]
    scores = list(retrieval_context.get("scores") or [])[:4]
    metadatas = list(retrieval_context.get("metadatas") or [])[:4]
    metrics = retrieval_context.get("metrics") if isinstance(retrieval_context.get("metrics"), Mapping) else {}
    return {
        "chunks": chunks,
        "scores": scores,
        "metadatas": metadatas,
        "pipeline": retrieval_context.get("pipeline"),
        "retrieval_profile": retrieval_context.get("retrieval_profile") or metrics.get("retrieval_profile"),
        "dense_only": metrics.get("dense_only"),
        "sparse_status": metrics.get("sparse_status"),
        "sparse_backend": metrics.get("sparse_backend"),
        "fallback_reason": metrics.get("fallback_reason"),
    }


async def warm_capture_context_cache(
    db: DBSession,
    *,
    workspace_id: str,
    workspace_slug: Optional[str],
    session_id: str,
    timeout_seconds: float = RETRIEVAL_PREFETCH_TIMEOUT_SECONDS,
) -> Dict[str, Any]:
    session = get_session(db, workspace_id=workspace_id, session_id=session_id)
    ctx = _load_context(db, workspace_id, session.context_id)
    collection_name = _resolve_collection_name(ctx)
    query = " ".join(part for part in (session.title, session.objective) if part).strip()
    if not query:
        query = "Expert Knowledge Capture context warmup"
    started = time.perf_counter()
    status = "completed"
    detail: Dict[str, Any] = {"collection_name": collection_name, "retrieval_profile": "oracle_fast"}
    try:
        from app.services.rag.context import retrieve_rag_context

        retrieval_context = await asyncio.wait_for(
            retrieve_rag_context(
                {
                    "query": query,
                    "workspace_id": workspace_id,
                    "workspace_slug": workspace_slug,
                    "capability_id": session.capability_id,
                    "system_id": session.system_id,
                    "context_collection": collection_name,
                    "retrieval_profile": "oracle_fast",
                    "latency_profile": "fast",
                    "rag_pipeline_mode": "auto",
                    "top_k": 4,
                    "source_display_k": 4,
                    "candidate_pool_k": 20,
                }
            ),
            timeout=timeout_seconds,
        )
        compact = _compact_retrieval_context(retrieval_context)
        _set_capture_warm_cache(session.id, compact)
        detail.update(
            {
                "chunks": len(compact.get("chunks") or []),
                "pipeline": compact.get("pipeline"),
                "dense_only": compact.get("dense_only"),
                "sparse_status": compact.get("sparse_status"),
                "sparse_backend": compact.get("sparse_backend"),
                "fallback_reason": compact.get("fallback_reason"),
            }
        )
    except TimeoutError:
        status = "timeout"
        detail["reason"] = f"warm cache retrieval exceeded {timeout_seconds:.1f}s"
    except Exception as exc:  # noqa: BLE001
        status = "error"
        detail["reason"] = str(exc)
    latency_ms = int((time.perf_counter() - started) * 1000)
    metrics = dict(session.metrics or {})
    metrics["retrieval_warm_cache"] = {
        "status": status,
        "latency_ms": latency_ms,
        **detail,
    }
    session.metrics = metrics
    _record_capture_event(
        db,
        session=session,
        event_type="retrieval_warm_cache_completed" if status == "completed" else "retrieval_warm_cache_failed",
        source="capture_engine",
        status=status,
        meta_data=metrics["retrieval_warm_cache"],
    )
    db.commit()
    return metrics["retrieval_warm_cache"]


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
    for field in ("id", "gap_id", "follow_up", "reason", "text"):
        value = _clean_optional_string(question.get(field))
        if value:
            keys.add(value)
            keys.add(value.lower())
    if index is not None:
        keys.add(f"question-{index}")
    return keys


def _normalize_proposal_open_question_status(value: Any) -> str:
    status = str(value or "open").strip().lower()
    status = _PROPOSAL_OPEN_QUESTION_STATUS_ALIASES.get(status, status)
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
    event_list = list(events or [])
    deferred_item_ids = {
        str((event.meta_data or {}).get("item_id"))
        for event in event_list
        if event.event_type in {"quality_item_deferred", "capture_quality_deferred"}
        and (event.meta_data or {}).get("deferred_reason")
        and (event.meta_data or {}).get("item_id")
    }

    for evaluation in session.evaluations or []:
        verdict = str(evaluation.get("verdict") or "")
        follow_up = evaluation.get("follow_up")
        item_id = str(evaluation.get("id") or evaluation.get("question_id") or uuid.uuid4())
        if item_id in seen or item_id in deferred_item_ids:
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

    for event in event_list:
        meta = event.meta_data or {}
        deferred = meta.get("deferred_reason")
        if deferred and event.event_type in {"quality_item_deferred", "capture_quality_deferred"}:
            label = meta.get("label") or _effective_event_text(event) or "Élément reporté"
            bucket = meta.get("bucket") or "open_questions"
            payload = {
                "id": str(meta.get("item_id") or event.id),
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
        question_id = question.get("gap_id") or question.get("id")
        if question_id and str(question_id) in deferred_item_ids:
            continue
        status = _stored_oracle_question_status(
            plan,
            question_id=question_id,
            question_text=label,
        ) or "open"
        if status in {"answered", "dismissed", "addressed"}:
            continue
        open_questions.append(
            {
                "id": question_id or str(uuid.uuid4()),
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
    clean_bucket = (bucket or "open_questions").strip()
    if clean_bucket not in {"imprecisions", "contradictions", "open_questions"}:
        raise ValueError("Quality bucket not found")
    events = list_capture_events(db, workspace_id=workspace_id, session_id=session_id)
    backlog = build_quality_backlog(session, events)
    candidate = next(
        (
            item
            for item in backlog.get(clean_bucket, [])
            if str(item.get("id") or "") == str(item_id or "")
        ),
        None,
    )
    if not candidate:
        raise ValueError("Quality item not found")
    reason = (deferred_reason or "end_of_session").strip()
    label = candidate.get("label") or candidate.get("follow_up") or reason
    _record_capture_event(
        db,
        session=session,
        event_type="quality_item_deferred",
        source="operator_edit",
        status="deferred",
        created_by=actor_user_id,
        meta_data={
            "item_id": item_id,
            "bucket": clean_bucket,
            "deferred_reason": reason,
            "label": label,
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


def session_is_archived(session: ExpertCaptureSession) -> bool:
    return bool((session.metrics or {}).get("archived"))


def archive_capture_session(
    db: DBSession,
    *,
    workspace_id: str,
    session_id: str,
    archived: bool = True,
    actor_user_id: Optional[str] = None,
) -> ExpertCaptureSession:
    """Soft-archive (or restore) a capture session via a metrics flag.

    Archived sessions stay fully readable (transcript, proposals, audit trail)
    but are hidden from the default sessions listing.
    """
    session = get_session(db, workspace_id=workspace_id, session_id=session_id)
    metrics = dict(session.metrics or {})
    if archived:
        metrics["archived"] = True
        metrics["archived_at"] = datetime.utcnow().isoformat()
        if actor_user_id:
            metrics["archived_by_user_id"] = actor_user_id
    else:
        metrics.pop("archived", None)
        metrics.pop("archived_at", None)
        metrics.pop("archived_by_user_id", None)
    session.metrics = metrics
    flag_modified(session, "metrics")
    db.commit()
    db.refresh(session)
    return session


def delete_capture_session(
    db: DBSession,
    *,
    workspace_id: str,
    session_id: str,
) -> None:
    """Permanently delete a capture session (events and proposals cascade)."""
    session = get_session(db, workspace_id=workspace_id, session_id=session_id)
    db.delete(session)
    db.commit()


def _is_plan_build_schema(plan: Dict[str, Any]) -> bool:
    return plan.get("schema_version") in PLAN_BUILD_SCHEMA_VERSIONS or plan.get("mode") in {
        "plan_build",
        "provided_plan",
    }


def _build_retrieval_request(
    *,
    text: str,
    workspace_id: str,
    workspace_slug: Optional[str],
    session: Any,
    collection_name: Optional[str],
    profile: str,
    latency_profile: str,
    top_k: int,
) -> Dict[str, Any]:
    """Single source of truth for the retrieval request dict.

    Shared by the in-process and worker retrieval paths so the two can't drift.
    """
    return {
        "query": text,
        "workspace_id": workspace_id,
        "workspace_slug": workspace_slug,
        "capability_id": session.capability_id,
        "system_id": session.system_id,
        "context_collection": collection_name,
        "retrieval_profile": profile,
        "latency_profile": latency_profile,
        "rag_pipeline_mode": "auto",
        "top_k": max(1, min(top_k, 8)),
        "source_display_k": max(1, min(top_k, 8)),
        "candidate_pool_k": 20,
    }


async def _retrieve_context_chunks_async(
    db: Optional[DBSession],
    *,
    workspace_id: str,
    workspace_slug: Optional[str],
    session: Any,
    query: str,
    top_k: int = 4,
    retrieval_profile: str = "oracle_fast",
    collection_name: Optional[str] = None,
) -> Tuple[List[str], List[Dict[str, Any]], List[float]]:
    """Retrieve context chunks for the capture session.

    ``retrieval_profile`` selects the RAG lane: ``oracle_fast`` (default) for the
    live capture path (low latency), or ``chat`` for the FINAL phase
    (corpus_planner + hybrid + cross-encoder, chat-grade quality).

    ``collection_name`` may be pre-resolved by the caller (FINAL concurrent
    path), in which case ``db`` is never touched — the retrieval itself never
    uses the SQLAlchemy session, so the call is safe to run concurrently.
    """
    text = (query or "").strip()
    if not text:
        return [], [], []
    profile = (retrieval_profile or "oracle_fast").strip() or "oracle_fast"
    latency_profile = "balanced" if profile == "chat" else "fast"

    from app.core.config import settings as cfg

    # Worker path: when enabled and the collection is already resolved, run the
    # retrieval in the Celery worker process (its own GIL). The realtime event
    # loop only enqueues (off-loop via to_thread) and awaits loop-free, so the
    # CPU-bound retrieval can never block the transcript relay. We never touch
    # the DB here; a missing collection falls through to the in-process path.
    if cfg.voice_oracle_retrieval_via_worker and collection_name is not None:
        try:
            from app.services.rag.context import (
                await_rag_retrieval_task,
                dispatch_rag_retrieval_task,
            )

            request = _build_retrieval_request(
                text=text,
                workspace_id=workspace_id,
                workspace_slug=workspace_slug,
                session=session,
                collection_name=collection_name,
                profile=profile,
                latency_profile=latency_profile,
                top_k=top_k,
            )
            async_result = await asyncio.to_thread(
                dispatch_rag_retrieval_task,
                request,
                queue=cfg.voice_oracle_retrieval_queue,
            )
            result = await await_rag_retrieval_task(
                async_result, cfg.voice_oracle_retrieval_timeout_seconds
            )
            return (
                list(result.get("chunks") or []),
                list(result.get("metadatas") or []),
                list(result.get("scores") or []),
            )
        except Exception:
            return [], [], []

    try:
        if collection_name is None:
            ctx = _load_context(db, workspace_id, session.context_id)
            collection_name = _resolve_collection_name(ctx)
        from app.services.rag.context import retrieve_rag_context

        result = await retrieve_rag_context(
            _build_retrieval_request(
                text=text,
                workspace_id=workspace_id,
                workspace_slug=workspace_slug,
                session=session,
                collection_name=collection_name,
                profile=profile,
                latency_profile=latency_profile,
                top_k=top_k,
            )
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


async def _plan_dialogue_oracle_parallel_async(
    db: DBSession,
    *,
    workspace_id: str,
    workspace_slug: Optional[str],
    session: ExpertCaptureSession,
    plan: Dict[str, Any],
    query: str,
    latest_instruction: str = "",
) -> Tuple[List[str], List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any], Dict[str, float]]:
    """Plan dialogue turn: run RAG retrieval and the LLM structuring concurrently.

    The structuring prompt only ever uses RAG chunks as kb_ref evidence (never to
    widen scope), so the LLM call can start immediately instead of waiting ~1-3s
    for retrieval. Deterministic post-processing (gaps scoring, contradiction
    detection, kb_refs) still runs on the retrieved chunks once both complete.
    """
    started = time.monotonic()
    context = session_context_from_capture(
        session=session,
        plan=plan,
        latest_instruction=latest_instruction,
    )
    retrieval_task = asyncio.create_task(
        _retrieve_context_chunks_async(
            db,
            workspace_id=workspace_id,
            workspace_slug=workspace_slug,
            session=session,
            query=query,
        )
    )
    llm_task = asyncio.create_task(plan_structure_llm_async(context))
    rag_chunks, rag_metadatas, _scores = await retrieval_task
    retrieval_ms = (time.monotonic() - started) * 1000.0
    gaps = build_knowledge_gaps(
        objective=query,
        expert_profile=session.expert_profile,
        context_snapshot=plan.get("context") or {},
        knowledge_refs=list(plan.get("knowledge_refs") or []),
        rag_chunks=rag_chunks,
        rag_metadatas=rag_metadatas,
    )
    parsed = await llm_task
    llm_ms = (time.monotonic() - started) * 1000.0
    oracle = compose_plan_oracle(
        context,
        parsed,
        rag_chunks=rag_chunks,
        rag_metadatas=rag_metadatas,
        base_gaps=gaps,
    )
    timings = {
        "retrieval_ms": round(retrieval_ms, 1),
        "llm_ms": round(llm_ms, 1),
        "total_ms": round((time.monotonic() - started) * 1000.0, 1),
    }
    return rag_chunks, rag_metadatas, gaps, oracle, timings


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
    rag_chunks, rag_metadatas, gaps, oracle, oracle_timings = asyncio.run(
        _plan_dialogue_oracle_parallel_async(
            db,
            workspace_id=workspace_id,
            workspace_slug=workspace_slug,
            session=session,
            plan=plan,
            query=f"{session.objective} {subject}".strip(),
            latest_instruction=clean,
        )
    )
    plan["topics"] = merge_topic_proposals(plan, oracle.get("topic_proposals") or [])
    plan["oracle"] = {
        "coverage_gaps": oracle.get("coverage_gaps") or [],
        "contradiction_candidates": oracle.get("contradiction_candidates") or [],
        "oracle_exact_matches": oracle.get("oracle_exact_matches") or [],
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
        text_raw=clean or None,
        source="capture_engine",
        status="accepted",
        created_by=actor_user_id,
        meta_data={
            "turn_count": len(turns),
            "ready_to_finalize": dialogue["ready_to_finalize"],
            "capture_phase": "plan_build",
        },
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
            "oracle_exact_match_count": len(oracle.get("oracle_exact_matches") or []),
            # Latency profile of the parallel retrieval + LLM structuring pass.
            "oracle_timings_ms": oracle_timings,
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
            "oracle_exact_matches": oracle.get("oracle_exact_matches") or [],
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
        if not isinstance(raw_subtopics, list):
            raw_subtopics = []
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
        subtopics = [node for node in (topic.get("subtopics") or []) if isinstance(node, dict)]
        capture_units = subtopics or ([topic] if isinstance(topic, dict) else [])
        for unit in capture_units:
            unit_id = str(unit.get("id") or "")
            title = str(unit.get("title") or "Sujet")
            objective = str(unit.get("objective") or session.objective or "")
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
                        "title": _source_display_title(md),
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
                    "subtopic_id": unit_id,
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

    from app.services.capture_templates import (
        header_fields_from_plan,
        required_field_gaps,
        resolve_session_capture_template,
        site_modification_consistency_question,
    )

    capture_template = resolve_session_capture_template(
        plan=plan,
        metrics=session.metrics or {},
    )
    header_fields = header_fields_from_plan(plan)
    if capture_template:
        for gap in required_field_gaps(capture_template, header_fields):
            slug = str(gap.get("slug") or gap.get("id") or "").strip()
            text = str(gap.get("description") or gap.get("title") or "").strip()
            if not text:
                continue
            key = slug or text.lower()
            if key in seen:
                continue
            seen.add(key)
            items.append(
                {
                    "id": slug or f"open-{len(items) + 1:02d}",
                    "text": text,
                    "topic_id": gap.get("topic_id"),
                    "priority": _coerce_priority(gap.get("priority")),
                    "status": "open",
                    "blocking": True,
                    "required_field_key": gap.get("required_field_key"),
                    "source": "capture_template_required_field",
                }
            )
        consistency = site_modification_consistency_question(header_fields, expert_text)
        if consistency:
            key = str(consistency.get("id") or consistency.get("gap_id") or "").strip()
            if key and key not in seen:
                seen.add(key)
                items.append(
                    {
                        "id": key,
                        "text": consistency.get("text"),
                        "topic_id": None,
                        "priority": _coerce_priority(consistency.get("priority")),
                        "status": "open",
                        "blocking": False,
                        "required_field_key": consistency.get("required_field_key"),
                        "source": consistency.get("source"),
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
    # Per-partial hot path: skip the ledger rematerialization. The live oracle's
    # ``recent_transcript`` context is best-effort and must not pay an O(N) rebuild
    # on every partial; it reads the cached column (slightly behind during silent
    # capture, which is acceptable for contradiction-tracking heuristics).
    session = get_session(db, workspace_id=workspace_id, session_id=session_id, materialize=False)
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
    active_section_confidence = float(evaluation.get("active_section_confidence") or 0.0)
    from app.services.capture_knowledge_oracle import LIVE_SECTION_DETECT_MIN_CONFIDENCE

    if (
        active_subtopic_id
        and active_section_confidence >= LIVE_SECTION_DETECT_MIN_CONFIDENCE
        and active_subtopic_id != metrics.get("active_subtopic_id")
    ):
        metrics["active_subtopic_id"] = active_subtopic_id
        session.metrics = metrics
        flag_modified(session, "metrics")
        _record_capture_event(
            db,
            session=session,
            event_type="subtopic_focus_changed",
            source="capture_engine",
            status="accepted",
            meta_data={
                "active_subtopic_id": active_subtopic_id,
                "active_section_confidence": active_section_confidence,
                "client_turn_id": client_turn_id,
            },
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
                "oracle_exact_matches": hint.get("oracle_exact_matches") or [],
                "exact_match_backend": hint.get("exact_match_backend"),
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
    return {
        "hints": pushed,
        "active_subtopic_id": active_subtopic_id,
        "active_topic_id": evaluation.get("active_topic_id"),
        "active_section_confidence": active_section_confidence,
        "session": session,
        "contradiction_candidates": evaluation.get("contradiction_candidates") or [],
        "oracle_exact_matches": evaluation.get("oracle_exact_matches") or [],
        "retrieval": evaluation.get("retrieval") or [],
    }


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
            for turn in _read_transcript(session, events=events)
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
    expert_user_id = session.created_by_user_id or proposal.created_by_user_id
    expert_name = _resolve_user_label(db, expert_user_id) or (actor_label if not expert_user_id else None)
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
        or _default_publication_collection(db, workspace, ctx)
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
    if expert_name:
        publication_meta["expert_name"] = expert_name
        metadata["expert_name"] = expert_name
    if expert_user_id:
        publication_meta["expert_user_id"] = expert_user_id
        metadata["captured_by_user_id"] = expert_user_id
    unresolved_count = _count_open_questions(proposal_payload)
    related_documents = _related_capture_documents_from_payload(proposal_payload)
    publication_meta["open_questions_count"] = unresolved_count
    if related_documents:
        publication_meta["related_documents"] = related_documents
        metadata["related_documents"] = related_documents
    metadata["proposal_id"] = proposal.id
    metadata["capture_session_id"] = session.id
    if publication_category:
        metadata["publication_category"] = publication_category
    if publication_destination:
        metadata["publication_destination"] = publication_destination
    if publication_title:
        metadata["publication_final_title"] = publication_title
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
    # The stored report_markdown keeps the open questions; only the artifact
    # actually published/ingested is stripped when the reviewer excluded them.
    if content and not bool(publication_meta.get("include_unresolved_questions", True)):
        content = _strip_open_questions_section(content)

    from app.services.knowledge_collections import create_or_get_collection
    from app.services.object_store import get_object_store
    from app.services.knowledge_collections import ingested_key, original_key
    from app.core.settings_manager import get_resolved_settings
    from app.services.rag.vector_store_config import resolve_vector_db_type
    from app.services.rag.document_service import DocumentService

    slug = (publication_destination or collection_name).replace("_", "-")[:80] or "expert-capture"
    collection = create_or_get_collection(
        db,
        workspace=workspace,
        slug=slug,
        name=publication_destination or collection_name,
        description="Expert capture publications",
    )
    db.flush()
    # Honour end-of-capture triage: documents marked ``share_level=none`` stay
    # citable in the report but must never be promoted into the KB collection.
    share_levels = _capture_document_share_levels(session)
    promotable_documents = [
        ref
        for ref in related_documents
        if not (isinstance(ref, dict) and _capture_document_ref_share_level(ref, share_levels) == "none")
    ]
    promoted_documents = _promote_capture_documents_for_publication(
        db,
        workspace=workspace,
        destination_collection=collection,
        related_documents=promotable_documents,
    )
    if promoted_documents:
        proposal_payload = _rewrite_capture_document_sources_to_publication(proposal_payload, promoted_documents)
        related_documents = _related_capture_documents_from_payload(proposal_payload)
        publication_meta = dict(proposal_payload.get("publication") or publication_meta)
        recommended = dict(proposal_payload.get("recommended_ingestion") or recommended)
        metadata = dict(recommended.get("metadata") or metadata)
        publication_meta["related_documents"] = related_documents
        publication_meta["promoted_documents"] = promoted_documents
        metadata["related_documents"] = related_documents
        metadata["promoted_documents"] = promoted_documents
        recommended["metadata"] = metadata
        proposal_payload["recommended_ingestion"] = recommended
        proposal_payload["publication"] = publication_meta
        proposal.proposal = proposal_payload
        flag_modified(proposal, "proposal")
    from app.services.capture_templates import (
        header_fields_from_plan,
        publication_filename_from_header,
        resolve_session_capture_template,
    )

    publish_template = resolve_session_capture_template(
        plan=session.plan or {},
        metrics=session.metrics or {},
    )
    filename = (
        _clean_optional_string(publication_meta.get("filename"))
        or _clean_optional_string(metadata.get("publication_filename"))
    )
    if not filename and publish_template:
        filename = publication_filename_from_header(
            header_fields_from_plan(session.plan or {}),
            fallback_session_id=session.id,
        )
    if not filename:
        filename = f"capture-{session.id[:8]}.md"
    publication_meta["filename"] = filename
    metadata["publication_filename"] = filename
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
        ingest_metadata = {
            key: value
            for key, value in {
                "source": "expert_capture_session",
                "capture_session_id": session.id,
                "proposal_id": proposal.id,
                "publication_category": publication_category,
                "publication_destination": publication_destination,
                "publication_final_title": publication_title,
                "publication_filename": filename,
                "collection_slug": collection.slug,
                "expert_name": expert_name,
                "captured_by_user_id": expert_user_id,
                "open_questions_count": unresolved_count,
                # Carry the expert-fiche provenance so the Volet 3 ranking boost
                # (keyed on source_type=expert_fiche) survives ingestion. Every
                # capture publication IS an expert fiche, so default the marker
                # when the proposal did not set it; without the pin/boost flags
                # enabled this changes no ranking. FSE templates override with
                # ``source_type=fse_report`` via publication defaults.
                "source_type": metadata.get("source_type") or "expert_fiche",
                "origin": metadata.get("origin"),
                "input_modality": metadata.get("input_modality"),
                "related_documents": metadata.get("related_documents"),
                "fse_customer": metadata.get("fse_customer"),
                "fse_machine": metadata.get("fse_machine"),
                "fse_reference": metadata.get("fse_reference"),
                "fse_country": metadata.get("fse_country"),
                "fse_intervention_date": metadata.get("fse_intervention_date"),
                "fse_intervention_type": metadata.get("fse_intervention_type"),
                "fse_week": metadata.get("fse_week"),
            }.items()
            if value
        }
        result = await doc_service.ingest_document(
            str(path),
            collection_name=collection.slug,
            collection_slug=collection.slug,
            document_metadata=ingest_metadata,
        )
    document_id = result.get("document_id")
    if str(result.get("status") or "").lower() != "success" or not document_id:
        # Vector ingest failed: keep the proposal ``accepted`` so publication can
        # be retried, and persist the failure on the publication payload.
        publication_meta["status"] = "failed"
        publication_meta["error"] = str(result.get("error") or "Vector ingestion failed")
        publication_meta["failed_at"] = datetime.utcnow().isoformat()
        proposal_payload["publication"] = publication_meta
        proposal.proposal = proposal_payload
        flag_modified(proposal, "proposal")
        emit_audit_event(
            db=db,
            workspace_id=workspace.id,
            event_type="kc.proposal.publish_failed",
            actor=actor_label,
            details={
                "proposal_id": proposal.id,
                "session_id": session.id,
                "collection": collection.slug,
                "error": publication_meta["error"],
            },
        )
        db.commit()
        raise ValueError(f"Publication failed during vector ingestion: {publication_meta['error']}")
    export_urls: Dict[str, str] = {}
    if document_id:
        raw_url = f"/api/v1/documents/{quote(str(document_id), safe='')}/raw"
        export_urls = {
            "download_url": raw_url,
            "raw_url": raw_url,
        }
        publication_meta["export_urls"] = export_urls
        publication_meta["document_id"] = document_id
        publication_meta["collection_slug"] = collection.slug
        publication_meta["chunks_processed"] = result.get("chunks_processed", 0)
        proposal_payload["publication"] = publication_meta
        proposal.proposal = proposal_payload
        flag_modified(proposal, "proposal")
        db.flush()
    proposal.status = "published"
    # Clear any failure markers left by a previous unsuccessful attempt.
    publication_meta["status"] = "published"
    publication_meta.pop("error", None)
    publication_meta.pop("failed_at", None)
    publication_meta["published_at"] = datetime.utcnow().isoformat()
    proposal_payload["publication"] = publication_meta
    proposal.proposal = proposal_payload
    flag_modified(proposal, "proposal")
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
            "expert_name": expert_name,
            "open_questions_count": unresolved_count,
            "export_urls": export_urls,
            "promoted_documents": promoted_documents,
        },
    )
    db.commit()
    promotion_job_ids = sorted(
        {
            str(item.get("job_id"))
            for item in promoted_documents
            if isinstance(item, dict) and item.get("job_id")
        }
    )
    if promotion_job_ids:
        from app.models.knowledge_collection import WorkerJob
        from app.services.worker_dispatch import dispatch_worker_job

        for job_id in promotion_job_ids:
            job = db.query(WorkerJob).filter(WorkerJob.id == job_id).first()
            if job:
                dispatch_worker_job(db, job, allow_inline_fallback=False)
        db.commit()
    return {
        "proposal_id": proposal.id,
        "expert_name": expert_name,
        "open_questions_count": unresolved_count,
        "collection": collection.slug,
        "document_id": document_id,
        "chunks_processed": result.get("chunks_processed", 0),
        "status": result.get("status"),
        "category": publication_category,
        "destination": publication_destination,
        "destination_scope": publication_destination,
        "final_title": publication_title,
        "export_urls": export_urls,
        "promoted_documents": promoted_documents,
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
                "source": md.get("source") or _source_display_filename(md) or md.get("document_id"),
                "title": _source_display_title(md),
                "collection": md.get("collection") or md.get("collection_name"),
                "metadata": md,
            }
        )
    return formatted


def structure_capture_payload(
    session: ExpertCaptureSession,
    transcript_events: Optional[List[ExpertCaptureEvent]] = None,
    *,
    plan_snapshot: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    transcript = _read_transcript(session, events=transcript_events)
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

    plan = dict(plan_snapshot if plan_snapshot is not None else (session.plan or {}))
    open_questions = _build_proposal_open_questions(session, plan, evaluations)
    from app.services.capture_templates import (
        header_fields_from_plan,
        required_field_open_questions,
        resolve_session_capture_template,
        site_modification_consistency_question,
    )

    capture_template = resolve_session_capture_template(
        plan=plan,
        metrics=session.metrics or {},
    )
    header_fields = header_fields_from_plan(plan)
    if capture_template:
        # Missing required header fields become blocking open questions in review.
        existing_keys = {
            str(item.get("required_field_key") or item.get("gap_id") or item.get("id") or "").strip()
            for item in open_questions
            if isinstance(item, dict)
        }
        for question in required_field_open_questions(
            capture_template,
            header_fields,
        ):
            key = str(question.get("required_field_key") or question.get("gap_id") or "").strip()
            if key and key in existing_keys:
                continue
            open_questions.insert(0, question)
            if key:
                existing_keys.add(key)
        transcript_text = " ".join(
            str(turn.get("text") or "")
            for turn in transcript
            if turn.get("speaker") == "expert"
        )
        consistency = site_modification_consistency_question(header_fields, transcript_text)
        if consistency:
            key = str(consistency.get("id") or consistency.get("gap_id") or "").strip()
            if key and key not in existing_keys:
                open_questions.insert(0, consistency)
                existing_keys.add(key)
    # Plan-hierarchy aligned structuring of the captured facts, enriched with the
    # per-section FINAL synthesis when available (cabled _structure_facts_by_plan).
    plan_structure = _structure_facts_by_plan(plan, captured)
    plan_structure = _attach_section_synthesis(plan_structure, plan)
    plan_structure = _filter_redundant_unassigned_facts(plan_structure)
    plan_structure = _ensure_free_conversation_report_topic(
        session,
        plan_structure,
        captured,
        open_questions,
    )
    from app.services.capture_report_templates import (
        FSE_INTERVENTION_REPORT_TEMPLATE_ID,
        build_knowledge_sheet_content,
        resolve_knowledge_sheet_template,
    )

    template_id = resolve_knowledge_sheet_template(session)
    stored_synthesis = plan.get("section_synthesis") if isinstance(plan.get("section_synthesis"), dict) else {}
    has_final_synthesis = any(
        isinstance(entry, dict) and str(entry.get("synthesis") or "").strip()
        for entry in stored_synthesis.values()
    )
    # FSE report template keeps fixed sections; do not free-assemble from section synthesis.
    if has_final_synthesis and template_id != FSE_INTERVENTION_REPORT_TEMPLATE_ID:
        # The FINAL pass ran: the report is assembled from the per-section
        # restructured syntheses (deduped, glossary-aligned), not the raw facts.
        markdown = _assemble_report_from_sections(session, plan_structure, open_questions)
    else:
        markdown = build_knowledge_sheet_content(
            template_id,
            session,
            captured,
            open_questions,
            transcript=transcript,
            plan_structure=plan_structure,
        )
    blocking_required = [
        item
        for item in open_questions
        if isinstance(item, dict) and item.get("blocking") and item.get("source") == "capture_template_required_field"
    ]
    transcript_segments = _build_transcript_segments(transcript, event_rows)
    return {
        "session_id": session.id,
        "title": session.title,
        "objective": session.objective,
        "context_id": session.context_id,
        "captured_facts": captured,
        "plan_structure": plan_structure,
        "open_questions": open_questions,
        "finalize_checklist": {
            "required_fields_complete": not blocking_required,
            "missing_required_fields": [
                {
                    "key": item.get("required_field_key"),
                    "label": (item.get("follow_up") or item.get("text") or "").replace(
                        "Champ obligatoire manquant : ", ""
                    ),
                    "blocking": True,
                }
                for item in blocking_required
            ],
            "capture_template_id": (capture_template or {}).get("id"),
        },
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
    default_destination: Optional[str] = None,
) -> Dict[str, Any]:
    from app.services.capture_templates import (
        header_fields_from_plan,
        publication_defaults_from_template,
        publication_filename_from_header,
        publication_title_from_header,
        resolve_session_capture_template,
        tracking_metadata_from_header,
    )

    publication = dict(previous_publication or {})
    existing = payload.get("publication")
    if isinstance(existing, dict):
        publication.update(existing)
    capture_template = resolve_session_capture_template(
        plan=session.plan or {},
        metrics=session.metrics or {},
    )
    template_publication = publication_defaults_from_template(capture_template)
    header_fields = header_fields_from_plan(session.plan or {})
    snapshot = (session.plan or {}).get("capture_template")
    intervention_type = None
    if isinstance(snapshot, dict):
        intervention_type = snapshot.get("intervention_type")
    category = _clean_optional_string(publication.get("category")) or _suggest_publication_category(session, payload)
    destination = (
        _clean_optional_string(publication.get("destination"))
        or _clean_optional_string(publication.get("destination_scope"))
        or _clean_optional_string(template_publication.get("destination"))
        or _clean_optional_string(default_destination)
        or _resolve_collection_name(ctx)
    )
    recommended = payload.get("recommended_ingestion") if isinstance(payload.get("recommended_ingestion"), dict) else {}
    fse_title = (
        publication_title_from_header(header_fields, fallback="")
        if capture_template
        else ""
    )
    final_title = (
        _clean_optional_string(publication.get("final_title"))
        or _clean_optional_string(fse_title)
        or _clean_optional_string(recommended.get("title"))
        or _clean_optional_string(payload.get("title"))
        or session.title
    )
    source_type = (
        _clean_optional_string(publication.get("source_type"))
        or _clean_optional_string(template_publication.get("source_type"))
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
    if source_type:
        publication["source_type"] = source_type
    if capture_template:
        filename = publication_filename_from_header(
            header_fields,
            fallback_session_id=session.id,
        )
        publication["filename"] = filename
    tracking = tracking_metadata_from_header(
        header_fields,
        intervention_type=str(intervention_type or "") or None,
    )
    if tracking:
        publication["tracking"] = {**(publication.get("tracking") or {}), **tracking}
    payload["publication"] = publication
    metadata = dict(recommended.get("metadata") or {})
    metadata.setdefault("publication_category_suggested", category)
    metadata.setdefault("publication_destination_suggested", destination)
    metadata.setdefault("publication_destination_scope_suggested", destination)
    if source_type:
        metadata.setdefault("source_type", source_type)
    if capture_template:
        metadata["publication_filename"] = publication.get("filename")
    metadata.update(tracking)
    recommended["metadata"] = metadata
    if capture_template and fse_title:
        recommended["title"] = final_title
    payload["recommended_ingestion"] = recommended
    return payload


def _normalize_input_modality(value: Optional[str], *, audio_ref: Optional[str] = None) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in CAPTURE_INPUT_MODALITIES:
        return normalized
    return "voice" if audio_ref else "text"


def _positive_int(value: Any) -> Optional[int]:
    if value is None or str(value).strip() == "":
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _capture_timecode_ms(session: ExpertCaptureSession, at: Optional[datetime] = None) -> Optional[int]:
    start = session.started_at or session.created_at
    if not start:
        return None
    current = at or datetime.utcnow()
    try:
        return max(0, int((current - start).total_seconds() * 1000))
    except Exception:
        return None


def _normalize_capture_document_ref(value: Any, *, default_timecode_ms: Optional[int] = None) -> Optional[Dict[str, Any]]:
    if not isinstance(value, Mapping):
        return None
    document_id = str(value.get("document_id") or value.get("doc_id") or "").strip()
    collection = str(value.get("collection") or value.get("collection_name") or "").strip()
    filename = str(value.get("filename") or value.get("document_filename") or "").strip()
    title = str(value.get("title") or value.get("document_title") or filename or "").strip()
    if not (document_id or filename or title):
        return None
    page = _positive_int(value.get("page") or value.get("page_number"))
    slide = _positive_int(value.get("slide") or value.get("slide_number"))
    image_index = _positive_int(value.get("image_index"))
    ref: Dict[str, Any] = {
        "kind": CAPTURE_DOCUMENT_SOURCE_KIND,
        "document_id": document_id or None,
        "collection": collection or None,
        "collection_name": collection or None,
        "filename": filename or None,
        "title": title or filename or document_id or None,
        "page": page,
        "page_number": page,
        "slide": slide,
        "image_index": image_index,
        "anchor_id": value.get("anchor_id") or value.get("anchor"),
        "preview": str(value.get("preview") or value.get("excerpt") or "").strip() or None,
        "association_mode": str(value.get("association_mode") or "active_view").strip() or "active_view",
        "timecode_ms": _positive_int(value.get("timecode_ms")) or default_timecode_ms,
    }
    for key in ("event_id", "turn_id", "source_event_id"):
        if value.get(key):
            ref[key] = str(value.get(key))
    return {key: val for key, val in ref.items() if val is not None and val != ""}


def _normalize_capture_document_refs(
    refs: Optional[Iterable[Any]],
    visual_context: Optional[Mapping[str, Any]] = None,
    *,
    default_timecode_ms: Optional[int] = None,
) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    seen: set[str] = set()
    candidates: List[Any] = list(refs or [])
    if visual_context:
        candidates.append(dict(visual_context))
    for item in candidates:
        ref = _normalize_capture_document_ref(item, default_timecode_ms=default_timecode_ms)
        if not ref:
            continue
        key = "|".join(
            str(ref.get(part) or "")
            for part in ("collection", "document_id", "filename", "page", "slide", "image_index", "anchor_id")
        )
        if key in seen:
            continue
        seen.add(key)
        normalized.append(ref)
    return normalized


# Deictic / "as you can see" trigger phrases (FR, configurable). Detection only
# fires when a turn ALSO carries at least one document view, so the cost in
# session is a single regex match. The list can be overridden via
# ``settings.capture_deictic_phrases`` (env / workspace tuning) without code change.
_CAPTURE_DEICTIC_PHRASES_FR: Tuple[str, ...] = (
    "cette page",
    "cette slide",
    "cette diapo",
    "cette diapositive",
    "cette image",
    "cette figure",
    "ce schema",
    "ce schéma",
    "ce tableau",
    "ce graphe",
    "ce graphique",
    "cette courbe",
    "ce diagramme",
    "cette photo",
    "cette capture",
    "ce document",
    "ce doc",
    "cette vue",
    "cette section",
    "ce passage",
    "cet ecran",
    "cet écran",
    "a l'ecran",
    "à l'écran",
    "comme on le voit",
    "comme on voit",
    "comme vous le voyez",
    "comme vous voyez",
    "vous voyez",
    "regardez",
    "ici",
    "là",
    # EN equivalents (transcript may be English).
    "this page",
    "this slide",
    "this image",
    "this figure",
    "this chart",
    "this graph",
    "this table",
    "this diagram",
    "this document",
    "as you can see",
    "as we can see",
    "you can see",
    "look here",
    "on screen",
)

_CAPTURE_DEICTIC_PATTERN: Optional[re.Pattern[str]] = None


def _capture_deictic_pattern() -> re.Pattern[str]:
    global _CAPTURE_DEICTIC_PATTERN
    if _CAPTURE_DEICTIC_PATTERN is not None:
        return _CAPTURE_DEICTIC_PATTERN
    phrases: Iterable[str] = _CAPTURE_DEICTIC_PHRASES_FR
    try:
        from app.core.config import settings as cfg

        override = getattr(cfg, "capture_deictic_phrases", None)
        if isinstance(override, (list, tuple)) and override:
            phrases = [str(item).strip() for item in override if str(item).strip()]
    except Exception:  # noqa: BLE001 - config override is best-effort.
        phrases = _CAPTURE_DEICTIC_PHRASES_FR
    ordered = sorted({p for p in phrases if p}, key=len, reverse=True)
    pattern = r"\b(?:" + "|".join(re.escape(p) for p in ordered) + r")\b"
    _CAPTURE_DEICTIC_PATTERN = re.compile(pattern, re.IGNORECASE)
    return _CAPTURE_DEICTIC_PATTERN


def _detect_capture_deictic_phrase(text: Optional[str]) -> Optional[str]:
    """Return the first deictic trigger phrase found in ``text`` (or None)."""
    if not text or not str(text).strip():
        return None
    match = _capture_deictic_pattern().search(str(text))
    return match.group(0).strip() if match else None


# Per-view index lifecycle exposed to the frontend chips. Ordered so the journal
# (referenced) never downgrades a doc the batch already queued/indexed.
CAPTURE_INDEX_STATUSES = ("not_indexed", "referenced", "queued", "indexed", "failed")
_CAPTURE_INDEX_RANK = {"not_indexed": 0, "referenced": 1, "queued": 2, "indexed": 3}


def _capture_document_keys(item: Mapping[str, Any]) -> List[str]:
    keys: List[str] = []
    for value in (item.get("document_id"), item.get("filename")):
        text = str(value or "").strip().lower()
        if text and text not in keys:
            keys.append(text)
    return keys


def _capture_view_key(ref: Mapping[str, Any]) -> str:
    doc = str(ref.get("document_id") or ref.get("filename") or "").strip().lower()
    return "|".join(
        [doc]
        + [str(ref.get(part) or "") for part in ("page", "slide", "image_index")]
    )


def _capture_view_kind(ref: Mapping[str, Any]) -> str:
    """Classify the referenced view (page|slide|image|document)."""
    if _positive_int(ref.get("page") or ref.get("page_number")):
        return "page"
    if _positive_int(ref.get("slide") or ref.get("slide_number")):
        return "slide"
    if _positive_int(ref.get("image_index")):
        return "image"
    return "document"


# End-of-capture sharing intent per document. ``excerpt`` (default) indexes only
# the referenced views; ``full`` adds the whole original; ``none`` keeps the doc
# citable in the report but out of the KB index.
CAPTURE_SHARE_LEVELS = ("full", "excerpt", "none")


def _normalize_share_level(value: Any, *, default: str = "full") -> str:
    text = str(value or "").strip().lower()
    return text if text in CAPTURE_SHARE_LEVELS else default


def _doc_share_level(doc: Mapping[str, Any]) -> str:
    """Read a doc's authoritative ``share_level`` with ``full_share`` retro-read.

    Product decision (2026-07): attachments are always shared IN FULL — the
    ``excerpt``/``none`` levels are no longer offered by the UI, so the default
    for unset docs is ``full``. Explicitly stored levels are still honoured for
    legacy sessions.
    """
    if doc.get("share_level"):
        return _normalize_share_level(doc.get("share_level"))
    if "full_share" in doc and doc.get("full_share") is False:
        return "excerpt"
    return "full"


def _capture_document_share_levels(session: ExpertCaptureSession) -> Dict[str, str]:
    """Map capture-document keys (document_id / filename, lowercased) to triage
    ``share_level`` from the session's capture-documents state."""
    state = (dict(session.metrics or {}).get("capture_documents") or {})
    levels: Dict[str, str] = {}
    for doc in state.get("documents") or []:
        if not isinstance(doc, dict):
            continue
        level = _doc_share_level(doc)
        for key in (doc.get("document_id"), doc.get("filename")):
            text = str(key or "").strip().lower()
            if text:
                levels[text] = level
    return levels


def _capture_document_ref_share_level(ref: Mapping[str, Any], levels: Mapping[str, str]) -> Optional[str]:
    for raw in (ref.get("document_id"), ref.get("filename")):
        text = str(raw or "").strip()
        if not text:
            continue
        for candidate in (text.lower(), Path(text).name.lower()):
            level = levels.get(candidate)
            if level:
                return level
    return None


def _apply_capture_share_levels(
    session: ExpertCaptureSession,
    *,
    levels_by_key: Mapping[str, str],
) -> bool:
    """Apply ``{doc_key: share_level}`` onto the capture documents state.

    Keeps the legacy ``full_share`` boolean in sync (``full`` => True). Returns
    True when at least one document entry changed.
    """
    wanted = {
        str(key).strip().lower(): _normalize_share_level(level)
        for key, level in (levels_by_key or {}).items()
        if str(key).strip()
    }
    if not wanted:
        return False
    metrics = dict(session.metrics or {})
    state = _capture_documents_state(session)
    documents = [dict(item) for item in (state.get("documents") or []) if isinstance(item, dict)]
    changed = False
    for entry in documents:
        match = next((wanted[key] for key in _capture_document_keys(entry) if key in wanted), None)
        if match is None:
            continue
        if _doc_share_level(entry) != match or entry.get("share_level") != match:
            entry["share_level"] = match
            entry["full_share"] = match == "full"
            changed = True
    if changed:
        state["documents"] = documents
        metrics["capture_documents"] = state
        session.metrics = metrics
        flag_modified(session, "metrics")
    return changed


def _mark_capture_document_index_status(
    session: ExpertCaptureSession,
    *,
    document_keys: Iterable[str],
    status: str,
    only_upgrade: bool = True,
) -> bool:
    """Set ``index_status`` on the matching capture document state entry.

    Returns True when a document row was updated. ``only_upgrade`` keeps the
    monotonic lifecycle (e.g. a deictic ``referenced`` never overwrites a doc the
    finalize batch already moved to ``queued``/``indexed``); ``failed`` is always
    applied so the UI surfaces errors.
    """
    wanted = {str(key).strip().lower() for key in document_keys if str(key).strip()}
    if not wanted:
        return False
    metrics = dict(session.metrics or {})
    state = _capture_documents_state(session)
    documents = [dict(item) for item in (state.get("documents") or []) if isinstance(item, dict)]
    changed = False
    for entry in documents:
        if not (set(_capture_document_keys(entry)) & wanted):
            continue
        current = str(entry.get("index_status") or "not_indexed")
        if only_upgrade and status != "failed":
            if _CAPTURE_INDEX_RANK.get(status, 0) <= _CAPTURE_INDEX_RANK.get(current, 0):
                continue
        if current != status:
            entry["index_status"] = status
            changed = True
    if changed:
        state["documents"] = documents
        metrics["capture_documents"] = state
        session.metrics = metrics
        flag_modified(session, "metrics")
    return changed


def _source_key(source: Dict[str, Any]) -> str:
    return "|".join(
        str(source.get(part) or "").strip().lower()
        for part in ("kind", "collection", "document_id", "filename", "page", "slide", "source")
    )


def _report_source_from_document_ref(ref: Dict[str, Any], rank: int) -> Dict[str, Any]:
    page = _positive_int(ref.get("page") or ref.get("page_number"))
    slide = _positive_int(ref.get("slide") or ref.get("slide_number"))
    label_parts = [str(ref.get("title") or ref.get("filename") or ref.get("document_id") or "Document").strip()]
    if slide:
        label_parts.append(f"slide {slide}")
    elif page:
        label_parts.append(f"page {page}")
    return {
        "rank": rank,
        "kind": CAPTURE_DOCUMENT_SOURCE_KIND,
        "document_id": ref.get("document_id"),
        "source_id": ref.get("source_id") or ref.get("document_id"),
        "source": " - ".join(part for part in label_parts if part),
        "title": ref.get("title") or ref.get("filename"),
        "filename": ref.get("filename"),
        "collection": ref.get("collection") or ref.get("collection_name"),
        "page": page,
        "page_number": page,
        "slide": slide,
        "image_index": ref.get("image_index"),
        "preview": ref.get("preview"),
        "turn_id": ref.get("turn_id"),
        "event_id": ref.get("event_id") or ref.get("source_event_id"),
        "timecode_ms": ref.get("timecode_ms"),
        "association_mode": ref.get("association_mode"),
    }


def _document_sources_from_facts(facts: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    sources: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for fact in facts or []:
        if not isinstance(fact, dict):
            continue
        for ref in fact.get("document_refs") or []:
            if not isinstance(ref, dict):
                continue
            source = _report_source_from_document_ref(ref, len(sources) + 1)
            key = _source_key(source)
            if key in seen:
                continue
            seen.add(key)
            sources.append(source)
    return sources


def _merge_report_sources(*groups: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    merged: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for group in groups:
        for source in group or []:
            if not isinstance(source, dict):
                continue
            item = dict(source)
            key = _source_key(item)
            if key in seen:
                continue
            seen.add(key)
            item["rank"] = len(merged) + 1
            merged.append(item)
    return merged


def _iter_plan_structure_sources(plan_structure: Any) -> Iterable[Dict[str, Any]]:
    if not isinstance(plan_structure, Mapping):
        return
    for source in plan_structure.get("sources") or []:
        if isinstance(source, dict):
            yield source
    for topic in plan_structure.get("topics") or []:
        if not isinstance(topic, Mapping):
            continue
        yield from _iter_plan_structure_sources(topic)
        for subtopic in topic.get("subtopics") or []:
            if isinstance(subtopic, Mapping):
                yield from _iter_plan_structure_sources(subtopic)


def _related_capture_documents_from_payload(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []
    for source in _iter_plan_structure_sources(payload.get("plan_structure") or {}):
        if source.get("kind") == CAPTURE_DOCUMENT_SOURCE_KIND:
            candidates.append(source)
    for fact in payload.get("captured_facts") or []:
        if isinstance(fact, dict):
            candidates.extend(_document_sources_from_facts([fact]))
    related: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for source in candidates:
        if not isinstance(source, dict):
            continue
        key = _source_key(source)
        if key in seen:
            continue
        seen.add(key)
        related.append(
            {
                key_name: source.get(key_name)
                for key_name in (
                    "kind",
                    "document_id",
                    "collection",
                    "filename",
                    "title",
                    "page",
                    "page_number",
                    "slide",
                    "image_index",
                    "preview",
                    "turn_id",
                    "event_id",
                    "timecode_ms",
                    "association_mode",
                )
                if source.get(key_name) is not None
            }
        )
    return related


def _capture_document_promotion_key(ref: Mapping[str, Any]) -> str:
    collection = str(ref.get("collection") or ref.get("collection_name") or "").strip().lower()
    filename = str(ref.get("filename") or "").strip().lower()
    document_id = str(ref.get("document_id") or ref.get("source_id") or "").strip().lower()
    return f"{collection}|{filename or document_id}"


def _rewrite_capture_document_sources_to_publication(value: Any, promotions: List[Dict[str, Any]]) -> Any:
    if not promotions:
        return value
    by_key = {
        str(item.get("source_key") or ""): item
        for item in promotions
        if item.get("source_key")
    }
    if isinstance(value, list):
        return [_rewrite_capture_document_sources_to_publication(item, promotions) for item in value]
    if not isinstance(value, dict):
        return value
    rewritten = {
        key: _rewrite_capture_document_sources_to_publication(item, promotions)
        for key, item in value.items()
    }
    if rewritten.get("kind") == CAPTURE_DOCUMENT_SOURCE_KIND:
        promotion = by_key.get(_capture_document_promotion_key(rewritten))
        if promotion:
            rewritten["published_from_collection"] = rewritten.get("collection") or rewritten.get("collection_name")
            rewritten["published_from_filename"] = rewritten.get("filename")
            rewritten["collection"] = promotion.get("collection")
            rewritten["collection_name"] = promotion.get("collection_name")
            rewritten["filename"] = promotion.get("filename")
            rewritten["document_id"] = promotion.get("document_id")
            rewritten["source_id"] = promotion.get("document_id")
            rewritten["publication_promoted"] = True
    return rewritten


def _promote_capture_documents_for_publication(
    db: DBSession,
    *,
    workspace: Any,
    destination_collection: Any,
    related_documents: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    if not related_documents:
        return []

    from app.services.knowledge_collections import (
        create_worker_job,
        get_collection_or_404,
        original_key,
        resolve_original_key,
        update_collection_status,
        upsert_collection_source,
    )
    from app.services.object_store import get_object_store

    store = get_object_store()
    existing_names = list(destination_collection.document_names or [])
    promoted_names: List[str] = []
    promotions: List[Dict[str, Any]] = []
    seen: set[str] = set()

    for ref in related_documents:
        if not isinstance(ref, dict):
            continue
        source_collection_ref = str(ref.get("collection") or ref.get("collection_name") or "").strip()
        source_filename = Path(str(ref.get("filename") or "")).name
        source_key = _capture_document_promotion_key(ref)
        if not source_collection_ref or not source_filename or source_key in seen:
            continue
        seen.add(source_key)
        try:
            source_collection = get_collection_or_404(
                db,
                workspace_id=workspace.id,
                collection_ref=source_collection_ref,
            )
        except Exception as exc:  # noqa: BLE001
            _logger.warning(
                "capture document promotion skipped: source collection missing",
                extra={
                    "workspace_id": workspace.id,
                    "collection": source_collection_ref,
                    "source_filename": source_filename,
                    "error": str(exc),
                },
            )
            continue

        original_source_key = resolve_original_key(source_collection, source_filename, store=store)
        if not store.exists(original_source_key):
            _logger.warning(
                "capture document promotion skipped: original missing",
                extra={
                    "workspace_id": workspace.id,
                    "collection": source_collection.slug,
                    "source_filename": source_filename,
                },
            )
            continue

        destination_name = source_filename
        if destination_name in existing_names and source_collection.slug != destination_collection.slug:
            prefix = re.sub(r"[^a-zA-Z0-9_.-]+", "-", source_collection.slug)[:48].strip("-")
            destination_name = f"{prefix}-{source_filename}" if prefix else source_filename
        content = store.read_bytes(original_source_key)
        store.write_bytes(original_key(destination_collection, destination_name), content)
        upsert_collection_source(
            db,
            collection=destination_collection,
            filename=destination_name,
            status="queued",
            origin="capture_publication_ref",
            size_bytes=len(content),
            source_metadata={
                "document_id": destination_name,
                "source": CAPTURE_DOCUMENT_SOURCE_KIND,
                "source_collection": source_collection.slug,
                "source_filename": source_filename,
                "capture_timecode_ms": ref.get("timecode_ms"),
                "association_mode": ref.get("association_mode"),
            },
        )
        if destination_name not in existing_names:
            existing_names.append(destination_name)
        promoted_names.append(destination_name)
        promotions.append(
            {
                "source_key": source_key,
                "kind": CAPTURE_DOCUMENT_SOURCE_KIND,
                "document_id": destination_name,
                "collection": destination_collection.slug,
                "collection_name": destination_collection.slug,
                "filename": destination_name,
                "title": ref.get("title") or source_filename,
                "source_collection": source_collection.slug,
                "source_filename": source_filename,
                "page": ref.get("page"),
                "page_number": ref.get("page_number"),
                "slide": ref.get("slide"),
                "image_index": ref.get("image_index"),
                "timecode_ms": ref.get("timecode_ms"),
                "association_mode": ref.get("association_mode"),
                "status": "queued",
            }
        )

    if promoted_names:
        update_collection_status(
            db,
            destination_collection.id,
            status="queued",
            document_names=existing_names,
            document_count=len(existing_names),
        )
        job = create_worker_job(
            db,
            workspace_id=workspace.id,
            collection_id=destination_collection.id,
            kind="document_ingest_index",
        )
        job.result = {
            "ingest_options": {
                "mode": "incremental",
                "document_names": promoted_names,
                "source": "capture_publication_documents",
            }
        }
        db.flush()
        for promotion in promotions:
            promotion["job_id"] = job.id

    return promotions


def capture_document_collection_slug(session_id: str) -> str:
    clean = re.sub(r"[^a-zA-Z0-9-]+", "-", str(session_id or "")).strip("-").lower()
    return f"{CAPTURE_DOCUMENT_COLLECTION_PREFIX}-{clean}"[:120]


def _capture_documents_state(session: ExpertCaptureSession) -> Dict[str, Any]:
    metrics = dict(session.metrics or {})
    state = dict(metrics.get("capture_documents") or {})
    state.setdefault("collection", capture_document_collection_slug(session.id))
    state.setdefault("documents", [])
    return state


def _upsert_capture_document_state(
    session: ExpertCaptureSession,
    *,
    collection: str,
    documents: Iterable[Dict[str, Any]],
    active_view: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    metrics = dict(session.metrics or {})
    state = _capture_documents_state(session)
    state["collection"] = collection
    existing = [
        dict(item)
        for item in (state.get("documents") or [])
        if isinstance(item, dict)
    ]
    by_key = {
        str(item.get("document_id") or item.get("filename") or "").lower(): item
        for item in existing
        if item.get("document_id") or item.get("filename")
    }
    for item in documents or []:
        if not isinstance(item, dict):
            continue
        entry = dict(item)
        key = str(entry.get("document_id") or entry.get("filename") or "").lower()
        if not key:
            continue
        previous = dict(by_key.get(key) or {})
        previous.update(entry)
        previous.setdefault("collection", collection)
        previous.setdefault("collection_name", collection)
        by_key[key] = previous
    state["documents"] = list(by_key.values())
    if active_view:
        state["active_view"] = active_view
    metrics["capture_documents"] = state
    session.metrics = metrics
    flag_modified(session, "metrics")
    return state


def register_capture_documents(
    db: DBSession,
    *,
    workspace_id: str,
    session_id: str,
    collection: str,
    documents: Iterable[Dict[str, Any]],
    actor_user_id: Optional[str] = None,
) -> Dict[str, Any]:
    session = get_session(db, workspace_id=workspace_id, session_id=session_id, materialize=False)
    now = datetime.utcnow().isoformat()
    normalized_docs: List[Dict[str, Any]] = []
    for item in documents or []:
        if not isinstance(item, dict):
            continue
        filename = str(item.get("filename") or "").strip()
        document_id = str(item.get("document_id") or "").strip()
        if not (filename or document_id):
            continue
        share_level = _doc_share_level(item) if (item.get("share_level") or item.get("full_share")) else "full"
        doc = {
            "document_id": document_id or None,
            "filename": filename or None,
            "title": item.get("title") or filename or document_id,
            "collection": collection,
            "collection_name": collection,
            "status": item.get("status") or "queued",
            "index_status": item.get("index_status") or "not_indexed",
            # ``share_level`` is authoritative; ``full_share`` kept for v0 back-compat.
            "share_level": share_level,
            "full_share": share_level == "full",
            "chunks_processed": item.get("chunks_processed") or 0,
            "job_id": item.get("job_id"),
            "uploaded_at": item.get("uploaded_at") or now,
            "uploaded_by_user_id": actor_user_id,
        }
        normalized_docs.append(
            {
                key: value
                for key, value in doc.items()
                if value is not None or key in ("full_share", "share_level")
            }
        )
    state = _upsert_capture_document_state(session, collection=collection, documents=normalized_docs)
    for doc in normalized_docs:
        _record_capture_event(
            db,
            session=session,
            event_type="capture_document_uploaded",
            source="capture_document",
            status=str(doc.get("status") or "queued"),
            created_by=actor_user_id,
            meta_data=doc,
        )
    db.commit()
    db.refresh(session)
    return {"session": serialize_session(session), "collection": collection, "documents": state.get("documents") or []}


def record_capture_document_view(
    db: DBSession,
    *,
    workspace_id: str,
    session_id: str,
    view: Dict[str, Any],
    actor_user_id: Optional[str] = None,
) -> Dict[str, Any]:
    session = get_session(db, workspace_id=workspace_id, session_id=session_id, materialize=False)
    ref = _normalize_capture_document_ref(
        view,
        default_timecode_ms=_capture_timecode_ms(session, datetime.utcnow()),
    )
    if not ref:
        raise ValueError("Document view must include at least a document id, filename or title")
    collection = str(ref.get("collection") or ref.get("collection_name") or capture_document_collection_slug(session.id))
    _upsert_capture_document_state(session, collection=collection, documents=[], active_view=ref)
    event = _record_capture_event(
        db,
        session=session,
        event_type="capture_document_viewed",
        source="capture_document",
        status="accepted",
        created_by=actor_user_id,
        meta_data=ref,
    )
    # A MANUAL mark ("Marquer dans le fil") is a real anchor, not just audit
    # metadata: journal it as ``capture_view_referenced`` too so it (a) survives
    # the feed re-hydration (build_capture_feed only projects view references),
    # (b) enters the finalize/provenance batch, and (c) yields an event id that
    # ``update_capture_view_anchor`` can actually patch (discard / rebind).
    anchor_event = None
    if str(ref.get("association_mode") or "").strip().lower() == "manual":
        anchor_payload = {
            "document_id": ref.get("document_id"),
            "collection": collection,
            "collection_name": collection,
            "filename": ref.get("filename"),
            "title": ref.get("title") or ref.get("filename") or ref.get("document_id"),
            "page": ref.get("page"),
            "slide": ref.get("slide"),
            "image_index": ref.get("image_index"),
            "timecode_ms": ref.get("timecode_ms"),
            "association_mode": "manual",
            "status": "confirmed",
            "confidence": 1.0,
            "view_kind": _capture_view_kind(ref),
        }
        anchor_payload = {key: value for key, value in anchor_payload.items() if value is not None}
        anchor_event = _record_capture_event(
            db,
            session=session,
            event_type="capture_view_referenced",
            speaker="expert",
            source="capture_document",
            status="accepted",
            confidence="1.0",
            parent_event_id=event.id,
            created_by=actor_user_id,
            meta_data=anchor_payload,
        )
    db.commit()
    db.refresh(session)
    return {
        "session": serialize_session(session),
        # The anchor event (when journaled) is what the frontend must key the
        # mark on — its id is patchable and feed-projected. Fall back to the
        # audit event for non-manual view logging.
        "event": serialize_event(anchor_event or event),
        "active_view": ref,
    }


def _journaled_view_counts(db: DBSession, *, session_id: str) -> Dict[str, int]:
    """Count distinct journaled views (dedup by doc+page/slide/image) per doc.

    Keyed by both ``document_id`` and ``filename`` (lowercased) so a doc whose
    state entry only carries one of the two still resolves its count.
    """
    rows = (
        db.query(ExpertCaptureEvent)
        .filter(
            ExpertCaptureEvent.session_id == session_id,
            ExpertCaptureEvent.event_type == "capture_view_referenced",
        )
        .all()
    )
    views_by_doc: Dict[str, set[str]] = {}
    for row in rows:
        meta = row.meta_data or {}
        # Discarded anchors are excluded from the finalize batch, so they must not
        # inflate ``referenced_views_count`` in the documents API / triage UI either.
        if str(meta.get("status") or "").strip().lower() == "discarded":
            continue
        view_key = "|".join(str(meta.get(part) or "") for part in ("page", "slide", "image_index"))
        for doc_key in _capture_document_keys(meta):
            views_by_doc.setdefault(doc_key, set()).add(view_key)
    return {doc_key: len(view_keys) for doc_key, view_keys in views_by_doc.items()}


def build_capture_documents_collection(
    db: DBSession,
    *,
    workspace_id: str,
    session: ExpertCaptureSession,
) -> Dict[str, Any]:
    """Build the capture session documents collection (GET shape).

    Merges the persisted ``capture_documents`` state with the live collection
    source ledger and decorates each doc with the shared contract fields:
    ``index_status`` (not_indexed|referenced|queued|indexed|failed),
    ``referenced_views_count`` (distinct journaled views) and ``full_share``.
    """
    state = _capture_documents_state(session)
    collection = state.get("collection") or capture_document_collection_slug(session.id)
    documents: List[Dict[str, Any]] = [
        dict(item) for item in (state.get("documents") or []) if isinstance(item, dict)
    ]
    from fastapi import HTTPException

    try:
        from app.services.knowledge_collections import (
            collection_source_rows,
            get_collection_or_404,
        )

        collection_row = get_collection_or_404(db, workspace_id=workspace_id, collection_ref=str(collection))
        state_by_name = {
            str(item.get("filename") or item.get("document_id") or "").lower(): dict(item)
            for item in documents
            if isinstance(item, dict) and (item.get("filename") or item.get("document_id"))
        }
        ledger_documents: List[Dict[str, Any]] = []
        for row in collection_source_rows(db, collection=collection_row):
            metadata = dict(row.source_metadata or {})
            document_id = metadata.get("document_id") or row.normalized_name or row.filename or row.id
            previous = state_by_name.get(str(row.filename or row.normalized_name or "").lower()) or {}
            ledger_documents.append(
                {
                    **previous,
                    "document_id": str(document_id),
                    "filename": row.filename,
                    "title": previous.get("title") or row.filename,
                    "collection": collection_row.slug,
                    "collection_name": collection_row.slug,
                    "status": row.status,
                    "chunks_processed": int(row.chunk_count or 0),
                    "mime_type": row.mime_type,
                    "source_kind": row.source_kind,
                    "source_id": row.id,
                }
            )
        if ledger_documents:
            documents = ledger_documents
    except HTTPException as exc:  # collection not created yet (store-only upload pending)
        if getattr(exc, "status_code", None) != 404:
            raise

    view_counts = _journaled_view_counts(db, session_id=session.id)
    for doc in documents:
        doc_keys = _capture_document_keys(doc)
        referenced = max((view_counts.get(key, 0) for key in doc_keys), default=0)
        doc["referenced_views_count"] = referenced
        share_level = _doc_share_level(doc)
        doc["share_level"] = share_level
        doc["full_share"] = share_level == "full"
        index_status = str(doc.get("index_status") or "not_indexed")
        if index_status not in CAPTURE_INDEX_STATUSES:
            index_status = "not_indexed"
        # A doc with journaled views is at least ``referenced`` even if the state
        # entry predates this field (older sessions / direct ledger rows).
        if referenced > 0 and _CAPTURE_INDEX_RANK.get(index_status, 0) < _CAPTURE_INDEX_RANK["referenced"]:
            index_status = "referenced"
        doc["index_status"] = index_status

    return {
        "collection": collection,
        "collection_name": collection,
        "documents": documents,
        "active_view": state.get("active_view"),
    }


def set_capture_documents_share_level(
    db: DBSession,
    *,
    workspace_id: str,
    session_id: str,
    items: Iterable[Mapping[str, Any]],
    actor_user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Set per-document ``share_level`` (end-of-capture triage).

    ``items`` is a list of ``{document_id, share_level}``: each listed doc is
    updated, docs not listed keep their existing level (default ``excerpt``). No
    ingestion happens here — the background finalize batch reads ``share_level``.
    Returns the updated documents collection (same shape as the GET endpoint).
    """
    session = get_session(db, workspace_id=workspace_id, session_id=session_id, materialize=False)
    levels_by_key: Dict[str, str] = {}
    for item in items or []:
        if not isinstance(item, Mapping):
            continue
        key = str(item.get("document_id") or item.get("filename") or "").strip().lower()
        if not key:
            continue
        levels_by_key[key] = _normalize_share_level(item.get("share_level"))
    if _apply_capture_share_levels(session, levels_by_key=levels_by_key):
        db.commit()
        db.refresh(session)
    return build_capture_documents_collection(db, workspace_id=workspace_id, session=session)


def set_capture_documents_full_share(
    db: DBSession,
    *,
    workspace_id: str,
    session_id: str,
    document_ids: Iterable[str],
    actor_user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """v0 alias over ``share_level`` (``True``->``full`` / ``False``->``excerpt``).

    The request body is the complete selection: listed docs become ``full``, the
    rest ``excerpt``. No ingestion happens here — the background finalize batch
    reads the resulting ``share_level``. Returns the updated documents collection.
    """
    session = get_session(db, workspace_id=workspace_id, session_id=session_id, materialize=False)
    wanted = {str(value).strip().lower() for value in (document_ids or []) if str(value).strip()}
    state = _capture_documents_state(session)
    documents = [dict(item) for item in (state.get("documents") or []) if isinstance(item, dict)]
    levels_by_key: Dict[str, str] = {}
    for entry in documents:
        for key in _capture_document_keys(entry):
            levels_by_key[key] = "full" if key in wanted else "excerpt"
    if _apply_capture_share_levels(session, levels_by_key=levels_by_key):
        db.commit()
        db.refresh(session)
    return build_capture_documents_collection(db, workspace_id=workspace_id, session=session)


def update_capture_view_anchor(
    db: DBSession,
    *,
    workspace_id: str,
    session_id: str,
    event_id: str,
    action: str,
    document_id: Optional[str] = None,
    collection: Optional[str] = None,
    filename: Optional[str] = None,
    title: Optional[str] = None,
    page: Optional[int] = None,
    slide: Optional[int] = None,
    image_index: Optional[int] = None,
    actor_user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Correct a journaled anchor (``capture_view_referenced``).

    ``confirm`` => status=confirmed/confidence=1.0; ``discard`` => status=discarded
    (kept out of the finalize batch); ``rebind`` => re-target the doc/view fields
    then status=confirmed/confidence=1.0. Returns the updated view ref dict.
    """
    get_session(db, workspace_id=workspace_id, session_id=session_id, materialize=False)
    event = (
        db.query(ExpertCaptureEvent)
        .filter(
            ExpertCaptureEvent.workspace_id == workspace_id,
            ExpertCaptureEvent.session_id == session_id,
            ExpertCaptureEvent.id == event_id,
            ExpertCaptureEvent.event_type == "capture_view_referenced",
        )
        .first()
    )
    if not event:
        raise ValueError("Capture view reference not found")
    meta = dict(event.meta_data or {})
    if action == "confirm":
        meta["status"] = "confirmed"
        meta["confidence"] = 1.0
        event.confidence = "1.0"
    elif action == "discard":
        meta["status"] = "discarded"
    elif action == "rebind":
        if document_id is not None:
            meta["document_id"] = document_id
        if collection is not None:
            meta["collection"] = collection
            meta["collection_name"] = collection
        if filename is not None:
            meta["filename"] = filename
        if title is not None:
            meta["title"] = title
        # Re-target the view locator atomically: a rebind picks one concrete view,
        # so a field omitted by the correction must be cleared rather than left
        # carrying the previous binding's page/slide/image_index.
        for key, value in (("page", page), ("slide", slide), ("image_index", image_index)):
            if value is not None:
                meta[key] = value
            else:
                meta.pop(key, None)
        meta["view_kind"] = _capture_view_kind(meta)
        meta["status"] = "confirmed"
        meta["confidence"] = 1.0
        event.confidence = "1.0"
    else:
        raise ValueError(f"Unsupported view anchor action: {action}")
    event.meta_data = meta
    flag_modified(event, "meta_data")
    db.commit()
    db.refresh(event)
    return dict(event.meta_data or {})


_CAPTURE_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff"}
_CAPTURE_OFFICE_EXTENSIONS = {".pptx", ".ppt", ".doc", ".docx", ".odp", ".odt", ".ods", ".xlsx", ".xls"}


def _set_capture_finalize_state(session: ExpertCaptureSession, finalize_state: Dict[str, Any]) -> None:
    metrics = dict(session.metrics or {})
    state = _capture_documents_state(session)
    state["finalize_index"] = finalize_state
    metrics["capture_documents"] = state
    session.metrics = metrics
    flag_modified(session, "metrics")


def _extract_single_pdf_page(pdf_bytes: bytes, *, page: int, out_path: Path) -> bool:
    """Write a single-page PDF (1-based ``page``) to ``out_path``. Returns success."""
    try:
        import io

        from PyPDF2 import PdfReader, PdfWriter

        reader = PdfReader(io.BytesIO(pdf_bytes))
        total = len(reader.pages)
        if total <= 0:
            return False
        index = max(0, min(int(page) - 1, total - 1))
        writer = PdfWriter()
        writer.add_page(reader.pages[index])
        with open(out_path, "wb") as handle:
            writer.write(handle)
        return True
    except Exception as exc:  # noqa: BLE001 - extraction failures degrade to whole-doc.
        _logger.warning("capture_view_pdf_page_extract_failed: %s", exc)
        return False


def _extract_capture_view_file(
    original: bytes,
    filename: str,
    *,
    page: Optional[int],
    slide: Optional[int],
    image_index: Optional[int],
    tmp_dir: Path,
) -> Optional[str]:
    """Materialize the referenced VIEW from the original document to a temp file.

    PDF page / pptx slide (office->pdf then page) / image. Falls back to the
    whole document when the view cannot be isolated. Returns the temp path.
    """
    name = Path(filename or "document").name
    ext = Path(name).suffix.lower()
    stem = Path(name).stem or "document"
    target_page = _positive_int(page) or _positive_int(slide)

    if ext in _CAPTURE_IMAGE_EXTENSIONS:
        out = tmp_dir / name
        out.write_bytes(original)
        return str(out)

    if ext == ".pdf":
        if target_page:
            out = tmp_dir / f"{stem}-p{target_page}.pdf"
            if _extract_single_pdf_page(original, page=target_page, out_path=out):
                return str(out)
        out = tmp_dir / name
        out.write_bytes(original)
        return str(out)

    if ext in _CAPTURE_OFFICE_EXTENSIONS:
        try:
            from app.api.v1.endpoints.documents import _office_preview_pdf_bytes

            pdf_bytes = _office_preview_pdf_bytes(original, name)
        except Exception as exc:  # noqa: BLE001 - keep the original if conversion fails.
            _logger.warning("capture_view_office_convert_failed: %s", exc)
            out = tmp_dir / name
            out.write_bytes(original)
            return str(out)
        if target_page:
            out = tmp_dir / f"{stem}-slide{target_page}.pdf"
            if _extract_single_pdf_page(pdf_bytes, page=target_page, out_path=out):
                return str(out)
        out = tmp_dir / f"{stem}.pdf"
        out.write_bytes(pdf_bytes)
        return str(out)

    out = tmp_dir / name
    out.write_bytes(original)
    return str(out)


async def _run_capture_finalize_index_async(
    db_factory,
    *,
    workspace_id: str,
    session_id: str,
) -> Dict[str, Any]:
    """Background batch: index the journaled views + the full-share docs.

    Decoupled from the report return (the report cites sources from the journaled
    refs directly). Idempotent: views/full docs already indexed are skipped, and a
    ``running`` guard prevents concurrent double-runs. Per-doc ``index_status``
    transitions queued -> indexed/failed so GET documents reflects progress.
    """
    import shutil

    from app.core.settings_manager import get_resolved_settings
    from app.models.workspace import Workspace
    from app.services.knowledge_collections import get_collection_or_404, resolve_original_key
    from app.services.object_store import get_object_store
    from app.services.rag.document_service import DocumentService
    from app.services.rag.vector_store_config import resolve_vector_db_type

    db = db_factory()
    tmp_dir = Path(tempfile.mkdtemp(prefix="agentium-capture-view-"))
    try:
        try:
            session = get_session(db, workspace_id=workspace_id, session_id=session_id, materialize=False)
        except ValueError:
            return {"status": "skipped", "reason": "session_not_found"}

        state = _capture_documents_state(session)
        finalize_state = dict(state.get("finalize_index") or {})
        if finalize_state.get("status") == "running":
            return {"status": "skipped", "reason": "already_running"}

        view_rows = (
            db.query(ExpertCaptureEvent)
            .filter(
                ExpertCaptureEvent.session_id == session_id,
                ExpertCaptureEvent.event_type == "capture_view_referenced",
            )
            .order_by(ExpertCaptureEvent.sequence.asc())
            .all()
        )
        views_by_key: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
        for row in view_rows:
            meta = dict(row.meta_data or {})
            # Discarded anchors (operator correction) never reach the index.
            if str(meta.get("status") or "").strip().lower() == "discarded":
                continue
            views_by_key.setdefault(_capture_view_key(meta), meta)

        documents = [dict(item) for item in (state.get("documents") or []) if isinstance(item, dict)]
        full_docs = [doc for doc in documents if _doc_share_level(doc) == "full"]
        if not views_by_key and not full_docs:
            finalize_state.update({"status": "done", "finished_at": datetime.utcnow().isoformat(), "indexed": 0})
            _set_capture_finalize_state(session, finalize_state)
            db.commit()
            return {"status": "noop"}

        collection_slug = state.get("collection") or capture_document_collection_slug(session_id)
        try:
            collection_row = get_collection_or_404(db, workspace_id=workspace_id, collection_ref=str(collection_slug))
        except Exception:  # noqa: BLE001 - nothing was ever stored.
            return {"status": "skipped", "reason": "collection_missing"}

        workspace = db.query(Workspace).filter(Workspace.id == workspace_id).first()
        if not workspace:
            return {"status": "skipped", "reason": "workspace_missing"}

        already_views = set(finalize_state.get("indexed_view_keys") or [])
        already_full = set(finalize_state.get("indexed_full_docs") or [])
        finalize_state.update(
            {
                "status": "running",
                "started_at": datetime.utcnow().isoformat(),
                "indexed_view_keys": sorted(already_views),
                "indexed_full_docs": sorted(already_full),
            }
        )
        _set_capture_finalize_state(session, finalize_state)
        db.commit()

        app_settings = get_resolved_settings(workspace_id=workspace_id)
        doc_service = DocumentService(
            collection_name=collection_row.slug,
            vector_db_type=resolve_vector_db_type(app_settings),
            workspace_slug=workspace.slug,
        )
        store = get_object_store()

        def _read_original(filename: str) -> Optional[bytes]:
            if not filename:
                return None
            try:
                key = resolve_original_key(collection_row, Path(str(filename)).name, store=store)
                if not store.exists(key):
                    return None
                return store.read_bytes(key)
            except Exception as exc:  # noqa: BLE001
                _logger.warning("capture_view_original_read_failed: %s", exc)
                return None

        indexed_count = 0
        for doc in documents:
            doc_keys = set(_capture_document_keys(doc))
            if not doc_keys:
                continue
            share_level = _doc_share_level(doc)
            # ``none`` keeps the doc citable in the report but out of the KB index.
            if share_level == "none":
                continue
            doc_views = [
                meta
                for key, meta in views_by_key.items()
                if (set(_capture_document_keys(meta)) & doc_keys) and key not in already_views
            ]
            is_full = share_level == "full" and not (doc_keys & already_full)
            if not doc_views and not is_full:
                continue

            _mark_capture_document_index_status(session, document_keys=doc_keys, status="queued", only_upgrade=False)
            db.commit()

            filename = doc.get("filename") or next((meta.get("filename") for meta in doc_views if meta.get("filename")), None)
            original = _read_original(str(filename or ""))
            doc_failed = False

            if original is None:
                doc_failed = True
            else:
                for meta in doc_views:
                    view_key = _capture_view_key(meta)
                    try:
                        view_path = _extract_capture_view_file(
                            original,
                            str(filename or meta.get("filename") or "document"),
                            page=meta.get("page") or meta.get("page_number"),
                            slide=meta.get("slide"),
                            image_index=meta.get("image_index"),
                            tmp_dir=tmp_dir,
                        )
                        if not view_path:
                            doc_failed = True
                            continue
                        document_metadata = {
                            key: value
                            for key, value in {
                                "capture_view": True,
                                "capture_session_id": session_id,
                                "document_id": meta.get("document_id") or doc.get("document_id"),
                                "source_filename": filename,
                                "page": meta.get("page") or meta.get("page_number"),
                                "slide": meta.get("slide"),
                                "image_index": meta.get("image_index"),
                                "turn_id": meta.get("turn_id"),
                                "timecode_ms": meta.get("timecode_ms"),
                                "statement": meta.get("statement"),
                                "origin": "capture_view_index",
                            }.items()
                            if value is not None
                        }
                        result = await doc_service.ingest_document(
                            view_path,
                            document_metadata=document_metadata,
                            collection_slug=collection_row.slug,
                            workspace_id=workspace_id,
                            collection_id=collection_row.id,
                        )
                        if result.get("status") == "error":
                            doc_failed = True
                        else:
                            already_views.add(view_key)
                            indexed_count += 1
                    except Exception as exc:  # noqa: BLE001 - one bad view must not abort the batch.
                        _logger.warning("capture_view_index_failed: %s", exc)
                        doc_failed = True

                if is_full:
                    try:
                        full_path = tmp_dir / Path(str(filename)).name
                        full_path.write_bytes(original)
                        result = await doc_service.ingest_document(
                            str(full_path),
                            document_metadata={
                                "capture_full_share": True,
                                "capture_session_id": session_id,
                                "document_id": doc.get("document_id"),
                                "source_filename": filename,
                                "origin": "capture_full_share_index",
                            },
                            collection_slug=collection_row.slug,
                            workspace_id=workspace_id,
                            collection_id=collection_row.id,
                        )
                        if result.get("status") == "error":
                            doc_failed = True
                        else:
                            already_full |= doc_keys
                            indexed_count += 1
                    except Exception as exc:  # noqa: BLE001
                        _logger.warning("capture_full_share_index_failed: %s", exc)
                        doc_failed = True

            # Re-load through the live session object before mutating state again.
            _mark_capture_document_index_status(
                session,
                document_keys=doc_keys,
                status="failed" if doc_failed else "indexed",
                only_upgrade=False,
            )
            finalize_state["indexed_view_keys"] = sorted(already_views)
            finalize_state["indexed_full_docs"] = sorted(already_full)
            _set_capture_finalize_state(session, finalize_state)
            db.commit()

        finalize_state.update(
            {
                "status": "done",
                "finished_at": datetime.utcnow().isoformat(),
                "indexed": indexed_count,
                "indexed_view_keys": sorted(already_views),
                "indexed_full_docs": sorted(already_full),
            }
        )
        _set_capture_finalize_state(session, finalize_state)
        db.commit()
        return {"status": "done", "indexed": indexed_count}
    except Exception as exc:  # noqa: BLE001 - never crash the worker thread.
        _logger.exception("capture_finalize_index_failed: %s", exc)
        try:
            db.rollback()
            session = get_session(db, workspace_id=workspace_id, session_id=session_id, materialize=False)
            finalize_state = dict(_capture_documents_state(session).get("finalize_index") or {})
            finalize_state.update({"status": "failed", "error": str(exc), "finished_at": datetime.utcnow().isoformat()})
            _set_capture_finalize_state(session, finalize_state)
            db.commit()
        except Exception:  # noqa: BLE001
            db.rollback()
        return {"status": "failed", "error": str(exc)}
    finally:
        db.close()
        shutil.rmtree(tmp_dir, ignore_errors=True)


def run_capture_finalize_index(db_factory, *, workspace_id: str, session_id: str) -> Dict[str, Any]:
    """Synchronous entrypoint (BackgroundTasks / worker thread) for the batch."""
    return asyncio.run(
        _run_capture_finalize_index_async(db_factory, workspace_id=workspace_id, session_id=session_id)
    )


def _fact_from_turn(turn: Dict[str, Any], evaluations: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    related = next((ev for ev in evaluations if ev.get("turn_id") == turn.get("id")), None)
    turn_kind = turn.get("turn_kind") or "answer"
    text = turn.get("text", "")
    document_refs = _normalize_capture_document_refs(
        turn.get("document_refs") or [],
        turn.get("visual_context") if isinstance(turn.get("visual_context"), Mapping) else None,
        default_timecode_ms=_positive_int(turn.get("timecode_ms")),
    )
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
        "input_modality": turn.get("input_modality") or "voice",
        "document_refs": document_refs,
        "visual_context": turn.get("visual_context"),
        "timecode_ms": turn.get("timecode_ms"),
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
                "title": _source_display_title(md),
                "source": md.get("source") or _source_display_filename(md) or md.get("document_id"),
                "preview": str(chunk)[:360],
                "metadata": md,
            }
        )
    return refs


def _section_key(topic_id: Optional[str], subtopic_id: Optional[str]) -> str:
    """Stable key for storing per-section FINAL synthesis on the plan."""
    return str(subtopic_id or topic_id or "session")


def _resolve_default_plan_section(plan: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    """First plan section (topic, subtopic) used when capture turns lack tags."""
    topics = [topic for topic in (plan.get("topics") or []) if isinstance(topic, dict)]
    if not topics:
        return None, None
    topic = topics[0]
    topic_id = topic.get("id")
    subtopics = [node for node in (topic.get("subtopics") or []) if isinstance(node, dict)]
    if subtopics:
        return topic_id, subtopics[0].get("id")
    return topic_id, None


def _resolve_session_active_section(session: ExpertCaptureSession) -> Tuple[Optional[str], Optional[str]]:
    """Active plan section from session metrics, or the default first section."""
    metrics = session.metrics or {}
    topic_id = metrics.get("active_topic_id")
    subtopic_id = metrics.get("active_subtopic_id")
    if topic_id or subtopic_id:
        return topic_id, subtopic_id
    return _resolve_default_plan_section(session.plan or {})


def _open_question_text(question: Dict[str, Any]) -> str:
    return str(
        question.get("follow_up") or question.get("text") or question.get("reason") or ""
    ).strip()


def _open_question_dedupe_key(question: Dict[str, Any]) -> str:
    text = _open_question_text(question).lower()
    if text:
        return text
    for field in ("gap_id", "id", "question_id"):
        value = _clean_optional_string(question.get(field))
        if value:
            return value.lower()
    return ""


def _is_generic_evaluation_open_question(question: Dict[str, Any]) -> bool:
    text = _open_question_text(question).lower()
    if text in _GENERIC_EVALUATION_OPEN_QUESTIONS:
        return True
    reason = str(question.get("reason") or question.get("verdict") or "").strip().lower()
    return reason == "contradiction_or_update" and (not text or text in _GENERIC_EVALUATION_OPEN_QUESTIONS)


def _proposal_open_question_from_raw(
    raw: Dict[str, Any],
    *,
    default_source: str,
) -> Dict[str, Any]:
    text = _open_question_text(raw)
    question = {
        "gap_id": raw.get("id") or raw.get("gap_id"),
        "reason": raw.get("source") or raw.get("reason") or default_source,
        "follow_up": text,
        "text": text,
        "topic_id": raw.get("topic_id"),
        "subtopic_id": raw.get("subtopic_id"),
        "priority": raw.get("priority"),
        "status": _normalize_proposal_open_question_status(raw.get("status")),
        "source": raw.get("source") or default_source,
    }
    # Criticality metadata must survive into the review payload (blocking
    # template required-fields, and the field key they map to).
    if raw.get("blocking"):
        question["blocking"] = True
    required_field_key = _clean_optional_string(raw.get("required_field_key"))
    if required_field_key:
        question["required_field_key"] = required_field_key
    return question


def _open_question_sort_key(question: Dict[str, Any]) -> Tuple[int, float]:
    """Blocking questions first, then priority descending (raw scale kept —
    coverage gaps use ~0-3, grounded questions 0..1). Stable for ties."""
    try:
        priority = float(question.get("priority"))
    except (TypeError, ValueError):
        priority = 0.0
    return (0 if question.get("blocking") else 1, -priority)


def _build_proposal_open_questions(
    session: ExpertCaptureSession,
    plan: Dict[str, Any],
    evaluations: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Unified proposal open questions: live oracle (capture) + FINAL grounded
    (section synthesis), deduped. Generic evaluation placeholders are dropped
    whenever grounded/live questions exist."""
    merged: List[Dict[str, Any]] = []
    seen: set[str] = set()

    def _append(raw: Dict[str, Any], *, default_source: str) -> None:
        if not isinstance(raw, dict):
            return
        key = _open_question_dedupe_key(raw)
        if not key or key in seen:
            return
        seen.add(key)
        merged.append(_proposal_open_question_from_raw(raw, default_source=default_source))

    for question in (plan or {}).get("live_open_questions") or []:
        _append(question, default_source="oracle_live")

    stored = (plan or {}).get("section_synthesis") or {}
    if isinstance(stored, dict):
        for entry in stored.values():
            if not isinstance(entry, dict):
                continue
            for question in entry.get("open_questions") or []:
                _append(question, default_source="oracle_grounded")

    has_grounded = bool(merged)
    for evaluation in evaluations if evaluations is not None else (session.evaluations or []):
        if not isinstance(evaluation, dict) or evaluation.get("verdict") == "sufficient":
            continue
        candidate = {
            "gap_id": evaluation.get("gap_id"),
            "reason": evaluation.get("verdict"),
            "follow_up": evaluation.get("follow_up"),
            "text": evaluation.get("follow_up"),
            "topic_id": evaluation.get("topic_id"),
            "subtopic_id": evaluation.get("subtopic_id"),
            "status": "open",
        }
        if has_grounded and _is_generic_evaluation_open_question(candidate):
            continue
        _append(candidate, default_source="evaluation")

    return sorted(merged, key=_open_question_sort_key)


def merge_live_open_questions_into_plan(
    db: DBSession,
    *,
    workspace_id: str,
    session_id: str,
    questions: List[Dict[str, Any]],
) -> None:
    """Persist LIVE grounded questions on the plan so capture.finish reuses them."""
    if not questions:
        return
    session = get_session(db, workspace_id=workspace_id, session_id=session_id)
    plan = dict(session.plan or {})
    existing = [
        dict(question)
        for question in (plan.get("live_open_questions") or [])
        if isinstance(question, dict)
    ]
    seen = {_open_question_dedupe_key(question) for question in existing if _open_question_dedupe_key(question)}
    for raw in questions:
        if not isinstance(raw, dict):
            continue
        key = _open_question_dedupe_key(raw)
        if not key or key in seen:
            continue
        seen.add(key)
        existing.append(dict(raw))
    plan["live_open_questions"] = existing
    session.plan = plan
    flag_modified(session, "plan")
    db.commit()


def _header_match_key(header_fields: Mapping[str, Any]) -> Tuple[str, str, str]:
    reference = str(header_fields.get("reference") or "").strip().lower()
    customer = str(header_fields.get("customer") or "").strip().lower()
    site = str(header_fields.get("site_or_machine") or "").strip().lower()
    return reference, customer, site


def _find_previous_fse_proposal(
    db: DBSession,
    *,
    workspace_id: str,
    system_id: Optional[str],
    header_fields: Mapping[str, Any],
) -> Optional[KnowledgeUpdateProposal]:
    """Latest accepted/published proposal for same system + reference (or customer+site)."""
    reference, customer, site = _header_match_key(header_fields)
    if not reference and not (customer and site):
        return None
    query = (
        db.query(KnowledgeUpdateProposal)
        .join(
            ExpertCaptureSession,
            ExpertCaptureSession.id == KnowledgeUpdateProposal.session_id,
        )
        .filter(
            KnowledgeUpdateProposal.workspace_id == workspace_id,
            KnowledgeUpdateProposal.status.in_(("accepted", "published")),
        )
    )
    if system_id:
        query = query.filter(ExpertCaptureSession.system_id == system_id)
    rows = query.order_by(KnowledgeUpdateProposal.created_at.desc()).limit(40).all()
    fallback: Optional[KnowledgeUpdateProposal] = None
    for proposal in rows:
        session = proposal.session
        plan = (session.plan if session else None) or {}
        prior_header = plan.get("header_fields") if isinstance(plan.get("header_fields"), dict) else {}
        pub = (proposal.proposal or {}).get("publication") if isinstance(proposal.proposal, dict) else {}
        tracking = pub.get("tracking") if isinstance(pub, dict) and isinstance(pub.get("tracking"), dict) else {}
        prior_ref = str(
            prior_header.get("reference")
            or tracking.get("fse_reference")
            or ""
        ).strip().lower()
        prior_customer = str(
            prior_header.get("customer")
            or tracking.get("fse_customer")
            or ""
        ).strip().lower()
        prior_site = str(
            prior_header.get("site_or_machine")
            or tracking.get("fse_machine")
            or ""
        ).strip().lower()
        if reference and prior_ref and prior_ref == reference:
            return proposal
        if (
            not fallback
            and customer
            and site
            and prior_customer == customer
            and prior_site == site
        ):
            fallback = proposal
    return fallback


def _inject_previous_report_open_items(
    db: DBSession,
    *,
    workspace_id: str,
    system_id: Optional[str],
    plan: Dict[str, Any],
    header_fields: Mapping[str, Any],
) -> Dict[str, Any]:
    """Inject unresolved N-1 open questions into plan.live_open_questions."""
    from app.services.capture_templates import (
        previous_report_open_question_payload,
        unresolved_open_questions,
    )

    prior = _find_previous_fse_proposal(
        db,
        workspace_id=workspace_id,
        system_id=system_id,
        header_fields=header_fields,
    )
    if not prior:
        plan["previous_report_open_items"] = {"count": 0}
        return plan
    payload = prior.proposal if isinstance(prior.proposal, dict) else {}
    unresolved = unresolved_open_questions(payload.get("open_questions") or [])
    if not unresolved:
        plan["previous_report_open_items"] = {
            "count": 0,
            "source_proposal_id": prior.id,
            "source_session_id": prior.session_id,
        }
        return plan
    existing = [
        dict(question)
        for question in (plan.get("live_open_questions") or [])
        if isinstance(question, dict)
    ]
    seen = {_open_question_dedupe_key(question) for question in existing if _open_question_dedupe_key(question)}
    injected: List[Dict[str, Any]] = []
    for index, question in enumerate(unresolved, start=1):
        item = previous_report_open_question_payload(
            question,
            index=index,
            source_proposal_id=prior.id,
            source_session_id=prior.session_id,
        )
        key = _open_question_dedupe_key(item)
        if not key or key in seen:
            continue
        seen.add(key)
        existing.append(item)
        injected.append(item)
    plan["live_open_questions"] = existing
    plan["previous_report_open_items"] = {
        "count": len(injected),
        "source_proposal_id": prior.id,
        "source_session_id": prior.session_id,
    }
    return plan


def _backfill_turn_plan_tags(
    db: DBSession,
    *,
    workspace_id: str,
    session_id: str,
) -> ExpertCaptureSession:
    """Tag untagged expert turns with the active/default plan section so the FINAL
    per-section reformulation can map statements to the plan hierarchy."""
    session = get_session(db, workspace_id=workspace_id, session_id=session_id)
    plan = session.plan or {}
    topics = [topic for topic in (plan.get("topics") or []) if isinstance(topic, dict)]
    if not topics:
        return session

    default_topic_id, default_subtopic_id = _resolve_session_active_section(session)
    transcript = list(session.transcript or [])
    changed = False
    carry_topic_id = default_topic_id
    carry_subtopic_id = default_subtopic_id

    for index, turn in enumerate(transcript):
        if not isinstance(turn, dict) or turn.get("speaker") != "expert":
            continue
        text = str(turn.get("text") or turn.get("text_raw") or "").strip()
        if not text:
            continue
        topic_id = turn.get("topic_id")
        subtopic_id = turn.get("subtopic_id")
        if topic_id or subtopic_id:
            carry_topic_id = topic_id or carry_topic_id
            carry_subtopic_id = subtopic_id if subtopic_id is not None else carry_subtopic_id
            continue
        updated = dict(turn)
        updated["topic_id"] = carry_topic_id or default_topic_id
        updated["subtopic_id"] = carry_subtopic_id if carry_subtopic_id is not None else default_subtopic_id
        transcript[index] = updated
        changed = True
        carry_topic_id = updated.get("topic_id") or carry_topic_id
        carry_subtopic_id = updated.get("subtopic_id")

    if not changed:
        return session

    session.transcript = transcript
    flag_modified(session, "transcript")
    # These plan-section tags live only on the materialized turns (not the ledger);
    # clear the deferred flag so later readers use this tagged cache rather than
    # rebuilding a less-tagged transcript from events.
    _set_transcript_dirty(session, False)
    captured = list(session.captured_facts or [])
    for fact in captured:
        if fact.get("topic_id") or fact.get("subtopic_id"):
            continue
        turn_id = fact.get("turn_id")
        for turn in transcript:
            if turn.get("id") == turn_id:
                fact["topic_id"] = turn.get("topic_id")
                fact["subtopic_id"] = turn.get("subtopic_id")
                break
    session.captured_facts = captured
    flag_modified(session, "captured_facts")
    db.commit()
    db.refresh(session)
    return session


def _attach_section_synthesis(plan_structure: Dict[str, Any], plan: Dict[str, Any]) -> Dict[str, Any]:
    """Attach the stored per-section FINAL synthesis (text + KB sources + grounded
    open questions) onto the structured plan so the report UI can render section
    cards with chat-style sources."""
    stored = (plan or {}).get("section_synthesis") or {}
    if not isinstance(stored, dict) or not stored:
        return plan_structure

    def _apply(node: Dict[str, Any], entry: Any) -> None:
        if not isinstance(entry, dict):
            return
        if entry.get("synthesis"):
            node["synthesis"] = entry.get("synthesis")
        if entry.get("sources"):
            node["sources"] = _merge_report_sources(node.get("sources") or [], entry.get("sources") or [])
        if entry.get("open_questions"):
            node["open_questions"] = entry.get("open_questions")

    for topic in plan_structure.get("topics") or []:
        _apply(topic, stored.get(_section_key(topic.get("topic_id"), None)))
        for subtopic in topic.get("subtopics") or []:
            _apply(subtopic, stored.get(_section_key(topic.get("topic_id"), subtopic.get("subtopic_id"))))

    # No-plan resilience: when the FINAL pass ran without any plan topics (e.g.
    # the thematic structuring yielded nothing), the synthesis is stored under
    # the unscoped "session" key. Surface it as a single pseudo-section so the
    # report keeps the reformulated text, its KB sources and grounded questions
    # instead of silently falling back to the verbatim transcript.
    if not plan_structure.get("topics"):
        session_entry = stored.get("session")
        if isinstance(session_entry, dict) and str(session_entry.get("synthesis") or "").strip():
            unassigned = plan_structure.get("unassigned") or []
            plan_structure["topics"] = [
                {
                    "topic_id": "session",
                    "title": str(session_entry.get("section_label") or "").strip() or "Synthèse de la capture",
                    "prompt": None,
                    "facts": list(unassigned),
                    "subtopics": [],
                    "synthesis": session_entry.get("synthesis"),
                    "sources": session_entry.get("sources") or [],
                    "open_questions": session_entry.get("open_questions") or [],
                }
            ]
            plan_structure["unassigned"] = []
    return plan_structure


def _ensure_free_conversation_report_topic(
    session: ExpertCaptureSession,
    plan_structure: Dict[str, Any],
    captured_facts: List[Dict[str, Any]],
    open_questions: List[Dict[str, Any]],
) -> Dict[str, Any]:
    if not _is_free_conversation_session(session):
        return plan_structure
    if plan_structure.get("topics"):
        return plan_structure
    facts = list(plan_structure.get("unassigned") or captured_facts or [])
    if not facts:
        return plan_structure
    sources: List[Dict[str, Any]] = []
    seen_sources: set[str] = set()
    for fact in facts:
        if not isinstance(fact, dict):
            continue
        for ref in [*(fact.get("retrieval_refs") or []), *(_document_sources_from_facts([fact]) or [])]:
            if not isinstance(ref, dict):
                continue
            key = _source_key(ref) or str(ref.get("document_id") or ref.get("source") or ref.get("title") or ref)
            if key in seen_sources:
                continue
            seen_sources.add(key)
            sources.append(ref)
    plan_structure["topics"] = [
        {
            "topic_id": "session",
            "title": "Synthèse de la capture",
            "prompt": None,
            "facts": facts,
            "subtopics": [],
            "sources": sources,
            "open_questions": list(open_questions or []),
        }
    ]
    plan_structure["unassigned"] = []
    return plan_structure


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
                    "sources": _document_sources_from_facts(sub_facts),
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
                "sources": _document_sources_from_facts(topic_facts),
                "subtopics": subtopic_nodes,
            }
        )
    unassigned = [fact for fact in facts if id(fact) not in assigned]
    return {"topics": structured_topics, "unassigned": unassigned}


# "Hors plan" redundancy: an unassigned fact whose content words are (near-)fully
# contained in an assigned fact or a section synthesis is a duplicate leftover of
# the plan assignment, not extra knowledge — drop it from the report.
_UNASSIGNED_REDUNDANCY_MIN = 0.8
_REDUNDANCY_STOPWORDS = frozenset(
    {
        "les", "des", "une", "aux", "est", "sont", "pour", "avec", "dans", "sur",
        "par", "pas", "que", "qui", "quand", "comme", "mais", "aussi", "plus",
        "tres", "cette", "ces", "son", "ses", "leur", "leurs", "ete", "etre",
        "fait", "faire", "tout", "tous", "toute", "toutes", "nous", "vous",
        "ils", "elles", "elle", "donc", "alors", "puis", "sans", "sous", "chez",
        "the", "and", "with", "from", "that", "this", "have", "has",
    }
)


def _redundancy_tokens(text: str) -> set[str]:
    """Normalized content words: lowercase, accents stripped, punctuation out."""
    normalized = unicodedata.normalize("NFD", str(text or "").lower())
    normalized = "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")
    return {
        token
        for token in re.findall(r"[a-z0-9]+", normalized)
        if len(token) >= 3 and token not in _REDUNDANCY_STOPWORDS
    }


def _filter_redundant_unassigned_facts(plan_structure: Dict[str, Any]) -> Dict[str, Any]:
    """Drop "hors plan" facts already covered by assigned facts or section syntheses.

    Conservative lexical containment only (no LLM): an unassigned fact is dropped
    when ≥ ``_UNASSIGNED_REDUNDANCY_MIN`` of its content words appear in a single
    assigned fact or section synthesis. Dropped count is kept on the structure
    (``unassigned_dropped_redundant``) for observability.
    """
    unassigned = list(plan_structure.get("unassigned") or [])
    if not unassigned:
        return plan_structure

    reference_token_sets: List[set[str]] = []

    def _collect(node: Dict[str, Any]) -> None:
        for fact in node.get("facts") or []:
            if isinstance(fact, dict):
                tokens = _redundancy_tokens(fact.get("text") or fact.get("statement") or "")
                if tokens:
                    reference_token_sets.append(tokens)
        synthesis_tokens = _redundancy_tokens(node.get("synthesis") or "")
        if synthesis_tokens:
            reference_token_sets.append(synthesis_tokens)

    for topic in plan_structure.get("topics") or []:
        if not isinstance(topic, dict):
            continue
        _collect(topic)
        for subtopic in topic.get("subtopics") or []:
            if isinstance(subtopic, dict):
                _collect(subtopic)

    if not reference_token_sets:
        return plan_structure

    kept: List[Dict[str, Any]] = []
    dropped = 0
    for fact in unassigned:
        tokens = (
            _redundancy_tokens(fact.get("text") or fact.get("statement") or "")
            if isinstance(fact, dict)
            else set()
        )
        # Short facts (< 3 content words) are too noisy to judge — always kept.
        if len(tokens) >= 3 and any(
            len(tokens & reference) / len(tokens) >= _UNASSIGNED_REDUNDANCY_MIN
            for reference in reference_token_sets
        ):
            dropped += 1
            continue
        kept.append(fact)

    if dropped:
        plan_structure["unassigned"] = kept
        plan_structure["unassigned_dropped_redundant"] = dropped
        _logger.info(
            "capture report: dropped %d redundant hors-plan fact(s) (%d kept)",
            dropped,
            len(kept),
        )
    return plan_structure


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
        lines.append("## Questions ouvertes pour reprise")
        lines.append("_Points restés sans réponse à la publication ; à compléter par un expert._")
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
    header_fields: Optional[Dict[str, Any]] = None,
) -> ExpertCaptureSession:
    from app.services.capture_templates import (
        apply_intervention_type_to_template,
        apply_required_field_defaults,
        attach_template_to_plan,
        get_capture_template,
        intervention_type_id_from_header,
        normalize_header_fields,
        plan_seed_to_provided_text,
        required_field_gaps,
        template_id_from_system_settings,
    )

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
    resolved_system_id = system_id
    system_row: Optional[System] = None
    if resolved_system_id:
        system_row = (
            db.query(System)
            .filter(System.id == resolved_system_id, System.workspace_id == workspace_id)
            .first()
        )
    capture_template = get_capture_template(
        template_id_from_system_settings(system_row.settings if system_row else None)
    )
    normalized_header_fields = normalize_header_fields(header_fields)
    if capture_template:
        capture_template = apply_intervention_type_to_template(
            capture_template,
            header_fields=normalized_header_fields,
        )
        normalized_header_fields = apply_required_field_defaults(
            capture_template,
            normalized_header_fields,
        )
        normalized_header_fields["intervention_type"] = intervention_type_id_from_header(
            normalized_header_fields
        )
    effective_provided_plan_text = provided_plan_text
    normalized_plan_mode = (plan_mode or "ai_plan").strip().lower()
    if capture_template:
        # Constrained capture fork: force the template plan rails.
        normalized_plan_mode = "provided_plan"
        if not (effective_provided_plan_text or "").strip():
            effective_provided_plan_text = plan_seed_to_provided_text(capture_template)
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
            provided_seed=effective_provided_plan_text,
        )
        if normalized_plan_mode == "provided_plan":
            plan["mode"] = "provided_plan"
            plan = _apply_provided_plan_seed(plan, effective_provided_plan_text)
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
            provided_seed=effective_provided_plan_text,
        )
    plan["mode"] = normalized_plan_mode
    plan["knowledge_refs"] = knowledge_refs or []
    plan["voice_runtime"] = voice_runtime
    plan = _attach_plan_source_metadata(
        plan,
        kind=plan_source_kind or ("manual" if capture_template else None),
        filename=plan_source_filename,
        seed=effective_provided_plan_text,
        replaces_existing_plan=plan_source_replaces_existing_plan,
    )
    if unlimited_duration:
        plan["unlimited_duration"] = True
    if capture_template:
        plan = attach_template_to_plan(
            plan,
            capture_template,
            header_fields=normalized_header_fields,
        )
        gaps = [
            *required_field_gaps(capture_template, plan.get("header_fields")),
            *gaps,
        ]
        plan["oracle"] = {
            **(plan.get("oracle") or {}),
            "coverage_gaps": [
                *required_field_gaps(capture_template, plan.get("header_fields")),
                *list((plan.get("oracle") or {}).get("coverage_gaps") or []),
            ],
        }
        plan = _inject_previous_report_open_items(
            db,
            workspace_id=workspace_id,
            system_id=resolved_system_id,
            plan=plan,
            header_fields=plan.get("header_fields") or {},
        )

    capability = db.query(Capability).filter(Capability.slug == CAPABILITY_SLUG).first()
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
    if capture_template:
        session_metrics["capture_template_id"] = capture_template.get("id")
    session_title = title or (
        str(capture_template.get("label") or "").strip() if capture_template else ""
    ) or "Expert Knowledge Capture"
    session = ExpertCaptureSession(
        id=str(uuid.uuid4()),
        workspace_id=workspace_id,
        capability_id=capability.id if capability else None,
        context_id=resolved_context_id,
        system_id=resolved_system_id,
        created_by_user_id=created_by_user_id,
        title=session_title,
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
        default_topic_id, default_subtopic_id = _resolve_default_plan_section(plan)
        if default_topic_id:
            metrics = dict(session.metrics or {})
            metrics.setdefault("active_topic_id", default_topic_id)
            if default_subtopic_id:
                metrics.setdefault("active_subtopic_id", default_subtopic_id)
            session.metrics = metrics
            flag_modified(session, "metrics")
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
    topic_id: Optional[str] = None,
    subtopic_id: Optional[str] = None,
    topic_path: Optional[str] = None,
    compute_evaluation: bool = True,
    persist_transcript: bool = True,
    voice_stream_metrics: Optional[Dict[str, Any]] = None,
    input_modality: Optional[str] = None,
    document_refs: Optional[List[Dict[str, Any]]] = None,
    visual_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    turn_started_at = time.perf_counter()
    # The turn is recorded on the append-only event ledger regardless; ``materialize``
    # is skipped here so the hot per-turn path never pays the ledger rebuild.
    session = get_session(db, workspace_id=workspace_id, session_id=session_id, materialize=False)
    if session.status == "planned" and _topic_plan_requires_approval(session.plan or {}):
        raise ValueError("Capture plan must be approved before the session starts")
    if session.status == "planned":
        session.status = "active"
        session.started_at = session.started_at or datetime.utcnow()

    if speaker == "expert" and not (topic_id or subtopic_id):
        active_topic_id, active_subtopic_id = _resolve_session_active_section(session)
        topic_id = topic_id or active_topic_id
        subtopic_id = subtopic_id if subtopic_id is not None else active_subtopic_id

    normalized_modality = _normalize_input_modality(input_modality, audio_ref=audio_ref)
    turn_created_at = datetime.utcnow()
    timecode_ms = _capture_timecode_ms(session, turn_created_at)
    normalized_document_refs = _normalize_capture_document_refs(
        document_refs or [],
        visual_context if isinstance(visual_context, Mapping) else None,
        default_timecode_ms=timecode_ms,
    )
    normalized_visual_context = (
        _normalize_capture_document_ref(visual_context, default_timecode_ms=timecode_ms)
        if isinstance(visual_context, Mapping)
        else None
    )
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
            meta_data={
                "client_turn_id": client_turn_id,
                "turn_kind": turn_kind,
                "input_modality": normalized_modality,
                "timecode_ms": timecode_ms,
                **question_meta,
            },
        )
    if speaker == "expert" and normalized_modality == "voice":
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
            meta_data={
                "client_turn_id": client_turn_id,
                "turn_kind": turn_kind,
                "input_modality": normalized_modality,
                "document_refs": normalized_document_refs,
                "visual_context": normalized_visual_context,
                "timecode_ms": timecode_ms,
                **question_meta,
            },
        )

    turn = {
        "id": client_turn_id or str(uuid.uuid4()),
        "speaker": speaker,
        "text": text,
        "question_id": question_id,
        # Explicit section tags (from section.select) win over question-derived
        # tags so free-flow capture turns still map to the active plan node.
        "topic_id": topic_id or question_meta.get("topic_id"),
        "subtopic_id": subtopic_id or question_meta.get("subtopic_id"),
        "topic_path": topic_path or question_meta.get("topic_path"),
        "audio_ref": audio_ref,
        "client_turn_id": client_turn_id,
        "retrieval_event_id": retrieval_event_id,
        "retrieval_refs": retrieval_refs,
        "interruption_of_event_id": interruption_of_event_id,
        "turn_kind": turn_kind,
        "input_modality": normalized_modality,
        "document_refs": normalized_document_refs,
        "visual_context": normalized_visual_context,
        "timecode_ms": timecode_ms,
        "text_partials": text_partials or [],
        "latency_ms": latency_ms or {},
        "created_at": turn_created_at.isoformat(),
    }
    turn_source = "expert_voice" if normalized_modality == "voice" else "expert_text"
    event = _record_capture_event(
        db,
        session=session,
        event_type="expert_turn_finalized" if speaker == "expert" else "transcript_turn_recorded",
        speaker=speaker,
        question_id=question_id,
        audio_ref=audio_ref,
        text_raw=text,
        source=turn_source if speaker == "expert" else "operator_edit",
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
            "input_modality": normalized_modality,
            "document_refs": normalized_document_refs,
            "visual_context": normalized_visual_context,
            "timecode_ms": timecode_ms,
            "text_partials": text_partials or [],
            "latency_ms": latency_ms or {},
            **question_meta,
            # Persist the RESOLVED section tags (explicit section.select wins over
            # question-derived tags) so the ledger alone can rebuild the turn.
            "topic_id": turn["topic_id"],
            "subtopic_id": turn["subtopic_id"],
            "topic_path": turn["topic_path"],
        },
    )
    turn["source_event_id"] = event.id
    turn["text_raw"] = text
    turn["text_status"] = event.status

    # Deictic mention journaling (voice + text): when the expert references the
    # shown view(s) ("comme on le voit sur cette page"...) AND the turn carries
    # document view(s), journal an append-only ``capture_view_referenced`` event
    # per distinct view. This is the ONLY in-session work: a regex + a ledger
    # write. No conversion, no embedding, no worker dispatch (deferred to the
    # background finalize batch). Referenced docs move to ``index_status`` =
    # ``referenced`` so the chips reflect it live.
    view_references: List[Dict[str, Any]] = []
    if speaker == "expert" and normalized_document_refs:
        trigger_phrase = _detect_capture_deictic_phrase(text)
        if trigger_phrase:
            # Deterministic anchor confidence (D2 phase 1): a single distinct view
            # in the turn is unambiguous (confirmed); >=2 distinct views make the
            # deictic target ambiguous (lowconf, below the 0.7 threshold).
            distinct_view_keys = {_capture_view_key(ref) for ref in normalized_document_refs}
            if len(distinct_view_keys) <= 1:
                anchor_status, anchor_confidence = "confirmed", 1.0
            else:
                anchor_status, anchor_confidence = "lowconf", 0.5
            seen_view_keys: set[str] = set()
            for ref in normalized_document_refs:
                view_key = _capture_view_key(ref)
                if view_key in seen_view_keys:
                    continue
                seen_view_keys.add(view_key)
                collection_slug = (
                    ref.get("collection")
                    or ref.get("collection_name")
                    or capture_document_collection_slug(session.id)
                )
                payload = {
                    "document_id": ref.get("document_id"),
                    "collection": collection_slug,
                    "collection_name": collection_slug,
                    "filename": ref.get("filename"),
                    "title": ref.get("title") or ref.get("filename") or ref.get("document_id"),
                    "page": ref.get("page") or ref.get("page_number"),
                    "slide": ref.get("slide"),
                    "image_index": ref.get("image_index"),
                    "timecode_ms": ref.get("timecode_ms") or timecode_ms,
                    "turn_id": turn["id"],
                    "statement": text,
                    "trigger_phrase": trigger_phrase,
                    "association_mode": ref.get("association_mode") or "active_view",
                    "status": anchor_status,
                    "confidence": anchor_confidence,
                    "view_kind": _capture_view_kind(ref),
                }
                payload = {key: value for key, value in payload.items() if value is not None}
                view_event = _record_capture_event(
                    db,
                    session=session,
                    event_type="capture_view_referenced",
                    speaker="expert",
                    question_id=question_id,
                    source="capture_document",
                    status="accepted",
                    confidence=str(anchor_confidence),
                    parent_event_id=event.id,
                    created_by=actor_user_id,
                    meta_data=payload,
                )
                # Surface the ledger position (sequence) inside the payload so the
                # realtime push and the report citations share one shape.
                enriched = {**payload, "event_id": view_event.id, "event_sequence": view_event.sequence}
                view_event.meta_data = enriched
                flag_modified(view_event, "meta_data")
                _mark_capture_document_index_status(
                    session,
                    document_keys=_capture_document_keys(ref),
                    status="referenced",
                )
                view_references.append(enriched)

    if persist_transcript:
        # Keep the materialized cache in sync. When prior silent turns deferred the
        # rewrite, catch up from the ledger (the new turn's event is already
        # flushed) instead of appending onto a stale list.
        if _transcript_is_dirty(session):
            session.transcript = _transcript_from_events(_list_turn_events(db, session.id))
            flag_modified(session, "transcript")
            _set_transcript_dirty(session, False)
        else:
            transcript = list(session.transcript or [])
            transcript.append(turn)
            session.transcript = transcript
    else:
        # Silent capture path: do NOT rewrite the growing transcript column every
        # turn. The event ledger is the source of truth; readers rematerialize it.
        _set_transcript_dirty(session, True)

    evaluation: Optional[Dict[str, Any]] = None
    relance: Dict[str, Optional[str]] = {"kind": None, "text": None}
    suggestions: List[Dict[str, str]] = []
    open_questions: List[Dict[str, Any]] = []
    next_prompt: Optional[str] = None
    next_question: Optional[Dict[str, Any]] = None
    system_prompt_event_id: Optional[str] = None
    if speaker == "expert":
        # Silent capture path (compute_evaluation=False) skips the per-turn LLM
        # evaluate/relance work — the realtime gateway discards that return and the
        # finalize rebuilds the proposal from the event ledger. captured_facts and
        # the metrics recompute are kept because the post-finalize re-synthesis
        # (answer_proposal_open_question) reads live ``session.captured_facts``.
        if compute_evaluation:
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
            captured.append(_fact_from_turn(turn, session.evaluations or []))
            session.captured_facts = captured

        if persist_transcript:
            session.metrics = _metrics_for_session(session)
        else:
            # Silent capture path: derive the per-turn counters cheaply instead of
            # the O(N) ``_metrics_for_session`` recompute (which would read the
            # deferred transcript). The full metrics are refreshed on the next read
            # (``serialize_session``) and at finalize.
            metrics = dict(session.metrics or {})
            metrics["turns"] = int(metrics.get("turns") or 0) + 1
            metrics["captured_facts"] = len(session.captured_facts or [])
            session.metrics = metrics
            flag_modified(session, "metrics")
        resolve_hints_from_expert_text(
            db,
            workspace_id=workspace_id,
            session_id=session_id,
            text=text,
            actor_user_id=actor_user_id,
        )

        if compute_evaluation:
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

    if voice_stream_metrics is not None:
        # Fold the per-turn voice_stream metrics into this single write instead of
        # a second get_session + commit (previously _merge_capture_metrics).
        metrics = dict(session.metrics or {})
        voice_metrics = dict(metrics.get("voice_stream") or {})
        recorded_latency = dict(voice_stream_metrics)
        recorded_latency.setdefault(
            "turn_end_to_prompt", int((time.perf_counter() - turn_started_at) * 1000)
        )
        voice_metrics["last_latency_ms"] = recorded_latency
        voice_metrics["turns"] = int(voice_metrics.get("turns") or 0) + 1
        voice_metrics["runtime_provider"] = recorded_latency.get("runtime_provider")
        voice_metrics["runtime_requested_provider"] = recorded_latency.get("runtime_requested_provider")
        voice_metrics["fallback_used"] = recorded_latency.get("fallback_used")
        metrics["voice_stream"] = voice_metrics
        session.metrics = metrics

    db.commit()
    # The silent capture caller discards the return; skip the O(N) ``db.refresh`` +
    # ``serialize_session`` (which would re-read the whole transcript every turn).
    serialized_session = None
    if persist_transcript:
        db.refresh(session)
        serialized_session = serialize_session(session)
    return {
        "session": serialized_session,
        "turn": turn,
        "evaluation": evaluation,
        "relance": relance,
        "suggestions": suggestions,
        "open_questions": open_questions,
        "next_prompt": next_prompt,
        "next_question_id": (next_question or {}).get("id") if speaker == "expert" else None,
        "system_prompt_event_id": system_prompt_event_id,
        "view_references": view_references,
    }


def create_update_proposal(
    db: DBSession,
    *,
    workspace_id: str,
    session_id: str,
    complete_session: bool = True,
    created_by_user_id: Optional[str] = None,
    plan_snapshot: Optional[Dict[str, Any]] = None,
) -> KnowledgeUpdateProposal:
    session = get_session(db, workspace_id=workspace_id, session_id=session_id, materialize=False)
    db.refresh(session)
    events = list_capture_events(db, workspace_id=workspace_id, session_id=session_id)
    # Rebuild + persist the transcript from the ledger (no-op when already in sync)
    # so the proposal payload, closure sheet and segments see every committed turn.
    _persist_materialized_transcript(db, session, events=events)
    payload = structure_capture_payload(
        session,
        events,
        plan_snapshot=plan_snapshot or dict(session.plan or {}),
    )
    proposal = _latest_pending_proposal_for_session(db, workspace_id=workspace_id, session_id=session_id)
    previous_publication = (
        dict((proposal.proposal or {}).get("publication") or {})
        if proposal and isinstance((proposal.proposal or {}).get("publication"), dict)
        else {}
    )
    ctx = _load_context(db, workspace_id, session.context_id)
    from app.models.workspace import Workspace as _Workspace

    proposal_workspace = db.query(_Workspace).filter(_Workspace.id == workspace_id).first()
    payload = _apply_publication_defaults(
        payload,
        session=session,
        ctx=ctx,
        previous_publication=previous_publication,
        default_destination=_default_publication_collection(db, proposal_workspace, ctx) if proposal_workspace else None,
    )
    operation = "updated" if proposal else "created"
    if proposal:
        conversation_state = ((proposal.proposal or {}).get("conversation") or {}).copy()
        if conversation_state:
            payload["conversation"] = conversation_state
        proposal.proposal = payload
        flag_modified(proposal, "proposal")
        if proposal.status == "changes_requested":
            # Refresh reopens the proposal for review; keep review_notes so the
            # requested changes remain visible to the next reviewer.
            proposal.status = "pending_review"
            proposal.reviewed_at = None
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
        _sync_session_proposal_open_questions_count(session, payload.get("open_questions"))
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


def _chat_correction_title(query: Optional[str]) -> str:
    """Derive a short human title from the originating chat question."""
    text = " ".join(str(query or "").split())
    if not text:
        return "Correction experte"
    snippet = text[:96].rstrip()
    if len(text) > len(snippet):
        snippet = f"{snippet}…"
    return f"Correction experte – {snippet}"


def _normalize_chat_correction_sources(sources: Optional[List[Any]]) -> List[Dict[str, Any]]:
    """Coerce free-form chat sources into a stable list of dicts for metadata."""
    normalized: List[Dict[str, Any]] = []
    for item in sources or []:
        if isinstance(item, Mapping):
            entry = {
                key: value
                for key, value in {
                    "title": _clean_optional_string(item.get("title") or item.get("name")),
                    "url": _clean_optional_string(item.get("url") or item.get("uri")),
                    "document_id": _clean_optional_string(item.get("document_id") or item.get("id")),
                    "collection": _clean_optional_string(
                        item.get("collection") or item.get("collection_slug")
                    ),
                    "snippet": _clean_optional_string(item.get("snippet") or item.get("excerpt")),
                }.items()
                if value
            }
            if entry:
                normalized.append(entry)
        else:
            label = _clean_optional_string(item)
            if label:
                normalized.append({"title": label})
    return normalized


def _chat_correction_markdown(
    *,
    query: Optional[str],
    correction_text: str,
    sources: List[Dict[str, Any]],
    expert_name: Optional[str],
    title: str,
) -> str:
    """Compose a clean, reviewable expert fiche from an inline chat correction.

    Layout mirrors the captured-fiche shape (question, expert answer, evidence)
    so reviewers and the downstream ingestion see a familiar structure.
    """
    question = " ".join(str(query or "").split()) or "—"
    correction = str(correction_text or "").strip()
    source_lines = []
    for source in sources:
        label = source.get("title") or source.get("url") or source.get("document_id")
        if not label:
            continue
        url = source.get("url")
        source_lines.append(f"- [{label}]({url})" if url else f"- {label}")
    sources_block = "\n".join(source_lines) or "- Aucune source citée."
    expert_block = f"\n_Expert : {expert_name}_\n" if expert_name else ""
    return (
        f"# {title}\n"
        f"{expert_block}\n"
        "## Question d'origine\n"
        f"{question}\n\n"
        "## Correction / complément de l'expert\n"
        f"{correction or '—'}\n\n"
        "## Sources citées\n"
        f"{sources_block}\n"
    )


def is_expert_review_required(source_policy: Optional[Mapping[str, Any]]) -> bool:
    """Whether expert corrections/captures must be reviewed before publication.

    Honours a per-workspace ``source_policy["expert_review_required"]`` override
    when present, otherwise falls back to the global default
    ``settings.kc_expert_review_required`` (``True``). Keeping the default
    ``True`` leaves the review workflow byte-for-byte unchanged unless a
    workspace explicitly opts out (``expert_review_required: false``).
    """
    if isinstance(source_policy, Mapping) and "expert_review_required" in source_policy:
        return bool(source_policy.get("expert_review_required"))
    from app.core.config import settings as cfg

    return bool(getattr(cfg, "kc_expert_review_required", True))


_CHAT_CORRECTION_THEME_MAX_WORDS = 12


def _fallback_chat_correction_theme(query: Optional[str], correction_text: str) -> str:
    """Deterministic short theme used when the LLM is unavailable.

    Derives from the first clause of the correction, then the originating
    question, truncated to a handful of words so the acknowledgement stays a
    one-liner. Never raises and never returns an empty string.
    """
    for raw in (correction_text, query):
        text = " ".join(str(raw or "").split())
        if not text:
            continue
        clause = re.split(r"[.;:\n]", text, maxsplit=1)[0].strip() or text
        words = clause.split()
        theme = " ".join(words[:_CHAT_CORRECTION_THEME_MAX_WORDS])
        if len(words) > _CHAT_CORRECTION_THEME_MAX_WORDS:
            theme = f"{theme}…"
        if theme:
            return theme
    return "votre correction"


async def summarize_chat_correction_theme(
    query: Optional[str],
    correction_text: str,
    *,
    workspace_id: Optional[str] = None,
    timeout_seconds: float = 4.0,
) -> str:
    """Very short (≤ ~12 words) thematic synthesis of an expert chat correction.

    Uses a cheap LLM call (mirrors :func:`plan_structure_llm_async`) bounded by a
    hard timeout, with a deterministic fallback derived from the
    question/correction so the acknowledgement never fails or hangs when no LLM
    is configured or the call errors/times out.
    """
    fallback = _fallback_chat_correction_theme(query, correction_text)
    correction = " ".join(str(correction_text or "").split())
    if not correction:
        return fallback
    try:
        api_key, model = _resolve_llm_config(workspace_id)
        if not api_key:
            return fallback
        from app.core.config import settings as cfg

        model = str(getattr(cfg, "capture_finalize_model", "") or model).strip() or model

        async def _call() -> Optional[str]:
            from openai import AsyncOpenAI

            client = AsyncOpenAI(api_key=api_key)
            prompt = {
                "question": " ".join(str(query or "").split()) or None,
                "correction": correction,
                "instruction": (
                    "Résume en UNE expression thématique très courte (≤ 12 mots, "
                    "sans phrase complète, sans ponctuation finale) le SUJET de la "
                    "correction apportée par l'expert. Réponds en JSON "
                    '{"theme": "..."}.'
                ),
            }
            response = await client.chat.completions.create(
                model=model,
                **_model_chat_kwargs(model, temperature=0.2),
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": "Synthèse thématique courte. JSON only."},
                    {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
                ],
            )
            content = response.choices[0].message.content if response.choices else None
            if not content:
                return None
            parsed = json.loads(content)
            theme = str((parsed or {}).get("theme") or "").strip()
            return theme or None

        theme = await asyncio.wait_for(_call(), timeout=timeout_seconds)
    except Exception:
        return fallback
    if not theme:
        return fallback
    words = theme.split()
    if len(words) > _CHAT_CORRECTION_THEME_MAX_WORDS:
        theme = " ".join(words[:_CHAT_CORRECTION_THEME_MAX_WORDS]) + "…"
    return theme


def build_chat_correction_acknowledgement(theme: str, *, published: bool) -> str:
    """Natural-language acquittal added to the chat thread after a correction.

    This is a simple acknowledgement of the correction — it does NOT reformulate
    or regenerate the original answer.
    """
    theme = (theme or "").strip() or "votre correction"
    if published:
        return f"J'ai bien pris en compte votre correction : {theme}."
    return (
        f"J'ai bien pris en compte votre correction : {theme}. "
        "Elle a été envoyée en revue avant publication."
    )


def create_chat_correction_proposal(
    db: DBSession,
    *,
    workspace: Any,
    user: Any,
    query: str,
    assistant_answer: Optional[str],
    correction_text: str,
    sources: Optional[List[Any]] = None,
    transcript_raw: Optional[str] = None,
    audio_ref: Optional[str] = None,
    input_modality: str = "text",
    source_policy: Optional[Dict[str, Any]] = None,
) -> Tuple[KnowledgeUpdateProposal, ExpertCaptureSession]:
    """Turn an inline chat correction into a ``pending_review`` proposal.

    A lightweight :class:`ExpertCaptureSession` (status ``chat_correction``)
    anchors the audit trail. When the correction came from voice, the raw
    transcript and the edited text are recorded on an ``ExpertCaptureEvent``
    (``source="voice"``) for replay. The resulting
    :class:`KnowledgeUpdateProposal` carries ``source_type="expert_fiche"`` so
    Volet 3 can boost it once published, and its publication destination
    defaults to :func:`resolve_expert_fiche_collection`.
    """
    correction_text = str(correction_text or "").strip()
    if not correction_text:
        raise ValueError("Chat correction cannot be empty")
    workspace_id = getattr(workspace, "id", None) or (
        workspace.get("id") if isinstance(workspace, Mapping) else None
    )
    user_id = getattr(user, "id", None) or (user.get("id") if isinstance(user, Mapping) else None)
    objective = " ".join(str(query or "").split()) or "Correction experte en chat"
    title = _chat_correction_title(query)
    normalized_modality = (input_modality or "text").strip().lower() or "text"
    is_voice = normalized_modality == "voice" or bool(transcript_raw)
    if is_voice:
        normalized_modality = "voice"

    capability = db.query(Capability).filter(Capability.slug == CAPABILITY_SLUG).first()
    session = ExpertCaptureSession(
        id=str(uuid.uuid4()),
        workspace_id=workspace_id,
        capability_id=capability.id if capability else None,
        created_by_user_id=user_id,
        title=title,
        objective=objective,
        status="chat_correction",
        plan={},
        knowledge_gaps=[],
        metrics={"origin": "chat_correction", "input_modality": normalized_modality},
    )
    db.add(session)
    db.flush()

    if is_voice:
        _record_capture_event(
            db,
            session=session,
            event_type="chat_correction_voice",
            speaker="expert",
            source="voice",
            status="accepted",
            audio_ref=audio_ref,
            text_raw=transcript_raw,
            text_amended=correction_text,
            created_by=user_id,
            meta_data={"origin": "chat_correction", "input_modality": "voice"},
        )

    expert_name = _resolve_user_label(db, user_id)
    normalized_sources = _normalize_chat_correction_sources(sources)
    destination_collection = resolve_expert_fiche_collection(workspace, source_policy)
    content = _chat_correction_markdown(
        query=query,
        correction_text=correction_text,
        sources=normalized_sources,
        expert_name=expert_name,
        title=title,
    )

    metadata: Dict[str, Any] = {
        "source_type": "expert_fiche",
        "origin": "chat_correction",
        "input_modality": normalized_modality,
        "question": objective,
        "sources": normalized_sources,
        "publication_destination": destination_collection,
        "publication_destination_scope": destination_collection,
    }
    if assistant_answer and str(assistant_answer).strip():
        metadata["assistant_answer"] = str(assistant_answer).strip()
    if expert_name:
        metadata["expert_name"] = expert_name
    if audio_ref:
        metadata["audio_ref"] = audio_ref

    payload: Dict[str, Any] = {
        "session_id": session.id,
        "title": title,
        "objective": objective,
        "report_markdown": content,
        "recommended_ingestion": {
            "title": title,
            "content": content,
            "metadata": metadata,
        },
        "publication": {
            "destination": destination_collection,
            "destination_scope": destination_collection,
            "final_title": title,
        },
        "review": {
            "required": True,
            "reason": "Expert chat corrections must be validated before they become indexed fiches.",
        },
    }

    proposal = KnowledgeUpdateProposal(
        id=str(uuid.uuid4()),
        workspace_id=workspace_id,
        session_id=session.id,
        status="pending_review",
        proposal=payload,
        created_by_user_id=user_id,
    )
    db.add(proposal)
    db.flush()
    _record_capture_event(
        db,
        session=session,
        event_type="proposal_generated",
        source="capture_engine",
        status="accepted",
        created_by=user_id,
        meta_data={
            "proposal_id": proposal.id,
            "origin": "chat_correction",
            "input_modality": normalized_modality,
            "destination_collection": destination_collection,
        },
    )
    db.commit()
    db.refresh(proposal)
    db.refresh(session)
    return proposal, session


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
    if proposal.status == "published":
        # A published fiche's review state is frozen; a new revision must go
        # through a fresh proposal instead.
        raise ValueError("Proposal is already published; its review state can no longer change")
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
            raw.get("question_id"),
            raw.get("key"),
            raw.get("id"),
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

    session = (
        db.query(ExpertCaptureSession)
        .filter(
            ExpertCaptureSession.id == proposal.session_id,
            ExpertCaptureSession.workspace_id == workspace_id,
        )
        .first()
    )
    if session:
        payload = _rebuild_proposal_report_payload(session, payload, questions)
        _sync_session_proposal_open_questions_count(session, questions)
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

    proposal.proposal = payload
    flag_modified(proposal, "proposal")
    db.commit()
    db.refresh(proposal)
    return proposal


def _resolve_rewrite_context(workspace_settings: Optional[Dict[str, Any]] = None) -> str:
    """Static domain framing for the FINAL reformulation only.

    Workspace ``settings.voice.transcript_rewrite_context`` overrides the global
    ``settings.voice_transcript_rewrite_context``.
    """
    if isinstance(workspace_settings, dict):
        voice_cfg = workspace_settings.get("voice")
        if isinstance(voice_cfg, dict):
            override = str(voice_cfg.get("transcript_rewrite_context") or "").strip()
            if override:
                return override
    from app.core.config import settings as cfg

    return str(getattr(cfg, "voice_transcript_rewrite_context", "") or "").strip()


def _resolve_plan_section_meta(
    plan: Dict[str, Any],
    topic_id: Optional[str],
    subtopic_id: Optional[str],
) -> Dict[str, Any]:
    """Resolve titles / path for a plan section addressed by topic/subtopic id."""
    meta = {
        "topic_id": topic_id,
        "subtopic_id": subtopic_id,
        "topic_title": None,
        "subtopic_title": None,
        "topic_path": None,
    }
    for topic in (plan or {}).get("topics") or []:
        if not isinstance(topic, dict):
            continue
        t_id = topic.get("id")
        for subtopic in topic.get("subtopics") or []:
            if not isinstance(subtopic, dict):
                continue
            if subtopic_id and subtopic.get("id") == subtopic_id:
                meta["topic_id"] = t_id
                meta["topic_title"] = topic.get("title")
                meta["subtopic_title"] = subtopic.get("title")
                meta["topic_path"] = " / ".join(
                    part for part in [topic.get("title"), subtopic.get("title")] if part
                )
                return meta
        if topic_id and not subtopic_id and t_id == topic_id:
            meta["topic_title"] = topic.get("title")
            meta["topic_path"] = topic.get("title")
            return meta
    return meta


def _section_statements(
    session: ExpertCaptureSession,
    topic_id: Optional[str],
    subtopic_id: Optional[str],
) -> List[str]:
    """Tier-1 corrected expert statements belonging to a section (or all if unscoped)."""
    statements: List[str] = []
    for turn in _read_transcript(session):
        if not isinstance(turn, dict) or turn.get("speaker") != "expert":
            continue
        text = str(turn.get("text") or turn.get("text_raw") or "").strip()
        if not text:
            continue
        if subtopic_id:
            if turn.get("subtopic_id") == subtopic_id:
                statements.append(text)
            elif (
                turn.get("topic_id") == topic_id
                and not turn.get("subtopic_id")
                and topic_id
            ):
                # Expert spoke on the topic before a subtopic was selected.
                statements.append(text)
        elif topic_id:
            if turn.get("topic_id") == topic_id:
                statements.append(text)
        else:
            statements.append(text)
    return statements


def _fact_belongs_to_section(
    fact: Dict[str, Any],
    topic_id: Optional[str],
    subtopic_id: Optional[str],
) -> bool:
    if subtopic_id:
        return fact.get("subtopic_id") == subtopic_id or (
            bool(topic_id) and fact.get("topic_id") == topic_id and not fact.get("subtopic_id")
        )
    if topic_id:
        return fact.get("topic_id") == topic_id
    return True


def _section_document_sources(
    session: ExpertCaptureSession,
    topic_id: Optional[str],
    subtopic_id: Optional[str],
) -> List[Dict[str, Any]]:
    facts = [
        fact
        for fact in (session.captured_facts or [])
        if isinstance(fact, dict) and _fact_belongs_to_section(fact, topic_id, subtopic_id)
    ]
    return _document_sources_from_facts(facts)


def _resolve_capture_report_source_min_score() -> float:
    from app.core.config import settings as cfg

    try:
        return float(getattr(cfg, "capture_report_source_min_score", 0.35) or 0.35)
    except (TypeError, ValueError):
        return 0.35


def _normalized_relevance_score(metadata: Any) -> Optional[float]:
    """Return a per-chunk relevance score on a normalized [0, 1] scale, or ``None``.

    The ``scores`` list returned by ``retrieve_rag_context`` is the RRF fusion
    weight, whose scale is path-dependent (~0.005-0.02 on the client-weighted
    RRF path vs ~3-22 on the Qdrant server-side path) and therefore NOT
    comparable to a cosine/similarity threshold. The retrieval layer instead
    preserves, per chunk in the metadata, normalized signals we can threshold:

    * ``cross_encoder_score`` — sigmoid relevance in [0, 1] (present only when
      the balanced cross-encoder rerank actually ran; absent on timeout/skip).
    * ``dense_score`` — the per-chunk dense cosine preserved at the dense layer
      (present whenever the chunk surfaced through the dense lane).

    Prefer the cross-encoder score, fall back to the dense cosine, and return
    ``None`` when neither is available (e.g. sparse-only chunks) so the caller
    keeps the chunk instead of dropping it on the meaningless fusion score.
    """
    if not isinstance(metadata, dict):
        return None
    for key in ("cross_encoder_score", "dense_score"):
        raw = metadata.get(key)
        if raw is None:
            continue
        try:
            return float(raw)
        except (TypeError, ValueError):
            continue
    return None


def _filter_retrieval_by_min_score(
    chunks: List[str],
    metadatas: List[Dict[str, Any]],
    scores: List[float],
    min_score: float,
) -> Tuple[List[str], List[Dict[str, Any]], List[float]]:
    """Drop retrieval hits below ``min_score`` before attaching them to reports.

    The threshold is applied to a NORMALIZED per-chunk relevance score in [0, 1]
    (cross-encoder sigmoid score if present, else the dense cosine
    ``dense_score``), NOT to the path-dependent RRF fusion ``scores``. A chunk
    with no normalized signal (sparse-only / missing-score) is KEPT — dropping
    it on the tiny client-weighted fusion score is exactly the regression this
    guards against.
    """
    if min_score <= 0:
        return list(chunks or []), list(metadatas or []), list(scores or [])
    kept_chunks: List[str] = []
    kept_meta: List[Dict[str, Any]] = []
    kept_scores: List[float] = []
    for index, chunk in enumerate(chunks or []):
        metadata = (
            metadatas[index]
            if index < len(metadatas) and isinstance(metadatas[index], dict)
            else {}
        )
        normalized = _normalized_relevance_score(metadata)
        if normalized is not None and normalized < min_score:
            continue
        kept_chunks.append(str(chunk))
        kept_meta.append(metadata)
        score = scores[index] if index < len(scores) else None
        if score is not None:
            kept_scores.append(float(score))
    return kept_chunks, kept_meta, kept_scores


def _apply_open_question_statuses_to_plan_structure(
    plan_structure: Dict[str, Any],
    open_questions: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Propagate proposal open-question lifecycle statuses onto plan_structure nodes."""
    if not isinstance(plan_structure, dict):
        return plan_structure
    status_by_text: Dict[str, str] = {}
    status_by_id: Dict[str, str] = {}
    for question in open_questions or []:
        if not isinstance(question, dict):
            continue
        status = _normalize_proposal_open_question_status(question.get("status"))
        text = str(
            question.get("follow_up") or question.get("text") or question.get("reason") or ""
        ).strip().lower()
        if text:
            status_by_text[text] = status
        for field in ("gap_id", "id", "question_id"):
            qid = _clean_optional_string(question.get(field))
            if qid:
                status_by_id[qid.lower()] = status

    def _sync_node(node: Dict[str, Any]) -> None:
        synced: List[Dict[str, Any]] = []
        for raw in node.get("open_questions") or []:
            if not isinstance(raw, dict):
                continue
            question = dict(raw)
            text = str(question.get("text") or question.get("follow_up") or "").strip().lower()
            qid = _clean_optional_string(question.get("id") or question.get("gap_id"))
            if qid and qid.lower() in status_by_id:
                question["status"] = status_by_id[qid.lower()]
            elif text and text in status_by_text:
                question["status"] = status_by_text[text]
            synced.append(question)
        if synced:
            node["open_questions"] = synced

    for topic in plan_structure.get("topics") or []:
        if not isinstance(topic, dict):
            continue
        _sync_node(topic)
        for subtopic in topic.get("subtopics") or []:
            if isinstance(subtopic, dict):
                _sync_node(subtopic)
    return plan_structure


def _rebuild_proposal_report_payload(
    session: ExpertCaptureSession,
    payload: Dict[str, Any],
    open_questions: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Refresh plan_structure question statuses and re-assemble report markdown."""
    plan_structure = payload.get("plan_structure")
    if not isinstance(plan_structure, dict):
        return payload
    updated = dict(payload)
    synced_structure = _apply_open_question_statuses_to_plan_structure(plan_structure, open_questions)
    report = _assemble_report_from_sections(session, synced_structure, open_questions)
    updated["plan_structure"] = synced_structure
    updated["open_questions"] = open_questions
    updated["report_markdown"] = report
    recommended = dict(updated.get("recommended_ingestion") or {})
    recommended["content"] = report
    updated["recommended_ingestion"] = recommended
    return updated


def _assemble_report_from_sections(
    session: ExpertCaptureSession,
    plan_structure: Dict[str, Any],
    open_questions: List[Dict[str, Any]],
) -> str:
    """Assemble a Markdown report from the per-section FINAL synthesis.

    Prefers each section's reformulated ``synthesis``; falls back to fact bullets.
    """
    lines: List[str] = [f"# {session.title}", "", f"Objectif : {session.objective}", ""]

    def _emit_facts(facts: List[Dict[str, Any]]) -> None:
        for fact in facts or []:
            statement = str(fact.get("text") or "").strip()
            if statement:
                lines.append(f"- {statement}")

    def _emit_sources(node: Dict[str, Any]) -> None:
        labels: List[str] = []
        for source in node.get("sources") or []:
            if not isinstance(source, dict):
                continue
            label = str(source.get("title") or source.get("source") or "").strip()
            if label and label not in labels:
                labels.append(label)
        if labels:
            lines.append("")
            lines.append("Sources : " + " · ".join(labels))

    for topic in plan_structure.get("topics") or []:
        lines.append(f"## {topic.get('title') or 'Sujet'}")
        if topic.get("synthesis"):
            lines.append(str(topic["synthesis"]).strip())
        else:
            _emit_facts(topic.get("facts") or [])
        _emit_sources(topic)
        for subtopic in topic.get("subtopics") or []:
            lines.append(f"### {subtopic.get('title') or 'Sous-sujet'}")
            if subtopic.get("synthesis"):
                lines.append(str(subtopic["synthesis"]).strip())
            else:
                _emit_facts(subtopic.get("facts") or [])
            _emit_sources(subtopic)
        lines.append("")
    unassigned = plan_structure.get("unassigned") or []
    if unassigned:
        lines.append("## Points hors plan")
        _emit_facts(unassigned)
        lines.append("")
    visible_questions = [
        q
        for q in open_questions or []
        if isinstance(q, dict)
        and _normalize_proposal_open_question_status(q.get("status")) in {"open", "deferred"}
    ]
    if visible_questions:
        lines.append("## Questions ouvertes pour reprise")
        lines.append("_Points restés sans réponse à la publication ; à compléter par un expert._")
        for item in visible_questions:
            label = item.get("follow_up") or item.get("text") or item.get("reason") or item.get("gap_id")
            if label:
                lines.append(f"- {label}")
    return "\n".join(lines).rstrip() + "\n"


def _strip_open_questions_section(markdown: str) -> str:
    """Drop the open-questions section from a report about to be published.

    Matches the ``## Questions ouvertes …`` heading emitted by
    ``_assemble_report_from_sections`` and removes everything until the next
    same-or-higher-level heading (or end of document). Does not mutate the
    stored ``report_markdown`` — only the published artifact is stripped.
    """
    lines = markdown.splitlines()
    kept: List[str] = []
    skipping = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## "):
            skipping = stripped[3:].strip().lower().startswith("questions ouvertes")
            if skipping:
                continue
        elif stripped.startswith("# "):
            skipping = False
        if not skipping:
            kept.append(line)
    result = re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).rstrip()
    return (result + "\n") if result else ""


def set_active_capture_section(
    db: DBSession,
    *,
    workspace_id: str,
    session_id: str,
    topic_id: Optional[str] = None,
    subtopic_id: Optional[str] = None,
    actor_user_id: Optional[str] = None,
) -> ExpertCaptureSession:
    """Set the active topic/subtopic for the session (section.select). No relance."""
    session = get_session(db, workspace_id=workspace_id, session_id=session_id, materialize=False)
    metrics = dict(session.metrics or {})
    meta = _resolve_plan_section_meta(session.plan or {}, topic_id, subtopic_id)
    if topic_id is not None:
        metrics["active_topic_id"] = meta.get("topic_id") or topic_id or None
    if subtopic_id is not None:
        metrics["active_subtopic_id"] = subtopic_id or None
    session.metrics = metrics
    flag_modified(session, "metrics")
    db.commit()
    db.refresh(session)
    return session


def _source_display_filename(md: Dict[str, Any]) -> Optional[str]:
    return md.get("filename") or md.get("document_filename") or md.get("legacy_document_name")


def _source_display_title(md: Dict[str, Any]) -> Optional[str]:
    """Human document name for source chips — same metadata keys the chat chips
    resolve (``document_title``/``document_filename`` come from the Qdrant
    payload), so the report never shows raw document ids."""
    return (
        md.get("title")
        or md.get("document_title")
        or _source_display_filename(md)
        or md.get("archive_name")
        or md.get("source")
    )


def _section_sources(
    chunks: List[str],
    metadatas: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Shape the retrieved KB passages backing a section into displayable sources.

    Carries the document identity (title + document_id/collection) so the
    frontend can render chat-style source chips with the document preview,
    instead of raw ids. Deduped by document."""
    metadatas = metadatas or []
    sources: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for index, chunk in enumerate(chunks or []):
        text = str(chunk or "").strip()
        md = metadatas[index] if index < len(metadatas) and isinstance(metadatas[index], dict) else {}
        document_id = md.get("document_id") or md.get("doc_id") or md.get("id")
        filename = _source_display_filename(md)
        title = _source_display_title(md)
        page = _positive_int(md.get("page") or md.get("page_number"))
        slide = _positive_int(md.get("slide") or md.get("slide_number"))
        key = str(document_id or title or text[:80]).strip().lower()
        if page or slide:
            key = f"{key}|p:{page or ''}|s:{slide or ''}"
        if not key or key in seen:
            continue
        seen.add(key)
        sources.append(
            {
                "rank": index + 1,
                "document_id": document_id,
                "source_id": md.get("source_id") or md.get("source"),
                "source": md.get("source") or filename or title or document_id,
                "title": title,
                "filename": filename,
                "collection": md.get("collection") or md.get("collection_name"),
                "page": page,
                "page_number": page,
                "slide": slide,
                "preview": text[:360],
            }
        )
    return sources


def _resolve_final_glossary(
    workspace: Any,
    session: Any,
    chunks: Optional[List[str]] = None,
):
    """Tier-2 glossary for the FINAL pass: workspace glossary + plan labels +
    distinctive terms from the section's retrieved KB passages.

    ``workspace``/``session`` only need ``.settings`` / ``.plan`` attributes —
    callers pass plain snapshots so this stays DB-free (safe under concurrency).
    """
    from app.services.voice_transcript_glossary import resolve_glossary

    try:
        return resolve_glossary(workspace, session, chunks or [])
    except Exception:
        return None


async def _notify_finalize_progress(
    progress: Optional[FinalizeProgressCallback],
    payload: Dict[str, Any],
) -> None:
    """Best-effort progress notification (await coroutines, ignore failures)."""
    if progress is None:
        return
    try:
        result = progress(payload)
        if asyncio.iscoroutine(result):
            await result
    except Exception:  # noqa: BLE001 - progress must never break finalization.
        pass


# Bounded fan-out for the FINAL per-section pass: enough to hide the LLM
# latency across sections without hammering the retrieval/OpenAI lanes.
_FINALIZE_SECTION_CONCURRENCY = 3


def _prepare_section_finalize(
    db: DBSession,
    *,
    workspace_id: str,
    session: ExpertCaptureSession,
    topic_id: Optional[str],
    subtopic_id: Optional[str],
    static_context: Optional[str],
) -> Dict[str, Any]:
    """All DB reads for one section's FINAL pass, done up-front.

    Returns a plain-data snapshot (statements, meta, collection name, glossary
    inputs) so the heavy compute phase can run concurrently across sections
    without ever touching the shared SQLAlchemy session.
    """
    from types import SimpleNamespace

    from app.models.workspace import Workspace as WorkspaceModel

    plan = dict(session.plan or {})
    meta = _resolve_plan_section_meta(plan, topic_id, subtopic_id)
    section_key = _section_key(meta.get("topic_id"), meta.get("subtopic_id"))
    raw_statements = _section_statements(session, meta.get("topic_id"), meta.get("subtopic_id"))
    document_sources = _section_document_sources(session, meta.get("topic_id"), meta.get("subtopic_id"))
    label = (
        meta.get("topic_path")
        or " / ".join(part for part in [meta.get("topic_title"), meta.get("subtopic_title")] if part)
        or (session.title or "")
    )
    if static_context is None:
        static_context = _resolve_rewrite_context(None)
    try:
        ctx = _load_context(db, workspace_id, session.context_id)
    except Exception:
        ctx = None
    try:
        workspace = db.query(WorkspaceModel).filter(WorkspaceModel.id == workspace_id).first()
    except Exception:
        workspace = None
    workspace_settings = dict(getattr(workspace, "settings", None) or {}) if workspace is not None else {}
    return {
        "meta": meta,
        "section_key": section_key,
        "label": label,
        "raw_statements": raw_statements,
        "document_sources": document_sources,
        "static_context": static_context,
        "collection_name": _resolve_collection_name(ctx),
        "session_ref": SimpleNamespace(
            context_id=session.context_id,
            capability_id=session.capability_id,
            system_id=session.system_id,
        ),
        "glossary_workspace": SimpleNamespace(settings=workspace_settings),
        "glossary_session": SimpleNamespace(plan=plan),
    }


async def _compute_section_finalize_async(
    *,
    workspace_id: str,
    workspace_slug: Optional[str],
    prep: Dict[str, Any],
    progress: Optional[FinalizeProgressCallback] = None,
) -> Dict[str, Any]:
    """Compute phase of one section's FINAL pass — NO DB access.

    Chat-grade retrieval, dedupe of repeated/rephrased expert turns, Tier-2
    domain-glossary vocabulary alignment, then the exhaustive LLM reformulation
    and the grounded open-question generation run CONCURRENTLY (the questions
    only need statements + chunks, never the synthesis). Safe to run for several
    sections at once (everything works on the plain-data ``prep`` snapshot).
    """
    meta = prep["meta"]
    label = prep["label"]
    raw_statements = list(prep["raw_statements"])

    # 1) Dedupe: the expert repeats/rephrases across turns — clean before the
    # reformulation so duplicates never reach the report.
    await _notify_finalize_progress(
        progress,
        {"stage": "dedupe", "label": "Nettoyage des doublons…", "section_label": label},
    )
    statements, dedup_removed = dedupe_statements(raw_statements)

    query = f"{label} {' '.join(statements)}".strip()[:1200]
    try:
        chunks, metadatas, raw_scores = await _retrieve_context_chunks_async(
            None,
            workspace_id=workspace_id,
            workspace_slug=workspace_slug,
            session=prep["session_ref"],
            query=query,
            top_k=4,
            retrieval_profile="chat",
            collection_name=prep["collection_name"],
        )
    except Exception:
        chunks, metadatas, raw_scores = [], [], []
    min_source_score = _resolve_capture_report_source_min_score()
    chunks, metadatas, _scores = _filter_retrieval_by_min_score(
        chunks,
        metadatas,
        raw_scores,
        min_source_score,
    )

    from app.services.capture_knowledge_oracle import (
        generate_grounded_open_questions_async,
        reformulate_section_async,
    )
    from app.services.voice_transcript_glossary import correct_transcript_segment_tier1

    # 2) Tier-2 vocabulary alignment: the workspace domain glossary is wired into
    # the FINAL pass (deterministic Tier-1 repair on the inputs + glossary terms
    # handed to the reformulation prompt), not the live path.
    await _notify_finalize_progress(
        progress,
        {"stage": "vocabulary", "label": "Alignement vocabulaire métier…", "section_label": label},
    )
    glossary = _resolve_final_glossary(prep["glossary_workspace"], prep["glossary_session"], chunks)
    glossary_terms: List[str] = list(glossary.terms) if glossary is not None else []
    if glossary is not None and not glossary.is_empty:
        statements = [correct_transcript_segment_tier1(s, glossary) for s in statements]

    # 3) Restructuring + exhaustive reformulation, CONCURRENT with the grounded
    # open-question generation (which only needs statements + chunks).
    await _notify_finalize_progress(
        progress,
        {"stage": "reformulate", "label": "Reformulation et questions ouvertes…", "section_label": label},
    )
    synthesis, grounded = await asyncio.gather(
        reformulate_section_async(
            workspace_id=workspace_id,
            section_label=label,
            statements=statements,
            kb_chunks=chunks,
            static_context=prep["static_context"],
            glossary_terms=glossary_terms,
        ),
        generate_grounded_open_questions_async(
            "\n".join(statements),
            chunks,
            metadatas,
            {
                "topic_id": meta.get("topic_id"),
                "subtopic_id": meta.get("subtopic_id"),
                "topic_title": meta.get("topic_title"),
                "subtopic_title": meta.get("subtopic_title"),
            },
            workspace_id=workspace_id,
        ),
    )
    return {
        "section_key": prep["section_key"],
        "topic_id": meta.get("topic_id"),
        "subtopic_id": meta.get("subtopic_id"),
        "section_label": label,
        "synthesis": synthesis,
        "open_questions": grounded,
        "sources": _merge_report_sources(_section_sources(chunks, metadatas), prep.get("document_sources") or []),
        "statement_count": len(statements),
        "raw_statement_count": len(raw_statements),
        "dedup_removed": dedup_removed,
        "glossary_term_count": len(glossary_terms),
        "updated_at": datetime.utcnow().isoformat(),
    }


def _skipped_section_entry(prep: Dict[str, Any]) -> Dict[str, Any]:
    meta = prep["meta"]
    return {
        "section_key": prep["section_key"],
        "topic_id": meta.get("topic_id"),
        "subtopic_id": meta.get("subtopic_id"),
        "synthesis": "",
        "open_questions": [],
        "sources": list(prep.get("document_sources") or []),
        "statement_count": 0,
        "skipped": True,
    }


def _store_section_synthesis_entries(
    db: DBSession,
    *,
    workspace_id: str,
    session_id: str,
    entries: List[Dict[str, Any]],
) -> ExpertCaptureSession:
    """Sequential DB write phase: store computed section syntheses + events and
    commit ONCE (the single sync session is never used concurrently)."""
    session = get_session(db, workspace_id=workspace_id, session_id=session_id)
    plan = dict(session.plan or {})
    section_synthesis = dict(plan.get("section_synthesis") or {})
    for entry in entries:
        section_synthesis[entry["section_key"]] = entry
    plan["section_synthesis"] = section_synthesis
    session.plan = plan
    flag_modified(session, "plan")
    for entry in entries:
        _record_capture_event(
            db,
            session=session,
            event_type="capture_section_finalized",
            source="capture_engine",
            status="accepted",
            meta_data={
                "section_key": entry["section_key"],
                "topic_id": entry.get("topic_id"),
                "subtopic_id": entry.get("subtopic_id"),
                "statement_count": entry.get("statement_count", 0),
                "grounded_question_count": len(entry.get("open_questions") or []),
            },
        )
    db.commit()
    db.refresh(session)
    return session


async def finalize_capture_section(
    db: DBSession,
    *,
    workspace_id: str,
    session_id: str,
    topic_id: Optional[str] = None,
    subtopic_id: Optional[str] = None,
    workspace_slug: Optional[str] = None,
    static_context: Optional[str] = None,
    progress: Optional[FinalizeProgressCallback] = None,
) -> Dict[str, Any]:
    """FINAL phase for ONE section (section.finish).

    The heavy end-of-capture pass for a section: chat-grade retrieval, dedupe of
    repeated/rephrased expert turns, Tier-2 domain-glossary vocabulary alignment,
    the exhaustive LLM reformulation and the grounded open-question generation
    (run concurrently), then stores the result (with its KB sources) on the plan
    under ``section_synthesis``. Non-fatal: returns an empty entry when the
    section has no captured statements.
    """
    session = get_session(db, workspace_id=workspace_id, session_id=session_id)
    prep = _prepare_section_finalize(
        db,
        workspace_id=workspace_id,
        session=session,
        topic_id=topic_id,
        subtopic_id=subtopic_id,
        static_context=static_context,
    )
    if not prep["raw_statements"]:
        return _skipped_section_entry(prep)
    entry = await _compute_section_finalize_async(
        workspace_id=workspace_id,
        workspace_slug=workspace_slug,
        prep=prep,
        progress=progress,
    )
    _store_section_synthesis_entries(
        db,
        workspace_id=workspace_id,
        session_id=session_id,
        entries=[entry],
    )
    return entry


async def _ensure_final_thematic_plan(
    db: DBSession,
    *,
    workspace_id: str,
    session_id: str,
) -> ExpertCaptureSession:
    """When the capture ran WITHOUT a plan (free conversation), structure the
    expression into LLM-derived thematic blocks at the FINAL phase.

    Materializes the themes as plan topics (``generated_by: final_thematic``)
    and tags each expert turn with its theme's topic_id, so the whole
    per-section FINAL machinery (dedupe, reformulation, grounded questions,
    report assembly) applies unchanged."""
    session = get_session(db, workspace_id=workspace_id, session_id=session_id)
    plan = dict(session.plan or {})
    if [t for t in (plan.get("topics") or []) if isinstance(t, dict)]:
        return session
    transcript = list(session.transcript or [])
    expert_indexes = [
        index
        for index, turn in enumerate(transcript)
        if isinstance(turn, dict)
        and turn.get("speaker") == "expert"
        and str(turn.get("text") or turn.get("text_raw") or "").strip()
    ]
    if not expert_indexes:
        return session
    statements = [
        str(transcript[index].get("text") or transcript[index].get("text_raw") or "").strip()
        for index in expert_indexes
    ]
    try:
        themes = await derive_thematic_blocks_async(workspace_id=workspace_id, statements=statements)
    except Exception as exc:  # noqa: BLE001 - thematic structuring must not abort the proposal.
        _logger.warning("knowledge_capture_thematic_structuring_failed: %s", exc)
        themes = []
    if not themes:
        return session
    topics: List[Dict[str, Any]] = []
    for theme in themes:
        theme_id = str(theme.get("id") or f"theme-{len(topics) + 1:02d}")
        title = str(theme.get("title") or "").strip() or f"Thème {len(topics) + 1}"
        topics.append(
            {
                "id": theme_id,
                "title": title,
                "status": "completed",
                "generated_by": "final_thematic",
                "subtopics": [],
            }
        )
        for statement_index in theme.get("statement_indexes") or []:
            try:
                transcript_index = expert_indexes[int(statement_index)]
            except (TypeError, ValueError, IndexError):
                continue
            turn = dict(transcript[transcript_index])
            turn["topic_id"] = theme_id
            turn.setdefault("topic_path", title)
            transcript[transcript_index] = turn
    plan["topics"] = topics
    plan["final_thematic"] = True
    session.plan = plan
    session.transcript = transcript
    flag_modified(session, "plan")
    flag_modified(session, "transcript")
    # Theme tags live only on the materialized turns; clear the deferred flag so the
    # downstream proposal build uses this tagged cache instead of rebuilding it.
    _set_transcript_dirty(session, False)
    _record_capture_event(
        db,
        session=session,
        event_type="capture_thematic_structure_built",
        source="capture_engine",
        status="accepted",
        meta_data={"theme_count": len(topics), "statement_count": len(statements)},
    )
    db.commit()
    db.refresh(session)
    return session


async def finalize_capture(
    db: DBSession,
    *,
    workspace_id: str,
    session_id: str,
    workspace_slug: Optional[str] = None,
    static_context: Optional[str] = None,
    created_by_user_id: Optional[str] = None,
    progress: Optional[FinalizeProgressCallback] = None,
) -> KnowledgeUpdateProposal:
    """FINAL phase for the whole capture (capture.finish).

    The heavy end-of-capture pass: restructures the expression against the plan
    hierarchy (or LLM-derived thematic blocks when the conversation was free),
    closes every remaining section (dedupe + Tier-2 glossary alignment +
    exhaustive reformulation + grounded questions) and then builds/refreshes the
    proposal from the stored syntheses. ``progress`` (optional async callback)
    receives honest stage events for the frontend loader."""
    session = get_session(db, workspace_id=workspace_id, session_id=session_id)
    plan = dict(session.plan or {})
    has_plan = bool([t for t in (plan.get("topics") or []) if isinstance(t, dict)])
    await _notify_finalize_progress(
        progress,
        {
            "stage": "restructure",
            "label": "Restructuration selon le plan…" if has_plan else "Structuration en blocs thématiques…",
        },
    )
    if not has_plan:
        session = await _ensure_final_thematic_plan(db, workspace_id=workspace_id, session_id=session_id)
        plan = dict(session.plan or {})
    else:
        session = _backfill_turn_plan_tags(db, workspace_id=workspace_id, session_id=session_id)
        plan = dict(session.plan or {})
    sections: List[Tuple[Optional[str], Optional[str]]] = []
    for topic in plan.get("topics") or []:
        if not isinstance(topic, dict):
            continue
        subtopics = [st for st in (topic.get("subtopics") or []) if isinstance(st, dict)]
        if subtopics:
            for subtopic in subtopics:
                sections.append((topic.get("id"), subtopic.get("id")))
        else:
            sections.append((topic.get("id"), None))
    if not sections:
        sections = [(None, None)]
    total = len(sections)

    # Up-front sequential DB reads: snapshot everything each section's compute
    # phase needs, so the concurrent phase below never touches the shared
    # SQLAlchemy session.
    preps: List[Dict[str, Any]] = [
        _prepare_section_finalize(
            db,
            workspace_id=workspace_id,
            session=session,
            topic_id=topic_id,
            subtopic_id=subtopic_id,
            static_context=static_context,
        )
        for topic_id, subtopic_id in sections
    ]

    semaphore = asyncio.Semaphore(_FINALIZE_SECTION_CONCURRENCY)
    started_count = 0

    async def _run_section(prep: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        nonlocal started_count
        async with semaphore:
            started_count += 1
            section_label = prep["label"]
            await _notify_finalize_progress(
                progress,
                {
                    "stage": "section",
                    "label": f"Synthèse « {section_label} »…" if section_label else "Synthèse de la capture…",
                    "section_label": section_label,
                    "current": min(started_count, total),
                    "total": total,
                },
            )
            if not prep["raw_statements"]:
                return None
            try:
                return await _compute_section_finalize_async(
                    workspace_id=workspace_id,
                    workspace_slug=workspace_slug,
                    prep=prep,
                    progress=progress,
                )
            except Exception as exc:  # noqa: BLE001 - one bad section must not abort the proposal.
                _logger.warning("knowledge_capture_finalize_section_failed: %s", exc)
                return None

    # Concurrent compute phase (LLM + retrieval), bounded fan-out.
    results = await asyncio.gather(*(_run_section(prep) for prep in preps))
    finalized_sections: Dict[str, Dict[str, Any]] = {
        str(entry["section_key"]): entry
        for entry in results
        if isinstance(entry, dict) and entry.get("section_key") and not entry.get("skipped")
    }
    # Sequential DB write phase: single-session writes + ONE commit.
    if finalized_sections:
        try:
            _store_section_synthesis_entries(
                db,
                workspace_id=workspace_id,
                session_id=session_id,
                entries=list(finalized_sections.values()),
            )
        except Exception as exc:  # noqa: BLE001 - the proposal is still built from the computed entries.
            _logger.warning("knowledge_capture_finalize_store_failed: %s", exc)
            db.rollback()
    await _notify_finalize_progress(progress, {"stage": "report", "label": "Assemblage du rapport…"})
    db.expire_all()
    fresh_session = get_session(db, workspace_id=workspace_id, session_id=session_id)
    db.refresh(fresh_session)
    plan_snapshot = dict(fresh_session.plan or {})
    if finalized_sections:
        merged_synthesis = dict(plan_snapshot.get("section_synthesis") or {})
        merged_synthesis.update(finalized_sections)
        plan_snapshot["section_synthesis"] = merged_synthesis
    proposal = create_update_proposal(
        db,
        workspace_id=workspace_id,
        session_id=session_id,
        created_by_user_id=created_by_user_id,
        plan_snapshot=plan_snapshot,
    )
    await _notify_finalize_progress(progress, {"stage": "done", "label": "Rapport prêt."})
    return proposal


def _match_proposal_open_question(
    questions: List[Dict[str, Any]],
    question_id: str,
) -> Optional[int]:
    qid = _clean_optional_string(question_id)
    if not qid:
        return None
    qid_lower = qid.lower()
    for index, question in enumerate(questions):
        keys = {key.lower() for key in _proposal_open_question_keys(question, index)}
        if qid_lower in keys:
            return index
        for field in ("gap_id", "id", "follow_up", "text", "reason"):
            value = _clean_optional_string(question.get(field))
            if value and value.lower() == qid_lower:
                return index
    return None


async def answer_proposal_open_question(
    db: DBSession,
    *,
    workspace_id: str,
    proposal_id: str,
    question_id: str,
    text: str,
    actor_user_id: Optional[str] = None,
    actor_label: Optional[str] = None,
    workspace_slug: Optional[str] = None,
    static_context: Optional[str] = None,
) -> KnowledgeUpdateProposal:
    """Answer ONE proposal open question (text already transcribed for voice).

    Injects the answer into the relevant plan section, marks the question
    ``answered`` and RE-SYNTHESIZES ONLY THAT SECTION (the LLM reformulation +
    grounded questions are scoped to the section; other sections keep their
    cached synthesis — no full rebuild).
    """
    proposal = (
        db.query(KnowledgeUpdateProposal)
        .filter(KnowledgeUpdateProposal.id == proposal_id, KnowledgeUpdateProposal.workspace_id == workspace_id)
        .first()
    )
    if not proposal:
        raise ValueError("Knowledge update proposal not found")
    answer = (text or "").strip()
    if not answer:
        raise ValueError("Answer text cannot be empty")
    session = get_session(db, workspace_id=workspace_id, session_id=proposal.session_id)
    payload = dict(proposal.proposal or {})
    questions = [
        dict(question)
        for question in (payload.get("open_questions") or [])
        if isinstance(question, dict)
    ]
    if not questions:
        raise ValueError("Knowledge update proposal has no open questions")
    target_index = _match_proposal_open_question(questions, question_id)
    if target_index is None:
        raise ValueError("Open question not found")
    target = questions[target_index]
    topic_id = target.get("topic_id")
    subtopic_id = target.get("subtopic_id")

    # Inject the answer as a section-tagged expert turn so the targeted
    # re-synthesis (and captured_facts) pick it up.
    append_turn(
        db,
        workspace_id=workspace_id,
        session_id=session.id,
        speaker="expert",
        text=answer,
        turn_kind="complement",
        actor_user_id=actor_user_id,
        topic_id=topic_id,
        subtopic_id=subtopic_id,
    )
    await finalize_capture_section(
        db,
        workspace_id=workspace_id,
        session_id=session.id,
        topic_id=topic_id,
        subtopic_id=subtopic_id,
        workspace_slug=workspace_slug,
        static_context=static_context,
    )
    session = get_session(db, workspace_id=workspace_id, session_id=session.id)

    now = datetime.utcnow().isoformat()
    questions[target_index]["status"] = "answered"
    questions[target_index]["answer_text"] = answer
    questions[target_index]["status_updated_at"] = now
    questions[target_index]["status_updated_by_user_id"] = actor_user_id

    plan = session.plan or {}
    captured = list(session.captured_facts or [])
    plan_structure = _filter_redundant_unassigned_facts(
        _attach_section_synthesis(_structure_facts_by_plan(plan, captured), plan)
    )
    report = _assemble_report_from_sections(session, plan_structure, questions)

    payload["open_questions"] = questions
    payload["captured_facts"] = captured
    payload["plan_structure"] = plan_structure
    payload["report_markdown"] = report
    recommended = dict(payload.get("recommended_ingestion") or {})
    recommended["content"] = report
    metadata = dict(recommended.get("metadata") or {})
    metadata.update(
        {
            "edited_by_user_id": actor_user_id,
            "edited_at": now,
            "last_answered_question_id": _clean_optional_string(question_id),
        }
    )
    recommended["metadata"] = metadata
    payload["recommended_ingestion"] = recommended
    proposal.proposal = payload
    flag_modified(proposal, "proposal")
    _sync_session_proposal_open_questions_count(session, questions)
    _record_capture_event(
        db,
        session=session,
        event_type="proposal_open_question_answered",
        source="operator_edit",
        status="answered",
        created_by=actor_label or actor_user_id,
        meta_data={
            "proposal_id": proposal.id,
            "question_id": _clean_optional_string(question_id),
            "topic_id": topic_id,
            "subtopic_id": subtopic_id,
            "answer_chars": len(answer),
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
    if proposal.status == "published":
        raise ValueError("Proposal is already published; its report can no longer be edited")
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
    if proposal.status == "published":
        raise ValueError("Proposal is already published; its report can no longer be edited")
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


def _is_free_conversation_session(session: ExpertCaptureSession) -> bool:
    plan = session.plan or {}
    return plan.get("mode") == "free_conversation" or plan.get("schema_version") == FREE_CONVERSATION_SCHEMA_VERSION


def is_free_conversation_session(session: ExpertCaptureSession) -> bool:
    return _is_free_conversation_session(session)


def _metadata_float(metadata: Dict[str, Any], key: str) -> float:
    try:
        return float(metadata.get(key) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _retrieval_metadata_has_strong_evidence(metadatas: List[Dict[str, Any]]) -> bool:
    for metadata in metadatas:
        coverage = _metadata_float(metadata, "retrieval_evidence_coverage")
        policy_score = _metadata_float(metadata, "retrieval_policy_score")
        exact_terms = metadata.get("retrieval_exact_terms_matched")
        exact_term_count = len(exact_terms) if isinstance(exact_terms, list) else 0
        if coverage >= 0.35 or exact_term_count >= 2 or (coverage >= 0.2 and policy_score >= 3):
            return True
    return False


def _capture_prefetch_passive_state(
    session: ExpertCaptureSession,
    *,
    status: str,
    oracle_exact_matches: List[Dict[str, Any]],
    metadatas: List[Dict[str, Any]],
) -> tuple[bool, Optional[str]]:
    if not _is_free_conversation_session(session):
        return False, None
    if status in {"timeout", "error"}:
        return True, status
    if oracle_exact_matches:
        return False, None
    if _retrieval_metadata_has_strong_evidence(metadatas):
        return False, None
    return True, "weak_evidence"


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
    warm_cache = _get_capture_warm_cache(session.id)
    warm_cache_hit = False
    oracle_exact_matches: List[Dict[str, Any]] = []

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
                    "retrieval_profile": "oracle_fast",
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
            "retrieval_profile": metrics.get("retrieval_profile") or retrieval_context.get("retrieval_profile"),
            "profile": metrics.get("profile"),
            "scope_confidence": metrics.get("scope_confidence"),
            "fallback_reason": metrics.get("fallback_reason"),
            "warm_cache_hit": False,
        }
    except TimeoutError:
        status = "timeout"
        event_type = "retrieval_prefetch_timeout"
        detail = {"reason": f"retrieval exceeded {timeout_seconds:.1f}s"}
    except Exception as exc:
        status = "error"
        event_type = "retrieval_prefetch_timeout"
        detail = {"reason": str(exc)}
    if status in {"timeout", "error"} and warm_cache:
        chunks = list(warm_cache.get("chunks") or [])
        scores = list(warm_cache.get("scores") or [])
        metadatas = list(warm_cache.get("metadatas") or [])
        status = "completed_from_warm_cache"
        event_type = "retrieval_prefetch_completed"
        warm_cache_hit = True
        detail = {
            **detail,
            "warm_cache_hit": True,
            "warm_cache_reason": detail.get("reason"),
            "pipeline": warm_cache.get("pipeline"),
            "retrieval_profile": warm_cache.get("retrieval_profile") or "oracle_fast",
            "dense_only": warm_cache.get("dense_only"),
            "sparse_status": warm_cache.get("sparse_status"),
            "sparse_backend": warm_cache.get("sparse_backend"),
            "fallback_reason": warm_cache.get("fallback_reason"),
        }

    if chunks:
        oracle_exact_matches = sparse_exact_match_evidence(text, chunks, metadatas)
    passive, passive_reason = _capture_prefetch_passive_state(
        session,
        status=status,
        oracle_exact_matches=oracle_exact_matches,
        metadatas=metadatas,
    )

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
            "warm_cache_hit": warm_cache_hit,
            "passive": passive,
            "passive_reason": passive_reason,
            "oracle_exact_matches": oracle_exact_matches,
            "oracle_exact_match_count": len(oracle_exact_matches),
            **question_meta,
            **detail,
        },
    )
    db.commit()
    db.refresh(final_event)

    hint_payload: Dict[str, Any] = {}
    if not passive and chunks and len(_words(text)) >= 6:
        hint_payload = process_capture_partial_hints(
            db,
            workspace_id=workspace_id,
            session_id=session_id,
            partial_text=text,
            retrieval_chunks=chunks,
            retrieval_metadatas=metadatas,
            client_turn_id=client_turn_id,
        )
        if not oracle_exact_matches:
            oracle_exact_matches = list(hint_payload.get("oracle_exact_matches") or [])

    returned_chunks = [] if passive else chunks
    returned_scores = [] if passive else scores
    returned_metadatas = [] if passive else metadatas
    return {
        "event_id": final_event.id,
        "status": status,
        "latency_ms": latency_ms,
        "chunks": returned_chunks,
        "scores": returned_scores,
        "metadatas": returned_metadatas,
        "stale": False,
        "warm_cache_hit": warm_cache_hit,
        "passive": passive,
        "passive_reason": passive_reason,
        "oracle_exact_matches": oracle_exact_matches,
        "oracle_exact_match_count": len(oracle_exact_matches),
        "collection_name": collection_name,
        "hints": [] if passive else (hint_payload.get("hints") or []),
        "active_subtopic_id": None if passive else hint_payload.get("active_subtopic_id"),
        "active_topic_id": None if passive else hint_payload.get("active_topic_id"),
        "active_section_confidence": 0.0 if passive else (hint_payload.get("active_section_confidence") or 0.0),
        "contradiction_candidates": [] if passive else (hint_payload.get("contradiction_candidates") or []),
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


def get_session(
    db: DBSession,
    *,
    workspace_id: str,
    session_id: str,
    materialize: bool = True,
) -> ExpertCaptureSession:
    session = (
        db.query(ExpertCaptureSession)
        .filter(ExpertCaptureSession.id == session_id, ExpertCaptureSession.workspace_id == workspace_id)
        .first()
    )
    if not session:
        raise ValueError("Expert capture session not found")
    # Lazily rematerialize the transcript cache from the append-only ledger when a
    # silent capture turn deferred the rewrite. ``materialize=False`` keeps the
    # per-turn / per-partial hot paths from paying the rebuild (they do not need a
    # complete transcript and must never trigger the O(N) column rewrite).
    if materialize and _transcript_is_dirty(session):
        _materialize_committed_transcript(session, events=_list_turn_events(db, session.id))
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


def _count_proposal_open_questions(questions: Optional[List[Dict[str, Any]]]) -> int:
    """Count proposal questions still awaiting a decision (status ``open`` only)."""
    return len(
        [
            question
            for question in (questions or [])
            if isinstance(question, dict)
            and _normalize_proposal_open_question_status(question.get("status")) == "open"
        ]
    )


def _sync_session_proposal_open_questions_count(
    session: ExpertCaptureSession,
    questions: Optional[List[Dict[str, Any]]],
) -> None:
    count = _count_proposal_open_questions(questions)
    metrics = dict(session.metrics or {})
    metrics["open_questions_count"] = count
    metrics["proposal_open_questions_count"] = count
    session.metrics = metrics
    flag_modified(session, "metrics")


def _session_open_questions_count(session: ExpertCaptureSession) -> int:
    metrics = session.metrics or {}
    proposal_count = metrics.get("proposal_open_questions_count")
    if proposal_count is not None:
        try:
            return max(0, int(proposal_count))
        except (TypeError, ValueError):
            pass
    try:
        open_questions = build_open_questions(session)
    except Exception:
        return 0
    return len(
        [
            item
            for item in open_questions
            if item.get("status") not in {"addressed", "answered", "dismissed", "deferred", "invalid"}
        ]
    )


def _resolve_user_label(db: Optional[DBSession], user_id: Optional[str]) -> Optional[str]:
    """Best-effort display label (email/username) for a user id."""
    if not db or not user_id:
        return None
    try:
        from app.models.user import User

        user = db.query(User).filter(User.id == user_id).first()
    except Exception:
        return None
    if not user:
        return None
    return str(getattr(user, "email", None) or getattr(user, "username", None) or user_id)


def _session_created_by_label(session: ExpertCaptureSession) -> Optional[str]:
    user_id = getattr(session, "created_by_user_id", None)
    if not user_id:
        return None
    try:
        from sqlalchemy.orm import object_session

        db = object_session(session)
    except Exception:
        return None
    return _resolve_user_label(db, user_id)


def serialize_session(session: ExpertCaptureSession, *, surface: Optional[str] = None) -> Dict[str, Any]:
    # Sessions reached without ``get_session`` (e.g. list queries) may still carry a
    # deferred transcript: rebuild it from the ledger so every downstream read in
    # this serializer (summary, open-question count, turn_count, transcript) is exact.
    if _transcript_is_dirty(session):
        _materialize_committed_transcript(session)
    plan = dict(session.plan or {})
    if surface in {"plan_build", "plan"} or _is_plan_build_schema(plan):
        plan = _serialize_plan_for_ui(plan, surface=surface)
    timer_metrics = _compute_timer_metrics(session)
    summary_short = _session_summary_short(session)
    open_questions_count = _session_open_questions_count(session)
    last_activity = (session.updated_at or session.completed_at or session.started_at or session.created_at)
    # Lightweight scalar count of recorded conversation turns, mirroring the RAG
    # session ``message_count`` so unified admin views can show a single column.
    turn_count = len([turn for turn in (session.transcript or []) if isinstance(turn, dict)])
    return {
        "id": session.id,
        "workspace_id": session.workspace_id,
        "capability_id": session.capability_id,
        "context_id": session.context_id,
        "system_id": session.system_id,
        "run_id": session.run_id,
        "created_by_user_id": session.created_by_user_id,
        "created_by_label": _session_created_by_label(session),
        "title": session.title,
        "objective": session.objective,
        "turn_count": turn_count,
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
            **{k: v for k, v in (session.metrics or {}).items() if k != "transcript_dirty"},
            **timer_metrics,
            "summary_short": summary_short,
            "open_questions_count": open_questions_count,
            "last_activity": last_activity.isoformat() if last_activity else None,
        },
        "summary_short": summary_short,
        "open_questions_count": open_questions_count,
        "last_activity": last_activity.isoformat() if last_activity else None,
        "archived": session_is_archived(session),
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


def _count_open_questions(payload: Dict[str, Any]) -> int:
    count = 0
    for question in payload.get("open_questions") or []:
        if not isinstance(question, dict):
            continue
        status = str(question.get("status") or "open").lower()
        if status in {"open", "deferred", "active"}:
            count += 1
    return count


def _fiche_word_count(payload: Dict[str, Any]) -> int:
    recommended = dict(payload.get("recommended_ingestion") or {})
    content = recommended.get("content") or ""
    if not content:
        return 0
    return len(re.findall(r"\S+", str(content)))


def _published_at_sort_key(proposal: KnowledgeUpdateProposal) -> str:
    publication = dict((proposal.proposal or {}).get("publication") or {})
    reviewed_at = proposal.reviewed_at.isoformat() if proposal.reviewed_at else ""
    created_at = proposal.created_at.isoformat() if proposal.created_at else ""
    return str(publication.get("published_at") or reviewed_at or created_at or "")


def _user_display(users_by_id: Dict[str, Any], user_id: Optional[str]) -> Optional[Dict[str, str]]:
    if not user_id:
        return None
    user = users_by_id.get(user_id)
    if not user:
        return {"id": user_id, "label": user_id[:8]}
    label = getattr(user, "email", None) or getattr(user, "username", None) or user_id
    return {"id": user_id, "label": str(label)}


def _serialize_published_fiche(
    proposal: KnowledgeUpdateProposal,
    session: Optional[ExpertCaptureSession],
    *,
    users_by_id: Dict[str, Any],
    current_user_id: Optional[str] = None,
) -> Dict[str, Any]:
    payload = dict(proposal.proposal or {})
    publication = dict(payload.get("publication") or {})
    recommended = dict(payload.get("recommended_ingestion") or {})
    metadata = dict(recommended.get("metadata") or {})

    title = (
        _clean_optional_string(publication.get("final_title"))
        or _clean_optional_string(recommended.get("title"))
        or _clean_optional_string(payload.get("title"))
        or (session.title if session else None)
        or "Capture publication"
    )
    category = _clean_optional_string(publication.get("category")) or _clean_optional_string(
        metadata.get("publication_category")
    )
    destination = (
        _clean_optional_string(publication.get("destination"))
        or _clean_optional_string(publication.get("destination_scope"))
        or _clean_optional_string(publication.get("collection_slug"))
        or _clean_optional_string(metadata.get("publication_destination"))
    )
    collection_slug = (
        _clean_optional_string(publication.get("collection_slug"))
        or _clean_optional_string(metadata.get("collection_slug"))
        or destination
    )
    document_id = _clean_optional_string(publication.get("document_id")) or _clean_optional_string(
        metadata.get("document_id")
    )
    published_at = publication.get("published_at")
    chunks_processed = publication.get("chunks_processed") or metadata.get("chunks_processed") or 0

    author_user_id = (session.created_by_user_id if session else None) or proposal.created_by_user_id
    published_by_user_id = proposal.reviewer_user_id or author_user_id

    export_urls = dict(publication.get("export_urls") or {})
    raw_url = export_urls.get("raw_url") or export_urls.get("download_url")
    if not raw_url and document_id:
        raw_url = f"/api/v1/documents/{quote(str(document_id), safe='')}/raw"

    preview_url = None
    if document_id and collection_slug:
        filename = (
            _clean_optional_string(publication.get("filename"))
            or _clean_optional_string(metadata.get("publication_filename"))
            or f"capture-{(session.id[:8] if session else proposal.session_id[:8])}.md"
        )
        preview_url = (
            f"documents/{quote(str(document_id), safe='')}/rich-preview"
            f"?collection_name={quote(str(collection_slug), safe='')}"
            f"&filename={quote(filename, safe='')}"
        )

    session_owner_user_id = session.created_by_user_id if session else None

    return {
        "id": proposal.id,
        "proposal_id": proposal.id,
        "title": title,
        "category": category,
        "destination": destination,
        "collection_slug": collection_slug,
        "published_at": published_at,
        "published_by": _user_display(users_by_id, published_by_user_id),
        "author": _user_display(users_by_id, author_user_id),
        "capture_session_id": proposal.session_id,
        "session_title": session.title if session else None,
        "document_id": document_id,
        "word_count": _fiche_word_count(payload),
        "chunks_processed": int(chunks_processed or 0),
        "open_questions_count": _count_open_questions(payload),
        "export_urls": export_urls,
        "preview_url": preview_url,
        "raw_url": raw_url,
        "session_owned_by_current_user": bool(
            current_user_id and session_owner_user_id and current_user_id == session_owner_user_id
        ),
    }


def list_published_fiches(
    db: DBSession,
    *,
    workspace_id: str,
    current_user_id: Optional[str] = None,
    category: Optional[str] = None,
    destination: Optional[str] = None,
    author_user_id: Optional[str] = None,
    published_after: Optional[str] = None,
    published_before: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> Dict[str, Any]:
    rows = (
        db.query(KnowledgeUpdateProposal, ExpertCaptureSession)
        .join(ExpertCaptureSession, ExpertCaptureSession.id == KnowledgeUpdateProposal.session_id)
        .filter(
            KnowledgeUpdateProposal.workspace_id == workspace_id,
            KnowledgeUpdateProposal.status == "published",
        )
        .all()
    )
    rows.sort(key=lambda item: _published_at_sort_key(item[0]), reverse=True)

    category_key = (category or "").strip().lower()
    destination_key = (destination or "").strip().lower()
    author_key = (author_user_id or "").strip()
    needle = (q or "").strip().lower()

    filtered: List[Tuple[KnowledgeUpdateProposal, ExpertCaptureSession]] = []
    for proposal, session in rows:
        payload = dict(proposal.proposal or {})
        publication = dict(payload.get("publication") or {})
        recommended = dict(payload.get("recommended_ingestion") or {})
        metadata = dict(recommended.get("metadata") or {})
        title = (
            _clean_optional_string(publication.get("final_title"))
            or _clean_optional_string(recommended.get("title"))
            or _clean_optional_string(payload.get("title"))
            or session.title
            or ""
        )
        row_category = (
            _clean_optional_string(publication.get("category"))
            or _clean_optional_string(metadata.get("publication_category"))
            or ""
        ).lower()
        row_destination = (
            _clean_optional_string(publication.get("destination"))
            or _clean_optional_string(publication.get("destination_scope"))
            or _clean_optional_string(publication.get("collection_slug"))
            or _clean_optional_string(metadata.get("publication_destination"))
            or ""
        ).lower()
        row_author_id = session.created_by_user_id or proposal.created_by_user_id or ""
        published_at = str(publication.get("published_at") or "")

        if category_key and row_category != category_key:
            continue
        if destination_key and destination_key not in row_destination:
            continue
        if author_key and row_author_id != author_key:
            continue
        if published_after and published_at and published_at < published_after:
            continue
        if published_before and published_at and published_at > published_before:
            continue
        if needle:
            haystack = " ".join([title, row_category, row_destination, session.title or ""]).lower()
            if needle not in haystack:
                continue
        filtered.append((proposal, session))

    total = len(filtered)
    page = filtered[offset : offset + limit]

    user_ids = set()
    for proposal, session in page:
        if session.created_by_user_id:
            user_ids.add(session.created_by_user_id)
        if proposal.created_by_user_id:
            user_ids.add(proposal.created_by_user_id)
        if proposal.reviewer_user_id:
            user_ids.add(proposal.reviewer_user_id)

    users_by_id: Dict[str, Any] = {}
    if user_ids:
        from app.models.user import User

        for user in db.query(User).filter(User.id.in_(user_ids)).all():
            users_by_id[user.id] = user

    fiches = [
        _serialize_published_fiche(proposal, session, users_by_id=users_by_id, current_user_id=current_user_id)
        for proposal, session in page
    ]
    return {
        "fiches": fiches,
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": offset + len(fiches) < total,
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


# The append-only event ledger is the source of truth for the conversation turns.
# These finalized rows carry everything ``append_turn`` needs to rematerialize the
# ``session.transcript`` JSON column, so a committed capture turn no longer has to
# rewrite the whole growing column every turn (the O(N^2) hot path).
_TURN_EVENT_TYPES = ("expert_turn_finalized", "transcript_turn_recorded")


def _transcript_is_dirty(session: ExpertCaptureSession) -> bool:
    """True when a silent capture turn deferred the transcript rewrite — the column
    is stale and must be rebuilt from the event ledger before it is read."""
    return bool((session.metrics or {}).get("transcript_dirty"))


def _set_transcript_dirty(session: ExpertCaptureSession, value: bool) -> None:
    metrics = dict(session.metrics or {})
    if value:
        if metrics.get("transcript_dirty") is True:
            return
        metrics["transcript_dirty"] = True
    else:
        if "transcript_dirty" not in metrics:
            return
        metrics.pop("transcript_dirty", None)
    session.metrics = metrics
    flag_modified(session, "metrics")


def _list_turn_events(db: DBSession, session_id: str) -> List[ExpertCaptureEvent]:
    return (
        db.query(ExpertCaptureEvent)
        .filter(
            ExpertCaptureEvent.session_id == session_id,
            ExpertCaptureEvent.event_type.in_(_TURN_EVENT_TYPES),
        )
        .order_by(ExpertCaptureEvent.sequence.asc(), ExpertCaptureEvent.created_at.asc())
        .all()
    )


def _transcript_from_events(events: Iterable[ExpertCaptureEvent]) -> List[Dict[str, Any]]:
    """Rebuild the ordered transcript turn list from the capture event ledger.

    The turn dict mirrors exactly what ``append_turn`` materializes (same keys,
    same shape) so every reader observes an identical transcript whether the
    column was written eagerly or rebuilt lazily. Amendments are reflected because
    the finalized event itself carries ``text_amended`` once an operator edits it.
    """
    turns: List[Dict[str, Any]] = []
    for event in events:
        if event.event_type not in _TURN_EVENT_TYPES:
            continue
        meta = event.meta_data or {}
        amended = event.text_amended
        turn = {
            "id": meta.get("turn_id") or event.id,
            "speaker": event.speaker,
            "text": (amended.strip() if amended else (event.text_raw or "")),
            "question_id": event.question_id,
            "topic_id": meta.get("topic_id"),
            "subtopic_id": meta.get("subtopic_id"),
            "topic_path": meta.get("topic_path"),
            "audio_ref": event.audio_ref,
            "client_turn_id": meta.get("client_turn_id"),
            "retrieval_event_id": meta.get("retrieval_event_id"),
            "retrieval_refs": meta.get("retrieval_refs") or [],
            "interruption_of_event_id": meta.get("interruption_of_event_id"),
            "turn_kind": meta.get("turn_kind") or "answer",
            "input_modality": meta.get("input_modality") or "voice",
            "document_refs": meta.get("document_refs") or [],
            "visual_context": meta.get("visual_context"),
            "timecode_ms": meta.get("timecode_ms"),
            "text_partials": meta.get("text_partials") or [],
            "latency_ms": meta.get("latency_ms") or {},
            "created_at": event.created_at.isoformat() if event.created_at else None,
            "source_event_id": event.id,
            "text_raw": event.text_raw,
            "text_status": event.status,
        }
        if amended:
            turn["text_amended"] = amended
        turns.append(turn)
    return turns


_FEED_EVENT_TYPES = (*_TURN_EVENT_TYPES, "capture_view_referenced")


def _capture_feed_view_ref(event: ExpertCaptureEvent, meta: Dict[str, Any]) -> Dict[str, Any]:
    """Shape a journaled ``capture_view_referenced`` event into the anchor view
    ref the Fil timeline binds to (mirrors the realtime WS / HTTP push shape)."""
    confidence = meta.get("confidence")
    if confidence is None and event.confidence is not None:
        try:
            confidence = float(event.confidence)
        except (TypeError, ValueError):
            confidence = None
    collection = meta.get("collection") or meta.get("collection_name")
    return {
        "session_id": event.session_id,
        "event_id": event.id,
        "document_id": meta.get("document_id"),
        "collection": collection,
        "collection_name": collection,
        "filename": meta.get("filename"),
        "title": meta.get("title"),
        "page": meta.get("page"),
        "slide": meta.get("slide"),
        "image_index": meta.get("image_index"),
        "turn_id": meta.get("turn_id"),
        "timecode_ms": meta.get("timecode_ms"),
        "statement": meta.get("statement"),
        "trigger_phrase": meta.get("trigger_phrase"),
        "status": meta.get("status") or "confirmed",
        "confidence": confidence,
        "view_kind": meta.get("view_kind"),
        "association_mode": meta.get("association_mode"),
    }


def build_capture_feed(
    db: DBSession,
    *,
    workspace_id: str,
    session_id: str,
) -> List[Dict[str, Any]]:
    """Project the append-only event ledger into the ordered "Le Fil" feed (D1
    step C): one typed entry per ``speak`` (voice turn) / ``note`` (text turn) /
    ``anchor`` (deictic ``capture_view_referenced``) event, carrying the anchor
    status/confidence. The Fil hydrates from this on session load/resume, then
    keeps appending live WS events (WS stays the live source of truth)."""
    rows = (
        db.query(ExpertCaptureEvent)
        .filter(
            ExpertCaptureEvent.workspace_id == workspace_id,
            ExpertCaptureEvent.session_id == session_id,
            ExpertCaptureEvent.event_type.in_(_FEED_EVENT_TYPES),
        )
        .order_by(ExpertCaptureEvent.sequence.asc(), ExpertCaptureEvent.created_at.asc())
        .all()
    )
    turn_channel: Dict[str, str] = {}
    feed: List[Dict[str, Any]] = []
    for event in rows:
        meta = event.meta_data or {}
        ts_ms = int(event.created_at.timestamp() * 1000) if event.created_at else None
        if event.event_type in _TURN_EVENT_TYPES:
            channel = "text" if (meta.get("input_modality") or "voice") == "text" else "voice"
            turn_channel[event.id] = channel
            text = _effective_event_text(event)
            if not text:
                continue
            turn_id = meta.get("turn_id") or event.id
            feed.append(
                {
                    "id": turn_id,
                    "kind": "note" if channel == "text" else "speak",
                    "channel": channel,
                    "speaker": event.speaker,
                    "text": text,
                    "partial": False,
                    "ts_ms": ts_ms,
                    "seq": event.sequence,
                    "turn_id": turn_id,
                    "event_id": event.id,
                }
            )
        else:
            view = _capture_feed_view_ref(event, meta)
            channel = turn_channel.get(event.parent_event_id or "", "voice")
            feed.append(
                {
                    "id": event.id,
                    "kind": "anchor",
                    "channel": channel,
                    "speaker": event.speaker,
                    "text": (
                        view.get("statement")
                        or view.get("trigger_phrase")
                        or view.get("title")
                        or view.get("filename")
                        or "view referenced"
                    ),
                    "partial": False,
                    "ts_ms": ts_ms,
                    "seq": event.sequence,
                    "turn_id": meta.get("turn_id"),
                    "event_id": event.id,
                    "view": view,
                }
            )
    return feed


def _read_transcript(
    session: ExpertCaptureSession,
    *,
    events: Optional[Iterable[ExpertCaptureEvent]] = None,
) -> List[Dict[str, Any]]:
    """Correct transcript for a reader without mutating the session. Cheap (the
    cached column) unless a silent turn deferred the rewrite, in which case it is
    rebuilt from the supplied/related event ledger."""
    if not _transcript_is_dirty(session):
        return session.transcript or []
    rows = events
    if rows is None:
        try:
            rows = session.events
        except Exception:
            return session.transcript or []
    return _transcript_from_events(rows)


def _materialize_committed_transcript(
    session: ExpertCaptureSession,
    *,
    events: Optional[Iterable[ExpertCaptureEvent]] = None,
) -> List[Dict[str, Any]]:
    """Refresh the in-memory ``session.transcript`` from the ledger WITHOUT marking
    it dirty for SQLAlchemy (no per-read write). Used by read seams (``get_session``,
    ``serialize_session``) so raw ``session.transcript`` access is correct again."""
    rows = events
    if rows is None:
        try:
            rows = session.events
        except Exception:
            return session.transcript or []
    turns = _transcript_from_events(rows)
    set_committed_value(session, "transcript", turns)
    return turns


def _persist_materialized_transcript(
    db: DBSession,
    session: ExpertCaptureSession,
    *,
    events: Optional[Iterable[ExpertCaptureEvent]] = None,
) -> None:
    """Write the ledger-derived transcript back to the column and clear the deferred
    flag so the cache and the source of truth agree again (at section/finalize
    boundaries). No-op when the column is already in sync."""
    if not _transcript_is_dirty(session):
        return
    rows = events if events is not None else _list_turn_events(db, session.id)
    session.transcript = _transcript_from_events(rows)
    flag_modified(session, "transcript")
    _set_transcript_dirty(session, False)


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
    # ``transcript`` was materialized in full by ``get_session`` before this edit,
    # so the cache now reflects every committed turn plus the amendment.
    _set_transcript_dirty(session, False)


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
            # ``changes_requested`` proposals are reopened on re-finalize instead
            # of spawning a duplicate row; accepted/rejected/published stay
            # untouched (a new revision there is intended behaviour).
            KnowledgeUpdateProposal.status.in_(("pending_review", "changes_requested")),
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


def session_has_proposal_material(db: DBSession, *, workspace_id: str, session: ExpertCaptureSession) -> bool:
    return _session_has_proposal_material(db, workspace_id=workspace_id, session=session)


def _resolve_collection_name(ctx: Optional[Context]) -> str:
    state = (ctx.environment_state or {}) if ctx else {}
    collection = state.get("collection") or state.get("collection_name") or state.get("rag_collection")
    return str(collection).strip() if collection else "documents"


def _default_publication_collection(db: DBSession, workspace: Any, ctx: Optional[Context]) -> str:
    """Default publish destination for capture fiches — parity with chat corrections.

    Chat expert corrections default their destination to
    :func:`resolve_expert_fiche_collection` over the workspace chat
    ``source_policy`` (the exact collection ``_include_expert_fiche_collection``
    folds into the chat-recherche searched set). Capture publications reuse the
    same resolution so a fiche published without an explicit destination lands
    where the chat recherche actually looks. When the workspace has not enabled
    ``expert_fiche_correction_enabled`` that collection is never queried by
    chat, so the previous behavior (the capture context collection) is kept.
    """
    try:
        from app.services.systems.bootstrap import resolve_workspace_chat_source_policy

        source_policy = resolve_workspace_chat_source_policy(db, workspace)
        if source_policy.get("expert_fiche_correction_enabled"):
            slug = resolve_expert_fiche_collection(workspace, source_policy)
            if slug:
                return slug
    except Exception:  # pragma: no cover - defensive: never block publication
        _logger.warning("capture_publish.default_collection_resolution_failed", exc_info=True)
    return _resolve_collection_name(ctx)


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
                "title": _source_display_title(md),
                "source": md.get("source") or _source_display_filename(md) or md.get("document_id"),
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
        if not subtopics:
            topic_prompt = str(topic.get("prompt") or "").strip() or broad_presentation_prompt(topic_title)
            questions.append(
                {
                    "id": f"{topic_id}-present" if topic_id else None,
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
        elif subtopics and topic_is_outline:
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
