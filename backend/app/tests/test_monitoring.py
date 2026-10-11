from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import metrics
from app.core.monitoring import MetricsCollector, normalize_endpoint


def _metrics_client() -> TestClient:
    app = FastAPI()
    app.include_router(metrics.router, prefix="/api/v1/metrics")
    app.dependency_overrides[metrics.get_current_user] = lambda: SimpleNamespace(id="user-1")
    return TestClient(app)


def test_normalize_endpoint_keeps_named_routes_and_collapses_ids() -> None:
    assert normalize_endpoint("/api/v1/visual-intelligence/dashboard") == "/api/v1/visual-intelligence/dashboard"
    assert normalize_endpoint("/api/v1/systems/9e6f7a41-2f2e-4e52-9e1a-bdc9d9f44430") == "/api/v1/systems/{uuid}"
    assert normalize_endpoint("/api/v1/deposit-links/I6UUw3U9VbH6dAbBT-Q/files") == "/api/v1/deposit-links/{id}/files"
    assert normalize_endpoint("/api/v1/runs/12345") == "/api/v1/runs/{int}"


def test_metrics_collector_tracks_pending_latency_and_slow_requests() -> None:
    collector = MetricsCollector()

    request_id = collector.start_request(
        "/api/v1/systems/9e6f7a41-2f2e-4e52-9e1a-bdc9d9f44430",
        method="GET",
    )
    collector.record_latency("/api/v1/systems/9e6f7a41-2f2e-4e52-9e1a-bdc9d9f44430", 42.5)
    collector.record_request("/api/v1/systems/9e6f7a41-2f2e-4e52-9e1a-bdc9d9f44430", 200)
    collector.record_slow_request(
        method="GET",
        endpoint="/api/v1/systems/9e6f7a41-2f2e-4e52-9e1a-bdc9d9f44430",
        status_code=200,
        duration_ms=2600.0,
        request_id=request_id,
    )

    runtime = collector.get_runtime_snapshot(include_details=True)
    assert runtime["pending_requests"]["total"] == 1
    assert runtime["pending_requests"]["active"][0]["endpoint"] == "/api/v1/systems/{uuid}"

    endpoints = collector.get_endpoint_summary()
    assert endpoints["/api/v1/systems/{uuid}"]["latency"]["p95_ms"] == 42.5
    assert endpoints["/api/v1/systems/{uuid}"]["requests"]["200"] == 1
    assert runtime["recent_slow_requests"][0]["endpoint"] == "/api/v1/systems/{uuid}"

    collector.finish_request("/api/v1/systems/9e6f7a41-2f2e-4e52-9e1a-bdc9d9f44430", request_id=request_id)
    assert collector.get_runtime_snapshot()["pending_requests"]["total"] == 0


def test_metrics_collector_tracks_streams_and_runtime_health() -> None:
    collector = MetricsCollector()

    stream_id = collector.start_stream(
        "/api/v1/chat/stream",
        stream_type="sse",
        metadata={"assistant_profile": "vigie_executive"},
    )
    runtime = collector.get_runtime_snapshot(include_details=True)
    assert runtime["active_streams"]["total"] == 1
    assert runtime["active_streams"]["active"][0]["metadata"]["assistant_profile"] == "vigie_executive"

    collector.finish_stream(stream_id, status="completed")
    assert collector.get_runtime_snapshot()["active_streams"]["total"] == 0
    assert "/api/v1/chat/stream#sse" in collector.get_endpoint_summary()

    request_id = collector.start_request("/api/v1/mission-room/cockpit", method="GET")
    with collector._lock:
        collector.pending_requests[request_id]["started_monotonic"] -= 31.0
    health = collector.get_runtime_health(stuck_after_ms=30_000.0)
    assert health["status"] == "degraded"
    assert "stuck_requests" in health["reasons"]


def test_metrics_runtime_endpoint_exposes_nonblocking_runtime_state() -> None:
    response = _metrics_client().get("/api/v1/metrics/runtime")

    assert response.status_code == 200
    body = response.json()
    assert "pending_requests" in body
    assert "active_streams" in body
    assert "event_loop_lag" in body


def test_metrics_endpoints_endpoint_exposes_endpoint_summary() -> None:
    metrics.metrics_collector.record_latency("/api/v1/test/123", 10.0)
    metrics.metrics_collector.record_request("/api/v1/test/123", 200)

    response = _metrics_client().get("/api/v1/metrics/endpoints")

    assert response.status_code == 200
    body = response.json()
    assert "/api/v1/test/{int}" in body
    assert body["/api/v1/test/{int}"]["requests"]["200"] >= 1
