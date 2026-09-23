"""SharePoint REST client authenticated via OAuth 2.0 delegated permissions
(Microsoft Entra ID / MSAL).

Preferred path once the ``papAI - SharePoint Reader`` app has been granted
admin consent (or the guest user has consented) on the Andritz tenant. Until
then, callers should fall back to
:class:`backend.app.services.connectors.sharepoint_otp.client.SharePointBrowserClient`.

Design parity with the session-based client: same ``list_files`` /
``list_subfolders`` / ``walk`` / ``download_file`` surface so the ingester
can swap implementations without changes.

Token handling
--------------
- Interactive login (``acquire_token_interactive``) is only triggered the
  first time for a given ``(tenant_host, user)`` pair, or when MSAL cannot
  silently renew the access token.
- The MSAL token cache is persisted on disk, encrypted with the same
  per-tenant Fernet machinery as the session-cookie store (see
  :mod:`.crypto`).
- When silent acquisition fails and we cannot interactively prompt (e.g.
  running inside a Celery worker), :class:`SharePointLoginRequired` is raised
  so the UI can re-open the interactive flow in the user's browser.
"""

from __future__ import annotations

import dataclasses
import logging
import re
from pathlib import Path
from typing import Iterator

import requests

from .client import (
    SharePointFile,
    SharePointFolder,
    _quote_sp_path,
)
from .crypto import (
    decrypt_blob,
    encrypt_blob,
)
from .errors import (
    SharePointApiError,
    SharePointLoginRequired,
    SharePointSessionExpired,
)

logger = logging.getLogger(__name__)

DEFAULT_AUTHORITY_COMMON = "https://login.microsoftonline.com/common"
"""Authority used for first-time interactive sign-in. The access token is
then issued by the *resource* tenant, which is what SharePoint expects."""


@dataclasses.dataclass(frozen=True)
class MsalAppConfig:
    client_id: str
    tenant_host: str
    """E.g. ``contoso.sharepoint.com``. Used to scope the access token."""
    authority: str = DEFAULT_AUTHORITY_COMMON

    @property
    def sharepoint_scopes(self) -> list[str]:
        # SharePoint REST expects a resource-scoped token; MSAL translates
        # ``<resource>/<perm>`` shapes into the right v2.0 scope automatically.
        return [f"https://{self.tenant_host}/AllSites.Read"]


class _EncryptedTokenCacheFile:
    """Bridges MSAL's :class:`SerializableTokenCache` with our on-disk Fernet
    envelopes. Reads are lazy; writes happen whenever the cache mutates.
    """

    def __init__(self, path: Path, tenant: str) -> None:
        self.path = path
        self.tenant = tenant

    def load_into(self, cache) -> None:
        if not self.path.exists():
            return
        try:
            blob = self.path.read_bytes()
            plaintext = decrypt_blob(blob, tenant=self.tenant).decode("utf-8")
            cache.deserialize(plaintext)
        except Exception as exc:  # pragma: no cover - corrupted cache
            logger.warning("Discarding unreadable MSAL cache %s: %s", self.path, exc)

    def persist(self, cache) -> None:
        if not cache.has_state_changed:
            return
        payload = cache.serialize().encode("utf-8")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_bytes(encrypt_blob(payload, tenant=self.tenant))


class SharePointMsalAuth:
    """Own the MSAL ``PublicClientApplication`` for a given tenant/user, and
    vend access tokens on demand. Token acquisition is split into ``silent``
    (safe for background workers) and ``interactive`` (requires a browser).
    """

    def __init__(
        self,
        app_config: MsalAppConfig,
        *,
        cache_path: Path,
        user_hint: str | None = None,
    ) -> None:
        from msal import PublicClientApplication, SerializableTokenCache

        self.app_config = app_config
        self.user_hint = user_hint
        self._cache = SerializableTokenCache()
        self._cache_file = _EncryptedTokenCacheFile(
            path=cache_path, tenant=app_config.tenant_host
        )
        self._cache_file.load_into(self._cache)
        self._app = PublicClientApplication(
            client_id=app_config.client_id,
            authority=app_config.authority,
            token_cache=self._cache,
        )

    def _persist(self) -> None:
        self._cache_file.persist(self._cache)

    def acquire_silent(self) -> str:
        """Return a valid access token without user interaction.

        Raises :class:`SharePointLoginRequired` if there is no usable cached
        refresh token for the target user.
        """
        scopes = self.app_config.sharepoint_scopes
        accounts = self._app.get_accounts(username=self.user_hint)
        if not accounts:
            raise SharePointLoginRequired(
                sharing_url=f"https://{self.app_config.tenant_host}",
                detail="No MSAL account cached; interactive sign-in required.",
            )
        result = self._app.acquire_token_silent(scopes, account=accounts[0])
        self._persist()
        if not result or "access_token" not in result:
            raise SharePointLoginRequired(
                sharing_url=f"https://{self.app_config.tenant_host}",
                detail=(result or {}).get(
                    "error_description", "Silent token acquisition failed."
                ),
            )
        return result["access_token"]

    def acquire_interactive(
        self,
        *,
        port: int = 8400,
        prompt: str = "select_account",
    ) -> str:
        """Open the system browser and complete OTP + MFA.

        Intended for CLI / first-time onboarding. Do NOT call from a Celery
        worker: it blocks until the user completes the flow.
        """
        scopes = self.app_config.sharepoint_scopes
        result = self._app.acquire_token_interactive(
            scopes=scopes,
            login_hint=self.user_hint,
            prompt=prompt,
            port=port,
        )
        self._persist()
        if not result or "access_token" not in result:
            raise SharePointLoginRequired(
                sharing_url=f"https://{self.app_config.tenant_host}",
                detail=(result or {}).get(
                    "error_description", "Interactive sign-in failed."
                ),
            )
        return result["access_token"]


class SharePointMsalClient:
    """SharePoint REST client using a delegated OAuth access token.

    Usage::

        auth = SharePointMsalAuth(cfg, cache_path=..., user_hint=upn)
        with SharePointMsalClient(auth) as client:
            for folder, subs, files in client.walk("/sites/foo/Shared Documents/bar"):
                ...
    """

    def __init__(
        self,
        auth: SharePointMsalAuth,
        *,
        timeout: float = 30.0,
    ) -> None:
        self.auth = auth
        self.timeout = timeout
        self._base = f"https://{auth.app_config.tenant_host}"
        self._http = requests.Session()
        self._http.headers.update(
            {"Accept": "application/json;odata=nometadata"}
        )
        self._access_token: str | None = None

    def __enter__(self) -> "SharePointMsalClient":
        self._access_token = self.auth.acquire_silent()
        self._http.headers["Authorization"] = f"Bearer {self._access_token}"
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self._http.close()

    # ---- core request ---------------------------------------------------

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        resp = self._http.request(
            method=method,
            url=url,
            timeout=self.timeout,
            allow_redirects=False,
            **kwargs,
        )
        if resp.status_code == 401:
            # Token likely expired mid-run. Try a single silent refresh.
            logger.info("Got 401 on %s; attempting silent token refresh.", url)
            try:
                self._access_token = self.auth.acquire_silent()
            except SharePointLoginRequired:
                raise SharePointSessionExpired(
                    f"SharePoint returned 401 for {url} and silent refresh failed."
                )
            self._http.headers["Authorization"] = f"Bearer {self._access_token}"
            resp = self._http.request(
                method=method,
                url=url,
                timeout=self.timeout,
                allow_redirects=False,
                **kwargs,
            )
            if resp.status_code == 401:
                raise SharePointSessionExpired(
                    f"SharePoint returned 401 after refresh for {url}."
                )
        return resp

    def _get_json(self, url: str) -> dict:
        r = self._request("GET", url)
        if r.status_code != 200:
            raise SharePointApiError(r.status_code, url, r.text[:500])
        return r.json()

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
            name=body["Name"], server_relative_url=body["ServerRelativeUrl"]
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
        return [
            SharePointFolder(
                name=item["Name"], server_relative_url=item["ServerRelativeUrl"]
            )
            for item in value
            if item["Name"] != "Forms"
        ]

    def download_file(
        self,
        server_relative_url: str,
        *,
        destination: str | Path,
        chunk_size: int = 1 << 16,
    ) -> Path:
        site_url = self._derive_site_url(server_relative_url)
        quoted = _quote_sp_path(server_relative_url)
        url = (
            f"{site_url}/_api/web/GetFileByServerRelativeUrl('{quoted}')/$value"
        )
        r = self._request("GET", url, stream=True)
        if r.status_code != 200:
            raise SharePointApiError(r.status_code, url, r.text[:500])
        dest = Path(destination)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".part")
        try:
            with tmp.open("wb") as fh:
                for chunk in r.iter_content(chunk_size=chunk_size):
                    if chunk:
                        fh.write(chunk)
            tmp.replace(dest)
        finally:
            r.close()
            if tmp.exists():
                tmp.unlink(missing_ok=True)
        return dest

    def walk(
        self, server_relative_url: str
    ) -> Iterator[tuple[SharePointFolder, list[SharePointFolder], list[SharePointFile]]]:
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
        match = self._SITE_RE.match(server_relative_url)
        if match:
            return f"{self._base}{match.group(1)}"
        return self._base
