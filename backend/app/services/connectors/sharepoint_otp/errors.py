"""Exception types raised by the SharePoint OTP connector."""

from __future__ import annotations


class SharePointConnectorError(Exception):
    """Base class for all connector errors."""


class SharePointAuthError(SharePointConnectorError):
    """The interactive login flow failed or timed out."""


class SharePointSessionExpired(SharePointConnectorError):
    """The stored cookies / tokens are no longer accepted by SharePoint.

    Callers should trigger a new interactive login via
    :class:`backend.app.services.connectors.sharepoint_otp.session.SharePointSession`
    or :class:`backend.app.services.connectors.sharepoint_otp.client_msal.SharePointMsalClient`.
    """


class SharePointLoginRequired(SharePointConnectorError):
    """Raised when a silent refresh is not possible and the UI must invite
    the user to complete an interactive OTP + MFA login.

    Distinct from :class:`SharePointSessionExpired` in that it signals a
    terminal condition for the current run: background workers should NOT
    retry the request and should instead surface the condition to the end
    user (e.g. via a "reconnect SharePoint" call-to-action)."""

    def __init__(self, sharing_url: str, detail: str = "") -> None:
        super().__init__(
            f"Interactive SharePoint login required for {sharing_url}: {detail}".rstrip(": ")
        )
        self.sharing_url = sharing_url
        self.detail = detail


class SharePointApiError(SharePointConnectorError):
    """SharePoint returned an unexpected non-success HTTP response."""

    def __init__(self, status: int, url: str, body: str) -> None:
        super().__init__(f"SharePoint API {status} for {url}: {body[:300]}")
        self.status = status
        self.url = url
        self.body = body
