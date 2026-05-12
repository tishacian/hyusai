"""Canonical System seed hooks.

`/intelligence` is no longer a bespoke feature page: it is a real ``System``
row bound to the ``market_signal_brief`` capability, so the frontend can
use the same SystemViewComponent to render it with the intelligence-specific
facets. This module provides the idempotent seeding hook called at startup
for every existing workspace (Vague A — P0, commit 2/5).
"""
from __future__ import annotations

from typing import Dict, List, Optional

from sqlalchemy.orm import Session as DBSession

from app.core.logging import get_logger
from app.models.capability import Capability
from app.models.skill import Skill
from app.models.system import System
from app.models.workspace import Workspace

logger = get_logger(__name__)


INTELLIGENCE_SYSTEM_NAME = "News Lab"
INTELLIGENCE_OBJECTIVE = (
    "Continuous market intelligence tuned to your semantic targets. "
    "The scheduler harvests RSS feeds every hour, scores articles against "
    "your targets, and surfaces decision-grade briefs."
)
INTELLIGENCE_CAPABILITY_SLUG = "market_signal_brief"
INTELLIGENCE_SKILL_SLUG = "intelligence_batch_v1"

EXPERT_CAPTURE_SYSTEM_NAME = "Expert Knowledge Capture"
EXPERT_CAPTURE_OBJECTIVE = (
    "Run guided voice-to-voice expert interviews, retrieve live Knowledge context, "
    "evaluate each answer, and produce HITL-reviewable knowledge update proposals."
)
EXPERT_CAPTURE_CAPABILITY_SLUG = "expert_knowledge_capture"
EXPERT_CAPTURE_SKILL_SLUGS = [
    "knowledge_gap_analysis_v1",
    "expert_interview_plan_v1",
    "voice_realtime_session_v1",
    "voice_realtime_transcribe_v1",
    "voice_transcribe_v1",
    "semantic_search_v1",
    "expert_answer_evaluator_v1",
    "voice_oracle_turn_v1",
    "voice_tandem_oracle_v1",
    "voice_realtime_speak_v1",
    "capture_structuring_v1",
    "voice_tts_v1",
    "audit_log_v1",
]


def ensure_intelligence_system_default(
    db: DBSession, workspace_id: str
) -> Optional[System]:
    """Create the workspace's default Intelligence System if missing.

    Idempotent on ``(workspace_id, capability_id, name=INTELLIGENCE_SYSTEM_NAME)``.
    Returns the (existing or newly created) System, or ``None`` if the
    required capability/skill haven't been seeded yet.
    """
    capability = (
        db.query(Capability)
        .filter(Capability.slug == INTELLIGENCE_CAPABILITY_SLUG)
        .first()
    )
    if not capability:
        logger.warning(
            "intel_system_seed.skip.missing_capability",
            workspace_id=workspace_id,
            slug=INTELLIGENCE_CAPABILITY_SLUG,
        )
        return None

    skill = (
        db.query(Skill).filter(Skill.slug == INTELLIGENCE_SKILL_SLUG).first()
    )
    skill_ids: List[str] = [skill.id] if skill else []

    existing = (
        db.query(System)
        .filter(
            System.workspace_id == workspace_id,
            System.capability_id == capability.id,
            System.name == INTELLIGENCE_SYSTEM_NAME,
        )
        .first()
    )
    if existing:
        # Lightweight refresh so flow_definition.variant stays in sync even
        # if an older seed produced a bare row.
        flow = dict(existing.flow_definition or {})
        if flow.get("variant") != "intelligence":
            flow["variant"] = "intelligence"
            flow.setdefault("nodes", [])
            flow.setdefault("edges", [])
            existing.flow_definition = flow
            db.commit()
        return existing

    flow_definition: Dict[str, object] = {
        "variant": "intelligence",
        "nodes": [
            {
                "id": "source.feeds",
                "type": "source",
                "label": "RSS feeds",
            },
            {
                "id": "skill.intelligence_batch_v1",
                "type": "skill",
                "skill_slug": INTELLIGENCE_SKILL_SLUG,
                "label": "Intelligence batch",
            },
            {
                "id": "sink.brief",
                "type": "sink",
                "label": "Decision-grade brief",
            },
        ],
        "edges": [
            {"from": "source.feeds", "to": "skill.intelligence_batch_v1"},
            {"from": "skill.intelligence_batch_v1", "to": "sink.brief"},
        ],
    }

    system = System(
        workspace_id=workspace_id,
        name=INTELLIGENCE_SYSTEM_NAME,
        objective=INTELLIGENCE_OBJECTIVE,
        capability_id=capability.id,
        skill_ids=skill_ids,
        flow_definition=flow_definition,
        execution_mode="continuous_monitoring",
        coordination_pattern="single_agent",
        status="active",
        created_by="system:intelligence_seed",
        retrieval_mode_default="auto",
    )
    db.add(system)
    db.commit()
    db.refresh(system)

    logger.info(
        "intel_system_seed.created",
        workspace_id=workspace_id,
        system_id=system.id,
        capability_id=capability.id,
    )
    return system


def ensure_intelligence_system_for_all_workspaces(
    db: DBSession,
) -> Dict[str, int]:
    """Ensure every active workspace has its Intelligence System seeded.

    Safe to call on every boot — the per-workspace helper is idempotent.
    Returns a small report (``{"created": N, "skipped": M}``) so the startup
    log stays readable.
    """
    report = {"created": 0, "skipped": 0, "already": 0}
    workspaces = (
        db.query(Workspace)
        .filter(Workspace.is_active.is_(True), Workspace.deleted_at.is_(None))
        .all()
    )
    for ws in workspaces:
        before = (
            db.query(System)
            .filter(
                System.workspace_id == ws.id,
                System.name == INTELLIGENCE_SYSTEM_NAME,
            )
            .count()
        )
        system = ensure_intelligence_system_default(db, ws.id)
        if system is None:
            report["skipped"] += 1
        elif before == 0:
            report["created"] += 1
        else:
            report["already"] += 1
    return report


def _skill_lookup(db: DBSession, slugs: List[str]) -> Dict[str, Skill]:
    rows = db.query(Skill).filter(Skill.slug.in_(slugs)).all()
    return {skill.slug: skill for skill in rows}


def _expert_capture_flow_definition(skills: Dict[str, Skill]) -> Dict[str, object]:
    def task(
        node_id: str,
        *,
        slug: str,
        label: str,
        x: int,
        y: int,
        inputs_map: Optional[Dict[str, str]] = None,
        outputs_map: Optional[Dict[str, str]] = None,
        data: Optional[Dict[str, object]] = None,
    ) -> Dict[str, object]:
        skill = skills.get(slug)
        return {
            "id": node_id,
            "type": "skill",
            "kind": "task",
            "label": label,
            "position": {"x": x, "y": y},
            "data": data or {},
            "config": {
                "skill_id": skill.id if skill else None,
                "skill_slug": slug,
                "inputs_map": inputs_map or {},
                "outputs_map": outputs_map or {},
            },
        }

    nodes: List[Dict[str, object]] = [
        {
            "id": "capture.session_request",
            "type": "source",
            "kind": "source",
            "label": "Capture session request",
            "position": {"x": 40, "y": 220},
            "data": {
                "menu": "Objective",
                "description": "Objective, expert profile, duration and Knowledge Context selected from /knowledge/capture.",
            },
            "outputs": [
                {"name": "objective", "schema": "string", "required": True},
                {"name": "context", "schema": "object"},
            ],
        },
        task(
            "skill.knowledge_gap_analysis",
            slug="knowledge_gap_analysis_v1",
            label="Identify tacit knowledge gaps",
            x=340,
            y=100,
            inputs_map={"objective": "session.objective", "context": "session.context"},
            outputs_map={"gaps": "capture.gaps"},
            data={"menu": "Plan", "phase": "preflight"},
        ),
        task(
            "skill.expert_interview_plan",
            slug="expert_interview_plan_v1",
            label="Build interview plan",
            x=640,
            y=100,
            inputs_map={"objective": "session.objective", "gaps": "capture.gaps"},
            outputs_map={"plan": "capture.plan"},
            data={"menu": "Plan", "phase": "preflight"},
        ),
        task(
            "skill.voice_realtime_session",
            slug="voice_realtime_session_v1",
            label="Resolve voice runtime",
            x=940,
            y=100,
            inputs_map={"provider": "system.voice_runtime.provider"},
            outputs_map={"provider": "turn.voice_provider", "events": "turn.voice_events"},
            data={"menu": "Voice", "runtime": "cascade_openai", "capability": "voice2voice_interaction"},
        ),
        task(
            "skill.voice_transcribe",
            slug="voice_realtime_transcribe_v1",
            label="Realtime / cascade transcript",
            x=1240,
            y=100,
            inputs_map={"audio_ref": "turn.audio_ref"},
            outputs_map={"transcript": "turn.transcript"},
            data={"menu": "Voice", "runtime": "cascade_openai", "supports": ["text.partial", "text.final", "barge_in"]},
        ),
        task(
            "skill.semantic_search_prefetch",
            slug="semantic_search_v1",
            label="Pseudo realtime retrieval prefetch",
            x=1540,
            y=100,
            inputs_map={"query": "turn.partial_transcript", "collection": "context.environment_state.collection"},
            outputs_map={"results": "turn.retrieval_refs"},
            data={"menu": "Knowledge", "mode": "chah", "top_k": 4, "timeout_ms": 2500},
        ),
        task(
            "skill.expert_answer_evaluator",
            slug="expert_answer_evaluator_v1",
            label="Evaluate answer / correction",
            x=1840,
            y=100,
            inputs_map={"answer": "turn.final_transcript", "question": "capture.current_question", "gap": "capture.current_gap"},
            outputs_map={"evaluation": "turn.evaluation"},
            data={"menu": "Evaluation", "phase": "turn"},
        ),
        task(
            "skill.voice_tandem_oracle",
            slug="voice_tandem_oracle_v1",
            label="Tandem oracle loop",
            x=2140,
            y=20,
            inputs_map={
                "partial_text": "turn.partial_transcript",
                "final_text": "turn.final_transcript",
                "evaluation": "turn.evaluation",
                "sources": "turn.retrieval_refs",
            },
            outputs_map={"events": "turn.oracle_events", "committed": "turn.oracle_committed"},
            data={
                "menu": "Voice",
                "pattern": "Realtime loop + Background oracle",
                "events": ["oracle.delta", "oracle.superseded", "oracle.action", "oracle.commit"],
            },
        ),
        task(
            "skill.voice_oracle_turn",
            slug="voice_oracle_turn_v1",
            label="Commit voice action",
            x=2440,
            y=100,
            inputs_map={"answer": "turn.final_transcript", "question": "capture.current_question", "gap": "capture.current_gap"},
            outputs_map={"action": "turn.voice_action"},
            data={"menu": "Voice", "events": ["oracle.action", "runtime.metric"]},
        ),
        {
            "id": "decision.answer_route",
            "type": "custom",
            "kind": "decision",
            "label": "Route next action",
            "position": {"x": 2740, "y": 100},
            "data": {"menu": "Conversation-only", "description": "Intent + sufficiency gate."},
            "config": {
                "branches": [
                    {"label": "follow_up_required", "condition": "evaluation.verdict != 'sufficient'"},
                    {"label": "proposal_requested", "condition": "intent in ['proposal_requested', 'accept_confirmed']"},
                ],
                "default_branch": "follow_up_required",
            },
        },
        task(
            "skill.voice_tts_followup",
            slug="voice_realtime_speak_v1",
            label="Speak follow-up / next question",
            x=3040,
            y=20,
            inputs_map={"text": "turn.next_prompt"},
            outputs_map={"audio_url": "turn.prompt_audio"},
            data={"menu": "Voice", "phase": "barge_in"},
        ),
        task(
            "skill.capture_structuring",
            slug="capture_structuring_v1",
            label="Create knowledge proposal",
            x=3040,
            y=210,
            inputs_map={"session": "capture.session", "events": "capture.audit_events"},
            outputs_map={"proposal": "capture.proposal"},
            data={"menu": "Proposal", "phase": "synthesis"},
        ),
        {
            "id": "hitl.proposal_review",
            "type": "policy",
            "kind": "hitl",
            "label": "HITL proposal confirmation",
            "position": {"x": 3340, "y": 210},
            "data": {"menu": "Governance", "description": "Voice confirmation, amendment, then final accept/reject."},
            "config": {
                "prompt": "Validate, amend, reject, or request another capture turn before ingestion.",
                "approvers": ["expert", "operator"],
                "timeout_ms": 86_400_000,
            },
        },
        task(
            "skill.audit_log",
            slug="audit_log_v1",
            label="Persist audit trail",
            x=3640,
            y=160,
            inputs_map={"event": "capture.event"},
            outputs_map={"event_id": "capture.audit_event_id"},
            data={"menu": "Traceability", "events": [
                "stt_partial",
                "stt_final",
                "retrieval_prefetch_completed",
                "conversation_intent_detected",
                "proposal_generated",
                "proposal_reviewed",
            ]},
        ),
        {
            "id": "sink.knowledge_update",
            "type": "sink",
            "kind": "sink",
            "label": "Reviewed knowledge update",
            "position": {"x": 3640, "y": 160},
            "data": {"menu": "Knowledge", "description": "Accepted proposal ready for ingestion into the selected Knowledge collection."},
            "inputs": [{"name": "proposal", "schema": "object", "required": True}],
        },
    ]
    edges = [
        {"from": "capture.session_request", "to": "skill.knowledge_gap_analysis", "kind": "data"},
        {"from": "skill.knowledge_gap_analysis", "to": "skill.expert_interview_plan", "kind": "data"},
        {"from": "skill.expert_interview_plan", "to": "skill.voice_realtime_session", "kind": "control"},
        {"from": "skill.voice_realtime_session", "to": "skill.voice_transcribe", "kind": "control"},
        {"from": "skill.voice_transcribe", "to": "skill.semantic_search_prefetch", "kind": "data"},
        {"from": "skill.semantic_search_prefetch", "to": "skill.expert_answer_evaluator", "kind": "data"},
        {"from": "skill.expert_answer_evaluator", "to": "skill.voice_tandem_oracle", "kind": "data"},
        {"from": "skill.voice_tandem_oracle", "to": "skill.voice_oracle_turn", "kind": "data"},
        {"from": "skill.voice_oracle_turn", "to": "decision.answer_route", "kind": "data"},
        {
            "from": "decision.answer_route",
            "to": "skill.voice_tts_followup",
            "kind": "branch",
            "branch_label": "follow_up_required",
        },
        {"from": "skill.voice_tts_followup", "to": "skill.audit_log", "kind": "control"},
        {
            "from": "decision.answer_route",
            "to": "skill.capture_structuring",
            "kind": "branch",
            "branch_label": "proposal_requested",
        },
        {"from": "skill.capture_structuring", "to": "hitl.proposal_review", "kind": "control"},
        {"from": "hitl.proposal_review", "to": "skill.audit_log", "kind": "control"},
        {"from": "skill.audit_log", "to": "sink.knowledge_update", "kind": "control"},
    ]
    return {
        "schema_version": 2,
        "variant": "expert_knowledge_capture",
        "source": "flow",
        "extended": True,
        "template_id": "expert-knowledge-capture-v2v",
        "template_name": "Knowledge Capture Voice2Voice",
        "nodes": nodes,
        "edges": edges,
        "collections": [],
        "rag_mode": "C-HAH",
        "canonical_rag_mode": "chah",
        "retrieval": {"mode": "chah", "top_k": 4, "timeout_ms": 2500, "non_blocking": True},
        "voice_runtime": {
            "provider": "cascade_openai",
            "capability": "voice2voice_interaction",
            "transport": "backend_ws",
            "events": ["text.partial", "text.final", "audio.out", "barge_in", "oracle.action", "runtime.metric"],
        },
        "ui": {
            "type": "knowledge_capture",
            "label": "Capture console",
            "entry_route": "capture",
            "primary_action": "Start session",
            "legacy_route": "/knowledge/capture",
        },
        "policy": {
            "confidence_threshold": 0.7,
            "require_citations": True,
            "enable_audit": True,
            "max_latency_ms": 4000,
        },
        "conversation": {
            "mode": "conversation_only",
            "requires_confirmation": ["proposal", "acceptance"],
            "supports_multiple_proposals": True,
        },
    }


def ensure_expert_capture_system_default(db: DBSession, workspace_id: str) -> Optional[System]:
    capability = db.query(Capability).filter(Capability.slug == EXPERT_CAPTURE_CAPABILITY_SLUG).first()
    if not capability:
        logger.warning(
            "expert_capture_system_seed.skip.missing_capability",
            workspace_id=workspace_id,
            slug=EXPERT_CAPTURE_CAPABILITY_SLUG,
        )
        return None

    skills = _skill_lookup(db, EXPERT_CAPTURE_SKILL_SLUGS)
    skill_ids = [skills[slug].id for slug in EXPERT_CAPTURE_SKILL_SLUGS if slug in skills]
    flow_definition = _expert_capture_flow_definition(skills)

    existing = (
        db.query(System)
        .filter(
            System.workspace_id == workspace_id,
            System.capability_id == capability.id,
            System.name == EXPERT_CAPTURE_SYSTEM_NAME,
        )
        .first()
    )
    if existing:
        flow = dict(existing.flow_definition or {})
        if flow.get("variant") != "expert_knowledge_capture":
            existing.flow_definition = flow_definition
        existing.objective = existing.objective or EXPERT_CAPTURE_OBJECTIVE
        existing.skill_ids = skill_ids
        existing.execution_mode = "human_augmented"
        existing.coordination_pattern = "single_agent"
        existing.status = "active"
        existing.retrieval_mode_default = "chah"
        db.commit()
        db.refresh(existing)
        return existing

    system = System(
        workspace_id=workspace_id,
        name=EXPERT_CAPTURE_SYSTEM_NAME,
        objective=EXPERT_CAPTURE_OBJECTIVE,
        capability_id=capability.id,
        skill_ids=skill_ids,
        flow_definition=flow_definition,
        execution_mode="human_augmented",
        execution_profile={
            "runtime": "voice2voice_cascade",
            "latency_target": "perceived_realtime",
            "max_retrieval_prefetch_ms": 2500,
            "durability": "audit_events",
        },
        coordination_pattern="single_agent",
        status="active",
        created_by="system:expert_capture_seed",
        retrieval_mode_default="chah",
    )
    db.add(system)
    db.commit()
    db.refresh(system)
    logger.info(
        "expert_capture_system_seed.created",
        workspace_id=workspace_id,
        system_id=system.id,
        capability_id=capability.id,
    )
    return system


def ensure_expert_capture_system_for_all_workspaces(db: DBSession) -> Dict[str, int]:
    report = {"created": 0, "skipped": 0, "already": 0}
    workspaces = (
        db.query(Workspace)
        .filter(Workspace.is_active.is_(True), Workspace.deleted_at.is_(None))
        .all()
    )
    for ws in workspaces:
        before = (
            db.query(System)
            .filter(System.workspace_id == ws.id, System.name == EXPERT_CAPTURE_SYSTEM_NAME)
            .count()
        )
        system = ensure_expert_capture_system_default(db, ws.id)
        if system is None:
            report["skipped"] += 1
        elif before == 0:
            report["created"] += 1
        else:
            report["already"] += 1
    return report
