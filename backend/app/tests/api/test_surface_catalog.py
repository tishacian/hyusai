from __future__ import annotations

from types import SimpleNamespace

from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import actions, agents, catalog, settings, traces


def _catalog_client() -> TestClient:
    app = FastAPI()
    knowledge_router = APIRouter()
    deposit_router = APIRouter()

    @knowledge_router.get("/sessions")
    async def list_sessions() -> dict:
        return {"sessions": []}

    @deposit_router.post("/{access_id}/session")
    async def create_deposit_session(access_id: str) -> dict:
        return {"access_id": access_id}

    app.include_router(catalog.router, prefix="/api/v1/catalog")
    app.include_router(knowledge_router, prefix="/api/v1/knowledge-capture")
    app.include_router(deposit_router, prefix="/api/v1/deposit-links")
    app.include_router(actions.router, prefix="/api/v1/actions")
    app.include_router(agents.router, prefix="/api/v1/agents")
    app.include_router(traces.router, prefix="/api/v1/traces")
    app.include_router(settings.router, prefix="/api/v1/settings")
    app.dependency_overrides[catalog.get_current_user] = lambda: SimpleNamespace(id="user-1")
    return TestClient(app)


def test_endpoint_catalog_covers_all_openapi_routes():
    response = _catalog_client().get("/api/v1/catalog/endpoints")

    assert response.status_code == 200
    body = response.json()
    assert body["version"]
    assert body["uncataloged"] == []

    paths = {(entry["method"], entry["path"]) for entry in body["entries"]}
    assert ("GET", "/api/v1/catalog/endpoints") in paths
    assert ("GET", "/api/v1/actions/effective") in paths
    assert ("GET", "/api/v1/knowledge-capture/sessions") in paths
    assert any(
        entry["path"].startswith("/api/v1/deposit-links/")
        and entry["status"] == "public-external"
        for entry in body["entries"]
    )


def test_catalog_marks_known_compatibility_surfaces():
    body = _catalog_client().get("/api/v1/catalog/endpoints").json()
    entries = body["entries"]

    assert any(
        entry["path"].startswith("/api/v1/agents")
        and entry["status"] == "deprecated"
        and entry["successor_prefix"] == "/api/v1/systems"
        for entry in entries
    )
    assert any(
        entry["path"].startswith("/api/v1/traces")
        and entry["status"] == "deprecated"
        and entry["successor_prefix"] == "/api/v1/runs"
        for entry in entries
    )
    assert any(
        entry["path"].startswith("/api/v1/settings")
        and entry["status"] == "compatibility"
        and entry["successor_prefix"] == "/api/v1/presets"
        for entry in entries
    )


def test_legacy_routers_stamp_successor_headers():
    class FakeOrchestrator:
        def list_agents(self) -> list:
            return []

    app = FastAPI()
    app.include_router(agents.router, prefix="/agents")
    app.include_router(traces.router, prefix="/traces")
    app.include_router(settings.router, prefix="/settings")
    app.dependency_overrides[agents.get_current_user] = lambda: SimpleNamespace(id="user-1")
    app.dependency_overrides[traces.get_current_user] = lambda: SimpleNamespace(id="user-1")
    agents.set_orchestrator(FakeOrchestrator())
    client = TestClient(app)

    agents_response = client.get("/agents")
    traces_response = client.get("/traces/traces")
    settings_response = client.get("/settings/health")

    assert agents_response.headers["X-Deprecated"].startswith("Use /api/v1/systems")
    assert agents_response.headers["Link"] == '</api/v1/systems>; rel="successor-version"'
    assert traces_response.headers["X-Deprecated"].startswith("Use /api/v1/runs")
    assert traces_response.headers["Link"] == '</api/v1/runs>; rel="successor-version"'
    assert settings_response.headers["X-Deprecated"].startswith("Use /api/v1/presets")
    assert settings_response.headers["Link"] == '</api/v1/presets>; rel="successor-version"'
