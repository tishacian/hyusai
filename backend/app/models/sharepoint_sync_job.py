"""Persisted state for SharePoint sync jobs.

Single table, scoped to a workspace via ``workspace_id`` so each tenant
only sees its own sync history through the listing endpoint. Progress
and result metadata live in plain columns (strings + ints) so any
worker — the API process or a future Celery consumer — can update them
without needing a shared JSON schema.

Schema evolution:
    - 012: initial table (id, session_key, auth_mode, state, progress,
      files_*, bytes_total, login_required_detail, error, output_dir,
      folder_server_relative_url, created_at, updated_at).
    - df4cf80 introduced ``workspace_id`` in the SQL model but shipped
      *without* a migration; catch-up shipped as 014 after the drift
      was caught during E4.1 smoke.
    - 013: added ``ingested_count`` / ``ingest_failed_count`` /
      ``collection_name`` for the RAG wiring step of E4.1.
"""

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text

from app.db.base import Base


class SharePointSyncJob(Base):
    __tablename__ = "sharepoint_sync_jobs"

    id = Column(String(36), primary_key=True)
    workspace_id = Column(
        String(36), ForeignKey("workspaces.id"), nullable=True, index=True
    )
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
    # Populated after the sync completes and files are piped through
    # DocumentService.ingest_document. `ingested_count` counts successes,
    # `ingest_failed_count` counts parser/embedder rejections. These tell
    # apart "sync worked but some PDFs won't parse" from "sync itself
    # failed". See migration 013.
    ingested_count = Column(Integer, nullable=False, default=0, server_default="0")
    ingest_failed_count = Column(Integer, nullable=False, default=0, server_default="0")
    # Which logical collection the ingested docs landed in (symmetric with
    # POST /documents/upload's `collection_name` form field). NULL while
    # the job is running or if ingest was skipped entirely.
    collection_name = Column(String(100), nullable=True)
    login_required_detail = Column(Text, nullable=True)
    error = Column(Text, nullable=True)
    output_dir = Column(Text, nullable=True)
    folder_server_relative_url = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )
