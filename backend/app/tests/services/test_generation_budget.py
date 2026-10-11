import pytest

from app.services.rag import generation_budget as gb
from app.services.rag.generation_budget import (
    model_context_window,
    resolve_generation_budget,
)


@pytest.fixture(autouse=True)
def _chars_over_4_tokens(monkeypatch):
    # Pin the chars/4 fallback so assertions don't depend on whether tiktoken
    # is installed (its BPE counts runs of repeated chars very differently).
    monkeypatch.setattr(gb, "count_tokens", lambda text: len(text or "") // 4)
    monkeypatch.setattr(
        gb,
        "message_tokens",
        lambda message: len(str(message.get("content", ""))) // 4 + 4,
    )


def _budget(input_chars: int, *, model="gpt-4o", profile="balanced", detail=False):
    return resolve_generation_budget(
        system_prompt="s" * 100,
        user_prompt="u" * input_chars,
        history=[],
        model=model,
        latency_profile=profile,
        wants_more_detail=detail,
    )


def test_model_window_lookup_longest_prefix_and_fallbacks():
    assert model_context_window("gpt-4o-mini") == 128_000
    assert model_context_window("gpt-4") == 8_192
    assert model_context_window("gpt-4-turbo-2024") == 128_000
    assert model_context_window("qwen3:8b") == 32_768
    # Unknown model → ollama_default_num_ctx (32768) fallback.
    assert model_context_window("totally-unknown") == 32_768


def test_small_input_gets_top_tier_capped_by_profile():
    budget = _budget(400, profile="deep")
    assert budget.rho < 0.40
    assert budget.max_output_tokens == 8192  # deep cap

    balanced = _budget(400, profile="balanced")
    assert balanced.max_output_tokens == 4096  # profile cap below the 8192 tier

    fast = _budget(400, profile="fast")
    assert fast.max_output_tokens == 2048


def test_rho_tiers_shrink_output():
    # gpt-4 window = 8192; ~6000 input tokens → rho ≈ 0.73 → 4096 tier,
    # then window clamp: 8192 - 6025 - 256 ≈ 1911 → floor at... above 512.
    budget = _budget(24_000, model="gpt-4", profile="deep")
    assert 0.70 < budget.rho < 0.78
    assert budget.max_output_tokens < 4096
    assert budget.max_output_tokens >= 512


def test_window_clamp_never_overflows():
    budget = _budget(31_000, model="gpt-4", profile="deep")  # input ≈ window
    assert budget.input_tokens + budget.max_output_tokens <= budget.model_window + 512


def test_wants_more_detail_multiplies_within_caps():
    base = _budget(400, profile="deep", detail=False)
    detailed = _budget(400, profile="deep", detail=True)
    assert detailed.max_output_tokens >= base.max_output_tokens


def test_frequency_penalty_scales_with_input():
    assert _budget(100).frequency_penalty == 0.01
    assert _budget(3000).frequency_penalty == 0.05
    assert _budget(10_000).frequency_penalty == 0.10


def test_history_counts_toward_input():
    with_history = resolve_generation_budget(
        system_prompt="s",
        user_prompt="u",
        history=[{"role": "user", "content": "x" * 4000}],
        model="gpt-4o",
        latency_profile="balanced",
    )
    without = resolve_generation_budget(
        system_prompt="s",
        user_prompt="u",
        history=[],
        model="gpt-4o",
        latency_profile="balanced",
    )
    assert with_history.input_tokens > without.input_tokens
