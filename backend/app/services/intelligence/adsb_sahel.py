"""ADS-B Sahel snapshot for SENTINEL-CI OSINT live (Vague 2.2).

Port simplifie d'osiris ``api/flights`` : bounding boxes Bamako/Ouaga/Niamey/Abidjan,
classification military heuristique, cache 60s, fallback baseline JSON.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import httpx

from app.core.logging import get_logger
from app.services.intelligence.cache import cache_get, cache_set

logger = get_logger(__name__)

CACHE_KEY = "intelligence:security:adsb:v1"
CACHE_TTL_SECONDS = 60

BASELINE_RESOURCE = (
    Path(__file__).resolve().parents[2] / "resources" / "security" / "adsb-sahel-baseline.json"
)

ADSB_API = "https://api.adsb.lol/v2/lat/{lat}/lon/{lon}/dist/{dist}"

HUBS: tuple[tuple[str, float, float, int], ...] = (
    ("Bamako", 12.6392, -8.0029, 250),
    ("Ouagadougou", 12.3714, -1.5197, 250),
    ("Niamey", 13.5137, 2.1098, 250),
    ("Abidjan", 5.3600, -4.0083, 200),
)

MILITARY_CALLSIGN_PREFIXES = ("RCH", "KING", "CHARLY", "CNV", "NATO", "FRA", "BFA", "NIG", "MAL")
MILITARY_TYPES = (
    "C130",
    "C-130",
    "C17",
    "C-17",
    "CN235",
    "CN-235",
    "AT6",
    "AT-6",
    "P3",
    "P-3",
    "A400",
    "KC135",
    "KC-135",
    "HELI",
)


def _baseline() -> dict[str, Any]:
    try:
        return json.loads(BASELINE_RESOURCE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        logger.warning("adsb_sahel.baseline_missing", path=str(BASELINE_RESOURCE))
        return {"tracks": [], "watch_zones": [], "cedeao_bases": []}
    except Exception as exc:  # noqa: BLE001
        logger.warning("adsb_sahel.baseline_unparsable", error=str(exc))
        return {"tracks": [], "watch_zones": [], "cedeao_bases": []}


def _is_military(row: dict[str, Any]) -> bool:
    callsign = str(row.get("flight") or row.get("callsign") or "").upper()
    if any(callsign.startswith(prefix) for prefix in MILITARY_CALLSIGN_PREFIXES):
        return True
    db_flags = row.get("dbFlags") or row.get("db_flags") or 0
    try:
        if int(db_flags) & 1:
            return True
    except (TypeError, ValueError):
        pass
    aircraft_type = str(row.get("t") or row.get("type") or row.get("desc") or "").upper()
    return any(token in aircraft_type for token in MILITARY_TYPES)


def _classify_kind(row: dict[str, Any]) -> str:
    aircraft_type = str(row.get("t") or row.get("type") or row.get("desc") or "Unknown")
    if "C130" in aircraft_type.upper() or "C-130" in aircraft_type.upper():
        return "C-130 (transport)"
    if "CN235" in aircraft_type.upper() or "CN-235" in aircraft_type.upper():
        return "CN-235 (transport leger)"
    if "C17" in aircraft_type.upper() or "C-17" in aircraft_type.upper():
        return "C-17 (transport lourd)"
    if "AT6" in aircraft_type.upper() or "AT-6" in aircraft_type.upper():
        return "AT-6 Wolverine (appui)"
    if row.get("alt_baro", row.get("altitude", 0)) and float(row.get("alt_baro", row.get("altitude", 0)) or 0) < 8000:
        return "Helicoptere advisory"
    return aircraft_type or "Vol advisory"


def _normalize_track(row: dict[str, Any], *, index: int) -> Optional[dict[str, Any]]:
    lat = row.get("lat")
    lon = row.get("lon")
    if lat is None or lon is None:
        return None
    try:
        latitude = float(lat)
        longitude = float(lon)
    except (TypeError, ValueError):
        return None
    callsign = str(row.get("flight") or row.get("callsign") or f"UNK{index:04d}")
    military = _is_military(row)
    altitude = row.get("alt_baro", row.get("altitude"))
    try:
        altitude_ft = int(float(altitude)) if altitude is not None else None
    except (TypeError, ValueError):
        altitude_ft = None
    track = row.get("track", row.get("heading"))
    try:
        heading = int(float(track)) if track is not None else None
    except (TypeError, ValueError):
        heading = None
    speed = row.get("gs", row.get("speed"))
    try:
        speed_kt = int(float(speed)) if speed is not None else None
    except (TypeError, ValueError):
        speed_kt = None
    hex_code = str(row.get("hex") or "")
    return {
        "id": f"adsb-{hex_code or index}",
        "callsign": callsign,
        "kind": _classify_kind(row),
        "operator": "Vol militaire advisory" if military else "Vol logistique regional",
        "altitude_ft": altitude_ft,
        "heading": heading,
        "speed_kt": speed_kt,
        "longitude": longitude,
        "latitude": latitude,
        "origin": "ADS-B live (advisory)",
        "destination": "ADS-B live (advisory)",
        "tone": "watch" if military else "stable",
        "military": military,
        "hex": hex_code,
    }


def _fetch_hub(name: str, lat: float, lon: float, dist_nm: int, *, timeout: float = 6.0) -> list[dict[str, Any]]:
    url = ADSB_API.format(lat=lat, lon=lon, dist=dist_nm)
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            response = client.get(
                url,
                headers={"User-Agent": "Agentium-SENTINEL-CI/1.0"},
            )
        if response.status_code != 200:
            logger.info("adsb_sahel.hub_non_200", hub=name, status=response.status_code)
            return []
        payload = response.json()
        if isinstance(payload, dict):
            rows = payload.get("ac") or payload.get("aircraft") or []
        elif isinstance(payload, list):
            rows = payload
        else:
            rows = []
        return [row for row in rows if isinstance(row, dict)]
    except Exception as exc:  # noqa: BLE001
        logger.info("adsb_sahel.hub_unreachable", hub=name, error=str(exc))
        return []


def _collect_live_tracks() -> list[dict[str, Any]]:
    seen_hex: set[str] = set()
    tracks: list[dict[str, Any]] = []
    index = 0
    for _name, lat, lon, dist in HUBS:
        for row in _fetch_hub(_name, lat, lon, dist):
            hex_code = str(row.get("hex") or "")
            if hex_code and hex_code in seen_hex:
                continue
            if hex_code:
                seen_hex.add(hex_code)
            normalized = _normalize_track(row, index=index)
            index += 1
            if normalized:
                tracks.append(normalized)
    military_first = sorted(tracks, key=lambda item: (not item.get("military"), -(item.get("altitude_ft") or 0)))
    return military_first[:40]


def _baseline_payload(*, reason: str = "baseline_json") -> dict[str, Any]:
    baseline = _baseline()
    return {
        **baseline,
        "live": False,
        "source": reason,
        "source_kind": "adsb_baseline",
        "source_badge": "CACHE BASELINE",
        "fetched_at": baseline.get("captured_at") or datetime.utcnow().isoformat() + "Z",
        "track_count": len(baseline.get("tracks") or []),
    }


def sync_adsb_sahel(*, force: bool = False) -> dict[str, Any]:
    if not force:
        cached = cache_get(CACHE_KEY)
        if cached:
            return cached

    tracks = _collect_live_tracks()
    baseline = _baseline()
    if not tracks:
        payload = _baseline_payload(reason="adsb_live_empty_fallback")
        cache_set(CACHE_KEY, payload, CACHE_TTL_SECONDS)
        return payload

    payload: dict[str, Any] = {
        "captured_at": datetime.utcnow().isoformat() + "Z",
        "disclaimer": baseline.get("disclaimer")
        or "ADS-B advisory only — aucune donnee operationnelle classifiee.",
        "theater_label": baseline.get("theater_label") or "Theatre Sahel — axe Bamako/Ouagadougou/Niamey",
        "live": True,
        "source": "adsb.lol",
        "source_kind": "adsb_live",
        "source_badge": "LIVE",
        "fetched_at": datetime.utcnow().isoformat() + "Z",
        "tracks": tracks,
        "watch_zones": baseline.get("watch_zones") or [],
        "cedeao_bases": baseline.get("cedeao_bases") or [],
        "track_count": len(tracks),
        "military_count": sum(1 for track in tracks if track.get("military")),
    }
    cache_set(CACHE_KEY, payload, CACHE_TTL_SECONDS)
    return payload


def adsb_sahel_payload(*, allow_live: bool = True) -> dict[str, Any]:
    if allow_live:
        cached = cache_get(CACHE_KEY)
        if cached and cached.get("live"):
            return cached
    return _baseline_payload()
