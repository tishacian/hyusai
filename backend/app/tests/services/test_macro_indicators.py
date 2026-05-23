"""Tests for ``app.services.macro_indicators`` (Phase B)."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.models.workspace import Workspace
from app.models.workspace_macro_indicator import WorkspaceMacroIndicator
from app.services import macro_indicators


def _workspace() -> Workspace:
    return Workspace(id="ws-macro", slug="sentinel-ci", name="SENTINEL-CI", settings={})


def test_fetch_civ_indicators_falls_back_when_world_bank_unreachable(monkeypatch, db_session):
    workspace = _workspace()
    db_session.add(workspace)
    db_session.commit()

    monkeypatch.setattr(macro_indicators, "_world_bank_series", lambda code, **_: [])

    result = macro_indicators.fetch_civ_indicators(db_session, workspace)
    assert result["fallbacks"] == 3
    assert result["refreshed"] == 0
    assert result["network_used"] is False
    indicator_keys = {item["key"] for item in result["indicators"]}
    assert indicator_keys == {"unemployment", "inflation", "gdp_growth"}

    rows = db_session.query(WorkspaceMacroIndicator).filter(
        WorkspaceMacroIndicator.workspace_id == workspace.id
    ).all()
    assert len(rows) == 3
    assert all(row.status == "fallback" for row in rows)
    assert all(row.series for row in rows)


def test_fetch_civ_indicators_uses_world_bank_when_available(monkeypatch, db_session):
    workspace = _workspace()
    db_session.add(workspace)
    db_session.commit()

    fake_series = [
        {"year": 2022, "value": 3.1},
        {"year": 2023, "value": 3.4},
        {"year": 2024, "value": 3.7},
    ]
    monkeypatch.setattr(macro_indicators, "_world_bank_series", lambda code, **_: fake_series)

    result = macro_indicators.fetch_civ_indicators(db_session, workspace)
    assert result["refreshed"] == 3
    assert result["fallbacks"] == 0
    assert result["network_used"] is True
    for item in result["indicators"]:
        assert item["status"] == "world_bank"
        assert item["current"] == 3.7
        assert item["current_year"] == 2024
        assert item["trend"] == "+0.3"


def test_fetch_civ_indicators_respects_ttl(monkeypatch, db_session):
    workspace = _workspace()
    db_session.add(workspace)
    db_session.commit()

    monkeypatch.setattr(macro_indicators, "_world_bank_series", lambda code, **_: [{"year": 2024, "value": 5.0}])
    macro_indicators.fetch_civ_indicators(db_session, workspace)

    call_counter = {"count": 0}

    def _counter(code, **_):
        call_counter["count"] += 1
        return [{"year": 2024, "value": 5.5}]

    monkeypatch.setattr(macro_indicators, "_world_bank_series", _counter)

    second = macro_indicators.fetch_civ_indicators(db_session, workspace)
    assert call_counter["count"] == 0, "World Bank should not be re-hit while cache is fresh"
    assert all(item["current"] == 5.0 for item in second["indicators"])

    forced = macro_indicators.fetch_civ_indicators(db_session, workspace, force=True)
    assert call_counter["count"] == 3, "Forcing should invalidate the cache"
    assert all(item["current"] == 5.5 for item in forced["indicators"])


def test_macro_indicators_payload_lazy_populates(monkeypatch, db_session):
    workspace = _workspace()
    db_session.add(workspace)
    db_session.commit()

    monkeypatch.setattr(macro_indicators, "_world_bank_series", lambda code, **_: [])

    payload = macro_indicators.macro_indicators_payload(db_session, workspace)
    assert payload["country"] == "CIV"
    assert {item["key"] for item in payload["indicators"]} == {"unemployment", "inflation", "gdp_growth"}
    assert "Banque mondiale" in payload["source"]
