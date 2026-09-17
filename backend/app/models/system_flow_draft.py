"""Server-owned mutable Flow draft, separate from published execution state."""

from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.db.base import Base


class SystemFlowDraft(Base):
    """Exactly one optimistic-concurrency draft per System.

    ``revision`` is monotonic for semantic draft changes. A byte-equivalent
    JSON save is a no-op and does not consume a revision. The published base is
    an immutable SystemVersion id, never a copy of mutable System state.
    """

    __tablename__ = "system_flow_drafts"

    system_id = Column(
        String(36),
        ForeignKey("systems.id", ondelete="CASCADE"),
        primary_key=True,
    )
    workspace_id = Column(
        String(36),
        ForeignKey("workspaces.id"),
        nullable=True,
        index=True,
    )
    flow_definition = Column(JSON, nullable=False, default=dict)
    # NULL preserves the legacy authority until an explicit draft save or
    # publication captures it. Never backfill historical policy guesses.
    control_policy_snapshot = Column(JSON, nullable=True)
    revision = Column(Integer, nullable=False, default=1)
    flow_sha256 = Column(String(64), nullable=False)
    base_published_version_id = Column(
        String(36),
        ForeignKey("system_versions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    updated_by = Column(String(255), nullable=False, default="migration-077")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    system = relationship(
        "System",
        back_populates="flow_draft",
        foreign_keys=[system_id],
    )

    __table_args__ = (
        CheckConstraint("revision >= 1", name="ck_system_flow_drafts_revision_positive"),
    )
