"""Session management endpoints"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from app.core.logging import get_logger
from app.db.base import get_db
from app.models.user import Session, Message
from datetime import datetime
import uuid

logger = get_logger(__name__)
router = APIRouter()


class SessionCreate(BaseModel):
    """Session creation request"""
    user_id: str
    context: Optional[Dict[str, Any]] = {}


class SessionResponse(BaseModel):
    """Session response"""
    id: str
    user_id: str
    created_at: datetime
    last_activity: datetime
    message_count: int


@router.post("")
async def create_session(
    session: SessionCreate,
    db: Session = Depends(get_db)
):
    """Create a new session"""
    try:
        db_session = Session(
            id=str(uuid.uuid4()),
            user_id=session.user_id,
            context=session.context or {}
        )
        db.add(db_session)
        db.commit()
        db.refresh(db_session)
        
        return SessionResponse(
            id=db_session.id,
            user_id=db_session.user_id,
            created_at=db_session.created_at,
            last_activity=db_session.last_activity,
            message_count=0
        )
    except Exception as e:
        logger.error("Failed to create session", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("")
async def list_sessions(
    user_id: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    """List sessions"""
    try:
        query = db.query(Session)
        if user_id:
            query = query.filter(Session.user_id == user_id)
        
        sessions = query.order_by(Session.last_activity.desc()).offset(skip).limit(limit).all()
        
        return {
            "sessions": [
                {
                    "id": s.id,
                    "user_id": s.user_id,
                    "created_at": s.created_at.isoformat() if s.created_at else None,
                    "last_activity": s.last_activity.isoformat() if s.last_activity else None,
                    "message_count": len(s.messages)
                }
                for s in sessions
            ],
            "total": query.count()
        }
    except Exception as e:
        logger.error("Failed to list sessions", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{session_id}")
async def get_session(
    session_id: str,
    db: Session = Depends(get_db)
):
    """Get a session by ID"""
    try:
        session = db.query(Session).filter(Session.id == session_id).first()
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        
        return SessionResponse(
            id=session.id,
            user_id=session.user_id,
            created_at=session.created_at,
            last_activity=session.last_activity,
            message_count=len(session.messages)
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get session", session_id=session_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{session_id}")
async def delete_session(
    session_id: str,
    db: Session = Depends(get_db)
):
    """Delete a session"""
    try:
        session = db.query(Session).filter(Session.id == session_id).first()
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        
        db.delete(session)
        db.commit()
        
        return {"message": "Session deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to delete session", session_id=session_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{session_id}/messages")
async def get_session_messages(
    session_id: str,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    """Get messages for a session"""
    try:
        session = db.query(Session).filter(Session.id == session_id).first()
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        
        messages = db.query(Message).filter(
            Message.session_id == session_id
        ).order_by(Message.timestamp.asc()).offset(skip).limit(limit).all()
        
        return {
            "messages": [
                {
                    "id": m.id,
                    "role": m.role,
                    "content": m.content,
                    "timestamp": m.timestamp.isoformat() if m.timestamp else None,
                    "meta_data": m.meta_data
                }
                for m in messages
            ],
            "total": len(session.messages)
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get session messages", session_id=session_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

