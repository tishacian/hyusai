"""The turn loop: tool calling, citations, session thread, failure translation."""
from __future__ import annotations

import json

import pytest

from app.models.user import Message, User
from app.models.user import Session as ChatSession
from app.models.workspace import Workspace, WorkspaceMember
from app.services.assistant import engine as assistant_engine
from app.services.assistant.engine import (
    SURFACE_VOICE,
    AssistantInputInvalidError,
    AssistantModelFailedError,
    AssistantSessionNotFoundError,
    AssistantUnavailableError,
    answer_assistant_turn,
    build_system_prompt,
)


class FakeToolClient:
    """Scripted ``complete_with_tools`` so the loop is tested, not the provider."""

    def __init__(self, script: list[dict]) -> None:
        self.script = list(script)
        self.calls: list[dict] = []
        self.api_key = "test"

    async def complete_with_tools(self, model, messages, *, tools=None, **kwargs):
        self.calls.append({"model": model, "messages": [dict(m) for m in messages], "tools": tools})
        if not self.script:
            return {"content": "done", "tool_calls": [], "finish_reason": "stop", "usage": {}}
        return self.script.pop(0)


def _answer(content: str) -> dict:
    return {
        "content": content,
        "tool_calls": [],
        "finish_reason": "stop",
        "model": "gpt-test",
        "usage": {"total_tokens": 11},
    }


def _tool_call(name: str, arguments: dict, *, call_id: str = "call_1") -> dict:
    return {
        "content": None,
        "tool_calls": [
            {
                "id": call_id,
                "name": name,
                "arguments": arguments,
                "arguments_json": json.dumps(arguments),
            }
        ],
        "finish_reason": "tool_calls",
        "model": "gpt-test",
        "usage": {},
    }


@pytest.fixture()
def subject(db_session):
    workspace = Workspace(
        id="ws-engine",
        name="Engine",
        slug="engine",
        settings={
            "knowledge_scopes": [
                {"key": "itsd", "collection_slugs": ["itsd-knowledge"], "is_default": True}
            ],
            "assistant": {
                "persona": "Tu es l'assistant ITSD.",
                "knowledge_scope": "itsd",
                "allowed_tools": ["search_knowledge", "list_services"],
                "locale": "fr",
                "max_tool_turns": 2,
            },
        },
    )
    user = User(id="user-engine", username="engine@datategy.test")
    db_session.add_all(
        [
            workspace,
            user,
            WorkspaceMember(
                user_id=user.id,
                workspace_id=workspace.id,
                role="member",
                role_template="workspace_contributor",
            ),
        ]
    )
    db_session.commit()
    return workspace, user


def _install_client(monkeypatch, client: FakeToolClient) -> None:
    monkeypatch.setattr(assistant_engine, "build_model_client", lambda config: client)


async def test_a_plain_answer_opens_a_thread_and_persists_both_messages(
    db_session, subject, monkeypatch
):
    workspace, user = subject
    client = FakeToolClient([_answer("Bonjour, comment puis-je aider ?")])
    _install_client(monkeypatch, client)

    result = await answer_assistant_turn(
        db_session,
        user=user,
        workspace=workspace,
        text="bonjour",
    )

    assert result.answer == "Bonjour, comment puis-je aider ?"
    assert result.tool_calls == []
    assert result.tool_turns == 0
    assert result.finish_reason == "stop"
    assert result.config["knowledge_scope"] == "itsd"
    assert result.config["allowed_tools"] == ["list_services", "search_knowledge"]

    session = db_session.query(ChatSession).filter(ChatSession.id == result.session_id).one()
    assert session.workspace_id == workspace.id
    assert session.meta_data["created_from"] == "assistant_engine"
    roles = [
        row.role
        for row in db_session.query(Message)
        .filter(Message.session_id == result.session_id)
        .order_by(Message.role.asc())
        .all()
    ]
    assert roles == ["assistant", "user"]
    assert result.message_id


async def test_the_loop_executes_a_tool_then_answers_with_its_citations(
    db_session, subject, monkeypatch
):
    workspace, user = subject

    async def fake_retrieve(request):
        assert request["knowledge_scope"] == "itsd"
        assert request["workspace_slug"] == "engine"
        return {
            "chunks": ["Pour réinitialiser un mot de passe, ouvrez un ticket."],
            "scores": [0.81],
            "metadatas": [
                {
                    "chunk_id": "chunk-1",
                    "document_filename": "password-reset.md",
                    "collection": "itsd-knowledge",
                }
            ],
        }

    monkeypatch.setattr("app.services.rag.context.retrieve_rag_context", fake_retrieve)
    client = FakeToolClient(
        [
            _tool_call("search_knowledge", {"query": "réinitialiser mot de passe"}),
            _answer("Ouvrez un ticket ITSD."),
        ]
    )
    _install_client(monkeypatch, client)

    result = await answer_assistant_turn(
        db_session,
        user=user,
        workspace=workspace,
        text="comment réinitialiser mon mot de passe ?",
    )

    assert result.answer == "Ouvrez un ticket ITSD."
    assert result.tool_turns == 1
    assert [call.name for call in result.tool_calls] == ["search_knowledge"]
    assert result.tool_calls[0].ok is True
    assert result.tool_calls[0].result["passages"][0]["snippet"].startswith("Pour réinitialiser")
    assert result.citations == [
        {
            "index": 1,
            "id": "chunk-1",
            "title": "password-reset.md",
            "filename": "password-reset.md",
            "document_id": None,
            "collection": "itsd-knowledge",
            "page": None,
        }
    ]

    # The transcript sent back to the provider must carry the assistant tool_calls
    # message and its matching tool result, or the provider rejects the follow-up.
    second_turn = client.calls[1]["messages"]
    assert second_turn[-2]["role"] == "assistant"
    assert second_turn[-2]["tool_calls"][0]["function"]["name"] == "search_knowledge"
    assert second_turn[-1] == {
        "role": "tool",
        "tool_call_id": "call_1",
        "content": second_turn[-1]["content"],
    }


async def test_a_tool_outside_the_workspace_allowlist_is_refused_to_the_model(
    db_session, subject, monkeypatch
):
    workspace, user = subject
    client = FakeToolClient(
        [
            _tool_call("start_system_run", {"system_id": "sys-1"}),
            _answer("Je ne peux pas déclencher cette action."),
        ]
    )
    _install_client(monkeypatch, client)

    result = await answer_assistant_turn(
        db_session,
        user=user,
        workspace=workspace,
        text="lance le run",
    )

    assert result.tool_calls[0].ok is False
    assert result.tool_calls[0].error == "tool_not_available"
    assert result.answer == "Je ne peux pas déclencher cette action."


async def test_unparseable_tool_arguments_are_reported_back_instead_of_crashing(
    db_session, subject, monkeypatch
):
    workspace, user = subject
    broken = _tool_call("search_knowledge", {})
    broken["tool_calls"][0]["arguments"] = None
    broken["tool_calls"][0]["arguments_json"] = "{not json"
    client = FakeToolClient([broken, _answer("Pouvez-vous préciser ?")])
    _install_client(monkeypatch, client)

    result = await answer_assistant_turn(
        db_session,
        user=user,
        workspace=workspace,
        text="?",
    )

    assert result.tool_calls[0].error == "arguments_unparseable"
    assert result.answer == "Pouvez-vous préciser ?"


async def test_the_tool_budget_is_bounded_and_still_produces_a_sentence(
    db_session, subject, monkeypatch
):
    workspace, user = subject
    client = FakeToolClient(
        [
            _tool_call("list_services", {}, call_id="c1"),
            _tool_call("list_services", {}, call_id="c2"),
            _answer("Voici ce que je peux dire."),
        ]
    )
    _install_client(monkeypatch, client)

    result = await answer_assistant_turn(
        db_session,
        user=user,
        workspace=workspace,
        text="liste tout",
    )

    # max_tool_turns=2 in the fixture: two tool turns, then one tool-free call.
    assert result.tool_turns == 2
    assert result.finish_reason == "tool_turn_limit"
    assert result.answer == "Voici ce que je peux dire."
    assert client.calls[-1]["tools"] is None


async def test_history_is_replayed_on_the_next_turn_of_the_same_thread(
    db_session, subject, monkeypatch
):
    workspace, user = subject
    client = FakeToolClient([_answer("premier"), _answer("second")])
    _install_client(monkeypatch, client)

    first = await answer_assistant_turn(
        db_session,
        user=user,
        workspace=workspace,
        text="première question",
    )
    second = await answer_assistant_turn(
        db_session,
        user=user,
        workspace=workspace,
        text="deuxième question",
        session_id=first.session_id,
    )

    assert second.session_id == first.session_id
    replayed = [
        message["content"]
        for message in client.calls[1]["messages"]
        if message["role"] in {"user", "assistant"}
    ]
    assert replayed == ["première question", "premier", "deuxième question"]


async def test_an_external_session_reference_keeps_one_voice_thread(
    db_session, subject, monkeypatch
):
    workspace, user = subject
    client = FakeToolClient([_answer("un"), _answer("deux")])
    _install_client(monkeypatch, client)

    first = await answer_assistant_turn(
        db_session,
        user=user,
        workspace=workspace,
        text="un",
        external_session_ref="voice-session-42",
        surface=SURFACE_VOICE,
    )
    second = await answer_assistant_turn(
        db_session,
        user=user,
        workspace=workspace,
        text="deux",
        external_session_ref="voice-session-42",
        surface=SURFACE_VOICE,
    )

    assert second.session_id == first.session_id
    assert second.surface == SURFACE_VOICE


async def test_an_unknown_session_id_is_refused(db_session, subject, monkeypatch):
    workspace, user = subject
    _install_client(monkeypatch, FakeToolClient([_answer("x")]))

    with pytest.raises(AssistantSessionNotFoundError):
        await answer_assistant_turn(
            db_session,
            user=user,
            workspace=workspace,
            text="salut",
            session_id="does-not-exist",
        )


async def test_a_foreign_session_id_is_not_reachable(db_session, subject, monkeypatch):
    workspace, user = subject
    other = Workspace(id="ws-other", name="Other", slug="other", settings={})
    foreign_session = ChatSession(
        id="session-foreign",
        user_id=user.id,
        workspace_id=other.id,
        status="active",
    )
    db_session.add_all([other, foreign_session])
    db_session.commit()
    _install_client(monkeypatch, FakeToolClient([_answer("x")]))

    with pytest.raises(AssistantSessionNotFoundError):
        await answer_assistant_turn(
            db_session,
            user=user,
            workspace=workspace,
            text="salut",
            session_id=foreign_session.id,
        )


async def test_an_empty_utterance_is_refused_before_any_model_call(
    db_session, subject, monkeypatch
):
    workspace, user = subject
    client = FakeToolClient([_answer("x")])
    _install_client(monkeypatch, client)

    with pytest.raises(AssistantInputInvalidError):
        await answer_assistant_turn(db_session, user=user, workspace=workspace, text="   ")
    assert client.calls == []


async def test_a_provider_failure_becomes_one_typed_engine_error(
    db_session, subject, monkeypatch
):
    workspace, user = subject

    class ExplodingClient(FakeToolClient):
        async def complete_with_tools(self, model, messages, *, tools=None, **kwargs):
            raise RuntimeError("upstream 500")

    _install_client(monkeypatch, ExplodingClient([]))

    with pytest.raises(AssistantModelFailedError) as failure:
        await answer_assistant_turn(db_session, user=user, workspace=workspace, text="salut")
    assert failure.value.status_code == 502


async def test_a_provider_without_tool_calling_fails_closed(db_session, subject):
    workspace, _user = subject
    workspace.settings = {**workspace.settings, "assistant": {"provider": "ollama"}}

    from app.services.assistant.config import resolve_assistant_config
    from app.services.assistant.tools import KNOWN_TOOLS

    config = resolve_assistant_config(workspace, known_tools=KNOWN_TOOLS)
    with pytest.raises(AssistantUnavailableError) as unavailable:
        assistant_engine.build_model_client(config)
    assert unavailable.value.status_code == 503


def test_asking_for_azure_never_silently_calls_the_public_api(subject) -> None:
    """A provider label this deployment cannot honour is refused, not redirected.

    There is no Azure client here: the only tool-calling client hard-codes
    ``api.openai.com`` and ``OPENAI_API_KEY``. Building it for a workspace that
    configured ``azure_openai`` would send its traffic to another tenancy behind
    a label that says otherwise, which is worse than having no assistant.
    """
    workspace, _user = subject
    workspace.settings = {**workspace.settings, "assistant": {"provider": "azure_openai"}}

    from app.services.assistant.config import resolve_assistant_config
    from app.services.assistant.tools import KNOWN_TOOLS

    config = resolve_assistant_config(workspace, known_tools=KNOWN_TOOLS)

    with pytest.raises(AssistantUnavailableError) as unavailable:
        assistant_engine.build_model_client(config)
    assert unavailable.value.status_code == 503
    # The message has to say why, because the label is the thing that is wrong.
    assert "azure_openai" in str(unavailable.value)
    assert "openai" in str(unavailable.value)
    assert "azure_openai" not in assistant_engine.TOOL_CALLING_PROVIDERS


def test_an_oversized_tool_result_is_cut_and_still_parses_as_json() -> None:
    """The transcript's tool messages are JSON; a cut one has to stay JSON.

    The model reads this as the content of a ``role: "tool"`` message. A
    truncated object with a closing brace glued back on parses as nothing, and
    announces itself as a complete result it is not.
    """
    result = {"ok": True, "passages": ["a" * 200 + '" }' for _ in range(200)]}
    message = assistant_engine._truncate_tool_result(result)

    assert len(message) <= assistant_engine.MAX_TOOL_RESULT_CHARS
    parsed = json.loads(message)
    assert parsed["truncated"] is True
    assert parsed["ok"] is True
    # What survives is the beginning of the real result, verbatim.
    assert parsed["result_json_prefix"].startswith('{"ok": true')
    assert json.dumps(result, ensure_ascii=False).startswith(parsed["result_json_prefix"])


def test_a_tool_result_that_fits_is_passed_through_untouched() -> None:
    result = {"ok": False, "error": "run_forbidden", "message": "no"}
    assert json.loads(assistant_engine._truncate_tool_result(result)) == result


def test_the_voice_surface_prompt_asks_for_speakable_output(subject) -> None:
    workspace, _user = subject
    from app.services.assistant.config import resolve_assistant_config
    from app.services.assistant.tools import KNOWN_TOOLS

    config = resolve_assistant_config(workspace, known_tools=KNOWN_TOOLS)
    prompt = build_system_prompt(
        config,
        surface=SURFACE_VOICE,
        session_context={"service_catalog": [{"slug": "a"}], "route_hint": "password_reset"},
    )

    assert "Tu es l'assistant ITSD." in prompt
    assert "itsd-knowledge" in prompt
    assert "no markdown" in prompt
    assert "password_reset" in prompt
    # The catalogue payload itself is reachable through tools, not inlined.
    assert "service_catalog_size" in prompt
    assert '"slug"' not in prompt
