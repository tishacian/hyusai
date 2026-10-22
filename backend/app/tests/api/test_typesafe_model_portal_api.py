"""TypeSafe setup uses existing workspace-admin and write-only credential APIs."""

from cryptography.fernet import Fernet

from app.api.v1.endpoints import model_portal
from app.tests.api.test_model_portal_api import portal as portal


def test_admin_can_configure_test_and_clear_typesafe_without_generation(portal, monkeypatch):
    client, workspace, user, system, skill, flow, dispatches = portal
    monkeypatch.setenv("LLM_PORTAL_FERNET_KEY", Fernet.generate_key().decode())
    response = client.put(
        "/models/credentials/typesafe", json={"api_key": "test-typesafe-private-key"}
    )
    assert response.status_code == 200, response.text
    assert response.json()["provider"] == {"key": "typesafe", "api_key_set": True}
    assert "test-typesafe-private-key" not in response.text
    config = client.get("/models/config").json()
    assert "typesafe" not in config["runtime_providers"]
    assert "test-typesafe-private-key" not in str(config)

    async def probe(*, api_key=None):
        assert api_key == "test-typesafe-private-key"
        return {"status": "active", "models": ["jev-latest"], "latency_ms": 1, "error": None}

    monkeypatch.setattr(model_portal.providers_service, "_health_typesafe", probe)
    response = client.post("/models/providers/typesafe/test")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["test_kind"] == "connection" and body["generation_verified"] is False
    assert body["provider"]["capabilities"] == ["typed_decisions"]
    assert body["provider"]["runtime_available"] is False
    assert body["provider"]["models"] == ["jev-latest"]
    assert dispatches == []
    cleared = client.put("/models/credentials/typesafe", json={"clear_api_key": True})
    assert cleared.status_code == 200
    assert cleared.json()["provider"]["api_key_set"] is False


def test_non_admin_cannot_change_or_test_typesafe_credentials(portal):
    client, workspace, user, system, skill, flow, dispatches = portal
    user.role = "user"
    assert (
        client.put("/models/credentials/typesafe", json={"api_key": "not-written"}).status_code
        == 403
    )
    assert client.post("/models/providers/typesafe/test").status_code == 403
    assert dispatches == []


def test_typesafe_cannot_be_selected_as_workspace_chat_default(portal):
    client, workspace, *_ = portal
    response = client.put(
        "/models/routing", json={"default_provider": "typesafe", "default_model": "jev-1.13.0"}
    )
    assert response.status_code == 400, response.text
    assert response.json()["detail"]["code"] == "MODEL_PORTAL_CONFIG_INVALID"
