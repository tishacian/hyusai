"""CEDEAO tension index for SENTINEL-CI OSINT live (Vague 2.2).

Composite allégé worldmonitor CII : 4 composantes 0-100 (Unrest, Conflict,
Security advisories, Information/rumeur), score composite + delta 7j.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from app.core.logging import get_logger
from app.services.intelligence.cache import cache_get, cache_set
from app.services.intelligence.rss_security import rss_security_payload, score_security_text, sync_rss_security

logger = get_logger(__name__)

CACHE_KEY = "intelligence:security:cedeao:v1"
CACHE_TTL_SECONDS = 1800

BASELINE_RESOURCE = (
    Path(__file__).resolve().parents[2] / "resources" / "macro" / "sovereign-indicators-baseline.json"
)

COMPONENT_WEIGHTS = {
    "unrest": 0.30,
    "conflict": 0.25,
    "security_advisories": 0.25,
    "information": 0.20,
}

RUMOR_BASELINE_SCORE = 64.0
UNREST_BASELINE_SCORE = 58.0
CONFLICT_BASELINE_SCORE = 72.0
ADVISORY_BASELINE_SCORE = 68.0


def _cedeao_baseline_series() -> list[dict[str, Any]]:
    try:
        document = json.loads(BASELINE_RESOURCE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return []
    for indicator in document.get("indicators") or []:
        if indicator.get("key") == "cedeao_tension":
            return list(indicator.get("series") or [])
    return []


def _series_delta_7d(series: list[dict[str, Any]]) -> float:
    if len(series) < 2:
        return 0.0
    try:
        latest = float(series[-1]["value"])
        anchor_index = max(0, len(series) - 8)
        previous = float(series[anchor_index]["value"])
        return round(latest - previous, 1)
    except (KeyError, TypeError, ValueError):
        return 0.0


def _rss_component_score(rss: Optional[dict[str, Any]]) -> float:
    if not rss:
        return ADVISORY_BASELINE_SCORE
    articles = rss.get("articles") or []
    if not articles:
        return ADVISORY_BASELINE_SCORE
    scores = [float(item.get("security_score") or 0) for item in articles[:12]]
    if not scores:
        return ADVISORY_BASELINE_SCORE
    return round(sum(scores) / len(scores), 1)


def _information_component_score() -> float:
    rumor_text = (
        "Rumeur frontiere Nord tweet telegram blog regional demanti officiel "
        "pulsation sociale inquiete"
    )
    return float(score_security_text(rumor_text)["score"])


def _build_components(rss: Optional[dict[str, Any]]) -> dict[str, float]:
    rss_score = _rss_component_score(rss)
    return {
        "unrest": round((UNREST_BASELINE_SCORE * 0.55) + (rss_score * 0.45), 1),
        "conflict": CONFLICT_BASELINE_SCORE,
        "security_advisories": round((ADVISORY_BASELINE_SCORE * 0.4) + (rss_score * 0.6), 1),
        "information": round((RUMOR_BASELINE_SCORE * 0.5) + (_information_component_score() * 0.5), 1),
    }


def _composite_score(components: dict[str, float]) -> float:
    total = 0.0
    for key, weight in COMPONENT_WEIGHTS.items():
        total += float(components.get(key) or 0) * weight
    return round(total, 1)


def _trend_direction(delta: float) -> str:
    if delta > 0.5:
        return "up"
    if delta < -0.5:
        return "down"
    return "stable"


def sync_cedeao_index(*, force: bool = False) -> dict[str, Any]:
    if not force:
        cached = cache_get(CACHE_KEY)
        if cached:
            return cached

    rss = sync_rss_security(force=force)
    components = _build_components(rss)
    composite = _composite_score(components)
    series = _cedeao_baseline_series()
    delta_7d = _series_delta_7d(series) if series else round(composite - 71.0, 1)

    payload: dict[str, Any] = {
        "live": bool(rss.get("live")),
        "source": "CEDEAO composite (RSS + baseline ACLED-like + rumeur)",
        "source_kind": "cedeao_index",
        "source_badge": "LIVE" if rss.get("live") else "CACHE BASELINE",
        "fetched_at": datetime.utcnow().isoformat() + "Z",
        "score": composite,
        "unit": "/100",
        "delta_7d": delta_7d,
        "trend": _trend_direction(delta_7d),
        "components": components,
        "component_weights": COMPONENT_WEIGHTS,
        "series": series
        or [
            {
                "date": (datetime.utcnow() - timedelta(days=offset)).strftime("%Y-%m-%d"),
                "value": round(composite - (6 - offset) * 0.4, 1),
            }
            for offset in range(7, -1, -1)
        ],
        "attribution": "Composite ouvert — ACLED-like baseline + RSS securite + rumeur demo.",
    }
    cache_set(CACHE_KEY, payload, CACHE_TTL_SECONDS)
    return payload


def cedeao_index_payload(*, allow_live: bool = True) -> dict[str, Any]:
    if allow_live:
        cached = cache_get(CACHE_KEY)
        if cached:
            return cached
        rss = rss_security_payload(allow_live=True)
        if rss:
            components = _build_components(rss)
            composite = _composite_score(components)
            series = _cedeao_baseline_series()
            delta_7d = _series_delta_7d(series) if series else 0.0
            return {
                "live": bool(rss.get("live")),
                "source": "CEDEAO composite (RSS + baseline ACLED-like + rumeur)",
                "source_kind": "cedeao_index",
                "source_badge": "LIVE" if rss.get("live") else "CACHE BASELINE",
                "fetched_at": datetime.utcnow().isoformat() + "Z",
                "score": composite,
                "unit": "/100",
                "delta_7d": delta_7d,
                "trend": _trend_direction(delta_7d),
                "components": components,
                "component_weights": COMPONENT_WEIGHTS,
                "series": series,
                "attribution": "Composite ouvert — ACLED-like baseline + RSS securite + rumeur demo.",
            }

    series = _cedeao_baseline_series()
    latest = float(series[-1]["value"]) if series else 72.0
    return {
        "live": False,
        "source": "OSINT composite (cache baseline)",
        "source_kind": "cedeao_baseline",
        "source_badge": "CACHE BASELINE",
        "fetched_at": datetime.utcnow().isoformat() + "Z",
        "score": latest,
        "unit": "/100",
        "delta_7d": _series_delta_7d(series),
        "trend": _trend_direction(_series_delta_7d(series)),
        "components": {
            "unrest": UNREST_BASELINE_SCORE,
            "conflict": CONFLICT_BASELINE_SCORE,
            "security_advisories": ADVISORY_BASELINE_SCORE,
            "information": RUMOR_BASELINE_SCORE,
        },
        "component_weights": COMPONENT_WEIGHTS,
        "series": series,
        "attribution": "Baseline demo — reproductible Vice Premier Ministre.",
    }
