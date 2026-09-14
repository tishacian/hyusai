"""Unit tests for the OmniRAG conversation-memory / follow-up fixes.

These guard the live Andritz demo fixes for the dominant end-user complaint
("il ne suit pas la conversation"):
  1. follow-up / meta instructions ("détaille", "réponds plus long", "résume")
     are detected and reuse the previous answer instead of running retrieval on
     the short instruction;
  2. the Sources panel is suppressed on follow-up / meta turns and only kept
     when the answer actually grounded on retrieval;
  3. recent conversation turns (incl. the previous assistant answer) are passed
     into the LLM generation messages so the model can expand/continue.
"""

from __future__ import annotations

import httpx

from app.agents.procurement_agent import (
    OmniRAGAgent,
    _cited_source_indices,
    _conversation_history,
    _ensure_grounded_citation,
    _is_meta_followup,
    _previous_assistant_answer,
    _trimmed_history_for_prompt,
)

_HISTORY = [
    {"role": "user", "content": "Quels documents de convoyeur sont indexés pour ARA200 ?"},
    {
        "role": "assistant",
        "content": "Les documents indexés pour l'ARA200 incluent le manuel des pièces.",
    },
]


def test_llm_client_honors_request_provider_and_caches_per_provider(monkeypatch):
    from app.llm import llm as llm_module

    created: list[tuple[str, str | None]] = []

    class _FakeLLM:
        def __init__(self, *, provider: str, api_key: str | None = None):
            self.provider = provider
            created.append((provider, api_key))

    monkeypatch.setattr(llm_module, "LLM", _FakeLLM)
    agent = OmniRAGAgent()

    ollama = agent._get_llm("ollama")
    assert ollama.provider == "ollama"
    assert agent._get_llm("ollama") is ollama

    openai = agent._get_llm("openai")
    assert openai.provider == "openai"
    assert openai is not ollama
    assert [provider for provider, _ in created] == ["ollama", "openai"]


# ── Follow-up / meta detection ─────────────────────────────────────────────
def test_meta_followups_detected_with_history():
    for query in [
        "détaille",
        "detaille",
        "détaille ta doc",
        "je veux une réponse 10 fois plus longue",
        "je veux une reponse 10 fois plus longue",
        "résume",
        "reformule",
        "explique",
        "plus long",
        "plus de détails",
        "continue",
        "développe",
    ]:
        assert _is_meta_followup(query, _HISTORY) is True, query


def test_meta_followup_requires_history():
    # Without a previous assistant answer there is nothing to expand, so the
    # turn is treated as a normal (retrieval) query.
    assert _is_meta_followup("détaille", []) is False
    assert _is_meta_followup("détaille", [{"role": "user", "content": "hi"}]) is False


def test_real_questions_are_not_followups():
    for query in [
        "de quelle documentation disposes-tu ?",
        "Quels documents de convoyeur sont indexés pour ARA200 ?",
        "Dans le projet AKK200, quelle source contient Filtering cartridge LM 300 ?",
        "quelles sont les vitesses moyennes des lignes de production ?",
    ]:
        assert _is_meta_followup(query, _HISTORY) is False, query


def test_new_project_reference_is_not_misclassified_as_meta_followup():
    for query in [
        "résume BAO100",
        "Resume BCX200",
        "résume le projet ACJ100",
        "et BAX300",
        "BHX300",
    ]:
        assert _is_meta_followup(query, _HISTORY) is False, query


def test_short_pronoun_only_turn_is_followup():
    # Very short, non-question instruction in an ongoing conversation is a
    # follow-up; a short question ("?") is conservatively kept as a new query.
    assert _is_meta_followup("encore plus", _HISTORY) is True
    assert _is_meta_followup("et ça ?", _HISTORY) is False


# ── History extraction / trimming ──────────────────────────────────────────
def test_conversation_history_extracted_from_request_context():
    request = {"context": {"conversation_history": _HISTORY}}
    turns = _conversation_history(request)
    assert [t["role"] for t in turns] == ["user", "assistant"]
    assert _previous_assistant_answer(turns).startswith("Les documents")


def test_conversation_history_ignores_malformed_entries():
    request = {
        "context": {
            "conversation_history": [
                {"role": "user", "content": "ok"},
                # "system" turns carry the condensed-history summary injected
                # by the memory manager and are kept.
                {"role": "system", "content": "résumé des échanges précédents"},
                {"role": "assistant", "content": ""},
                {"role": "tool", "content": "dropped"},
                "not-a-dict",
            ]
        }
    }
    turns = _conversation_history(request)
    assert turns == [
        {"role": "user", "content": "ok"},
        {"role": "system", "content": "résumé des échanges précédents"},
    ]


def test_trimmed_history_keeps_latest_assistant_full_caps_older():
    long_old = "x" * 9000
    long_latest = "y" * 9000
    history = [
        {"role": "assistant", "content": long_old},
        {"role": "user", "content": "détaille"},
        {"role": "assistant", "content": long_latest},
    ]
    trimmed = _trimmed_history_for_prompt(history)
    # Older assistant answer is capped; the most recent one is preserved in full
    # so an "expand" follow-up has the real text to build on.
    assert len(trimmed[0]["content"]) < len(long_old)
    assert trimmed[-1]["content"] == long_latest


# ── Citation parsing + source gating ───────────────────────────────────────
def test_cited_source_indices():
    assert _cited_source_indices("voir [1] et [3], aussi [3]") == {1, 3}
    assert _cited_source_indices("aucune citation ici") == set()


def test_single_source_citation_is_repaired_for_strongly_grounded_answer():
    answer, repaired = _ensure_grounded_citation(
        "The golden path opens a cited source and recovers from a retryable failure.",
        [
            {
                "title": "Agentium first-use evidence",
                "snippet": "The golden path opens a cited source and recovers from a retryable failure.",
            }
        ],
        is_followup=False,
        has_citable_context=True,
    )

    assert answer.endswith(" [1].")
    assert repaired is True


def test_single_source_citation_repair_stays_fail_closed_for_weak_overlap():
    original = "There is not enough information to answer safely."
    answer, repaired = _ensure_grounded_citation(
        original,
        [{"title": "Pump manual", "snippet": "Nominal pump pressure is 40 bar."}],
        is_followup=False,
        has_citable_context=True,
    )

    assert answer == original
    assert repaired is False


def _sources(n: int):
    return [{"id": f"chunk-{i}", "title": f"doc {i}"} for i in range(n)]


def test_gate_sources_suppressed_for_followup():
    assert (
        OmniRAGAgent._gate_sources(
            _sources(3),
            "réponse plus longue [1][2]",
            is_followup=True,
            has_citable_context=True,
            discovery_intent=False,
        )
        == []
    )


def test_gate_sources_suppressed_without_citable_context():
    assert (
        OmniRAGAgent._gate_sources(
            _sources(3),
            "answer [1]",
            is_followup=False,
            has_citable_context=False,
            discovery_intent=False,
        )
        == []
    )


def test_gate_sources_kept_when_model_cited():
    sources = _sources(3)
    kept = OmniRAGAgent._gate_sources(
        sources,
        "La réponse est X [1] et Y [3].",
        is_followup=False,
        has_citable_context=True,
        discovery_intent=False,
    )
    # Full list kept so the front's [n] → sources[n-1] mapping stays aligned.
    assert kept == sources


def test_gate_sources_discovery_kept_without_citations():
    sources = _sources(4)
    kept = OmniRAGAgent._gate_sources(
        sources,
        "Je dispose de plusieurs manuels et listes de pièces.",
        is_followup=False,
        has_citable_context=True,
        discovery_intent=True,
    )
    assert kept == sources


def test_gate_sources_suppressed_when_not_grounded_and_not_discovery():
    # Non-discovery factual turn where the model didn't cite anything → the
    # answer didn't ground on retrieval, so no spurious Sources panel.
    kept = OmniRAGAgent._gate_sources(
        _sources(4),
        "Je n'ai pas d'information pertinente sur ce point.",
        is_followup=False,
        has_citable_context=True,
        discovery_intent=False,
    )
    assert kept == []


async def test_generation_connection_failure_emits_safe_structured_error(monkeypatch):
    class _StoppedLLM:
        async def stream_complete(self, **_kwargs):
            if False:  # pragma: no cover - keeps this an async generator
                yield ""
            raise httpx.ConnectError(
                "All connection attempts failed for http://ollama.internal:11434?token=secret",
                request=httpx.Request("POST", "http://ollama.internal:11434/api/chat"),
            )

    agent = OmniRAGAgent()
    monkeypatch.setattr(agent, "_get_llm", lambda _provider: _StoppedLLM())
    chunks = [
        chunk
        async for chunk in agent.process(
            {
                "query": "continue",
                "agent_preferences": {
                    "model_preferences": {"provider": "ollama", "model": "qwen3:8b"}
                },
                "context": {"conversation_history": _HISTORY},
            }
        )
    ]

    errors = [chunk for chunk in chunks if chunk.get("chunk_type") == "error"]
    assert errors == [
        {
            "chunk_type": "error",
            "content": (
                "The configured model provider is unreachable. "
                "Check that it is running and try again."
            ),
            "error": {
                "code": "provider_unreachable",
                "message": (
                    "The configured model provider is unreachable. "
                    "Check that it is running and try again."
                ),
                "retryable": True,
            },
            "is_final": True,
        }
    ]
    assert "ollama.internal" not in str(chunks)
    assert "secret" not in str(chunks)


# ── stream_complete passes conversation history to the model ───────────────
async def test_stream_complete_inserts_history_between_system_and_user(monkeypatch):
    from app.llm import llm as llm_module
    from app.llm.models import StreamChoice, StreamingResponse

    captured: dict = {}

    class _FakeProvider:
        def __init__(self, *args, **kwargs):
            pass

        async def stream_generate(self, request):
            captured["messages"] = request.messages_as_dicts()
            yield StreamingResponse(
                id="x",
                model=request.model,
                created=0,
                choices=[StreamChoice(index=0, delta={"content": "ok"}, finish_reason=None)],
            )

    monkeypatch.setitem(llm_module.LLM._PROVIDER_FACTORIES, "openai", lambda: _FakeProvider)
    client = llm_module.LLM(provider="openai", api_key="test")

    history = [
        {"role": "user", "content": "Quels documents pour ARA200 ?"},
        {"role": "assistant", "content": "Le manuel des pièces ARA200."},
    ]
    out = ""
    async for piece in client.stream_complete(
        prompt="détaille",
        model="gpt-5",
        system_prompt="SYS",
        history=history,
    ):
        out += piece

    roles = [m["role"] for m in captured["messages"]]
    assert roles == ["system", "user", "assistant", "user"]
    assert captured["messages"][1]["content"] == "Quels documents pour ARA200 ?"
    assert captured["messages"][2]["content"] == "Le manuel des pièces ARA200."
    assert captured["messages"][-1]["content"] == "détaille"
    assert out == "ok"
