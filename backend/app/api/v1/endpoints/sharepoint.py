"""SharePoint shared-folder connector endpoints.

The demo VM runs uvicorn with multiple workers and does NOT have a
Celery broker. To keep the UX responsive while staying
infrastructure-light we rely on :class:`BackgroundTasks` and persist
job metadata in the app DB (see :class:`SharePointSyncJob`) so the
``GET /sync/{job_id}`` endpoint works from any worker.

Why no browser-based interactive login server-side
---------------------------------------------------
The VM has no display and SSH-forwarded browsers are a poor UX. The
operator captures the OTP session on their laptop via the CLI and
uploads the resulting ``storage_state`` via ``PUT /sessions/{key}``.
The server re-encrypts it under its own Fernet key (if configured) and
stores it in ``settings.sharepoint_session_dir``.
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DBSession

from app.core.config import settings
from app.db.base import SessionLocal, get_db
from app.models.sharepoint_sync_job import SharePointSyncJob

logger = logging.getLogger(__name__)
router = APIRouter()


# ---- bridge settings -> env for the connector's crypto module -----------
# The crypto module reads from os.environ so it stays usable from CLI
# contexts that don't import `app.core.config`. We propagate the
# configured values once at import time.
if settings.sharepoint_connector_fernet_key:
    os.environ.setdefault(
        "SHAREPOINT_CONNECTOR_FERNET_KEY",
        settings.sharepoint_connector_fernet_key,
    )
if settings.sharepoint_connector_require_encryption:
    os.environ.setdefault("SHAREPOINT_CONNECTOR_REQUIRE_ENCRYPTION", "1")


# ---- payloads -----------------------------------------------------------


class SharePointSyncRequest(BaseModel):
    session_key: str = Field(
        ..., description="Server-side identifier of the cached session / tokens."
    )
    folder_server_relative_url: str = Field(
        ...,
        description=(
            "Target folder, e.g. '/sites/107645/Shared Documents/Test_partage_externe'."
        ),
    )
    sharing_url: str | None = Field(
        None,
        description="Sharing link (required for auth_mode='session').",
    )
    auth_mode: str = Field("session", pattern="^(session|msal)$")
    prune_local_files: bool = False
    client_id: str | None = None
    tenant_host: str | None = None
    user_hint: str | None = None
    output_dir: str | None = None


class SessionUploadRequest(BaseModel):
    session_dict: dict = Field(
        ...,
        description=(
            "JSON dump of SharePointSession.to_dict() captured locally via the "
            "CLI (`python scripts/sharepoint_connector_demo.py ... "
            "--export-session`)."
        ),
    )


class SharePointJobSummary(BaseModel):
    job_id: str
    session_key: str
    auth_mode: str
    state: str
    status: str | None = None
    progress: str | None = None
    files_total: int = 0
    files_downloaded: int = 0
    bytes_total: int = 0
    login_required_detail: str | None = None
    error: str | None = None
    output_dir: str | None = None
    folder_server_relative_url: str | None = None
    created_at: str
    updated_at: str


def _job_to_summary(job: SharePointSyncJob) -> SharePointJobSummary:
    return SharePointJobSummary(
        job_id=job.id,
        session_key=job.session_key,
        auth_mode=job.auth_mode,
        state=job.state,
        status=job.status,
        progress=job.progress,
        files_total=job.files_total or 0,
        files_downloaded=job.files_downloaded or 0,
        bytes_total=job.bytes_total or 0,
        login_required_detail=job.login_required_detail,
        error=job.error,
        output_dir=job.output_dir,
        folder_server_relative_url=job.folder_server_relative_url,
        created_at=job.created_at.isoformat() if job.created_at else "",
        updated_at=job.updated_at.isoformat() if job.updated_at else "",
    )


# ---- helpers -----------------------------------------------------------


def _resolve_output_dir(request: SharePointSyncRequest) -> Path:
    if request.output_dir:
        return Path(request.output_dir)
    safe_key = request.session_key.replace("/", "_").replace(":", "_")
    return Path(settings.sharepoint_download_dir) / safe_key


def _update_job_row(job_id: str, **fields: object) -> None:
    """Open a short-lived DB session to update a job. Called from background
    workers where the request-scoped session is no longer available.
    """
    db = SessionLocal()
    try:
        job = db.query(SharePointSyncJob).filter(SharePointSyncJob.id == job_id).first()
        if job is None:
            return
        for key, value in fields.items():
            setattr(job, key, value)
        job.updated_at = datetime.utcnow()
        db.commit()
    finally:
        db.close()


# ---- background worker -------------------------------------------------


def _run_sync_job(job_id: str, request: SharePointSyncRequest) -> None:
    """Runs in FastAPI's thread pool; blocking I/O (Playwright, downloads)
    is fine here.
    """
    from types import SimpleNamespace

    from app.services.connectors.sharepoint_otp.celery_service import (
        run_sync_from_payload,
    )

    output_dir = _resolve_output_dir(request)
    payload = SimpleNamespace(
        auth_mode=request.auth_mode,
        folder_server_relative_url=request.folder_server_relative_url,
        output_dir=output_dir,
        session_key=request.session_key,
        session_dir=Path(settings.sharepoint_session_dir),
        sharing_url=request.sharing_url,
        prune_local_files=request.prune_local_files,
        client_id=request.client_id,
        tenant_host=request.tenant_host,
        user_hint=request.user_hint,
    )

    def _progress(msg: str) -> None:
        _update_job_row(job_id, progress=str(msg)[:120])

    try:
        outcome = run_sync_from_payload(payload, progress=_progress)
    except Exception as exc:  # noqa: BLE001 - we persist failures
        logger.exception("SharePoint sync job %s crashed", job_id)
        _update_job_row(
            job_id,
            state="failed",
            status="failed",
            error=f"{type(exc).__name__}: {exc}",
            progress="failed",
        )
        return

    if outcome.status == "completed":
        result = outcome.result
        _update_job_row(
            job_id,
            state="completed",
            status="completed",
            files_total=result.files_total if result else 0,
            files_downloaded=result.files_downloaded if result else 0,
            bytes_total=result.bytes_total if result else 0,
            progress="done",
        )
    elif outcome.status == "login_required":
        _update_job_row(
            job_id,
            state="completed",
            status="login_required",
            login_required_detail=outcome.login_required_detail,
            progress="login_required",
        )
    else:
        _update_job_row(
            job_id,
            state="failed",
            status="failed",
            error=outcome.error,
            progress="failed",
        )


# ---- routes -------------------------------------------------------------


@router.post(
    "/sync",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=SharePointJobSummary,
    summary="Trigger an incremental sync of a SharePoint shared folder.",
)
def enqueue_sharepoint_sync(
    request: SharePointSyncRequest,
    background_tasks: BackgroundTasks,
    db: DBSession = Depends(get_db),
) -> SharePointJobSummary:
    if request.auth_mode == "session" and not request.sharing_url:
        raise HTTPException(
            status_code=400,
            detail="sharing_url is required when auth_mode='session'.",
        )
    if request.auth_mode == "msal" and (
        not request.client_id or not request.tenant_host
    ):
        raise HTTPException(
            status_code=400,
            detail="client_id and tenant_host are required when auth_mode='msal'.",
        )

    output_dir = _resolve_output_dir(request)
    job = SharePointSyncJob(
        id=str(uuid.uuid4()),
        session_key=request.session_key,
        auth_mode=request.auth_mode,
        state="running",
        status=None,
        progress="queued",
        output_dir=str(output_dir),
        folder_server_relative_url=request.folder_server_relative_url,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    background_tasks.add_task(_run_sync_job, job.id, request)
    return _job_to_summary(job)


@router.get(
    "/sync/{job_id}",
    response_model=SharePointJobSummary,
    summary="Fetch a sync job status + result.",
)
def get_sharepoint_job(
    job_id: str, db: DBSession = Depends(get_db)
) -> SharePointJobSummary:
    job = db.query(SharePointSyncJob).filter(SharePointSyncJob.id == job_id).first()
    if job is None:
        raise HTTPException(status_code=404, detail=f"Unknown job {job_id}")
    return _job_to_summary(job)


@router.get(
    "/sync",
    summary="List recent SharePoint sync jobs.",
)
def list_sharepoint_jobs(
    limit: int = 20, db: DBSession = Depends(get_db)
) -> dict:
    rows = (
        db.query(SharePointSyncJob)
        .order_by(SharePointSyncJob.created_at.desc())
        .limit(limit)
        .all()
    )
    return {"jobs": [_job_to_summary(job).model_dump() for job in rows]}


@router.put(
    "/sessions/{session_key}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Upload an OTP-captured SharePoint session (storage_state).",
)
def upload_sharepoint_session(
    session_key: str, body: SessionUploadRequest
) -> None:
    from app.services.connectors.sharepoint_otp import (
        SharePointSession,
        SharePointSessionStore,
    )

    try:
        session = SharePointSession.from_dict(body.session_dict)
    except Exception as exc:
        raise HTTPException(
            status_code=400, detail=f"Invalid session payload: {exc}"
        ) from exc

    if not session.storage_state:
        raise HTTPException(
            status_code=400,
            detail=(
                "session_dict.storage_state is empty; recapture via the CLI "
                "and make sure the OTP + Authenticator flow completed."
            ),
        )

    store = SharePointSessionStore(settings.sharepoint_session_dir)
    store.save(session_key, session)


@router.get(
    "/sessions/{session_key}",
    summary="Check whether a SharePoint session is cached server-side.",
)
def get_sharepoint_session_status(session_key: str) -> dict:
    from app.services.connectors.sharepoint_otp import SharePointSessionStore

    store = SharePointSessionStore(settings.sharepoint_session_dir)
    session = store.load(session_key)
    if session is None:
        return {"session_key": session_key, "exists": False}
    return {
        "session_key": session_key,
        "exists": True,
        "tenant_host": session.tenant_host,
        "sharing_url": session.sharing_url,
        "captured_at": session.captured_at,
    }


@router.delete(
    "/sessions/{session_key}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Forget a cached SharePoint session.",
)
def delete_sharepoint_session(session_key: str) -> None:
    from app.services.connectors.sharepoint_otp import SharePointSessionStore

    SharePointSessionStore(settings.sharepoint_session_dir).delete(session_key)
