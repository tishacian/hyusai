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

from app.core.auth import get_current_user, get_current_workspace
from app.core.config import settings
from app.db.base import SessionLocal, get_db
from app.models.sharepoint_sync_job import SharePointSyncJob
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services.audit_logger import emit_audit_event

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
    # E4.1 — which logical RAG collection the downloaded files should be
    # ingested into. Default "documents" so chat sees them automatically
    # (the drop-and-ask flow reads from the same collection). Keep it
    # short + filesystem-safe: we pass it verbatim to DocumentService /
    # Qdrant, scoping per-workspace is done at the service layer.
    collection_name: str = Field("documents", min_length=1, max_length=100)


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
    ingested_count: int = 0
    ingest_failed_count: int = 0
    collection_name: str | None = None
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
        ingested_count=job.ingested_count or 0,
        ingest_failed_count=job.ingest_failed_count or 0,
        collection_name=job.collection_name,
        login_required_detail=job.login_required_detail,
        error=job.error,
        output_dir=job.output_dir,
        folder_server_relative_url=job.folder_server_relative_url,
        created_at=job.created_at.isoformat() if job.created_at else "",
        updated_at=job.updated_at.isoformat() if job.updated_at else "",
    )


# ---- helpers -----------------------------------------------------------


def _scoped_session_key(workspace: Workspace, session_key: str) -> str:
    """Namespace session_key by workspace so two workspaces never share
    cached SharePoint sessions on disk or in the DB.
    """
    safe_key = session_key.replace("/", "_").replace(":", "_").strip()
    if not safe_key:
        raise HTTPException(status_code=400, detail="session_key must not be empty")
    return f"ws_{workspace.id}__{safe_key}"


def _resolve_output_dir(
    workspace: Workspace, request: SharePointSyncRequest
) -> Path:
    if request.output_dir:
        return Path(request.output_dir)
    safe_key = request.session_key.replace("/", "_").replace(":", "_")
    return Path(settings.sharepoint_download_dir) / workspace.slug / safe_key


def _require_admin_role(db: DBSession, user: User, workspace: Workspace) -> None:
    """Mutating session state is an operator-grade action (it persists
    live cookies server-side). Restrict it to workspace owners/admins.
    """
    membership = (
        db.query(WorkspaceMember)
        .filter(
            WorkspaceMember.user_id == user.id,
            WorkspaceMember.workspace_id == workspace.id,
        )
        .first()
    )
    if membership is None or membership.role not in ("owner", "admin"):
        raise HTTPException(
            status_code=403,
            detail="Workspace admin or owner role required.",
        )


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


def _ingest_downloaded_files(
    *,
    result,  # IngestionResult
    output_dir: Path,
    workspace_id: str,
    workspace_slug: str,
    collection_name: str,
) -> tuple[int, int]:
    """Pipe every freshly downloaded file through the RAG pipeline.

    Runs **after** the connector has materialised files to disk; reuses
    the same ``DocumentService.ingest_document`` path that
    ``POST /documents/upload`` exercises (see ``documents.py``) so chat
    and drop-and-ask see SharePoint files with zero extra configuration.

    We only ingest ``downloaded_paths`` (new or changed files in this
    run). Files already in the manifest were skipped during sync →
    skipping them here too avoids duplicate vectors in Qdrant.

    :returns: ``(ingested_count, failed_count)``. Never raises —
        ingestion failures are tallied and persisted on the job row,
        but the sync itself is still reported ``completed``.
    """
    from app.core.settings_manager import get_resolved_settings
    from app.services.rag.document_service import DocumentService
    from app.services.rag.vector_store_config import resolve_vector_db_type

    if not result or not result.downloaded_paths:
        return 0, 0

    app_settings = get_resolved_settings(workspace_id=workspace_id)
    # Match the drop-and-ask / documents upload path exactly so search lands
    # in the same vector store collection and chat sees the files.
    db_type = resolve_vector_db_type(app_settings)

    try:
        doc_service = DocumentService(
            collection_name=collection_name,
            vector_db_type=db_type,
            workspace_slug=workspace_slug,
        )
    except Exception:  # noqa: BLE001 — embedder boot can fail
        logger.exception(
            "DocumentService init failed for SharePoint ingest "
            "(workspace=%s, collection=%s) — skipping ingest pass",
            workspace_slug,
            collection_name,
        )
        return 0, len(result.downloaded_paths)

    import asyncio

    # Background task already runs in a thread-pool worker with no event
    # loop; spin up a dedicated loop for the async ingest calls.
    loop = asyncio.new_event_loop()
    ingested = 0
    failed = 0
    try:
        asyncio.set_event_loop(loop)
        # `downloaded_paths` are absolute ``Path`` objects rooted under
        # ``output_dir`` (see ingester.py: ``target_file = target_dir /
        # f.name``). Use them directly; joining to ``output_dir`` again
        # would silently ignore the relative part because ``Path / abs``
        # returns ``abs``.
        for downloaded in result.downloaded_paths:
            abs_path = Path(downloaded)
            if not abs_path.is_absolute():
                abs_path = (output_dir / abs_path).resolve()
            if not abs_path.exists():
                logger.warning(
                    "SharePoint ingest: path %s not on disk (expected in %s)",
                    downloaded,
                    output_dir,
                )
                failed += 1
                continue
            try:
                outcome_ingest = loop.run_until_complete(
                    doc_service.ingest_document(str(abs_path))
                )
            except Exception:  # noqa: BLE001 — parser/embedder can throw
                logger.exception(
                    "SharePoint ingest failed for %s (collection=%s)",
                    abs_path,
                    collection_name,
                )
                failed += 1
                continue
            # DocumentService.ingest_document returns a dict shaped
            # {status, document_id, chunks_processed, ...}. Treat any
            # non-"error" status as success — this includes the
            # "already indexed" fast path when the file hash matches.
            status_val = (
                outcome_ingest.get("status") if isinstance(outcome_ingest, dict) else None
            )
            if status_val == "error":
                failed += 1
            else:
                ingested += 1
    finally:
        try:
            loop.close()
        except Exception:  # noqa: BLE001
            pass

    return ingested, failed


def _run_sync_job(
    job_id: str,
    request: SharePointSyncRequest,
    scoped_key: str,
    output_dir: Path,
    *,
    workspace_id: str,
    workspace_slug: str,
    actor: str,
) -> None:
    """Runs in FastAPI's thread pool; blocking I/O (Playwright, downloads)
    is fine here.
    """
    from types import SimpleNamespace

    from app.services.connectors.sharepoint_otp.celery_service import (
        run_sync_from_payload,
    )

    payload = SimpleNamespace(
        auth_mode=request.auth_mode,
        folder_server_relative_url=request.folder_server_relative_url,
        output_dir=output_dir,
        session_key=scoped_key,
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
        emit_audit_event(
            workspace_id=workspace_id,
            actor=actor,
            event_type="sharepoint.sync.failed",
            severity="warning",
            details={
                "job_id": job_id,
                "session_key": request.session_key,
                "auth_mode": request.auth_mode,
                "folder": request.folder_server_relative_url,
                "error": f"{type(exc).__name__}: {exc}",
            },
        )
        return

    if outcome.status == "completed":
        result = outcome.result
        _update_job_row(
            job_id,
            files_total=result.files_total if result else 0,
            files_downloaded=result.files_downloaded if result else 0,
            bytes_total=result.bytes_total if result else 0,
            progress="ingesting",
            collection_name=request.collection_name,
        )
        ingested, failed = _ingest_downloaded_files(
            result=result,
            output_dir=output_dir,
            workspace_id=workspace_id,
            workspace_slug=workspace_slug,
            collection_name=request.collection_name,
        )
        _update_job_row(
            job_id,
            state="completed",
            status="completed",
            ingested_count=ingested,
            ingest_failed_count=failed,
            progress="done",
        )
        emit_audit_event(
            workspace_id=workspace_id,
            actor=actor,
            event_type="sharepoint.sync.completed",
            details={
                "job_id": job_id,
                "session_key": request.session_key,
                "auth_mode": request.auth_mode,
                "folder": request.folder_server_relative_url,
                "collection_name": request.collection_name,
                "files_total": result.files_total if result else 0,
                "files_downloaded": result.files_downloaded if result else 0,
                "bytes_total": result.bytes_total if result else 0,
                "ingested_count": ingested,
                "ingest_failed_count": failed,
            },
        )
    elif outcome.status == "login_required":
        _update_job_row(
            job_id,
            state="completed",
            status="login_required",
            login_required_detail=outcome.login_required_detail,
            progress="login_required",
        )
        emit_audit_event(
            workspace_id=workspace_id,
            actor=actor,
            event_type="sharepoint.sync.login_required",
            severity="warning",
            details={
                "job_id": job_id,
                "session_key": request.session_key,
                "auth_mode": request.auth_mode,
                "detail": outcome.login_required_detail,
            },
        )
    else:
        _update_job_row(
            job_id,
            state="failed",
            status="failed",
            error=outcome.error,
            progress="failed",
        )
        emit_audit_event(
            workspace_id=workspace_id,
            actor=actor,
            event_type="sharepoint.sync.failed",
            severity="warning",
            details={
                "job_id": job_id,
                "session_key": request.session_key,
                "auth_mode": request.auth_mode,
                "folder": request.folder_server_relative_url,
                "error": outcome.error,
            },
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
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
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

    scoped_key = _scoped_session_key(workspace, request.session_key)
    output_dir = _resolve_output_dir(workspace, request)
    job = SharePointSyncJob(
        id=str(uuid.uuid4()),
        workspace_id=workspace.id,
        session_key=request.session_key,
        auth_mode=request.auth_mode,
        state="running",
        status=None,
        progress="queued",
        output_dir=str(output_dir),
        folder_server_relative_url=request.folder_server_relative_url,
        collection_name=request.collection_name,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    actor = user.username or user.email or "unknown"
    emit_audit_event(
        workspace_id=workspace.id,
        actor=actor,
        event_type="sharepoint.sync.enqueued",
        details={
            "job_id": job.id,
            "session_key": request.session_key,
            "auth_mode": request.auth_mode,
            "folder": request.folder_server_relative_url,
            "collection_name": request.collection_name,
        },
    )
    background_tasks.add_task(
        _run_sync_job,
        job.id,
        request,
        scoped_key,
        output_dir,
        workspace_id=workspace.id,
        workspace_slug=workspace.slug,
        actor=actor,
    )
    return _job_to_summary(job)


@router.get(
    "/sync/{job_id}",
    response_model=SharePointJobSummary,
    summary="Fetch a sync job status + result.",
)
def get_sharepoint_job(
    job_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
) -> SharePointJobSummary:
    job = (
        db.query(SharePointSyncJob)
        .filter(
            SharePointSyncJob.id == job_id,
            SharePointSyncJob.workspace_id == workspace.id,
        )
        .first()
    )
    if job is None:
        raise HTTPException(status_code=404, detail=f"Unknown job {job_id}")
    return _job_to_summary(job)


@router.get(
    "/sync",
    summary="List recent SharePoint sync jobs for the current workspace.",
)
def list_sharepoint_jobs(
    limit: int = 20,
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
) -> dict:
    rows = (
        db.query(SharePointSyncJob)
        .filter(SharePointSyncJob.workspace_id == workspace.id)
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
    session_key: str,
    body: SessionUploadRequest,
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
) -> None:
    _require_admin_role(db, user, workspace)

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

    scoped_key = _scoped_session_key(workspace, session_key)
    store = SharePointSessionStore(settings.sharepoint_session_dir)
    store.save(scoped_key, session)

    emit_audit_event(
        workspace_id=workspace.id,
        actor=user.username or user.email or "unknown",
        event_type="sharepoint.session.uploaded",
        details={
            "session_key": session_key,
            "tenant_host": session.tenant_host,
            # Never log `storage_state` itself (cookies + tokens) — a
            # boolean is enough for the audit trail.
            "has_storage_state": bool(session.storage_state),
        },
    )


@router.get(
    "/sessions/{session_key}",
    summary="Check whether a SharePoint session is cached server-side.",
)
def get_sharepoint_session_status(
    session_key: str,
    workspace: Workspace = Depends(get_current_workspace),
) -> dict:
    from app.services.connectors.sharepoint_otp import SharePointSessionStore

    scoped_key = _scoped_session_key(workspace, session_key)
    store = SharePointSessionStore(settings.sharepoint_session_dir)
    session = store.load(scoped_key)
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
def delete_sharepoint_session(
    session_key: str,
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
) -> None:
    _require_admin_role(db, user, workspace)
    from app.services.connectors.sharepoint_otp import SharePointSessionStore

    scoped_key = _scoped_session_key(workspace, session_key)
    SharePointSessionStore(settings.sharepoint_session_dir).delete(scoped_key)

    emit_audit_event(
        workspace_id=workspace.id,
        actor=user.username or user.email or "unknown",
        event_type="sharepoint.session.deleted",
        details={"session_key": session_key},
    )
