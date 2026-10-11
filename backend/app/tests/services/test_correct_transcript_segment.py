"""Tests for the two-tier domain transcript corrector."""
from __future__ import annotations

import asyncio

import pytest

from app.services.voice_transcript_glossary import (
    build_glossary_from_terms,
    correct_transcript_segment,
    correct_transcript_segment_tier1,
)


def _glossary(terms):
    return build_glossary_from_terms(terms, max_terms=200)


def test_tier1_corrects_near_homophone_cadre_to_carde():
    glossary = _glossary(["carde", "injecteurs"])
    out = correct_transcript_segment_tier1(
        "le cadre passe sous les injecteurs", glossary
    )
    assert "carde" in out
    assert "cadre" not in out
    # The non-target tokens are preserved verbatim.
    assert out == "le carde passe sous les injecteurs"


def test_tier1_normalizes_acronym_casing_bom_to_BOM():
    glossary = _glossary(["BOM", "carde"])
    out = correct_transcript_segment_tier1("le bom est valide", glossary)
    assert "BOM" in out
    assert "bom" not in out


def test_tier1_alphanumeric_acronym_casing():
    glossary = _glossary(["KD724", "XS1"])
    out = correct_transcript_segment_tier1("monte le kd724 puis le xs1", glossary)
    assert "KD724" in out
    assert "XS1" in out


def test_tier1_no_op_when_no_match():
    glossary = _glossary(["carde", "BOM"])
    text = "nous parlons de tout autre chose ici"
    assert correct_transcript_segment_tier1(text, glossary) == text


def test_tier1_does_not_fabricate_or_drop_content():
    glossary = _glossary(["carde"])
    text = "le cadre passe sous les injecteurs et tourne vite"
    out = correct_transcript_segment_tier1(text, glossary)
    # Same number of word tokens, only 'cadre' rewritten.
    assert len(out.split()) == len(text.split())
    assert out.replace("carde", "cadre") == text


def test_tier1_is_idempotent():
    glossary = _glossary(["carde", "BOM"])
    text = "le cadre passe et le bom est valide"
    once = correct_transcript_segment_tier1(text, glossary)
    twice = correct_transcript_segment_tier1(once, glossary)
    assert once == twice
    assert "carde" in once and "BOM" in once


def test_tier1_empty_glossary_returns_input():
    glossary = build_glossary_from_terms([])
    text = "le cadre passe"
    assert correct_transcript_segment_tier1(text, glossary) == text


def test_tier1_preserves_leading_capitalization():
    glossary = _glossary(["carde"])
    out = correct_transcript_segment_tier1("Cadre vérifié", glossary)
    assert out.startswith("Carde")


def test_async_entrypoint_returns_tier1_when_llm_disabled():
    glossary = _glossary(["carde", "BOM"])
    out = asyncio.run(
        correct_transcript_segment(
            "le cadre passe sous les injecteurs et le bom est valide",
            glossary,
            llm_enabled=False,
        )
    )
    assert "carde" in out
    assert "BOM" in out


def test_tier2_mocked_llm_refines(monkeypatch):
    glossary = _glossary(["carde", "BOM"])

    import app.services.capture_knowledge_oracle as oracle

    monkeypatch.setattr(oracle, "_resolve_llm_config", lambda *_a, **_k: ("fake-key", "gpt-4o-mini"))

    class _Msg:
        content = "le carde passe sous les injecteurs et le BOM est valide."

    class _Choice:
        message = _Msg()

    class _Resp:
        choices = [_Choice()]

    class _Completions:
        async def create(self, *args, **kwargs):
            return _Resp()

    class _Chat:
        completions = _Completions()

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            self.chat = _Chat()

    import openai

    monkeypatch.setattr(openai, "AsyncOpenAI", _FakeClient)

    out = asyncio.run(
        correct_transcript_segment(
            "le cadre passe sous les injecteurs et le bom est valide",
            glossary,
            llm_enabled=True,
            timeout_ms=2000,
        )
    )
    assert out == "le carde passe sous les injecteurs et le BOM est valide."


def test_tier2_timeout_falls_back_to_tier1(monkeypatch):
    glossary = _glossary(["carde", "BOM"])

    import app.services.capture_knowledge_oracle as oracle

    monkeypatch.setattr(oracle, "_resolve_llm_config", lambda *_a, **_k: ("fake-key", "gpt-4o-mini"))

    class _Completions:
        async def create(self, *args, **kwargs):
            await asyncio.sleep(5)
            raise AssertionError("should have timed out")

    class _Chat:
        completions = _Completions()

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            self.chat = _Chat()

    import openai

    monkeypatch.setattr(openai, "AsyncOpenAI", _FakeClient)

    out = asyncio.run(
        correct_transcript_segment(
            "le cadre passe et le bom est valide",
            glossary,
            llm_enabled=True,
            timeout_ms=50,
        )
    )
    # Falls back to the deterministic Tier-1 result.
    assert "carde" in out
    assert "BOM" in out


def test_tier2_error_falls_back_to_tier1(monkeypatch):
    glossary = _glossary(["carde"])

    import app.services.capture_knowledge_oracle as oracle

    monkeypatch.setattr(oracle, "_resolve_llm_config", lambda *_a, **_k: ("", ""))

    out = asyncio.run(
        correct_transcript_segment("le cadre passe", glossary, llm_enabled=True, timeout_ms=500)
    )
    assert "carde" in out
