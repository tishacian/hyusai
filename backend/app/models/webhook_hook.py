"""Inbound webhook hooks (orchestration Phase 3)."""
from datetime import datetime
from uuid import uuid4

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, String, Text

from app.db.base import Base


class WebhookHook(Base):
    """Maps ``POST /hooks/{id}`` to a System + event kind.

    Auth is HMAC over the raw body (``X-Agentium-Signature: sha256=<hex>``).
    The public id is this row's primary key — treat it as a capability URL.
    """

    __tablename__ = "webhook_hooks"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id = Column(
        String(36),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    system_id = Column(
        String(36),
        ForeignKey("systems.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    name = Column(String(255), nullable=False, default="Webhook")
    # Event kind consumed by ``triggers.emit_event`` (default webhook.received).
    event_type = Column(String(120), nullable=False, default="webhook.received")
    secret = Column(Text, nullable=False)
    enabled = Column(Boolean, nullable=False, default=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_webhook_hooks_workspace_system", "workspace_id", "system_id"),
    )
