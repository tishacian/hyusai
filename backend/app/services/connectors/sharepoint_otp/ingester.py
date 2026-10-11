"""High-level ingestion helper: walks a shared folder and downloads its files.

Designed to be called from both a CLI demo and a Celery worker. The
implementation writes files to a local directory preserving the folder
hierarchy; callers can then feed them to the RAG pipeline without further
SharePoint-specific knowledge.

Two client implementations are supported transparently:

- :class:`~.client.SharePointBrowserClient` — cookie session captured by
  Playwright after an OTP + MFA login.
- :class:`~.client_msal.SharePointMsalClient` — OAuth delegated token via
  MSAL (preferred once admin consent is granted).

Incremental sync: a small JSON manifest in ``<output_dir>`` records each
file's ``TimeLastModified`` and size. On subsequent runs, unchanged files
are skipped; stale manifest entries (files deleted on SharePoint) are
pruned, with their local copies optionally removed.
"""

from __future__ import annotations

import logging
import re
import urllib.parse
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, ContextManager, Iterator, Protocol
from urllib.parse import urlparse

from .client import (
    SharePointBrowserClient,
    SharePointFile,
    SharePointFolder,
)
from .errors import (
    SharePointLoginRequired,
    SharePointSessionExpired,
)
from .manifest import SyncManifest
from .session import (
    SharePointSession,
    SharePointSessionStore,
    login_via_sharing_link,
)

logger = logging.getLogger(__name__)


@dataclass
class IngestionResult:
    files_total: int
    """Total number of files seen in the remote folder (including skipped)."""
    files_downloaded: int
    """Number of files actually transferred during this run."""
    bytes_total: int
    """Total bytes transferred during this run (excludes skipped files)."""
    downloaded_paths: list[Path] = field(default_factory=list)
    skipped_paths: list[Path] = field(default_factory=list)
    pruned_paths: list[Path] = field(default_factory=list)


class _WalkClient(Protocol):
    """Minimal surface the ingester needs from any SharePoint client."""

    def walk(
        self, server_relative_url: str
    ) -> Iterator[tuple[SharePointFolder, list[SharePointFolder], list[SharePointFile]]]: ...

    def download_file(
        self, server_relative_url: str, *, destination: str | Path
    ) -> Path: ...


ClientFactory = Callable[[], ContextManager[_WalkClient]]
"""Callable that builds a fresh, already-authenticated SharePoint client
wrapped in a context manager. Used by the ingester to support both the
Playwright-based client and the MSAL client without any branching logic."""


class SharedFolderIngester:
    """Orchestrate end-to-end ingestion of a SharePoint shared folder.

    Two ways to construct it:

    - :meth:`for_session_client` (default, OTP fallback) — captures cookies
      via Playwright on first use.
    - :meth:`for_msal_client` — uses an MSAL-backed OAuth token.

    Or pass any ``client_factory`` directly for testing.
    """

    def __init__(
        self,
        folder_server_relative_url: str,
        *,
        client_factory: ClientFactory,
        output_dir: Path,
        interactive_recovery: Callable[[], ClientFactory] | None = None,
        prune_local_files: bool = False,
    ) -> None:
        self.folder_server_relative_url = folder_server_relative_url
        self._client_factory = client_factory
        self._interactive_recovery = interactive_recovery
        self.output_dir = output_dir
        self.prune_local_files = prune_local_files

    # ---- factory helpers ------------------------------------------------

    @classmethod
    def for_session_client(
        cls,
        *,
        sharing_url: str,
        folder_server_relative_url: str,
        session_store: SharePointSessionStore,
        session_key: str,
        output_dir: Path,
        interactive_login_allowed: bool = True,
        prune_local_files: bool = False,
    ) -> "SharedFolderIngester":
        """Build an ingester that authenticates via a captured OTP session.

        ``interactive_login_allowed=False`` makes the ingester usable from a
        Celery worker: it will raise :class:`SharePointLoginRequired`
        instead of opening a browser window.
        """
        verify_url = _build_verify_url(sharing_url, folder_server_relative_url)

        def make_session(*, force_reauth: bool) -> SharePointSession:
            if not force_reauth:
                stored = session_store.load(session_key)
                if stored is not None:
                    logger.info(
                        "Re-using stored SharePoint session %s", session_key
                    )
                    return stored
            if not interactive_login_allowed:
                raise SharePointLoginRequired(
                    sharing_url=sharing_url,
                    detail="No valid session cached and interactive login is disabled.",
                )
            logger.info("Starting interactive login for %s", sharing_url)
            session = login_via_sharing_link(sharing_url, verify_url=verify_url)
            session_store.save(session_key, session)
            logger.info("Session captured and stored under key %s", session_key)
            return session

        @contextmanager
        def factory() -> Iterator[_WalkClient]:
            session = make_session(force_reauth=False)
            with SharePointBrowserClient(session) as client:
                yield client

        def recovery() -> ClientFactory:
            if not interactive_login_allowed:
                raise SharePointLoginRequired(
                    sharing_url=sharing_url,
                    detail="Session expired mid-run; cannot re-auth silently.",
                )

            @contextmanager
            def retry_factory() -> Iterator[_WalkClient]:
                session = make_session(force_reauth=True)
                with SharePointBrowserClient(session) as client:
                    yield client

            return retry_factory

        return cls(
            folder_server_relative_url=folder_server_relative_url,
            client_factory=factory,
            output_dir=output_dir,
            interactive_recovery=recovery,
            prune_local_files=prune_local_files,
        )

    @classmethod
    def for_msal_client(
        cls,
        *,
        msal_auth,  # type: ignore[no-untyped-def]
        folder_server_relative_url: str,
        output_dir: Path,
        prune_local_files: bool = False,
    ) -> "SharedFolderIngester":
        """Build an ingester backed by an MSAL delegated token.

        ``msal_auth`` is a :class:`.client_msal.SharePointMsalAuth` already
        primed with a token cache; callers decide ahead of time whether a
        missing account should trigger an interactive prompt.
        """
        from .client_msal import (
            SharePointMsalClient,
        )

        @contextmanager
        def factory() -> Iterator[_WalkClient]:
            with SharePointMsalClient(msal_auth) as client:
                yield client

        return cls(
            folder_server_relative_url=folder_server_relative_url,
            client_factory=factory,
            output_dir=output_dir,
            prune_local_files=prune_local_files,
        )

    # ---- main entry point ----------------------------------------------

    def run(
        self,
        *,
        progress: Callable[[SharePointFile, Path], None] | None = None,
    ) -> IngestionResult:
        try:
            with self._client_factory() as client:
                return self._download_all(client, progress)
        except SharePointSessionExpired:
            if self._interactive_recovery is None:
                raise SharePointLoginRequired(
                    sharing_url="",
                    detail="Session expired and no recovery strategy is configured.",
                )
            logger.warning("Session expired; asking user to re-authenticate")
            retry_factory = self._interactive_recovery()
            with retry_factory() as client:
                return self._download_all(client, progress)

    # ---- internals ------------------------------------------------------

    def _download_all(
        self,
        client: _WalkClient,
        progress: Callable[[SharePointFile, Path], None] | None,
    ) -> IngestionResult:
        root = self.folder_server_relative_url.rstrip("/")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        manifest = SyncManifest.load(self.output_dir)

        downloaded_paths: list[Path] = []
        skipped_paths: list[Path] = []
        seen_remote_urls: list[str] = []
        total_bytes = 0
        total_files = 0

        for folder, _subfolders, files in client.walk(root):
            rel = folder.server_relative_url[len(root):].lstrip("/")
            target_dir = self.output_dir / rel if rel else self.output_dir
            target_dir.mkdir(parents=True, exist_ok=True)

            for f in files:
                total_files += 1
                seen_remote_urls.append(f.server_relative_url)
                target_file = target_dir / f.name
                if not manifest.should_download(f) and target_file.exists():
                    skipped_paths.append(target_file)
                    continue
                client.download_file(f.server_relative_url, destination=target_file)
                manifest.record(f, target_file)
                total_bytes += f.size_bytes
                downloaded_paths.append(target_file)
                if progress is not None:
                    progress(f, target_file)

        pruned_entries = manifest.prune(seen_remote_urls)
        pruned_paths: list[Path] = []
        for entry in pruned_entries:
            local = Path(entry.local_path)
            if self.prune_local_files and local.exists():
                try:
                    local.unlink()
                    pruned_paths.append(local)
                except OSError as exc:  # pragma: no cover - best effort
                    logger.warning("Could not delete stale file %s: %s", local, exc)
            else:
                pruned_paths.append(local)

        manifest.save(self.output_dir)

        return IngestionResult(
            files_total=total_files,
            files_downloaded=len(downloaded_paths),
            bytes_total=total_bytes,
            downloaded_paths=downloaded_paths,
            skipped_paths=skipped_paths,
            pruned_paths=pruned_paths,
        )


def _build_verify_url(sharing_url: str, folder_server_relative_url: str) -> str:
    tenant_host = urlparse(sharing_url).hostname or ""
    match = re.match(
        r"^(/sites/[^/]+|/teams/[^/]+)",
        folder_server_relative_url,
        re.IGNORECASE,
    )
    site_prefix = match.group(1) if match else ""
    quoted = folder_server_relative_url.replace("'", "''")
    return (
        f"https://{tenant_host}{site_prefix}/_api/web/"
        f"GetFolderByServerRelativeUrl('{urllib.parse.quote(quoted)}')"
        "?$select=Name,ServerRelativeUrl"
    )


def derive_session_key(sharing_url: str) -> str:
    """Build a filesystem-safe key from the sharing URL."""
    parsed = urlparse(sharing_url)
    return f"{parsed.netloc}_{parsed.path.strip('/').replace('/', '_')}"
