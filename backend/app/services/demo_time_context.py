"""Unified demo date/time context for SENTINEL-CI executive scenarios."""
from __future__ import annotations

import os
from datetime import date, datetime, time
from typing import Any, Optional

from app.models.workspace import Workspace

DEFAULT_DEMO_DATE = "2026-05-25"
DEFAULT_DEMO_TIME = "10:30:00"
DEFAULT_TIMEZONE = "Africa/Abidjan"

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
    return os.getenv("SENTINEL_DEMO_DATE", DEFAULT_DEMO_DATE)


def resolve_demo_date(workspace: Optional[Workspace] = None) -> date:
    if workspace is not None:
        ctx = (workspace.settings or {}).get("demo_time_context") or {}
        raw = ctx.get("current_date")
        if raw:
            return date.fromisoformat(str(raw))
    return date.fromisoformat(demo_date_from_env())


def resolve_demo_time(workspace: Optional[Workspace] = None) -> time:
    if workspace is not None:
        ctx = (workspace.settings or {}).get("demo_time_context") or {}
        raw = ctx.get("current_time")
        if raw:
            parts = str(raw).split(":")
            if len(parts) >= 2:
                return time(int(parts[0]), int(parts[1]), int(parts[2]) if len(parts) > 2 else 0)
    default = os.getenv("SENTINEL_DEMO_TIME", DEFAULT_DEMO_TIME)
    parts = default.split(":")
    return time(int(parts[0]), int(parts[1]), int(parts[2]) if len(parts) > 2 else 0)


def demo_date_label(day: date) -> str:
    return f"{_WEEKDAYS_FR[day.weekday()]} {day.day} {_MONTHS_FR[day.month - 1]} {day.year}"


def demo_time_context_defaults(workspace: Optional[Workspace] = None) -> dict[str, Any]:
    day = resolve_demo_date(workspace)
    return {
        "mode": "fixed",
        "current_date": day.isoformat(),
        "current_time": resolve_demo_time(workspace).strftime("%H:%M:%S"),
        "label": demo_date_label(day),
        "timezone": DEFAULT_TIMEZONE,
    }


def demo_datetime_at(hour: int, minute: int = 0, *, workspace: Optional[Workspace] = None) -> datetime:
    return datetime.combine(resolve_demo_date(workspace), time(hour, minute))
