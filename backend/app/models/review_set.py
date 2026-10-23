"""Review sets: records a System produced, opened for per-record human review.

See docs/agentium-experience-lot10-review-workbench.md. Decisions are
append-only; the item row carries the latest one for filtering.
"""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)

from app.db.base import Base


class ReviewSet(Base):
    __tablename__ = "review_sets"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id = Column(
        String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    namespace = Column(String(80), nullable=False)
    group_key = Column(String(200), nullable=False)
    group_labels = Column(JSON, nullable=False, default=dict)
    title = Column(String(300), nullable=False)
    source = Column(JSON, nullable=False, default=dict)
    taxonomy = Column(JSON, nullable=False, default=dict)
    policy = Column(JSON, nullable=False, default=dict)
    reviewers = Column(JSON, nullable=True)
    status = Column(String(16), nullable=False, default="open", index=True)
    item_count = Column(Integer, nullable=False, default=0)
    decided_count = Column(Integer, nullable=False, default=0)
    deadline_at = Column(DateTime, nullable=True)
    created_by = Column(String(36), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    closed_at = Column(DateTime, nullable=True)
    # Set once review_set.completed has been handed to the trigger registry.
    event_emitted_at = Column(DateTime, nullable=True)

    __table_args__ = (CheckConstraint("status IN ('open','closed')", name="ck_review_sets_status"),)


class ReviewItem(Base):
    __tablename__ = "review_items"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    set_id = Column(
        String(36), ForeignKey("review_sets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    item_ref = Column(String(200), nullable=False)
    position = Column(Integer, nullable=False)
    tier = Column(String(40), nullable=False)
    weight = Column(Float, nullable=False, default=1.0)
    subject = Column(JSON, nullable=False, default=dict)
    search_text = Column(Text, nullable=False, default="")
    revision = Column(Integer, nullable=False, default=0)
    claimed_by = Column(String(36), nullable=True)
    claim_expires_at = Column(DateTime, nullable=True)
    status = Column(String(16), nullable=False, default="pending", index=True)
    worst_severity = Column(String(40), nullable=True)
    categories = Column(JSON, nullable=False, default=list)
    decided_by = Column(String(36), nullable=True)
    decided_at = Column(DateTime, nullable=True)
    duration_ms = Column(Integer, nullable=False, default=0)

    __table_args__ = (
        UniqueConstraint("set_id", "item_ref", name="uq_review_items_set_ref"),
        CheckConstraint(
            "status IN ('pending','approve','correct','reject')", name="ck_review_items_status"
        ),
    )


class ReviewDecision(Base):
    __tablename__ = "review_decisions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    item_id = Column(
        String(36), ForeignKey("review_items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    set_id = Column(String(36), nullable=False, index=True)
    revision = Column(Integer, nullable=False)
    decision = Column(String(16), nullable=False)
    value = Column(Text, nullable=True)
    annotations = Column(JSON, nullable=False, default=list)
    comment = Column(Text, nullable=True)
    duration_ms = Column(Integer, nullable=False, default=0)
    decided_by = Column(String(36), nullable=True)
    decided_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("item_id", "revision", name="uq_review_decisions_item_revision"),
        CheckConstraint(
            "decision IN ('approve','correct','reject')", name="ck_review_decisions_decision"
        ),
    )
