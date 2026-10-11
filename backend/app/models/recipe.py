"""Python recipe execution plane — managed venvs + async executions.

A ``PythonEnv`` is a content-addressed virtual environment: its identity is
the fingerprint of the normalized requirement set, the Python version and the
registry configuration. Rows survive eviction (only the on-disk venv goes
away) so a rebuild is transparent and — thanks to ``lock_text`` — exactly
reproducible.

A ``RecipeExecution`` is one author-written script run dispatched to the
Celery worker plane. It carries the operator-facing lifecycle
(``queued | env_building | running | succeeded | failed | cancelled |
timed_out``) that the Flow Builder polls, plus the evidence trail
(exit code, stdout/stderr tails, duration).
"""
from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)

from app.db.base import Base

PYTHON_ENV_STATUSES = ("pending", "building", "ready", "failed", "evicted")
RECIPE_EXECUTION_STATUSES = (
    "queued",
    "env_building",
    "running",
    "succeeded",
    "failed",
    "cancelled",
    "timed_out",
)
RECIPE_EXECUTION_TERMINAL_STATUSES = frozenset(
    {"succeeded", "failed", "cancelled", "timed_out"}
)


class PythonEnv(Base):
    __tablename__ = "python_envs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id = Column(
        String(36),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # sha256 over (python_version, normalized requirements, registry config).
    fingerprint = Column(String(64), nullable=False, index=True)
    python_version = Column(String(16), nullable=False)
    requirements_text = Column(Text, nullable=False, default="")
    # ``pip freeze`` captured after the first successful build. Rebuilds after
    # an eviction install from this lock so the env comes back byte-compatible.
    lock_text = Column(Text, nullable=True)
    index_url = Column(String(500), nullable=True)
    extra_index_urls = Column(JSON, default=list)

    # pending | building | ready | failed | evicted
    status = Column(String(16), default="pending", nullable=False, index=True)
    size_bytes = Column(BigInteger, default=0, nullable=False)
    build_log_tail = Column(Text, nullable=True)
    build_error = Column(Text, nullable=True)
    built_at = Column(DateTime, nullable=True)
    build_duration_ms = Column(Float, nullable=True)

    last_used_at = Column(DateTime, nullable=True, index=True)
    use_count = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "fingerprint",
            name="uq_python_envs_workspace_fingerprint",
        ),
    )


class RecipeExecution(Base):
    __tablename__ = "recipe_executions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id = Column(
        String(36),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # No FK on run/invocation: workspace teardown and run purges must stay
    # cheap (same posture as Run.parent_run_id).
    run_id = Column(String(36), nullable=True, index=True)
    node_id = Column(String(160), nullable=True)
    invocation_id = Column(String(36), nullable=True, index=True)

    env_id = Column(
        String(36),
        ForeignKey("python_envs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    env_fingerprint = Column(String(64), nullable=True)
    celery_task_id = Column(String(255), nullable=True)

    # queued | env_building | running | succeeded | failed | cancelled | timed_out
    status = Column(String(20), default="queued", nullable=False, index=True)
    cancel_requested = Column(Boolean, default=False, nullable=False)

    code_sha256 = Column(String(64), nullable=True)
    timeout_s = Column(Float, nullable=True)
    input_json = Column(JSON, default=dict)
    output_json = Column(JSON, nullable=True)
    exit_code = Column(Integer, nullable=True)
    stdout_tail = Column(Text, nullable=True)
    stderr_tail = Column(Text, nullable=True)
    error = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    duration_ms = Column(Float, nullable=True)
