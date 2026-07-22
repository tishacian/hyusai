"""Expert Knowledge Capture API.

This surface turns a workspace Context / Knowledge scope into a guided
interview plan, captures expert answers, evaluates whether a relance is
needed, and emits a reviewable knowledge update proposal.
"""
from __future__ import annotations

import base64
import binascii
import os
import tempfile
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session as DBSession

from app.core.auth import get_current_user, get_current_workspace
from app.core.iam.dependencies import (
    current_membership,
    enforce_permission,
    require_any_app_entitlement,
)
from app.core.iam.roles import WORKSPACE_CONTRIBUTOR, normalize_role_template
from app.core.logging import get_logger
from app.db.base import get_db
from app.models.expert_capture import ExpertCaptureSession, KnowledgeUpdateProposal
from app.models.system import System
from app.models.user import Message, User
from app.models.workspace import Workspace
from app.services.audit_logger import emit_audit_event
from app.services.capture_templates import (
    get_capture_template,
    list_capture_templates,
    template_id_from_system_settings,
)
from app.services.iam.app_entitlements import FSE_REPORTS_APP, KNOWLEDGE_CAPTURE_APP
from app.services.iam.config_service import effective_role_flags, load_iam_config
from app.services.iam.decision_plane import enforce_action
from app.services.iam.manifest import REVIEW_ROLES
from app.services.knowledge_capture import (
    amend_capture_event,
    amend_capture_plan,
    answer_proposal_open_question,
    append_turn,
    apply_proposal_report_instruction,
    apply_session_closure_action,
    approve_capture_plan,
    archive_capture_session,
    build_capture_documents_collection,
    build_capture_feed,
    build_chat_correction_acknowledgement,
    build_open_questions,
    build_quality_backlog,
    build_session_closure_sheet,
    capture_document_collection_slug,
    create_capture_plan,
    create_chat_correction_proposal,
    create_update_proposal,
    defer_quality_item,
    delete_capture_session,
    export_session_proposal_markdown,
    extend_capture_session,
    finalize_capture,
    finalize_plan_from_dialogue,
    generate_question_bank,
    generate_session_closure_sheet,
    get_hint_queue,
    get_plan_topics,
    get_session,
    is_expert_review_required,
    is_free_conversation_session,
    list_capture_events,
    list_published_fiches,
    pause_capture_session,
    prefetch_capture_retrieval,
    process_conversation_step,
    process_plan_dialogue_turn,
    publish_proposal_to_knowledge,
    record_capture_document_view,
    register_capture_documents,
    resume_capture_session,
    review_proposal,
    run_capture_finalize_index,
    serialize_event,
    serialize_proposal,
    serialize_session,
    session_has_proposal_material,
    session_is_archived,
    set_capture_documents_full_share,
    set_capture_documents_share_level,
    start_session,
    summarize_chat_correction_theme,
    update_capture_session_flags,
    update_capture_view_anchor,
    update_oracle_question_statuses,
    update_plan_topics,
    update_proposal_open_question_statuses,
    update_proposal_report_content,
    validate_plan_topics,
    warm_capture_context_cache,
)
from app.services.knowledge_collections import (
    create_or_get_collection,
    original_key,
    update_collection_status,
    upsert_collection_source,
)
from app.services.object_store import get_object_store
from app.services.rag.knowledge_scopes import resolve_expert_fiche_collection
from app.services.systems.bootstrap import resolve_workspace_chat_source_policy
from app.services.voice_runtime import list_voice_runtime_providers

router = APIRouter(
    dependencies=[Depends(require_any_app_entitlement(KNOWLEDGE_CAPTURE_APP, FSE_REPORTS_APP))]
)
logger = get_logger(__name__)

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


def _as_dict(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _resolve_chat_source_policy(db: DBSession, workspace: Workspace) -> Dict[str, Any]:
    """Resolve the workspace chat ``source_policy`` the same way chat does.

    Delegates to the shared resolver so the inline-correction surface folds in
    the exact policy the chat endpoint uses: the workspace chat System settings
    (then its flow definition) layered over the workspace-level
    ``settings.source_policy``. This means ``expert_fiche_correction_enabled``
    is honoured whether it is set on the chat System or on the workspace
    settings (the location the chat frontend reads), keeping the CTA gate and
    the backend 403 enforcement consistent.
    """
    return resolve_workspace_chat_source_policy(db, workspace)


def _resolve_workspace_source_policy(workspace: Workspace) -> Dict[str, Any]:
    """Resolve the workspace-level ``source_policy`` for the capture surface.

    System captures have no chat System, so the review gate reads the
    workspace ``settings.source_policy`` directly (the location the migration /
    workbench writes ``expert_review_required`` to).
    """
    return _as_dict(_as_dict(getattr(workspace, "settings", None)).get("source_policy"))


def _auto_accept_capture_proposal_if_review_disabled(
    db: DBSession,
    *,
    workspace: Workspace,
    user: User,
    proposal: KnowledgeUpdateProposal,
) -> KnowledgeUpdateProposal:
    # Review-disabled capture removes reviewer arbitration only. Publishing must
    # stay explicit from the publish step.
    source_policy = _resolve_workspace_source_policy(workspace)
    if is_expert_review_required(source_policy) or proposal.status != "pending_review":
        return proposal
    try:
        review_proposal(
            db,
            workspace_id=workspace.id,
            proposal_id=proposal.id,
            status="accepted",
            reviewer="auto",
            review_notes="auto-validée (revue désactivée)",
        )
        db.refresh(proposal)
    except Exception:  # noqa: BLE001 — never lose the capture on auto-review failure.
        logger.exception(
            "kc.capture_proposal.auto_review_failed",
            proposal_id=proposal.id,
            workspace_id=workspace.id,
            actor=_actor_label(user),
        )
    return proposal


_AUDIO_CONTENT_TYPE_EXTENSIONS = {
    "audio/webm": ".webm",
    "audio/ogg": ".ogg",
    "audio/oga": ".ogg",
    "audio/mp4": ".m4a",
    "audio/x-m4a": ".m4a",
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/wave": ".wav",
}


def _audio_extension(content_type: Optional[str]) -> str:
    key = str(content_type or "").split(";")[0].strip().lower()
    return _AUDIO_CONTENT_TYPE_EXTENSIONS.get(key, ".webm")


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


async def _run_warm_capture_context_cache(
    session_factory,
    *,
    workspace_id: str,
    workspace_slug: Optional[str],
    session_id: str,
) -> None:
    db = session_factory()
    try:
        await warm_capture_context_cache(
            db,
            workspace_id=workspace_id,
            workspace_slug=workspace_slug,
            session_id=session_id,
        )
    except Exception as exc:  # noqa: BLE001 - warmup must never block capture.
        logger.warning("Knowledge Capture retrieval warm cache failed", error=str(exc), session_id=session_id)
    finally:
        db.close()


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
    plan_source_kind: Optional[Literal["manual", "pasted_text", "uploaded_file", "conversation"]] = None
    plan_source_filename: Optional[str] = None
    plan_source_replaces_existing_plan: bool = False
    header_fields: Optional[Dict[str, Any]] = None
    template_id: Optional[str] = None


class PlanDialogueTurnRequest(BaseModel):
    text: str = Field(default="", min_length=0)
    confirm_finalize: bool = False


class SessionFlagsRequest(BaseModel):
    defer_weak_contradictions: Optional[bool] = None
    suppress_oracle_questions: Optional[bool] = None
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
    destination_scope: Optional[str] = None
    final_title: Optional[str] = None
    include_unresolved_questions: bool = True


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
    input_modality: Literal["voice", "text"] = "text"
    document_refs: List[Dict[str, Any]] = Field(default_factory=list)
    visual_context: Optional[Dict[str, Any]] = None


class CaptureFullShareRequest(BaseModel):
    document_ids: List[str] = Field(default_factory=list)


class CaptureShareLevelItem(BaseModel):
    document_id: str
    share_level: Literal["full", "excerpt", "none"]


class CaptureShareLevelRequest(BaseModel):
    items: List[CaptureShareLevelItem] = Field(default_factory=list)


class CaptureViewUpdateRequest(BaseModel):
    action: Literal["confirm", "discard", "rebind"]
    document_id: Optional[str] = None
    collection: Optional[str] = None
    filename: Optional[str] = None
    title: Optional[str] = None
    page: Optional[int] = Field(default=None, ge=1)
    slide: Optional[int] = Field(default=None, ge=1)
    image_index: Optional[int] = Field(default=None, ge=1)


class CaptureDocumentViewRequest(BaseModel):
    document_id: Optional[str] = None
    collection: Optional[str] = None
    collection_name: Optional[str] = None
    filename: Optional[str] = None
    title: Optional[str] = None
    page: Optional[int] = Field(default=None, ge=1)
    page_number: Optional[int] = Field(default=None, ge=1)
    slide: Optional[int] = Field(default=None, ge=1)
    image_index: Optional[int] = Field(default=None, ge=1)
    preview: Optional[str] = None
    association_mode: str = "active_view"


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


class ProposalInstructionRequest(BaseModel):
    instruction: str = Field(..., min_length=1)
    current_content: Optional[str] = None


class ProposalOpenQuestionStatusItem(BaseModel):
    question_key: Optional[str] = None
    question_id: Optional[str] = None
    question_text: Optional[str] = None
    # Unified lifecycle: open | answered | invalid | deferred. Legacy "dismissed"
    # is still accepted and mapped to "invalid" server-side.
    status: Literal["open", "answered", "invalid", "deferred", "dismissed"] = "open"


class ProposalOpenQuestionStatusRequest(BaseModel):
    items: List[ProposalOpenQuestionStatusItem] = Field(default_factory=list)


class ProposalOpenQuestionAnswerRequest(BaseModel):
    text: str = Field(..., min_length=1)


class EventAmendRequest(BaseModel):
    text_amended: str = Field(..., min_length=1)
    actor: Optional[str] = None
    reason: Optional[str] = None


class ChatCorrectionRequest(BaseModel):
    query: str = Field(..., min_length=1)
    answer: str = Field(default="")
    correction: str = Field(..., min_length=1)
    message_id: Optional[str] = None
    session_id: Optional[str] = None
    sources: Optional[List[Any]] = None
    transcript_raw: Optional[str] = None
    audio_base64: Optional[str] = None
    audio_content_type: Optional[str] = None
    audio_ref: Optional[str] = None
    input_modality: Optional[str] = "text"


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


@router.get("/templates")
async def list_capture_session_templates(
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
        resource_attrs={"capability": CAPTURE_CAPABILITY},
        audit_prefix="kc",
    )
    return {"templates": list_capture_templates()}


@router.get("/templates/{template_id}")
async def get_capture_session_template(
    template_id: str,
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
        resource_attrs={"capability": CAPTURE_CAPABILITY},
        audit_prefix="kc",
    )
    template = get_capture_template(template_id)
    if not template:
        raise HTTPException(status_code=404, detail=f"Capture template not found: {template_id}")
    return template


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
    requested_template_id = str(body.template_id or "").strip()
    if requested_template_id:
        template = get_capture_template(requested_template_id)
        if template is None:
            raise HTTPException(status_code=400, detail="Unknown capture template")
        bound_system = None
        if body.system_id:
            bound_system = (
                db.query(System)
                .filter(
                    System.id == body.system_id,
                    System.workspace_id == workspace.id,
                    System.status != "retired",
                )
                .first()
            )
        bound_template_id = template_id_from_system_settings(
            bound_system.settings if bound_system else None
        )
        if bound_template_id != requested_template_id:
            raise HTTPException(
                status_code=400,
                detail="Capture template requires a matching active system_id",
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
            plan_source_kind=body.plan_source_kind,
            plan_source_filename=body.plan_source_filename,
            plan_source_replaces_existing_plan=body.plan_source_replaces_existing_plan,
            created_by_user_id=user.id,
            header_fields=body.header_fields,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        await warm_capture_context_cache(
            db,
            workspace_id=workspace.id,
            workspace_slug=workspace.slug,
            session_id=session.id,
        )
        db.refresh(session)
    except Exception as exc:  # noqa: BLE001 - cache warmup must never block planning.
        logger.warning("Knowledge Capture retrieval warm cache failed", error=str(exc), session_id=session.id)
    return serialize_session(session)


@router.get("/sessions")
async def list_capture_sessions(
    status: Optional[str] = None,
    domain: Optional[str] = None,
    system_id: Optional[str] = None,
    include_archived: bool = False,
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
    rows = q.order_by(ExpertCaptureSession.updated_at.desc()).all()
    if not include_archived:
        rows = [row for row in rows if not session_is_archived(row)]
    if domain:
        domain_key = domain.strip().lower()
        rows = [
            row
            for row in rows
            if ((row.metrics or {}).get("capture_domain") or "").lower() == domain_key
        ]
    rows = rows[:limit]
    return {"sessions": [serialize_session(row) for row in rows]}


@router.post("/sessions/{session_id}/archive")
async def archive_capture_session_endpoint(
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
        session = archive_capture_session(
            db,
            workspace_id=workspace.id,
            session_id=session_id,
            archived=True,
            actor_user_id=user.id,
        )
    except ValueError as exc:
        raise _http_error_from_value_error(exc) from exc
    return serialize_session(session)


@router.post("/sessions/{session_id}/unarchive")
async def unarchive_capture_session_endpoint(
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
        session = archive_capture_session(
            db,
            workspace_id=workspace.id,
            session_id=session_id,
            archived=False,
            actor_user_id=user.id,
        )
    except ValueError as exc:
        raise _http_error_from_value_error(exc) from exc
    return serialize_session(session)


@router.delete("/sessions/{session_id}")
async def delete_capture_session_endpoint(
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
        delete_capture_session(db, workspace_id=workspace.id, session_id=session_id)
    except ValueError as exc:
        raise _http_error_from_value_error(exc) from exc
    return {"deleted": True, "session_id": session_id}


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
        from app.db.base import SessionLocal

        background_tasks.add_task(
            _run_warm_capture_context_cache,
            SessionLocal,
            workspace_id=workspace.id,
            workspace_slug=workspace.slug,
            session_id=session_id,
        )
        if (
            prior_qbank_status == "idle"
            and (session.plan or {}).get("question_bank_status") == "generating"
        ):
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
            input_modality=body.input_modality,
            document_refs=body.document_refs,
            visual_context=body.visual_context,
            # Text notes entered during live capture must follow the same hot-path
            # contract as voice turns: persist the business statement, but leave
            # evaluation/relance/oracle work to the async/final pipelines.
            compute_evaluation=body.input_modality != "text",
        )
    except ValueError as exc:
        raise _http_error_from_value_error(exc) from exc


@router.get("/sessions/{session_id}/documents")
async def list_capture_session_documents(
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
        return build_capture_documents_collection(db, workspace_id=workspace.id, session=session)
    except ValueError as exc:
        raise _http_error_from_value_error(exc) from exc


@router.post("/sessions/{session_id}/documents")
async def upload_capture_session_documents(
    session_id: str,
    files: List[UploadFile] = File(...),
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
) -> Dict[str, Any]:
    """Store the uploaded originals ONLY — no ingestion during the session.

    Per the fluid-capture pipeline the session collection stays empty until the
    end-of-capture background batch: here we persist the original bytes, register
    each doc in the ``capture_documents`` state with ``index_status=not_indexed``
    and record the upload event. No DocumentService ingestion, no worker dispatch.
    """
    if not files:
        raise HTTPException(status_code=422, detail="At least one file is required")
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
        collection_slug = capture_document_collection_slug(session_id)
        collection = create_or_get_collection(
            db,
            workspace=workspace,
            name=f"Capture session {session.title[:80]}",
            description="Draft documents uploaded during an expert capture session",
            created_by_user_id=user.id,
            slug=collection_slug,
        )
        store = get_object_store()
        existing_names = list(collection.document_names or [])
        documents: List[Dict[str, Any]] = []
        for file in files:
            safe_name = Path(file.filename or "upload").name.replace("/", "_").replace("\\", "_")
            content = await file.read()
            store.write_bytes(original_key(collection, safe_name), content)
            upsert_collection_source(
                db,
                collection=collection,
                filename=safe_name,
                status="queued",
                mime_type=file.content_type,
                origin="capture_session_upload",
                size_bytes=len(content),
                source_metadata={
                    "capture_session_id": session_id,
                    "uploaded_by_user_id": user.id,
                    "source": "capture_session_upload",
                },
            )
            if safe_name not in existing_names:
                existing_names.append(safe_name)
            documents.append(
                {
                    "document_id": safe_name,
                    "filename": safe_name,
                    "status": "stored",
                    "index_status": "not_indexed",
                    "chunks_processed": 0,
                }
            )
        # Collection metadata is tracked, but the collection stays un-ingested
        # ("queued" = stored, awaiting the end-of-capture batch).
        update_collection_status(
            db,
            collection.id,
            status="queued",
            document_names=existing_names,
            document_count=len(existing_names),
        )
        db.commit()
        registered = register_capture_documents(
            db,
            workspace_id=workspace.id,
            session_id=session_id,
            collection=collection.slug,
            documents=documents,
            actor_user_id=user.id,
        )
        return build_capture_documents_collection(
            db,
            workspace_id=workspace.id,
            session=get_session(db, workspace_id=workspace.id, session_id=session_id),
        ) | {"session": registered.get("session")}
    except ValueError as exc:
        raise _http_error_from_value_error(exc) from exc
    except Exception as exc:  # noqa: BLE001
        logger.error("capture document upload failed", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/sessions/{session_id}/documents/view")
async def record_capture_session_document_view(
    session_id: str,
    body: CaptureDocumentViewRequest,
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
        payload = body.model_dump(exclude_none=True)
        payload.setdefault("collection", capture_document_collection_slug(session_id))
        return record_capture_document_view(
            db,
            workspace_id=workspace.id,
            session_id=session_id,
            view=payload,
            actor_user_id=user.id,
        )
    except ValueError as exc:
        raise _http_error_from_value_error(exc) from exc


@router.post("/sessions/{session_id}/documents/full-share")
async def select_capture_session_full_share(
    session_id: str,
    body: CaptureFullShareRequest,
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
) -> Dict[str, Any]:
    """End-of-capture triage: mark which docs to index in FULL.

    Records the ``full_share`` selection on ``capture_documents`` state; no
    ingestion happens here (the background finalize batch reads the flags).
    Returns the updated documents collection (same shape as GET documents).
    """
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
        return set_capture_documents_full_share(
            db,
            workspace_id=workspace.id,
            session_id=session_id,
            document_ids=body.document_ids,
            actor_user_id=user.id,
        )
    except ValueError as exc:
        raise _http_error_from_value_error(exc) from exc


@router.post("/sessions/{session_id}/documents/share-level")
async def select_capture_session_share_level(
    session_id: str,
    body: CaptureShareLevelRequest,
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
) -> Dict[str, Any]:
    """End-of-capture triage: set each doc's ``share_level`` {full|excerpt|none}.

    Records the per-doc selection on ``capture_documents`` state; no ingestion
    happens here (the background finalize batch reads ``share_level``). Returns
    the updated documents collection (same shape as GET documents).
    """
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
        return set_capture_documents_share_level(
            db,
            workspace_id=workspace.id,
            session_id=session_id,
            items=[item.model_dump() for item in body.items],
            actor_user_id=user.id,
        )
    except ValueError as exc:
        raise _http_error_from_value_error(exc) from exc


@router.post("/sessions/{session_id}/views/{event_id}")
async def update_capture_session_view(
    session_id: str,
    event_id: str,
    body: CaptureViewUpdateRequest,
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
) -> Dict[str, Any]:
    """Correct a journaled anchor: confirm / discard / rebind.

    Patches the ``capture_view_referenced`` event ``meta_data`` (status,
    confidence, and on rebind the doc/view target). Returns the updated view ref.
    """
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
        return update_capture_view_anchor(
            db,
            workspace_id=workspace.id,
            session_id=session_id,
            event_id=event_id,
            action=body.action,
            document_id=body.document_id,
            collection=body.collection,
            filename=body.filename,
            title=body.title,
            page=body.page,
            slide=body.slide,
            image_index=body.image_index,
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


@router.get("/sessions/{session_id}/feed")
async def get_session_feed(
    session_id: str,
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
) -> Dict[str, Any]:
    """Typed projection of the event ledger into the ordered "Le Fil" feed (D1
    step C): ``speak`` (voice turn) / ``note`` (text turn) / ``anchor`` (deictic
    reference, with status + confidence). The Fil hydrates from this on load /
    resume, then appends live WS events."""
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
        feed = build_capture_feed(db, workspace_id=workspace.id, session_id=session_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"feed": feed}


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
            resource_kind="knowledge_proposal",
            action="submit_review",
            resource_attrs=_session_attrs(session),
            audit_prefix="kc",
        )
        # FINAL per-section reformulation (finalize_capture) is the canonical
        # report builder. The HTTP finalize path (LiveKit transport) used to only
        # reach it for free-conversation sessions and fell into the raw
        # create_update_proposal builder whenever the session had a plan — which
        # is why the LiveKit review fiche showed verbatim turns. Run
        # finalize_capture for ANY session that carries proposal material (free
        # conversation OR plan-driven). create_update_proposal stays as a
        # defensive fallback: no material to reformulate, or finalize_capture
        # raised.
        proposal = None
        if session_has_proposal_material(
            db,
            workspace_id=workspace.id,
            session=session,
        ):
            try:
                proposal = await finalize_capture(
                    db,
                    workspace_id=workspace.id,
                    session_id=session_id,
                    workspace_slug=workspace.slug,
                    created_by_user_id=user.id,
                )
            except Exception as exc:  # noqa: BLE001 - fall back to the raw builder.
                logger.warning(
                    "capture_proposal_finalize_failed_fallback_raw",
                    session_id=session_id,
                    error=str(exc),
                )
                db.rollback()
                proposal = None
        if proposal is None:
            proposal = create_update_proposal(
                db,
                workspace_id=workspace.id,
                session_id=session_id,
                created_by_user_id=user.id,
            )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    proposal = _auto_accept_capture_proposal_if_review_disabled(
        db,
        workspace=workspace,
        user=user,
        proposal=proposal,
    )
    _schedule_capture_finalize_index(background_tasks, workspace_id=workspace.id, session_id=session_id)
    return serialize_proposal(proposal)


@router.get("/fiches")
async def list_published_capture_fiches(
    category: Optional[str] = None,
    destination: Optional[str] = None,
    author_user_id: Optional[str] = None,
    published_after: Optional[str] = None,
    published_before: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
) -> Dict[str, Any]:
    """List published knowledge capture outputs for the workspace.

    Published fiches are workspace-wide: unlike capture sessions, they are
    visible to every member who can read the capture capability.
    """
    enforce_permission(
        db,
        user=user,
        workspace=workspace,
        resource_kind="capture_session",
        action="read",
        resource_attrs={"capability": CAPTURE_CAPABILITY, "owner_user_id": user.id},
        audit_prefix="kc",
    )
    return list_published_fiches(
        db,
        workspace_id=workspace.id,
        current_user_id=user.id,
        category=category,
        destination=destination,
        author_user_id=author_user_id,
        published_after=published_after,
        published_before=published_before,
        q=q,
        limit=limit,
        offset=offset,
    )


@router.get("/proposals")
async def list_capture_proposals(
    status: Optional[str] = None,
    system_id: Optional[str] = None,
    session_id: Optional[str] = None,
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
    if session_id:
        q = q.filter(KnowledgeUpdateProposal.session_id == session_id)
    joined_session = False
    if _contributors_see_only_own(db, user=user, workspace=workspace):
        q = q.join(ExpertCaptureSession, ExpertCaptureSession.id == KnowledgeUpdateProposal.session_id)
        joined_session = True
        q = q.filter(
            or_(
                KnowledgeUpdateProposal.created_by_user_id == user.id,
                ExpertCaptureSession.created_by_user_id == user.id,
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
        attrs = _proposal_attrs(existing, session)
        enforce_permission(
            db,
            user=user,
            workspace=workspace,
            resource_kind="knowledge_proposal",
            action="review_decide",
            resource_attrs=attrs,
            audit_prefix="kc",
        )
        enforce_action(
            db,
            user=user,
            workspace=workspace,
            resource_kind="decision",
            action="approve",
            legacy_allowed=True,
            resource_attrs={
                "decision_id": proposal_id,
                "owner_user_id": attrs.get("owner_user_id"),
            },
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
            reviewer=_actor_label(user),
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


@router.patch("/proposals/{proposal_id}/open-questions")
async def update_capture_proposal_open_questions(
    proposal_id: str,
    body: ProposalOpenQuestionStatusRequest,
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
        proposal = update_proposal_open_question_statuses(
            db,
            workspace_id=workspace.id,
            proposal_id=proposal_id,
            items=[item.dict() for item in body.items],
            actor_user_id=user.id,
            actor_label=_actor_label(user),
        )
    except ValueError as exc:
        raise _http_error_from_value_error(exc) from exc
    return serialize_proposal(proposal)


@router.post("/proposals/{proposal_id}/open-questions/{question_id}/answer")
async def answer_capture_proposal_open_question(
    proposal_id: str,
    question_id: str,
    body: ProposalOpenQuestionAnswerRequest,
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
) -> Dict[str, Any]:
    """Answer ONE open question: inject the answer into its plan section, mark it
    answered and re-synthesize ONLY that section (targeted, not a full rebuild).

    Voice answers arrive as already-transcribed text (the frontend transcribes via
    the existing voice endpoint, then calls this).
    """
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
        proposal = await answer_proposal_open_question(
            db,
            workspace_id=workspace.id,
            proposal_id=proposal_id,
            question_id=question_id,
            text=body.text,
            actor_user_id=user.id,
            actor_label=_actor_label(user),
            workspace_slug=workspace.slug,
        )
    except ValueError as exc:
        raise _http_error_from_value_error(exc) from exc
    return serialize_proposal(proposal)


@router.post("/proposals/{proposal_id}/instruction")
async def apply_capture_proposal_instruction(
    proposal_id: str,
    body: ProposalInstructionRequest,
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
        proposal = await apply_proposal_report_instruction(
            db,
            workspace_id=workspace.id,
            proposal_id=proposal_id,
            instruction=body.instruction,
            current_content=body.current_content,
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
            suppress_oracle_questions=body.suppress_oracle_questions,
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


def _schedule_capture_finalize_index(
    background_tasks: BackgroundTasks,
    *,
    workspace_id: str,
    session_id: str,
) -> None:
    """Queue the end-of-capture indexing batch after the response is sent.

    Decoupled from the report return: the report cites sources from the journaled
    refs directly, while this batch extracts/indexes the referenced views and the
    full-share docs in the background. The job is idempotent and guards against
    concurrent double-runs, so triggering from every finalize path is safe.
    """
    from app.db.base import SessionLocal

    background_tasks.add_task(
        run_capture_finalize_index,
        SessionLocal,
        workspace_id=workspace_id,
        session_id=session_id,
    )


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
            action="execute",
            resource_attrs=_session_attrs(session),
            audit_prefix="kc",
        )
        normalized_action = (body.action or "finish").strip().lower()
        if normalized_action == "finish":
            # The capture is wrapping up: kick the background indexing batch
            # (referenced views + full-share docs) regardless of which finalize
            # branch runs below. Idempotent + decoupled from the report return.
            _schedule_capture_finalize_index(background_tasks, workspace_id=workspace.id, session_id=session_id)
        if normalized_action == "finish" and is_free_conversation_session(session) and session_has_proposal_material(
            db,
            workspace_id=workspace.id,
            session=session,
        ):
            proposal = await finalize_capture(
                db,
                workspace_id=workspace.id,
                session_id=session_id,
                workspace_slug=workspace.slug,
                created_by_user_id=user.id,
            )
            proposal = _auto_accept_capture_proposal_if_review_disabled(
                db,
                workspace=workspace,
                user=user,
                proposal=proposal,
            )
            refreshed = get_session(db, workspace_id=workspace.id, session_id=session_id)
            closure = build_session_closure_sheet(
                refreshed,
                list_capture_events(db, workspace_id=workspace.id, session_id=session_id),
            )
            return {
                "action": "finish",
                "session": serialize_session(refreshed),
                "closure_sheet": closure,
                "proposal": serialize_proposal(proposal),
            }
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
        attrs = _proposal_attrs(existing, session)
        enforce_permission(
            db,
            user=user,
            workspace=workspace,
            resource_kind="knowledge_proposal",
            action="trigger_ingestion",
            resource_attrs=attrs,
            audit_prefix="kc",
        )
        enforce_action(
            db,
            user=user,
            workspace=workspace,
            resource_kind="knowledge_proposal",
            action="publish",
            legacy_allowed=True,
            resource_attrs={
                "owner_user_id": attrs.get("owner_user_id"),
            },
        )
        return await publish_proposal_to_knowledge(
            db,
            workspace=workspace,
            proposal_id=proposal_id,
            actor_label=_actor_label(user),
            category=body.category if body else None,
            destination=(body.destination_scope or body.destination) if body else None,
            final_title=body.final_title if body else None,
            include_unresolved_questions=body.include_unresolved_questions if body else None,
        )
    except ValueError as exc:
        raise _http_error_from_value_error(exc) from exc


_CHAT_CORRECTION_AUDIO_MAX_BYTES = 25 * 1024 * 1024


@router.post("/chat-correction")
async def submit_chat_correction(
    body: ChatCorrectionRequest,
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
) -> Dict[str, Any]:
    """Turn an inline chat correction/completion into a ``pending_review`` proposal.

    Reserved to ``REVIEW_ROLES`` via the ``knowledge_proposal:chat_correct``
    rule and gated by the per-workspace ``expert_fiche_correction_enabled``
    source-policy flag (403 when off, so the frontend degrades gracefully).
    """
    enforce_permission(
        db,
        user=user,
        workspace=workspace,
        resource_kind="knowledge_proposal",
        action="chat_correct",
        resource_attrs={"capability": CAPTURE_CAPABILITY},
        audit_prefix="kc",
    )

    source_policy = _resolve_chat_source_policy(db, workspace)
    if not source_policy.get("expert_fiche_correction_enabled"):
        raise HTTPException(
            status_code=403,
            detail="Expert fiche correction is disabled for this workspace.",
        )

    correction_text = body.correction.strip()
    if not correction_text:
        raise HTTPException(status_code=400, detail="Chat correction cannot be empty.")

    collection_slug = resolve_expert_fiche_collection(workspace, source_policy)

    audio_ref = (body.audio_ref or "").strip() or None
    if not audio_ref and body.audio_base64:
        try:
            raw_audio = base64.b64decode(body.audio_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise HTTPException(status_code=400, detail="Invalid audio_base64 payload.") from exc
        if len(raw_audio) > _CHAT_CORRECTION_AUDIO_MAX_BYTES:
            raise HTTPException(status_code=413, detail="Audio payload exceeds the 25 MB limit.")
        if raw_audio:
            store = get_object_store()
            capture_ref = uuid.uuid4().hex
            audio_ref = store.key(
                "workspaces",
                workspace.id,
                "expert-fiche-captures",
                collection_slug,
                capture_ref,
                f"audio{_audio_extension(body.audio_content_type)}",
            )
            store.write_bytes(audio_ref, raw_audio)

    try:
        proposal, session = create_chat_correction_proposal(
            db,
            workspace=workspace,
            user=user,
            query=body.query,
            assistant_answer=body.answer,
            correction_text=correction_text,
            sources=body.sources,
            transcript_raw=body.transcript_raw,
            audio_ref=audio_ref,
            input_modality=body.input_modality or "text",
            source_policy=source_policy,
        )
    except ValueError as exc:
        raise _http_error_from_value_error(exc) from exc

    emit_audit_event(
        db=db,
        workspace_id=workspace.id,
        event_type="kc.chat_correction.created",
        actor=_actor_label(user),
        details={
            "proposal_id": proposal.id,
            "session_id": session.id,
            "collection": collection_slug,
            "input_modality": body.input_modality or "text",
            "message_id": body.message_id,
            "chat_session_id": body.session_id,
            "audio_ref": audio_ref,
        },
    )

    # Auto-validation: when the workspace disables expert review, accept and
    # publish immediately so the correction becomes a live expert fiche without
    # a second reviewer. Ingestion failures degrade gracefully — the proposal
    # is preserved (the correction is never lost) and a review status is
    # reported instead.
    status = "pending_review"
    document_id: Optional[str] = None
    if not is_expert_review_required(source_policy):
        try:
            attrs = _proposal_attrs(proposal, session)
            enforce_action(
                db,
                user=user,
                workspace=workspace,
                resource_kind="knowledge_proposal",
                action="publish",
                # Auto-publication existed before the granular plane. Compat
                # and shadow therefore preserve it; only an explicit enforce
                # decision can keep the correction in review.
                legacy_allowed=True,
                resource_attrs={
                    "owner_user_id": attrs.get("owner_user_id"),
                },
            )
            review_proposal(
                db,
                workspace_id=workspace.id,
                proposal_id=proposal.id,
                status="accepted",
                reviewer="auto",
                review_notes="auto-validée (revue désactivée)",
            )
            publication = await publish_proposal_to_knowledge(
                db,
                workspace=workspace,
                proposal_id=proposal.id,
                actor_label=_actor_label(user),
            )
            status = "published"
            document_id = publication.get("document_id")
        except Exception:  # noqa: BLE001 — never lose the correction on ingest failure.
            logger.exception(
                "kc.chat_correction.auto_publish_failed",
                proposal_id=proposal.id,
                workspace_id=workspace.id,
            )
            status = "pending_review"

    theme = await summarize_chat_correction_theme(
        body.query,
        correction_text,
        workspace_id=workspace.id,
    )
    acknowledgement = build_chat_correction_acknowledgement(
        theme, published=status == "published"
    )

    # Persist the acknowledgement into the chat session (mirrors the chat
    # endpoint's Message persistence) so the trace survives a reload. Only when
    # a chat session_id is supplied.
    ack_message_id: Optional[str] = None
    if body.session_id:
        ack_message_id = str(uuid.uuid4())
        db.add(
            Message(
                id=ack_message_id,
                session_id=body.session_id,
                role="assistant",
                content=acknowledgement,
                meta_data={
                    "kind": "expert_correction_ack",
                    "proposal_id": proposal.id,
                    "status": status,
                    "source_message_id": body.message_id,
                },
            )
        )
        db.commit()

    return {
        "proposal_id": proposal.id,
        "status": status,
        "collection": collection_slug,
        "document_id": document_id,
        "acknowledgement": acknowledgement,
        "ack_message_id": ack_message_id,
        "summary": theme,
        "review_queue_url": "/api/v1/knowledge-capture/proposals?status=pending_review",
    }
