"""Canonical RAG Preset — multi-scope configuration catalog.

A Preset captures the Retrieval/Generation/Chunking/Experience knobs
previously squashed into the global ``app_settings`` singleton. Presets are
scoped by ``workspace`` (default), ``capability`` or ``system`` so a Run can
resolve the most specific one at execution time.
"""
from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    JSON,
    String,
)

from app.db.base import Base


class RagPreset(Base):
    __tablename__ = "rag_presets"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name = Column(String(120), nullable=False)

    scope = Column(String(16), nullable=False)
    scope_id = Column(String(36), nullable=True)

    workspace_id = Column(
        String(36),
        ForeignKey("workspaces.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # camelCase payload, identical to what `SettingsService` returns, so the
    # frontend can keep consuming the legacy /settings endpoint unchanged.
    config = Column(JSON, nullable=False, default=dict)

    is_default = Column(Boolean, nullable=False, default=False)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "scope IN ('workspace', 'capability', 'system')",
            name="ck_rag_presets_scope",
        ),
        Index("ix_rag_presets_scope", "scope", "scope_id"),
    )
