"""Canonical Context — the typed bag of state available to a System Run.

Contexts version explicitly so that adaptive policies can roll back to a
known-good context if confidence collapses.

Ephemeral contexts (Vague D / D0): the chat workspace surface creates
temporary drop-and-ask contexts scoped to a session, expiring after a TTL
(24h by default). These are purged opportunistically by `GET /contexts`
and by the drop-and-ask flow itself — no background worker required.
"""
from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)

from app.db.base import Base


class Context(Base):
    __tablename__ = "contexts"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id = Column(String(36), nullable=True, index=True)
    system_id = Column(String(36), nullable=True, index=True)
    # Portable, opaque identity used by Workspace Blueprints. Context names
    # may legitimately collide and therefore never carry import authority.
    blueprint_key = Column(String(120), nullable=False, default=lambda: str(uuid4()))

    name = Column(String(200), nullable=False, default="default")
    version = Column(Integer, default=1)

    data_refs = Column(JSON, default=list)
    memory_refs = Column(JSON, default=list)
    history_refs = Column(JSON, default=list)
    environment_state = Column(JSON, default=dict)
    business_constraints = Column(JSON, default=dict)
    permissions = Column(JSON, default=dict)

    # D0 — ephemeral session contexts (drop-and-ask). When true, the
    # context is auto-purged by opportunistic cleanup past `ttl_expires_at`.
    # A user can call `POST /contexts/{id}/persist` to flip the flag and
    # keep it permanently.
    ephemeral = Column(Boolean, default=False, nullable=False, index=True)
    ttl_expires_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "blueprint_key",
            name="uq_contexts_workspace_blueprint_key",
        ),
        Index(
            "uq_contexts_global_blueprint_key",
            "blueprint_key",
            unique=True,
            postgresql_where=text("workspace_id IS NULL"),
            sqlite_where=text("workspace_id IS NULL"),
        ),
    )
