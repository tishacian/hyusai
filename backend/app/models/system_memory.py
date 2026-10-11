"""Durable per-system correlation state, updated while a gate waits.

Membrane valves decide HOLD; this table is the durable store reinjected into
the walker variable pool as ``memory.*`` on ``resume_run_dag``.
"""
from datetime import datetime
from uuid import uuid4

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, JSON, String, UniqueConstraint

from app.db.base import Base


class SystemMemory(Base):
    __tablename__ = "system_memory"

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
    correlation_key = Column(String(255), nullable=False)
    state = Column(JSON, nullable=False, default=dict)
    version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "system_id",
            "correlation_key",
            name="uq_system_memory_ws_system_corr",
        ),
        Index("ix_system_memory_lookup", "workspace_id", "system_id", "correlation_key"),
    )
