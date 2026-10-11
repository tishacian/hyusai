"""Unit tests for the rpa_dispatch_v1 skill wrapper."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.services.connectors.rpa import service as rpa_service
from app.services.skills_registry import wrappers


@pytest.mark.asyncio
async def test_rpa_dispatch_wrapper_is_bound():
    assert wrappers.runtime_status("rpa_dispatch_v1") == "bound"


@pytest.mark.asyncio
async def test_rpa_dispatch_wrapper_calls_service(monkeypatch):
    workspace = SimpleNamespace(
        id="ws-1",
        slug="agentium-showcase",
        settings={"features": {"rpa_bridge": True}},
    )
    db = MagicMock()
    monkeypatch.setattr(
        wrappers,
        "_calendar_db_and_workspace",
        lambda payload, ctx=None: (db, workspace),
    )

    captured: dict = {}

    def fake_dispatch(config, **kwargs):
        captured["config"] = config
        captured["kwargs"] = kwargs
        return {
            "job_id": "j1",
            "job_key": kwargs["job_key"],
            "status": "succeeded",
            "result": {"ok": True},
            "polls": 1,
            "duration_ms": 12,
            "timed_out": False,
        }

    monkeypatch.setattr(rpa_service, "is_workspace_enabled", lambda _ws: True)
    monkeypatch.setattr(
        rpa_service,
        "get_config",
        lambda _ws, *, include_secrets=False: {
            "base_url": "http://mock-rpa",
            "auth_token": "tok",
            "configured": True,
            "job_mapping": {},
        },
    )
    monkeypatch.setattr(rpa_service, "dispatch_and_poll", fake_dispatch)

    result = await wrappers._rpa_dispatch_v1(
        {"job_key": "invoice", "input": {"n": 1}, "timeout_s": 10},
        {"db": db, "workspace_id": "ws-1"},
    )
    assert result["status"] == "succeeded"
    assert result["job_id"] == "j1"
    assert captured["kwargs"]["job_key"] == "invoice"
    assert captured["kwargs"]["input_payload"] == {"n": 1}
    assert captured["kwargs"]["timeout_s"] == 10.0


@pytest.mark.asyncio
async def test_rpa_dispatch_rejects_disabled_workspace(monkeypatch):
    workspace = SimpleNamespace(
        id="ws-1",
        slug="other",
        settings={"features": {"rpa_bridge": False}},
    )
    db = MagicMock()
    monkeypatch.setattr(
        wrappers,
        "_calendar_db_and_workspace",
        lambda payload, ctx=None: (db, workspace),
    )
    monkeypatch.setattr(rpa_service, "is_workspace_enabled", lambda _ws: False)

    with pytest.raises(ValueError, match="not enabled"):
        await wrappers._rpa_dispatch_v1(
            {"job_key": "x"},
            {"db": db, "workspace_id": "ws-1"},
        )


@pytest.mark.asyncio
async def test_rpa_dispatch_rejects_unconfigured(monkeypatch):
    workspace = SimpleNamespace(id="ws-1", slug="agentium-showcase", settings={})
    db = MagicMock()
    monkeypatch.setattr(
        wrappers,
        "_calendar_db_and_workspace",
        lambda payload, ctx=None: (db, workspace),
    )
    monkeypatch.setattr(rpa_service, "is_workspace_enabled", lambda _ws: True)
    monkeypatch.setattr(
        rpa_service,
        "get_config",
        lambda _ws, *, include_secrets=False: {
            "base_url": "",
            "configured": False,
        },
    )

    with pytest.raises(ValueError, match="not configured"):
        await wrappers._rpa_dispatch_v1(
            {"job_key": "x"},
            {"db": db, "workspace_id": "ws-1"},
        )
