"""SharePoint REST client that issues its HTTP calls from inside a Playwright
browser context.

Background: SharePoint Online flat-out rejects API calls made with a plain
``requests.Session`` primed with cookies captured from Playwright — it
returns ``401 X-MSDAVEXT_Error: 917656`` ("Before opening files in this
location you must first browse to the web site and select the option to
login automatically"). This is caused by SharePoint's IDCRL / front-door
checks that tie cookies to a TLS fingerprint, HTTP/2 characteristics and
JS-set tokens we can't easily replay. The simplest reliable fix is to
keep a real headless browser around and issue all REST calls through its
``context.request`` APIRequestContext, which behaves like a same-origin XHR.

The client exposes the same surface as the previous ``requests``-based
implementation (``list_files``, ``list_subfolders``, ``walk``,
``download_file``). It is a **context manager**: the underlying Chromium
must be closed explicitly to avoid leaking processes.
"""

from __future__ import annotations

import dataclasses
import logging
import re
from pathlib import Path
from typing import Iterator

from backend.app.services.connectors.sharepoint_otp.errors import (
    SharePointApiError,
    SharePointSessionExpired,
)
from backend.app.services.connectors.sharepoint_otp.session import SharePointSession

logger = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True)
class SharePointFile:
    name: str
    server_relative_url: str
    size_bytes: int
    modified_iso: str


@dataclasses.dataclass(frozen=True)
class SharePointFolder:
    name: str
    server_relative_url: str


def _quote_sp_path(path: str) -> str:
    """Escape a server-relative path for use inside single quotes of a
    ``GetFolderByServerRelativeUrl('...')`` URL.
    """
    return path.replace("'", "''")


class SharePointBrowserClient:
    """Playwright-backed SharePoint REST client.

    Usage::

        with SharePointBrowserClient(session) as client:
            for folder, subs, files in client.walk("/sites/foo/Shared Documents/bar"):
                ...
    """

    def __init__(
        self,
        session: SharePointSession,
        *,
        headless: bool = True,
        timeout_ms: int = 30_000,
    ) -> None:
        self.session = session
        self._headless = headless
        self._timeout_ms = timeout_ms
        self._base = f"https://{session.tenant_host}"
        self._pw = None
        self._browser = None
        self._context = None

    def __enter__(self) -> "SharePointBrowserClient":
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self._headless)
        # storage_state can be a dict directly (Playwright >= 1.33).
        self._context = self._browser.new_context(
            storage_state=self.session.storage_state
        )
        # Open a page on the site so the browser has a proper origin/referer
        # for the subsequent API calls — some SP tenants return 403 if the
        # APIRequestContext has never visited the origin.
        page = self._context.new_page()
        try:
            page.goto(
                self._base,
                wait_until="domcontentloaded",
                timeout=self._timeout_ms,
            )
        except Exception as exc:
            logger.debug("Warm-up navigation to %s failed: %s", self._base, exc)
        finally:
            page.close()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            if self._context is not None:
                self._context.close()
            if self._browser is not None:
                self._browser.close()
        finally:
            if self._pw is not None:
                self._pw.stop()

    # ---- core request ---------------------------------------------------

    def _get_json(self, url: str) -> dict:
        assert self._context is not None
        resp = self._context.request.get(
            url,
            headers={"Accept": "application/json;odata=nometadata"},
            timeout=self._timeout_ms,
        )
        if resp.status == 401:
            raise SharePointSessionExpired(
                f"SharePoint returned 401 for {url}. Session likely expired."
            )
        if resp.status != 200:
            raise SharePointApiError(resp.status, url, resp.text())
        return resp.json()

    # ---- public API -----------------------------------------------------

    def get_folder(self, server_relative_url: str) -> SharePointFolder:
        site_url = self._derive_site_url(server_relative_url)
        quoted = _quote_sp_path(server_relative_url)
        url = (
            f"{site_url}/_api/web/GetFolderByServerRelativeUrl('{quoted}')"
            "?$select=Name,ServerRelativeUrl"
        )
        body = self._get_json(url)
        return SharePointFolder(
            name=body["Name"],
            server_relative_url=body["ServerRelativeUrl"],
        )

    def list_files(self, server_relative_url: str) -> list[SharePointFile]:
        site_url = self._derive_site_url(server_relative_url)
        quoted = _quote_sp_path(server_relative_url)
        url = (
            f"{site_url}/_api/web/GetFolderByServerRelativeUrl('{quoted}')/Files"
            "?$select=Name,ServerRelativeUrl,Length,TimeLastModified"
        )
        value = self._get_json(url).get("value", [])
        return [
            SharePointFile(
                name=item["Name"],
                server_relative_url=item["ServerRelativeUrl"],
                size_bytes=int(item.get("Length", 0)),
                modified_iso=item.get("TimeLastModified", ""),
            )
            for item in value
        ]

    def list_subfolders(self, server_relative_url: str) -> list[SharePointFolder]:
        site_url = self._derive_site_url(server_relative_url)
        quoted = _quote_sp_path(server_relative_url)
        url = (
            f"{site_url}/_api/web/GetFolderByServerRelativeUrl('{quoted}')/Folders"
            "?$select=Name,ServerRelativeUrl"
        )
        value = self._get_json(url).get("value", [])
        # Document libraries expose a "Forms" system folder that must be skipped.
        return [
            SharePointFolder(
                name=item["Name"],
                server_relative_url=item["ServerRelativeUrl"],
            )
            for item in value
            if item["Name"] != "Forms"
        ]

    def download_file(
        self,
        server_relative_url: str,
        *,
        destination: str | Path,
    ) -> Path:
        """Download a single file to ``destination`` (atomic rename)."""
        assert self._context is not None
        site_url = self._derive_site_url(server_relative_url)
        quoted = _quote_sp_path(server_relative_url)
        url = f"{site_url}/_api/web/GetFileByServerRelativeUrl('{quoted}')/$value"
        resp = self._context.request.get(url, timeout=self._timeout_ms)
        if resp.status == 401:
            raise SharePointSessionExpired(
                f"SharePoint returned 401 downloading {server_relative_url}"
            )
        if resp.status != 200:
            raise SharePointApiError(resp.status, url, resp.text()[:500])
        dest = Path(destination)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".part")
        tmp.write_bytes(resp.body())
        tmp.replace(dest)
        return dest

    def walk(
        self, server_relative_url: str
    ) -> Iterator[tuple[SharePointFolder, list[SharePointFolder], list[SharePointFile]]]:
        """Depth-first traversal that yields ``(folder, subfolders, files)``."""
        stack = [self.get_folder(server_relative_url)]
        while stack:
            current = stack.pop()
            subfolders = self.list_subfolders(current.server_relative_url)
            files = self.list_files(current.server_relative_url)
            yield current, subfolders, files
            stack.extend(reversed(subfolders))

    # ---- helpers --------------------------------------------------------

    _SITE_RE = re.compile(r"^(/sites/[^/]+|/teams/[^/]+)", re.IGNORECASE)

    def _derive_site_url(self, server_relative_url: str) -> str:
        """Return ``https://<tenant>/sites/<name>`` for the site that owns
        this path. SharePoint REST is scoped per site collection.
        """
        match = self._SITE_RE.match(server_relative_url)
        if match:
            return f"{self._base}{match.group(1)}"
        return self._base


# Backwards-compatible alias so existing imports keep working.
SharePointCookieClient = SharePointBrowserClient
