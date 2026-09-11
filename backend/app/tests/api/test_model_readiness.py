from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import model_portal
from app.models.user import User
from app.models.workspace import Workspace


def test_model_readiness_api_reports_selected_provider_and_model(monkeypatch):
    workspace = Workspace(
        id="ws-model-readiness",
        name="Model Readiness",
        slug="model-readiness",
        settings={
            "features": {"model_portal_beta": True},
            "llm_portal": {
                "routing": {
                    "default_provider": "ollama",
                    "default_model": "qwen3:8b",
                }
            },
        },
    )
    user = User(
        id="model-readiness-owner",
        username="model-readiness-owner",
        email="model-readiness-owner@example.test",
        role="admin",
    )

    async def forbidden_nodes(**_kwargs):
        raise AssertionError("Ollama readiness must not probe unrelated serving nodes")

    async def fake_ollama():
        return {
            "status": "active",
            "latency_ms": 2.0,
            "models": ["qwen3:8b"],
            "error": None,
        }

    monkeypatch.setattr(model_portal.serving_nodes_service, "list_nodes", forbidden_nodes)
    monkeypatch.setattr(model_portal.providers_service, "_health_ollama", fake_ollama)

    app = FastAPI()
    app.include_router(model_portal.router, prefix="/models")
    app.dependency_overrides[model_portal.get_current_workspace] = lambda: workspace
    app.dependency_overrides[model_portal.get_current_user] = lambda: user

    response = TestClient(app).get("/models/readiness")

    assert response.status_code == 200
    assert response.json() == {
        "provider": "ollama",
        "model": "qwen3:8b",
        "source": "workspace",
        "status": "ready",
        "reason": "ready",
        "message": "The selected provider and model are ready.",
        "retryable": False,
        "provider_status": "active",
    }
