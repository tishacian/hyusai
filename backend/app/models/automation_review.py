"""A reservation on one automation result, then a reread and a comparison.

The system id is the object. A later result from another automation is refused.
"""
from datetime import datetime
from uuid import uuid4

from sqlalchemy import Column, DateTime, ForeignKey, String, Text

from app.db.base import Base


class AutomationReview(Base):
    __tablename__ = "automation_reviews"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id = Column(String(36), ForeignKey("workspaces.id"), nullable=False, index=True)
    system_id = Column(String(36), ForeignKey("systems.id"), nullable=False, index=True)
    run_id = Column(String(36), ForeignKey("runs.id"), nullable=False)
    note = Column(Text, nullable=False)
    status = Column(String(20), nullable=False, default="reserved")
    draft_hash = Column(String(64), nullable=True)
    correction_hash = Column(String(64), nullable=True)
    later_run_id = Column(String(36), ForeignKey("runs.id"), nullable=True)
    created_by_user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
