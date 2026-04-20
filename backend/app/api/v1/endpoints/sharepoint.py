"""SharePoint shared-folder connector endpoints.

The demo VM runs a single ``uvicorn`` process and does NOT have a Celery
broker. To keep the UX responsive while staying infrastructure-light we
rely on FastAPI's :class:`BackgroundTasks` + a tiny in-process job
registry protected by a :class:`threading.Lock`. Jobs survive as long as
the uvicorn worker lives; they are not persisted to SQL because:

- they carry no business state (the *output* lives on disk + in the
  RAG pipeline);
- the demo only has one uvicorn worker;
- a restart simply loses job metadata; the user can re-enqueue.

If we ever scale out or switch to multi-worker, swap the
``_JOB_REGISTRY`` for a SQL-backed table without changing the routes.

Why no browser-based interactive login server-side
---------------------------------------------------
The VM has no display and SSH-forwarded browsers are a poor UX. The
operator captures the OTP session on their laptop via the CLI and uploads
the resulting ``storage_state`` via ``PUT /sessions/{key}``. The server
re-encrypts it under its own Fernet key and stores it in
``settings.sharepoint_session_dir``.
"""

from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, BackgroundTasks, HTTPException, status
from pydantic import BaseModel, Field

from app.core.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()


# ---- bridge settings -> env for the connector's crypto module -----------
# The crypto module reads from os.environ so it stays usable from CLI / Celery
# contexts that don't import `app.core.config`. We propagate the settings
# values once at import time.
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
    # MSAL-only
    client_id: str | None = None
    tenant_host: str | None = None
    user_hint: str | None = None
    # Optional override (defaults to settings.sharepoint_download_dir / session_key)
    output_dir: str | None = None


class SessionUploadRequest(BaseModel):
    session_dict: dict = Field(
        ...,
        description=(
            "JSON dump of SharePointSession.to_dict() captured locally via the CLI "
            "(`python scripts/sharepoint_connector_demo.py ... --export-session`)."
        ),
    )


class SharePointJobSummary(BaseModel):
    job_id: str
    state: str  # "running" | "completed" | "failed"
    status: str | None = None  # "completed" | "login_required" | "failed"
    created_at: float
    updated_at: float
    progress: str | None = None
    files_total: int = 0
    files_downloaded: int = 0
    bytes_total: int = 0
    login_required_detail: str | None = None
    error: str | None = None
    output_dir: str | None = None


# ---- in-memory job registry --------------------------------------------


_JOB_REGISTRY: Dict[str, dict] = {}
_JOB_LOCK = threading.Lock()


def _new_job_record(output_dir: Path) -> tuple[str, dict]:
    job_id = str(uuid.uuid4())
    record = {
        "job_id": job_id,
        "state": "running",
        "status": None,
        "created_at": time.time(),
        "updated_at": time.time(),
        "progress": "queued",
        "files_total": 0,
        "files_downloaded": 0,
        "bytes_total": 0,
        "login_required_detail": None,
        "error": None,
        "output_dir": str(output_dir),
    }
    with _JOB_LOCK:
        _JOB_REGISTRY[job_id] = record
    return job_id, record


def _update_job(job_id: str, **fields: Any) -> None:
    with _JOB_LOCK:
        record = _JOB_REGISTRY.get(job_id)
        if record is None:
            return
        record.update(fields)
        record["updated_at"] = time.time()


def _read_job(job_id: str) -> dict | None:
    with _JOB_LOCK:
        record = _JOB_REGISTRY.get(job_id)
        return dict(record) if record is not None else None


# ---- background worker -------------------------------------------------


def _resolve_output_dir(request: SharePointSyncRequest) -> Path:
    if request.output_dir:
        return Path(request.output_dir)
    safe_key = request.session_key.replace("/", "_").replace(":", "_")
    return Path(settings.sharepoint_download_dir) / safe_key


def _run_sync_job(job_id: str, request: SharePointSyncRequest) -> None:
    """Invoked by FastAPI's BackgroundTasks. Runs in the uvicorn event loop's
    thread pool, so blocking I/O (Playwright, large downloads) is fine.
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
        _update_job(job_id, progress=msg)

    outcome = run_sync_from_payload(payload, progress=_progress)

    if outcome.status == "completed":
        result = outcome.result
        _update_job(
            job_id,
            state="completed",
            status="completed",
            files_total=result.files_total if result else 0,
            files_downloaded=result.files_downloaded if result else 0,
            bytes_total=result.bytes_total if result else 0,
            progress="done",
        )
    elif outcome.status == "login_required":
        _update_job(
            job_id,
            state="completed",
            status="login_required",
            login_required_detail=outcome.login_required_detail,
            progress="login_required",
        )
    else:
        _update_job(
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
    job_id, record = _new_job_record(output_dir)
    background_tasks.add_task(_run_sync_job, job_id, request)
    return SharePointJobSummary(**record)


@router.get(
    "/sync/{job_id}",
    response_model=SharePointJobSummary,
    summary="Fetch a sync job status + result.",
)
def get_sharepoint_job(job_id: str) -> SharePointJobSummary:
    record = _read_job(job_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Unknown job {job_id}")
    return SharePointJobSummary(**record)


@router.put(
    "/sessions/{session_key}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Upload an OTP-captured SharePoint session (storage_state).",
)
def upload_sharepoint_session(
    session_key: str, body: SessionUploadRequest
) -> None:
    """Persist a :class:`SharePointSession` captured on the operator's laptop.

    This is the "reconnect SharePoint" path: when a sync finishes with
    ``status='login_required'``, the UI asks the operator to rerun
    ``scripts/sharepoint_connector_demo.py --force-reauth --export-session``
    locally, copy the printed JSON block, and PUT it here. The server
    re-encrypts it under its own Fernet key so the plaintext never lands
    on disk unless encryption is unconfigured.
    """
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
    from app.services.connectors.sharepoint_otp import (
        SharePointSessionStore,
    )

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
    from app.services.connectors.sharepoint_otp import (
        SharePointSessionStore,
    )

    SharePointSessionStore(settings.sharepoint_session_dir).delete(session_key)
