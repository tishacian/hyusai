from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import model_portal
from app.models.user import User
from app.models.workspace import Workspace
from app.services.model_plane import workspace_config as ws_config


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


def _setup_client(db_session, workspace: Workspace, user: User) -> TestClient:
    app = FastAPI()
    app.include_router(model_portal.router, prefix="/models")
    app.dependency_overrides[model_portal.get_current_workspace] = lambda: workspace
    app.dependency_overrides[model_portal.get_current_user] = lambda: user
    app.dependency_overrides[model_portal.get_db] = lambda: db_session
    return TestClient(app)


def test_model_setup_validates_then_persists_once(monkeypatch, db_session):
    workspace = Workspace(
        id="ws-model-setup-ready",
        name="Model Setup Ready",
        slug="model-setup-ready",
        settings={
            "llm_portal": {
                "routing": {
                    "default_provider": "ollama",
                    "default_model": "old-model",
                }
            }
        },
    )
    user = User(
        id="model-setup-admin",
        username="model-setup-admin",
        email="model-setup-admin@example.test",
        role="admin",
    )
    db_session.add_all([workspace, user])
    db_session.commit()

    async def ready(*, workspace):
        routing = ws_config.get_routing(workspace)
        assert routing["default_provider"] == "openai"
        assert routing["default_model"] == "gpt-test"
        assert ws_config.get_decrypted_api_key(workspace, "openai") == "sk-valid"
        return {
            "provider": "openai",
            "model": "gpt-test",
            "source": "workspace",
            "status": "ready",
            "reason": "ready",
            "message": "The selected provider and model are ready.",
            "retryable": False,
            "provider_status": "active",
        }

    monkeypatch.setattr(model_portal.providers_service, "get_readiness", ready)

    response = _setup_client(db_session, workspace, user).put(
        "/models/setup",
        json={
            "provider": "openai",
            "model": "gpt-test",
            "fallback_chain": ["openai"],
            "api_key": "sk-valid",
        },
    )

    assert response.status_code == 200
    assert response.json()["readiness"]["status"] == "ready"
    assert response.json()["provider"]["api_key_set"] is True
    db_session.refresh(workspace)
    assert ws_config.get_routing(workspace)["default_model"] == "gpt-test"
    assert ws_config.get_decrypted_api_key(workspace, "openai") == "sk-valid"


def test_failed_model_setup_preserves_last_working_configuration(monkeypatch, db_session):
    initial_settings = {
        "llm_portal": {
            "routing": {
                "default_provider": "ollama",
                "default_model": "working-model",
            }
        }
    }
    workspace = Workspace(
        id="ws-model-setup-rejected",
        name="Model Setup Rejected",
        slug="model-setup-rejected",
        settings=initial_settings,
    )
    user = User(
        id="model-setup-rejected-admin",
        username="model-setup-rejected-admin",
        email="model-setup-rejected-admin@example.test",
        role="admin",
    )
    db_session.add_all([workspace, user])
    db_session.commit()

    async def rejected(**_kwargs):
        return {
            "provider": "openai",
            "model": "missing-model",
            "source": "workspace",
            "status": "needs_setup",
            "reason": "model_missing",
            "message": "The selected model is not available from this provider.",
            "retryable": False,
        }

    monkeypatch.setattr(model_portal.providers_service, "get_readiness", rejected)

    response = _setup_client(db_session, workspace, user).put(
        "/models/setup",
        json={
            "provider": "openai",
            "model": "missing-model",
            "api_key": "sk-invalid",
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"]["reason"] == "model_missing"
    db_session.refresh(workspace)
    assert workspace.settings == initial_settings


def test_legacy_routing_write_cannot_bypass_validation(monkeypatch, db_session):
    initial_settings = {
        "llm_portal": {
            "routing": {
                "default_provider": "ollama",
                "default_model": "working-model",
            }
        }
    }
    workspace = Workspace(
        id="ws-legacy-routing-rejected",
        name="Legacy Routing Rejected",
        slug="legacy-routing-rejected",
        settings=initial_settings,
    )
    user = User(
        id="legacy-routing-admin",
        username="legacy-routing-admin",
        email="legacy-routing-admin@example.test",
        role="admin",
    )
    db_session.add_all([workspace, user])
    db_session.commit()

    async def unreachable(**_kwargs):
        return {
            "status": "unavailable",
            "reason": "provider_unreachable",
            "message": "The model service is not responding.",
            "retryable": True,
        }

    monkeypatch.setattr(model_portal.providers_service, "get_readiness", unreachable)

    response = _setup_client(db_session, workspace, user).put(
        "/models/routing",
        json={"default_provider": "openai", "default_model": "gpt-test"},
    )

    assert response.status_code == 422
    db_session.refresh(workspace)
    assert workspace.settings == initial_settings


def test_legacy_credential_write_requires_the_guided_setup_for_a_new_provider(db_session):
    workspace = Workspace(
        id="ws-legacy-credential-rejected",
        name="Legacy Credential Rejected",
        slug="legacy-credential-rejected",
        settings={
            "llm_portal": {
                "routing": {
                    "default_provider": "ollama",
                    "default_model": "qwen3:8b",
                }
            }
        },
    )
    user = User(
        id="legacy-credential-admin",
        username="legacy-credential-admin",
        email="legacy-credential-admin@example.test",
        role="admin",
    )
    db_session.add_all([workspace, user])
    db_session.commit()

    response = _setup_client(db_session, workspace, user).put(
        "/models/credentials/openai",
        json={"api_key": "sk-unverified"},
    )

    assert response.status_code == 422
    db_session.refresh(workspace)
    assert ws_config.get_decrypted_api_key(workspace, "openai") is None
