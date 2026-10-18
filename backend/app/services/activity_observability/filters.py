"""Shared filters for journal pages and their aggregate populations."""

from fastapi import HTTPException

from .projection import STATUSES


def parse_status_filter(value: str | None, *, detail: str) -> tuple[str, ...] | None:
    """Accept one status or a comma-separated union; never widen an invalid filter."""
    if value is None:
        return None
    values = tuple(part.strip() for part in value.split(","))
    if any(part not in STATUSES for part in values):
        raise HTTPException(422, detail=detail)
    return tuple(dict.fromkeys(values))
