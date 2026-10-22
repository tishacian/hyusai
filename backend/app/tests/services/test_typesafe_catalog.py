"""TypeSafe discovery authenticates without generating a decision or exposing keys."""

from types import SimpleNamespace

import httpx
import pytest
from cryptography.fernet import Fernet

from app.services.model_plane import providers, workspace_config


@pytest.fixture(autouse=True)
def isolated_catalog(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.setenv("LLM_PORTAL_FERNET_KEY", Fernet.generate_key().decode())
    providers.clear_health_cache()
    yield
    providers.clear_health_cache()


def _workspace(identity="workspace-a"):
    return SimpleNamespace(id=identity, settings={})


def _mock_http(monkeypatch, handler):
    client_class = httpx.AsyncClient
    monkeypatch.setattr(
        providers.httpx,
        "AsyncClient",
        lambda **kwargs: client_class(transport=httpx.MockTransport(handler), **kwargs),
    )


def test_typesafe_key_is_write_only_replaceable_and_clearable():
    workspace = _workspace()
    public = workspace_config.set_cloud_credential(
        None, workspace, "typesafe", api_key="test-private-typesafe-key"
    )
    assert "test-private-typesafe-key" not in str(public)
    assert "test-private-typesafe-key" not in str(workspace.settings)
    assert next(row for row in public["cloud_credentials"] if row["key"] == "typesafe") == {
        "key": "typesafe",
        "api_key_set": True,
    }
    assert (
        workspace_config.get_decrypted_api_key(workspace, "typesafe") == "test-private-typesafe-key"
    )
    workspace_config.set_cloud_credential(None, workspace, "typesafe", api_key="replacement-key")
    assert workspace_config.get_decrypted_api_key(workspace, "typesafe") == "replacement-key"
    public = workspace_config.set_cloud_credential(None, workspace, "typesafe", clear_api_key=True)
    assert workspace_config.get_decrypted_api_key(workspace, "typesafe") is None
    assert not next(row for row in public["cloud_credentials"] if row["key"] == "typesafe")[
        "api_key_set"
    ]


@pytest.mark.asyncio
async def test_unconfigured_typesafe_advertises_decision_capability_without_probe(monkeypatch):
    async def forbidden(**kwargs):
        pytest.fail("an unconfigured provider must not probe")

    monkeypatch.setattr(providers, "_health_typesafe", forbidden)
    rows = await providers.list_providers(
        workspace=_workspace(), provider_key="typesafe", include_local_serving=False
    )
    assert len(rows) == 1
    row = rows[0]
    assert row["status"] == "available" and not row["configured"]
    assert row["runtime_available"] is False
    assert row["typed_decisions_available"] is True
    assert row["capabilities"] == ["typed_decisions"]
    assert row["models"] == ["jev-1.13.0"]
    assert row["models_source"] == "documented_catalog"
    assert row["generation_verified"] is False
    assert row["portal_url"] == "https://console.typesafe.ai/keys"


@pytest.mark.asyncio
async def test_probe_uses_authenticated_get_and_account_catalog(monkeypatch):
    workspace = _workspace()
    workspace_config.set_cloud_credential(None, workspace, "typesafe", api_key="workspace-key")
    monkeypatch.setenv("TYPESAFE_API_KEY", "environment-key")
    requests = []

    def handler(request):
        requests.append(request)
        assert request.method == "GET"
        assert str(request.url) == "https://api.typesafe.ai/v1/models"
        assert request.headers["authorization"] == "Bearer workspace-key"
        return httpx.Response(
            200,
            json={
                "models": [
                    {"name": "jev-latest", "description": "Jev", "release_date": "2026-09-15"}
                ]
            },
        )

    _mock_http(monkeypatch, handler)
    rows = await providers.list_providers(
        workspace=workspace, provider_key="typesafe", include_local_serving=False
    )
    row = rows[0]
    assert row["status"] == "active" and row["models"] == ["jev-latest"]
    assert row["credential_source"] == "workspace"
    assert row["models_source"] == "provider_catalog" and row["generation_verified"] is False
    assert "workspace-key" not in str(row) and "environment-key" not in str(row)
    await providers.list_providers(
        workspace=workspace, provider_key="typesafe", include_local_serving=False
    )
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,payload",
    [
        (200, {"models": []}),
        (200, {"models": [{"name": 1}]}),
        (401, {"detail": "private token"}),
        (302, {}),
    ],
)
async def test_connected_failure_or_empty_catalog_never_fabricates_models(
    monkeypatch, status, payload
):
    monkeypatch.setenv("TYPESAFE_API_KEY", "environment-key")
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(
            status, json=payload, headers={"Location": "https://untrusted.example"}
        )

    _mock_http(monkeypatch, handler)
    row = (
        await providers.list_providers(
            workspace=_workspace(), provider_key="typesafe", include_local_serving=False
        )
    )[0]
    assert row["models"] == []
    assert len(requests) == 1
    assert "private token" not in str(row)
    assert row["status"] == (
        "active" if status == 200 and payload == {"models": []} else "unreachable"
    )


@pytest.mark.asyncio
async def test_unreadable_workspace_credential_does_not_fall_back_to_environment(monkeypatch):
    workspace = _workspace()
    workspace_config.set_cloud_credential(None, workspace, "typesafe", api_key="workspace-key")
    monkeypatch.setenv("LLM_PORTAL_FERNET_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("TYPESAFE_API_KEY", "environment-key")

    def forbidden(request):
        pytest.fail("an unreadable workspace credential cannot use the environment account")

    _mock_http(monkeypatch, forbidden)
    row = (
        await providers.list_providers(
            workspace=workspace, provider_key="typesafe", include_local_serving=False
        )
    )[0]
    assert row["status"] == "unreachable"
    assert row["credential_source"] == "workspace"
    assert row["models"] == []


@pytest.mark.asyncio
async def test_model_rows_keep_typed_capability_out_of_text_selection(monkeypatch):
    async def catalog(**kwargs):
        return [
            {
                "key": "typesafe",
                "status": "active",
                "configured": True,
                "models_source": "provider_catalog",
                "runtime_available": False,
                "capabilities": ["typed_decisions"],
                "typed_decisions_available": True,
                "credential_source": "workspace",
                "models": ["jev-1.13.0"],
            }
        ]

    monkeypatch.setattr(providers, "list_providers", catalog)
    row = (await providers.list_models(workspace=_workspace()))[0]
    assert row["id"] == "typesafe:jev-1.13.0"
    assert row["compatibility"] == "typed_decisions"
    assert row["compatibility_source"] == "provider_contract"
    assert row["typed_decisions_available"] is True and row["runtime_available"] is False
    assert row["discovered"] and not row["generation_verified"]
    assert "typesafe" not in providers.RUNTIME_PROVIDERS


@pytest.mark.parametrize(
    "provider,model,fallbacks,routes",
    [
        ("typesafe", "jev-1.13.0", [], {}),
        ("openai", "gpt-5", ["typesafe"], {}),
        ("openai", "gpt-5", [], {"judge": {"provider": "typesafe", "model": "jev-1.13.0"}}),
    ],
)
def test_text_routing_cannot_admit_typesafe(provider, model, fallbacks, routes):
    workspace = _workspace()
    with pytest.raises(ValueError):
        workspace_config.set_routing(
            None,
            workspace,
            default_provider=provider,
            default_model=model,
            fallback_chain=fallbacks,
            named_routes=routes,
        )
    assert workspace.settings == {}
