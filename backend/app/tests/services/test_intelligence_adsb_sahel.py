from __future__ import annotations

import pytest

from app.services.intelligence import adsb_sahel, cache as intel_cache


@pytest.fixture(autouse=True)
def _clear_intel_cache():
    intel_cache.clear_memory_cache()
    yield
    intel_cache.clear_memory_cache()


def test_is_military_detects_callsign_and_type():
    assert adsb_sahel._is_military({"flight": "RCH1234", "t": "C130"}) is True
    assert adsb_sahel._is_military({"flight": "AFR123", "t": "A320"}) is False


def test_normalize_track_maps_coordinates():
    track = adsb_sahel._normalize_track(
        {
            "hex": "abc123",
            "flight": "FRA9201",
            "lat": 12.5,
            "lon": -7.9,
            "alt_baro": 22000,
            "track": 65,
            "gs": 280,
            "t": "C130",
        },
        index=1,
    )
    assert track is not None
    assert track["callsign"] == "FRA9201"
    assert track["military"] is True
    assert track["latitude"] == 12.5


def test_sync_adsb_sahel_falls_back_to_baseline_when_live_empty(monkeypatch):
    monkeypatch.setattr(adsb_sahel, "_collect_live_tracks", lambda: [])
    payload = adsb_sahel.sync_adsb_sahel(force=True)
    assert payload["live"] is False
    assert payload["source_badge"] == "CACHE BASELINE"
    assert len(payload.get("tracks") or []) >= 10


def test_sync_adsb_sahel_marks_live_when_tracks_present(monkeypatch):
    monkeypatch.setattr(
        adsb_sahel,
        "_collect_live_tracks",
        lambda: [
            {
                "id": "adsb-live-1",
                "callsign": "RCH001",
                "kind": "C-130 (transport)",
                "operator": "Vol militaire advisory",
                "altitude_ft": 20000,
                "heading": 90,
                "speed_kt": 260,
                "longitude": -2.0,
                "latitude": 13.0,
                "origin": "ADS-B live (advisory)",
                "destination": "ADS-B live (advisory)",
                "tone": "watch",
                "military": True,
                "hex": "live1",
            }
        ],
    )
    payload = adsb_sahel.sync_adsb_sahel(force=True)
    assert payload["live"] is True
    assert payload["source_badge"] == "LIVE"
    assert payload["tracks"][0]["callsign"] == "RCH001"


def test_adsb_sahel_payload_demo_forces_baseline(monkeypatch):
    live_payload = {
        "live": True,
        "source_badge": "LIVE",
        "tracks": [{"id": "live"}],
        "watch_zones": [],
        "cedeao_bases": [],
    }
    intel_cache.cache_set(adsb_sahel.CACHE_KEY, live_payload, 60)
    baseline = adsb_sahel.adsb_sahel_payload(allow_live=False)
    assert baseline["live"] is False
    assert baseline["source_badge"] == "CACHE BASELINE"


def test_fetch_hub_handles_5xx_and_network_errors(monkeypatch):
    """Hub fetch must degrade to empty list on HTTP failure or network exception."""

    class _ServerErrorClient:
        def __init__(self, *_args, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

        def get(self, *_args, **_kwargs):
            class _R:
                status_code = 502
                def json(self):
                    return {}
            return _R()

    monkeypatch.setattr(adsb_sahel.httpx, "Client", _ServerErrorClient)
    assert adsb_sahel._fetch_hub("Bamako", 12.0, -8.0, 200) == []

    class _BoomClient:
        def __init__(self, *_args, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

        def get(self, *_args, **_kwargs):
            raise OSError("simulated timeout")

    monkeypatch.setattr(adsb_sahel.httpx, "Client", _BoomClient)
    assert adsb_sahel._fetch_hub("Bamako", 12.0, -8.0, 200) == []


def test_baseline_payload_preserves_disclaimer_and_zones():
    payload = adsb_sahel._baseline_payload()
    assert payload["live"] is False
    assert payload["source_badge"] == "CACHE BASELINE"
    assert "advisory" in (payload.get("disclaimer") or "").lower()
    assert payload["track_count"] >= 1
    assert any(zone.get("name") for zone in (payload.get("watch_zones") or []))


def test_normalize_track_handles_invalid_coordinates():
    """Tracks missing or non-numeric lat/lon must be silently dropped."""
    assert adsb_sahel._normalize_track({"flight": "X", "lat": None, "lon": -3.0}, index=0) is None
    assert adsb_sahel._normalize_track({"flight": "X", "lat": "nope", "lon": -3.0}, index=0) is None
    assert adsb_sahel._normalize_track({"flight": "X"}, index=0) is None
