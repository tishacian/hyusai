"""Unit tests for the RPA Bridge connector service."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest

from app.services.connectors.rpa import service as rpa_service


def _workspace(slug: str = "agentium-showcase", settings: dict | None = None):
    return SimpleNamespace(
        slug=slug,
        name="Showcase",
        settings=settings if settings is not None else {},
    )


def _mock_db():
    db = MagicMock()
    db.add = MagicMock()
    db.commit = MagicMock()
    db.refresh = MagicMock()
    return db


def test_feature_gate_csv_fallback_and_settings():
    assert rpa_service.is_workspace_enabled(_workspace(slug="agentium-showcase"))
    assert not rpa_service.is_workspace_enabled(_workspace(slug="other-ws"))
    enabled = _workspace(
        slug="other-ws",
        settings={"features": {"rpa_bridge": True}},
    )
    assert rpa_service.is_workspace_enabled(enabled)
    disabled = _workspace(
        slug="agentium-showcase",
        settings={"features": {"rpa_bridge": False}},
    )
    assert not rpa_service.is_workspace_enabled(disabled)


def test_set_and_get_config_masks_token(monkeypatch):
    monkeypatch.delenv(rpa_service.ENV_MASTER_KEY, raising=False)
    monkeypatch.delenv(rpa_service.ENV_FALLBACK_TOKEN, raising=False)
    monkeypatch.setattr(rpa_service, "flag_modified", lambda *_a, **_k: None)
    ws = _workspace()
    db = _mock_db()
    cfg = rpa_service.set_config(
        db,
        ws,
        {
            "base_url": "http://127.0.0.1:8099/",
            "auth_token": "secret-token",
            "job_mapping": {"invoice": "uipath.invoice.v1"},
            "callback_webhook_url": "https://example.com/hooks/rpa",
        },
    )
    assert cfg["base_url"] == "http://127.0.0.1:8099"
    assert cfg["auth_token_set"] is True
    assert cfg["configured"] is True
    assert cfg["job_mapping"] == {"invoice": "uipath.invoice.v1"}
    assert cfg["callback_webhook_url"] == "https://example.com/hooks/rpa"
    assert "auth_token" not in cfg

    secret = rpa_service.get_config(ws, include_secrets=True)
    assert secret["auth_token"] == "secret-token"


def test_set_config_keeps_existing_token_when_omitted(monkeypatch):
    monkeypatch.delenv(rpa_service.ENV_MASTER_KEY, raising=False)
    monkeypatch.delenv(rpa_service.ENV_FALLBACK_TOKEN, raising=False)
    monkeypatch.setattr(rpa_service, "flag_modified", lambda *_a, **_k: None)
    ws = _workspace()
    db = _mock_db()
    rpa_service.set_config(
        db,
        ws,
        {"base_url": "http://localhost:8099", "auth_token": "first"},
    )
    cfg = rpa_service.set_config(
        db,
        ws,
        {"base_url": "http://localhost:8099", "job_mapping": {"a": "b"}},
    )
    assert cfg["job_mapping"] == {"a": "b"}
    assert rpa_service.get_config(ws, include_secrets=True)["auth_token"] == "first"


def test_set_config_requires_http_base_url(monkeypatch):
    monkeypatch.setattr(rpa_service, "flag_modified", lambda *_a, **_k: None)
    ws = _workspace()
    db = _mock_db()
    with pytest.raises(ValueError, match="http"):
        rpa_service.set_config(db, ws, {"base_url": "ftp://bad"})


def test_resolve_job_key_uses_mapping():
    config = {"job_mapping": {"invoice": "ext.invoice"}}
    assert rpa_service.resolve_job_key(config, "invoice") == "ext.invoice"
    assert rpa_service.resolve_job_key(config, "other") == "other"


def test_dispatch_and_poll_success(monkeypatch):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if request.method == "POST" and request.url.path.endswith("/jobs"):
            body = json.loads(request.content.decode("utf-8"))
            assert body["job_key"] == "ext.invoice"
            assert body["input"] == {"po": "42"}
            return httpx.Response(
                200,
                json={"id": "job-1", "status": "running", "job_key": body["job_key"]},
            )
        if request.method == "GET" and request.url.path.endswith("/jobs/job-1"):
            return httpx.Response(
                200,
                json={
                    "id": "job-1",
                    "status": "succeeded",
                    "result": {"ok": True},
                },
            )
        return httpx.Response(404, json={"detail": "not found"})

    transport = httpx.MockTransport(handler)
    real_client = httpx.Client

    def client_factory(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr(rpa_service.httpx, "Client", client_factory)
    monkeypatch.setattr(rpa_service.time, "sleep", lambda *_a, **_k: None)

    config = {
        "base_url": "http://mock-rpa",
        "auth_token": "tok",
        "job_mapping": {"invoice": "ext.invoice"},
    }
    result = rpa_service.dispatch_and_poll(
        config,
        job_key="invoice",
        input_payload={"po": "42"},
        timeout_s=5,
        poll_interval_s=0.01,
    )
    assert result["job_id"] == "job-1"
    assert result["status"] == "succeeded"
    assert result["result"] == {"ok": True}
    assert result["polls"] >= 1
    assert calls["n"] >= 2


def test_dispatch_timeout(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"id": "job-slow", "status": "running"})
        return httpx.Response(200, json={"id": "job-slow", "status": "running"})

    transport = httpx.MockTransport(handler)
    real_client = httpx.Client

    def client_factory(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr(rpa_service.httpx, "Client", client_factory)
    monkeypatch.setattr(rpa_service.time, "sleep", lambda *_a, **_k: None)

    # Force immediate deadline after start.
    clock = {"t": 0.0}

    def fake_perf():
        clock["t"] += 1.0
        return clock["t"]

    monkeypatch.setattr(rpa_service.time, "perf_counter", fake_perf)

    with pytest.raises(TimeoutError, match="did not finish"):
        rpa_service.dispatch_and_poll(
            {"base_url": "http://mock-rpa", "auth_token": "tok"},
            job_key="slow",
            timeout_s=0.5,
            poll_interval_s=0.01,
        )


def test_test_connection_health(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/health")
        assert request.headers.get("Authorization") == "Bearer tok"
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    real_client = httpx.Client

    def client_factory(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr(rpa_service.httpx, "Client", client_factory)
    out = rpa_service.test_connection(
        {"base_url": "http://mock-rpa", "auth_token": "tok"}
    )
    assert out["ok"] is True
    assert out["body"]["ok"] is True
