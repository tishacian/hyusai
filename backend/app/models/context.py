"""Canonical Context — the typed bag of state available to a System Run.

Contexts version explicitly so that adaptive policies can roll back to a
known-good context if confidence collapses.
"""
from datetime import datetime
from uuid import uuid4

from sqlalchemy import Column, DateTime, Integer, JSON, String

from app.db.base import Base


class Context(Base):
    __tablename__ = "contexts"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id = Column(String(36), nullable=True, index=True)
    system_id = Column(String(36), nullable=True, index=True)

    name = Column(String(200), nullable=False, default="default")
    version = Column(Integer, default=1)

    data_refs = Column(JSON, default=list)
    memory_refs = Column(JSON, default=list)
    history_refs = Column(JSON, default=list)
    environment_state = Column(JSON, default=dict)
    business_constraints = Column(JSON, default=dict)
    permissions = Column(JSON, default=dict)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
