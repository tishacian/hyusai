"""Workspace-scoped map system models."""
from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    Boolean,
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


class WorkspaceMap(Base):
    """A configurable map surface owned by a workspace."""

    __tablename__ = "workspace_maps"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    system_id = Column(String(36), ForeignKey("systems.id", ondelete="SET NULL"), nullable=True, index=True)
    slug = Column(String(120), nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=False, default="")
    country = Column(String(120), nullable=False, default="")
    projection = Column(String(80), nullable=False, default="illustrative_exec_demo")
    view_box = Column(String(80), nullable=False, default="")
    center = Column(JSON, nullable=False, default=dict)
    settings = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("workspace_id", "slug", name="uq_workspace_maps_workspace_slug"),
        Index("ix_workspace_maps_workspace_slug", "workspace_id", "slug"),
    )


class WorkspaceMapLayer(Base):
    """A visible data layer in a workspace map."""

    __tablename__ = "workspace_map_layers"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    map_id = Column(String(36), ForeignKey("workspace_maps.id", ondelete="CASCADE"), nullable=False, index=True)
    key = Column(String(120), nullable=False)
    label = Column(String(255), nullable=False)
    kind = Column(String(80), nullable=False, default="zone")
    visible = Column(Boolean, nullable=False, default=True)
    payload = Column(JSON, nullable=False, default=dict)
    sort_order = Column(Integer, nullable=False, default=0)

    __table_args__ = (
        UniqueConstraint("map_id", "key", name="uq_workspace_map_layers_map_key"),
        Index("ix_workspace_map_layers_map_sort", "map_id", "sort_order"),
    )


class WorkspaceMapZone(Base):
    """A scored territory or operational zone."""

    __tablename__ = "workspace_map_zones"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    map_id = Column(String(36), ForeignKey("workspace_maps.id", ondelete="CASCADE"), nullable=False, index=True)
    zone_key = Column(String(120), nullable=False)
    name = Column(String(255), nullable=False)
    level = Column(Integer, nullable=False, default=0)
    tone = Column(String(32), nullable=False, default="stable")
    polygon = Column(Text, nullable=False, default="")
    centroid = Column(JSON, nullable=False, default=dict)
    meta_data = Column("metadata", JSON, nullable=False, default=dict)
    source_refs = Column(JSON, nullable=False, default=list)

    __table_args__ = (
        UniqueConstraint("map_id", "zone_key", name="uq_workspace_map_zones_map_key"),
        Index("ix_workspace_map_zones_map_level", "map_id", "level"),
    )


class WorkspaceMapSignal(Base):
    """Signal attached to a map zone or to a map globally."""

    __tablename__ = "workspace_map_signals"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    map_id = Column(String(36), ForeignKey("workspace_maps.id", ondelete="CASCADE"), nullable=False, index=True)
    zone_id = Column(String(36), ForeignKey("workspace_map_zones.id", ondelete="SET NULL"), nullable=True, index=True)
    source_kind = Column(String(80), nullable=False, default="mission_room")
    source_id = Column(String(160), nullable=False, default="")
    title = Column(String(255), nullable=False)
    summary = Column(Text, nullable=False, default="")
    weight = Column(Integer, nullable=False, default=10)
    confidence = Column(Float, nullable=False, default=0.65)
    occurred_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    meta_data = Column("metadata", JSON, nullable=False, default=dict)

    __table_args__ = (
        Index("ix_workspace_map_signals_map_source", "map_id", "source_kind", "source_id"),
    )


class WorkspaceMapScore(Base):
    """Computed score for a zone during a map scoring job."""

    __tablename__ = "workspace_map_scores"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    map_id = Column(String(36), ForeignKey("workspace_maps.id", ondelete="CASCADE"), nullable=False, index=True)
    zone_id = Column(String(36), ForeignKey("workspace_map_zones.id", ondelete="CASCADE"), nullable=False, index=True)
    job_id = Column(String(36), ForeignKey("workspace_jobs.id", ondelete="SET NULL"), nullable=True, index=True)
    score = Column(Integer, nullable=False, default=0)
    level_label = Column(String(32), nullable=False, default="stable")
    drivers = Column(JSON, nullable=False, default=list)
    recommendations = Column(JSON, nullable=False, default=list)
    recommended_windows = Column(JSON, nullable=False, default=list)
    computed_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_workspace_map_scores_map_zone", "map_id", "zone_id"),
    )
