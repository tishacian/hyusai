"""Expert Knowledge Capture API.

This surface turns a workspace Context / Knowledge scope into a guided
interview plan, captures expert answers, evaluates whether a relance is
needed, and emits a reviewable knowledge update proposal.
"""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DBSession

from app.core.auth import get_current_workspace
from app.db.base import get_db
from app.models.expert_capture import ExpertCaptureSession, KnowledgeUpdateProposal
from app.models.workspace import Workspace
from app.services.knowledge_capture import (
    amend_capture_event,
    append_turn,
    create_capture_plan,
    create_update_proposal,
    get_session,
    list_capture_events,
    prefetch_capture_retrieval,
    process_conversation_step,
    review_proposal,
    serialize_event,
    serialize_proposal,
    serialize_session,
    start_session,
)
from app.services.voice_runtime import list_voice_runtime_providers

router = APIRouter()


class CapturePlanRequest(BaseModel):
    objective: str = Field(..., min_length=8)
    title: Optional[str] = None
    expert_profile: Optional[str] = None
    duration_minutes: int = Field(default=20, ge=5, le=90)
    context_id: Optional[str] = None
    system_id: Optional[str] = None
    knowledge_refs: List[str] = Field(default_factory=list)
    voice_runtime: str = "cascade"


class CaptureTurnRequest(BaseModel):
    speaker: Literal["expert", "system", "operator"] = "expert"
    text: str = Field(..., min_length=1)
    question_id: Optional[str] = None
    audio_ref: Optional[str] = None
    client_turn_id: Optional[str] = None
    retrieval_event_id: Optional[str] = None
    interruption_of_event_id: Optional[str] = None
    turn_kind: Literal["answer", "correction", "complement"] = "answer"


class RetrievalPrefetchRequest(BaseModel):
    client_turn_id: Optional[str] = None
    question_id: Optional[str] = None
    partial_text: str = Field(..., min_length=1)
    mode: str = "chah"
    top_k: int = Field(default=4, ge=1, le=8)


class ConversationStepRequest(BaseModel):
    client_turn_id: Optional[str] = None
    text: str = Field(..., min_length=1)
    question_id: Optional[str] = None
    retrieval_event_id: Optional[str] = None
    interruption_of_event_id: Optional[str] = None
    last_proposal_id: Optional[str] = None


class ProposalReviewRequest(BaseModel):
    status: Literal["accepted", "rejected", "changes_requested"]
    reviewer: Optional[str] = None
    review_notes: Optional[str] = None


class EventAmendRequest(BaseModel):
    text_amended: str = Field(..., min_length=1)
    actor: Optional[str] = None
    reason: Optional[str] = None


@router.get("/voice-runtimes")
async def voice_runtimes() -> Dict[str, Any]:
    return list_voice_runtime_providers()


@router.post("/plans")
async def plan_capture_session(
    body: CapturePlanRequest,
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
) -> Dict[str, Any]:
    try:
        session = create_capture_plan(
            db,
            workspace_id=workspace.id,
            title=body.title,
            objective=body.objective,
            expert_profile=body.expert_profile,
            duration_minutes=body.duration_minutes,
            context_id=body.context_id,
            system_id=body.system_id,
            knowledge_refs=body.knowledge_refs,
            voice_runtime=body.voice_runtime,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return serialize_session(session)


@router.get("/sessions")
async def list_capture_sessions(
    status: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=200),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
) -> Dict[str, Any]:
    q = db.query(ExpertCaptureSession).filter(ExpertCaptureSession.workspace_id == workspace.id)
    if status:
        q = q.filter(ExpertCaptureSession.status == status)
    rows = q.order_by(ExpertCaptureSession.updated_at.desc()).limit(limit).all()
    return {"sessions": [serialize_session(row) for row in rows]}


@router.get("/sessions/{session_id}")
async def get_capture_session(
    session_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
) -> Dict[str, Any]:
    try:
        session = get_session(db, workspace_id=workspace.id, session_id=session_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return serialize_session(session)


@router.post("/sessions/{session_id}/start")
async def start_capture_session(
    session_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
) -> Dict[str, Any]:
    try:
        session = start_session(db, workspace_id=workspace.id, session_id=session_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return serialize_session(session)


@router.post("/sessions/{session_id}/turns")
async def add_capture_turn(
    session_id: str,
    body: CaptureTurnRequest,
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
) -> Dict[str, Any]:
    try:
        return append_turn(
            db,
            workspace_id=workspace.id,
            session_id=session_id,
            speaker=body.speaker,
            text=body.text,
            question_id=body.question_id,
            audio_ref=body.audio_ref,
            client_turn_id=body.client_turn_id,
            retrieval_event_id=body.retrieval_event_id,
            interruption_of_event_id=body.interruption_of_event_id,
            turn_kind=body.turn_kind,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/sessions/{session_id}/retrieval-prefetch")
async def prefetch_session_retrieval(
    session_id: str,
    body: RetrievalPrefetchRequest,
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
) -> Dict[str, Any]:
    try:
        return await prefetch_capture_retrieval(
            db,
            workspace_id=workspace.id,
            workspace_slug=workspace.slug,
            session_id=session_id,
            client_turn_id=body.client_turn_id,
            question_id=body.question_id,
            partial_text=body.partial_text,
            mode=body.mode,
            top_k=body.top_k,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/sessions/{session_id}/conversation-step")
async def conversation_session_step(
    session_id: str,
    body: ConversationStepRequest,
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
) -> Dict[str, Any]:
    try:
        return process_conversation_step(
            db,
            workspace_id=workspace.id,
            session_id=session_id,
            client_turn_id=body.client_turn_id,
            text=body.text,
            question_id=body.question_id,
            retrieval_event_id=body.retrieval_event_id,
            interruption_of_event_id=body.interruption_of_event_id,
            last_proposal_id=body.last_proposal_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/sessions/{session_id}/events")
async def list_session_events(
    session_id: str,
    event_type: Optional[str] = None,
    status: Optional[str] = None,
    after_sequence: Optional[int] = Query(default=None, ge=0),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
) -> Dict[str, Any]:
    try:
        get_session(db, workspace_id=workspace.id, session_id=session_id)
        rows = list_capture_events(
            db,
            workspace_id=workspace.id,
            session_id=session_id,
            event_type=event_type,
            status=status,
            after_sequence=after_sequence,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"events": [serialize_event(row) for row in rows]}


@router.patch("/sessions/{session_id}/events/{event_id}/amend")
async def amend_session_event(
    session_id: str,
    event_id: str,
    body: EventAmendRequest,
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
) -> Dict[str, Any]:
    try:
        return amend_capture_event(
            db,
            workspace_id=workspace.id,
            session_id=session_id,
            event_id=event_id,
            text_amended=body.text_amended,
            actor=body.actor,
            reason=body.reason,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/sessions/{session_id}/proposal")
async def create_capture_proposal(
    session_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
) -> Dict[str, Any]:
    try:
        proposal = create_update_proposal(db, workspace_id=workspace.id, session_id=session_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return serialize_proposal(proposal)


@router.get("/proposals")
async def list_capture_proposals(
    status: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=200),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
) -> Dict[str, Any]:
    q = db.query(KnowledgeUpdateProposal).filter(KnowledgeUpdateProposal.workspace_id == workspace.id)
    if status:
        q = q.filter(KnowledgeUpdateProposal.status == status)
    rows = q.order_by(KnowledgeUpdateProposal.created_at.desc()).limit(limit).all()
    return {"proposals": [serialize_proposal(row) for row in rows]}


@router.patch("/proposals/{proposal_id}/review")
async def review_capture_proposal(
    proposal_id: str,
    body: ProposalReviewRequest,
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
) -> Dict[str, Any]:
    try:
        proposal = review_proposal(
            db,
            workspace_id=workspace.id,
            proposal_id=proposal_id,
            status=body.status,
            reviewer=body.reviewer,
            review_notes=body.review_notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return serialize_proposal(proposal)
