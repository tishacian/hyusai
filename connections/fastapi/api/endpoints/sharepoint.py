"""FastAPI routes for the SharePoint shared-folder connector.

Four responsibilities:

1. Enqueue a sync job (``POST /sharepoint/sync``). Returns a Celery task id.
2. Poll the task state and result (``GET /sharepoint/sync/{task_id}``).
3. Upload a :class:`SharePointSession` previously captured on the operator's
   laptop (``PUT /sharepoint/sessions/{session_key}``). This is the
   "reconnect SharePoint" path when the worker responds with
   ``login_required``: a headless VM cannot complete OTP + Authenticator,
   so the operator captures locally via the CLI and pushes the serialized
   session here, encrypted at rest with the per-tenant Fernet key.
4. Inspect / delete a stored session (``GET`` / ``DELETE
   /sharepoint/sessions/{session_key}``).

The routes purposefully do NOT attempt to run an interactive Playwright
login server-side: on the ``omnirag-demo`` VM there is no display, and
tunnelling the browser through SSH is a poor UX. Delegating the OTP flow
to the operator's local machine keeps the VM non-interactive.
"""

from __future__ import annotations

from pathlib import Path
from typing import cast
from uuid import UUID

from celery import Task
from celery.result import AsyncResult
from fastapi import APIRouter, HTTPException, status

from connections.celery.app import app as celery_app
from connections.celery.tasks import sharepoint_otp_sync
from connections.payload_models.flow_operations import (
    SharePointSessionStatus,
    SharePointSessionUploadPayload,
    SharePointSyncPayload,
    SharePointSyncResult,
)
from connections.payload_models.flow_operations.base import BaseTaskResponse

router = APIRouter(prefix="/flow_operations/sharepoint", tags=["SharePoint"])

sharepoint_otp_sync = cast(Task, sharepoint_otp_sync)

SESSION_DIR = Path(".sharepoint_sessions")
"""Default directory for persisted sessions. Operators can override via the
``session_dir`` field in the sync payload; session uploads always land here
so the worker finds them without extra configuration."""


@router.post(
    "/sync",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=BaseTaskResponse,
    summary="Enqueue an incremental sync of a SharePoint shared folder.",
)
def enqueue_sharepoint_sync(payload: SharePointSyncPayload) -> dict:
    """Push a sync job onto the Celery ``cpu`` queue.

    The task itself runs non-interactively: if the worker cannot authenticate
    silently (no cached session / expired MSAL refresh token), it finishes
    with ``status="login_required"`` and the UI must invite the user to
    re-capture a session via the CLI and re-upload it through
    ``PUT /sharepoint/sessions/{session_key}``.
    """
    task = sharepoint_otp_sync.apply_async(
        args=(payload.model_dump(mode="json"),), queue="cpu"
    )
    return {"task_id": task.id}


@router.get(
    "/sync/{task_id}",
    summary="Fetch the result of a previously enqueued sync.",
)
def get_sharepoint_sync_result(task_id: UUID) -> dict:
    """Return the Celery task state and, when ready, the structured
    :class:`SharePointSyncResult`.
    """
    result = AsyncResult(str(task_id), app=celery_app)
    response: dict[str, object] = {
        "task_id": str(task_id),
        "state": result.state,
        "ready": result.ready(),
    }
    if result.ready():
        if result.successful():
            payload = result.result or {}
            if isinstance(payload, dict):
                response["result"] = SharePointSyncResult.model_validate(
                    payload
                ).model_dump(mode="json")
            else:
                response["result"] = payload
        else:
            response["error"] = str(result.result)
    return response


@router.put(
    "/sessions/{session_key}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Upload a SharePoint session captured locally via the CLI.",
)
def upload_sharepoint_session(
    session_key: str, payload: SharePointSessionUploadPayload
) -> None:
    """Persist an encrypted :class:`SharePointSession` under ``session_key``.

    The operator captures the session locally (``scripts/sharepoint_connector_demo.py
    --sharing-url ... --output ... --force-reauth``), reads the resulting
    ``.sharepoint_sessions/<key>.json``, decrypts it with their local master
    key if needed, and POSTs the ``session_dict`` here. The server re-encrypts
    it under its own master key (scoped to the captured ``tenant_host``)
    before writing to disk.
    """
    from backend.app.services.connectors.sharepoint_otp import (
        SharePointSession,
        SharePointSessionStore,
    )

    try:
        session = SharePointSession.from_dict(payload.session_dict)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid session payload: {exc}",
        ) from exc

    if not session.storage_state:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "session_dict.storage_state is empty; recapture via the CLI "
                "and make sure the OTP + Authenticator flow completed."
            ),
        )

    store = SharePointSessionStore(SESSION_DIR)
    store.save(session_key, session)


@router.get(
    "/sessions/{session_key}",
    response_model=SharePointSessionStatus,
    summary="Check whether a SharePoint session is cached server-side.",
)
def get_sharepoint_session_status(session_key: str) -> SharePointSessionStatus:
    """Return metadata about the cached session without exposing cookies."""
    from backend.app.services.connectors.sharepoint_otp import (
        SharePointSessionStore,
    )

    store = SharePointSessionStore(SESSION_DIR)
    session = store.load(session_key)
    if session is None:
        return SharePointSessionStatus(session_key=session_key, exists=False)
    return SharePointSessionStatus(
        session_key=session_key,
        tenant_host=session.tenant_host,
        sharing_url=session.sharing_url,
        captured_at=session.captured_at,
        exists=True,
    )


@router.delete(
    "/sessions/{session_key}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Forget a cached SharePoint session.",
)
def delete_sharepoint_session(session_key: str) -> None:
    from backend.app.services.connectors.sharepoint_otp import (
        SharePointSessionStore,
    )

    SharePointSessionStore(SESSION_DIR).delete(session_key)
