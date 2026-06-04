"""Expert Knowledge Capture API.

This surface turns a workspace Context / Knowledge scope into a guided
interview plan, captures expert answers, evaluates whether a relance is
needed, and emits a reviewable knowledge update proposal.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session as DBSession

from app.core.auth import get_current_user, get_current_workspace
from app.core.iam.dependencies import current_membership, enforce_permission
from app.core.iam.roles import WORKSPACE_CONTRIBUTOR, normalize_role_template
from app.services.iam.manifest import REVIEW_ROLES
from app.db.base import get_db
from app.models.expert_capture import ExpertCaptureSession, KnowledgeUpdateProposal
from app.models.user import User
from app.models.workspace import Workspace
from app.services.iam.config_service import effective_role_flags, load_iam_config
from app.services.knowledge_capture import (
    amend_capture_event,
    amend_capture_plan,
    append_turn,
    apply_session_closure_action,
    approve_capture_plan,
    build_open_questions,
    build_quality_backlog,
    build_session_closure_sheet,
    create_capture_plan,
    create_update_proposal,
    defer_quality_item,
    export_session_proposal_markdown,
    extend_capture_session,
    finalize_plan_from_dialogue,
    generate_question_bank,
    generate_session_closure_sheet,
    get_hint_queue,
    get_plan_topics,
    get_session,
    list_capture_events,
    pause_capture_session,
    prefetch_capture_retrieval,
    process_conversation_step,
    process_plan_dialogue_turn,
    publish_proposal_to_knowledge,
    resume_capture_session,
    review_proposal,
    serialize_event,
    serialize_proposal,
    serialize_session,
    start_session,
    update_oracle_question_statuses,
    update_proposal_report_content,
    update_capture_session_flags,
    update_plan_topics,
    validate_plan_topics,
)
from app.services.voice_runtime import list_voice_runtime_providers

router = APIRouter()

CAPTURE_CAPABILITY = "expert_knowledge_capture"
_PLAN_SOURCE_MAX_BYTES = 8 * 1024 * 1024
_PLAN_SOURCE_TEXT_LIMIT = 20000
_PLAN_SOURCE_EXTENSIONS = {
    ".csv",
    ".docx",
    ".htm",
    ".html",
    ".json",
    ".log",
    ".md",
    ".markdown",
    ".pdf",
    ".rtf",
    ".text",
    ".tsv",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}
_PLAN_SOURCE_MEDIA_TYPES = {
    "application/json",
    "application/pdf",
    "application/rtf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/xml",
    "text/csv",
    "text/html",
    "text/markdown",
    "text/plain",
    "text/tab-separated-values",
    "text/xml",
}


def _safe_plan_source_filename(filename: Optional[str]) -> str:
    name = Path(str(filename or "plan.txt").replace("\\", "/")).name.strip()
    return (name or "plan.txt")[:180]


def _read_uploaded_text_fallback(path: str) -> str:
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return Path(path).read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return Path(path).read_text(encoding="latin-1", errors="ignore")


async def _extract_plan_source_text(upload: UploadFile) -> Dict[str, Any]:
    filename = _safe_plan_source_filename(upload.filename)
    ext = Path(filename).suffix.lower()
    media_type = str(upload.content_type or "").lower()
    if ext not in _PLAN_SOURCE_EXTENSIONS and not media_type.startswith("text/") and media_type not in _PLAN_SOURCE_MEDIA_TYPES:
        raise ValueError("Format de fichier non supporté pour une source de plan.")

    fd, temp_path = tempfile.mkstemp(prefix="agentium-plan-source-", suffix=ext or ".txt")
    size = 0
    try:
        with os.fdopen(fd, "wb") as handle:
            while True:
                chunk = await upload.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > _PLAN_SOURCE_MAX_BYTES:
                    raise ValueError("Le fichier de plan dépasse la limite de 8 Mo.")
                handle.write(chunk)
        if size <= 0:
            raise ValueError("Le fichier de plan est vide.")

        document_type = "text"
        try:
            import app.services.document_parser.parsers  # noqa: F401
            from app.services.document_parser.factory import DocumentParserFactory

            parser = DocumentParserFactory.get_parser(temp_path)
            parsed = await parser.parse(temp_path, chunk_size=2000, chunk_overlap=100, use_ocr=False)
            text = str(parsed.raw_content or "").strip()
            document_type = getattr(parsed.document_type, "value", str(parsed.document_type))
        except Exception as exc:
            if ext in {".pdf", ".docx"}:
                raise ValueError("Impossible d'extraire du texte depuis ce fichier.") from exc
            text = _read_uploaded_text_fallback(temp_path).strip()

        if not text or text == "No content could be extracted from this document.":
            raise ValueError("Aucun texte exploitable trouvé dans le fichier.")
        truncated = len(text) > _PLAN_SOURCE_TEXT_LIMIT
        if truncated:
            text = text[:_PLAN_SOURCE_TEXT_LIMIT]
        return {
            "filename": filename,
            "content_type": upload.content_type,
            "document_type": document_type,
            "chars": len(text),
            "truncated": truncated,
            "text": text,
        }
    finally:
        try:
            await upload.close()
        finally:
            try:
                os.unlink(temp_path)
            except OSError:
                pass


def _actor_label(user: User) -> str:
    return user.email or user.username or user.id


def _session_attrs(session: ExpertCaptureSession) -> Dict[str, Any]:
    return {
        "capability": CAPTURE_CAPABILITY,
        "resource_id": session.id,
        "owner_user_id": session.created_by_user_id,
        "created_by_user_id": session.created_by_user_id,
    }


def _proposal_attrs(proposal: KnowledgeUpdateProposal, session: Optional[ExpertCaptureSession] = None) -> Dict[str, Any]:
    owner = proposal.created_by_user_id or (session.created_by_user_id if session else None)
    return {
        "capability": CAPTURE_CAPABILITY,
        "resource_id": proposal.id,
        "session_id": proposal.session_id,
        "owner_user_id": owner,
        "created_by_user_id": owner,
    }


def _load_proposal_with_session(
    db: DBSession,
    *,
    workspace_id: str,
    proposal_id: str,
) -> tuple[KnowledgeUpdateProposal, Optional[ExpertCaptureSession]]:
    proposal = (
        db.query(KnowledgeUpdateProposal)
        .filter(KnowledgeUpdateProposal.id == proposal_id, KnowledgeUpdateProposal.workspace_id == workspace_id)
        .first()
    )
    if not proposal:
        raise ValueError("Knowledge update proposal not found")
    session = (
        db.query(ExpertCaptureSession)
        .filter(ExpertCaptureSession.id == proposal.session_id, ExpertCaptureSession.workspace_id == workspace_id)
        .first()
    )
    return proposal, session


def _allow_immature_ai_plan(db: DBSession, *, user: User, workspace: Workspace) -> bool:
    membership = current_membership(db, user, workspace)
    role_template = normalize_role_template(
        getattr(membership, "role_template", None) if membership else None,
        getattr(membership, "role", None) if membership else None,
    )
    return role_template in REVIEW_ROLES


def _contributors_see_only_own(db: DBSession, *, user: User, workspace: Workspace) -> bool:
    membership = current_membership(db, user, workspace)
    role_template = normalize_role_template(
        getattr(membership, "role_template", None) if membership else None,
        getattr(membership, "role", None) if membership else None,
    )
    flags = effective_role_flags(load_iam_config(db, workspace.id, create=False))
    return role_template == WORKSPACE_CONTRIBUTOR and bool(flags.get("contributors_see_only_own_sessions", True))


def _http_error_from_value_error(exc: ValueError) -> HTTPException:
    message = str(exc)
    status_code = 404 if "not found" in message.lower() else 400
    return HTTPException(status_code=status_code, detail=message)


class CapturePlanRequest(BaseModel):
    objective: str = Field(default="", min_length=0)
    title: Optional[str] = None
    expert_profile: Optional[str] = None
    duration_minutes: Optional[int] = Field(default=20, ge=0, le=90)
    context_id: Optional[str] = None
    system_id: Optional[str] = None
    knowledge_refs: List[str] = Field(default_factory=list)
    voice_runtime: str = "cascade_openai"
    plan_mode: str = "free_conversation"
    capture_domain: Optional[str] = None
    provided_plan_text: Optional[str] = None


class PlanDialogueTurnRequest(BaseModel):
    text: str = Field(default="", min_length=0)
    confirm_finalize: bool = False


class SessionFlagsRequest(BaseModel):
    defer_weak_contradictions: Optional[bool] = None
    capture_domain: Optional[str] = None
    focused_quality_question_id: Optional[str] = None
    focused_quality_evaluation_id: Optional[str] = None


class QualityDeferRequest(BaseModel):
    item_id: str
    bucket: Literal["imprecisions", "contradictions", "open_questions"] = "open_questions"
    deferred_reason: str = "end_of_session"


class OracleQuestionStatusItem(BaseModel):
    question_id: Optional[str] = None
    question_text: Optional[str] = None
    status: Literal["active", "open", "answered", "dismissed", "deferred"] = "open"


class OracleQuestionStatusRequest(BaseModel):
    items: List[OracleQuestionStatusItem] = Field(default_factory=list)


class ProposalExportRequest(BaseModel):
    executive_summary: Optional[str] = None
    proposal_id: Optional[str] = None


class ProposalPublishRequest(BaseModel):
    category: Optional[str] = None
    destination: Optional[str] = None


class SessionClosureRequest(BaseModel):
    action: Literal["finish", "extend", "schedule"] = "finish"
    extension_minutes: int = Field(default=15, ge=5, le=60)


class CaptureTurnRequest(BaseModel):
    speaker: Literal["expert", "system", "operator"] = "expert"
    text: str = Field(..., min_length=1)
    question_id: Optional[str] = None
    audio_ref: Optional[str] = None
    client_turn_id: Optional[str] = None
    retrieval_event_id: Optional[str] = None
    interruption_of_event_id: Optional[str] = None
    turn_kind: Literal["answer", "correction", "complement"] = "answer"


class CapturePlanUpdateRequest(BaseModel):
    plan: Dict[str, Any]


class PlanTopicsUpdateRequest(BaseModel):
    topics: List[Dict[str, Any]]


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


class ProposalContentUpdateRequest(BaseModel):
    content: str = Field(..., min_length=1)


class EventAmendRequest(BaseModel):
    text_amended: str = Field(..., min_length=1)
    actor: Optional[str] = None
    reason: Optional[str] = None


@router.get("/voice-runtimes")
async def voice_runtimes(
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
) -> Dict[str, Any]:
    enforce_permission(
        db,
        user=user,
        workspace=workspace,
        resource_kind="voice_runtime",
        action="read",
        resource_attrs={"capability": CAPTURE_CAPABILITY},
        audit_prefix="kc",
    )
    return list_voice_runtime_providers(workspace=workspace)


@router.post("/plan-source/extract")
async def extract_plan_source(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
) -> Dict[str, Any]:
    enforce_permission(
        db,
        user=user,
        workspace=workspace,
        resource_kind="capture_session",
        action="create",
        resource_attrs={"capability": CAPTURE_CAPABILITY},
        audit_prefix="kc",
    )
    try:
        return await _extract_plan_source_text(file)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/plans")
async def plan_capture_session(
    body: CapturePlanRequest,
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
) -> Dict[str, Any]:
    enforce_permission(
        db,
        user=user,
        workspace=workspace,
        resource_kind="capture_session",
        action="create",
        resource_attrs={"capability": CAPTURE_CAPABILITY},
        audit_prefix="kc",
    )
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
            plan_mode=body.plan_mode,
            allow_ai_plan=_allow_immature_ai_plan(db, user=user, workspace=workspace),
            capture_domain=body.capture_domain,
            provided_plan_text=body.provided_plan_text,
            created_by_user_id=user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return serialize_session(session)


@router.get("/sessions")
async def list_capture_sessions(
    status: Optional[str] = None,
    domain: Optional[str] = None,
    system_id: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=200),
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
) -> Dict[str, Any]:
    enforce_permission(
        db,
        user=user,
        workspace=workspace,
        resource_kind="capture_session",
        action="read",
        resource_attrs={"capability": CAPTURE_CAPABILITY, "owner_user_id": user.id},
        audit_prefix="kc",
    )
    q = db.query(ExpertCaptureSession).filter(ExpertCaptureSession.workspace_id == workspace.id)
    if status:
        q = q.filter(ExpertCaptureSession.status == status)
    if system_id:
        q = q.filter(ExpertCaptureSession.system_id == system_id)
    if _contributors_see_only_own(db, user=user, workspace=workspace):
        q = q.filter(or_(ExpertCaptureSession.created_by_user_id == user.id, ExpertCaptureSession.created_by_user_id.is_(None)))
    if domain:
        domain_key = domain.strip().lower()
        rows = q.order_by(ExpertCaptureSession.updated_at.desc()).all()
        rows = [
            row
            for row in rows
            if ((row.metrics or {}).get("capture_domain") or "").lower() == domain_key
        ][:limit]
    else:
        rows = q.order_by(ExpertCaptureSession.updated_at.desc()).limit(limit).all()
    return {"sessions": [serialize_session(row) for row in rows]}


@router.get("/sessions/{session_id}")
async def get_capture_session(
    session_id: str,
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
) -> Dict[str, Any]:
    try:
        session = get_session(db, workspace_id=workspace.id, session_id=session_id)
    except ValueError as exc:
        raise _http_error_from_value_error(exc) from exc
    enforce_permission(
        db,
        user=user,
        workspace=workspace,
        resource_kind="capture_session",
        action="read",
        resource_attrs=_session_attrs(session),
        audit_prefix="kc",
    )
    return serialize_session(session)


@router.patch("/sessions/{session_id}/plan")
async def update_capture_plan(
    session_id: str,
    body: CapturePlanUpdateRequest,
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
) -> Dict[str, Any]:
    try:
        existing = get_session(db, workspace_id=workspace.id, session_id=session_id)
        enforce_permission(
            db,
            user=user,
            workspace=workspace,
            resource_kind="capture_session",
            action="update",
            resource_attrs=_session_attrs(existing),
            audit_prefix="kc",
        )
        session = amend_capture_plan(
            db,
            workspace_id=workspace.id,
            session_id=session_id,
            plan=body.plan,
            actor_user_id=user.id,
        )
    except ValueError as exc:
        raise _http_error_from_value_error(exc) from exc
    return serialize_session(session)


@router.post("/sessions/{session_id}/plan/approve")
async def approve_capture_session_plan(
    session_id: str,
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
) -> Dict[str, Any]:
    try:
        existing = get_session(db, workspace_id=workspace.id, session_id=session_id)
        enforce_permission(
            db,
            user=user,
            workspace=workspace,
            resource_kind="capture_session",
            action="update",
            resource_attrs=_session_attrs(existing),
            audit_prefix="kc",
        )
        session = approve_capture_plan(
            db,
            workspace_id=workspace.id,
            session_id=session_id,
            actor_user_id=user.id,
        )
    except ValueError as exc:
        raise _http_error_from_value_error(exc) from exc
    return serialize_session(session)


@router.post("/sessions/{session_id}/start")
async def start_capture_session(
    session_id: str,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
) -> Dict[str, Any]:
    try:
        existing = get_session(db, workspace_id=workspace.id, session_id=session_id)
        enforce_permission(
            db,
            user=user,
            workspace=workspace,
            resource_kind="capture_session",
            action="execute",
            resource_attrs=_session_attrs(existing),
            audit_prefix="kc",
        )
        prior_qbank_status = (existing.plan or {}).get("question_bank_status") or "idle"
        session = start_session(db, workspace_id=workspace.id, session_id=session_id)
        if (
            prior_qbank_status == "idle"
            and (session.plan or {}).get("question_bank_status") == "generating"
        ):
            from app.db.base import SessionLocal

            background_tasks.add_task(
                _run_question_bank_generation,
                SessionLocal,
                workspace_id=workspace.id,
                session_id=session_id,
                workspace_slug=workspace.slug,
            )
    except ValueError as exc:
        raise _http_error_from_value_error(exc) from exc
    return serialize_session(session)


@router.post("/sessions/{session_id}/turns")
async def add_capture_turn(
    session_id: str,
    body: CaptureTurnRequest,
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
) -> Dict[str, Any]:
    try:
        session = get_session(db, workspace_id=workspace.id, session_id=session_id)
        enforce_permission(
            db,
            user=user,
            workspace=workspace,
            resource_kind="capture_session",
            action="update",
            resource_attrs=_session_attrs(session),
            audit_prefix="kc",
        )
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
            actor_user_id=user.id,
        )
    except ValueError as exc:
        raise _http_error_from_value_error(exc) from exc


@router.post("/sessions/{session_id}/retrieval-prefetch")
async def prefetch_session_retrieval(
    session_id: str,
    body: RetrievalPrefetchRequest,
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
) -> Dict[str, Any]:
    try:
        session = get_session(db, workspace_id=workspace.id, session_id=session_id)
        enforce_permission(
            db,
            user=user,
            workspace=workspace,
            resource_kind="capture_session",
            action="execute",
            resource_attrs=_session_attrs(session),
            audit_prefix="kc",
        )
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
        raise _http_error_from_value_error(exc) from exc


@router.post("/sessions/{session_id}/conversation-step")
async def conversation_session_step(
    session_id: str,
    body: ConversationStepRequest,
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
) -> Dict[str, Any]:
    try:
        session = get_session(db, workspace_id=workspace.id, session_id=session_id)
        enforce_permission(
            db,
            user=user,
            workspace=workspace,
            resource_kind="capture_session",
            action="execute",
            resource_attrs=_session_attrs(session),
            audit_prefix="kc",
        )

        def _validate_voice_proposal_acceptance(proposal: KnowledgeUpdateProposal) -> None:
            proposal_session = (
                db.query(ExpertCaptureSession)
                .filter(
                    ExpertCaptureSession.id == proposal.session_id,
                    ExpertCaptureSession.workspace_id == workspace.id,
                )
                .first()
            )
            attrs = _proposal_attrs(proposal, proposal_session)
            enforce_permission(
                db,
                user=user,
                workspace=workspace,
                resource_kind="knowledge_proposal",
                action="review_decide",
                resource_attrs=attrs,
                audit_prefix="kc",
            )
            enforce_permission(
                db,
                user=user,
                workspace=workspace,
                resource_kind="knowledge_proposal",
                action="trigger_ingestion",
                resource_attrs=attrs,
                audit_prefix="kc",
            )

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
            actor_user_id=user.id,
            actor_label=_actor_label(user),
            proposal_acceptance_validator=_validate_voice_proposal_acceptance,
        )
    except ValueError as exc:
        raise _http_error_from_value_error(exc) from exc


@router.get("/sessions/{session_id}/events")
async def list_session_events(
    session_id: str,
    event_type: Optional[str] = None,
    status: Optional[str] = None,
    after_sequence: Optional[int] = Query(default=None, ge=0),
    business_only: bool = False,
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
) -> Dict[str, Any]:
    try:
        session = get_session(db, workspace_id=workspace.id, session_id=session_id)
        enforce_permission(
            db,
            user=user,
            workspace=workspace,
            resource_kind="capture_session",
            action="read",
            resource_attrs=_session_attrs(session),
            audit_prefix="kc",
        )
        rows = list_capture_events(
            db,
            workspace_id=workspace.id,
            session_id=session_id,
            event_type=event_type,
            status=status,
            after_sequence=after_sequence,
            business_only=business_only,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"events": [serialize_event(row) for row in rows]}


@router.patch("/sessions/{session_id}/events/{event_id}/amend")
async def amend_session_event(
    session_id: str,
    event_id: str,
    body: EventAmendRequest,
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
) -> Dict[str, Any]:
    try:
        session = get_session(db, workspace_id=workspace.id, session_id=session_id)
        enforce_permission(
            db,
            user=user,
            workspace=workspace,
            resource_kind="capture_session",
            action="update",
            resource_attrs=_session_attrs(session),
            audit_prefix="kc",
        )
        return amend_capture_event(
            db,
            workspace_id=workspace.id,
            session_id=session_id,
            event_id=event_id,
            text_amended=body.text_amended,
            actor=body.actor or _actor_label(user),
            reason=body.reason,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/sessions/{session_id}/proposal")
async def create_capture_proposal(
    session_id: str,
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
) -> Dict[str, Any]:
    try:
        session = get_session(db, workspace_id=workspace.id, session_id=session_id)
        enforce_permission(
            db,
            user=user,
            workspace=workspace,
            resource_kind="knowledge_proposal",
            action="submit_review",
            resource_attrs=_session_attrs(session),
            audit_prefix="kc",
        )
        proposal = create_update_proposal(
            db,
            workspace_id=workspace.id,
            session_id=session_id,
            created_by_user_id=user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return serialize_proposal(proposal)


@router.get("/proposals")
async def list_capture_proposals(
    status: Optional[str] = None,
    system_id: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=200),
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
) -> Dict[str, Any]:
    enforce_permission(
        db,
        user=user,
        workspace=workspace,
        resource_kind="knowledge_proposal",
        action="read",
        resource_attrs={"capability": CAPTURE_CAPABILITY, "owner_user_id": user.id},
        audit_prefix="kc",
    )
    q = db.query(KnowledgeUpdateProposal).filter(KnowledgeUpdateProposal.workspace_id == workspace.id)
    if status:
        q = q.filter(KnowledgeUpdateProposal.status == status)
    joined_session = False
    if _contributors_see_only_own(db, user=user, workspace=workspace):
        q = q.join(ExpertCaptureSession, ExpertCaptureSession.id == KnowledgeUpdateProposal.session_id)
        joined_session = True
        q = q.filter(
            or_(
                KnowledgeUpdateProposal.created_by_user_id == user.id,
                ExpertCaptureSession.created_by_user_id == user.id,
                KnowledgeUpdateProposal.created_by_user_id.is_(None),
            )
        )
    if system_id:
        if not joined_session:
            q = q.join(ExpertCaptureSession, ExpertCaptureSession.id == KnowledgeUpdateProposal.session_id)
        q = q.filter(ExpertCaptureSession.system_id == system_id)
    rows = q.order_by(KnowledgeUpdateProposal.created_at.desc()).limit(limit).all()
    return {"proposals": [serialize_proposal(row) for row in rows]}


@router.patch("/proposals/{proposal_id}/review")
async def review_capture_proposal(
    proposal_id: str,
    body: ProposalReviewRequest,
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
) -> Dict[str, Any]:
    try:
        existing, session = _load_proposal_with_session(db, workspace_id=workspace.id, proposal_id=proposal_id)
        enforce_permission(
            db,
            user=user,
            workspace=workspace,
            resource_kind="knowledge_proposal",
            action="review_decide",
            resource_attrs=_proposal_attrs(existing, session),
            audit_prefix="kc",
        )
        if body.status == "accepted":
            enforce_permission(
                db,
                user=user,
                workspace=workspace,
                resource_kind="knowledge_proposal",
                action="trigger_ingestion",
                resource_attrs=_proposal_attrs(existing, session),
                audit_prefix="kc",
            )
        proposal = review_proposal(
            db,
            workspace_id=workspace.id,
            proposal_id=proposal_id,
            status=body.status,
            reviewer=body.reviewer or _actor_label(user),
            review_notes=body.review_notes,
            reviewer_user_id=user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return serialize_proposal(proposal)


@router.patch("/proposals/{proposal_id}/content")
async def update_capture_proposal_content(
    proposal_id: str,
    body: ProposalContentUpdateRequest,
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
) -> Dict[str, Any]:
    try:
        existing, session = _load_proposal_with_session(db, workspace_id=workspace.id, proposal_id=proposal_id)
        enforce_permission(
            db,
            user=user,
            workspace=workspace,
            resource_kind="knowledge_proposal",
            action="review_decide",
            resource_attrs=_proposal_attrs(existing, session),
            audit_prefix="kc",
        )
        proposal = update_proposal_report_content(
            db,
            workspace_id=workspace.id,
            proposal_id=proposal_id,
            content=body.content,
            actor_user_id=user.id,
            actor_label=_actor_label(user),
        )
    except ValueError as exc:
        raise _http_error_from_value_error(exc) from exc
    return serialize_proposal(proposal)


@router.get("/sessions/{session_id}/quality-backlog")
async def get_capture_quality_backlog(
    session_id: str,
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
) -> Dict[str, Any]:
    try:
        session = get_session(db, workspace_id=workspace.id, session_id=session_id)
        enforce_permission(
            db,
            user=user,
            workspace=workspace,
            resource_kind="capture_session",
            action="read",
            resource_attrs=_session_attrs(session),
            audit_prefix="kc",
        )
        events = list_capture_events(db, workspace_id=workspace.id, session_id=session_id)
        return build_quality_backlog(session, events)
    except ValueError as exc:
        raise _http_error_from_value_error(exc) from exc


@router.post("/sessions/{session_id}/quality/defer")
async def defer_capture_quality_item(
    session_id: str,
    body: QualityDeferRequest,
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
) -> Dict[str, Any]:
    try:
        session = get_session(db, workspace_id=workspace.id, session_id=session_id)
        enforce_permission(
            db,
            user=user,
            workspace=workspace,
            resource_kind="capture_session",
            action="update",
            resource_attrs=_session_attrs(session),
            audit_prefix="kc",
        )
        return defer_quality_item(
            db,
            workspace_id=workspace.id,
            session_id=session_id,
            item_id=body.item_id,
            bucket=body.bucket,
            deferred_reason=body.deferred_reason,
            actor_user_id=user.id,
        )
    except ValueError as exc:
        raise _http_error_from_value_error(exc) from exc


@router.patch("/sessions/{session_id}/oracle-questions")
async def patch_capture_oracle_questions(
    session_id: str,
    body: OracleQuestionStatusRequest,
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
) -> Dict[str, Any]:
    try:
        session = get_session(db, workspace_id=workspace.id, session_id=session_id)
        enforce_permission(
            db,
            user=user,
            workspace=workspace,
            resource_kind="capture_session",
            action="update",
            resource_attrs=_session_attrs(session),
            audit_prefix="kc",
        )
        updated = update_oracle_question_statuses(
            db,
            workspace_id=workspace.id,
            session_id=session_id,
            items=[item.dict() for item in body.items],
            actor_user_id=user.id,
        )
    except ValueError as exc:
        raise _http_error_from_value_error(exc) from exc
    return {
        "session": serialize_session(updated),
        "open_questions": build_open_questions(updated),
    }


@router.patch("/sessions/{session_id}/flags")
async def patch_capture_session_flags(
    session_id: str,
    body: SessionFlagsRequest,
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
) -> Dict[str, Any]:
    try:
        session = get_session(db, workspace_id=workspace.id, session_id=session_id)
        enforce_permission(
            db,
            user=user,
            workspace=workspace,
            resource_kind="capture_session",
            action="update",
            resource_attrs=_session_attrs(session),
            audit_prefix="kc",
        )
        updated = update_capture_session_flags(
            db,
            workspace_id=workspace.id,
            session_id=session_id,
            defer_weak_contradictions=body.defer_weak_contradictions,
            capture_domain=body.capture_domain,
            focused_quality_question_id=body.focused_quality_question_id,
            focused_quality_evaluation_id=body.focused_quality_evaluation_id,
        )
    except ValueError as exc:
        raise _http_error_from_value_error(exc) from exc
    return serialize_session(updated)


@router.post("/sessions/{session_id}/plan/dialogue-turn")
def capture_plan_dialogue_turn(
    session_id: str,
    body: PlanDialogueTurnRequest,
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
) -> Dict[str, Any]:
    try:
        session = get_session(db, workspace_id=workspace.id, session_id=session_id)
        enforce_permission(
            db,
            user=user,
            workspace=workspace,
            resource_kind="capture_session",
            action="update",
            resource_attrs=_session_attrs(session),
            audit_prefix="kc",
        )
        return process_plan_dialogue_turn(
            db,
            workspace_id=workspace.id,
            session_id=session_id,
            text=body.text,
            actor_user_id=user.id,
            confirm_finalize=body.confirm_finalize,
            workspace_slug=workspace.slug,
        )
    except ValueError as exc:
        raise _http_error_from_value_error(exc) from exc


@router.post("/sessions/{session_id}/plan/finalize")
def capture_plan_finalize(
    session_id: str,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
) -> Dict[str, Any]:
    try:
        session = get_session(db, workspace_id=workspace.id, session_id=session_id)
        enforce_permission(
            db,
            user=user,
            workspace=workspace,
            resource_kind="capture_session",
            action="update",
            resource_attrs=_session_attrs(session),
            audit_prefix="kc",
        )
        prior_qbank_status = (session.plan or {}).get("question_bank_status") or "idle"
        finalized = finalize_plan_from_dialogue(
            db,
            workspace_id=workspace.id,
            session_id=session_id,
            actor_user_id=user.id,
            workspace_slug=workspace.slug,
        )
        if (
            prior_qbank_status == "idle"
            and (finalized.plan or {}).get("question_bank_status") == "generating"
        ):
            from app.db.base import SessionLocal

            background_tasks.add_task(
                _run_question_bank_generation,
                SessionLocal,
                workspace_id=workspace.id,
                session_id=session_id,
                workspace_slug=workspace.slug,
            )
    except ValueError as exc:
        raise _http_error_from_value_error(exc) from exc
    return serialize_session(finalized, surface="plan")


def _run_question_bank_generation(
    db_factory,
    *,
    workspace_id: str,
    session_id: str,
    workspace_slug: Optional[str],
) -> None:
    db = db_factory()
    try:
        generate_question_bank(
            db,
            workspace_id=workspace_id,
            session_id=session_id,
            workspace_slug=workspace_slug,
        )
    finally:
        db.close()


@router.get("/sessions/{session_id}/plan/topics")
async def capture_plan_topics(
    session_id: str,
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
) -> Dict[str, Any]:
    try:
        session = get_session(db, workspace_id=workspace.id, session_id=session_id)
        enforce_permission(
            db,
            user=user,
            workspace=workspace,
            resource_kind="capture_session",
            action="read",
            resource_attrs=_session_attrs(session),
            audit_prefix="kc",
        )
        return get_plan_topics(db, workspace_id=workspace.id, session_id=session_id)
    except ValueError as exc:
        raise _http_error_from_value_error(exc) from exc


@router.patch("/sessions/{session_id}/plan/topics")
async def capture_plan_topics_update(
    session_id: str,
    body: PlanTopicsUpdateRequest,
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
) -> Dict[str, Any]:
    try:
        session = get_session(db, workspace_id=workspace.id, session_id=session_id)
        enforce_permission(
            db,
            user=user,
            workspace=workspace,
            resource_kind="capture_session",
            action="update",
            resource_attrs=_session_attrs(session),
            audit_prefix="kc",
        )
        updated = update_plan_topics(
            db,
            workspace_id=workspace.id,
            session_id=session_id,
            topics=body.topics,
            actor_user_id=user.id,
        )
    except ValueError as exc:
        raise _http_error_from_value_error(exc) from exc
    return serialize_session(updated, surface="plan")


@router.post("/sessions/{session_id}/plan/validate-topics")
def capture_plan_validate_topics(
    session_id: str,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
) -> Dict[str, Any]:
    try:
        session = get_session(db, workspace_id=workspace.id, session_id=session_id)
        enforce_permission(
            db,
            user=user,
            workspace=workspace,
            resource_kind="capture_session",
            action="update",
            resource_attrs=_session_attrs(session),
            audit_prefix="kc",
        )
        validated = validate_plan_topics(
            db,
            workspace_id=workspace.id,
            session_id=session_id,
            actor_user_id=user.id,
        )
        from app.db.base import SessionLocal

        background_tasks.add_task(
            _run_question_bank_generation,
            SessionLocal,
            workspace_id=workspace.id,
            session_id=session_id,
            workspace_slug=workspace.slug,
        )
    except ValueError as exc:
        raise _http_error_from_value_error(exc) from exc
    return serialize_session(validated, surface="plan")


@router.get("/sessions/{session_id}/hint-queue")
async def capture_hint_queue(
    session_id: str,
    subtopic_id: Optional[str] = Query(default=None),
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
) -> Dict[str, Any]:
    try:
        session = get_session(db, workspace_id=workspace.id, session_id=session_id)
        enforce_permission(
            db,
            user=user,
            workspace=workspace,
            resource_kind="capture_session",
            action="read",
            resource_attrs=_session_attrs(session),
            audit_prefix="kc",
        )
        return get_hint_queue(
            db,
            workspace_id=workspace.id,
            session_id=session_id,
            subtopic_id=subtopic_id,
        )
    except ValueError as exc:
        raise _http_error_from_value_error(exc) from exc


@router.post("/sessions/{session_id}/pause")
async def pause_capture_session_endpoint(
    session_id: str,
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
) -> Dict[str, Any]:
    try:
        session = get_session(db, workspace_id=workspace.id, session_id=session_id)
        enforce_permission(
            db,
            user=user,
            workspace=workspace,
            resource_kind="capture_session",
            action="update",
            resource_attrs=_session_attrs(session),
            audit_prefix="kc",
        )
        paused = pause_capture_session(
            db,
            workspace_id=workspace.id,
            session_id=session_id,
            actor_user_id=user.id,
        )
    except ValueError as exc:
        raise _http_error_from_value_error(exc) from exc
    return serialize_session(paused)


@router.post("/sessions/{session_id}/resume")
async def resume_capture_session_endpoint(
    session_id: str,
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
) -> Dict[str, Any]:
    try:
        session = get_session(db, workspace_id=workspace.id, session_id=session_id)
        enforce_permission(
            db,
            user=user,
            workspace=workspace,
            resource_kind="capture_session",
            action="execute",
            resource_attrs=_session_attrs(session),
            audit_prefix="kc",
        )
        resumed = resume_capture_session(
            db,
            workspace_id=workspace.id,
            session_id=session_id,
            actor_user_id=user.id,
        )
    except ValueError as exc:
        raise _http_error_from_value_error(exc) from exc
    return serialize_session(resumed)


@router.post("/sessions/{session_id}/proposal/export")
async def export_capture_proposal(
    session_id: str,
    body: ProposalExportRequest,
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
) -> Dict[str, Any]:
    try:
        session = get_session(db, workspace_id=workspace.id, session_id=session_id)
        enforce_permission(
            db,
            user=user,
            workspace=workspace,
            resource_kind="capture_session",
            action="read",
            resource_attrs=_session_attrs(session),
            audit_prefix="kc",
        )
        markdown = export_session_proposal_markdown(
            db,
            workspace_id=workspace.id,
            session_id=session_id,
            proposal_id=body.proposal_id,
            executive_summary=body.executive_summary,
        )
    except ValueError as exc:
        raise _http_error_from_value_error(exc) from exc
    return {"markdown": markdown}


@router.get("/sessions/{session_id}/closure-sheet")
async def get_capture_closure_sheet(
    session_id: str,
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
) -> Dict[str, Any]:
    try:
        session = get_session(db, workspace_id=workspace.id, session_id=session_id)
        enforce_permission(
            db,
            user=user,
            workspace=workspace,
            resource_kind="capture_session",
            action="read",
            resource_attrs=_session_attrs(session),
            audit_prefix="kc",
        )
        events = list_capture_events(db, workspace_id=workspace.id, session_id=session_id)
        payload = build_session_closure_sheet(session, events)
        stored = (session.metrics or {}).get("closure_sheet")
        if stored:
            payload["markdown"] = stored
    except ValueError as exc:
        raise _http_error_from_value_error(exc) from exc
    return payload


@router.post("/sessions/{session_id}/closure")
async def apply_capture_session_closure(
    session_id: str,
    body: SessionClosureRequest,
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
) -> Dict[str, Any]:
    try:
        session = get_session(db, workspace_id=workspace.id, session_id=session_id)
        enforce_permission(
            db,
            user=user,
            workspace=workspace,
            resource_kind="capture_session",
            action="execute",
            resource_attrs=_session_attrs(session),
            audit_prefix="kc",
        )
        return apply_session_closure_action(
            db,
            workspace_id=workspace.id,
            session_id=session_id,
            action=body.action,
            actor_user_id=user.id,
            extension_minutes=body.extension_minutes,
        )
    except ValueError as exc:
        raise _http_error_from_value_error(exc) from exc


@router.post("/sessions/{session_id}/extend")
async def extend_capture_session_endpoint(
    session_id: str,
    body: SessionClosureRequest,
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
) -> Dict[str, Any]:
    try:
        session = get_session(db, workspace_id=workspace.id, session_id=session_id)
        enforce_permission(
            db,
            user=user,
            workspace=workspace,
            resource_kind="capture_session",
            action="execute",
            resource_attrs=_session_attrs(session),
            audit_prefix="kc",
        )
        extended = extend_capture_session(
            db,
            workspace_id=workspace.id,
            session_id=session_id,
            extension_minutes=body.extension_minutes,
            actor_user_id=user.id,
        )
    except ValueError as exc:
        raise _http_error_from_value_error(exc) from exc
    return serialize_session(extended)


@router.post("/proposals/{proposal_id}/publish")
async def publish_capture_proposal(
    proposal_id: str,
    body: Optional[ProposalPublishRequest] = None,
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
) -> Dict[str, Any]:
    try:
        existing, session = _load_proposal_with_session(db, workspace_id=workspace.id, proposal_id=proposal_id)
        enforce_permission(
            db,
            user=user,
            workspace=workspace,
            resource_kind="knowledge_proposal",
            action="trigger_ingestion",
            resource_attrs=_proposal_attrs(existing, session),
            audit_prefix="kc",
        )
        return await publish_proposal_to_knowledge(
            db,
            workspace=workspace,
            proposal_id=proposal_id,
            actor_label=_actor_label(user),
            category=body.category if body else None,
            destination=body.destination if body else None,
        )
    except ValueError as exc:
        raise _http_error_from_value_error(exc) from exc
