"""Adaptive generation budget (RAGGER Eq. 15 + Annexe C.5).

Allocates ``max_output_tokens`` from the context-to-window ratio
``ρ = input_tokens / model_window`` using the paper's schedule, then applies
the safety clamp the paper omits (the schedule alone can overflow small
windows): ``min(tier, window − input − margin)``, floored at 512, capped per
latency profile so long generations never inflate the interactive stream.

Also centralises the model context-window lookup, which had no single source
of truth in the codebase. Token counting reuses ``count_tokens`` (tiktoken
with a chars/4 fallback) — the ±15% encoder mismatch on non-OpenAI models is
acceptable given the wide tiers.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.core.config import settings
from app.core.memory_manager import count_tokens, message_tokens

_SAFETY_MARGIN_TOKENS = 256
_MIN_OUTPUT_TOKENS = 512
_DETAIL_MULTIPLIER = 1.5

# Context windows by model-name prefix (longest prefix wins). Single source
# of truth; extend as models are onboarded.
MODEL_CONTEXT_WINDOWS: dict[str, int] = {
    "gpt-5": 272_000,
    "gpt-4.1": 1_000_000,
    "gpt-4o": 128_000,
    "gpt-4-turbo": 128_000,
    "gpt-4": 8_192,
    "gpt-3.5": 16_385,
    "o1": 200_000,
    "o3": 200_000,
    "claude": 200_000,
    "qwen3": 32_768,
    "qwen2": 32_768,
    "llama3": 8_192,
    "llama-3": 8_192,
    "mistral": 32_768,
    "gemma": 8_192,
    "phi-3": 4_096,
    "deepseek": 64_000,
}

# (rho upper bound, max new tokens) — paper Annexe C.5.
_RHO_SCHEDULE: tuple[tuple[float, int], ...] = (
    (0.40, 8192),
    (0.55, 7168),
    (0.625, 6144),
    (0.70, 5120),
    (0.78, 4096),
    (0.86, 3072),
    (0.94, 2560),
    (1.0, 2048),
)


@dataclass(frozen=True)
class GenerationBudget:
    max_output_tokens: int
    frequency_penalty: float
    input_tokens: int
    rho: float
    model_window: int
    diagnostics: dict[str, Any] = field(default_factory=dict)


def model_context_window(model: str | None) -> int:
    name = str(model or "").strip().lower()
    best: int | None = None
    best_len = -1
    for prefix, window in MODEL_CONTEXT_WINDOWS.items():
        if name.startswith(prefix) and len(prefix) > best_len:
            best = window
            best_len = len(prefix)
    if best is not None:
        return best
    try:
        fallback = int(getattr(settings, "ollama_default_num_ctx", 0) or 0)
    except (TypeError, ValueError):
        fallback = 0
    return fallback if fallback > 0 else 8_192


def _profile_cap(latency_profile: str | None) -> int:
    profile = str(latency_profile or "").strip().lower()
    if profile == "deep":
        return max(_MIN_OUTPUT_TOKENS, int(settings.rag_generation_max_output_cap_deep))
    if profile == "balanced":
        return max(_MIN_OUTPUT_TOKENS, int(settings.rag_generation_max_output_cap_balanced))
    return max(_MIN_OUTPUT_TOKENS, int(settings.rag_generation_max_output_cap_fast))


def _frequency_penalty(input_tokens: int) -> float:
    if input_tokens <= 512:
        return 0.01
    if input_tokens <= 1024:
        return 0.05
    return 0.10


def resolve_generation_budget(
    *,
    system_prompt: str | None,
    user_prompt: str,
    history: list[dict[str, str]] | None,
    model: str | None,
    latency_profile: str | None = None,
    wants_more_detail: bool = False,
) -> GenerationBudget:
    input_tokens = count_tokens(system_prompt or "") + count_tokens(user_prompt or "")
    for message in history or []:
        input_tokens += message_tokens(message)

    window = model_context_window(model)
    rho = min(1.0, input_tokens / max(1, window))

    tier = _RHO_SCHEDULE[-1][1]
    for bound, tokens in _RHO_SCHEDULE:
        if rho < bound:
            tier = tokens
            break

    if wants_more_detail:
        tier = int(tier * _DETAIL_MULTIPLIER)

    cap = _profile_cap(latency_profile)
    # Safety clamp the paper omits: never request more than the window can
    # actually hold past the input.
    available = window - input_tokens - _SAFETY_MARGIN_TOKENS
    max_output = max(_MIN_OUTPUT_TOKENS, min(tier, cap, max(_MIN_OUTPUT_TOKENS, available)))

    return GenerationBudget(
        max_output_tokens=max_output,
        frequency_penalty=_frequency_penalty(input_tokens),
        input_tokens=input_tokens,
        rho=round(rho, 4),
        model_window=window,
        diagnostics={
            "generation_budget_status": "adaptive",
            "generation_rho": round(rho, 4),
            "generation_input_tokens": input_tokens,
            "generation_max_output_tokens": max_output,
            "generation_model_window": window,
            "generation_profile_cap": cap,
            "generation_wants_more_detail": bool(wants_more_detail),
        },
    )
