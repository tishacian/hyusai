"""UTC anchors shared by observation surfaces, independent of execution clocks."""

from datetime import UTC, datetime, timedelta

from fastapi import HTTPException


def observation_anchor(value: datetime | None = None) -> datetime:
    now = datetime.now(UTC).replace(tzinfo=None)
    if value is None:
        return now
    anchor = value.astimezone(UTC).replace(tzinfo=None) if value.tzinfo else value
    if anchor > now + timedelta(minutes=1):
        raise HTTPException(422, detail="OBSERVATION_ANCHOR_IN_FUTURE")
    return anchor
