"""Per-source scheduling, separate from an explicit operator refresh."""

from datetime import datetime, timezone


def source_is_due(
    last_fetched: datetime | None, interval_seconds: int | None, now: datetime
) -> bool:
    """Return whether the configured source interval has elapsed."""
    if last_fetched is None:
        return True
    previous = (
        last_fetched.replace(tzinfo=timezone.utc) if last_fetched.tzinfo is None else last_fetched
    )
    current = now.replace(tzinfo=timezone.utc) if now.tzinfo is None else now
    return (current - previous).total_seconds() >= max(300, interval_seconds or 3600)
