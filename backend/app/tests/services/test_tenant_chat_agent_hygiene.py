"""The shared chat agent keeps Andritz's answer hygiene for Andritz only.

OmniRAGAgent serves every tenant. Its system prompt told every workspace that
"Agentium users in the Andritz workspace are already Andritz experts", its
answer-shaping rules named Andritz, and every streamed answer held back its
last 480 characters so an Andritz contact footer could be stripped. The
Andritz prompts must not move by a byte: the fixture was captured from
demo/agentic before the change.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.agents import procurement_agent as agent

FIXTURE = (
    Path(__file__).resolve().parents[1] / "fixtures" / "tenant_prompts" / "andritz_chat_agent_prompts.json"
)
GOLDEN = json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_andritz_system_prompt_is_unchanged():
    assert agent.default_system_prompt("andritz") == GOLDEN["system_prompt"]


@pytest.mark.parametrize("case", GOLDEN["rag_user_prompt"], ids=lambda c: str(sorted(c["kwargs"].items())[1:3]))
def test_andritz_rag_user_prompt_is_unchanged(case):
    assert agent._build_rag_user_prompt(**case["kwargs"], family="andritz") == case["expected"]


@pytest.mark.parametrize("family", [None, "generic", "industrial", "sentinel_ci"])
def test_other_families_keep_the_rule_without_the_customer(family):
    system = agent.default_system_prompt(family)
    user = agent._build_rag_user_prompt(**GOLDEN["rag_user_prompt"][0]["kwargs"], family=family)
    framing = user.split("Context")[0] + user[user.find("Answer-shaping") :]
    assert "Andritz" not in system and "Andritz" not in framing
    assert "contact the supplier" in system
    assert "Do not end with generic document boilerplate" in user


def test_only_andritz_buffers_the_answer_tail(monkeypatch):
    families = {"ws-andritz": "andritz", "ws-other": "generic"}
    monkeypatch.setattr(agent, "_workspace_family_for_slug", lambda slug: families.get(slug, "generic"))

    other = agent._answer_tail_filter("ws-other", "Quelle est la vitesse ?")
    assert other.feed("Premier morceau. ") == "Premier morceau. "  # streamed at once
    assert other.flush() == ""

    andritz = agent._answer_tail_filter("ws-andritz", "Quelle est la vitesse ?")
    emitted = andritz.feed("Réponse. ") + andritz.feed("Pour plus d'informations, contactez Andritz.")
    emitted += andritz.flush()
    assert emitted == "Réponse."

    asking = agent._answer_tail_filter("ws-andritz", "Quel est le contact support ?")
    assert asking.feed("Contactez Andritz au 01.") == "Contactez Andritz au 01."


def test_the_family_lookup_is_cached_per_slug(monkeypatch):
    agent._family_by_slug.clear()
    calls = []

    class _Query:
        def filter(self, *_a):
            return self

        def scalar(self):
            calls.append(1)
            return {"family": "andritz"}

    class _Session:
        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

        def query(self, *_a):
            return _Query()

    monkeypatch.setattr("app.db.base.SessionLocal", lambda: _Session())
    assert agent._workspace_family_for_slug("cached-ws") == "andritz"
    assert agent._workspace_family_for_slug("cached-ws") == "andritz"
    assert len(calls) == 1
    assert agent._workspace_family_for_slug("") == "generic"
    agent._family_by_slug.clear()
