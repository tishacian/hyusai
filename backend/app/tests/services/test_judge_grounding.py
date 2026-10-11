"""Unit tests for the grounded, provider-neutral LLM-as-Judge (Phase 1).

Covers the three Phase 1 judge fixes in
``app.services.evaluation.judge.JudgeService``:

* **Context injection** — ``evaluate`` renders the retrieved chunks into the
  prompt (``## Retrieved context excerpts``) instead of the old boolean
  ``Retrieved context available: yes/no``, and truncates the response to 4000
  chars (was 2000).
* **Provider-neutral routing** — the completion is resolved through
  ``ModelRouter`` using ``settings.judge_model or settings.default_model`` on
  ``settings.default_provider`` (never the old hardcoded ``gpt-4o`` / OpenAI
  lock), with the router's Ollama fallback honoured.
* **Resilience** — a total routing/model failure still returns the default
  75-per-dimension scores.

All tests use a fake ``ModelRouter`` (never a real provider / network call),
mirroring ``test_chat_agentic_skills.py``.
"""
from __future__ import annotations

import json

from app.core.config import settings
from app.services.evaluation.judge import (
    DIMENSIONS,
    JudgeService,
    _format_context_excerpts,
)

_VALID_COMPLETION = json.dumps(
    {
        "scores": {d: 88 for d in DIMENSIONS},
        "claims": [{"claim": "restates the query", "supported": True}],
        "question_type": "simple",
        "topic": "pump",
        "overall_note": "ok",
    }
)


def _install_recording_router(monkeypatch, *, completion: str = _VALID_COMPLETION,
                              return_key: str = "content") -> dict:
    """Patch ``ModelRouter`` so the judge resolves a fake client.

    Records the resolved ``preferences``, ``model`` and rendered ``prompt`` so a
    test can assert routing + prompt content without any provider/network call.
    ``return_key`` toggles the client return shape (OpenAI ``content`` vs Ollama
    ``response``) to prove the judge normalises both.
    """
    recorded: dict = {}

    class _FakeClient:
        async def generate(self, model: str, prompt: str):
            recorded["model"] = model
            recorded["prompt"] = prompt
            return {return_key: completion}

    class _FakeRouter:
        def __init__(self, *args, **kwargs):
            pass

        async def get_client(self, preferences=None):
            recorded["preferences"] = preferences
            return _FakeClient()

    monkeypatch.setattr("app.services.model_router.ModelRouter", _FakeRouter)
    return recorded


# ---------------------------------------------------------------------------
# Context injection
# ---------------------------------------------------------------------------
async def test_context_chunks_are_injected_into_prompt(monkeypatch):
    recorded = _install_recording_router(monkeypatch)
    svc = JudgeService()

    chunks = [
        "Pump URACA KD724 operates at 250 bar in project BBA120.",
        "Filtering cartridge LM 300 and O-ring string D. 3,6 for AKK200.",
    ]
    await svc.evaluate(query="Quelle pompe ?", response="La pompe URACA.", context_chunks=chunks)

    prompt = recorded["prompt"]
    # The actual chunk text must reach the judge...
    assert "Pump URACA KD724 operates at 250 bar" in prompt
    assert "O-ring string D. 3,6 for AKK200" in prompt
    # ...via the new excerpts section, not the old boolean.
    assert "## Retrieved context excerpts" in prompt
    assert "Retrieved context available" not in prompt


async def test_response_truncation_widened_to_4000(monkeypatch):
    recorded = _install_recording_router(monkeypatch)
    svc = JudgeService()

    # NEEDLE sits past the old 2000 cap but under 4000; FARTAIL sits past 4000.
    response = ("x" * 2500) + "NEEDLE" + ("y" * 2000) + "FARTAIL"
    await svc.evaluate(query="q", response=response, context_chunks=["c"])

    prompt = recorded["prompt"]
    assert "NEEDLE" in prompt  # kept (was dropped under the old 2000 cap)
    assert "FARTAIL" not in prompt  # still truncated at 4000


# ---------------------------------------------------------------------------
# Provider-neutral routing (no hardcoded gpt-4o / OpenAI lock)
# ---------------------------------------------------------------------------
async def test_model_selection_uses_default_model_not_gpt4o(monkeypatch):
    monkeypatch.setattr(settings, "judge_model", "")
    monkeypatch.setattr(settings, "default_model", "gpt-5")
    monkeypatch.setattr(settings, "default_provider", "openai")
    recorded = _install_recording_router(monkeypatch)

    await JudgeService().evaluate(query="q", response="r", context_chunks=["c"])

    assert recorded["model"] == "gpt-5"
    assert recorded["model"] != "gpt-4o"
    assert recorded["preferences"] == {"provider": "openai", "model": "gpt-5"}


async def test_judge_model_override_wins(monkeypatch):
    monkeypatch.setattr(settings, "judge_model", "gpt-5-mini")
    monkeypatch.setattr(settings, "default_model", "gpt-5")
    recorded = _install_recording_router(monkeypatch)

    await JudgeService().evaluate(query="q", response="r", context_chunks=["c"])

    assert recorded["model"] == "gpt-5-mini"


async def test_provider_neutral_ollama_return_shape(monkeypatch):
    # Not hard-locked to OpenAI: an Ollama-style client (``response`` key) on a
    # non-openai default provider is routed + parsed identically.
    monkeypatch.setattr(settings, "judge_model", "qwen3:8b")
    monkeypatch.setattr(settings, "default_provider", "ollama")
    recorded = _install_recording_router(monkeypatch, return_key="response")

    result = await JudgeService().evaluate(query="q", response="r", context_chunks=["c"])

    assert recorded["preferences"]["provider"] == "ollama"
    assert recorded["model"] == "qwen3:8b"
    # Ollama ``response`` shape was parsed (real scores, not the fallback 75s).
    assert result["composite_score"] == 88.0


# ---------------------------------------------------------------------------
# Resilience
# ---------------------------------------------------------------------------
async def test_error_remains_unavailable(monkeypatch):
    class _BrokenRouter:
        def __init__(self, *args, **kwargs):
            pass

        async def get_client(self, preferences=None):
            raise RuntimeError("no available model clients")

    monkeypatch.setattr("app.services.model_router.ModelRouter", _BrokenRouter)

    result = await JudgeService().evaluate(query="q", response="r", context_chunks=["c"])

    assert result["scores"] == {}
    assert result["status"] == "failed"
    assert result["composite_score"] is None
    assert result["hallucination_rate"] is None
    assert result["reason"] == "judge_response_unavailable"


async def test_ollama_fallback_uses_local_default_model(monkeypatch):
    # On-prem degradation: when the primary provider fails, the judge retries on
    # Ollama with ``ollama_default_model`` (not the cloud model name, which would
    # fail Ollama's model-availability check).
    monkeypatch.setattr(settings, "judge_model", "")
    monkeypatch.setattr(settings, "default_model", "gpt-5")
    monkeypatch.setattr(settings, "default_provider", "openai")
    monkeypatch.setattr(settings, "ollama_default_model", "qwen3:8b")

    calls: list = []

    class _FailingClient:
        async def generate(self, model, prompt):
            raise RuntimeError("openai down")

    class _OllamaClient:
        async def generate(self, model, prompt):
            calls.append(model)
            return {"response": _VALID_COMPLETION}

    class _FailoverRouter:
        def __init__(self, *args, **kwargs):
            pass

        async def get_client(self, preferences=None):
            calls.append(("get_client", preferences.get("provider")))
            if preferences.get("provider") == "ollama":
                return _OllamaClient()
            return _FailingClient()

    monkeypatch.setattr("app.services.model_router.ModelRouter", _FailoverRouter)

    result = await JudgeService().evaluate(query="q", response="r", context_chunks=["c"])

    # Fell over to Ollama with the local default tag and parsed real scores.
    assert ("get_client", "ollama") in calls
    assert "qwen3:8b" in calls
    assert result["composite_score"] == 88.0


async def test_malformed_completion_falls_back(monkeypatch):
    _install_recording_router(monkeypatch, completion="not-json-at-all")

    result = await JudgeService().evaluate(query="q", response="r", context_chunks=["c"])

    assert result["scores"] == {}
    assert result["status"] == "failed"
    assert result["reason"] == "judge_response_unavailable"


# ---------------------------------------------------------------------------
# Excerpt formatter
# ---------------------------------------------------------------------------
def test_format_context_excerpts_empty():
    assert _format_context_excerpts(None) == "(no retrieved context was provided)"
    assert _format_context_excerpts([]) == "(no retrieved context was provided)"
    assert _format_context_excerpts(["  ", ""]) == "(no retrieved context was provided)"


def test_format_context_excerpts_numbers_and_caps_chunks():
    chunks = [f"chunk number {i}" for i in range(20)]
    out = _format_context_excerpts(chunks, max_chunks=8)
    assert out.startswith("[1] chunk number 0")
    assert "[8] chunk number 7" in out
    assert "[9]" not in out  # capped at max_chunks


def test_format_context_excerpts_truncates_to_budget():
    long_chunk = "z" * 5000
    out = _format_context_excerpts([long_chunk], char_budget=3500)
    assert out.endswith("…")
    # [1] prefix + <=3500 chars of text + ellipsis, well under the raw 5000.
    assert len(out) < 3600
