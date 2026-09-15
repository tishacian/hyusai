"""Immutable suite revisions and their canonical Run comparisons."""
from datetime import datetime
from uuid import uuid4

from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint
from app.db.base import Base


class EvaluationSuite(Base):
    __tablename__ = "evaluation_suites"
    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id = Column(String(36), ForeignKey("workspaces.id"), nullable=False, index=True)
    system_id = Column(String(36), ForeignKey("systems.id"), nullable=False, index=True)
    name = Column(String(160), nullable=False)
    revision = Column(Integer, nullable=False, default=1)
    cases = Column(JSON, nullable=False)
    corpus_manifest = Column(JSON, nullable=False, default=list)
    provenance = Column(JSON, nullable=False, default=dict)
    created_by_user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint("workspace_id", "system_id", "name", "revision", name="uq_evaluation_suite_revision"),)


class EvaluationCampaign(Base):
    __tablename__ = "evaluation_campaigns"
    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id = Column(String(36), ForeignKey("workspaces.id"), nullable=False, index=True)
    system_id = Column(String(36), ForeignKey("systems.id"), nullable=False, index=True)
    suite_id = Column(String(36), ForeignKey("evaluation_suites.id"), nullable=False)
    baseline_run_id = Column(String(36), ForeignKey("runs.id"), nullable=False)
    job_id = Column(String(36), ForeignKey("workspace_jobs.id"), nullable=True)
    request_key = Column(String(160), nullable=False)
    request_sha256 = Column(String(64), nullable=False)
    status = Column(String(32), nullable=False, default="queued")
    method = Column(String(40), nullable=False, default="server_assertions")
    snapshot = Column(JSON, nullable=False)
    results = Column(JSON, nullable=False, default=list)
    created_by_user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    __table_args__ = (UniqueConstraint("workspace_id", "created_by_user_id", "request_key", name="uq_evaluation_campaign_request"),)
