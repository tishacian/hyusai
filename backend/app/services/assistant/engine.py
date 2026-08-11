"""The conversational assistant engine: one tool-calling turn loop.

This module is the single entry point for every assistant surface. The HTTP
endpoint and the LiveKit voice gateway both call :func:`answer_assistant_turn`;
neither of them owns routing, prompting or tool selection. The engine knows
nothing about any particular tenant — see :mod:`app.services.assistant.config`.

Contract, in one line: text in, answer + citations + tool trace + session id out.
"""
from __future__ import annotations

import json
import time
import uuid
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session as DBSession

from app.core.logging import get_logger
from app.models.user import Message, User
from app.models.user import Session as ChatSession
from app.models.workspace import Workspace
from app.services.assistant.config import AssistantConfig, resolve_assistant_config
from app.services.assistant.tools import (
    KNOWN_TOOLS,
    ToolContext,
    execute_tool,
    tools_for,
)

logger = get_logger(__name__)

SURFACE_TEXT = "text"
SURFACE_VOICE = "voice"

# Providers whose client exposes ``complete_with_tools``. Tool calling does not
# exist anywhere else in this repository, so anything else fails closed loudly
# instead of silently degrading to a one-shot completion.
TOOL_CALLING_PROVIDERS = frozenset({"openai"})

# Provider labels this engine refuses by name rather than by absence, because
# accepting them would send the call somewhere other than where the label says.
# ``azure_openai`` has no client here: the only tool-calling client hard-codes
# ``https://api.openai.com/v1`` and ``OPENAI_API_KEY``, so honouring the label
# would quietly bill and expose a public-API call to a workspace that asked for
# its own Azure tenancy. A workspace that wants the public API says ``openai``.
MISLABELLED_PROVIDERS: dict[str, str] = {
    "azure_openai": (
        "Assistant provider 'azure_openai' is not implemented here: this deployment "
        "has no Azure OpenAI client, and the tool-calling client only reaches the "
        "public OpenAI API. Set provider to 'openai' if that is what you want."
    ),
}

MAX_TEXT_CHARS = 8000
MAX_TOOL_RESULT_CHARS = 12000

# Ceiling on the session context a surface may hand over, counted on the JSON
# the surface sends. The voice lane bounds the frames it reassembles against
# this same number (``voice_session_gateway._ASSISTANT_CONTEXT_MAX_CHARS``), so
# the two lanes accept the same catalogue rather than one silently accepting
# what the other drops. Semantics stay in the engine: ``MAX_SERVICES`` caps the
# catalogue, this caps bytes.
MAX_SESSION_CONTEXT_CHARS = 262_144

SESSION_SIGNATURE_PREFIX = "assistant"


class AssistantEngineError(Exception):
    """Base class for engine failures that a surface must translate."""

    code = "assistant_error"
    status_code = 500


class AssistantSessionNotFoundError(AssistantEngineError):
    code = "assistant_session_not_found"
    status_code = 404


class AssistantInputInvalidError(AssistantEngineError):
    code = "assistant_input_invalid"
    status_code = 400


class AssistantUnavailableError(AssistantEngineError):
    """The configured model plane cannot serve a tool-calling turn."""

    code = "assistant_unavailable"
    status_code = 503


class AssistantModelFailedError(AssistantEngineError):
    code = "assistant_model_failed"
    status_code = 502


@dataclass
class ToolCallRecord:
    """One tool invocation, as the surfaces must be able to render it."""

    id: str
    name: str
    arguments: dict[str, Any]
    ok: bool
    error: str | None
    result: dict[str, Any]
    duration_ms: int

    def as_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AssistantTurnResult:
    """The single value both the HTTP endpoint and the voice gateway consume."""

    session_id: str
    message_id: str
    answer: str
    citations: list[dict[str, Any]] = field(default_factory=list)
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    model: str = ""
    surface: str = SURFACE_TEXT
    tool_turns: int = 0
    finish_reason: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    config: dict[str, Any] = field(default_factory=dict)

    def as_payload(self) -> dict[str, Any]:
        """Serialize to the wire/event shape shared by every surface."""
        return {
            "session_id": self.session_id,
            "message_id": self.message_id,
            "answer": self.answer,
            "citations": list(self.citations),
            "tool_calls": [call.as_payload() for call in self.tool_calls],
            "model": self.model,
            "surface": self.surface,
            "tool_turns": self.tool_turns,
            "finish_reason": self.finish_reason,
            "usage": dict(self.usage),
            "config": dict(self.config),
        }


# ---------------------------------------------------------------------------
# Session thread
# ---------------------------------------------------------------------------
def _user_id(user: User | None) -> str | None:
    return str(getattr(user, "id", "") or "") or None


def _session_signature(external_session_ref: str | None) -> str | None:
    if not external_session_ref:
        return None
    return f"{SESSION_SIGNATURE_PREFIX}:{external_session_ref}"[:512]


def resolve_assistant_session(
    db: DBSession,
    *,
    workspace: Workspace,
    user: User,
    session_id: str | None,
    external_session_ref: str | None = None,
    surface: str = SURFACE_TEXT,
) -> ChatSession:
    """Resolve the conversation thread for this turn.

    Three deliberate rules, none of which touch the classic chat reuse logic:

    * an explicit ``session_id`` must resolve to an active thread of this
      workspace and caller, otherwise :class:`AssistantSessionNotFoundError`;
    * an ``external_session_ref`` (for example a voice session id) reuses the
      thread previously opened for that reference, so a surface with no place to
      store a chat id still keeps one continuous conversation;
    * anything else opens a brand new thread. The engine never silently glues a
      new question onto an unrelated old thread.
    """
    owner_id = _user_id(user)
    if session_id:
        query = db.query(ChatSession).filter(
            ChatSession.id == session_id,
            ChatSession.workspace_id == workspace.id,
            ChatSession.status == "active",
        )
        query = (
            query.filter(ChatSession.user_id == owner_id)
            if owner_id
            else query.filter(ChatSession.user_id.is_(None))
        )
        session = query.first()
        if session is None:
            raise AssistantSessionNotFoundError(f"Assistant session {session_id!r} not found")
        return session

    signature = _session_signature(external_session_ref)
    if signature:
        query = db.query(ChatSession).filter(
            ChatSession.workspace_id == workspace.id,
            ChatSession.status == "active",
            ChatSession.context_signature == signature,
        )
        query = (
            query.filter(ChatSession.user_id == owner_id)
            if owner_id
            else query.filter(ChatSession.user_id.is_(None))
        )
        existing = query.order_by(ChatSession.last_activity.desc()).first()
        if existing is not None:
            return existing

    now = datetime.utcnow()
    session = ChatSession(
        id=str(uuid.uuid4()),
        user_id=owner_id,
        workspace_id=workspace.id,
        title=None,
        status="active",
        context_signature=signature,
        created_at=now,
        last_activity=now,
        meta_data={
            "created_from": "assistant_engine",
            "surface": surface,
            "external_session_ref": external_session_ref,
        },
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def _load_history(db: DBSession, *, session_id: str, limit: int) -> list[dict[str, str]]:
    """Return the last ``limit`` user/assistant messages in chronological order."""
    if limit <= 0:
        return []
    rows = (
        db.query(Message)
        .filter(Message.session_id == session_id)
        .order_by(Message.timestamp.desc())
        .limit(limit)
        .all()
    )
    history: list[dict[str, str]] = []
    for row in reversed(rows):
        if row.role not in {"user", "assistant"} or not (row.content or "").strip():
            continue
        history.append({"role": row.role, "content": row.content})
    return history


# ---------------------------------------------------------------------------
# Prompting
# ---------------------------------------------------------------------------
def _session_context_brief(session_context: Mapping[str, Any]) -> str:
    """Render the surface-supplied context, minus payloads exposed via tools."""
    scalars = {
        str(key): value
        for key, value in session_context.items()
        if key != "service_catalog" and isinstance(value, str | int | float | bool)
    }
    catalog = session_context.get("service_catalog")
    if isinstance(catalog, list) and catalog:
        scalars["service_catalog_size"] = len(catalog)
    if not scalars:
        return ""
    return json.dumps(scalars, ensure_ascii=False, default=str)[:2000]


def build_system_prompt(
    config: AssistantConfig,
    *,
    surface: str,
    session_context: Mapping[str, Any],
) -> str:
    lines = [config.persona.strip(), ""]
    lines.append(f"Workspace: {config.workspace_slug or config.workspace_id}.")
    if config.knowledge_scope:
        lines.append(f"Knowledge scope: {config.knowledge_scope}.")
    if config.collection_slugs:
        lines.append(f"Knowledge collections: {', '.join(config.collection_slugs)}.")
    lines.append(f"Surface: {surface}.")
    if surface == SURFACE_VOICE:
        lines.append(
            "You are speaking out loud: keep the answer short, one idea per sentence, "
            "no markdown, no bullet lists, no URLs."
        )
    if config.locale:
        lines.append(f"Always answer in this locale: {config.locale}.")
    brief = _session_context_brief(session_context)
    if brief:
        lines.append(f"Session context provided by the surface: {brief}")
    lines.append(
        "Tools are the only source of truth about this workspace. Chain several of "
        "them when needed, ask a clarifying question when the request is ambiguous, "
        "and never claim an action was performed unless a tool result proves it."
    )
    return "\n".join(line for line in lines if line is not None)


def _truncate_tool_result(result: Mapping[str, Any]) -> str:
    """Serialize one tool result for the transcript, bounded and still parseable.

    Every other ``role: "tool"`` message of this loop is a JSON object, so an
    oversized one stays a JSON object: what is cut travels as a string field of
    a valid envelope instead of as half an object with a closing brace glued
    back on. The loop re-measures because escaping the kept prefix costs
    characters of its own; it removes at least one character per pass, so it
    terminates.
    """
    payload = json.dumps(result, ensure_ascii=False, default=str)
    if len(payload) <= MAX_TOOL_RESULT_CHARS:
        return payload
    envelope: dict[str, Any] = {
        "ok": bool(result.get("ok")),
        "error": result.get("error"),
        "truncated": True,
        "result_json_prefix": "",
    }
    while payload:
        envelope["result_json_prefix"] = payload
        message = json.dumps(envelope, ensure_ascii=False)
        overflow = len(message) - MAX_TOOL_RESULT_CHARS
        if overflow <= 0:
            return message
        payload = payload[: len(payload) - overflow]
    envelope["result_json_prefix"] = ""
    return json.dumps(envelope, ensure_ascii=False)


def _merge_citations(
    collected: list[dict[str, Any]],
    result: Mapping[str, Any],
) -> None:
    """Accumulate deduplicated citations across every retrieval tool result."""
    seen = {
        (item.get("id"), item.get("filename"), item.get("page")) for item in collected
    }
    for citation in result.get("citations") or []:
        if not isinstance(citation, Mapping):
            continue
        key = (citation.get("id"), citation.get("filename"), citation.get("page"))
        if key in seen:
            continue
        seen.add(key)
        collected.append({**citation, "index": len(collected) + 1})


# ---------------------------------------------------------------------------
# Model plane
# ---------------------------------------------------------------------------
def build_model_client(config: AssistantConfig) -> Any:
    """Return a client exposing ``complete_with_tools`` for this configuration."""
    provider = (config.provider or "").strip().lower()
    mislabelled = MISLABELLED_PROVIDERS.get(provider)
    if mislabelled is not None:
        raise AssistantUnavailableError(mislabelled)
    if provider not in TOOL_CALLING_PROVIDERS:
        raise AssistantUnavailableError(
            f"Assistant provider {provider!r} does not support tool calling"
        )
    from app.services.model_clients.openai_client import OpenAIClient

    client = OpenAIClient()
    if not client.api_key:
        raise AssistantUnavailableError("Assistant provider credentials are not configured")
    return client


# ---------------------------------------------------------------------------
# The turn
# ---------------------------------------------------------------------------
async def answer_assistant_turn(
    db: DBSession,
    *,
    user: User,
    workspace: Workspace,
    text: str,
    session_id: str | None = None,
    external_session_ref: str | None = None,
    surface: str = SURFACE_TEXT,
    session_context: Mapping[str, Any] | None = None,
) -> AssistantTurnResult:
    """Answer one user utterance, calling tools as many times as needed.

    This is the internal call contract. ``voice_session_gateway`` calls it
    directly — the voice surface never goes through HTTP.

    Raises :class:`AssistantInputInvalidError`, :class:`AssistantSessionNotFoundError`,
    :class:`AssistantUnavailableError` or :class:`AssistantModelFailedError`; every other
    failure (a tool refusing, a run being denied) is returned inside the result
    so the conversation survives it.
    """
    utterance = str(text or "").strip()[:MAX_TEXT_CHARS]
    if not utterance:
        raise AssistantInputInvalidError("An assistant turn needs a non-empty text")

    session_context = dict(session_context or {})
    config = resolve_assistant_config(workspace, known_tools=KNOWN_TOOLS)
    client = build_model_client(config)

    session = resolve_assistant_session(
        db,
        workspace=workspace,
        user=user,
        session_id=session_id,
        external_session_ref=external_session_ref,
        surface=surface,
    )

    allowed_tools = tools_for(config)
    tool_specs = [tool.as_openai_spec() for tool in allowed_tools]
    ctx = ToolContext(
        db=db,
        user=user,
        workspace=workspace,
        config=config,
        session_id=session.id,
        surface=surface,
        session_context=session_context,
    )

    messages: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": build_system_prompt(
                config,
                surface=surface,
                session_context=session_context,
            ),
        },
        *_load_history(db, session_id=session.id, limit=config.history_turns),
        {"role": "user", "content": utterance},
    ]

    citations: list[dict[str, Any]] = []
    tool_records: list[ToolCallRecord] = []
    answer = ""
    finish_reason: str | None = None
    usage: dict[str, Any] = {}
    tool_turns = 0

    async def complete(*, with_tools: bool) -> dict[str, Any]:
        try:
            return await client.complete_with_tools(
                config.model,
                messages,
                tools=tool_specs if (with_tools and tool_specs) else None,
            )
        except Exception as exc:  # noqa: BLE001 — one upstream class for surfaces.
            logger.exception(
                "assistant.engine: model call failed",
                workspace_id=config.workspace_id,
                model=config.model,
                error=str(exc),
            )
            raise AssistantModelFailedError(str(exc)) from exc

    for _turn in range(config.max_tool_turns):
        completion = await complete(with_tools=True)
        finish_reason = completion.get("finish_reason")
        usage = completion.get("usage") or {}
        calls = list(completion.get("tool_calls") or [])
        if not calls:
            answer = str(completion.get("content") or "").strip()
            break

        tool_turns += 1
        messages.append(
            {
                "role": "assistant",
                "content": completion.get("content") or None,
                "tool_calls": [
                    {
                        "id": call.get("id") or "",
                        "type": "function",
                        "function": {
                            "name": call.get("name") or "",
                            "arguments": call.get("arguments_json") or "{}",
                        },
                    }
                    for call in calls
                ],
            }
        )
        for call in calls:
            name = str(call.get("name") or "")
            arguments = call.get("arguments")
            started = time.perf_counter()
            if not isinstance(arguments, dict):
                result: dict[str, Any] = {
                    "ok": False,
                    "error": "arguments_unparseable",
                    "message": "Tool arguments were not valid JSON; retry the call.",
                }
                arguments = {}
            else:
                result = await execute_tool(ctx, name, arguments)
            _merge_citations(citations, result)
            record = ToolCallRecord(
                id=str(call.get("id") or ""),
                name=name,
                arguments=arguments,
                ok=bool(result.get("ok")),
                error=result.get("error") if not result.get("ok") else None,
                result=result,
                duration_ms=int((time.perf_counter() - started) * 1000),
            )
            tool_records.append(record)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": record.id,
                    "content": _truncate_tool_result(result),
                }
            )
    else:
        # The tool budget ran out while the model was still calling tools. Ask
        # once more with no tools so the user always gets a real sentence back.
        completion = await complete(with_tools=False)
        answer = str(completion.get("content") or "").strip()
        usage = completion.get("usage") or usage
        finish_reason = "tool_turn_limit"

    message_id = _persist_turn(
        db,
        session=session,
        utterance=utterance,
        answer=answer,
        citations=citations,
        tool_records=tool_records,
        surface=surface,
        config=config,
    )

    return AssistantTurnResult(
        session_id=session.id,
        message_id=message_id,
        answer=answer,
        citations=citations,
        tool_calls=tool_records,
        model=config.model,
        surface=surface,
        tool_turns=tool_turns,
        finish_reason=finish_reason,
        usage=usage,
        config={
            "configured": config.configured,
            "knowledge_scope": config.knowledge_scope,
            "allowed_tools": sorted(config.allowed_tools),
        },
    )


def _persist_turn(
    db: DBSession,
    *,
    session: ChatSession,
    utterance: str,
    answer: str,
    citations: list[dict[str, Any]],
    tool_records: list[ToolCallRecord],
    surface: str,
    config: AssistantConfig,
) -> str:
    """Append the user/assistant pair to the thread and return the answer id."""
    now = datetime.utcnow()
    # ``messages`` has no sequence column, so the answer is stamped strictly
    # after the question. Without that the next turn replays the pair in an
    # arbitrary order and the model reads its own answer as the prompt.
    answered_at = now + timedelta(microseconds=1)
    assistant_message_id = str(uuid.uuid4())
    db.add(
        Message(
            id=str(uuid.uuid4()),
            session_id=session.id,
            role="user",
            content=utterance,
            timestamp=now,
            meta_data={"surface": surface, "engine": "assistant"},
        )
    )
    db.add(
        Message(
            id=assistant_message_id,
            session_id=session.id,
            role="assistant",
            content=answer,
            timestamp=answered_at,
            meta_data={
                "surface": surface,
                "engine": "assistant",
                "model": config.model,
                "citations": citations,
                "tool_calls": [
                    {
                        "name": record.name,
                        "ok": record.ok,
                        "error": record.error,
                        "duration_ms": record.duration_ms,
                    }
                    for record in tool_records
                ],
            },
        )
    )
    session.last_activity = answered_at
    db.commit()
    return assistant_message_id
