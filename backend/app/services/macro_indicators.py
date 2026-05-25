"""Macro-economic indicators service for the SENTINEL-CI cockpit (Phase B).

Pulls public, key-less World Bank Open Data series for Cote d'Ivoire and
caches them in ``workspace_macro_indicators`` (24h TTL). A committed
baseline JSON file ships as offline fallback so the demo never hard-fails
when the network is gated.

Public API:
- ``fetch_civ_indicators(db, workspace, force=False)`` — refresh + persist
  series; safe to call from boot, CLI, or the Celery scheduler.
- ``macro_indicators_payload(db, workspace)`` — read-only payload returned
  by ``GET /api/v1/mission-room/macro-indicators``.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

import httpx
from sqlalchemy.orm import Session as DBSession

from app.core.logging import get_logger
from app.models.workspace import Workspace
from app.models.workspace_macro_indicator import WorkspaceMacroIndicator
from app.services.audit_logger import emit_audit_event


logger = get_logger(__name__)


CIV_COUNTRY_CODE = "CIV"
DEFAULT_TTL = timedelta(hours=24)
WORLD_BANK_BASE_URL = "https://api.worldbank.org/v2"
BASELINE_RESOURCE = (
    Path(__file__).resolve().parents[1] / "resources" / "macro" / "civ-indicators-baseline.json"
)
SOVEREIGN_BASELINE_RESOURCE = (
    Path(__file__).resolve().parents[1] / "resources" / "macro" / "sovereign-indicators-baseline.json"
)

SOVEREIGN_INDICATOR_KEYS: tuple[str, ...] = (
    "cacao",
    "anacarde",
    "brent",
    "sovereign_spread",
    "bceao_reserves",
    "cedeao_tension",
    "opinion_ci",
    "abidjan_port",
)

INDICATOR_SPECS: tuple[dict[str, str], ...] = (
    {
        "key": "unemployment",
        "world_bank_code": "SL.UEM.TOTL.ZS",
        "label": "Chomage",
        "unit": "%",
    },
    {
        "key": "inflation",
        "world_bank_code": "FP.CPI.TOTL.ZG",
        "label": "Inflation (IPC, annuel)",
        "unit": "%",
    },
    {
        "key": "gdp_growth",
        "world_bank_code": "NY.GDP.MKTP.KD.ZG",
        "label": "Croissance PIB",
        "unit": "%",
    },
)


def _baseline() -> dict[str, Any]:
    try:
        return json.loads(BASELINE_RESOURCE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        logger.warning("macro_indicators.baseline_missing", path=str(BASELINE_RESOURCE))
        return {"indicators": []}
    except Exception as exc:  # noqa: BLE001
        logger.warning("macro_indicators.baseline_unparsable", error=str(exc))
        return {"indicators": []}


def _baseline_for(indicator_key: str) -> dict[str, Any]:
    for item in _baseline().get("indicators") or []:
        if item.get("key") == indicator_key:
            return item
    return {"series": []}


def _sovereign_baseline() -> dict[str, Any]:
    try:
        return json.loads(SOVEREIGN_BASELINE_RESOURCE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        logger.warning("macro_indicators.sovereign_baseline_missing", path=str(SOVEREIGN_BASELINE_RESOURCE))
        return {"indicators": []}
    except Exception as exc:  # noqa: BLE001
        logger.warning("macro_indicators.sovereign_baseline_unparsable", error=str(exc))
        return {"indicators": []}


def _sovereign_baseline_for(indicator_key: str) -> dict[str, Any]:
    for item in _sovereign_baseline().get("indicators") or []:
        if item.get("key") == indicator_key:
            return item
    return {"series": []}


def _world_bank_series(indicator_code: str, *, timeout: float = 4.5) -> list[dict[str, Any]]:
    """Fetch a yearly series from the World Bank Open Data API (public, no key)."""
    url = f"{WORLD_BANK_BASE_URL}/country/{CIV_COUNTRY_CODE}/indicator/{indicator_code}"
    params = {"format": "json", "per_page": 60}
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.get(url, params=params)
        if response.status_code != 200:
            logger.info(
                "macro_indicators.world_bank_non_200",
                indicator=indicator_code,
                status=response.status_code,
            )
            return []
        payload = response.json()
        if not isinstance(payload, list) or len(payload) < 2 or not isinstance(payload[1], list):
            return []
        rows = payload[1]
    except Exception as exc:  # noqa: BLE001 — graceful fallback
        logger.info("macro_indicators.world_bank_unreachable", indicator=indicator_code, error=str(exc))
        return []
    series: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        value = row.get("value")
        if value is None:
            continue
        try:
            year = int(row.get("date"))
            numeric = float(value)
        except (TypeError, ValueError):
            continue
        series.append({"year": year, "value": round(numeric, 3)})
    series.sort(key=lambda item: item["year"])
    return series


def _current_and_trend(series: list[dict[str, Any]]) -> tuple[Optional[dict[str, Any]], str]:
    if not series:
        return None, ""
    latest = series[-1]
    previous = series[-2] if len(series) >= 2 else None
    if previous and isinstance(previous.get("value"), (int, float)) and isinstance(latest.get("value"), (int, float)):
        delta = round(float(latest["value"]) - float(previous["value"]), 2)
        sign = "+" if delta > 0 else ""
        trend = f"{sign}{delta}"
    else:
        trend = ""
    return latest, trend


def _trend_direction(series: list[dict[str, Any]]) -> str:
    if len(series) < 2:
        return "flat"
    last = float(series[-1]["value"])
    prev = float(series[-2]["value"])
    if last > prev + 0.0001:
        return "up"
    if last < prev - 0.0001:
        return "down"
    return "flat"


def _sovereign_trend(series: list[dict[str, Any]], *, indicator_key: str) -> str:
    if len(series) < 2:
        return ""
    last = float(series[-1]["value"])
    prev = float(series[-2]["value"])
    if indicator_key == "sovereign_spread":
        delta = round(last - prev)
        sign = "+" if delta > 0 else ""
        return f"{sign}{delta} bps"
    if indicator_key in {"cedeao_tension", "opinion_ci", "bceao_reserves"}:
        delta = round(last - prev, 1)
        sign = "+" if delta > 0 else ""
        return f"{sign}{delta}"
    if prev:
        pct = round(((last - prev) / abs(prev)) * 100, 1)
        sign = "+" if pct > 0 else ""
        return f"{sign}{pct}%"
    return ""


def _persist_indicator(
    db: DBSession,
    workspace: Workspace,
    *,
    key: str,
    label: str,
    unit: str,
    series: list[dict[str, Any]],
    source: str,
    status: str,
    metadata: dict[str, Any],
) -> WorkspaceMacroIndicator:
    row = (
        db.query(WorkspaceMacroIndicator)
        .filter(
            WorkspaceMacroIndicator.workspace_id == workspace.id,
            WorkspaceMacroIndicator.indicator_key == key,
        )
        .first()
    )
    current, trend = _current_and_trend(series)
    if not row:
        row = WorkspaceMacroIndicator(
            workspace_id=workspace.id,
            indicator_key=key,
            source=source,
            label=label,
            unit=unit,
            series=series,
            current=current,
            trend=trend,
            fetched_at=datetime.utcnow(),
            status=status,
            meta_data=metadata,
        )
        db.add(row)
    else:
        row.source = source
        row.label = label
        row.unit = unit
        row.series = series
        row.current = current
        row.trend = trend
        row.fetched_at = datetime.utcnow()
        row.status = status
        row.meta_data = {**(row.meta_data or {}), **metadata}
    db.flush()
    return row


def fetch_civ_indicators(
    db: DBSession,
    workspace: Workspace,
    *,
    force: bool = False,
    ttl: timedelta = DEFAULT_TTL,
) -> dict[str, Any]:
    """Refresh Cote d'Ivoire macro indicators in the workspace cache."""
    indicators_payload: list[dict[str, Any]] = []
    refreshed = 0
    fallbacks = 0
    network_used = False
    for spec in INDICATOR_SPECS:
        existing = (
            db.query(WorkspaceMacroIndicator)
            .filter(
                WorkspaceMacroIndicator.workspace_id == workspace.id,
                WorkspaceMacroIndicator.indicator_key == spec["key"],
            )
            .first()
        )
        is_fresh = (
            existing is not None
            and existing.fetched_at is not None
            and (datetime.utcnow() - existing.fetched_at) < ttl
            and existing.status in {"world_bank", "cached"}
            and (existing.series or [])
        )
        if existing and is_fresh and not force:
            indicators_payload.append(_serialize(existing))
            continue
        series = _world_bank_series(spec["world_bank_code"])
        if series:
            network_used = True
            source = "world_bank"
            status = "world_bank"
            metadata = {"world_bank_code": spec["world_bank_code"]}
            refreshed += 1
        else:
            baseline = _baseline_for(spec["key"])
            series = list(baseline.get("series") or [])
            source = "baseline_json"
            status = "fallback"
            metadata = {
                "world_bank_code": spec["world_bank_code"],
                "fallback_reason": "world_bank_unreachable",
            }
            fallbacks += 1
        row = _persist_indicator(
            db,
            workspace,
            key=spec["key"],
            label=spec["label"],
            unit=spec["unit"],
            series=series,
            source=source,
            status=status,
            metadata=metadata,
        )
        indicators_payload.append(_serialize(row))
    db.commit()
    emit_audit_event(
        db=db,
        workspace_id=workspace.id,
        event_type="macro_indicators.refreshed",
        actor="system:macro_indicators",
        details={
            "refreshed": refreshed,
            "fallbacks": fallbacks,
            "network_used": network_used,
            "force": force,
        },
    )
    return {
        "workspace_id": workspace.id,
        "country": CIV_COUNTRY_CODE,
        "indicators": indicators_payload,
        "refreshed": refreshed,
        "fallbacks": fallbacks,
        "network_used": network_used,
    }


def _serialize(row: WorkspaceMacroIndicator) -> dict[str, Any]:
    series = row.series or []
    current = row.current or {}
    metadata = row.meta_data or {}
    return {
        "key": row.indicator_key,
        "label": row.label,
        "unit": row.unit,
        "current": current.get("value") if isinstance(current, dict) else None,
        "current_year": current.get("year") if isinstance(current, dict) else None,
        "trend": row.trend,
        "trend_direction": metadata.get("trend_direction"),
        "prism": metadata.get("prism"),
        "series": series,
        "source": "Banque mondiale" if row.source == "world_bank" else "Banque mondiale (cache baseline)",
        "source_kind": row.source,
        "status": row.status,
        "fetched_at": row.fetched_at.isoformat() if row.fetched_at else None,
        "description": metadata.get("description"),
        "source_url": metadata.get("source_url"),
    }


def _serialize_sovereign(row: WorkspaceMacroIndicator) -> dict[str, Any]:
    series = row.series or []
    current = row.current or {}
    metadata = row.meta_data or {}
    return {
        "id": row.indicator_key,
        "key": row.indicator_key,
        "label": row.label,
        "value": current.get("value") if isinstance(current, dict) else None,
        "current": current.get("value") if isinstance(current, dict) else None,
        "unit": row.unit,
        "delta": row.trend,
        "trend": row.trend,
        "trend_direction": metadata.get("trend_direction"),
        "sparkline": [point.get("value") for point in series if isinstance(point.get("value"), (int, float))],
        "series": series,
        "source": metadata.get("display_source") or row.source,
        "source_url": metadata.get("source_url"),
        "prism": metadata.get("prism"),
        "description": metadata.get("description"),
        "status": row.status,
        "fetched_at": row.fetched_at.isoformat() if row.fetched_at else None,
    }


def _fetch_sovereign_indicators(db: DBSession, workspace: Workspace, *, force: bool = False) -> list[dict[str, Any]]:
    """Load demo-safe sovereign KPIs from committed baseline (24h TTL in cache)."""
    payload: list[dict[str, Any]] = []
    for key in SOVEREIGN_INDICATOR_KEYS:
        baseline = _sovereign_baseline_for(key)
        if not baseline.get("series"):
            continue
        existing = (
            db.query(WorkspaceMacroIndicator)
            .filter(
                WorkspaceMacroIndicator.workspace_id == workspace.id,
                WorkspaceMacroIndicator.indicator_key == key,
            )
            .first()
        )
        is_fresh = (
            existing is not None
            and existing.fetched_at is not None
            and (datetime.utcnow() - existing.fetched_at) < DEFAULT_TTL
            and existing.status == "demo_fixture"
            and (existing.series or [])
        )
        if existing and is_fresh and not force:
            payload.append(_serialize_sovereign(existing))
            continue
        series = list(baseline.get("series") or [])
        current, _ = _current_and_trend(series)
        trend = _sovereign_trend(series, indicator_key=key)
        metadata = {
            "prism": baseline.get("prism"),
            "description": baseline.get("description"),
            "source_url": baseline.get("source_url"),
            "display_source": baseline.get("source"),
            "trend_direction": _trend_direction(series),
        }
        row = _persist_indicator(
            db,
            workspace,
            key=key,
            label=str(baseline.get("label") or key),
            unit=str(baseline.get("unit") or ""),
            series=series,
            source="demo_fixture",
            status="demo_fixture",
            metadata=metadata,
        )
        row.trend = trend
        row.current = current
        db.flush()
        payload.append(_serialize_sovereign(row))
    db.commit()
    return payload


def macro_indicators_payload(db: DBSession, workspace: Workspace) -> dict[str, Any]:
    """Return cached indicators; fetch on demand if cache is empty."""
    rows = (
        db.query(WorkspaceMacroIndicator)
        .filter(WorkspaceMacroIndicator.workspace_id == workspace.id)
        .order_by(WorkspaceMacroIndicator.indicator_key.asc())
        .all()
    )
    if not rows:
        fetch_civ_indicators(db, workspace)
        rows = (
            db.query(WorkspaceMacroIndicator)
            .filter(WorkspaceMacroIndicator.workspace_id == workspace.id)
            .order_by(WorkspaceMacroIndicator.indicator_key.asc())
            .all()
        )
    wb_rows = [row for row in rows if row.indicator_key not in SOVEREIGN_INDICATOR_KEYS]
    sovereign_rows = [row for row in rows if row.indicator_key in SOVEREIGN_INDICATOR_KEYS]
    if len(sovereign_rows) < len(SOVEREIGN_INDICATOR_KEYS):
        sovereign_payload = _fetch_sovereign_indicators(db, workspace)
    else:
        sovereign_payload = [_serialize_sovereign(row) for row in sovereign_rows]
    sovereign_payload.sort(key=lambda item: SOVEREIGN_INDICATOR_KEYS.index(item["key"]))

    fetched_at = max((row.fetched_at for row in rows if row.fetched_at), default=None)
    sovereign_fetched = max(
        (datetime.fromisoformat(item["fetched_at"]) for item in sovereign_payload if item.get("fetched_at")),
        default=None,
    )
    if sovereign_fetched and (fetched_at is None or sovereign_fetched > fetched_at):
        fetched_at = sovereign_fetched
    sources = {row.source for row in wb_rows}
    source_label = (
        "Banque mondiale"
        if sources == {"world_bank"}
        else "Banque mondiale (cache baseline)"
        if sources == {"baseline_json"}
        else "Banque mondiale + cache baseline"
        if sources
        else "Indicateurs souverains (cache baseline)"
    )
    return {
        "indicators": [_serialize(row) for row in wb_rows],
        "sovereign_indicators": sovereign_payload,
        "macro_indicators_sovereign": sovereign_payload,
        "country": CIV_COUNTRY_CODE,
        "source": source_label,
        "sovereign_source": "demo-fixture (osiris baseline)",
        "fetched_at": fetched_at.isoformat() if fetched_at else None,
    }
