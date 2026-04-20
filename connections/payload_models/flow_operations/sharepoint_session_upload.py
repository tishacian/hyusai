"""Payloads for the SharePoint session upload route.

The upload route is the server-side counterpart of the CLI's interactive
login: the operator runs ``scripts/sharepoint_connector_demo.py`` locally
(where a real browser is available), then POSTs the resulting JSON dump
(``session_dict``) to the server so it can drive Celery syncs.

This avoids the need to run a headful Chromium on the VM, which would be
impractical over SSH.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SharePointSessionUploadPayload(BaseModel):
    """Serialized :class:`SharePointSession` payload to persist server-side.

    The ``session_dict`` is exactly the JSON produced by ``session.to_dict()``
    on the client side.
    """

    session_dict: dict[str, Any] = Field(
        ...,
        description=(
            "JSON dump of SharePointSession.to_dict() captured locally via the CLI."
        ),
    )


class SharePointSessionStatus(BaseModel):
    session_key: str
    tenant_host: str | None = None
    sharing_url: str | None = None
    captured_at: float | None = None
    exists: bool
