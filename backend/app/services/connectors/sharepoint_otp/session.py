"""Interactive SharePoint sign-in using Playwright, with storage-state persistence.

For OTP-only B2B guests (accounts that cannot authenticate through the standard
``login.microsoftonline.com`` password page), the only way to establish a
SharePoint session is to replay the full sharing-link flow: open the sharing
URL, let the user type the emailed one-time code and complete Authenticator
MFA, then let the browser land on the shared folder.

SharePoint Online's REST endpoints refuse to serve requests whose cookies
have been "replayed" from a non-browser HTTP client (they return
``401 X-MSDAVEXT_Error: 917656``), even when all auth cookies are present and
browser headers (``Origin``, ``Referer``, ``Sec-Fetch-*``...) are spoofed. The
only robust way to keep calling the API after the interactive login is to
drive a real Chromium via Playwright and issue requests from inside the
browser context. This module captures and persists that browser context's
``storage_state`` (cookies + localStorage + indexedDB snapshots) so subsequent
sync runs can reopen a headless Chromium with the same state and issue
authenticated API calls without asking the user to go through OTP again.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from backend.app.services.connectors.sharepoint_otp.crypto import (
    decrypt_blob,
    encrypt_blob,
)
from backend.app.services.connectors.sharepoint_otp.errors import SharePointAuthError

logger = logging.getLogger(__name__)

DEFAULT_LOGIN_TIMEOUT_S = 300
"""Time in seconds the user has to complete OTP + MFA."""

REQUIRED_COOKIE_NAMES = {"FedAuth"}
"""Minimum cookie set that signals the sign-in is complete enough to capture."""


@dataclass
class SharePointSession:
    tenant_host: str
    sharing_url: str
    storage_state: dict[str, Any] = field(default_factory=dict)
    """Playwright ``context.storage_state()`` payload (cookies + origins)."""
    captured_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tenant_host": self.tenant_host,
            "sharing_url": self.sharing_url,
            "captured_at": self.captured_at,
            "storage_state": self.storage_state,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SharePointSession":
        return cls(
            tenant_host=payload["tenant_host"],
            sharing_url=payload["sharing_url"],
            captured_at=payload.get("captured_at", time.time()),
            storage_state=payload.get("storage_state", {}),
        )


class SharePointSessionStore:
    """Persist :class:`SharePointSession` instances on disk, encrypted per
    tenant via :mod:`backend.app.services.connectors.sharepoint_otp.crypto`.

    Keys are caller-chosen identifiers (typically a workspace/connector ID).
    The underlying encryption key is a single process-wide Fernet master; the
    per-tenant sub-key is derived via HKDF so a compromise of one tenant's
    blob does not yield plaintext for others.
    """

    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        safe = key.replace("/", "_").replace(":", "_")
        return self.directory / f"{safe}.json"

    def load(self, key: str) -> SharePointSession | None:
        path = self._path(key)
        if not path.exists():
            return None
        try:
            raw = path.read_bytes()
            # Peek the tenant from the envelope so we can key decryption.
            # If the file is legacy unwrapped JSON, fall back gracefully.
            tenant: str | None = None
            try:
                envelope = json.loads(raw.decode("utf-8"))
                if isinstance(envelope, dict):
                    tenant = envelope.get("tenant") or envelope.get(
                        "session", {}
                    ).get("tenant_host")
            except Exception:
                pass
            if tenant is None:
                # Last-resort: try loading as plaintext legacy file.
                return SharePointSession.from_dict(json.loads(raw))
            plaintext = decrypt_blob(raw, tenant=tenant)
            return SharePointSession.from_dict(json.loads(plaintext))
        except Exception as exc:  # pragma: no cover - corrupted file
            logger.warning("Ignoring unreadable session %s: %s", path, exc)
            return None

    def save(self, key: str, session: SharePointSession) -> None:
        path = self._path(key)
        payload = json.dumps(session.to_dict()).encode("utf-8")
        blob = encrypt_blob(payload, tenant=session.tenant_host)
        path.write_bytes(blob)

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)


def _tenant_host_from_sharing_url(sharing_url: str) -> str:
    host = urlparse(sharing_url).hostname
    if not host or not host.endswith(".sharepoint.com"):
        raise ValueError(
            f"Expected an https://<tenant>.sharepoint.com/... URL, got {sharing_url!r}"
        )
    return host


def login_via_sharing_link(
    sharing_url: str,
    *,
    headless: bool = False,
    timeout_s: int = DEFAULT_LOGIN_TIMEOUT_S,
    verify_url: str | None = None,
) -> SharePointSession:
    """Open a Playwright browser, let the human complete the OTP + MFA flow,
    and return the browser context's ``storage_state`` once the target
    ``verify_url`` responds with HTTP 200.

    Raises :class:`SharePointAuthError` if the login isn't completed within
    ``timeout_s``.
    """

    from playwright.sync_api import sync_playwright

    tenant_host = _tenant_host_from_sharing_url(sharing_url)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        context = browser.new_context()
        page = context.new_page()
        logger.info("Opening sharing URL; complete OTP + Authenticator in the window")
        page.goto(sharing_url, wait_until="domcontentloaded")

        deadline = time.time() + timeout_s
        captured_state: dict[str, Any] | None = None
        last_logged_names: set[str] = set()
        while time.time() < deadline:
            cookies = context.cookies()
            tenant_cookies = [c for c in cookies if c["domain"].endswith(tenant_host)]
            names = {c["name"] for c in tenant_cookies}
            if names != last_logged_names:
                logger.debug("Cookies on %s so far: %s", tenant_host, sorted(names))
                last_logged_names = names
            if not REQUIRED_COOKIE_NAMES.issubset(names):
                time.sleep(1.5)
                continue
            if verify_url is not None:
                try:
                    probe = page.request.get(
                        verify_url,
                        headers={"Accept": "application/json;odata=nometadata"},
                    )
                    logger.debug("Probe %s -> %s", verify_url, probe.status)
                    if probe.status != 200:
                        time.sleep(1.5)
                        continue
                except Exception as exc:  # pragma: no cover - best effort
                    logger.debug("Probe failed: %s", exc)
                    time.sleep(1.5)
                    continue
            time.sleep(1)
            captured_state = context.storage_state()
            logger.info(
                "Captured browser storage state (%d cookies, %d origins)",
                len(captured_state.get("cookies", [])),
                len(captured_state.get("origins", [])),
            )
            break

        context.close()
        browser.close()

    if captured_state is None:
        raise SharePointAuthError(
            f"Did not capture a usable SharePoint session for {tenant_host} "
            f"within {timeout_s}s. Make sure you completed the OTP + "
            "Authenticator flow and landed on the shared folder."
        )

    return SharePointSession(
        tenant_host=tenant_host,
        sharing_url=sharing_url,
        storage_state=captured_state,
    )
