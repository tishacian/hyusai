"""Session management endpoints — scoped by workspace/user."""
from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel
from typing import Dict, Any, List, Optional, Tuple
from sqlalchemy import func
from sqlalchemy.orm import Session as DBSession
from app.core.auth import get_current_user, get_current_workspace
from app.core.iam.dependencies import require_app_entitlement
from app.core.iam.roles import is_admin_template
from app.core.logging import get_logger
from app.db.base import get_db
from app.models.workspace import Workspace, WorkspaceMember
from app.models.user import Session as SessionModel, Message, User
from app.models.knowledge_collection import WorkerJob
from app.models.workspace_job import WorkspaceJob
from app.services.audit_logger import emit_audit_event
from app.services.iam.app_entitlements import CHAT_APP
from app.services.workspace_jobs import serialize_job
from datetime import datetime
import uuid

logger = get_logger(__name__)
router = APIRouter(dependencies=[Depends(require_app_entitlement(CHAT_APP))])


class SessionCreate(BaseModel):
    user_id: Optional[str] = None  # Ignored: taken from JWT
    context: Optional[Dict[str, Any]] = {}
    title: Optional[str] = None
    context_signature: Optional[str] = None


class SessionPatch(BaseModel):
    title: Optional[str] = None
    status: Optional[str] = None


def _actor(user: User) -> str:
    return user.email or user.username or user.id


def _is_workspace_admin(db: DBSession, user: User, workspace: Workspace) -> bool:
    if user.role == "admin":
        return True
    membership = (
        db.query(WorkspaceMember)
        .filter(WorkspaceMember.user_id == user.id, WorkspaceMember.workspace_id == workspace.id)
        .first()
    )
    return bool(membership and is_admin_template(membership.role_template, membership.role))


def _context_signature(context: Optional[Dict[str, Any]]) -> Optional[str]:
    if not isinstance(context, dict):
        return None
    explicit = context.get("context_signature")
    if explicit:
        return str(explicit)[:512]
    parts = [
        context.get("system_id") or "workspace",
        context.get("context_id") or "no-context",
        context.get("assistant_profile") or "default-profile",
        context.get("source_selection") or "auto",
        context.get("context_mode") or "no-session-docs",
        context.get("knowledge_scope") or "workspace-scope",
    ]
    return "|".join(str(part) for part in parts)[:512]


def _normalize_linked_object(raw: Any) -> Optional[Dict[str, Any]]:
    """Persist overlay/system linkage as ``meta_data.linked_object``."""
    if not isinstance(raw, dict):
        return None
    linked_type = str(raw.get("type") or "").strip()[:64]
    linked_id = str(raw.get("id") or "").strip()[:128]
    if not linked_type or not linked_id:
        return None
    label = str(raw.get("label") or "").strip()[:256] or linked_id
    lens_raw = raw.get("lens")
    lens = str(lens_raw).strip()[:64] if lens_raw else None
    payload: Dict[str, Any] = {
        "type": linked_type,
        "id": linked_id,
        "label": label,
    }
    if lens:
        payload["lens"] = lens
    return payload


def _session_meta_from_context(context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    meta = dict(context) if isinstance(context, dict) else {}
    linked = _normalize_linked_object(meta.get("linked_object"))
    if linked:
        meta["linked_object"] = linked
    elif "linked_object" in meta:
        meta.pop("linked_object", None)
    return meta


def _serialize_message(message: Message) -> Dict[str, Any]:
    return {
        "id": message.id,
        "role": message.role,
        "content": message.content,
        "timestamp": message.timestamp.isoformat() if message.timestamp else None,
        "meta_data": message.meta_data or {},
    }


def _build_author_lookup(db: DBSession, sessions: List[SessionModel]) -> Dict[str, User]:
    """Batch-load session authors in a single query (avoids N+1)."""
    user_ids = {s.user_id for s in sessions if getattr(s, "user_id", None)}
    if not user_ids:
        return {}
    rows = db.query(User).filter(User.id.in_(user_ids)).all()
    return {row.id: row for row in rows}


def _resolve_author_fields(user: Optional[User], user_id: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """Best-effort author label (email -> username -> id) and email."""
    email = getattr(user, "email", None) if user else None
    username = getattr(user, "username", None) if user else None
    label = str(email or username or user_id or "") or None
    return label, (str(email) if email else None)


def _serialize_session(
    session: SessionModel,
    *,
    include_messages: bool = False,
    include_jobs: bool = False,
    author_lookup: Optional[Dict[str, User]] = None,
) -> Dict[str, Any]:
    author = (author_lookup or {}).get(getattr(session, "user_id", None))
    author_label, author_email = _resolve_author_fields(author, session.user_id)
    payload: Dict[str, Any] = {
        "id": session.id,
        "user_id": session.user_id,
        "workspace_id": session.workspace_id,
        "author_label": author_label,
        "author_email": author_email,
        "title": session.title,
        "status": getattr(session, "status", None) or "active",
        "context_signature": getattr(session, "context_signature", None),
        "created_at": session.created_at.isoformat() if session.created_at else None,
        "last_activity": session.last_activity.isoformat() if session.last_activity else None,
        "archived_at": session.archived_at.isoformat() if getattr(session, "archived_at", None) else None,
        "deleted_at": session.deleted_at.isoformat() if getattr(session, "deleted_at", None) else None,
        "message_count": len(session.messages or []),
        "meta_data": session.meta_data or {},
    }
    if include_messages:
        payload["messages"] = [_serialize_message(message) for message in sorted(session.messages or [], key=lambda item: item.timestamp or datetime.min)]
    if include_jobs:
        payload["jobs"] = [serialize_job(job) for job in sorted(getattr(session, "_session_jobs", []) or [], key=lambda item: item.updated_at or item.created_at or datetime.min, reverse=True)]
    return payload


def _backfill_legacy_deep_jobs(db: DBSession, workspace: Workspace, session: SessionModel) -> None:
    legacy_jobs = (
        db.query(WorkerJob)
        .filter(
            WorkerJob.workspace_id == workspace.id,
            WorkerJob.kind == "rag_deep_retrieval",
        )
        .order_by(WorkerJob.updated_at.desc(), WorkerJob.created_at.desc())
        .limit(100)
        .all()
    )
    changed = False
    for legacy in legacy_jobs:
        legacy_result = legacy.result if isinstance(legacy.result, dict) else {}
        request = legacy_result.get("request") if isinstance(legacy_result.get("request"), dict) else {}
        if str(request.get("session_id") or "") != session.id:
            continue
        existing_rows = (
            db.query(WorkspaceJob)
            .filter(
                WorkspaceJob.workspace_id == workspace.id,
                WorkspaceJob.kind == "rag_deep_retrieval",
                WorkspaceJob.session_id == session.id,
            )
            .all()
        )
        if any((row.input_ref or {}).get("legacy_worker_job_id") == legacy.id for row in existing_rows):
            continue
        job = WorkspaceJob(
            id=str(uuid.uuid4()),
            workspace_id=workspace.id,
            session_id=session.id,
            collection_id=legacy.collection_id,
            kind="rag_deep_retrieval",
            title=f"Legacy Deep Search · {str(request.get('query') or legacy.id)[:96]}",
            status=legacy.status,
            progress=legacy.progress,
            stage=str(legacy_result.get("stage") or legacy.status or "legacy"),
            error=legacy.error,
            input_ref={
                "legacy_worker_job_id": legacy.id,
                "request": request,
                "latency_profile": legacy_result.get("latency_profile") or "deep",
                "trigger": legacy_result.get("trigger") or "legacy_worker_job_backfill",
            },
            result=legacy_result,
            events=[],
            created_by_user_id=session.user_id,
            created_at=legacy.created_at,
            started_at=legacy.started_at,
            completed_at=legacy.completed_at,
            updated_at=legacy.updated_at,
        )
        db.add(job)
        changed = True
    if changed:
        db.commit()


def _fetch_scoped_session(
    db: DBSession,
    session_id: str,
    user: User,
    workspace: Workspace,
    *,
    include_deleted: bool = False,
    require_owner: bool = False,
) -> SessionModel:
    session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    admin = _is_workspace_admin(db, user, workspace)
    if session.workspace_id != workspace.id or (session.user_id != user.id and not admin):
        raise HTTPException(status_code=404, detail="Session not found")
    # Admin cross-member access is strictly read-only: a non-owner (even an
    # admin) cannot mutate another member's session.
    if require_owner and session.user_id != user.id:
        raise HTTPException(status_code=403, detail="Cannot modify another member's session")
    if not include_deleted and (getattr(session, "status", None) == "deleted" or getattr(session, "deleted_at", None)):
        raise HTTPException(status_code=404, detail="Session not found")
    if admin and session.user_id != user.id:
        emit_audit_event(
            db=db,
            workspace_id=workspace.id,
            event_type="chat.session.admin_read",
            actor=_actor(user),
            details={"session_id": session.id, "owner_user_id": session.user_id},
        )
    return session


@router.post("")
async def create_session(
    session: SessionCreate,
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    """Create a new session in the current workspace."""
    try:
        db_session = SessionModel(
            id=str(uuid.uuid4()),
            user_id=user.id,
            workspace_id=workspace.id,
            title=(session.title or "").strip()[:500] or None,
            status="active",
            context_signature=(session.context_signature or _context_signature(session.context)),
            meta_data=_session_meta_from_context(session.context),
        )
        db.add(db_session)
        db.commit()
        db.refresh(db_session)

        return _serialize_session(db_session, author_lookup={user.id: user})
    except Exception as e:
        logger.error("Failed to create session", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("")
async def list_sessions(
    skip: int = 0,
    offset: Optional[int] = Query(default=None, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
    status: str = Query(default="active"),
    include_admin: bool = Query(default=False),
    member_user_id: Optional[str] = Query(default=None, alias="user_id"),
    q: Optional[str] = Query(default=None),
    linked_type: Optional[str] = Query(default=None),
    linked_id: Optional[str] = Query(default=None),
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    """List durable chat sessions in the current workspace.

    Workspace admins may pass ``include_admin=true`` to browse every member's
    sessions (read-only); ``user_id`` then narrows the list to one member.
    ``q`` searches titles; ``linked_type`` / ``linked_id`` filter
    ``meta_data.linked_object``.
    """
    try:
        admin = include_admin and _is_workspace_admin(db, user, workspace)
        effective_offset = offset if offset is not None else skip
        base_query = db.query(SessionModel).filter(SessionModel.workspace_id == workspace.id)
        if admin:
            if member_user_id:
                base_query = base_query.filter(SessionModel.user_id == member_user_id)
        else:
            base_query = base_query.filter(SessionModel.user_id == user.id)
        if status != "all":
            statuses = [item.strip() for item in status.split(",") if item.strip()]
            if statuses:
                base_query = base_query.filter(SessionModel.status.in_(statuses))
            else:
                base_query = base_query.filter(SessionModel.status == "active")
        else:
            base_query = base_query.filter(SessionModel.status != "deleted")
        needle = (q or "").strip()
        if needle:
            base_query = base_query.filter(func.lower(SessionModel.title).like(f"%{needle.lower()}%"))
        linked_type_norm = (linked_type or "").strip()
        linked_id_norm = (linked_id or "").strip()
        if linked_type_norm or linked_id_norm:
            linked = SessionModel.meta_data["linked_object"]
            if linked_type_norm:
                base_query = base_query.filter(linked["type"].as_string() == linked_type_norm)
            if linked_id_norm:
                base_query = base_query.filter(linked["id"].as_string() == linked_id_norm)
        sessions = (
            base_query.order_by(SessionModel.last_activity.desc())
            .offset(effective_offset)
            .limit(limit)
            .all()
        )
        author_lookup = _build_author_lookup(db, sessions)

        if admin:
            emit_audit_event(
                db=db,
                workspace_id=workspace.id,
                event_type="chat.session.admin_list",
                actor=_actor(user),
                details={
                    "status": status,
                    "member_user_id": member_user_id,
                    "q": needle or None,
                    "linked_type": linked_type_norm or None,
                    "linked_id": linked_id_norm or None,
                    "returned": len(sessions),
                },
            )

        return {
            "sessions": [_serialize_session(s, author_lookup=author_lookup) for s in sessions],
            "total": base_query.count(),
            "skip": effective_offset,
            "limit": limit,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to list sessions", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{session_id}")
async def get_session(
    session_id: str,
    include_messages: bool = Query(default=False),
    include_jobs: bool = Query(default=False),
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    session = _fetch_scoped_session(db, session_id, user, workspace)
    if include_jobs:
        _backfill_legacy_deep_jobs(db, workspace, session)
        session._session_jobs = (
            db.query(WorkspaceJob)
            .filter(
                WorkspaceJob.workspace_id == workspace.id,
                WorkspaceJob.session_id == session.id,
            )
            .order_by(WorkspaceJob.updated_at.desc(), WorkspaceJob.created_at.desc())
            .all()
        )
    author_lookup = _build_author_lookup(db, [session])
    return _serialize_session(
        session,
        include_messages=include_messages,
        include_jobs=include_jobs,
        author_lookup=author_lookup,
    )


@router.patch("/{session_id}")
async def patch_session(
    session_id: str,
    body: SessionPatch,
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    session = _fetch_scoped_session(db, session_id, user, workspace, include_deleted=True, require_owner=True)
    now = datetime.utcnow()
    if body.title is not None:
        cleaned = body.title.strip()
        session.title = cleaned[:500] if cleaned else None
    if body.status is not None:
        if body.status not in {"active", "archived", "deleted"}:
            raise HTTPException(status_code=400, detail="Invalid session status")
        session.status = body.status
        if body.status == "archived":
            session.archived_at = now
        elif body.status == "deleted":
            session.deleted_at = now
        elif body.status == "active":
            session.archived_at = None
            session.deleted_at = None
    session.last_activity = now
    db.commit()
    db.refresh(session)
    return _serialize_session(session, author_lookup=_build_author_lookup(db, [session]))


@router.delete("/{session_id}")
async def delete_session(
    session_id: str,
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    session = _fetch_scoped_session(db, session_id, user, workspace, include_deleted=True, require_owner=True)
    now = datetime.utcnow()
    session.status = "deleted"
    session.deleted_at = now
    session.last_activity = now
    db.commit()
    return {"message": "Session deleted successfully", "status": "deleted"}


@router.get("/{session_id}/messages")
async def get_session_messages(
    session_id: str,
    skip: int = 0,
    limit: int = 100,
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    session = _fetch_scoped_session(db, session_id, user, workspace)

    messages = (
        db.query(Message)
        .filter(Message.session_id == session_id)
        .order_by(Message.timestamp.asc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    return {
        "messages": [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "timestamp": m.timestamp.isoformat() if m.timestamp else None,
                "meta_data": m.meta_data or {},
            }
            for m in messages
        ],
        "total": len(session.messages),
    }
