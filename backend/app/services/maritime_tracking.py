"""Provider-neutral maritime vessel tracking for SENTINEL-CI.

The service is *demo-safe by default*: every call resolves through a curated
JSON snapshot (``backend/app/resources/maritime/abidjan-vessels-baseline.json``)
that anchors the storytelling around ``MV Atlantic Trader`` (cargo
``cargo-abidjan-supply-001`` / IMO 9876543 / MMSI 627012345). Optional providers
can be enabled at runtime through environment variables — see
``docs/sentinel-ci-maritime-webcams-integration.md``:

* ``SENTINEL_AIS_PROVIDER=baseline``  → JSON snapshot (default)
* ``SENTINEL_AIS_PROVIDER=aisstream`` → live WebSocket via AISStream.io
* ``SENTINEL_AIS_PROVIDER=aishub``    → REST snapshot via AISHub
* ``SENTINEL_AIS_PROVIDER=marinetraffic_embed`` → keeps baseline but exposes
  the public MarineTraffic iframe URL for the UI overlay.

Live providers must degrade silently and reuse the baseline if anything fails,
so the demo always renders. Nothing in this module performs blocking network
calls during request handling: live integrations are stubbed and only attempted
when a non-baseline provider is explicitly configured.
"""
from __future__ import annotations

import json
import logging
import time
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Optional

from pydantic import BaseModel, Field

from app.core.config import settings


logger = logging.getLogger(__name__)


_BASELINE_PATH = (
    Path(__file__).resolve().parents[1]
    / "resources"
    / "maritime"
    / "abidjan-vessels-baseline.json"
)


VesselType = str  # cargo|container|tanker|roro|fishing|tug|passenger|other
NavStatus = str   # at_anchor|moored|underway_using_engine|...


class BBox(BaseModel):
    """Geographic bounding box (lon/lat). Inclusive on all four edges."""

    west: float = Field(..., ge=-180.0, le=180.0)
    south: float = Field(..., ge=-90.0, le=90.0)
    east: float = Field(..., ge=-180.0, le=180.0)
    north: float = Field(..., ge=-90.0, le=90.0)

    def contains(self, lon: float, lat: float) -> bool:
        if self.south > self.north or self.west > self.east:
            return False
        return self.west <= lon <= self.east and self.south <= lat <= self.north


class VesselPosition(BaseModel):
    """A single AIS-equivalent vessel position consumed by the cockpit."""

    mmsi: str
    imo: Optional[str] = None
    name: str
    callsign: Optional[str] = None
    lat: float
    lon: float
    sog: Optional[float] = Field(default=None, description="Speed over ground (knots)")
    cog: Optional[float] = Field(default=None, description="Course over ground (deg)")
    heading: Optional[float] = Field(default=None, description="Heading (deg)")
    vessel_type: Optional[VesselType] = None
    nav_status: Optional[NavStatus] = None
    destination: Optional[str] = None
    eta: Optional[str] = None
    length: Optional[float] = None
    beam: Optional[float] = None
    draught: Optional[float] = None
    flag: Optional[str] = None
    last_seen: Optional[str] = None
    source: str = "baseline"
    demo_safe: bool = True
    linked_cargo_id: Optional[str] = None
    linked_project_ref: Optional[str] = None
    highlight: Optional[str] = None
    demo_role: Optional[str] = None


class VesselSnapshot(BaseModel):
    """Provider-agnostic snapshot returned to API consumers."""

    vessels: list[VesselPosition]
    bbox: Optional[BBox] = None
    source: str
    provider: str
    fetched_at: str
    ttl_seconds: int = 300
    embed_url: Optional[str] = None
    attribution: Optional[str] = None
    limitations: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

_PROVIDER_CACHE: dict[str, tuple[float, VesselSnapshot]] = {}


def _ttl_seconds(provider: str) -> int:
    return {
        "baseline": 300,
        "marinetraffic_embed": 300,
        "aisstream": 60,
        "aishub": 120,
    }.get(provider, 300)


def _cache_get(provider: str) -> Optional[VesselSnapshot]:
    cached = _PROVIDER_CACHE.get(provider)
    if not cached:
        return None
    expires_at, snapshot = cached
    if expires_at < time.time():
        _PROVIDER_CACHE.pop(provider, None)
        return None
    return snapshot


def _cache_put(provider: str, snapshot: VesselSnapshot) -> None:
    _PROVIDER_CACHE[provider] = (time.time() + _ttl_seconds(provider), snapshot)


def _clear_cache() -> None:
    _PROVIDER_CACHE.clear()


# ---------------------------------------------------------------------------
# Baseline loader
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _load_baseline_document() -> dict[str, Any]:
    if not _BASELINE_PATH.exists():
        return {"_meta": {}, "vessels": []}
    with _BASELINE_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _baseline_meta() -> dict[str, Any]:
    return dict(_load_baseline_document().get("_meta") or {})


def _baseline_vessels() -> list[VesselPosition]:
    document = _load_baseline_document()
    meta = document.get("_meta") or {}
    last_seen = meta.get("captured_at")
    vessels: list[VesselPosition] = []
    for row in document.get("vessels") or []:
        try:
            vessels.append(
                VesselPosition(
                    mmsi=str(row.get("mmsi")),
                    imo=str(row["imo"]) if row.get("imo") else None,
                    name=str(row.get("name") or row.get("mmsi") or "Vessel"),
                    callsign=row.get("callsign"),
                    lat=float(row.get("lat")),
                    lon=float(row.get("lon")),
                    sog=_optional_float(row.get("sog")),
                    cog=_optional_float(row.get("cog")),
                    heading=_optional_float(row.get("heading")),
                    vessel_type=row.get("vessel_type"),
                    nav_status=row.get("nav_status"),
                    destination=row.get("destination"),
                    eta=row.get("eta"),
                    length=_optional_float(row.get("length")),
                    beam=_optional_float(row.get("beam")),
                    draught=_optional_float(row.get("draught")),
                    flag=row.get("flag"),
                    last_seen=last_seen,
                    source="baseline",
                    demo_safe=True,
                    linked_cargo_id=row.get("linked_cargo_id"),
                    linked_project_ref=row.get("linked_project_ref"),
                    highlight=row.get("highlight"),
                    demo_role=row.get("demo_role"),
                )
            )
        except (TypeError, ValueError) as exc:  # noqa: PERF203
            logger.warning("Skipping malformed baseline vessel %s: %s", row.get("mmsi"), exc)
    return vessels


def _optional_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _baseline_bbox() -> Optional[BBox]:
    raw = (_baseline_meta().get("bbox") or {})
    try:
        return BBox(
            west=float(raw["west"]),
            south=float(raw["south"]),
            east=float(raw["east"]),
            north=float(raw["north"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Provider configuration
# ---------------------------------------------------------------------------


ALLOWED_PROVIDERS = {"baseline", "aisstream", "aishub", "marinetraffic_embed"}


def _configured_provider() -> str:
    provider = (getattr(settings, "sentinel_ais_provider", None) or "baseline").lower()
    if provider not in ALLOWED_PROVIDERS:
        logger.warning("Unknown SENTINEL_AIS_PROVIDER=%s; falling back to baseline", provider)
        return "baseline"
    return provider


def _marinetraffic_embed_url(bbox: Optional[BBox]) -> str:
    centre = bbox if bbox else _baseline_bbox()
    if centre:
        lon = round((centre.east + centre.west) / 2, 4)
        lat = round((centre.north + centre.south) / 2, 4)
    else:
        lon, lat = -3.998, 5.247
    # Public iframe widget exposed by MarineTraffic. Free of charge, no key,
    # subject to MarineTraffic ToS (attribution displayed inside the widget).
    return (
        "https://www.marinetraffic.com/en/ais/embed/"
        f"zoom:11/centery:{lat}/centerx:{lon}/maptype:0/shownames:false/"
        "mmsi:0/shipid:0/fleet:/fleet_id:/vtypes:/showmenu:/remember:false"
    )


# ---------------------------------------------------------------------------
# Provider implementations
# ---------------------------------------------------------------------------


def _baseline_snapshot(bbox: Optional[BBox]) -> VesselSnapshot:
    vessels = _baseline_vessels()
    meta = _baseline_meta()
    if bbox is None:
        bbox = _baseline_bbox()
    return VesselSnapshot(
        vessels=vessels,
        bbox=bbox,
        source="baseline",
        provider="baseline",
        fetched_at=str(meta.get("captured_at") or ""),
        ttl_seconds=_ttl_seconds("baseline"),
        attribution=str(meta.get("attribution") or ""),
        limitations=[
            "Snapshot demo-safe : positions cohérentes mais non temps réel.",
            "Aucun appel a un provider AIS payant.",
        ],
    )


def _marinetraffic_embed_snapshot(bbox: Optional[BBox]) -> VesselSnapshot:
    base = _baseline_snapshot(bbox)
    return base.model_copy(
        update={
            "provider": "marinetraffic_embed",
            "embed_url": _marinetraffic_embed_url(base.bbox),
            "limitations": base.limitations
            + [
                "Provider 'marinetraffic_embed' fournit un iframe public pour visualisation,",
                "mais les positions JSON restent basees sur la baseline demo-safe.",
            ],
        }
    )


def _aisstream_snapshot(bbox: Optional[BBox]) -> VesselSnapshot:
    """Stub for the AISStream.io WebSocket adapter.

    A production adapter would maintain a long-lived ``websockets.connect``
    coroutine to ``wss://stream.aisstream.io/v0/stream`` filtered by the
    configured ``BoundingBoxes`` and store the latest position per MMSI.
    The cockpit calls this function from a synchronous request handler, so it
    always serves from an in-memory cache: when no live snapshot exists we
    silently fall back to the baseline (and tag the snapshot accordingly) so
    the UI keeps rendering.
    """
    api_key = getattr(settings, "sentinel_aisstream_api_key", None)
    if not api_key:
        snapshot = _baseline_snapshot(bbox)
        return snapshot.model_copy(
            update={
                "provider": "aisstream",
                "source": "baseline",
                "limitations": snapshot.limitations
                + [
                    "AISStream provider selected but AISSTREAM_API_KEY is empty:"
                    " serving baseline.",
                ],
            }
        )
    # Real implementation would update a shared store from a background
    # consumer; we keep the wiring explicit here so that the integration
    # surface is documented and obvious to future maintainers.
    logger.info("aisstream provider configured (key=%s***); using baseline pending consumer", api_key[:4])
    snapshot = _baseline_snapshot(bbox)
    return snapshot.model_copy(
        update={
            "provider": "aisstream",
            "source": "baseline",
            "limitations": snapshot.limitations
            + [
                "AISStream consumer not yet wired: see"
                " docs/sentinel-ci-maritime-webcams-integration.md.",
            ],
        }
    )


def _aishub_snapshot(bbox: Optional[BBox]) -> VesselSnapshot:
    """Stub for AISHub.net REST snapshot.

    A production adapter would call
    ``https://data.aishub.net/ws.php?username=...&format=1&output=json``
    bounded by the requested bbox; we provide the same graceful fallback as
    AISStream while keeping the integration point easy to wire later.
    """
    username = getattr(settings, "sentinel_aishub_username", None)
    if not username:
        snapshot = _baseline_snapshot(bbox)
        return snapshot.model_copy(
            update={
                "provider": "aishub",
                "source": "baseline",
                "limitations": snapshot.limitations
                + [
                    "AISHub provider selected but SENTINEL_AISHUB_USERNAME is empty:"
                    " serving baseline.",
                ],
            }
        )
    snapshot = _baseline_snapshot(bbox)
    return snapshot.model_copy(
        update={
            "provider": "aishub",
            "source": "baseline",
            "limitations": snapshot.limitations
            + [
                "AISHub adapter not yet wired: see"
                " docs/sentinel-ci-maritime-webcams-integration.md.",
            ],
        }
    )


_PROVIDERS = {
    "baseline": _baseline_snapshot,
    "marinetraffic_embed": _marinetraffic_embed_snapshot,
    "aisstream": _aisstream_snapshot,
    "aishub": _aishub_snapshot,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def fetch_snapshot(
    bbox: Optional[BBox] = None,
    *,
    provider: Optional[str] = None,
    use_cache: bool = True,
) -> VesselSnapshot:
    """Return the active provider's snapshot, optionally cached for its TTL."""
    chosen = (provider or _configured_provider()).lower()
    if chosen not in _PROVIDERS:
        chosen = "baseline"
    cache_key = f"{chosen}:{_bbox_key(bbox)}"
    if use_cache:
        cached = _cache_get(cache_key)
        if cached:
            return cached
    try:
        snapshot = _PROVIDERS[chosen](bbox)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Provider %s failed, falling back to baseline: %s", chosen, exc)
        snapshot = _baseline_snapshot(bbox).model_copy(
            update={"limitations": [f"Provider {chosen} failure: fallback baseline.", str(exc)[:240]]}
        )
    if use_cache:
        _cache_put(cache_key, snapshot)
    return snapshot


def _bbox_key(bbox: Optional[BBox]) -> str:
    if not bbox:
        return "*"
    return f"{round(bbox.west, 3)},{round(bbox.south, 3)},{round(bbox.east, 3)},{round(bbox.north, 3)}"


def fetch_vessels_in_bbox(
    bbox: Optional[BBox] = None,
    limit: int = 50,
    *,
    vessel_types: Optional[Iterable[str]] = None,
    provider: Optional[str] = None,
    use_cache: bool = True,
) -> list[VesselPosition]:
    """Return vessels filtered by bbox + optional type list (highest priority first).

    "Highest priority" means: vessels carrying a ``highlight`` flag (linked to
    the demo narrative) come first, then the remainder ordered by MMSI for
    deterministic responses.
    """
    snapshot = fetch_snapshot(bbox, provider=provider, use_cache=use_cache)
    vessels = list(snapshot.vessels)
    if bbox is not None:
        vessels = [vessel for vessel in vessels if bbox.contains(vessel.lon, vessel.lat)]
    if vessel_types:
        wanted = {kind.strip().lower() for kind in vessel_types if kind}
        if wanted:
            vessels = [vessel for vessel in vessels if (vessel.vessel_type or "").lower() in wanted]
    vessels.sort(
        key=lambda vessel: (
            0 if vessel.highlight else 1,
            0 if vessel.linked_cargo_id else 1,
            vessel.mmsi,
        )
    )
    if limit is not None and limit > 0:
        vessels = vessels[: int(limit)]
    return vessels


def find_vessel_by_mmsi(
    mmsi: str,
    *,
    provider: Optional[str] = None,
) -> Optional[VesselPosition]:
    snapshot = fetch_snapshot(provider=provider)
    normalized = str(mmsi).strip()
    if not normalized:
        return None
    for vessel in snapshot.vessels:
        if vessel.mmsi == normalized:
            return vessel
    return None


def find_vessel_by_imo(imo: str, *, provider: Optional[str] = None) -> Optional[VesselPosition]:
    snapshot = fetch_snapshot(provider=provider)
    normalized = str(imo).strip()
    if not normalized:
        return None
    for vessel in snapshot.vessels:
        if (vessel.imo or "").strip() == normalized:
            return vessel
    return None


def serialize_snapshot(snapshot: VesselSnapshot) -> dict[str, Any]:
    """Public-friendly serialization used by API endpoints."""
    return {
        "vessels": [vessel.model_dump(exclude_none=True) for vessel in snapshot.vessels],
        "bbox": snapshot.bbox.model_dump() if snapshot.bbox else None,
        "source": snapshot.source,
        "provider": snapshot.provider,
        "fetched_at": snapshot.fetched_at,
        "ttl_seconds": snapshot.ttl_seconds,
        "embed_url": snapshot.embed_url,
        "attribution": snapshot.attribution,
        "limitations": list(snapshot.limitations or []),
        "policy": "advisory_only",
        "demo_safe": snapshot.source == "baseline",
    }


def serialize_vessel(vessel: VesselPosition) -> dict[str, Any]:
    return vessel.model_dump(exclude_none=True)


__all__ = [
    "ALLOWED_PROVIDERS",
    "BBox",
    "VesselPosition",
    "VesselSnapshot",
    "fetch_snapshot",
    "fetch_vessels_in_bbox",
    "find_vessel_by_mmsi",
    "find_vessel_by_imo",
    "serialize_snapshot",
    "serialize_vessel",
]
