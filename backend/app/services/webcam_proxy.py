"""Server-side proxy for public port webcam snapshots.

Some public sources (APM Terminals Apapa gate-cameras, Port autonome
d'Abidjan phototheque) ship a public JPG/PNG endpoint but block iframe
embedding via ``Content-Security-Policy: frame-ancestors 'self'`` or
``X-Frame-Options: DENY``. This module is the demo-safe shim that lets the
cockpit display a live vignette next to the AIS marker without scraping the
upstream page from the browser.

Design
------

* **Whitelist** ``source_id`` → upstream URL + static fallback. There is no
  open-redirect / open-proxy surface: an unknown id returns ``404``.
* **Cache** the upstream bytes in a process-local dict for ``ttl_seconds``
  (default 30 s, configurable per source). On upstream failures we also
  cache a *negative* entry for ``negative_ttl_seconds`` (default 60 s) so
  we don't hammer the source.
* **Static fallback**. Each entry points to a JPG/PNG embedded under
  ``backend/app/resources/webcams/`` so the demo keeps rendering even
  without internet access. The fallback is also served when the upstream
  returns a non-image payload (HTML error page, captcha…).
* **Audit log**. Each proxy hit emits ``webcam.proxy.served`` (or
  ``webcam.proxy.fallback`` / ``webcam.proxy.error``) with workspace,
  actor, source_id, cache hit/miss and upstream HTTP status.
* **Throttle** (best-effort, single-process): the upstream is fetched at
  most once every ``min_fetch_interval_seconds`` per source even if many
  concurrent requests miss the cache.

This module is intentionally lightweight: no Redis, no third-party HTTP
client — ``httpx`` is already a project dependency. It's enough for a demo
cockpit. Move to a proper edge cache before scaling to production.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import httpx


logger = logging.getLogger(__name__)


_WEBCAMS_DIR = Path(__file__).resolve().parents[1] / "resources" / "webcams"


@dataclass(frozen=True)
class WebcamSourceSpec:
    """Static description of a whitelisted webcam snapshot source."""

    source_id: str
    label: str
    upstream_url: str
    fallback_filename: str
    fallback_mime: str
    upstream_mime_hint: str = "image/jpeg"
    ttl_seconds: int = 30
    negative_ttl_seconds: int = 60
    min_fetch_interval_seconds: float = 10.0
    attribution: str = ""
    label_disclaimer: str = ""
    user_agent: str = "Mozilla/5.0 SENTINEL-CI/1.0 (+webcam-proxy)"


# ---------------------------------------------------------------------------
# Whitelist (single source of truth — wired to ``visual_intelligence`` seeds)
# ---------------------------------------------------------------------------

_WHITELIST: dict[str, WebcamSourceSpec] = {
    "apm-apapa-gate-1": WebcamSourceSpec(
        source_id="apm-apapa-gate-1",
        label="APM Terminals · Apapa Gate Camera 1",
        upstream_url=(
            "https://cms-cd.apmterminals.com/apm/api/v1/gatecameras/"
            "gate-camera?id=13b8ab33-4dfd-46ad-8085-a113b86c35e3"
        ),
        fallback_filename="apm-apapa-gate-1.jpg",
        fallback_mime="image/jpeg",
        upstream_mime_hint="image/jpeg",
        ttl_seconds=30,
        attribution="APM Terminals (Apapa) - snapshot public",
        label_disclaimer="Reference visuelle - demo Abidjan",
    ),
    "apm-apapa-gate-2": WebcamSourceSpec(
        source_id="apm-apapa-gate-2",
        label="APM Terminals · Apapa Gate Camera 2",
        upstream_url=(
            "https://cms-cd.apmterminals.com/apm/api/v1/gatecameras/"
            "gate-camera?id=10f6ae28-8c9e-46d3-8d13-18aa8396652f"
        ),
        fallback_filename="apm-apapa-gate-2.jpg",
        fallback_mime="image/jpeg",
        upstream_mime_hint="image/jpeg",
        ttl_seconds=30,
        attribution="APM Terminals (Apapa) - snapshot public",
        label_disclaimer="Reference visuelle - demo Abidjan",
    ),
    "paa-aerial-vue": WebcamSourceSpec(
        source_id="paa-aerial-vue",
        label="Port Autonome d'Abidjan · vue aerienne",
        upstream_url=(
            "https://portabidjan.ci/sites/default/files/styles/paa-home-diapo/"
            "public/phototheque/08042014_prise_de_vue_sans_titre_08042014_08-04-14_"
            "port_autonome_vue_aerienne_iu9a1959.jpg"
        ),
        fallback_filename="paa-aerial-vue.png",
        fallback_mime="image/png",
        upstream_mime_hint="image/png",
        ttl_seconds=300,
        attribution="Port Autonome d'Abidjan - phototheque officielle",
        label_disclaimer="Phototheque officielle PAA - reference visuelle (pas de live)",
    ),
    "paa-terminal-petrolier": WebcamSourceSpec(
        source_id="paa-terminal-petrolier",
        label="Port Autonome d'Abidjan · terminal petrolier",
        upstream_url=(
            "https://portabidjan.ci/sites/default/files/styles/paa-home-diapo/"
            "public/phototheque/port-dabidjan_terminal-petrolier_eleoducs-"
            "au-quai-petroliers_0.jpg"
        ),
        fallback_filename="paa-terminal-petrolier.png",
        fallback_mime="image/png",
        upstream_mime_hint="image/png",
        ttl_seconds=300,
        attribution="Port Autonome d'Abidjan - phototheque officielle",
        label_disclaimer="Phototheque officielle PAA - reference visuelle (pas de live)",
    ),
    "paa-terminal-fruitier": WebcamSourceSpec(
        source_id="paa-terminal-fruitier",
        label="Port Autonome d'Abidjan · terminal fruitier",
        upstream_url=(
            "https://portabidjan.ci/sites/default/files/styles/paa-home-diapo/"
            "public/phototheque/port_dabidjan_terminal_fruitier_chargement_"
            "des_fruits_sur_un_navire.jpg"
        ),
        fallback_filename="paa-terminal-fruitier.png",
        fallback_mime="image/png",
        upstream_mime_hint="image/png",
        ttl_seconds=300,
        attribution="Port Autonome d'Abidjan - phototheque officielle",
        label_disclaimer="Phototheque officielle PAA - reference visuelle (pas de live)",
    ),
}


def list_whitelisted_source_ids() -> list[str]:
    return sorted(_WHITELIST.keys())


def get_spec(source_id: str) -> Optional[WebcamSourceSpec]:
    return _WHITELIST.get(source_id)


# ---------------------------------------------------------------------------
# Vessel / cargo → recommended webcam source_id (auto-select for the cockpit
# vignette next to the AIS marker). Centralised here so the maritime API,
# the chat ``explain_why`` handler and the frontend share the same mapping.
# ---------------------------------------------------------------------------

_VESSEL_WEBCAM_MMSI_MAP: dict[str, str] = {
    # MV Atlantic Trader — S1 narrative anchor.
    "627012345": "apm-apapa-gate-1",
}

_CARGO_WEBCAM_MAP: dict[str, str] = {
    "cargo-abidjan-supply-001": "apm-apapa-gate-1",
}

# Ordered list of fallback source_ids to cycle through in the UI when the
# operator wants a different angle / a different operator. Order matches the
# narrative priority: APM gate cameras (live snapshot) first, then PAA static
# references for context.
RECOMMENDED_WEBCAM_CYCLE: tuple[str, ...] = (
    "apm-apapa-gate-1",
    "apm-apapa-gate-2",
    "paa-aerial-vue",
    "paa-terminal-petrolier",
    "paa-terminal-fruitier",
)


def recommended_webcam_for_vessel(
    *,
    mmsi: Optional[str] = None,
    cargo_id: Optional[str] = None,
) -> Optional[str]:
    """Return the proxy ``source_id`` that should auto-select for a vessel.

    Resolution order: explicit MMSI map → linked cargo map → ``None``. The
    helper is deliberately conservative: only vessels and cargos that carry
    a narrative role get an auto-selected webcam; everything else falls back
    to the frontend default cycle.
    """
    if mmsi and mmsi in _VESSEL_WEBCAM_MMSI_MAP:
        return _VESSEL_WEBCAM_MMSI_MAP[mmsi]
    if cargo_id and cargo_id in _CARGO_WEBCAM_MAP:
        return _CARGO_WEBCAM_MAP[cargo_id]
    return None


def webcam_cycle_for_vessel(
    *,
    mmsi: Optional[str] = None,
    cargo_id: Optional[str] = None,
) -> list[str]:
    """Return the ordered cycle of source_ids the UI can toggle through.

    The primary recommendation (from :func:`recommended_webcam_for_vessel`)
    comes first; the remaining whitelisted port-webcam sources follow in the
    canonical narrative order. Used by both the chat effect payload and the
    map-vignette UI to keep the storytelling deterministic.
    """
    primary = recommended_webcam_for_vessel(mmsi=mmsi, cargo_id=cargo_id)
    ordered: list[str] = []
    if primary:
        ordered.append(primary)
    for candidate in RECOMMENDED_WEBCAM_CYCLE:
        if candidate not in ordered:
            ordered.append(candidate)
    return ordered


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------


@dataclass
class _CacheEntry:
    expires_at: float
    content: bytes
    mime_type: str
    source: str  # "upstream" | "fallback"
    upstream_status: Optional[int]
    fetched_at: float = field(default_factory=time.time)
    last_attempt_at: float = field(default_factory=time.time)


_CACHE: dict[str, _CacheEntry] = {}
_LOCK = threading.Lock()


def _clear_cache(source_id: Optional[str] = None) -> None:
    """Test-only helper to drop the cache (whole or per source)."""
    with _LOCK:
        if source_id is None:
            _CACHE.clear()
            return
        _CACHE.pop(source_id, None)


def _now() -> float:
    return time.time()


def _read_fallback(spec: WebcamSourceSpec) -> tuple[bytes, str]:
    path = _WEBCAMS_DIR / spec.fallback_filename
    if not path.exists():
        # Last-resort transparent 1×1 PNG so we never raise on the demo path.
        # Hex of a 1x1 transparent PNG.
        single_pixel = bytes.fromhex(
            "89504E470D0A1A0A0000000D49484452000000010000000108060000001F15C489"
            "0000000A49444154789C63000100000005000100B0E25C0F0000000049454E44AE426082"
        )
        return single_pixel, "image/png"
    return path.read_bytes(), spec.fallback_mime


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WebcamProxyResult:
    """What ``fetch_snapshot`` returns to the FastAPI endpoint."""

    spec: WebcamSourceSpec
    content: bytes
    mime_type: str
    cache: str  # "hit" | "miss"
    source: str  # "upstream" | "fallback"
    upstream_status: Optional[int]
    fetched_at: float


# ---------------------------------------------------------------------------
# Upstream client
# ---------------------------------------------------------------------------


def _fetch_upstream(spec: WebcamSourceSpec, *, timeout_seconds: float = 12.0) -> tuple[bytes, str, int]:
    """Best-effort upstream fetch. Returns ``(bytes, mime, status)``.

    Raises ``RuntimeError`` if the response is not a recognized image type
    so the caller can fall back to the static asset.
    """
    headers = {
        "User-Agent": spec.user_agent,
        "Accept": "image/avif,image/webp,image/jpeg,image/png,*/*;q=0.8",
    }
    with httpx.Client(timeout=timeout_seconds, follow_redirects=True) as client:
        response = client.get(spec.upstream_url, headers=headers)
    status = response.status_code
    mime = response.headers.get("content-type", "").split(";")[0].strip().lower()
    if status >= 400:
        raise RuntimeError(f"webcam_proxy_upstream_status:{status}")
    if not mime.startswith("image/"):
        raise RuntimeError(f"webcam_proxy_upstream_not_image:{mime or '<empty>'}")
    return response.content, mime, status


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def fetch_snapshot(
    source_id: str,
    *,
    timeout_seconds: float = 12.0,
    force_refresh: bool = False,
) -> WebcamProxyResult:
    """Resolve ``source_id`` to a fresh-or-cached image snapshot.

    Always returns a payload (upstream when fresh, static fallback otherwise)
    so the demo cockpit never breaks. ``source`` and ``cache`` fields make it
    obvious which lane served the response, both in the API audit log and in
    the headers exposed by the FastAPI route.

    Raises :class:`KeyError` when ``source_id`` is not whitelisted.
    """
    spec = get_spec(source_id)
    if spec is None:
        raise KeyError(source_id)

    now = _now()
    with _LOCK:
        cached = _CACHE.get(source_id)
        if (
            cached
            and not force_refresh
            and cached.expires_at > now
            and (now - cached.last_attempt_at) < spec.min_fetch_interval_seconds
        ):
            return WebcamProxyResult(
                spec=spec,
                content=cached.content,
                mime_type=cached.mime_type,
                cache="hit",
                source=cached.source,
                upstream_status=cached.upstream_status,
                fetched_at=cached.fetched_at,
            )

    upstream_status: Optional[int] = None
    try:
        content, mime, upstream_status = _fetch_upstream(spec, timeout_seconds=timeout_seconds)
        source = "upstream"
    except Exception as exc:  # noqa: BLE001 — log and degrade
        logger.warning("webcam_proxy upstream failed for %s: %s", source_id, exc)
        content, mime = _read_fallback(spec)
        source = "fallback"

    if source == "upstream":
        ttl = spec.ttl_seconds
    else:
        ttl = spec.negative_ttl_seconds
    entry = _CacheEntry(
        expires_at=now + ttl,
        content=content,
        mime_type=mime,
        source=source,
        upstream_status=upstream_status,
        fetched_at=now,
        last_attempt_at=now,
    )
    with _LOCK:
        _CACHE[source_id] = entry
    return WebcamProxyResult(
        spec=spec,
        content=content,
        mime_type=mime,
        cache="miss",
        source=source,
        upstream_status=upstream_status,
        fetched_at=now,
    )


__all__ = [
    "WebcamSourceSpec",
    "WebcamProxyResult",
    "fetch_snapshot",
    "get_spec",
    "list_whitelisted_source_ids",
]
