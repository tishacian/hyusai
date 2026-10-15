"""A durable write identity and approval, independent of delivery attempts."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)

from app.db.base import Base


class ConnectorWrite(Base):
    __tablename__ = "connector_writes"
    __table_args__ = (
        UniqueConstraint("workspace_id", "request_key", name="uq_connector_write_request"),
        CheckConstraint(
            "state IN ('prepared','approved','sent','applied','failed','unknown','abandoned')",
            name="ck_connector_write_state",
        ),
    )
    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id = Column(
        String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    connection_id = Column(
        String(36), ForeignKey("connections.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    request_key = Column(String(120), nullable=False)
    connection_revision = Column(Integer, nullable=False)
    profile_digest = Column(String(64), nullable=False)
    operation = Column(String(32), nullable=False)
    target_digest = Column(String(64), nullable=False, index=True)
    contract = Column(JSON, nullable=False)
    contract_digest = Column(String(64), nullable=False)
    created_by = Column(String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    approved_by = Column(String(36), ForeignKey("users.id", ondelete="RESTRICT"))
    approved_at = Column(DateTime)
    state = Column(String(16), default="prepared", nullable=False, index=True)
    compute_run_id = Column(
        String(36), ForeignKey("compute_runs.id", ondelete="RESTRICT"), unique=True
    )
    receipt = Column(JSON)
    error_code = Column(String(160))
    finished_at = Column(DateTime)
