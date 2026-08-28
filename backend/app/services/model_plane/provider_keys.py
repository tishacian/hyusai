"""Canonical LLM provider keys shared by the portal, router, and flow chips.

Three vocabularies used to coexist (`azure` on the skill, `azure_openai` on
the portal, `openai` after a silent remap). One function owns the alias so
the inspector, the trace, and health cannot disagree.
"""

from __future__ import annotations

from typing import Any, Optional

PORTAL_PROVIDERS = (
    "ollama",
    "openai",
    "azure_openai",
    "azure_foundry",
    "openrouter",
    "anthropic",
    "gemini",
)

PROVIDER_ALIASES = {
    "azure": "azure_openai",
}

_OPENAI_MODEL_PREFIXES = ("gpt", "o1", "o3", "o4", "chatgpt", "text-", "davinci")


def canonical_provider(key: str) -> str:
    raw = (key or "").strip().lower()
    return PROVIDER_ALIASES.get(raw, raw)


def is_known_provider(key: str) -> bool:
    resolved = canonical_provider(key)
    return resolved in PORTAL_PROVIDERS or resolved.startswith("serving_")


def preferences_from_model(
    model: Optional[str],
    *,
    default_provider: str,
    default_model: str,
) -> dict[str, Any]:
    """Map a (possibly provider-prefixed) model string to router prefs."""

    provider = canonical_provider(default_provider or "ollama")
    fallback_model = (default_model or "").strip()
    raw = (model or "").strip()
    if not raw:
        return {"provider": provider, "model": fallback_model}
    for sep in (":", "/"):
        if sep in raw:
            head, tail = raw.split(sep, 1)
            if is_known_provider(head) and tail.strip():
                return {
                    "provider": canonical_provider(head),
                    "model": tail.strip(),
                }
    if raw.lower().startswith(_OPENAI_MODEL_PREFIXES):
        return {"provider": "openai", "model": raw}
    return {"provider": provider, "model": raw}
