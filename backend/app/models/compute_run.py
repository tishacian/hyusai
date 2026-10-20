"""Local compute registry shared by connector and DataOps execution planes."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
)

from app.db.base import Base

ACTIVE_STATUSES = frozenset({"admitted", "launching", "running", "committing"})
TERMINAL_STATUSES = frozenset({"succeeded", "failed", "cancelled", "timed_out", "lost"})


class ComputeRun(Base):
    __tablename__ = "compute_runs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id = Column(
        String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id = Column(String(36), nullable=True)
    connection_id = Column(
        String(36), ForeignKey("connections.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    connection_revision = Column(Integer, nullable=True)
    system_id = Column(String(36), nullable=True)
    system_version_id = Column(String(36), nullable=True)
    delegation_id = Column(String(36), nullable=True)
    run_id = Column(String(36), nullable=True, index=True)
    node_id = Column(String(160), nullable=True)
    attempt = Column(Integer, nullable=False, default=1)
    # Legacy DataOps keeps its existing row during the transition; this unique
    # link provides one registry identity, never an independent second task.
    recipe_execution_id = Column(
        String(36),
        ForeignKey("recipe_executions.id", ondelete="SET NULL"),
        nullable=True,
        unique=True,
    )
    kind = Column(String(32), nullable=False)
    operation = Column(String(32), nullable=False)
    placement = Column(String(24), nullable=False, default="local")
    profile = Column(String(160), nullable=True)
    fingerprint = Column(String(64), nullable=True)
    status = Column(String(20), nullable=False, default="queued", index=True)
    stage = Column(String(32), nullable=False, default="queued")
    progress = Column(JSON, nullable=False, default=dict)
    input_json = Column(JSON, nullable=False, default=dict)
    output_json = Column(JSON, nullable=True)
    metrics_json = Column(JSON, nullable=False, default=dict)
    error_code = Column(String(80), nullable=True)
    celery_task_id = Column(String(255), nullable=True)
    lease_token = Column(String(36), nullable=True)
    lease_expires_at = Column(DateTime, nullable=True, index=True)
    deadline_at = Column(DateTime, nullable=False, index=True)
    cancel_requested = Column(Boolean, nullable=False, default=False)
    write_started = Column(Boolean, nullable=False, default=False)
    outcome_unknown = Column(Boolean, nullable=False, default=False)
    cpu_cores = Column(Float, nullable=False, default=1.0)
    memory_mb = Column(Integer, nullable=False, default=1024)
    reserved_core_hours = Column(Float, nullable=False, default=0.0)
    core_hours = Column(Float, nullable=False, default=0.0)
    cost_usd = Column(Float, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('queued','admitted','launching','running','committing','succeeded','failed','cancelled','timed_out','lost')",
            name="ck_compute_runs_status",
        ),
        CheckConstraint(
            "cpu_cores > 0 AND memory_mb > 0 AND reserved_core_hours >= 0 AND core_hours >= 0 AND cost_usd >= 0",
            name="ck_compute_runs_resources",
        ),
        CheckConstraint("placement = 'local'", name="ck_compute_runs_local"),
    )
