"""Workspace-scoped cache for macro indicators (World Bank or other sources).

The cache decouples the public sparkline cockpit (Phase B of the AYA demo)
from the live World Bank Open Data endpoint, with a JSON fallback when the
upstream is unreachable. One row per (workspace, indicator_key).
"""
from datetime import datetime
from uuid import uuid4

from sqlalchemy import Column, DateTime, ForeignKey, Index, JSON, String

from app.db.base import Base


class WorkspaceMacroIndicator(Base):
    __tablename__ = "workspace_macro_indicators"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id = Column(
        String(36),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    indicator_key = Column(String(64), nullable=False)
    source = Column(String(64), nullable=False, default="world_bank")
    label = Column(String(160), nullable=False, default="")
    unit = Column(String(32), nullable=False, default="")
    series = Column(JSON, nullable=False, default=list)
    current = Column(JSON, nullable=True)
    trend = Column(String(32), nullable=False, default="")
    fetched_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    status = Column(String(32), nullable=False, default="cached")
    meta_data = Column("metadata", JSON, nullable=False, default=dict)

    __table_args__ = (
        Index(
            "ux_workspace_macro_indicator_key",
            "workspace_id",
            "indicator_key",
            unique=True,
        ),
    )
