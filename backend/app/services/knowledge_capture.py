"""Expert knowledge capture planning, session runtime and review output."""
from __future__ import annotations

import re
import asyncio
import time
import uuid
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

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

CAPABILITY_SLUG = "expert_knowledge_capture"
RETRIEVAL_PREFETCH_TIMEOUT_SECONDS = 2.5
POSITIVE_CONFIRMATION_TERMS = (
    "oui",
    "valide",
    "confirme",
    "c'est bon",
    "c est bon",
    "go",
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
    "on peut conclure",
)
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
    return sorted(gaps, key=lambda item: item["priority"], reverse=True)


def build_interview_plan(
    *,
    objective: str,
    expert_profile: Optional[str],
    duration_minutes: int,
    gaps: List[Dict[str, Any]],
    context_snapshot: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    duration = max(5, min(int(duration_minutes or 20), 90))
    available_question_minutes = max(3, duration - 4)
    question_count = max(2, min(len(gaps), available_question_minutes // 3 or 2))
    selected = gaps[:question_count]
    per_question = max(2, available_question_minutes // max(1, len(selected)))

    questions: List[Dict[str, Any]] = []
    for index, gap in enumerate(selected, start=1):
        questions.append(
            {
                "id": f"q-{index:02d}",
                "target_gap_id": gap["id"],
                "title": gap["title"],
                "question": _question_for_gap(gap, objective),
                "follow_ups": _followups_for_gap(gap),
                "estimated_minutes": per_question,
                "completion_criteria": [
                    "answer names a concrete situation or decision",
                    "answer explains the why, not only the what",
                    "answer identifies evidence, owner, or validation path when possible",
                ],
            }
        )

    return {
        "objective": objective,
        "expert_profile": expert_profile,
        "duration_minutes": duration,
        "voice_runtime": "cascade",
        "agenda": [
            {"label": "Frame objective and scope", "estimated_minutes": 2},
            {"label": "Resolve prioritized knowledge gaps", "estimated_minutes": available_question_minutes},
            {"label": "Confirm open questions and validation owner", "estimated_minutes": 2},
        ],
        "questions": questions,
        "context": context_snapshot or {},
        "success_metrics": [
            "coverage of prioritized gaps",
            "number of usable captured facts",
            "manual transcript correction rate",
            "estimated vs actual duration",
        ],
    }


def _question_for_gap(gap: Dict[str, Any], objective: str) -> str:
    title = gap.get("title", "Knowledge gap")
    if gap.get("slug") == "decision_rationale":
        return f"Pour l’objectif « {objective} », quelle décision experte est difficile à retrouver dans la documentation, et pourquoi ?"
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

    follow_up = None
    if verdict != "sufficient":
        follow_up = _select_follow_up(question, has_reason=has_reason, has_example=has_example, has_source=has_source)

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
        "follow_up": follow_up,
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
    active_proposal = last_proposal if last_proposal and last_proposal.status == "pending_review" else None
    proposal_confirmed = _proposal_conversation_confirmed(active_proposal)

    if active_proposal and has_positive:
        intent = "accept_confirmed" if proposal_confirmed else "proposal_confirmed"
        return {"intent": intent, "confidence": 0.92, "signals": {"proposal_confirmed": proposal_confirmed}}
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
    if not clean:
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
        r"\b(?:crée|cree|prépare|prepare)\s+la\s+proposition\b.*$",
        r"\bon\s+peut\s+(?:faire|créer|creer)\s+une\s+proposition\b.*$",
        r"\bje\s+pense\s+qu['’]?\s*on\s+peut\s+.*proposition\b.*$",
        r"\bon\s+peut\s+conclure\b.*$",
        r"\b(?:synthèse|synthese)\b.*$",
    ]
    for pattern in proposal_patterns:
        out = re.sub(pattern, "", out, flags=re.IGNORECASE).strip(" ,;:")
    return out


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
    action_taken = "none"
    next_prompt: Optional[str] = None
    proposal: Optional[KnowledgeUpdateProposal] = None
    requires_confirmation = False
    confirmation_target: Optional[str] = None
    turn_payload: Optional[Dict[str, Any]] = None

    if intent in {"answer_ready", "correction", "more_detail"}:
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
            )
        session = get_session(db, workspace_id=workspace_id, session_id=session_id)
        if _session_has_proposal_material(db, workspace_id=workspace_id, session=session):
            proposal = create_update_proposal(db, workspace_id=workspace_id, session_id=session_id, complete_session=False)
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
        proposal = review_proposal(
            db,
            workspace_id=workspace_id,
            proposal_id=last_proposal.id,
            status="accepted",
            reviewer="conversation-only",
            review_notes="Accepted by explicit voice confirmation.",
        )
        action_taken = "proposal_accepted"
        next_prompt = "La proposition est acceptée."
    elif intent == "accept_rejected":
        proposal = last_proposal
        action_taken = "acceptance_rejected"
        next_prompt = "D’accord, je ne valide pas encore. Indiquez ce qu’il faut corriger."

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
    markdown = _proposal_markdown(session, captured, open_questions)
    return {
        "session_id": session.id,
        "title": session.title,
        "objective": session.objective,
        "context_id": session.context_id,
        "captured_facts": captured,
        "open_questions": open_questions,
        "transcript": transcript,
        "transcript_events": event_evidence,
        "amendments": amendments,
        "recommended_ingestion": {
            "title": f"Expert capture - {session.title}",
            "content": markdown,
            "metadata": {
                "source": "expert_capture_session",
                "session_id": session.id,
                "voice_runtime": session.voice_runtime,
                "event_count": len(event_evidence),
                "amendment_count": len(amendments),
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
    duration_minutes: int,
    context_id: Optional[str],
    system_id: Optional[str],
    knowledge_refs: Optional[List[str]],
    voice_runtime: str = "cascade",
) -> ExpertCaptureSession:
    ctx = _load_context(db, workspace_id, context_id)
    snapshot = _context_snapshot(ctx)
    gaps = build_knowledge_gaps(
        objective=objective,
        expert_profile=expert_profile,
        context_snapshot=snapshot,
        knowledge_refs=knowledge_refs,
    )
    plan = build_interview_plan(
        objective=objective,
        expert_profile=expert_profile,
        duration_minutes=duration_minutes,
        gaps=gaps,
        context_snapshot=snapshot,
    )
    plan["knowledge_refs"] = knowledge_refs or []
    plan["voice_runtime"] = voice_runtime

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
    session = ExpertCaptureSession(
        id=str(uuid.uuid4()),
        workspace_id=workspace_id,
        capability_id=capability.id if capability else None,
        context_id=context_id,
        system_id=resolved_system_id,
        title=title or "Expert Knowledge Capture",
        objective=objective,
        expert_profile=expert_profile,
        duration_minutes=duration_minutes,
        voice_runtime=voice_runtime,
        status="planned",
        plan=plan,
        knowledge_gaps=gaps,
        metrics={"estimated_minutes": duration_minutes, "coverage": 0.0},
    )
    db.add(session)
    db.flush()
    run_id = _record_capture_run(
        db,
        workspace_id=workspace_id,
        capability_id=session.capability_id,
        trigger="knowledge_capture_plan",
        input_ref={"objective": objective, "duration_minutes": duration_minutes, "context_id": context_id},
        output_ref={"plan": plan, "knowledge_gaps": gaps},
        skill_slugs=["knowledge_gap_analysis_v1", "expert_interview_plan_v1"],
    )
    session.run_id = run_id
    _record_capture_event(
        db,
        session=session,
        event_type="capture_plan_created",
        source="capture_engine",
        status="accepted",
        meta_data={"run_id": run_id, "question_count": len(plan.get("questions") or [])},
    )
    db.commit()
    db.refresh(session)
    return session


def start_session(db: DBSession, *, workspace_id: str, session_id: str) -> ExpertCaptureSession:
    session = get_session(db, workspace_id=workspace_id, session_id=session_id)
    if session.status == "planned":
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
) -> Dict[str, Any]:
    session = get_session(db, workspace_id=workspace_id, session_id=session_id)
    if session.status == "planned":
        session.status = "active"
        session.started_at = session.started_at or datetime.utcnow()

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
            meta_data={"client_turn_id": client_turn_id, "turn_kind": turn_kind},
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
            meta_data={"client_turn_id": client_turn_id, "turn_kind": turn_kind},
        )

    turn = {
        "id": client_turn_id or str(uuid.uuid4()),
        "speaker": speaker,
        "text": text,
        "question_id": question_id,
        "audio_ref": audio_ref,
        "client_turn_id": client_turn_id,
        "retrieval_event_id": retrieval_event_id,
        "retrieval_refs": retrieval_refs,
        "interruption_of_event_id": interruption_of_event_id,
        "turn_kind": turn_kind,
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
        meta_data={
            "turn_id": turn["id"],
            "client_turn_id": client_turn_id,
            "retrieval_event_id": retrieval_event_id,
            "retrieval_refs": retrieval_refs,
            "interruption_of_event_id": interruption_of_event_id,
            "turn_kind": turn_kind,
        },
    )
    turn["source_event_id"] = event.id
    turn["text_raw"] = text
    turn["text_status"] = event.status
    transcript = list(session.transcript or [])
    transcript.append(turn)
    session.transcript = transcript

    evaluation: Optional[Dict[str, Any]] = None
    next_prompt: Optional[str] = None
    next_question: Optional[Dict[str, Any]] = None
    system_prompt_event_id: Optional[str] = None
    if speaker == "expert":
        question = _find_question(session.plan or {}, question_id)
        gap = _find_gap(session.knowledge_gaps or [], (question or {}).get("target_gap_id"))
        evaluation = evaluate_expert_answer(answer=text, question=question, gap=gap)
        evaluation["turn_id"] = turn["id"]
        evaluation["retrieval_event_id"] = retrieval_event_id
        evaluation["turn_kind"] = turn_kind

        evaluations = list(session.evaluations or [])
        evaluations.append(evaluation)
        session.evaluations = evaluations

        if evaluation["verdict"] == "sufficient":
            captured = list(session.captured_facts or [])
            captured.append(_fact_from_turn(turn, evaluations))
            session.captured_facts = captured
            next_question = _next_plan_question(session.plan or {}, evaluations)
            next_prompt = (next_question or {}).get("question")
        else:
            next_question = question
            next_prompt = evaluation.get("follow_up")
        session.metrics = _metrics_for_session(session)

        _record_capture_run(
            db,
            workspace_id=workspace_id,
            capability_id=session.capability_id,
            trigger="knowledge_capture_turn",
            input_ref={"session_id": session.id, "turn": turn},
            output_ref={"evaluation": evaluation, "next_prompt": next_prompt},
            skill_slugs=["expert_answer_evaluator_v1"],
        )
        if next_prompt:
            prompt_event = _record_capture_event(
                db,
                session=session,
                event_type="system_prompt_prepared",
                speaker="system",
                question_id=(next_question or {}).get("id") or question_id,
                text_raw=next_prompt,
                source="capture_engine",
                status="accepted",
                parent_event_id=event.id,
                meta_data={
                    "trigger_turn_id": turn["id"],
                    "client_turn_id": client_turn_id,
                    "retrieval_event_id": retrieval_event_id,
                    "turn_kind": turn_kind,
                },
            )
            system_prompt_event_id = prompt_event.id

    db.commit()
    db.refresh(session)
    return {
        "session": serialize_session(session),
        "turn": turn,
        "evaluation": evaluation,
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
) -> KnowledgeUpdateProposal:
    session = get_session(db, workspace_id=workspace_id, session_id=session_id)
    events = list_capture_events(db, workspace_id=workspace_id, session_id=session_id)
    payload = structure_capture_payload(session, events)
    proposal = _latest_pending_proposal_for_session(db, workspace_id=workspace_id, session_id=session_id)
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
        )
        db.add(proposal)
    if complete_session:
        session.status = "completed"
        session.completed_at = datetime.utcnow()
    db.flush()
    _record_capture_event(
        db,
        session=session,
        event_type="proposal_generated",
        source="capture_engine",
        status="accepted",
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
            meta_data={"proposal_id": proposal.id, "review_notes": review_notes},
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

    partial_event = _record_capture_event(
        db,
        session=session,
        event_type="stt_partial",
        speaker="expert",
        question_id=question_id,
        text_raw=text,
        source="browser_voice",
        status="accepted",
        meta_data={"client_turn_id": client_turn_id, "words": len(_words(text))},
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
        meta_data={"client_turn_id": client_turn_id, "mode": mode, "top_k": top_k},
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
        from app.services.rag.document_service import DocumentService
        from app.services.rag.pipeline_retrieval import retrieve_for_mode

        doc_svc = DocumentService(collection_name=collection_name, workspace_slug=workspace_slug)
        result = await asyncio.wait_for(
            retrieve_for_mode(
                doc_svc,
                text,
                mode,
                top_k=max(1, min(top_k, 8)),
                use_hybrid=True,
                hah_chah_enabled=True,
            ),
            timeout=timeout_seconds,
        )
        chunks = result.chunks
        scores = result.scores
        metadatas = result.metadatas
        detail = {"pipeline": result.pipeline, "label": result.label, "reason": result.reason, "detail": result.detail}
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
            **detail,
        },
    )
    db.commit()
    db.refresh(final_event)
    return {
        "event_id": final_event.id,
        "status": status,
        "latency_ms": latency_ms,
        "chunks": chunks,
        "scores": scores,
        "metadatas": metadatas,
        "stale": False,
        "collection_name": collection_name,
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


def serialize_session(session: ExpertCaptureSession) -> Dict[str, Any]:
    return {
        "id": session.id,
        "workspace_id": session.workspace_id,
        "capability_id": session.capability_id,
        "context_id": session.context_id,
        "system_id": session.system_id,
        "run_id": session.run_id,
        "title": session.title,
        "objective": session.objective,
        "expert_profile": session.expert_profile,
        "duration_minutes": session.duration_minutes,
        "voice_runtime": session.voice_runtime,
        "status": session.status,
        "plan": session.plan or {},
        "knowledge_gaps": session.knowledge_gaps or [],
        "transcript": session.transcript or [],
        "evaluations": session.evaluations or [],
        "captured_facts": session.captured_facts or [],
        "metrics": session.metrics or {},
        "started_at": session.started_at.isoformat() if session.started_at else None,
        "completed_at": session.completed_at.isoformat() if session.completed_at else None,
        "created_at": session.created_at.isoformat() if session.created_at else None,
        "updated_at": session.updated_at.isoformat() if session.updated_at else None,
    }


def serialize_proposal(proposal: KnowledgeUpdateProposal) -> Dict[str, Any]:
    return {
        "id": proposal.id,
        "workspace_id": proposal.workspace_id,
        "session_id": proposal.session_id,
        "status": proposal.status,
        "proposal": proposal.proposal or {},
        "review_notes": proposal.review_notes,
        "reviewer": proposal.reviewer,
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


def _find_question(plan: Dict[str, Any], question_id: Optional[str]) -> Optional[Dict[str, Any]]:
    questions = plan.get("questions") or []
    if question_id:
        return next((q for q in questions if q.get("id") == question_id), None)
    return questions[0] if questions else None


def _find_gap(gaps: List[Dict[str, Any]], gap_id: Optional[str]) -> Optional[Dict[str, Any]]:
    if not gap_id:
        return None
    return next((gap for gap in gaps if gap.get("id") == gap_id), None)


def _next_plan_question(plan: Dict[str, Any], evaluations: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    sufficiently_answered = {
        ev.get("question_id") for ev in evaluations if ev.get("verdict") == "sufficient"
    }
    for question in plan.get("questions") or []:
        if question.get("id") not in sufficiently_answered:
            return question
    return {
        "id": None,
        "question": "Nous avons couvert le plan principal. Quelles zones d’incertitude souhaitez-vous ajouter avant la synthèse ?",
    }


def _metrics_for_session(session: ExpertCaptureSession) -> Dict[str, Any]:
    evaluations = session.evaluations or []
    sufficient = [ev for ev in evaluations if ev.get("verdict") == "sufficient"]
    questions = (session.plan or {}).get("questions") or []
    coverage = len({ev.get("question_id") for ev in sufficient}) / max(1, len(questions))
    return {
        **(session.metrics or {}),
        "turns": len(session.transcript or []),
        "answers_evaluated": len(evaluations),
        "captured_facts": len(session.captured_facts or []),
        "coverage": round(coverage, 2),
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
) -> str:
    now = datetime.utcnow()
    run = Run(
        id=str(uuid.uuid4()),
        workspace_id=workspace_id,
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
