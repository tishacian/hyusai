"""Unit tests for the model_plane service (no live llm-portal / cloud calls)."""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from app.models.run import Run, SkillInvocation
from app.models.workspace import Workspace
from app.services.model_plane import distribution as distribution_mod
from app.services.model_plane import providers as providers_mod
from app.services.model_plane import registration as registration_mod
from app.services.model_plane import serving_nodes as serving_nodes_mod
from app.services.model_plane import workspace_config as workspace_config_mod
from app.services.model_plane.errors import classify_provider_error
from app.services.model_router import ModelRouter


def _http_status_error(status_code: int, body: str = "") -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "http://internal-provider.local/v1/models?key=secret")
    response = httpx.Response(status_code, request=request, text=body)
    return httpx.HTTPStatusError(
        f"upstream returned {status_code}: {body}",
        request=request,
        response=response,
    )


@pytest.mark.parametrize(
    ("exc", "code", "retryable"),
    [
        (
            httpx.ConnectError(
                "All connection attempts failed for http://ollama.internal:11434?token=secret",
                request=httpx.Request("POST", "http://ollama.internal:11434/api/chat"),
            ),
            "provider_unreachable",
            True,
        ),
        (httpx.ReadTimeout("slow provider"), "timeout", True),
        (_http_status_error(401, "invalid sk-secret"), "credentials_invalid", False),
        (_http_status_error(404, "model secret-model absent"), "model_missing", False),
        (_http_status_error(429, "quota for secret tenant"), "rate_limited", True),
        (RuntimeError("response body with sk-secret"), "generation_failed", True),
    ],
)
def test_provider_error_classification_is_stable_and_redacted(exc, code, retryable):
    failure = classify_provider_error(exc)

    assert failure.code == code
    assert failure.retryable is retryable
    payload = failure.as_dict()
    assert set(payload) == {"code", "message", "retryable"}
    serialized = str(payload).lower()
    assert "secret" not in serialized
    assert "http://" not in serialized
    assert "traceback" not in serialized


@pytest.mark.asyncio
async def test_provider_probe_returns_only_safe_classified_error(monkeypatch):
    class FailedClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def request(self, *_args, **_kwargs):
            raise httpx.ConnectError(
                "refused http://provider.internal?api_key=sk-secret",
                request=httpx.Request("GET", "http://provider.internal"),
            )

    monkeypatch.setattr(providers_mod.httpx, "AsyncClient", FailedClient)
    result = await providers_mod._probe(method="GET", url="http://provider.internal")

    assert result["status"] == "unreachable"
    assert result["error_code"] == "provider_unreachable"
    assert result["retryable"] is True
    assert result["models_verified"] is False
    assert "internal" not in result["error"]
    assert "secret" not in result["error"]


@pytest.mark.asyncio
async def test_readiness_uses_only_selected_ollama_and_live_model(monkeypatch):
    workspace = SimpleNamespace(
        settings={
            "llm_portal": {
                "routing": {
                    "default_provider": "ollama",
                    "default_model": "qwen3:8b",
                }
            }
        }
    )

    async def fake_ollama():
        return {
            "status": "active",
            "latency_ms": 3.0,
            "models": ["qwen3:8b"],
            "error": None,
        }

    monkeypatch.setattr(providers_mod, "_health_ollama", fake_ollama)
    readiness = await providers_mod.get_readiness(workspace=workspace)

    assert readiness == {
        "provider": "ollama",
        "model": "qwen3:8b",
        "source": "workspace",
        "status": "ready",
        "reason": "ready",
        "message": "The selected provider and model are ready.",
        "retryable": False,
        "provider_status": "active",
    }


@pytest.mark.asyncio
async def test_readiness_reports_stopped_ollama_as_unavailable(monkeypatch):
    workspace = SimpleNamespace(
        settings={
            "llm_portal": {
                "routing": {
                    "default_provider": "ollama",
                    "default_model": "qwen3:8b",
                }
            }
        }
    )

    async def stopped_ollama():
        return {
            "status": "unreachable",
            "latency_ms": 1.0,
            "models": [],
            "error": "All connection attempts failed at http://ollama.internal:11434",
            "error_code": "provider_unreachable",
            "retryable": True,
        }

    monkeypatch.setattr(providers_mod, "_health_ollama", stopped_ollama)
    readiness = await providers_mod.get_readiness(workspace=workspace)

    assert readiness["status"] == "unavailable"
    assert readiness["reason"] == "provider_unreachable"
    assert readiness["retryable"] is True
    assert "http://" not in readiness["message"]
    assert "All connection attempts failed" not in readiness["message"]


@pytest.mark.asyncio
async def test_readiness_never_promotes_catalog_fallback_to_verified_model(monkeypatch):
    workspace = SimpleNamespace(
        settings={
            "llm_portal": {
                "routing": {
                    "default_provider": "ollama",
                    "default_model": "qwen3:8b",
                }
            }
        }
    )

    async def empty_ollama():
        return {
            "status": "active",
            "latency_ms": 2.0,
            # Catalog fallback/display hint: not evidence from the probe.
            "models": ["qwen3:8b"],
            "models_verified": False,
            "error": None,
        }

    monkeypatch.setattr(providers_mod, "_health_ollama", empty_ollama)
    readiness = await providers_mod.get_readiness(workspace=workspace)

    assert readiness["status"] == "needs_setup"
    assert readiness["reason"] == "model_missing"


@pytest.mark.asyncio
async def test_readiness_checks_only_selected_unconfigured_provider(monkeypatch):
    workspace = SimpleNamespace(
        settings={
            "llm_portal": {
                "routing": {
                    "default_provider": "openai",
                    "default_model": "gpt-5",
                }
            }
        }
    )
    monkeypatch.setattr(providers_mod.settings, "openai_api_key", "")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    async def forbidden_ollama_probe():
        raise AssertionError("readiness must not probe a fallback provider")

    monkeypatch.setattr(providers_mod, "_health_ollama", forbidden_ollama_probe)
    readiness = await providers_mod.get_readiness(workspace=workspace)

    assert readiness["provider"] == "openai"
    assert readiness["model"] == "gpt-5"
    assert readiness["status"] == "needs_setup"
    assert readiness["reason"] == "provider_not_configured"


def test_parse_serving_nodes_empty_is_first_class():
    assert serving_nodes_mod.parse_serving_nodes("") == []
    assert serving_nodes_mod.parse_serving_nodes("   ") == []
    assert serving_nodes_mod.parse_serving_nodes("[]") == []


def test_parse_serving_nodes_json():
    raw = (
        '[{"name":"gpu-lab","base_url":"http://10.0.0.5:9000/","token":"s3cret"},'
        '{"name":"bad"},'
        '{"name":"cpu","base_url":"http://127.0.0.1:9001","token":""}]'
    )
    nodes = serving_nodes_mod.parse_serving_nodes(raw)
    assert [n.name for n in nodes] == ["gpu-lab", "cpu"]
    assert nodes[0].base_url == "http://10.0.0.5:9000"
    assert nodes[0].token == "s3cret"


def test_auth_headers_align_with_llm_portal():
    headers = serving_nodes_mod._auth_headers("tok-abc")
    assert headers["Authorization"] == "Bearer tok-abc"
    assert headers["X-LLM-Portal-Token"] == "tok-abc"
    assert "X-Portal-Token" not in headers
    assert serving_nodes_mod._auth_headers("") == {"Accept": "application/json"}


def test_normalize_gpu_from_portal_shape():
    raw = {
        "available": True,
        "total_count": 1,
        "gpus": [
            {
                "index": 0,
                "name": "RTX",
                "memory": {"total": 8 * 1024 * 1024 * 1024, "used": 2 * 1024 * 1024 * 1024},
                "utilization": {"gpu": 40, "memory": 10},
            }
        ],
    }
    gpu = serving_nodes_mod.normalize_gpu(raw)
    assert gpu["count"] == 1
    assert gpu["memory_total_mb"] == 8192
    assert gpu["memory_used_mb"] == 2048
    assert gpu["utilization"] == 40.0
    assert gpu["devices"][0]["name"] == "RTX"


def test_normalize_instance_engine_alias():
    inst = serving_nodes_mod.normalize_instance(
        {
            "id": "i1",
            "provider": "ollama",
            "model": "llama3.2:3b",
            "status": "running",
            "port": 11434,
        }
    )
    assert inst["provider"] == "ollama"
    assert inst["engine"] == "ollama"
    assert inst["status"] == "running"


@pytest.mark.asyncio
async def test_list_nodes_zero_state(monkeypatch):
    monkeypatch.setattr(serving_nodes_mod, "parse_serving_nodes", lambda *a, **k: [])
    payload = await serving_nodes_mod.list_nodes()
    assert payload["empty"] is True
    assert payload["nodes"] == []
    assert "No serving node" in payload["message"]


@pytest.mark.asyncio
async def test_list_providers_available_without_keys(monkeypatch):
    providers_mod.clear_health_cache()
    registration_mod.clear_routable_providers()
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_ENDPOINT", raising=False)

    async def fake_ollama():
        return {
            "status": "unreachable",
            "latency_ms": 12.0,
            "models": [],
            "error": "connection refused",
        }

    monkeypatch.setattr(providers_mod, "_health_ollama", fake_ollama)
    items = await providers_mod.list_providers(include_local_serving=True)
    by_key = {item["key"]: item for item in items}
    assert by_key["openai"]["status"] == "available"
    assert by_key["anthropic"]["status"] == "available"
    assert by_key["ollama"]["status"] == "unreachable"
    assert "latency_ms" in by_key["ollama"]


@pytest.mark.asyncio
async def test_list_providers_active_from_probe(monkeypatch):
    providers_mod.clear_health_cache()
    registration_mod.clear_routable_providers()
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    async def fake_probe(**kwargs):
        return {
            "status": "active",
            "latency_ms": 42.5,
            "models": ["gpt-5", "gpt-4o-mini"],
            "error": None,
        }

    monkeypatch.setattr(providers_mod, "_probe", fake_probe)
    # Keep other configured probes quiet
    for name in (
        "_health_ollama",
        "_health_azure",
        "_health_openrouter",
        "_health_anthropic",
        "_health_gemini",
    ):

        async def _available():
            return {"status": "available", "latency_ms": None, "models": [], "error": None}

        monkeypatch.setattr(providers_mod, name, _available)

    items = await providers_mod.list_providers(include_local_serving=False)
    openai = next(item for item in items if item["key"] == "openai")
    assert openai["status"] == "active"
    assert openai["models"] == ["gpt-5", "gpt-4o-mini"]
    assert openai["latency_ms"] == 42.5


def test_registration_sync_and_model_router(monkeypatch):
    registration_mod.clear_routable_providers()
    nodes = [
        {
            "name": "lab",
            "base_url": "http://gpu.local:9000",
            "status": "active",
            "instances": [
                {
                    "id": "abc123def",
                    "name": "vllm-qwen",
                    "provider": "vllm",
                    "model": "Qwen/Qwen2.5-0.6B-Instruct",
                    "port": 11001,
                    "status": "running",
                },
                {
                    "id": "stopped1",
                    "name": "idle",
                    "provider": "vllm",
                    "model": "x",
                    "port": 11002,
                    "status": "stopped",
                },
            ],
        }
    ]
    registered = registration_mod.sync_from_node_snapshots(nodes)
    assert len(registered) == 1
    meta = registered[0]
    assert meta["kind"] == "local"
    assert meta["openai_base_url"] == "http://gpu.local:11001/v1"
    assert meta["key"].startswith("serving_lab_")

    class FakeOpenAIClient:
        def __init__(self, api_key=None, base_url="https://api.openai.com/v1"):
            self.api_key = api_key
            self.base_url = base_url

    monkeypatch.setattr(
        "app.services.model_clients.openai_client.OpenAIClient",
        FakeOpenAIClient,
    )
    monkeypatch.setattr(
        "app.services.model_clients.ollama_client.OllamaClient",
        lambda base_url=None: SimpleNamespace(base_url=base_url),
    )
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    router = ModelRouter()
    assert meta["key"] in router.clients
    assert router.clients[meta["key"]].base_url == "http://gpu.local:11001/v1"


def test_split_effective_model():
    assert distribution_mod.split_effective_model("openai:gpt-5") == ("openai", "gpt-5")
    assert distribution_mod.split_effective_model("gpt-4o-mini") == ("openai", "gpt-4o-mini")
    assert distribution_mod.split_effective_model("claude-3-5-sonnet") == (
        "anthropic",
        "claude-3-5-sonnet",
    )
    assert distribution_mod.split_effective_model("qwen3:8b") == ("unknown", "qwen3:8b")


def test_distribution_aggregation(db_session):
    workspace_id = str(uuid4())
    run = Run(
        id=str(uuid4()),
        workspace_id=workspace_id,
        status="completed",
        started_at=datetime.utcnow(),
    )
    db_session.add(run)
    db_session.flush()

    now = datetime.utcnow()
    db_session.add_all(
        [
            SkillInvocation(
                id=str(uuid4()),
                run_id=run.id,
                status="completed",
                started_at=now - timedelta(days=1),
                latency_ms=100.0,
                cost=0.02,
                cost_measured=True,
                metrics={"cost_evidence": {"state": "calculated", "method": "catalog_unit_price", "currency": "USD"}},
                trace={"effective_model": "openai:gpt-5"},
            ),
            SkillInvocation(
                id=str(uuid4()),
                run_id=run.id,
                status="completed",
                started_at=now - timedelta(days=2),
                latency_ms=200.0,
                cost=0.01,
                cost_measured=True,
                metrics={"cost_evidence": {"state": "calculated", "method": "catalog_unit_price", "currency": "USD"}},
                trace={"effective_model": "openai:gpt-5"},
            ),
            SkillInvocation(
                id=str(uuid4()),
                run_id=run.id,
                status="completed",
                started_at=now - timedelta(days=3),
                latency_ms=50.0,
                cost=0.0,
                trace={"effective_model": "ollama:qwen3:8b"},
            ),
            # Outside window
            SkillInvocation(
                id=str(uuid4()),
                run_id=run.id,
                status="completed",
                started_at=now - timedelta(days=40),
                latency_ms=10.0,
                cost=9.0,
                trace={"effective_model": "openai:gpt-5"},
            ),
        ]
    )
    db_session.commit()

    payload = distribution_mod.get_distribution(
        db_session,
        workspace_id=workspace_id,
        window="7d",
    )
    assert payload["totals"]["invocations"] == 3
    assert payload["totals"]["cost"] == pytest.approx(0.03)
    by_model = {(row["provider"], row["model"]): row for row in payload["by_model"]}
    assert by_model[("openai", "gpt-5")]["invocations"] == 2
    assert by_model[("openai", "gpt-5")]["avg_latency_ms"] == pytest.approx(150.0)
    # ollama:qwen3:8b — head "ollama" is known, model is "qwen3:8b"
    assert ("ollama", "qwen3:8b") in by_model


def test_build_llm_uses_vllm_factory(monkeypatch):
    registration_mod.clear_routable_providers()
    registration_mod.sync_from_node_snapshots(
        [
            {
                "name": "n1",
                "base_url": "http://127.0.0.1:9000",
                "status": "active",
                "instances": [
                    {
                        "id": "i1",
                        "name": "local",
                        "provider": "vllm",
                        "model": "m",
                        "port": 8000,
                        "status": "running",
                    }
                ],
            }
        ]
    )
    meta = registration_mod.list_routable_providers()[0]

    captured = {}

    class FakeLLM:
        def __init__(self, provider, api_key=None, base_url=None, **kwargs):
            captured["provider"] = provider
            captured["api_key"] = api_key
            captured["base_url"] = base_url

    monkeypatch.setattr("app.llm.LLM", FakeLLM)
    registration_mod.build_llm(provider_meta=meta)
    assert captured["provider"] == "vllm"
    assert captured["base_url"] == "http://127.0.0.1:8000/v1"


def test_model_router_uses_workspace_anthropic_credential(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(
        workspace_config_mod,
        "get_runtime_provider_config",
        lambda workspace_id, provider: (
            {"api_key": "sk-ant-workspace"}
            if workspace_id == "ws-anthropic" and provider == "anthropic"
            else {}
        ),
    )

    router = ModelRouter(workspace_id="ws-anthropic")

    assert "anthropic" in router.clients
    assert router.clients["anthropic"].api_key == "sk-ant-workspace"
    assert router.clients["anthropic"].base_url == router.clients["anthropic"].DEFAULT_BASE_URL


def test_runtime_provider_config_reads_secret_without_exposing_it_publicly(db_session):
    workspace = Workspace(
        id="ws-runtime-secret",
        name="Runtime Secret",
        slug="runtime-secret",
        settings={},
    )
    db_session.add(workspace)
    db_session.commit()
    workspace_config_mod.set_cloud_credential(
        db_session,
        workspace,
        "anthropic",
        api_key="sk-ant-runtime",
    )

    runtime = workspace_config_mod.get_runtime_provider_config(workspace.id, "anthropic")
    public = workspace_config_mod.get_cloud_credentials_public(workspace)

    assert runtime == {"api_key": "sk-ant-runtime"}
    assert next(row for row in public if row["key"] == "anthropic") == {
        "key": "anthropic",
        "api_key_set": True,
    }
    assert "sk-ant-runtime" not in str(public)


def test_omnirag_uses_workspace_key_and_refreshes_after_rotation(monkeypatch):
    from app.agents.procurement_agent import OmniRAGAgent

    current_key = {"value": "sk-ant-first"}
    created: list[tuple[str, str | None, str | None]] = []

    class FakeLLM:
        def __init__(self, provider, api_key=None, base_url=None, **_kwargs):
            created.append((provider, api_key, base_url))

    monkeypatch.setattr("app.llm.llm.LLM", FakeLLM)
    monkeypatch.setattr(
        workspace_config_mod,
        "get_runtime_provider_config",
        lambda workspace_id, provider: (
            {"api_key": current_key["value"]}
            if workspace_id == "ws-anthropic" and provider == "anthropic"
            else {}
        ),
    )
    agent = OmniRAGAgent()

    first = agent._get_llm("anthropic", workspace_id="ws-anthropic")
    again = agent._get_llm("anthropic", workspace_id="ws-anthropic")
    current_key["value"] = "sk-ant-rotated"
    rotated = agent._get_llm("anthropic", workspace_id="ws-anthropic")

    assert first is again
    assert rotated is not first
    assert created == [
        ("anthropic", "sk-ant-first", "https://api.anthropic.com"),
        ("anthropic", "sk-ant-rotated", "https://api.anthropic.com"),
    ]
