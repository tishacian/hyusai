"""Workspace-scoped server-side proxy for whitelisted port webcam snapshots.

The cockpit map vignette next to the AIS marker calls
``GET /api/v1/mission-room/webcams/proxy?source_id=apm-apapa-gate-1``. The
backend resolves the ``source_id`` against
:mod:`app.services.webcam_proxy.WHITELIST`, fetches the upstream JPG/PNG
(cached 30-300 s) and serves it as a regular image response. If the upstream
fails, we serve the static fallback embedded in
``backend/app/resources/webcams/``.

This indirection exists because the upstream pages (APM Terminals Apapa
gate-cameras, Port autonome d'Abidjan phototheque) ship a
``Content-Security-Policy: frame-ancestors 'self'`` (APM) or transcode the
JPG behind Drupal style derivatives (PAA) — both prevent the browser from
embedding the asset directly. The proxy keeps the demo-safe rendering
guarantee and centralises the audit log.

Security:

* **Whitelist only**. Unknown ``source_id`` → ``404``. There is no open
  proxy surface.
* **Audit log** at every call (``webcam.proxy.served`` /
  ``webcam.proxy.fallback`` / ``webcam.proxy.error``).
* **No personal data** in/out — the assets are pure JPG/PNG of port
  infrastructure (no human identification).
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session as DBSession

from app.core.auth import get_current_user, get_current_workspace
from app.db.base import get_db
from app.extensions.registry import (
    MISSION_ROOM_EXTENSION_ID,
    require_workspace_extension,
)
from app.models.user import User
from app.models.workspace import Workspace
from app.services.audit_logger import emit_audit_event
from app.services.webcam_proxy import (
    fetch_snapshot as fetch_webcam_snapshot,
    get_spec as get_webcam_spec,
    list_whitelisted_source_ids,
)


router = APIRouter(
    dependencies=[Depends(require_workspace_extension(MISSION_ROOM_EXTENSION_ID))]
)


def _actor(user: Optional[User]) -> str:
    if not user:
        return "system"
    return user.email or user.username or user.id


def _audit(
    *,
    db: DBSession,
    workspace: Workspace,
    user: Optional[User],
    event_type: str,
    details: dict,
) -> None:
    emit_audit_event(
        db=db,
        workspace_id=workspace.id,
        event_type=event_type,
        actor=_actor(user),
        details=details,
    )


def _resolve_snapshot(
    *,
    source_id: str,
    force_refresh: bool,
    workspace: Workspace,
    user: Optional[User],
    db: DBSession,
    method: str,
) -> tuple[bytes, str, dict[str, str]]:
    """Validate ``source_id``, audit and fetch the snapshot bytes + headers.

    Shared by ``GET /proxy`` (returns the bytes) and ``HEAD /proxy``
    (returns just the headers — used by the cockpit for vignette
    pre-flights / link probing).
    """
    if get_webcam_spec(source_id) is None:
        _audit(
            db=db,
            workspace=workspace,
            user=user,
            event_type="webcam.proxy.error",
            details={"source_id": source_id, "reason": "not_whitelisted", "method": method},
        )
        raise HTTPException(status_code=404, detail="webcam_source_not_whitelisted")

    try:
        result = fetch_webcam_snapshot(source_id, force_refresh=force_refresh)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="webcam_source_not_whitelisted") from exc

    spec = result.spec
    event_type = "webcam.proxy.served" if result.source == "upstream" else "webcam.proxy.fallback"
    _audit(
        db=db,
        workspace=workspace,
        user=user,
        event_type=event_type,
        details={
            "source_id": source_id,
            "cache": result.cache,
            "source": result.source,
            "upstream_status": result.upstream_status,
            "mime": result.mime_type,
            "bytes": len(result.content),
            "method": method,
        },
    )

    headers = {
        # Browser-side cache aligns with the TTL we use server-side so the
        # vignette refreshes in lock-step with the upstream snapshot.
        "Cache-Control": f"private, max-age={max(5, spec.ttl_seconds)}",
        "X-Webcam-Source-Id": source_id,
        "X-Webcam-Source": result.source,
        "X-Webcam-Cache": result.cache,
        "X-Webcam-Attribution": spec.attribution,
        "X-Webcam-Disclaimer": spec.label_disclaimer,
        "Content-Disposition": f'inline; filename="{source_id}.{_ext_for(result.mime_type)}"',
    }
    if result.upstream_status is not None:
        headers["X-Webcam-Upstream-Status"] = str(result.upstream_status)
    return result.content, result.mime_type, headers


@router.get("/proxy")
def webcam_proxy(
    source_id: str = Query(..., min_length=1, max_length=80, description="Whitelisted webcam id"),
    force_refresh: bool = Query(default=False, description="Bypass the proxy cache (debug)"),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> Response:
    """Return a JPG/PNG snapshot for a whitelisted port webcam source."""
    content, mime_type, headers = _resolve_snapshot(
        source_id=source_id,
        force_refresh=force_refresh,
        workspace=workspace,
        user=user,
        db=db,
        method="GET",
    )
    return Response(content=content, media_type=mime_type, headers=headers)


@router.head("/proxy")
def webcam_proxy_head(
    source_id: str = Query(..., min_length=1, max_length=80, description="Whitelisted webcam id"),
    force_refresh: bool = Query(default=False, description="Bypass the proxy cache (debug)"),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> Response:
    """HEAD twin of :func:`webcam_proxy` — returns headers, no body.

    The cockpit map vignette pre-flights the snapshot URL with a HEAD call
    before swapping the ``<img>`` ``src`` so that broken sources fall back
    silently instead of triggering a layout flash. Without this handler the
    pre-flight would return ``404`` for whitelisted sources and the
    vignette would never render.
    """
    content, mime_type, headers = _resolve_snapshot(
        source_id=source_id,
        force_refresh=force_refresh,
        workspace=workspace,
        user=user,
        db=db,
        method="HEAD",
    )
    # Preserve the canonical Content-Length the client would see on GET, but
    # ship an empty body — per RFC 9110 §9.3.2 the response to HEAD has the
    # same metadata as GET, just without the message body.
    headers["Content-Length"] = str(len(content))
    return Response(content=b"", media_type=mime_type, headers=headers)


@router.get("/sources")
def list_sources(
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Lightweight inventory of the whitelisted webcam sources for the UI."""
    items = []
    for source_id in list_whitelisted_source_ids():
        spec = get_webcam_spec(source_id)
        if spec is None:  # safety
            continue
        items.append(
            {
                "source_id": spec.source_id,
                "label": spec.label,
                "attribution": spec.attribution,
                "label_disclaimer": spec.label_disclaimer,
                "ttl_seconds": spec.ttl_seconds,
                "proxy_url": f"/api/v1/mission-room/webcams/proxy?source_id={spec.source_id}",
                "upstream_host": _host_of(spec.upstream_url),
            }
        )
    _audit(
        db=db,
        workspace=workspace,
        user=user,
        event_type="webcam.proxy.listed",
        details={"count": len(items)},
    )
    return {
        "workspace": {"id": workspace.id, "slug": workspace.slug},
        "policy": "advisory_only",
        "sources": items,
    }


def _ext_for(mime_type: str) -> str:
    if "png" in mime_type:
        return "png"
    if "webp" in mime_type:
        return "webp"
    if "gif" in mime_type:
        return "gif"
    return "jpg"


def _host_of(url: str) -> str:
    try:
        from urllib.parse import urlparse

        return urlparse(url).hostname or ""
    except Exception:  # noqa: BLE001
        return ""
