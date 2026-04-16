"""Evaluation models for ProofAgent-style scoring"""
from datetime import datetime
from sqlalchemy import Column, String, DateTime, JSON, Integer, Float, ForeignKey
from app.db.base import Base


class EvaluationScore(Base):
    __tablename__ = "evaluation_scores"

    id = Column(String(36), primary_key=True)
    workspace_id = Column(String(36), ForeignKey("workspaces.id"), nullable=True, index=True)
    session_id = Column(String(36), nullable=True)
    agent_id = Column(String(100), nullable=True)
    turn_number = Column(Integer, default=0)
    query = Column(String(2000), nullable=True)
    scores = Column(JSON, default=dict)
    composite_score = Column(Float, default=0.0)
    hallucination_rate = Column(Float, default=0.0)
    drift_rate = Column(Float, default=0.0)
    claim_audit = Column(JSON, default=dict)
    metadata_ = Column("metadata", JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
