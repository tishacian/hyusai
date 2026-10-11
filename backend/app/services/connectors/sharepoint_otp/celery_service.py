"""Service-layer entry point used by the SharePoint sync Celery task.

Isolates the translation between our transport payload models and the
connector internals, and standardises the three possible outcomes returned
to the core:

- ``completed``: the sync ran and the manifest is up to date.
- ``login_required``: the worker cannot proceed without an interactive
  browser flow; the UI should surface a "reconnect SharePoint" CTA.
- ``failed``: unexpected error; the payload carries the exception message.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .client_msal import (
    MsalAppConfig,
    SharePointMsalAuth,
)
from .errors import (
    SharePointConnectorError,
    SharePointLoginRequired,
)
from .ingester import (
    IngestionResult,
    SharedFolderIngester,
)
from .session import (
    SharePointSessionStore,
)

logger = logging.getLogger(__name__)

ProgressFn = Callable[[str], None]


@dataclass
class SyncOutcome:
    status: str  # "completed" | "login_required" | "failed"
    result: IngestionResult | None = None
    login_required_detail: str | None = None
    error: str | None = None


def run_sync_from_payload(
    payload,  # SharePointSyncPayload — duck-typed to keep this module light
    *,
    progress: ProgressFn | None = None,
) -> SyncOutcome:
    """Execute the ingestion described by ``payload``.

    This function is **safe to call from a Celery worker**: it never opens
    a browser. If interactive authentication is needed, it returns an
    outcome with ``status="login_required"`` instead of raising.
    """
    session_dir = Path(payload.session_dir)
    output_dir = Path(payload.output_dir)

    if progress is not None:
        progress("starting")

    try:
        if payload.auth_mode == "session":
            if not payload.sharing_url:
                raise ValueError("sharing_url is required for auth_mode='session'")
            store = SharePointSessionStore(session_dir)
            ingester = SharedFolderIngester.for_session_client(
                sharing_url=payload.sharing_url,
                folder_server_relative_url=payload.folder_server_relative_url,
                session_store=store,
                session_key=payload.session_key,
                output_dir=output_dir,
                interactive_login_allowed=False,
                prune_local_files=payload.prune_local_files,
            )
        elif payload.auth_mode == "msal":
            if not payload.client_id or not payload.tenant_host:
                raise ValueError(
                    "client_id and tenant_host are required for auth_mode='msal'"
                )
            cfg = MsalAppConfig(
                client_id=payload.client_id,
                tenant_host=payload.tenant_host,
            )
            cache_path = session_dir / f"msal_{payload.session_key}.cache"
            auth = SharePointMsalAuth(
                cfg, cache_path=cache_path, user_hint=payload.user_hint
            )
            try:
                auth.acquire_silent()
            except SharePointLoginRequired as exc:
                return SyncOutcome(
                    status="login_required",
                    login_required_detail=exc.detail,
                )
            ingester = SharedFolderIngester.for_msal_client(
                msal_auth=auth,
                folder_server_relative_url=payload.folder_server_relative_url,
                output_dir=output_dir,
                prune_local_files=payload.prune_local_files,
            )
        else:
            raise ValueError(f"Unknown auth_mode: {payload.auth_mode!r}")

        def _file_progress(file, target) -> None:
            if progress is not None:
                progress(f"downloaded {file.name} ({file.size_bytes} B)")

        result = ingester.run(progress=_file_progress)
        if progress is not None:
            progress(
                f"done: {result.files_downloaded}/{result.files_total} files, "
                f"{result.bytes_total} bytes"
            )
        return SyncOutcome(status="completed", result=result)

    except SharePointLoginRequired as exc:
        logger.info("Login required for session_key=%s: %s", payload.session_key, exc)
        return SyncOutcome(
            status="login_required",
            login_required_detail=exc.detail or str(exc),
        )
    except SharePointConnectorError as exc:
        logger.exception("SharePoint connector failure: %s", exc)
        return SyncOutcome(status="failed", error=str(exc))
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("Unexpected SharePoint sync failure")
        return SyncOutcome(status="failed", error=f"{type(exc).__name__}: {exc}")
