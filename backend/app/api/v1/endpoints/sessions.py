"""Session management endpoints — scoped by workspace."""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session as DBSession
from app.core.auth import get_current_user, get_current_workspace
from app.core.logging import get_logger
from app.db.base import get_db
from app.models.user import Session as SessionModel, Message, User
from app.models.workspace import Workspace
from datetime import datetime
import uuid

logger = get_logger(__name__)
router = APIRouter()


class SessionCreate(BaseModel):
    user_id: Optional[str] = None  # Ignored: taken from JWT
    context: Optional[Dict[str, Any]] = {}


class SessionResponse(BaseModel):
    id: str
    user_id: str
    workspace_id: Optional[str] = None
    created_at: datetime
    last_activity: datetime
    message_count: int


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
            meta_data=session.context or {},
        )
        db.add(db_session)
        db.commit()
        db.refresh(db_session)

        return SessionResponse(
            id=db_session.id,
            user_id=db_session.user_id,
            workspace_id=db_session.workspace_id,
            created_at=db_session.created_at,
            last_activity=db_session.last_activity,
            message_count=0,
        )
    except Exception as e:
        logger.error("Failed to create session", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("")
async def list_sessions(
    skip: int = 0,
    limit: int = 100,
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    """List sessions in the current workspace (of the current user)."""
    try:
        base_query = db.query(SessionModel).filter(
            SessionModel.user_id == user.id,
            SessionModel.workspace_id == workspace.id,
        )
        sessions = (
            base_query.order_by(SessionModel.last_activity.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )

        return {
            "sessions": [
                {
                    "id": s.id,
                    "user_id": s.user_id,
                    "workspace_id": s.workspace_id,
                    "created_at": s.created_at.isoformat() if s.created_at else None,
                    "last_activity": s.last_activity.isoformat() if s.last_activity else None,
                    "message_count": len(s.messages),
                }
                for s in sessions
            ],
            "total": base_query.count(),
        }
    except Exception as e:
        logger.error("Failed to list sessions", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


def _fetch_scoped_session(
    db: DBSession, session_id: str, user: User, workspace: Workspace
) -> SessionModel:
    session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.user_id != user.id or (
        session.workspace_id is not None and session.workspace_id != workspace.id
    ):
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@router.get("/{session_id}")
async def get_session(
    session_id: str,
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    session = _fetch_scoped_session(db, session_id, user, workspace)
    return SessionResponse(
        id=session.id,
        user_id=session.user_id,
        workspace_id=session.workspace_id,
        created_at=session.created_at,
        last_activity=session.last_activity,
        message_count=len(session.messages),
    )


@router.delete("/{session_id}")
async def delete_session(
    session_id: str,
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    session = _fetch_scoped_session(db, session_id, user, workspace)
    db.delete(session)
    db.commit()
    return {"message": "Session deleted successfully"}


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
                "meta_data": m.meta_data,
            }
            for m in messages
        ],
        "total": len(session.messages),
    }
