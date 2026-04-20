"""SharePoint connector for B2B guest users.

Two authentication back-ends are supported:

- **Session-based** (Playwright + sharing-link OTP): works even when the
  tenant blocks Microsoft Graph and prevents delegated consent on custom
  apps. Robust but requires a real browser and periodic re-authentication.
- **OAuth delegated** (MSAL, ``papAI - SharePoint Reader`` Entra app):
  preferred path once admin consent or user-consent policy allows it; no
  browser in production, silent refresh, standard auditing.

Both clients expose the same surface so the :class:`SharedFolderIngester`
can swap implementations without code changes, and the ingester itself
supports incremental sync via a per-folder manifest.
"""

from .client import (
    SharePointBrowserClient,
    SharePointCookieClient,
    SharePointFile,
    SharePointFolder,
)
from .client_msal import (
    MsalAppConfig,
    SharePointMsalAuth,
    SharePointMsalClient,
)
from .crypto import (
    EncryptionConfig,
    EncryptionNotConfigured,
    decrypt_blob,
    encrypt_blob,
    generate_master_key,
)
from .errors import (
    SharePointApiError,
    SharePointAuthError,
    SharePointConnectorError,
    SharePointLoginRequired,
    SharePointSessionExpired,
)
from .ingester import (
    IngestionResult,
    SharedFolderIngester,
    derive_session_key,
)
from .manifest import (
    MANIFEST_FILENAME,
    ManifestEntry,
    SyncManifest,
)
from .session import (
    SharePointSession,
    SharePointSessionStore,
    login_via_sharing_link,
)

__all__ = [
    "SharePointApiError",
    "SharePointAuthError",
    "SharePointBrowserClient",
    "SharePointConnectorError",
    "SharePointCookieClient",
    "SharePointFile",
    "SharePointFolder",
    "SharePointLoginRequired",
    "SharePointMsalAuth",
    "SharePointMsalClient",
    "SharePointSession",
    "SharePointSessionExpired",
    "SharePointSessionStore",
    "MsalAppConfig",
    "SharedFolderIngester",
    "IngestionResult",
    "SyncManifest",
    "ManifestEntry",
    "MANIFEST_FILENAME",
    "EncryptionConfig",
    "EncryptionNotConfigured",
    "derive_session_key",
    "encrypt_blob",
    "decrypt_blob",
    "generate_master_key",
    "login_via_sharing_link",
]
