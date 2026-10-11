from __future__ import annotations

import pytest

from app.models.workspace import Workspace
from app.services.intelligence import cache as intel_cache
from app.services.intelligence import cedeao_index
from app.services.mission_room import (
    SECURITY_POSTURE,
    _resolve_security_posture,
    _security_live_osint_enabled,
    cedeao_index_payload_for_workspace,
)


@pytest.fixture(autouse=True)
def _clear_intel_cache():
    intel_cache.clear_memory_cache()
    yield
    intel_cache.clear_memory_cache()


def test_composite_score_weights_components():
    components = {
        "unrest": 60.0,
        "conflict": 70.0,
        "security_advisories": 80.0,
        "information": 50.0,
    }
    score = cedeao_index._composite_score(components)
    assert 50.0 <= score <= 100.0


def test_sync_cedeao_index_uses_rss_cache(monkeypatch):
    monkeypatch.setattr(
        cedeao_index,
        "sync_rss_security",
        lambda force=False: {
            "live": True,
            "source_badge": "LIVE",
            "articles": [{"security_score": 72, "title": "Tension Sahel"}],
            "signals": [{"id": "sig-1", "label": "Tension Sahel"}],
            "fetched_at": "2026-05-25T12:00:00Z",
        },
    )
    payload = cedeao_index.sync_cedeao_index(force=True)
    assert payload["score"] >= 50
    assert payload["source_badge"] == "LIVE"
    assert "components" in payload


def test_cedeao_index_payload_baseline_when_live_disabled():
    payload = cedeao_index.cedeao_index_payload(allow_live=False)
    assert payload["live"] is False
    assert payload["source_badge"] == "CACHE BASELINE"
    assert payload["score"] >= 50


def test_demo_workspace_forces_baseline_guard_rail(db_session):
    workspace = Workspace(id="ws-demo", slug="sentinel-ci", name="SENTINEL-CI", mode="demo", settings={"feature_flag": {"security_live_osint": True}})
    db_session.add(workspace)
    db_session.commit()
    assert _security_live_osint_enabled(workspace) is False

    intel_cache.cache_set(
        "intelligence:security:rss:v1",
        {"live": True, "source_badge": "LIVE", "signals": [{"id": "sig-live", "label": "Live RSS", "tone": "watch", "summary": "Live"}]},
        900,
    )
    posture = _resolve_security_posture(workspace)
    assert posture["osint_sources"]["rss"]["source_badge"] == "CACHE BASELINE"
    assert posture["osint_sources"]["rss"]["live"] is False


def test_cedeao_index_endpoint_payload_marks_demo_mode(db_session):
    workspace = Workspace(id="ws-demo-2", slug="sentinel-ci-2", name="SENTINEL-CI", mode="demo", settings={})
    db_session.add(workspace)
    db_session.commit()
    payload = cedeao_index_payload_for_workspace(workspace)
    assert payload["demo_mode"] is True
    assert payload["policy"] == "advisory_only"
    assert payload["source_badge"] == "CACHE BASELINE"


def test_component_weights_sum_to_one():
    """Composite weights must form a probability simplex (sum == 1.0)."""
    total = sum(cedeao_index.COMPONENT_WEIGHTS.values())
    assert abs(total - 1.0) < 1e-6


def test_cedeao_index_baseline_score_is_stable_offline():
    """Without any live RSS, the score must stay within the published baseline window."""
    payload = cedeao_index.cedeao_index_payload(allow_live=False)
    assert 40.0 <= payload["score"] <= 90.0
    assert payload["unit"] == "/100"
    assert payload["components"].keys() == cedeao_index.COMPONENT_WEIGHTS.keys()
    assert len(payload["series"]) >= 7


def test_resolve_security_posture_preserves_demo_signals(db_session):
    """Demo mode must keep the fixed SECURITY_POSTURE signals intact and badges baseline."""
    workspace = Workspace(
        id="ws-resolve-demo",
        slug="sentinel-ci-resolve",
        name="SENTINEL-CI",
        mode="demo",
        settings={},
    )
    db_session.add(workspace)
    db_session.commit()
    posture = _resolve_security_posture(workspace)
    interior_labels = [signal["label"] for signal in posture["interior"]["signals"]]
    fixture_labels = [signal["label"] for signal in SECURITY_POSTURE["interior"]["signals"]]
    assert interior_labels == fixture_labels
    assert posture["osint_sources"]["rss"]["source_badge"] == "CACHE BASELINE"
    assert posture["osint_sources"]["cedeao_index"]["source_badge"] == "CACHE BASELINE"


def test_trend_direction_thresholds():
    assert cedeao_index._trend_direction(1.0) == "up"
    assert cedeao_index._trend_direction(-1.0) == "down"
    assert cedeao_index._trend_direction(0.0) == "stable"
    assert cedeao_index._trend_direction(0.4) == "stable"
