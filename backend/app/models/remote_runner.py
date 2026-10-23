"""External runners: machines a workspace drives over SSH, and the jobs it starts there.

A runner never receives a free command. A job names a command of the closed
catalog (``app.services.remote_runners.catalog``) and its typed parameters; the
private key stays in the secret registry and is referenced, never stored here.
"""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)

from app.db.base import Base

JOB_ACTIVE_STATUSES = frozenset({"launching", "running", "cancelling"})
JOB_TERMINAL_STATUSES = frozenset({"succeeded", "failed", "cancelled", "timed_out", "lost"})


class RemoteRunner(Base):
    __tablename__ = "remote_runners"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id = Column(
        String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    slug = Column(String(80), nullable=False)
    name = Column(String(160), nullable=False)
    transport = Column(String(16), nullable=False, default="ssh")
    host = Column(String(255), nullable=False)
    port = Column(Integer, nullable=False, default=22)
    username = Column(String(80), nullable=False)
    # One OpenSSH public key line ("ssh-ed25519 AAAA..."); connections refuse any other.
    host_key = Column(Text, nullable=False)
    # secret://workspace/<name> holding the OpenSSH private key.
    key_secret_ref = Column(String(255), nullable=False)
    bastion = Column(JSON, nullable=True)
    work_root = Column(String(512), nullable=False)
    allowed_commands = Column(JSON, nullable=False, default=list)
    labels = Column(JSON, nullable=False, default=dict)
    max_concurrent_jobs = Column(Integer, nullable=False, default=1)
    enabled = Column(Boolean, nullable=False, default=True)
    last_probe = Column(JSON, nullable=True)
    last_probe_at = Column(DateTime, nullable=True)
    created_by = Column(String(36), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("workspace_id", "slug", name="uq_remote_runners_workspace_slug"),
        CheckConstraint("transport IN ('ssh','local')", name="ck_remote_runners_transport"),
        CheckConstraint(
            "port > 0 AND port < 65536 AND max_concurrent_jobs > 0",
            name="ck_remote_runners_limits",
        ),
    )


class RemoteRunnerJob(Base):
    __tablename__ = "remote_runner_jobs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id = Column(
        String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    runner_id = Column(
        String(36), ForeignKey("remote_runners.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    command = Column(String(120), nullable=False)
    params = Column(JSON, nullable=False, default=dict)
    run_id = Column(String(36), nullable=True, index=True)
    node_id = Column(String(160), nullable=True)
    # Carried into the job_finished event so a waiting flow can match it.
    correlation_key = Column(String(200), nullable=True, index=True)
    # When set, only this System hears the job_finished event.
    notify_system_id = Column(String(36), nullable=True)
    status = Column(String(16), nullable=False, default="queued", index=True)
    remote_dir = Column(String(1024), nullable=True)
    pid = Column(Integer, nullable=True)
    exit_code = Column(Integer, nullable=True)
    result = Column(JSON, nullable=True)
    # Files staged in the object store at submission, uploaded before launch.
    inputs = Column(JSON, nullable=False, default=list)
    artifacts = Column(JSON, nullable=False, default=list)
    log_tail = Column(Text, nullable=True)
    error_code = Column(String(80), nullable=True)
    error_detail = Column(Text, nullable=True)
    cancel_requested = Column(Boolean, nullable=False, default=False)
    cancel_sent_at = Column(DateTime, nullable=True)
    created_by = Column(String(36), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    deadline_at = Column(DateTime, nullable=False, index=True)
    launched_at = Column(DateTime, nullable=True)
    last_seen_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    # Set once the job_finished event has been handed to the trigger registry.
    event_emitted_at = Column(DateTime, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('queued','launching','running','cancelling',"
            "'succeeded','failed','cancelled','timed_out','lost')",
            name="ck_remote_runner_jobs_status",
        ),
    )
