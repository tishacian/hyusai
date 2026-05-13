"""Workspace-scoped visual intelligence sources and observations."""
from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)

from app.db.base import Base


class WorkspaceVisualSource(Base):
    """A public or authorized visual source owned by a workspace."""

    __tablename__ = "workspace_visual_sources"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    system_id = Column(String(36), ForeignKey("systems.id", ondelete="SET NULL"), nullable=True, index=True)
    created_by_user_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=False, default="")
    source_url = Column(Text, nullable=False, default="")
    source_type = Column(String(80), nullable=False, default="webcam")
    adapter = Column(String(80), nullable=False, default="http_image")
    region = Column(String(120), nullable=False, default="")
    status = Column(String(32), nullable=False, default="active")
    enabled = Column(Boolean, nullable=False, default=True)
    capture_cadence_minutes = Column(Integer, nullable=False, default=60)
    policy = Column(JSON, nullable=False, default=dict)
    meta_data = Column("metadata", JSON, nullable=False, default=dict)
    last_captured_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("workspace_id", "name", name="uq_workspace_visual_sources_workspace_name"),
        CheckConstraint("status IN ('active', 'paused', 'error')", name="ck_workspace_visual_sources_status"),
        CheckConstraint("adapter IN ('http_image', 'browser_screenshot', 'demo_static')", name="ck_workspace_visual_sources_adapter"),
        CheckConstraint("source_type IN ('webcam', 'image_snapshot', 'stream_embed')", name="ck_workspace_visual_sources_type"),
        Index("ix_workspace_visual_sources_workspace_status", "workspace_id", "status"),
    )


class WorkspaceVisualCapture(Base):
    """A single snapshot capture stored in ObjectStore."""

    __tablename__ = "workspace_visual_captures"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    source_id = Column(String(36), ForeignKey("workspace_visual_sources.id", ondelete="CASCADE"), nullable=False, index=True)
    job_id = Column(String(36), ForeignKey("workspace_jobs.id", ondelete="SET NULL"), nullable=True, index=True)
    status = Column(String(32), nullable=False, default="captured")
    object_key = Column(Text, nullable=False, default="")
    mime_type = Column(String(80), nullable=False, default="image/jpeg")
    size_bytes = Column(Integer, nullable=False, default=0)
    sha256 = Column(String(64), nullable=False, default="")
    width = Column(Integer, nullable=True)
    height = Column(Integer, nullable=True)
    error = Column(Text, nullable=True)
    meta_data = Column("metadata", JSON, nullable=False, default=dict)
    captured_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        CheckConstraint("status IN ('captured', 'analyzed', 'failed')", name="ck_workspace_visual_captures_status"),
        Index("ix_workspace_visual_captures_workspace_source", "workspace_id", "source_id"),
    )


class WorkspaceVisualObservation(Base):
    """Analysis result derived from a visual capture."""

    __tablename__ = "workspace_visual_observations"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    source_id = Column(String(36), ForeignKey("workspace_visual_sources.id", ondelete="CASCADE"), nullable=False, index=True)
    capture_id = Column(String(36), ForeignKey("workspace_visual_captures.id", ondelete="CASCADE"), nullable=False, index=True)
    summary = Column(Text, nullable=False, default="")
    tags = Column(JSON, nullable=False, default=list)
    confidence = Column(Float, nullable=False, default=0.65)
    vigilance_score = Column(Integer, nullable=False, default=0)
    level_label = Column(String(32), nullable=False, default="stable")
    source_refs = Column(JSON, nullable=False, default=list)
    provider = Column(String(80), nullable=False, default="rule_based")
    model = Column(String(160), nullable=True)
    meta_data = Column("metadata", JSON, nullable=False, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        CheckConstraint("level_label IN ('stable', 'monitoring', 'elevated', 'critical')", name="ck_workspace_visual_observations_level"),
        Index("ix_workspace_visual_observations_workspace_created", "workspace_id", "created_at"),
    )
