"""The voice gateway as an in-process client of the assistant engine.

Contracts pinned here (``docs/ops/assistant-engine-contract.md``):

* ``session.start`` with ``mode: "assistant"`` switches the gateway; nothing
  else does, and the capture behaviour of every other mode is untouched;
* a committed utterance reaches ``answer_assistant_turn()`` directly — never
  over HTTP — with ``surface="voice"`` and the voice session id as
  ``external_session_ref`` (thread continuity is the engine's business);
* the answer leaves as ``assistant.answer`` carrying **exactly**
  ``result.as_payload()``, the same body ``POST /api/v1/assistant/turns``
  serves, so the frontend shares one renderer between text and voice;
* the spoken answer follows on the existing ``audio.out`` event;
* both of those leave **framed**, and every frame fits the 15 KiB ceiling of a
  LiveKit reliable data packet — measured on the bytes the sidecar republishes,
  not asserted on the shape;
* assistant mode never resolves — nor requires — an ``ExpertCaptureSession``;
* an engine failure becomes one ``session.error`` carrying the engine's stable
  code, and the voice session survives it;
* a barge-in drops the in-flight answer instead of speaking over the user;
* the session context a surface pushes on ``assistant.context`` is reassembled
  from its frames and handed to the engine verbatim, and a turn spoken before
  it lands is answered without it rather than refused.
"""
from __future__ import annotations

import asyncio
import base64
import json
import math

import pytest

from app.models.user import User
from app.models.workspace import Workspace
from app.services import voice_session_gateway as gw
from app.services.assistant import (
    AssistantModelFailedError,
    AssistantTurnResult,
    ToolCallRecord,
)

_WEBM_HEADER_CHUNK = b"\x1a\x45\xdf\xa3" + b"\x00" * 8


def _workspace() -> Workspace:
    return Workspace(id="ws-voice-assistant", name="Voice Assistant", slug="voice-assistant")


def _user() -> User:
    return User(id="user-voice-assistant", username="ada@datategy.local", email="ada@datategy.local")


def _turn_result(answer: str = "Je peux réinitialiser votre mot de passe.") -> AssistantTurnResult:
    """A result shaped like a real one: citations, a tool call, usage, config."""
    citation = {
        "index": 1,
        "id": "chunk-9",
        "title": "itsd-password-reset.md",
        "filename": "itsd-password-reset.md",
        "document_id": "doc-9",
        "collection": "itsd-knowledge",
        "page": 2,
    }
    return AssistantTurnResult(
        session_id="thread-voice-1",
        message_id="message-voice-1",
        answer=answer,
        citations=[citation],
        tool_calls=[
            ToolCallRecord(
                id="call_a1",
                name="search_knowledge",
                arguments={"query": "réinitialisation mot de passe"},
                ok=True,
                error=None,
                result={"ok": True, "citations": [citation]},
                duration_ms=412,
            )
        ],
        model="gpt-5",
        surface="voice",
        tool_turns=1,
        finish_reason="stop",
        usage={"prompt_tokens": 1841, "completion_tokens": 96, "total_tokens": 1937},
        config={"configured": True, "knowledge_scope": "itsd", "allowed_tools": ["search_knowledge"]},
    )


def _rejoin(frames: list[dict]) -> dict:
    """What a surface sees, out of the frames the gateway sent — in order.

    Deliberately strict: it asserts the sequence rather than tolerating a gap,
    because the frontend treats a gap as an interrupted push and would render
    nothing at all.
    """
    total = int(frames[0]["total"])
    group = frames[:total]
    assert [int(frame["seq"]) for frame in group] == list(range(total))
    assert {int(frame["total"]) for frame in group} == {total}
    return json.loads("".join(frame[gw.OUTBOUND_FRAME_FIELD] for frame in group))


class _Socket:
    def __init__(self) -> None:
        self.sent: list[tuple[str, dict]] = []
        # The whole envelopes, exactly as the sidecar receives and republishes
        # them. Kept so a test can weigh a packet instead of trusting a shape.
        self.messages: list[dict] = []

    async def send_json(self, message: dict) -> None:
        self.messages.append(message)
        self.sent.append((message.get("type"), message.get("payload")))

    @property
    def types(self) -> list[str]:
        return [event_type for event_type, _ in self.sent]

    def payload(self, event_type: str) -> dict:
        """The first payload of that event, rejoined when the event ships framed."""
        if event_type in gw.OUTBOUND_FRAMED_EVENTS:
            frames = self.frames(event_type)
            assert frames, f"no {event_type} was sent"
            return _rejoin(frames)
        return next(payload for sent_type, payload in self.sent if sent_type == event_type)

    def payloads(self, event_type: str) -> list[dict]:
        return [payload for sent_type, payload in self.sent if sent_type == event_type]

    def frames(self, event_type: str) -> list[dict]:
        """The raw frames of a framed event, unrejoined."""
        return self.payloads(event_type)

    def packets(self, event_type: str | None = None) -> list[bytes]:
        """Each event as the sidecar puts it on the LiveKit data channel.

        The sidecar parses the gateway's JSON and re-serializes it compactly
        (``JSON.stringify``) before ``publishData``, so this is that encoding —
        the bytes the 15 KiB cap actually applies to.
        """
        return [
            json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            for message in self.messages
            if event_type is None or message.get("type") == event_type
        ]


class _Provider:
    """Cascade stand-in: the STT half feeds audio.endpoint, the TTS half audio.out."""

    def __init__(
        self,
        transcript: str = "je n'arrive plus à me connecter",
        speech: bytes = b"mp3",
    ) -> None:
        self.transcript = transcript
        self.speech = speech
        self.spoken: list[str] = []

    async def transcribe(self, audio_bytes, *, filename=None, content_type=None, language=None):
        return {"text": self.transcript, "provider": "cascade_openai", "model": "fake-stt"}

    async def synthesize_bytes(self, text: str):
        self.spoken.append(text)
        return {
            "audio_base64": base64.b64encode(self.speech).decode(),
            "content_type": "audio/mpeg",
            "bytes": len(self.speech),
            "provider": "cascade_openai",
            "model": "fake-tts",
        }


class _EngineStub:
    """Records every call to ``answer_assistant_turn`` and replays a result."""

    def __init__(self, result: AssistantTurnResult | None = None, error: Exception | None = None) -> None:
        self.result = result if result is not None else _turn_result()
        self.error = error
        self.calls: list[dict] = []
        self.entered = asyncio.Event()
        self.release: asyncio.Event | None = None

    async def __call__(self, db, **kwargs):
        self.calls.append({"db": db, **kwargs})
        self.entered.set()
        if self.release is not None:
            await self.release.wait()
        if self.error is not None:
            raise self.error
        return self.result


# The ``session.start`` the NAWA surface actually puts on the wire.
#
# ``nawaVoiceOpenOptions()`` names the mode, the surface, the capability and the
# languages — and nothing about the oracle. ``livekit-conversation.service.ts``
# then fills the rest in, and its default for ``tandem_oracle`` is **true**, with
# an ``oracle`` block that overrides neither ``live_partial_stt_enabled`` nor
# ``live_questions_enabled``. So the room that ships runs the assistant with the
# whole capture oracle armed, and this suite is built on that state rather than
# on a quieter one.
SHIPPED_SESSION_START = {
    "runtime": "cascade_openai",
    "provider": "cascade_openai",
    "model": None,
    "transport": "livekit",
    "language": "en",
    "output_language": "en",
    "fallback_policy": "backend_ws",
    "tandem_oracle": True,
    "oracle": {"min_interval_ms": 350, "min_delta_chars": 24},
    "capability": "voice2voice_interaction",
    "mode": "assistant",
    "codec": {"input": "opus", "channels": 1},
}


@pytest.fixture()
async def voice(monkeypatch, db_session):
    """Gateway + assistant-mode state with the engine and the cascade stubbed.

    The state is not hand-built: it comes out of the real ``session.start``
    handler fed the payload the frontend sends, so a flag the surface leaves to a
    default is exercised here with the value it will actually carry. The
    handshake echo goes to a throwaway socket — the socket the tests read only
    carries what they provoke.
    """
    engine = _EngineStub()
    provider = _Provider()
    monkeypatch.setattr(gw, "answer_assistant_turn", engine)
    monkeypatch.setattr(gw, "get_voice_runtime_provider", lambda *a, **k: provider)
    gateway = gw.VoiceSessionGateway()
    state = gw.VoiceSessionState(session_id="voice-session-1")
    await gateway._handle_event(
        _Socket(),
        db_session,
        user=_user(),
        workspace=_workspace(),
        state=state,
        event={"type": "session.start", "payload": SHIPPED_SESSION_START},
    )
    return gateway, state, engine, provider, _Socket()


async def _drain(state: gw.VoiceSessionState) -> None:
    """Await the off-loop assistant turn(s) scheduled by the handler."""
    await asyncio.gather(*list(state.assistant_tasks), return_exceptions=True)


async def _speak(gateway, socket, db_session, state, text: str = "je n'arrive plus à me connecter") -> None:
    await gateway._handle_event(
        socket,
        db_session,
        user=_user(),
        workspace=_workspace(),
        state=state,
        event={"type": "text.final", "payload": {"turn_id": "turn-1", "text": text}},
    )


# The catalogue a front asset owns, in the shape the surface pushes it.
_SESSION_CONTEXT = {
    "service_catalog": [
        {
            "slug": "password-reset",
            "title": "Réinitialisation de mot de passe",
            "category": "identity",
            "manual_process": "1. L'utilisateur appelle le service desk.\n2. L'agent vérifie l'identité.",
        },
        {"slug": "vpn-access", "title": "Accès VPN", "category": "network"},
    ],
    "route_hint": "password-reset",
}


def _context_frames(context: dict, count: int = 1) -> list[dict]:
    """The ``assistant.context`` payloads, framed as the frontend frames them."""
    raw = json.dumps(context, ensure_ascii=False)
    size = max(1, math.ceil(len(raw) / count))
    parts = [raw[at : at + size] for at in range(0, len(raw), size)] or [raw]
    return [
        {"seq": seq, "total": len(parts), "context_json": part}
        for seq, part in enumerate(parts)
    ]


async def _push(gateway, socket, db_session, state, payload: dict) -> None:
    await gateway._handle_event(
        socket,
        db_session,
        user=_user(),
        workspace=_workspace(),
        state=state,
        event={"type": gw.ASSISTANT_CONTEXT_EVENT, "payload": payload},
    )


@pytest.mark.asyncio
async def test_session_start_mode_assistant_switches_the_gateway(db_session, voice):
    """The single documented switch, as the frontend will send it."""
    gateway, _state, _engine, _provider, socket = voice
    state = gw.VoiceSessionState(session_id="voice-session-1")

    assert gateway._is_assistant_mode(state) is False
    await gateway._handle_event(
        socket,
        db_session,
        user=_user(),
        workspace=_workspace(),
        state=state,
        event={"type": "session.start", "payload": {"mode": "assistant", "transport": "livekit"}},
    )

    assert state.mode == "assistant"
    assert gateway._is_assistant_mode(state) is True
    # Echoed back so the surface can verify which loop it actually got.
    assert socket.payload("runtime.metric")["mode"] == "assistant"


@pytest.mark.asyncio
async def test_text_final_answers_with_assistant_answer_then_audio_out(db_session, voice):
    gateway, state, engine, provider, socket = voice

    await _speak(gateway, socket, db_session, state)
    await _drain(state)

    assert engine.calls, "the committed utterance never reached the engine"
    # The live transcript still ships, then the answer, then the spoken audio.
    assert socket.types.index("text.final") < socket.types.index("assistant.answer")
    assert socket.types.index("assistant.answer") < socket.types.index("audio.out")
    assert provider.spoken == [engine.result.answer]
    assert socket.payload("audio.out")["turn_id"] == "turn-1"


@pytest.mark.asyncio
async def test_assistant_answer_carries_exactly_result_as_payload(db_session, voice):
    """No re-encoding, no renaming, no envelope: one renderer for text and voice."""
    gateway, state, engine, _provider, socket = voice

    await _speak(gateway, socket, db_session, state)
    await _drain(state)

    assert socket.payload("assistant.answer") == engine.result.as_payload()
    assert set(socket.payload("assistant.answer")) == {
        "session_id",
        "message_id",
        "answer",
        "citations",
        "tool_calls",
        "model",
        "surface",
        "tool_turns",
        "finish_reason",
        "usage",
        "config",
    }


def _shipped_size_turn_result() -> AssistantTurnResult:
    """A turn the size a real one reaches: a catalogue listing and a retrieval.

    The measured offender is the catalogue: one ``list_services`` result over the
    39-service NAWA workbook serializes to 13 098 bytes, most of a 15 KiB packet
    on its own. A turn that also cites the policy it read — which is the ordinary
    case, not a contrived one — carries three retrieval passages of up to 1 200
    characters beside it, and is past the ceiling with room to spare.
    """
    services = [
        {
            "slug": f"service-{index:02d}",
            "title": f"Service desk request number {index:02d} — création et vérification",
            "category": "Identity & Access Management" if index % 2 else "Messaging & Collaboration",
            "summary": (
                "The service desk receives the request through the ITSD Portal, verifies the "
                "authorisation of the requester against the directory, and applies the change "
                f"once the Line Manager has approved it (entry {index:02d})."
            ),
        }
        for index in range(40)
    ]
    catalogue = {"ok": True, "services": services}
    assert len(json.dumps(catalogue, ensure_ascii=False, separators=(",", ":")).encode()) >= 13_000
    result = _turn_result(
        "Voici les services du desk qui correspondent à votre demande, avec la procédure de chacun."
    )
    result.tool_calls.append(
        ToolCallRecord(
            id="call_catalog",
            name="list_services",
            arguments={"query": "email"},
            ok=True,
            error=None,
            result=catalogue,
            duration_ms=8,
        )
    )
    result.tool_calls.append(
        ToolCallRecord(
            id="call_policy",
            name="search_knowledge",
            arguments={"query": "mot de passe temporaire"},
            ok=True,
            error=None,
            result={
                "ok": True,
                "passages": [
                    {"index": index, "snippet": "Un mot de passe temporaire " * 44, "score": 0.8}
                    for index in range(1, 4)
                ],
            },
            duration_ms=310,
        )
    )
    return result


@pytest.mark.asyncio
async def test_the_answer_and_its_audio_fit_the_livekit_packet_ceiling(
    db_session, voice, monkeypatch
):
    """The defect this framing exists for, measured in bytes on both events.

    A LiveKit reliable data packet is capped at 15 KiB and the sidecar
    republishes every gateway event as one packet. Whole, neither of these two
    payloads fits: the turn carries a 13 kB catalogue result and the spoken
    answer is a base64 MP3 of a few hundred kilobytes. The assertion is on the
    encoded bytes, so putting a whole payload back on the channel fails here even
    if its shape still looks right.
    """
    gateway, state, _engine, _provider, socket = voice
    big = _shipped_size_turn_result()
    monkeypatch.setattr(gw, "answer_assistant_turn", _EngineStub(result=big))
    # ~45 seconds of speech, which is what 600 characters of French synthesizes
    # to: 180 kB of MP3, 240 kB of base64.
    provider = _Provider(speech=b"\xff\xfb\x90d" * 45_000)
    monkeypatch.setattr(gw, "get_voice_runtime_provider", lambda *a, **k: provider)

    await _speak(gateway, socket, db_session, state)
    await _drain(state)

    whole_answer = json.dumps(big.as_payload(), ensure_ascii=False, separators=(",", ":"))
    assert len(whole_answer.encode()) > gw.LIVEKIT_DATA_PACKET_MAX_BYTES
    assert len(socket.payload("audio.out")["audio_base64"]) > gw.LIVEKIT_DATA_PACKET_MAX_BYTES

    oversized = [
        (message["type"], len(packet))
        for message, packet in zip(socket.messages, socket.packets())
        if len(packet) > gw.LIVEKIT_DATA_PACKET_MAX_BYTES
    ]
    assert oversized == []

    # And nothing was lost on the way through the frames.
    assert socket.payload("assistant.answer") == big.as_payload()
    assert base64.b64decode(socket.payload("audio.out")["audio_base64"]) == provider.speech
    assert len(socket.frames("assistant.answer")) > 1
    assert len(socket.frames("audio.out")) > 1


@pytest.mark.asyncio
async def test_a_payload_that_would_fit_is_framed_anyway(db_session, voice):
    """One shape, so reassembly is the path every answer takes.

    The stub answer is a sentence and three bytes of audio: both would fit in one
    packet. They are still framed, because the alternative is a frontend that
    rejoins frames only on the rare large payload — the branch nobody exercises
    until a demo does.
    """
    gateway, state, engine, _provider, socket = voice

    await _speak(gateway, socket, db_session, state)
    await _drain(state)

    for event_type in ("assistant.answer", "audio.out"):
        frames = socket.frames(event_type)
        assert len(frames) == 1
        assert frames[0]["seq"] == 0
        assert frames[0]["total"] == 1
        assert gw.OUTBOUND_FRAME_FIELD in frames[0]
    assert socket.payload("assistant.answer") == engine.result.as_payload()


def test_a_frame_never_cuts_a_character_in_half():
    """The budget is in bytes, so the cut has to respect UTF-8."""
    raw = "é" * 4096
    frames = gw.frame_payload_json(raw, budget=100)
    assert "".join(frames) == raw
    assert all(len(frame.encode()) <= 100 for frame in frames)
    # 100 bytes is 50 two-byte characters: an off-by-one cut would raise inside
    # the helper, so reaching this line at all is part of the assertion.
    assert {len(frame) for frame in frames[:-1]} == {50}


@pytest.mark.asyncio
async def test_engine_is_called_in_process_with_the_voice_surface_and_session_ref(db_session, voice):
    gateway, state, engine, _provider, socket = voice

    await _speak(gateway, socket, db_session, state)
    await _drain(state)

    call = engine.calls[0]
    assert call["db"] is db_session
    assert call["surface"] == gw.SURFACE_VOICE
    # Thread continuity is the engine's job: the gateway hands it the voice
    # session id and keeps no chat session id of its own.
    assert call["external_session_ref"] == state.session_id
    assert "session_id" not in call
    assert call["text"] == "je n'arrive plus à me connecter"


@pytest.mark.asyncio
async def test_assistant_mode_never_resolves_a_capture_session(db_session, voice, monkeypatch):
    gateway, state, _engine, _provider, socket = voice

    def _forbidden(*args, **kwargs):
        raise AssertionError("assistant mode must not require an ExpertCaptureSession")

    monkeypatch.setattr(gateway, "_capture_session", _forbidden)
    monkeypatch.setattr(gw, "append_turn", _forbidden)

    await _speak(gateway, socket, db_session, state)
    await _drain(state)

    assert socket.payload("assistant.answer")["answer"]
    assert state.capture_plan is None
    # The capture-only resolution is short-circuited, not merely unused.
    gateway._ensure_capture_plan(db_session, _workspace().id, state)
    assert state.capture_plan is None


@pytest.mark.asyncio
async def test_the_shipped_room_arms_the_capture_oracle_and_it_stays_inert(
    db_session, voice, monkeypatch
):
    """The assistant room ships with the capture oracle on. Prove it does nothing.

    Every capture behaviour of the oracle — live retrieval hints, active-section
    detection, live open questions, turn persistence — is gated behind
    ``state.capture_plan is not None``, and ``_ensure_capture_plan`` refuses to
    resolve one in assistant mode. That makes the whole capture side inert, but
    only as a consequence of two guards several hundred lines apart, on the one
    configuration nothing was testing.
    """
    gateway, state, engine, provider, socket = voice
    # Armed, not disabled: this is what the surface's own defaults produce.
    assert state.tandem_oracle_enabled is True
    assert state.live_partial_stt_enabled is True
    assert state.live_questions_enabled is True

    # Recorded rather than raised: three of these seams are called inside
    # ``except Exception`` blocks that would swallow an assertion and let the
    # test pass while the capture side ran.
    reached: list[str] = []

    def _record(what: str):
        def _seen(*args, **kwargs):
            reached.append(what)
            return None

        return _seen

    def _record_awaited(what: str):
        async def _seen(*args, **kwargs):
            reached.append(what)
            return None

        return _seen

    for seam in ("_capture_session", "_schedule_live_open_questions"):
        monkeypatch.setattr(gateway, seam, _record(seam))
    for seam in ("_maybe_push_capture_hints", "_maybe_detect_and_emit_active_section"):
        monkeypatch.setattr(gateway, seam, _record_awaited(seam))
    for seam in ("append_turn", "get_session", "build_open_questions"):
        monkeypatch.setattr(gw, seam, _record(seam))

    # The two events a spoken turn produces on the realtime lane: the live
    # partial the sidecar streams, then the committed final.
    await gateway._handle_event(
        socket,
        db_session,
        user=_user(),
        workspace=_workspace(),
        state=state,
        event={"type": "text.partial", "payload": {"turn_id": "turn-1", "text": "je n'arrive plus à me connecter"}},
    )
    await _speak(gateway, socket, db_session, state)
    await _drain(state)

    assert reached == []
    assert socket.payload("assistant.answer") == engine.result.as_payload()
    assert provider.spoken == [engine.result.answer]
    assert state.capture_plan is None
    # The oracle's inner-monologue track still ships on the partial: it is
    # in-memory, carries no capture semantics, and the surface ignores it. Its
    # presence is what says the oracle really did run.
    assert "oracle.delta" in socket.types
    assert "transcript.partial" in socket.types


@pytest.mark.asyncio
async def test_capture_mode_is_untouched_by_the_assistant_branch(db_session, voice, monkeypatch):
    """Regression guard: a conversation_only session still runs the capture seam."""
    gateway, _assistant_state, engine, _provider, socket = voice
    state = gw.VoiceSessionState(session_id="capture-session-1", tandem_oracle_enabled=False)
    resolved: list[str] = []

    def _record(db, workspace_id, session_id):
        resolved.append(session_id)
        return None

    monkeypatch.setattr(gateway, "_capture_session", _record)

    await _speak(gateway, socket, db_session, state)
    await _drain(state)

    assert resolved == ["capture-session-1"]
    assert engine.calls == []
    assert "assistant.answer" not in socket.types


@pytest.mark.asyncio
async def test_empty_final_text_never_reaches_the_engine(db_session, voice):
    gateway, state, engine, _provider, socket = voice

    await _speak(gateway, socket, db_session, state, text="   ")
    await _drain(state)

    assert engine.calls == []
    assert "assistant.answer" not in socket.types
    assert socket.payload("text.final")["empty"] is True


@pytest.mark.asyncio
async def test_engine_error_becomes_a_session_error_and_keeps_the_session(db_session, voice, monkeypatch):
    gateway, state, _engine, provider, socket = voice
    failing = _EngineStub(error=AssistantModelFailedError("upstream 500 from provider xyz"))
    monkeypatch.setattr(gw, "answer_assistant_turn", failing)

    await _speak(gateway, socket, db_session, state)
    await _drain(state)

    error = socket.payload("session.error")
    # The stable engine code travels; the raw provider text never does.
    assert error["code"] == "assistant_model_failed"
    assert "upstream 500" not in error["message"]
    assert "assistant.answer" not in socket.types
    assert provider.spoken == []
    # The session is still usable: the next utterance is answered normally.
    monkeypatch.setattr(gw, "answer_assistant_turn", _EngineStub())
    await _speak(gateway, socket, db_session, state)
    await _drain(state)
    assert "assistant.answer" in socket.types


@pytest.mark.asyncio
async def test_barge_in_drops_the_in_flight_answer(db_session, voice, monkeypatch):
    gateway, state, engine, provider, socket = voice
    engine.release = asyncio.Event()

    await _speak(gateway, socket, db_session, state)
    await engine.entered.wait()

    await gateway._handle_event(
        socket,
        db_session,
        user=_user(),
        workspace=_workspace(),
        state=state,
        event={"type": "barge_in", "payload": {"source": "vad"}},
    )
    engine.release.set()
    await _drain(state)

    assert socket.payload("barge_in")["status"] == "accepted"
    assert "assistant.answer" not in socket.types
    assert provider.spoken == []


@pytest.mark.asyncio
async def test_pushed_session_context_reaches_the_engine_verbatim(db_session, voice):
    """The surface owns the context; the gateway carries it and reads none of it."""
    gateway, state, engine, _provider, socket = voice

    for frame in _context_frames(_SESSION_CONTEXT):
        await _push(gateway, socket, db_session, state, frame)
    await _speak(gateway, socket, db_session, state)
    await _drain(state)

    assert engine.calls[0]["session_context"] == _SESSION_CONTEXT
    ack = socket.payloads(gw.ASSISTANT_CONTEXT_EVENT)[-1]
    assert ack["status"] == "ok"
    assert ack["service_catalog"] == 2
    assert ack["keys"] == ["route_hint", "service_catalog"]


@pytest.mark.asyncio
async def test_a_framed_context_is_reassembled_in_order(db_session, voice):
    """A LiveKit data packet caps at 15 KiB, so a catalogue arrives in pieces."""
    gateway, state, engine, _provider, socket = voice
    frames = _context_frames(_SESSION_CONTEXT, count=4)
    assert len(frames) == 4

    for frame in frames[:-1]:
        await _push(gateway, socket, db_session, state, frame)
        assert socket.payloads(gw.ASSISTANT_CONTEXT_EVENT)[-1]["status"] == "pending"
        # Nothing is readable until the last frame: half a catalogue is worse
        # than none, and the engine would not know which half it holds.
        assert state.assistant_context is None
    await _push(gateway, socket, db_session, state, frames[-1])

    assert state.assistant_context == _SESSION_CONTEXT
    await _speak(gateway, socket, db_session, state)
    await _drain(state)
    assert engine.calls[0]["session_context"] == _SESSION_CONTEXT


@pytest.mark.asyncio
async def test_a_turn_spoken_before_the_context_lands_is_still_answered(db_session, voice):
    gateway, state, engine, _provider, socket = voice

    await _speak(gateway, socket, db_session, state)
    await _drain(state)

    assert socket.payload("assistant.answer")["answer"]
    # Without a catalogue, not without an answer: the tools simply find nothing
    # to list, which is a poorer turn and not a failed one.
    assert engine.calls[0]["session_context"] is None

    for frame in _context_frames(_SESSION_CONTEXT):
        await _push(gateway, socket, db_session, state, frame)
    await _speak(gateway, socket, db_session, state)
    await _drain(state)
    assert engine.calls[1]["session_context"] == _SESSION_CONTEXT


@pytest.mark.asyncio
async def test_a_broken_push_is_refused_without_taking_the_session_down(db_session, voice):
    gateway, state, engine, _provider, socket = voice

    # A frame out of sequence, a frame that is not text, and a body that is not
    # an object: each is a client bug, none is a reason to end a live call.
    await _push(gateway, socket, db_session, state, {"seq": 1, "total": 2, "context_json": "{}"})
    await _push(gateway, socket, db_session, state, {"seq": 0, "total": 1, "context_json": None})
    await _push(gateway, socket, db_session, state, {"seq": 0, "total": 1, "context_json": "[1, 2]"})
    await _push(
        gateway,
        socket,
        db_session,
        state,
        {"seq": 0, "total": 99, "context_json": "{}"},
    )

    assert [ack["status"] for ack in socket.payloads(gw.ASSISTANT_CONTEXT_EVENT)] == ["invalid"] * 4
    assert [ack["reason"] for ack in socket.payloads(gw.ASSISTANT_CONTEXT_EVENT)] == [
        "context_frame_out_of_order",
        "context_frame_invalid",
        "context_unparseable",
        "context_frame_invalid",
    ]
    assert "session.error" not in socket.types
    assert state.assistant_context is None
    assert state.assistant_context_frames == []

    # And the session is still usable, context included.
    for frame in _context_frames(_SESSION_CONTEXT):
        await _push(gateway, socket, db_session, state, frame)
    await _speak(gateway, socket, db_session, state)
    await _drain(state)
    assert engine.calls[0]["session_context"] == _SESSION_CONTEXT


@pytest.mark.asyncio
async def test_a_context_larger_than_the_connection_budget_is_dropped(db_session, voice):
    gateway, state, _engine, _provider, socket = voice
    oversized = "x" * (gw._ASSISTANT_CONTEXT_MAX_CHARS + 1)

    await _push(gateway, socket, db_session, state, {"seq": 0, "total": 1, "context_json": oversized})

    assert socket.payload(gw.ASSISTANT_CONTEXT_EVENT)["reason"] == "context_too_large"
    assert state.assistant_context is None
    assert state.assistant_context_frames == []


@pytest.mark.asyncio
async def test_a_second_push_replaces_the_context_it_supersedes(db_session, voice):
    gateway, state, engine, _provider, socket = voice

    for frame in _context_frames(_SESSION_CONTEXT):
        await _push(gateway, socket, db_session, state, frame)
    for frame in _context_frames({"service_catalog": []}):
        await _push(gateway, socket, db_session, state, frame)
    await _speak(gateway, socket, db_session, state)
    await _drain(state)

    assert engine.calls[0]["session_context"] == {"service_catalog": []}


@pytest.mark.asyncio
async def test_audio_endpoint_lane_also_answers_with_the_assistant(db_session, voice):
    """The batch STT lane converges on the same seam as the realtime one."""
    gateway, state, engine, provider, socket = voice
    frame = {
        "bytes_b64": base64.b64encode(_WEBM_HEADER_CHUNK).decode(),
        "turn_id": "turn-audio-1",
        "content_type": "audio/webm",
        "incremental_transcription": False,
    }

    await gateway._handle_event(
        socket,
        db_session,
        user=_user(),
        workspace=_workspace(),
        state=state,
        event={"type": "audio.frame", "payload": frame},
    )
    await gateway._handle_event(
        socket,
        db_session,
        user=_user(),
        workspace=_workspace(),
        state=state,
        event={"type": "audio.endpoint", "payload": {"turn_id": "turn-audio-1"}},
    )
    await _drain(state)

    assert engine.calls[0]["text"] == provider.transcript
    assert socket.payload("assistant.answer") == engine.result.as_payload()
    assert provider.spoken == [engine.result.answer]
