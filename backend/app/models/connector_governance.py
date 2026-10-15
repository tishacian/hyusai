"""Platform-approved egress exceptions and immutable connector evidence."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import JSON, Column, DateTime, ForeignKey, String, Text

from app.db.base import Base


class ConnectorNetworkException(Base):
    __tablename__ = "connector_network_exceptions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    cidr = Column(String(64), nullable=False)
    ports = Column(JSON, nullable=False)
    reason = Column(Text, nullable=False)
    expires_at = Column(DateTime, nullable=False, index=True)
    created_by = Column(String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    revoked_at = Column(DateTime)
    revoked_by = Column(String(36), ForeignKey("users.id", ondelete="RESTRICT"))


class ConnectorEvidence(Base):
    __tablename__ = "connector_evidence"

    digest = Column(String(64), primary_key=True)
    profile_key = Column(String(160), nullable=False, index=True)
    identity_digest = Column(String(64), nullable=False, index=True)
    payload = Column(JSON, nullable=False)
    reports = Column(JSON, nullable=False)
    accepted_by = Column(String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    accepted_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    # The producer is an operator-supplied identity, distinct from bundle bytes.
    producer = Column(String(160), nullable=False)
    revoked_at = Column(DateTime)
    revoked_by = Column(String(36), ForeignKey("users.id", ondelete="RESTRICT"))
