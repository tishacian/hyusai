"""WebSocket gateway for streaming-compatible voice sessions.

J1 keeps the cascade provider as the concrete runtime while introducing the
protocol shape needed for lower-latency voice loops: typed events, inner
monologue text track, minimal latency metrics and HTTP fallback compatibility.
"""
from __future__ import annotations

import asyncio
import base64
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from fastapi import HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session as DBSession

from app.core.auth import decode_token
from app.core.config import settings
from app.core.logging import get_logger
from app.core.iam.dependencies import enforce_permission
from app.models.expert_capture import ExpertCaptureSession
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services.audit_logger import emit_audit_event
from app.services.knowledge_capture import (
    _retrieve_context_chunks,
    _retrieve_context_chunks_async,
    append_turn,
    build_open_questions,
    format_retrieval_chunks,
    get_session,
    is_capture_text_noise,
    process_capture_partial_hints,
    process_conversation_step,
)
from app.services.voice_runtime import (
    VoiceProviderError,
    get_voice_runtime_provider,
    resolve_voice_runtime_slug,
)
from app.services.livekit_service import LiveKitService, LiveKitServiceError
from app.services.voice_tandem_oracle import VoiceTandemOracle
from app.services.voice_transcript_glossary import (
    correct_transcript_segment,
    resolve_glossary,
)


logger = get_logger(__name__)


@dataclass
class VoiceSessionState:
    session_id: str
    runtime: str = "cascade_openai"
    capability: str = "voice2voice_interaction"
    mode: str = "conversation_only"
    transport: str = "backend_ws"
    model: Optional[str] = None
    fallback_policy: str = "cascade_openai"
    codec: Dict[str, Any] = field(default_factory=dict)
    sequence: int = 0
    audio_chunks: list[bytes] = field(default_factory=list)
    text_partials: list[str] = field(default_factory=list)
    client_turn_id: Optional[str] = None
    question_id: Optional[str] = None
    retrieval_event_id: Optional[str] = None
    interruption_of_event_id: Optional[str] = None
    last_proposal_id: Optional[str] = None
    content_type: str = "audio/webm"
    language: str = "fr"
    turn_started_at: Optional[float] = None
    endpoint_at: Optional[float] = None
    tandem_oracle_enabled: bool = True
    oracle: VoiceTandemOracle = field(default_factory=VoiceTandemOracle)
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    last_contradiction_candidates: list[Dict[str, Any]] = field(default_factory=list)
    last_retrieval_chunks: list[str] = field(default_factory=list)
    last_retrieval_metadatas: list[Dict[str, Any]] = field(default_factory=list)
    last_retrieval_scores: list[float] = field(default_factory=list)
    last_partial_stt_at: Optional[float] = None
    partial_stt_in_flight: bool = False
    last_partial_text: str = ""
    last_partial_chunk_count: int = 0


_PARTIAL_STT_MIN_INTERVAL_MS = 1500

_TRANSCRIPT_FILLERS = (
    "euh",
    "euhh",
    "heu",
    "heuh",
    "hum",
    "hmm",
    " benh",
    "bah",
    "ben",
)


def improve_transcript_segment(text: str) -> str:
    """Lightweight disfluency / punctuation cleanup for a transcript segment.

    Deterministic and cheap: strips common filler words, collapses immediate word
    repetitions and whitespace, capitalizes the first letter and ensures terminal
    punctuation. Used to produce the ``transcript.improved`` stage after a chunk
    has been transcribed.
    """
    raw = (text or "").strip()
    if not raw:
        return ""
    tokens = raw.split()
    cleaned: list[str] = []
    for token in tokens:
        bare = token.strip(",.;:!?…").lower()
        if bare in _TRANSCRIPT_FILLERS:
            continue
        if cleaned and cleaned[-1].strip(",.;:!?…").lower() == bare and bare:
            continue
        cleaned.append(token)
    result = " ".join(cleaned).strip()
    if not result:
        return raw
    result = result[0].upper() + result[1:]
    if result[-1] not in ".!?…":
        result = f"{result}."
    return result


def reframe_transcript_segment(text: str, *, plan_topic_label: Optional[str] = None) -> str:
    """Plan-aware reformulation of a transcript chunk.

    Cleans disfluencies (see :func:`improve_transcript_segment`) and, when the active
    plan topic is known, frames the cleaned statement under that topic so the segment
    reads against the plan rather than as a raw utterance. Never fabricates content and
    never duplicates the frame when the statement already names the topic.
    """
    improved = improve_transcript_segment(text)
    if not improved:
        return improved
    label = (plan_topic_label or "").strip()
    if not label:
        return improved
    if label.lower() in improved.lower():
        return improved
    core = improved[0].lower() + improved[1:]
    return f"{label} — {core}"


class VoiceSessionGateway:
    async def handle(
        self,
        websocket: WebSocket,
        *,
        session_id: str,
        token: Optional[str],
        workspace_slug: Optional[str],
        db: DBSession,
    ) -> None:
        await websocket.accept()
        auth = self._authenticate(db, token=token, workspace_slug=workspace_slug, session_id=session_id)
        if not auth:
            await self._send_error(websocket, "unauthorized", "Voice session authentication failed")
            await websocket.close(code=4401)
            return
        user, workspace = auth
        try:
            enforce_permission(
                db,
                user=user,
                workspace=workspace,
                resource_kind="voice_runtime",
                action="read",
                resource_attrs={"capability": "voice2voice_interaction"},
                audit_prefix="kc",
            )
        except HTTPException as exc:
            await self._send_error(websocket, "forbidden", str(exc.detail))
            await websocket.close(code=4403)
            return

        try:
            default_runtime = resolve_voice_runtime_slug(None, workspace_settings=workspace.settings)
        except VoiceProviderError:
            default_runtime = "cascade_openai"
        state = VoiceSessionState(session_id=session_id, runtime=default_runtime)
        capture_session = self._capture_session(db, workspace.id, session_id)
        if capture_session:
            try:
                enforce_permission(
                    db,
                    user=user,
                    workspace=workspace,
                    resource_kind="capture_session",
                    action="execute",
                    resource_attrs={
                        "capability": "expert_knowledge_capture",
                        "resource_id": capture_session.id,
                        "owner_user_id": capture_session.created_by_user_id,
                        "created_by_user_id": capture_session.created_by_user_id,
                    },
                    audit_prefix="kc",
                )
            except HTTPException as exc:
                await self._send_error(websocket, "forbidden", str(exc.detail), state=state)
                await websocket.close(code=4403)
                return

        await self._send(
            websocket,
            state,
            "session.ready",
            {
                "runtime": state.runtime,
                "provider": state.runtime,
                "transport": state.transport,
                "tandem_oracle": state.tandem_oracle_enabled,
            },
        )
        try:
            while True:
                event = await websocket.receive_json()
                await self._handle_event(websocket, db, user=user, workspace=workspace, state=state, event=event)
        except WebSocketDisconnect:
            return

    async def _handle_event(
        self,
        websocket: WebSocket,
        db: DBSession,
        *,
        user: User,
        workspace: Workspace,
        state: VoiceSessionState,
        event: Dict[str, Any],
    ) -> None:
        event_type = str(event.get("type") or "")
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        if event_type == "session.start":
            try:
                state.runtime = resolve_voice_runtime_slug(
                    str(payload.get("provider") or payload.get("runtime") or state.runtime),
                    workspace_settings=workspace.settings,
                    system_voice=payload.get("system_voice") if isinstance(payload.get("system_voice"), dict) else None,
                    node_config=payload.get("node_config") if isinstance(payload.get("node_config"), dict) else None,
                )
            except VoiceProviderError as exc:
                await self._send_error(websocket, exc.code, str(exc), state=state)
                return
            state.capability = str(payload.get("capability") or state.capability)
            state.mode = str(payload.get("mode") or state.mode)
            state.transport = str(payload.get("transport") or state.transport)
            state.model = str(payload.get("model")) if payload.get("model") else None
            state.language = str(payload.get("language") or payload.get("input_language") or state.language or "fr")
            state.fallback_policy = str(payload.get("fallback_policy") or state.fallback_policy)
            state.codec = payload.get("codec") if isinstance(payload.get("codec"), dict) else {}
            state.tandem_oracle_enabled = bool(payload.get("tandem_oracle", True))
            oracle_config = payload.get("oracle") if isinstance(payload.get("oracle"), dict) else {}
            state.oracle = VoiceTandemOracle(
                min_interval_ms=int(oracle_config.get("min_interval_ms") or 350),
                min_delta_chars=int(oracle_config.get("min_delta_chars") or 24),
            )
            await self._send(
                websocket,
                state,
                "runtime.metric",
                {
                    "metric": "session_started",
                    "value_ms": 0,
                    "provider": state.runtime,
                    "model": state.model,
                    "transport": state.transport,
                    "capability": state.capability,
                    "fallback_policy": state.fallback_policy,
                    "tandem_oracle": state.tandem_oracle_enabled,
                },
            )
            return
        if event_type in {
            "loop.start",
            "loop.pause",
            "loop.resume",
            "loop.stop",
            "loop.armed",
            "tts.started",
            "tts.ended",
            "tts.interrupted",
        }:
            if event_type in {"loop.stop", "tts.interrupted"}:
                # Hard stop / barge-in: cancel any pending incremental partials so the
                # next utterance starts clean.
                self._reset_partial_stt_state(state)
            emit_audit_event(
                workspace_id=workspace.id,
                event_type=f"voice.{event_type}",
                actor=user.email or user.username or user.id,
                details={
                    "session_id": state.session_id,
                    "runtime": state.runtime,
                    "transport": state.transport,
                    **payload,
                },
            )
            await self._send(websocket, state, event_type, {"status": "ok", **payload})
            return
        if event_type == "audio.frame":
            await self._handle_audio_frame(websocket, db, user=user, workspace=workspace, state=state, payload=payload)
            return
        if event_type in {"audio.endpoint", "audio.endpoint.auto"}:
            if event_type == "audio.endpoint.auto":
                payload = {**payload, "auto": True, "event_type": event_type}
            await self._handle_audio_endpoint(websocket, db, user=user, workspace=workspace, state=state, payload=payload)
            return
        if event_type == "barge_in":
            self._reset_partial_stt_state(state)
            metric_payload = {
                "metric": "barge_in",
                "value_ms": 0,
                "turn_id": payload.get("turn_id") or state.client_turn_id,
                "prompt_event_id": payload.get("prompt_event_id"),
                "interruption_of_event_id": payload.get("interruption_of_event_id")
                or state.interruption_of_event_id,
                "runtime": state.runtime,
                "transport": state.transport,
                "source": payload.get("source") or "client_control",
            }
            emit_audit_event(
                workspace_id=workspace.id,
                event_type="voice.barge_in",
                actor=user.email or user.username or user.id,
                details={
                    "session_id": state.session_id,
                    "runtime": state.runtime,
                    "transport": state.transport,
                    **payload,
                },
                db=db,
            )
            await self._send(websocket, state, "runtime.metric", metric_payload)
            await self._send(websocket, state, "barge_in", {"status": "accepted", **payload})
            return
        if event_type == "voice.command":
            command = str(payload.get("command") or "").strip()
            emit_audit_event(
                workspace_id=workspace.id,
                event_type="voice.command",
                actor=user.email or user.username or user.id,
                details={
                    "session_id": state.session_id,
                    "turn_id": payload.get("turn_id") or state.client_turn_id,
                    "command": command,
                    "runtime": state.runtime,
                    "transport": state.transport,
                },
            )
            await self._send(websocket, state, "voice.command", {"status": "accepted", **payload, "command": command})
            return
        if event_type == "text.partial":
            await self._handle_text_partial(websocket, db, user=user, workspace=workspace, state=state, payload=payload)
            return
        if event_type == "text.final":
            await self._handle_text_final(websocket, db, user=user, workspace=workspace, state=state, payload=payload)
            return
        if event_type in {
            "translation.partial",
            "translation.final",
            "oracle.delta",
            "oracle.action",
            "oracle.commit",
            "oracle.superseded",
            "runtime.metric",
        }:
            await self._send(websocket, state, event_type, payload)
            return
        if event_type == "session.close":
            await self._send(websocket, state, "session.close", {"status": "ok"})
            await websocket.close(code=1000)
            return
        await self._send_error(websocket, "unknown_event", f"Unknown voice event: {event_type}", state=state)

    @staticmethod
    def _reset_partial_stt_state(state: VoiceSessionState) -> None:
        state.last_partial_stt_at = None
        state.partial_stt_in_flight = False
        state.last_partial_text = ""
        state.last_partial_chunk_count = 0

    async def _handle_audio_frame(
        self,
        websocket: WebSocket,
        db: DBSession,
        *,
        user: User,
        workspace: Workspace,
        state: VoiceSessionState,
        payload: Dict[str, Any],
    ) -> None:
        raw = payload.get("bytes_b64")
        if not raw:
            await self._send_error(websocket, "missing_audio", "audio.frame requires bytes_b64", state=state)
            return
        try:
            chunk = base64.b64decode(str(raw))
        except Exception:
            await self._send_error(websocket, "invalid_audio", "audio.frame bytes_b64 is invalid", state=state)
            return
        if not state.audio_chunks:
            state.turn_started_at = time.perf_counter()
            state.client_turn_id = str(payload.get("turn_id") or payload.get("client_turn_id") or uuid.uuid4())
            state.question_id = payload.get("question_id") if payload.get("question_id") else state.question_id
            state.retrieval_event_id = payload.get("retrieval_event_id") if payload.get("retrieval_event_id") else None
            state.interruption_of_event_id = (
                payload.get("interruption_of_event_id") if payload.get("interruption_of_event_id") else None
            )
            state.content_type = str(payload.get("content_type") or payload.get("encoding") or "audio/webm")
            # New utterance: clear any leftover incremental-partial bookkeeping.
            self._reset_partial_stt_state(state)
            await self._send(websocket, state, "runtime.metric", {"metric": "audio_started", "value_ms": 0})
        state.audio_chunks.append(chunk)
        if payload.get("incremental_transcription") is False:
            return
        await self._maybe_run_incremental_transcription(
            websocket, db, user=user, workspace=workspace, state=state
        )

    async def _maybe_run_incremental_transcription(
        self,
        websocket: WebSocket,
        db: DBSession,
        *,
        user: User,
        workspace: Workspace,
        state: VoiceSessionState,
    ) -> None:
        """Throttled server-side incremental transcription of the GROWING audio buffer.

        Emits live ``transcript.partial`` and runs the tandem oracle + capture-hint
        retrieval mid-utterance. It never emits ``transcript.improved`` / ``text.final``
        and never runs fact extraction — those stay in ``_handle_audio_endpoint`` (the
        per-pause segment end). The authoritative buffer (``state.audio_chunks``) is read
        but never cleared here, so the endpoint's full transcription stays intact.
        """
        if not state.tandem_oracle_enabled or state.partial_stt_in_flight:
            return
        chunk_count = len(state.audio_chunks)
        if chunk_count < 1 or chunk_count <= state.last_partial_chunk_count:
            return
        now = time.perf_counter()
        if (
            state.last_partial_stt_at is not None
            and (now - state.last_partial_stt_at) * 1000.0 < _PARTIAL_STT_MIN_INTERVAL_MS
        ):
            return
        try:
            provider = get_voice_runtime_provider(state.runtime, workspace_settings=workspace.settings)
        except VoiceProviderError:
            return
        audio_bytes = b"".join(state.audio_chunks)
        if not audio_bytes:
            return
        turn_id = state.client_turn_id or str(uuid.uuid4())
        state.client_turn_id = turn_id
        # In-flight guard: only one incremental STT runs at a time; new frames keep
        # buffering and a later tick picks them up.
        state.partial_stt_in_flight = True
        state.last_partial_stt_at = now
        state.last_partial_chunk_count = chunk_count
        try:
            transcript = await provider.transcribe(
                audio_bytes,
                filename=f"{turn_id}.webm",
                content_type=state.content_type,
                language=state.language or "fr",
            )
        except Exception:
            return
        finally:
            state.partial_stt_in_flight = False

        text = str(transcript.get("text") or transcript.get("transcript") or "").strip()
        if is_capture_text_noise(text):
            return
        if not text or text == state.last_partial_text:
            return
        state.last_partial_text = text
        state.text_partials.append(text)
        await self._send(
            websocket,
            state,
            "transcript.partial",
            {"segment_id": turn_id, "turn_id": turn_id, "text": text},
        )
        events = state.oracle.observe_partial(
            text,
            turn_id=turn_id,
            input_state={
                "transcript_state": "partial",
                "provider": transcript.get("provider") or state.runtime,
                "transport": state.transport,
            },
            output_state={"oracle_state": "thinking"},
            duration_ms=0,
        )
        await self._emit_oracle_events(websocket, db, user=user, workspace=workspace, state=state, events=events)
        capture_session = self._capture_session(db, workspace.id, state.session_id)
        if capture_session:
            await self._maybe_push_capture_hints(
                websocket,
                db,
                user=user,
                workspace=workspace,
                state=state,
                capture_session=capture_session,
                partial_text=text,
            )

    async def _handle_text_partial(
        self,
        websocket: WebSocket,
        db: DBSession,
        *,
        user: User,
        workspace: Workspace,
        state: VoiceSessionState,
        payload: Dict[str, Any],
    ) -> None:
        turn_id = str(payload.get("turn_id") or state.client_turn_id or uuid.uuid4())
        state.client_turn_id = turn_id
        text = str(payload.get("text") or "")
        await self._send(websocket, state, "text.partial", {**payload, "turn_id": turn_id})
        # Live transcript stage keyed by a stable segment_id (== turn_id) so the UI can
        # later swap this text in place with the improved version.
        await self._send(
            websocket,
            state,
            "transcript.partial",
            {"segment_id": turn_id, "turn_id": turn_id, "text": text},
        )
        if not state.tandem_oracle_enabled:
            return
        events = state.oracle.observe_partial(
            text,
            turn_id=turn_id,
            input_state={
                "transcript_state": "partial",
                "provider": payload.get("provider") or state.runtime,
                "transport": state.transport,
            },
            output_state={"oracle_state": "thinking"},
            duration_ms=int(payload.get("duration_ms") or payload.get("latency_ms") or 0),
        )
        await self._emit_oracle_events(websocket, db, user=user, workspace=workspace, state=state, events=events)
        capture_session = self._capture_session(db, workspace.id, state.session_id)
        if capture_session and text.strip() and not is_capture_text_noise(text):
            await self._maybe_push_capture_hints(
                websocket,
                db,
                user=user,
                workspace=workspace,
                state=state,
                capture_session=capture_session,
                partial_text=text,
            )

    async def _maybe_push_capture_hints(
        self,
        websocket: WebSocket,
        db: DBSession,
        *,
        user: User,
        workspace: Workspace,
        state: VoiceSessionState,
        capture_session: ExpertCaptureSession,
        partial_text: str,
    ) -> None:
        if len(partial_text.split()) < 6:
            return
        # Contextualize live retrieval with the current plan topic AND the active
        # open_questions so retrieved chunks stay relevant to what the plan cares about.
        query_context = self._retrieval_query_context(capture_session)
        expanded_query = f"{partial_text} {query_context}".strip()
        chunks, metadatas, scores = await _retrieve_context_chunks_async(
            db,
            workspace_id=workspace.id,
            workspace_slug=workspace.slug,
            session=capture_session,
            query=expanded_query,
            top_k=4,
        )
        state.last_retrieval_chunks = list(chunks)
        state.last_retrieval_metadatas = list(metadatas or [])
        state.last_retrieval_scores = list(scores or [])
        result = process_capture_partial_hints(
            db,
            workspace_id=workspace.id,
            session_id=capture_session.id,
            partial_text=partial_text,
            retrieval_chunks=chunks,
            retrieval_metadatas=metadatas,
            client_turn_id=state.client_turn_id,
            actor_user_id=user.id,
        )
        candidates = result.get("contradiction_candidates") or []
        if candidates:
            state.last_contradiction_candidates = candidates
        for hint in result.get("hints") or []:
            hint_events = state.oracle.emit_hint(
                str(hint.get("hint") or ""),
                turn_id=state.client_turn_id or str(uuid.uuid4()),
                subtopic_id=hint.get("subtopic_id"),
                kb_excerpt=hint.get("kb_excerpt"),
                oracle_id=hint.get("oracle_id"),
            )
            await self._emit_oracle_events(
                websocket,
                db,
                user=user,
                workspace=workspace,
                state=state,
                events=hint_events,
            )

    async def _handle_text_final(
        self,
        websocket: WebSocket,
        db: DBSession,
        *,
        user: User,
        workspace: Workspace,
        state: VoiceSessionState,
        payload: Dict[str, Any],
    ) -> None:
        turn_id = str(payload.get("turn_id") or state.client_turn_id or uuid.uuid4())
        state.client_turn_id = turn_id
        text = str(payload.get("text") or "")
        await self._send(websocket, state, "text.final", {**payload, "turn_id": turn_id})
        if not state.tandem_oracle_enabled:
            return
        events = state.oracle.commit_final(
            text,
            turn_id=turn_id,
            duration_ms=int(payload.get("duration_ms") or payload.get("latency_ms") or 0),
        )
        await self._emit_oracle_events(websocket, db, user=user, workspace=workspace, state=state, events=events)

    async def _handle_audio_endpoint(
        self,
        websocket: WebSocket,
        db: DBSession,
        *,
        user: User,
        workspace: Workspace,
        state: VoiceSessionState,
        payload: Dict[str, Any],
    ) -> None:
        if payload.get("question_id"):
            state.question_id = str(payload.get("question_id"))
        if not state.audio_chunks:
            await self._send_error(websocket, "empty_audio", "audio.endpoint received without audio frames", state=state)
            return
        state.endpoint_at = time.perf_counter()
        try:
            provider = get_voice_runtime_provider(state.runtime, workspace_settings=workspace.settings)
        except VoiceProviderError as exc:
            await self._send_error(websocket, exc.code, str(exc), state=state)
            state.turn_started_at = None
            return
        audio_bytes = b"".join(state.audio_chunks)
        state.audio_chunks = []
        started = state.turn_started_at or state.endpoint_at
        try:
            transcript = await provider.transcribe(
                audio_bytes,
                filename=f"{state.client_turn_id or 'voice-session'}.webm",
                content_type=state.content_type,
                language=state.language or "fr",
            )
        except VoiceProviderError as exc:
            await self._send_error(websocket, exc.code, str(exc), state=state)
            state.turn_started_at = None
            return
        except Exception as exc:
            await self._send_error(websocket, "transcribe_failed", str(exc), state=state)
            state.turn_started_at = None
            return

        text = str(transcript.get("text") or transcript.get("transcript") or "").strip()
        ignored_reason = "stt_noise" if text and is_capture_text_noise(text) else None
        if ignored_reason:
            text = ""
        first_text_ms = int((time.perf_counter() - started) * 1000)
        latency = {
            "first_text": first_text_ms,
            "final_text": first_text_ms,
            "audio_bytes": len(audio_bytes),
            "runtime_provider": transcript.get("provider") or state.runtime,
            "runtime_requested_provider": transcript.get("requested_provider") or state.runtime,
            "runtime_model": transcript.get("model") or state.model,
            "fallback_used": bool(transcript.get("fallback")),
        }
        if text:
            state.text_partials.append(text)
            oracle_events: list[Dict[str, Any]] = []
            partial_seq = None
            if state.tandem_oracle_enabled:
                oracle_events = state.oracle.observe_partial(
                    text,
                    turn_id=state.client_turn_id or str(uuid.uuid4()),
                    input_state={
                        "transcript_state": "partial",
                        "provider": transcript.get("provider") or state.runtime,
                        "transport": state.transport,
                    },
                    output_state={"oracle_state": "thinking"},
                    duration_ms=first_text_ms,
                    force=True,
                )
                partial_seq = self._oracle_partial_seq(oracle_events)
            await self._send(
                websocket,
                state,
                "text.partial",
                {
                    "turn_id": state.client_turn_id,
                    "partial_seq": partial_seq,
                    "text": text,
                    "latency_ms": first_text_ms,
                },
            )
            await self._emit_oracle_events(websocket, db, user=user, workspace=workspace, state=state, events=oracle_events)
        # Two-stage transcript contract keyed by a stable segment_id (== turn_id):
        # the raw STT text as the partial, then the cleaned text as the improved stage.
        segment_id = state.client_turn_id or str(uuid.uuid4())
        capture_session = self._capture_session(db, workspace.id, state.session_id)
        # Domain-aware correction (hybrid glossary) feeds BOTH the improved stage
        # and the committed text.final / downstream turn, so captured facts use the
        # corrected wording. The raw transcript.partial below stays untouched, so no
        # latency is added to what the expert sees first. Gated by config.
        corrected_text = text
        if text and settings.voice_transcript_rewrite_enabled:
            try:
                glossary = resolve_glossary(workspace, capture_session, state.last_retrieval_chunks)
                if not glossary.is_empty:
                    corrected_text = await correct_transcript_segment(
                        text,
                        glossary,
                        llm_enabled=settings.voice_transcript_rewrite_llm_enabled,
                        timeout_ms=settings.voice_transcript_rewrite_timeout_ms,
                        workspace_id=workspace.id,
                    )
            except Exception:
                corrected_text = text
        if text:
            # Plan-aware reformulation: reframe the corrected chunk against the relevant
            # plan topic, not just disfluency cleanup. The UI labels it via reframed=True.
            plan_topic_label = self._active_plan_topic_label(capture_session)
            improved_text = reframe_transcript_segment(corrected_text, plan_topic_label=plan_topic_label)
            await self._send(
                websocket,
                state,
                "transcript.partial",
                {"segment_id": segment_id, "turn_id": state.client_turn_id, "text": text},
            )
            await self._send(
                websocket,
                state,
                "transcript.improved",
                {
                    "segment_id": segment_id,
                    "turn_id": state.client_turn_id,
                    "text": improved_text,
                    "reframed": True,
                },
            )
        await self._send(
            websocket,
            state,
            "text.final",
            {
                "turn_id": state.client_turn_id,
                "speaker": "expert",
                "text": corrected_text,
                "empty": not bool(text),
                "reason": None if text else (ignored_reason or "empty_transcript"),
                "confidence": transcript.get("confidence"),
                "latency_ms": first_text_ms,
                "source": f"{transcript.get('provider') or state.runtime}_stt",
                "provider": transcript.get("provider") or state.runtime,
                "requested_provider": transcript.get("requested_provider") or state.runtime,
                "model": transcript.get("model") or state.model,
                "fallback_used": bool(transcript.get("fallback")),
            },
        )
        await self._send(
            websocket,
            state,
            "runtime.metric",
            {
                "metric": "time_to_first_text",
                "value_ms": first_text_ms,
                "turn_id": state.client_turn_id,
                "provider": transcript.get("provider") or state.runtime,
                "model": transcript.get("model") or state.model,
                "transport": state.transport,
                "fallback_used": bool(transcript.get("fallback")),
            },
        )

        if capture_session and text:
            turn_started = time.perf_counter()
            if state.mode == "conversation_only":
                result = process_conversation_step(
                    db,
                    workspace_id=workspace.id,
                    session_id=capture_session.id,
                    client_turn_id=state.client_turn_id,
                    text=corrected_text,
                    question_id=state.question_id,
                    retrieval_event_id=state.retrieval_event_id,
                    interruption_of_event_id=state.interruption_of_event_id,
                    last_proposal_id=state.last_proposal_id,
                    actor_user_id=user.id,
                    actor_label=self._actor_label(user),
                    contradiction_candidates=state.last_contradiction_candidates,
                )
                proposal_payload = result.get("proposal") if isinstance(result.get("proposal"), dict) else None
                if proposal_payload and proposal_payload.get("id"):
                    state.last_proposal_id = str(proposal_payload["id"])
            else:
                result = append_turn(
                    db,
                    workspace_id=workspace.id,
                    session_id=capture_session.id,
                    speaker="expert",
                    text=corrected_text,
                    question_id=state.question_id,
                    client_turn_id=state.client_turn_id,
                    retrieval_event_id=state.retrieval_event_id,
                    interruption_of_event_id=state.interruption_of_event_id,
                    turn_kind="correction" if state.interruption_of_event_id else "answer",
                    actor_user_id=user.id,
                    text_partials=state.text_partials[-5:],
                    latency_ms=latency,
                    contradiction_candidates=state.last_contradiction_candidates,
                )
            turn_to_prompt_ms = int((time.perf_counter() - turn_started) * 1000)
            self._merge_capture_metrics(db, workspace.id, capture_session.id, {**latency, "turn_end_to_prompt": turn_to_prompt_ms})
            # Oracle live payload (non-blocking): the AI's own sorted open_questions, the
            # passive optional suggestions, and the plan/question-contextualized retrieval.
            oracle_suggestions = result.get("suggestions") or []
            oracle_open_questions = result.get("open_questions")
            if not oracle_open_questions:
                refreshed = self._capture_session(db, workspace.id, state.session_id)
                oracle_open_questions = build_open_questions(
                    refreshed,
                    contradiction_candidates=state.last_contradiction_candidates,
                ) if refreshed else []
            oracle_retrieval = {
                "chunks": format_retrieval_chunks(
                    state.last_retrieval_chunks,
                    state.last_retrieval_metadatas,
                    state.last_retrieval_scores,
                )
            }
            if state.mode == "conversation_only":
                await self._send(
                    websocket,
                    state,
                    "conversation.step",
                    {
                        "turn_id": state.client_turn_id,
                        "intent": result.get("intent"),
                        "confidence": result.get("confidence"),
                        "action_taken": result.get("action_taken"),
                        "session": result.get("session"),
                        "proposal": result.get("proposal"),
                        "requires_confirmation": result.get("requires_confirmation"),
                        "confirmation_target": result.get("confirmation_target"),
                        "closure_sheet": result.get("closure_sheet"),
                        "next_prompt": result.get("next_prompt"),
                        "next_question_id": result.get("next_question_id"),
                        "relance": result.get("relance") or {"kind": None, "text": None},
                        "suggestions": oracle_suggestions,
                        "open_questions": oracle_open_questions,
                        "retrieval": oracle_retrieval,
                    },
                )
            await self._send(
                websocket,
                state,
                "evaluation.delta",
                {
                    "turn_id": state.client_turn_id,
                    "evaluation": result.get("evaluation"),
                    "relance": result.get("relance") or {"kind": None, "text": None},
                    "suggestions": oracle_suggestions,
                    "open_questions": oracle_open_questions,
                    "retrieval": oracle_retrieval,
                    "next_question_id": result.get("next_question_id"),
                    "session": result.get("session"),
                    "proposal": result.get("proposal"),
                    "conversation_step": {
                        "intent": result.get("intent"),
                        "confidence": result.get("confidence"),
                        "action_taken": result.get("action_taken"),
                        "requires_confirmation": result.get("requires_confirmation"),
                        "confirmation_target": result.get("confirmation_target"),
                        "closure_sheet": result.get("closure_sheet"),
                        "next_prompt": result.get("next_prompt"),
                        "next_question_id": result.get("next_question_id"),
                    }
                    if state.mode == "conversation_only"
                    else None,
                },
            )
            if state.tandem_oracle_enabled:
                oracle_events = state.oracle.commit_final(
                    text,
                    turn_id=state.client_turn_id or str(uuid.uuid4()),
                    evaluation=result.get("evaluation") if isinstance(result.get("evaluation"), dict) else None,
                    next_prompt=result.get("next_prompt") if result.get("next_prompt") else None,
                    duration_ms=turn_to_prompt_ms,
                )
                await self._emit_oracle_events(
                    websocket,
                    db,
                    user=user,
                    workspace=workspace,
                    state=state,
                    events=oracle_events,
                )
            next_prompt = result.get("next_prompt")
            if next_prompt:
                await self._send(
                    websocket,
                    state,
                    "prompt.next",
                    {
                        "turn_id": state.client_turn_id,
                        "question_id": result.get("next_question_id") or state.question_id,
                        "text": next_prompt,
                        "reason": "capture_evaluator",
                        "speak": True,
                        "system_prompt_event_id": result.get("system_prompt_event_id"),
                    },
                )
                await self._send_prompt_audio(websocket, state, provider, str(next_prompt), started)
        elif state.tandem_oracle_enabled and text:
            oracle_events = state.oracle.commit_final(
                text,
                turn_id=state.client_turn_id or str(uuid.uuid4()),
                duration_ms=first_text_ms,
            )
            await self._emit_oracle_events(websocket, db, user=user, workspace=workspace, state=state, events=oracle_events)

        state.turn_started_at = None
        state.endpoint_at = None
        state.text_partials = []
        state.client_turn_id = None
        state.retrieval_event_id = None
        state.interruption_of_event_id = None
        state.last_contradiction_candidates = []
        state.last_retrieval_chunks = []
        state.last_retrieval_metadatas = []
        state.last_retrieval_scores = []
        self._reset_partial_stt_state(state)

    async def _send_prompt_audio(
        self,
        websocket: WebSocket,
        state: VoiceSessionState,
        provider: Any,
        text: str,
        started: float,
    ) -> None:
        try:
            speech = await provider.synthesize_bytes(text[:600])
        except VoiceProviderError as exc:
            await self._send_error(websocket, exc.code, str(exc), state=state)
            return
        except Exception as exc:
            await self._send_error(websocket, "synthesize_failed", str(exc), state=state)
            return
        first_audio_ms = int((time.perf_counter() - started) * 1000)
        await self._send(
            websocket,
            state,
            "runtime.metric",
            {
                "metric": "time_to_first_audio",
                "value_ms": first_audio_ms,
                "turn_id": state.client_turn_id,
                "provider": speech.get("provider") or state.runtime,
                "model": speech.get("model") or state.model,
                "transport": state.transport,
                "fallback_used": bool(speech.get("fallback")),
            },
        )
        await self._send(
            websocket,
            state,
            "audio.out",
            {
                "turn_id": state.client_turn_id,
                "content_type": speech.get("content_type") or "audio/mpeg",
                "audio_base64": speech.get("audio_base64"),
                "bytes": speech.get("bytes"),
                "model": speech.get("model"),
                "provider": speech.get("provider") or state.runtime,
                "requested_provider": speech.get("requested_provider") or state.runtime,
                "fallback_used": bool(speech.get("fallback")),
                "latency_ms": first_audio_ms,
            },
        )

    async def _emit_oracle_events(
        self,
        websocket: WebSocket,
        db: DBSession,
        *,
        user: User,
        workspace: Workspace,
        state: VoiceSessionState,
        events: list[Dict[str, Any]],
    ) -> None:
        for event in events:
            event_type = str(event.get("type") or "")
            payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
            enriched = {
                **payload,
                "provider": payload.get("provider") or state.runtime,
                "transport": payload.get("transport") or state.transport,
                "capability": payload.get("capability") or state.capability,
            }
            await self._send(websocket, state, event_type, enriched)
            if event_type == "oracle.action":
                emit_audit_event(
                    workspace_id=workspace.id,
                    event_type="voice.oracle.action",
                    actor=user.email or user.username or user.id,
                    details={
                        "session_id": state.session_id,
                        "turn_id": enriched.get("turn_id"),
                        "partial_seq": enriched.get("partial_seq"),
                        "oracle_id": enriched.get("oracle_id"),
                        "action": enriched.get("action"),
                        "reason": enriched.get("reason"),
                        "policy": "latest_oracle_wins",
                        "provider": state.runtime,
                        "transport": state.transport,
                    },
                )

    @staticmethod
    def _oracle_partial_seq(events: list[Dict[str, Any]]) -> Optional[int]:
        for event in events:
            if event.get("type") == "oracle.delta":
                payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
                try:
                    return int(payload.get("partial_seq"))
                except (TypeError, ValueError):
                    return None
        return None

    def _merge_capture_metrics(
        self,
        db: DBSession,
        workspace_id: str,
        session_id: str,
        latency: Dict[str, Any],
    ) -> None:
        try:
            session = get_session(db, workspace_id=workspace_id, session_id=session_id)
            metrics = dict(session.metrics or {})
            voice_metrics = dict(metrics.get("voice_stream") or {})
            voice_metrics["last_latency_ms"] = latency
            voice_metrics["turns"] = int(voice_metrics.get("turns") or 0) + 1
            voice_metrics["runtime_provider"] = latency.get("runtime_provider")
            voice_metrics["runtime_requested_provider"] = latency.get("runtime_requested_provider")
            voice_metrics["fallback_used"] = latency.get("fallback_used")
            metrics["voice_stream"] = voice_metrics
            session.metrics = metrics
            db.commit()
        except Exception:
            db.rollback()

    @staticmethod
    def _actor_label(user: User) -> str:
        return user.email or user.username or user.id

    def _authenticate(
        self,
        db: DBSession,
        *,
        token: Optional[str],
        workspace_slug: Optional[str],
        session_id: Optional[str] = None,
    ) -> Optional[tuple[User, Workspace]]:
        if not token:
            return None
        raw = token.strip()
        if raw.lower().startswith("bearer "):
            raw = raw[7:].strip()
        bridge_auth = self._authenticate_livekit_bridge(db, token=raw, workspace_slug=workspace_slug, session_id=session_id)
        if bridge_auth:
            return bridge_auth
        try:
            payload = decode_token(raw)
        except HTTPException:
            return None
        keycloak_sub = payload.get("sub")
        preferred_username = payload.get("preferred_username", keycloak_sub)
        user = db.query(User).filter(User.keycloak_sub == keycloak_sub).first() if keycloak_sub else None
        if not user and preferred_username:
            user = db.query(User).filter(User.username == preferred_username).first()
        if not user:
            return None
        workspace_query = db.query(Workspace).filter(
            Workspace.is_active == True,  # noqa: E712
            Workspace.deleted_at.is_(None),
        )
        if workspace_slug:
            workspace = workspace_query.filter(Workspace.slug == workspace_slug).first()
        else:
            membership = (
                db.query(WorkspaceMember)
                .join(Workspace, Workspace.id == WorkspaceMember.workspace_id)
                .filter(WorkspaceMember.user_id == user.id, Workspace.is_active == True, Workspace.deleted_at.is_(None))  # noqa: E712
                .order_by(WorkspaceMember.joined_at.asc())
                .first()
            )
            workspace = db.query(Workspace).filter(Workspace.id == membership.workspace_id).first() if membership else None
        if not workspace:
            return None
        membership = (
            db.query(WorkspaceMember)
            .filter(WorkspaceMember.user_id == user.id, WorkspaceMember.workspace_id == workspace.id)
            .first()
        )
        if not membership:
            return None
        return user, workspace

    def _authenticate_livekit_bridge(
        self,
        db: DBSession,
        *,
        token: str,
        workspace_slug: Optional[str],
        session_id: Optional[str],
    ) -> Optional[tuple[User, Workspace]]:
        try:
            claims = LiveKitService().decode_voice_bridge_token(token, session_id=session_id)
        except LiveKitServiceError:
            return None
        user_id = str(claims.get("user_id") or claims.get("sub") or "")
        token_workspace_id = str(claims.get("workspace_id") or "")
        token_workspace_slug = str(claims.get("workspace_slug") or "")
        if workspace_slug and token_workspace_slug and workspace_slug != token_workspace_slug:
            return None
        user = db.query(User).filter(User.id == user_id, User.is_active == True).first() if user_id else None  # noqa: E712
        workspace_query = db.query(Workspace).filter(
            Workspace.is_active == True,  # noqa: E712
            Workspace.deleted_at.is_(None),
        )
        workspace = None
        if token_workspace_id:
            workspace = workspace_query.filter(Workspace.id == token_workspace_id).first()
        if not workspace and token_workspace_slug:
            workspace = workspace_query.filter(Workspace.slug == token_workspace_slug).first()
        if not user or not workspace:
            return None
        membership = (
            db.query(WorkspaceMember)
            .filter(WorkspaceMember.user_id == user.id, WorkspaceMember.workspace_id == workspace.id)
            .first()
        )
        if not membership:
            return None
        return user, workspace

    @staticmethod
    def _active_plan_topic_label(capture_session: Optional[ExpertCaptureSession]) -> Optional[str]:
        if not capture_session:
            return None
        plan = capture_session.plan or {}
        metrics = capture_session.metrics or {}
        active_subtopic_id = metrics.get("active_subtopic_id")
        topics = plan.get("topics") or []
        for topic in topics:
            for subtopic in topic.get("subtopics") or []:
                if subtopic.get("id") == active_subtopic_id:
                    topic_title = (topic.get("title") or "").strip()
                    subtopic_title = (subtopic.get("title") or "").strip()
                    if topic_title and subtopic_title:
                        return f"{topic_title} / {subtopic_title}"
                    return subtopic_title or topic_title or None
        if topics:
            return (topics[0].get("title") or "").strip() or None
        return None

    def _retrieval_query_context(self, capture_session: Optional[ExpertCaptureSession]) -> str:
        """Build query-expansion terms from the active plan topic and the oracle's
        open_questions so live retrieval is plan/question-aware."""
        if not capture_session:
            return ""
        parts: list[str] = []
        label = self._active_plan_topic_label(capture_session)
        if label:
            parts.append(label)
        try:
            open_questions = build_open_questions(capture_session)
        except Exception:
            open_questions = []
        for item in [q for q in open_questions if q.get("status") != "addressed"][:3]:
            text = str(item.get("text") or "").strip()
            if text:
                parts.append(text)
        return " ".join(parts).strip()

    def _capture_session(
        self,
        db: DBSession,
        workspace_id: str,
        session_id: str,
    ) -> Optional[ExpertCaptureSession]:
        return (
            db.query(ExpertCaptureSession)
            .filter(ExpertCaptureSession.id == session_id, ExpertCaptureSession.workspace_id == workspace_id)
            .first()
        )

    async def _send_error(
        self,
        websocket: WebSocket,
        code: str,
        message: str,
        *,
        state: Optional[VoiceSessionState] = None,
    ) -> None:
        await self._send(
            websocket,
            state or VoiceSessionState(session_id="unknown"),
            "session.error",
            {"code": code, "message": message},
        )

    async def _send(
        self,
        websocket: WebSocket,
        state: VoiceSessionState,
        event_type: str,
        payload: Dict[str, Any],
    ) -> None:
        async with state.send_lock:
            state.sequence += 1
            await websocket.send_json(
                {
                    "id": str(uuid.uuid4()),
                    "session_id": state.session_id,
                    "type": event_type,
                    "ts_ms": int(time.time() * 1000),
                    "sequence": state.sequence,
                    "payload": payload,
                }
            )
