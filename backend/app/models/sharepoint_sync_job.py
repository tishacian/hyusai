"""Persisted state for SharePoint sync jobs.

We keep this simple (single table, no FK to Task/Workspace for now) because
the SharePoint connector runs at the platform level rather than per-workspace,
and the demo VM has only one operator. Progress / result metadata is stored
as text columns so we can query them from any worker without serialisation
surprises.
"""

from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, Text

from app.db.base import Base


class SharePointSyncJob(Base):
    __tablename__ = "sharepoint_sync_jobs"

    id = Column(String(36), primary_key=True)
    session_key = Column(String(255), nullable=False, index=True)
    auth_mode = Column(String(16), nullable=False, default="session")
    # "running" | "completed" | "failed"
    state = Column(String(20), nullable=False, default="running")
    # Refined status set once the job terminates:
    # "completed" | "login_required" | "failed" | None while running.
    status = Column(String(30), nullable=True)
    progress = Column(String(120), nullable=True)
    files_total = Column(Integer, default=0)
    files_downloaded = Column(Integer, default=0)
    bytes_total = Column(Integer, default=0)
    login_required_detail = Column(Text, nullable=True)
    error = Column(Text, nullable=True)
    output_dir = Column(Text, nullable=True)
    folder_server_relative_url = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )
