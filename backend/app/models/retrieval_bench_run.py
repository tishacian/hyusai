"""Nightly public retrieval bench results (HotpotQA distractor subset)."""
from datetime import datetime
from uuid import uuid4

from sqlalchemy import JSON, Column, DateTime, Float, Integer, String, Text

from app.db.base import Base


class RetrievalBenchRun(Base):
    __tablename__ = "retrieval_bench_runs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    bench = Column(String(80), nullable=False, index=True)
    status = Column(String(16), nullable=False, default="running")
    git_sha = Column(String(40), nullable=True)
    k = Column(Integer, nullable=False)
    case_count = Column(Integer, nullable=False, default=0)
    error_count = Column(Integer, nullable=False, default=0)
    recall_at_k = Column(Float, nullable=True)
    supporting_fact_rate = Column(Float, nullable=True)
    mean_latency_ms = Column(Float, nullable=True)
    metrics = Column(JSON, nullable=False, default=dict)
    error = Column(Text, nullable=True)
    started_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    completed_at = Column(DateTime, nullable=True)
