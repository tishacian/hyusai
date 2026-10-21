from datetime import datetime, timedelta, timezone

from app.services.intelligence.cadence import source_is_due


def test_cadence_is_per_source_and_has_a_precise_boundary():
    now = datetime(2026, 10, 21, tzinfo=timezone.utc)
    assert source_is_due(None, 86400, now)
    assert not source_is_due(now - timedelta(hours=12), 86400, now)
    assert source_is_due(now - timedelta(hours=24), 86400, now)
    assert source_is_due((now - timedelta(hours=24)).replace(tzinfo=None), 86400, now)
    assert not source_is_due(now + timedelta(minutes=1), 3600, now)
