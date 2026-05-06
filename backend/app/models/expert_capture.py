"""Expert knowledge capture sessions and review proposals.

The capture flow is intentionally generic: a workspace can prepare an
interview plan from any Context / Knowledge scope, run a guided expert
session, then review a structured update proposal before ingestion.
"""
from datetime import datetime
from uuid import uuid4

from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import relationship

from app.db.base import Base


class ExpertCaptureSession(Base):
    __tablename__ = "expert_capture_sessions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id = Column(String(36), nullable=False, index=True)
    capability_id = Column(String(36), nullable=True, index=True)
    context_id = Column(String(36), nullable=True, index=True)
    system_id = Column(String(36), nullable=True, index=True)
    run_id = Column(String(36), nullable=True, index=True)

    title = Column(String(240), nullable=False, default="Expert capture session")
    objective = Column(Text, nullable=False)
    expert_profile = Column(Text, nullable=True)
    duration_minutes = Column(Integer, nullable=False, default=20)
    voice_runtime = Column(String(80), nullable=False, default="cascade")
    status = Column(String(40), nullable=False, default="planned", index=True)

    plan = Column(JSON, default=dict)
    knowledge_gaps = Column(JSON, default=list)
    transcript = Column(JSON, default=list)
    evaluations = Column(JSON, default=list)
    captured_facts = Column(JSON, default=list)
    metrics = Column(JSON, default=dict)

    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    proposals = relationship(
        "KnowledgeUpdateProposal",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="KnowledgeUpdateProposal.created_at.desc()",
    )
    events = relationship(
        "ExpertCaptureEvent",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="ExpertCaptureEvent.sequence.asc()",
    )


class ExpertCaptureEvent(Base):
    __tablename__ = "expert_capture_events"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id = Column(String(36), nullable=False, index=True)
    session_id = Column(
        String(36),
        ForeignKey("expert_capture_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    parent_event_id = Column(String(36), nullable=True, index=True)

    event_type = Column(String(80), nullable=False, index=True)
    speaker = Column(String(40), nullable=True, index=True)
    sequence = Column(Integer, nullable=False, default=0)
    question_id = Column(String(80), nullable=True, index=True)
    audio_ref = Column(Text, nullable=True)

    text_raw = Column(Text, nullable=True)
    text_amended = Column(Text, nullable=True)
    confidence = Column(String(40), nullable=True)
    language = Column(String(16), nullable=True)
    source = Column(String(80), nullable=False, default="capture_engine", index=True)
    status = Column(String(40), nullable=False, default="accepted", index=True)
    meta_data = Column("metadata", JSON, default=dict)
    created_by = Column(String(255), nullable=True)

    started_at = Column(DateTime, nullable=True)
    ended_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    session = relationship("ExpertCaptureSession", back_populates="events")


class KnowledgeUpdateProposal(Base):
    __tablename__ = "knowledge_update_proposals"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id = Column(String(36), nullable=False, index=True)
    session_id = Column(
        String(36),
        ForeignKey("expert_capture_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    status = Column(String(40), nullable=False, default="pending_review", index=True)
    proposal = Column(JSON, default=dict)
    review_notes = Column(Text, nullable=True)
    reviewer = Column(String(255), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    reviewed_at = Column(DateTime, nullable=True)

    session = relationship("ExpertCaptureSession", back_populates="proposals")
