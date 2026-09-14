from __future__ import annotations

import pytest

from app.llm.models import CompletionRequest, TokenUsage
from app.llm.providers.anthropic_provider import AnthropicProvider


def _request(model: str, *, temperature: float = 0.3) -> CompletionRequest:
    return CompletionRequest(
        model=model,
        messages=[{"role": "user", "content": "Hello"}],
        temperature=temperature,
        max_tokens=2048,
    )


@pytest.mark.parametrize(
    "model",
    [
        "claude-opus-4-7",
        "claude-opus-4-8",
        "claude-opus-5",
        "claude-sonnet-5",
        "claude-fable-5-1",
    ],
)
def test_current_anthropic_models_omit_deprecated_temperature(model):
    provider = AnthropicProvider(api_key="sk-ant-test")

    params = provider._prepare_api_params(_request(model))

    assert "temperature" not in params


def test_older_anthropic_models_keep_workspace_temperature():
    provider = AnthropicProvider(api_key="sk-ant-test")

    params = provider._prepare_api_params(_request("claude-3-5-sonnet"))

    assert params["temperature"] == pytest.approx(0.3)


def test_installed_sdk_filters_removed_sampling_parameters():
    provider = AnthropicProvider(api_key="sk-ant-test")

    params = provider._supported_api_params(provider._prepare_api_params(_request("claude-opus-5")))

    assert "temperature" not in params
    assert "top_p" not in params


def test_opus_5_usage_uses_current_pricing():
    provider = AnthropicProvider(api_key="sk-ant-test")
    usage = TokenUsage(
        prompt_tokens=1000,
        completion_tokens=1000,
        total_tokens=2000,
    )

    priced = provider._calculate_costs(usage, "claude-opus-5")

    assert priced.prompt_cost == pytest.approx(0.005)
    assert priced.completion_cost == pytest.approx(0.025)
    assert priced.total_cost == pytest.approx(0.03)
