"""Payload models for the SharePoint shared-folder sync Celery task."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


class SharePointSyncPayload(BaseModel):
    """Inputs for the SharePoint ingestion Celery job.

    The payload is identical for both auth back-ends; only ``auth_mode``
    and the relevant side of the fields are consumed.

    ``session_key`` uniquely identifies the persisted session/token cache
    for this connector — typically a workspace/connector UUID. Having an
    explicit key means the worker can look up the right encrypted blob
    without having to hash the sharing URL.
    """

    auth_mode: Literal["session", "msal"] = "session"
    folder_server_relative_url: str = Field(
        ..., description="E.g. '/sites/107645/Shared Documents/Test_partage_externe'"
    )
    output_dir: Path = Field(
        ..., description="Local directory where files will be materialised."
    )
    session_key: str = Field(
        ..., description="Key used to store/retrieve cached auth state."
    )
    session_dir: Path = Field(
        default=Path(".sharepoint_sessions"),
        description="Directory containing the encrypted session/token cache.",
    )
    prune_local_files: bool = False

    # Session mode only:
    sharing_url: str | None = None

    # MSAL mode only:
    client_id: str | None = None
    tenant_host: str | None = None
    user_hint: str | None = None


class SharePointSyncResult(BaseModel):
    """Normalised result returned to the core after a sync attempt."""

    status: Literal["completed", "login_required", "failed"]
    files_total: int = 0
    files_downloaded: int = 0
    bytes_total: int = 0
    downloaded_paths: list[str] = Field(default_factory=list)
    skipped_paths: list[str] = Field(default_factory=list)
    pruned_paths: list[str] = Field(default_factory=list)
    login_required_detail: str | None = None
    error: str | None = None
