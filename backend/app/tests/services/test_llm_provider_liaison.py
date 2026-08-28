"""Provider keys, flow consumers, and workspace-aware routing."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services.model_plane.flow_consumers import (
    consumers_for_systems,
    schema_is_completion_shaped,
    skill_is_completion_shaped,
)
from app.services.model_plane.provider_keys import (
    canonical_provider,
    preferences_from_model,
)
from app.services.model_router import ModelRouter
from app.services.skills_registry import wrappers


def test_azure_alias_is_the_portal_key():
    assert canonical_provider("azure") == "azure_openai"
    assert preferences_from_model(
        "azure:gpt-4o-mini",
        default_provider="ollama",
        default_model="x",
    ) == {"provider": "azure_openai", "model": "gpt-4o-mini"}
    assert wrappers._resolve_model_preferences("azure:gpt-4o-mini")["provider"] == (
        "azure_openai"
    )


def test_completion_shaped_is_prompt_or_template_not_category():
    assert schema_is_completion_shaped(
        {"properties": {"prompt": {"type": "string"}, "model": {"type": "string"}}}
    )
    assert schema_is_completion_shaped({"properties": {"template": {"type": "string"}}})
    assert not schema_is_completion_shaped(
        {"properties": {"query": {"type": "string"}, "model": {"type": "string"}}}
    )
    assert skill_is_completion_shaped("azure_llm_v1", {"properties": {"query": {}}})
    assert not skill_is_completion_shaped(
        "llm_rag_answer_v1",
        {"properties": {"query": {"type": "string"}}},
    )


def test_consumers_include_completion_nodes_not_just_system_default():
    system = SimpleNamespace(
        id="sys-1",
        name="Churn Radar",
        default_model=None,
        status="active",
        flow_definition={
            "nodes": [
                {
                    "id": "task.brief",
                    "kind": "task",
                    "label": "Retention brief",
                    "config": {"skill_slug": "azure_llm_v1", "params": {"prompt": "x"}},
                },
                {
                    "id": "task.score",
                    "kind": "task",
                    "config": {"skill_slug": "ml_batch_score_v1"},
                },
            ]
        },
    )
    rows = consumers_for_systems(
        [system],
        schemas_by_slug={},
        default_provider="ollama",
        default_model="llama3",
    )
    assert rows[0]["nodes"] == [
        {
            "node_id": "task.brief",
            "label": "Retention brief",
            "skill_slug": "azure_llm_v1",
            "model": "gpt-4o-mini",
            "provider": "openai",
        }
    ]


@pytest.mark.asyncio
async def test_workspace_api_key_wins_over_env(monkeypatch):
    from app.services.model_plane import workspace_config as ws_cfg

    monkeypatch.setenv("OPENAI_API_KEY", "sk-env")
    ws = SimpleNamespace(
        id=str(uuid4()),
        settings={
            "llm_portal": {
                "cloud_credentials": {
                    "openai": {"api_key_encrypted": ws_cfg.encrypt_secret("sk-workspace")},
                },
                "routing": {
                    "default_provider": "openai",
                    "default_model": "gpt-4o-mini",
                    "fallback_chain": ["openai"],
                },
            }
        },
    )
    seen: list[str] = []

    class _Client:
        api_key = "sk-workspace"

        def __init__(self, api_key=None, base_url="https://api.openai.com/v1", **_k):
            self.api_key = api_key
            seen.append(api_key or "")

        async def health_check(self):
            return True

        async def generate(self, **_k):
            return {"content": "ok"}

    monkeypatch.setattr(
        "app.services.model_clients.openai_client.OpenAIClient",
        _Client,
    )
    router = ModelRouter()
    router.apply_workspace(ws)
    client = await router.get_client({"provider": "openai", "model": "gpt-4o-mini"})
    assert client.api_key == "sk-workspace"
    assert router.credential_sources["openai"] == "workspace"
    assert router.last_route["credential_source"] == "workspace"
    assert "sk-workspace" in seen


@pytest.mark.asyncio
async def test_empty_workspace_portal_keeps_the_env_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env")
    ws = SimpleNamespace(id=str(uuid4()), settings={})

    class _Client:
        def __init__(self, api_key=None, **_k):
            self.api_key = api_key

        async def health_check(self):
            return True

        async def generate(self, **_k):
            return {"content": "ok"}

    monkeypatch.setattr(
        "app.services.model_clients.openai_client.OpenAIClient",
        _Client,
    )
    router = ModelRouter()
    router.apply_workspace(ws)
    client = await router.get_client({"provider": "openai", "model": "gpt-4o-mini"})
    assert client.api_key == "sk-env"
    assert router.credential_sources["openai"] == "env"
    assert router.last_route["credential_source"] == "env"


def test_azure_llm_seed_schema_is_still_prompt_and_optional_model():
    from app.services.skills_registry.seed import SEED_SKILLS

    by_slug = {entry["slug"]: entry for entry in SEED_SKILLS}
    schema = by_slug["azure_llm_v1"]["input_schema"]
    assert schema["required"] == ["prompt"]
    assert set(schema["properties"]) == {"prompt", "model"}
    assert "provider" not in schema["properties"]
    assert "temperature" not in schema["properties"]
