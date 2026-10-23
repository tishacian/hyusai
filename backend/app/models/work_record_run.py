"""WorkRecordRun — the attempts a Work record received, one row per Run.

Written when a Work binding that declares a record identity starts a Run, or
by an explicit historical backfill (stamped with its batch id).
A new attempt is appended next to earlier ones; nothing is ever replaced, so a
case keeps its history of analyses, expiries and retries.
"""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import Column, DateTime, ForeignKey, Index, String, UniqueConstraint

from app.db.base import Base


class WorkRecordRun(Base):
    __tablename__ = "work_record_runs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id = Column(String(36), ForeignKey("workspaces.id"), nullable=False)
    experience_id = Column(String(36), nullable=False)
    binding_key = Column(String(120), nullable=False)
    record_namespace = Column(String(80), nullable=False)
    record_ref = Column(String(200), nullable=False)
    run_id = Column(String(36), ForeignKey("runs.id"), nullable=False)
    initiated_by_user_id = Column(String(36), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    # Set only on rows linked by a historical backfill, so one batch can be
    # reverted without touching attempts recorded when their Run started.
    backfill_batch_id = Column(String(36), nullable=True)

    __table_args__ = (
        UniqueConstraint("run_id", name="uq_work_record_runs_run"),
        Index(
            "ix_work_record_runs_record",
            "workspace_id",
            "record_namespace",
            "record_ref",
            "created_at",
        ),
        Index("ix_work_record_runs_backfill_batch", "backfill_batch_id"),
    )
