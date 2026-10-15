"""Shared admission counters; no request payload or API key secret is stored."""

from sqlalchemy import BigInteger, Column, DateTime, Integer, String

from app.db.base import Base


class MLAdmissionCounter(Base):
    __tablename__ = "ml_admission_counters"
    scope = Column(String(96), primary_key=True)
    window_at = Column(DateTime, primary_key=True)
    requests = Column(Integer, nullable=False, default=0)
    rows = Column(BigInteger, nullable=False, default=0)


class MLWorkspaceLock(Base):
    __tablename__ = "ml_workspace_locks"
    workspace_id = Column(String(36), primary_key=True)
    generation = Column(BigInteger, nullable=False, default=0)
