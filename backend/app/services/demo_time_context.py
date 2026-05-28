"""Unified demo date/time context for SENTINEL-CI executive scenarios."""
from __future__ import annotations

import os
from datetime import date, datetime, time
from typing import Any, Optional
from zoneinfo import ZoneInfo

from app.models.workspace import Workspace

DEFAULT_DEMO_DATE = "2026-05-25"
DEFAULT_DEMO_TIME = "10:30:00"
DEFAULT_TIMEZONE = "Africa/Abidjan"
DEFAULT_DEMO_MODE = "rolling"

_MONTHS_FR = (
    "Janvier",
    "Fevrier",
    "Mars",
    "Avril",
    "Mai",
    "Juin",
    "Juillet",
    "Aout",
    "Septembre",
    "Octobre",
    "Novembre",
    "Decembre",
)
_WEEKDAYS_FR = ("Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche")


def demo_date_from_env() -> str:
    return os.getenv("SENTINEL_DEMO_DATE", _abidjan_today().isoformat())


def _abidjan_now() -> datetime:
    return datetime.now(ZoneInfo(DEFAULT_TIMEZONE)).replace(tzinfo=None)


def _abidjan_today() -> date:
    return _abidjan_now().date()


def _demo_context(workspace: Optional[Workspace]) -> dict[str, Any]:
    if workspace is None:
        return {}
    return dict((workspace.settings or {}).get("demo_time_context") or {})


def _context_mode(ctx: dict[str, Any]) -> str:
    return str(os.getenv("SENTINEL_DEMO_DATE_MODE") or ctx.get("mode") or DEFAULT_DEMO_MODE).strip().lower()


def _is_locked_fixed_context(ctx: dict[str, Any]) -> bool:
    return bool(ctx.get("locked") or ctx.get("lock_fixed"))


def _parse_time(value: str) -> time:
    parts = str(value).split(":")
    if len(parts) >= 2:
        return time(int(parts[0]), int(parts[1]), int(parts[2]) if len(parts) > 2 else 0)
    return time(int(parts[0]), 0)


def resolve_demo_date(workspace: Optional[Workspace] = None) -> date:
    if os.getenv("SENTINEL_DEMO_DATE"):
        return date.fromisoformat(str(os.environ["SENTINEL_DEMO_DATE"]))

    ctx = _demo_context(workspace)
    mode = _context_mode(ctx)
    raw = ctx.get("current_date")
    rolling_modes = {"rolling", "live", "current", "today", "auto"}
    if mode in rolling_modes:
        return _abidjan_today()

    if mode == "fixed" and raw == DEFAULT_DEMO_DATE and not _is_locked_fixed_context(ctx):
        # Legacy SENTINEL-CI workspaces were seeded with 25/05/2026 as a
        # fixed demo day. Treat that un-locked seed as rolling so the cockpit
        # follows the actual Africa/Abidjan day during repeated demos.
        return _abidjan_today()

    if raw:
        return date.fromisoformat(str(raw))
    return _abidjan_today()


def resolve_demo_time(workspace: Optional[Workspace] = None) -> time:
    if os.getenv("SENTINEL_DEMO_TIME"):
        return _parse_time(str(os.environ["SENTINEL_DEMO_TIME"]))

    ctx = _demo_context(workspace)
    mode = _context_mode(ctx)
    raw = ctx.get("current_time")
    rolling_modes = {"rolling", "live", "current", "today", "auto"}
    if mode in rolling_modes or (mode == "fixed" and ctx.get("current_date") == DEFAULT_DEMO_DATE and not _is_locked_fixed_context(ctx)):
        return _abidjan_now().time().replace(microsecond=0)
    if raw:
        return _parse_time(str(raw))
    return _parse_time(DEFAULT_DEMO_TIME)


def demo_date_label(day: date) -> str:
    return f"{_WEEKDAYS_FR[day.weekday()]} {day.day} {_MONTHS_FR[day.month - 1]} {day.year}"


def demo_time_context_defaults(workspace: Optional[Workspace] = None) -> dict[str, Any]:
    day = resolve_demo_date(workspace)
    ctx = _demo_context(workspace)
    mode = _context_mode(ctx)
    if mode == "fixed" and ctx.get("current_date") == DEFAULT_DEMO_DATE and not _is_locked_fixed_context(ctx):
        mode = DEFAULT_DEMO_MODE
    return {
        "mode": mode,
        "current_date": day.isoformat(),
        "current_time": resolve_demo_time(workspace).strftime("%H:%M:%S"),
        "label": demo_date_label(day),
        "timezone": DEFAULT_TIMEZONE,
    }


def demo_datetime_at(hour: int, minute: int = 0, *, workspace: Optional[Workspace] = None) -> datetime:
    return datetime.combine(resolve_demo_date(workspace), time(hour, minute))
