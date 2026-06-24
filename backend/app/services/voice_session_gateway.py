"""WebSocket gateway for streaming-compatible voice sessions.

J1 keeps the cascade provider as the concrete runtime while introducing the
protocol shape needed for lower-latency voice loops: typed events, inner
monologue text track, minimal latency metrics and HTTP fallback compatibility.
"""
from __future__ import annotations

import asyncio
import base64
import inspect
import math
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

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
    _load_context,
    _resolve_collection_name,
    _retrieve_context_chunks,
    _retrieve_context_chunks_async,
    append_turn,
    build_open_questions,
    finalize_capture,
    finalize_capture_section,
    format_retrieval_chunks,
    get_session,
    is_capture_text_noise,
    process_capture_partial_hints,
    run_capture_finalize_index,
    serialize_proposal,
    serialize_session,
    set_active_capture_section,
)
from app.services.voice_runtime import (
    VoiceProviderError,
    get_voice_runtime_provider,
    resolve_voice_runtime_slug,
)
from app.services.livekit_service import LiveKitService, LiveKitServiceError
from app.services.voice_tandem_oracle import VoiceTandemOracle


logger = get_logger(__name__)
_ORIGINAL_RETRIEVE_CONTEXT_CHUNKS = _retrieve_context_chunks

# The only AI utterance allowed during capture: a timeline relance fired on
# section.finish. No content questions, no oracle relances.
SECTION_FINISH_RELANCE = "Avez-vous terminé cette section ? Souhaitez-vous continuer ?"

# User-facing message when the endpoint/pause STT fails on a segment. The raw
# provider error (e.g. OpenAI "Audio file might be corrupted") is logged
# server-side but never forwarded to the UI.
_STT_SEGMENT_FAILED_MESSAGE = (
    "La transcription a échoué sur ce segment audio. Reprenez la parole, la capture continue."
)


def _resolve_rewrite_context(workspace: Workspace) -> str:
    """Static FINAL-reformulation framing, workspace-overridable."""
    settings_obj = getattr(workspace, "settings", None)
    if isinstance(settings_obj, dict):
        voice_cfg = settings_obj.get("voice")
        if isinstance(voice_cfg, dict):
            override = str(voice_cfg.get("transcript_rewrite_context") or "").strip()
            if override:
                return override
    return str(getattr(settings, "voice_transcript_rewrite_context", "") or "").strip()


def _provider_accepts_language(provider: Any) -> bool:
    try:
        signature = inspect.signature(provider.transcribe)
    except (TypeError, ValueError):
        return True
    parameters = signature.parameters
    return "language" in parameters or any(
        param.kind == inspect.Parameter.VAR_KEYWORD
        for param in parameters.values()
    )


# EBML magic at offset 0 of a WebM container ("\x1a\x45\xdf\xa3"). Only the
# FIRST blob produced by a MediaRecorder carries the EBML/Segment header; any
# later chunk is a continuation cluster that is unparseable on its own.
_EBML_MAGIC = b"\x1a\x45\xdf\xa3"


def _is_webm_header(chunk: bytes) -> bool:
    """True when the chunk starts a valid WebM stream (EBML magic at offset 0)."""
    return chunk[:4] == _EBML_MAGIC


async def _transcribe_audio(
    provider: Any,
    audio_bytes: bytes,
    *,
    filename: str,
    content_type: str,
    language: str,
) -> Dict[str, Any]:
    kwargs: Dict[str, Any] = {
        "filename": filename,
        "content_type": content_type,
    }
    if _provider_accepts_language(provider):
        kwargs["language"] = language
    return await provider.transcribe(audio_bytes, **kwargs)


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
    live_partial_stt_enabled: bool = True
    live_questions_enabled: bool = True
    partial_stt_min_interval_ms: int = field(default_factory=lambda: _PARTIAL_STT_MIN_INTERVAL_MS)
    oracle: VoiceTandemOracle = field(default_factory=VoiceTandemOracle)
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    last_contradiction_candidates: list[Dict[str, Any]] = field(default_factory=list)
    last_retrieval_chunks: list[str] = field(default_factory=list)
    last_retrieval_metadatas: list[Dict[str, Any]] = field(default_factory=list)
    last_retrieval_scores: list[float] = field(default_factory=list)
    last_partial_stt_at: Optional[float] = None
    partial_stt_in_flight: bool = False
    # Monotonic generation for the offloaded incremental STT: bumped on every
    # _reset_partial_stt_state (endpoint, pause, barge-in, new utterance) so a
    # background STT task that completes AFTER the turn ended can detect it is
    # stale and drop its result instead of corrupting the next turn's state.
    partial_stt_generation: int = 0
    # Strong references to in-flight incremental STT tasks (fire-and-forget
    # asyncio tasks may otherwise be garbage-collected mid-run).
    partial_stt_tasks: set[asyncio.Task] = field(default_factory=set)
    # Strong references to offloaded FINAL-phase tasks (section.finish /
    # capture.finish). These run multi-LLM finalization and must never execute
    # inline on the receive loop (see _handle_event).
    finalize_tasks: set[asyncio.Task] = field(default_factory=set)
    # Serializes shared per-connection DB session use between the receive loop
    # (audio.endpoint persistence) and the offloaded incremental STT task.
    db_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    last_partial_text: str = ""
    last_partial_chunk_count: int = 0
    # Number of buffered audio chunks that produced the currently committed
    # ``last_partial_text``. Used at endpoint time to reuse the latest full-buffer
    # partial as the basis for ``text.final`` (skipping a redundant STT pass) when
    # no new audio arrived since that partial.
    last_partial_text_chunk_count: int = 0
    # Active plan section (set by section.select); used to tag captured turns so
    # the FINAL per-section reformulation maps them to the plan hierarchy.
    active_topic_id: Optional[str] = None
    active_subtopic_id: Optional[str] = None
    # Live oracle open questions (QUESTIONS IA panel during capture): expert
    # turn texts committed in the CURRENT section (reset when the active section
    # changes), the section key those texts belong to, plus throttle/in-flight
    # bookkeeping for the fire-and-forget question generation task. The latest
    # generated questions are kept so per-turn evaluation.delta re-sends them
    # instead of wiping the panel with an empty list.
    committed_turn_texts: list[str] = field(default_factory=list)
    committed_turns_section: Optional[str] = None
    live_questions_in_flight: bool = False
    last_live_questions_at: Optional[float] = None
    live_open_questions: list[Dict[str, Any]] = field(default_factory=list)
    live_questions_generation: int = 0
    live_questions_tasks: set[asyncio.Task] = field(default_factory=set)
    # Manual section.select locks auto-detection on the gateway for N seconds so
    # a left-rail click is not immediately overridden by speech overlap.
    manual_section_until: Optional[float] = None
    last_live_section_detect_at: Optional[float] = None
    last_live_section_emit_at: Optional[float] = None
    # Throttle for the orphan-frame-dropped debug print (at most one per second
    # per session) — late MediaRecorder continuation frames can arrive in bursts.
    last_orphan_drop_log_at: Optional[float] = None
    # Client-side audio/VAD metrics are diagnostic only and must never compete
    # with the hot audio path. Unknown metrics are ignored and accepted metrics
    # are lightly throttled per connection.
    last_client_metric_at: Optional[float] = None
    # Realtime lane: live partials (gpt-realtime-whisper deltas) arrive far more
    # often than the batch incremental STT cadence, so the grounded retrieval
    # hint pass is throttled per session to avoid a retrieval storm. Reset on
    # every turn so a fresh utterance grounds promptly.
    last_capture_hints_at: Optional[float] = None
    # The grounded-hint retrieval (embeddings + vector search + reranker + sync
    # contradiction post-processing) must NEVER run on the transcript-relay path:
    # awaiting it inline per partial stalled the event loop and froze the live
    # transcript on a fragment. It now runs fire-and-forget, guarded so at most
    # one is in flight per session (it only feeds passive state.last_retrieval_*).
    live_hints_in_flight: bool = False
    # Capture session resolution cache: the capture session id equals
    # ``session_id`` and only its ``plan`` is needed on the hot partial/turn path
    # (live section detection), so the growing capture row is loaded ONCE and its
    # plan cached here instead of being re-queried per partial and per turn.
    capture_plan: Optional[dict] = None
    capture_session_resolved: bool = False
    # RAG collection for the oracle's per-turn retrieval, resolved lazily ONCE
    # per session (DB context lookup off-loop via to_thread) and reused so the
    # worker-backed retrieval never re-hits the DB on the realtime loop.
    retrieval_collection_name: Optional[str] = None
    # Total committed words at the last live-questions generation: the oracle
    # questions are triggered by NEW-word accumulation (decoupled from the short
    # realtime STT turns), reset when the active section changes.
    last_questions_word_count: int = 0


# Cadence of the server-side incremental transcription. The live preview
# re-transcribes the WHOLE growing buffer on each tick (webm/opus clusters are
# not independently decodable, so true delta/windowed STT is unsafe — see
# TASK 1 rationale in ``_handle_audio_endpoint``). A larger interval is the
# robust lever to reduce churn: a long answer now refreshes a handful of times
# instead of 10-20. Resolved from settings at import (tests monkeypatch this
# module global directly, so reading it keeps that override working).
_PARTIAL_STT_MIN_INTERVAL_MS = int(
    getattr(settings, "voice_partial_stt_min_interval_ms", 4000) or 4000
)

# Hard ceiling on ONE incremental (partial) STT round-trip. The live preview is
# advisory only: when the provider degrades (observed: 79.4 s on an 800 KB
# buffer, trace 24a345) the partial is dropped silently instead of pinning the
# per-session in-flight slot — the endpoint's authoritative STT still produces
# text.final. The endpoint STT deliberately has NO timeout.
_PARTIAL_STT_TIMEOUT_S = 15.0

# Minimum interval between two live grounded-question generations for a session.
# The generation is an LLM round-trip fired in the background after a committed
# capture turn; throttling keeps it to at most one call every N seconds.
_LIVE_QUESTIONS_MIN_INTERVAL_S = 20.0
# Oracle context/trigger decoupled from the short realtime STT turns: the
# question context is the last ~N committed WORDS (richer than a sliding window
# of tiny VAD-sized turns) and a new generation only fires once enough NEW words
# accumulated since the last one OR the time throttle elapsed.
_LIVE_QUESTIONS_CONTEXT_WORDS = 1000
_LIVE_QUESTIONS_MIN_NEW_WORDS = 60

# Live plan-section detection: lightweight title overlap only (no LLM). Partial
# emits are throttled; turn commits always run detection once.
_LIVE_SECTION_DETECT_PARTIAL_INTERVAL_S = 30.0
_MANUAL_SECTION_OVERRIDE_COOLDOWN_S = 60.0
# Minimum interval between two grounded retrieval hint passes driven by live
# partials (realtime lane). The batch incremental STT already throttles itself
# to ``_PARTIAL_STT_MIN_INTERVAL_MS``; this guards the direct text.partial path.
_CAPTURE_HINTS_MIN_INTERVAL_S = 3.0
_CLIENT_METRIC_MIN_INTERVAL_S = 0.15
_CLIENT_CAPTURE_METRICS = {
    "chunk_gap_ms",
    "chunk_size",
    "send_audio_frame_ms",
    "rms",
    "noise_floor",
    "threshold",
    "endpoint_candidate",
    "endpoint_confirmed",
    "endpoint_cancelled",
    "endpoint_reason",
}


def _coerce_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _coerce_int_range(value: Any, default: int, *, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


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
            self._sync_voice_state_from_capture_session(state, capture_session)

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
            state.tandem_oracle_enabled = _coerce_bool(payload.get("tandem_oracle"), True)
            oracle_config = payload.get("oracle") if isinstance(payload.get("oracle"), dict) else {}
            state.live_partial_stt_enabled = _coerce_bool(
                oracle_config.get("live_partial_stt_enabled"),
                state.tandem_oracle_enabled,
            )
            state.live_questions_enabled = _coerce_bool(
                oracle_config.get("live_questions_enabled"),
                state.tandem_oracle_enabled,
            )
            state.partial_stt_min_interval_ms = _coerce_int_range(
                oracle_config.get("partial_stt_min_interval_ms"),
                _PARTIAL_STT_MIN_INTERVAL_MS,
                minimum=0,
                maximum=120_000,
            )
            state.oracle = VoiceTandemOracle(
                min_interval_ms=_coerce_int_range(
                    oracle_config.get("min_interval_ms"),
                    350,
                    minimum=0,
                    maximum=120_000,
                ),
                min_delta_chars=_coerce_int_range(
                    oracle_config.get("min_delta_chars"),
                    24,
                    minimum=0,
                    maximum=10_000,
                ),
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
                    "live_partial_stt_enabled": state.live_partial_stt_enabled,
                    "partial_stt_min_interval_ms": state.partial_stt_min_interval_ms,
                    "live_questions_enabled": state.live_questions_enabled,
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
        if event_type == "audio.pause":
            await self._handle_audio_pause(websocket, db, user=user, workspace=workspace, state=state, payload=payload)
            return
        if event_type == "client.metric":
            await self._handle_client_metric(websocket, db, user=user, workspace=workspace, state=state, payload=payload)
            return
        if event_type == "section.select":
            await self._handle_section_select(websocket, db, workspace=workspace, state=state, payload=payload)
            return
        if event_type == "section.finish":
            # FINAL-phase work (chat-grade retrieval + LLM reformulation + grounded
            # questions) must NEVER run inline on the receive loop: the loop awaits
            # one handler at a time, so every queued WS message — audio.endpoint
            # included — would stall behind the finalization for its whole
            # multi-LLM duration (root cause of the 31 s endpoint entry delay in
            # trace 24a345). Offload it; conversation.step is emitted by the task
            # when the finalization completes.
            task = asyncio.create_task(
                self._handle_section_finish(websocket, db, user=user, workspace=workspace, state=state, payload=payload)
            )
            state.finalize_tasks.add(task)
            task.add_done_callback(state.finalize_tasks.discard)
            return
        if event_type == "capture.finish":
            # Same offload rationale as section.finish above.
            task = asyncio.create_task(
                self._handle_capture_finish(websocket, db, user=user, workspace=workspace, state=state, payload=payload)
            )
            state.finalize_tasks.add(task)
            task.add_done_callback(state.finalize_tasks.discard)
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

    async def _handle_client_metric(
        self,
        websocket: WebSocket,
        db: Session,
        *,
        user: User,
        workspace: Workspace,
        state: VoiceSessionState,
        payload: Dict[str, Any],
    ) -> None:
        metric = str(payload.get("metric") or "").strip()
        if metric not in _CLIENT_CAPTURE_METRICS:
            return
        now = time.perf_counter()
        if state.last_client_metric_at is not None and now - state.last_client_metric_at < _CLIENT_METRIC_MIN_INTERVAL_S:
            return
        state.last_client_metric_at = now
        forwarded: Dict[str, Any] = {
            "metric": metric,
            "source": "client_capture",
            "runtime": state.runtime,
            "transport": state.transport,
            "turn_id": payload.get("turn_id") or state.client_turn_id,
        }
        for key in (
            "value_ms",
            "value",
            "chunk_gap_ms",
            "chunk_size",
            "send_audio_frame_ms",
            "rms",
            "rms_p50",
            "rms_p95",
            "noise_floor",
            "threshold",
            "silence_ms",
            "min_speech_ms",
            "endpoint_grace_ms",
            "since_voice_ms",
        ):
            value = payload.get(key)
            if isinstance(value, (int, float)) and math.isfinite(float(value)):
                forwarded[key] = value
        for key in ("capture_mode", "endpoint_reason", "surface", "visibility_state", "network_effective_type"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                forwarded[key] = value.strip()[:80]
        for key in ("auto_endpoint", "cancelled"):
            value = payload.get(key)
            if isinstance(value, bool):
                forwarded[key] = value
        emit_audit_event(
            workspace_id=workspace.id,
            event_type="voice.client_metric",
            actor=user.email or user.username or user.id,
            details={
                "session_id": state.session_id,
                **forwarded,
            },
            db=db,
        )
        await self._send(websocket, state, "runtime.metric", forwarded)

    @staticmethod
    def _reset_partial_stt_state(state: VoiceSessionState) -> None:
        state.last_partial_stt_at = None
        state.partial_stt_in_flight = False
        state.last_partial_text = ""
        state.last_partial_chunk_count = 0
        state.last_partial_text_chunk_count = 0
        state.last_capture_hints_at = None
        # Invalidate any offloaded incremental STT still in flight: when it
        # completes it compares its captured generation against this counter and
        # drops its (now stale) result.
        state.partial_stt_generation += 1

    def _reset_turn_after_stt_failure(self, state: VoiceSessionState) -> None:
        """Leave the session clean after a failed endpoint/pause STT.

        The buffer was already drained before the STT call; reset the turn and
        partial bookkeeping too so the NEXT utterance starts from scratch (no
        dead buffer, no stale reuse-partial text, no stale turn id) instead of
        accumulating failures for the rest of the session (trace 24a345)."""
        state.audio_chunks = []
        state.turn_started_at = None
        state.endpoint_at = None
        state.text_partials = []
        state.client_turn_id = None
        self._reset_partial_stt_state(state)

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
        # Header-validated buffer start (fix 24a345): a WebM buffer is only
        # decodable when chunk 0 carries the EBML/Segment header. MediaRecorder
        # keeps delivering in-flight continuation frames after a pause-flush
        # cleared the buffer; if such a headerless frame became the new chunk 0,
        # EVERY subsequent join would be an unparseable container (STT 400 for
        # the rest of the session). Drop headerless frames while the buffer is
        # empty — the next valid header chunk (from the resumed recorder)
        # becomes chunk 0 automatically, so the session self-heals. Gate on the
        # payload content type too: the browser fallback can send WebM chunks even
        # when the LiveKit room negotiated opus for the transport envelope.
        negotiated_input_codec = str((state.codec or {}).get("input") or "").lower()
        frame_content_type = str(payload.get("content_type") or payload.get("encoding") or "").lower()
        frame_is_webm = negotiated_input_codec == "webm" or "webm" in frame_content_type
        if (
            not state.audio_chunks
            and frame_is_webm
            and not _is_webm_header(chunk)
        ):
            now = time.perf_counter()
            if (
                state.last_orphan_drop_log_at is None
                or (now - state.last_orphan_drop_log_at) >= 1.0
            ):
                state.last_orphan_drop_log_at = now
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
        else:
            # Safety net: if the frontend rotated its turn id while the buffer is
            # still open (residual mismatch path; pause now flushes the segment so
            # this should not happen in normal flows), adopt the new id so
            # text.final is never emitted under a stale turn id the frontend
            # cannot match (trace 24a345: 524e65aa kept owning later turns).
            frame_turn_id = payload.get("turn_id") or payload.get("client_turn_id")
            if frame_turn_id and str(frame_turn_id) != state.client_turn_id:
                state.client_turn_id = str(frame_turn_id)
        state.audio_chunks.append(chunk)
        if payload.get("incremental_transcription") is False or not state.live_partial_stt_enabled:
            return
        # Fire-and-forget: the incremental STT (0.5-3 s, grows with the buffer)
        # must NEVER run inline on the receive loop, otherwise audio.endpoint
        # control messages queue behind unread audio.frame messages for the whole
        # STT duration. The partial_stt_in_flight guard (checked synchronously at
        # the start of the task, before its first await) keeps at most one
        # incremental STT in flight per session.
        task = asyncio.create_task(
            self._maybe_run_incremental_transcription(
                websocket, db, user=user, workspace=workspace, state=state
            )
        )
        state.partial_stt_tasks.add(task)
        task.add_done_callback(state.partial_stt_tasks.discard)

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
        if not state.live_partial_stt_enabled or state.partial_stt_in_flight:
            return
        chunk_count = len(state.audio_chunks)
        if chunk_count < 1 or chunk_count <= state.last_partial_chunk_count:
            return
        now = time.perf_counter()
        if (
            state.last_partial_stt_at is not None
            and (now - state.last_partial_stt_at) * 1000.0 < state.partial_stt_min_interval_ms
        ):
            return
        audio_bytes = b"".join(state.audio_chunks)
        if not audio_bytes:
            return
        turn_id = state.client_turn_id or str(uuid.uuid4())
        state.client_turn_id = turn_id
        # In-flight guard: only one incremental STT runs at a time; new frames keep
        # buffering and a later tick picks them up. The generation snapshot lets us
        # detect, after the STT await, that the turn was endpointed/reset meanwhile.
        state.partial_stt_in_flight = True
        my_generation = state.partial_stt_generation
        gap_since_prev_ms = (
            int((now - state.last_partial_stt_at) * 1000.0) if state.last_partial_stt_at is not None else None
        )
        stt_started_at = time.perf_counter()

        async def emit_partial_metric(
            status: str,
            *,
            reason: Optional[str] = None,
            stt_ms: Optional[int] = None,
            text_len: Optional[int] = None,
        ) -> None:
            metric_payload: Dict[str, Any] = {
                "metric": "partial_stt",
                "status": status,
                "turn_id": turn_id,
                "source": "incremental",
                "transport": state.transport,
                "chunk_count": chunk_count,
                "audio_bytes": len(audio_bytes),
                "interval_floor_ms": state.partial_stt_min_interval_ms,
            }
            if reason:
                metric_payload["reason"] = reason
            if stt_ms is not None:
                metric_payload["value_ms"] = stt_ms
                metric_payload["stt_ms"] = stt_ms
            if text_len is not None:
                metric_payload["text_len"] = text_len
            if gap_since_prev_ms is not None:
                metric_payload["gap_since_prev_ms"] = gap_since_prev_ms
            try:
                await self._send(websocket, state, "runtime.metric", metric_payload)
            except Exception:
                logger.debug("partial STT metric emission failed", exc_info=True)

        try:
            provider = get_voice_runtime_provider(state.runtime, workspace_settings=workspace.settings)
        except VoiceProviderError:
            await emit_partial_metric("skipped", reason="provider_unavailable")
            if state.partial_stt_generation == my_generation:
                state.partial_stt_in_flight = False
            return
        state.last_partial_stt_at = now
        state.last_partial_chunk_count = chunk_count
        try:
            transcript = await asyncio.wait_for(
                _transcribe_audio(
                    provider,
                    audio_bytes,
                    filename=f"{turn_id}.webm",
                    content_type=state.content_type,
                    language=state.language or "fr",
                ),
                timeout=_PARTIAL_STT_TIMEOUT_S,
            )
        except asyncio.TimeoutError:
            # Degraded provider: drop this advisory partial silently; the
            # in-flight flag is cleared (generation-guarded) in the finally below
            # so the next frame can schedule a fresh partial.
            await emit_partial_metric(
                "timeout",
                reason="timeout",
                stt_ms=int((time.perf_counter() - stt_started_at) * 1000),
            )
            return
        except Exception as exc:
            await emit_partial_metric(
                "error",
                reason=exc.__class__.__name__,
                stt_ms=int((time.perf_counter() - stt_started_at) * 1000),
            )
            return
        finally:
            # Only clear the flag if no reset happened while we were transcribing:
            # after a reset, a NEW task may already own partial_stt_in_flight and
            # clearing it here would allow two concurrent incremental STTs.
            if state.partial_stt_generation == my_generation:
                state.partial_stt_in_flight = False
        # Staleness guard: the offloaded STT may complete AFTER the turn ended
        # (audio.endpoint / pause / barge-in reset the partial state and bumped the
        # generation, or a new turn replaced client_turn_id). Drop the result
        # silently — committing text/chunk counts here would emit a transcript for
        # a finished turn and corrupt the next turn's partial-reuse logic in
        # _handle_audio_endpoint.
        if state.partial_stt_generation != my_generation or state.client_turn_id != turn_id:
            await emit_partial_metric(
                "stale",
                reason="turn_reset",
                stt_ms=int((time.perf_counter() - stt_started_at) * 1000),
            )
            return

        text = str(transcript.get("text") or transcript.get("transcript") or "").strip()
        if is_capture_text_noise(text):
            await emit_partial_metric(
                "noise",
                reason="noise_text",
                stt_ms=int((time.perf_counter() - stt_started_at) * 1000),
                text_len=len(text),
            )
            return
        if not text or text == state.last_partial_text:
            # Even when the text is unchanged, the bytes that produced it match the
            # current buffer, so the endpoint can still reuse this committed partial.
            if text and text == state.last_partial_text:
                state.last_partial_text_chunk_count = chunk_count
            await emit_partial_metric(
                "duplicate" if text else "empty",
                reason="unchanged_text" if text else "empty_text",
                stt_ms=int((time.perf_counter() - stt_started_at) * 1000),
                text_len=len(text),
            )
            return
        state.last_partial_text = text
        # Pin the committed partial to the exact buffer size that produced it so the
        # endpoint can safely reuse it for text.final (identical bytes -> identical STT).
        state.last_partial_text_chunk_count = chunk_count
        state.text_partials.append(text)
        try:
            await self._send(
                websocket,
                state,
                "transcript.partial",
                {"segment_id": turn_id, "turn_id": turn_id, "text": text},
            )
            await emit_partial_metric(
                "emitted",
                stt_ms=int((time.perf_counter() - stt_started_at) * 1000),
                text_len=len(text),
            )
            if state.tandem_oracle_enabled:
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
            # Hint retrieval/mutation runs on its own DB session inside the
            # background task, so the endpoint path never waits on oracle
            # retrieval or a shared WebSocket DB lock.
            async with state.db_lock:
                if state.partial_stt_generation != my_generation:
                    return
                self._ensure_capture_plan(db, workspace.id, state)
            if state.capture_plan is not None:
                await self._maybe_push_capture_hints(
                    websocket,
                    db,
                    user=user,
                    workspace=workspace,
                    state=state,
                    capture_session_id=state.session_id,
                    partial_text=text,
                    generation=my_generation,
                )
        except Exception:
            # Fire-and-forget task: the websocket may have closed (or the hint
            # pass failed) while the STT ran; never let the task crash.
            logger.debug("incremental transcription post-processing failed", exc_info=True)

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
        self._ensure_capture_plan(db, workspace.id, state)
        if state.capture_plan is not None and text.strip() and not is_capture_text_noise(text):
            now = time.perf_counter()
            # Live hints retrieval is CPU-bound (embeddings + reranker) and runs
            # WHILE the expert speaks -> starves the realtime transcript relay
            # even off-thread (GIL). Gated off by default; section detection below
            # stays on (cheap, in-memory).
            if (
                settings.voice_oracle_live_hints_enabled
                and not state.live_hints_in_flight
                and (
                    state.last_capture_hints_at is None
                    or (now - state.last_capture_hints_at) >= _CAPTURE_HINTS_MIN_INTERVAL_S
                )
            ):
                state.last_capture_hints_at = now
                state.live_hints_in_flight = True
                hint_partial_text = text

                async def _run_capture_hints() -> None:
                    # Fire-and-forget: the grounded retrieval + sync contradiction
                    # pass is slow and MUST NOT block the transcript relay (it only
                    # accumulates passive state.last_retrieval_* / candidates).
                    try:
                        await self._maybe_push_capture_hints(
                            websocket,
                            db,
                            user=user,
                            workspace=workspace,
                            state=state,
                            capture_session_id=state.session_id,
                            partial_text=hint_partial_text,
                        )
                    except Exception:  # noqa: BLE001 - never surface on the hot path.
                        logger.debug("live capture hints task failed", exc_info=True)
                    finally:
                        state.live_hints_in_flight = False

                hints_task = asyncio.create_task(_run_capture_hints())
                state.live_questions_tasks.add(hints_task)
                hints_task.add_done_callback(state.live_questions_tasks.discard)
            try:
                await self._maybe_detect_and_emit_active_section(
                    websocket,
                    db,
                    workspace=workspace,
                    state=state,
                    plan=state.capture_plan,
                    partial_text=text,
                    source="partial",
                )
            except Exception as exc:  # noqa: BLE001 - live detection must never break the capture loop.
                logger.warning(
                    "voice_live_section_detect_failed",
                    error=str(exc),
                    session_id=state.session_id,
                )

    async def _maybe_push_capture_hints(
        self,
        websocket: WebSocket,
        db: DBSession,
        *,
        user: User,
        workspace: Workspace,
        state: VoiceSessionState,
        capture_session_id: str,
        partial_text: str,
        generation: Optional[int] = None,
    ) -> None:
        del websocket, db
        if len(partial_text.split()) < 6:
            return
        if generation is not None and state.partial_stt_generation != generation:
            return
        client_turn_id = state.client_turn_id
        try:
            from app.db.base import SessionLocal

            with SessionLocal() as hint_db:
                # get_session is a synchronous DB read; running it inline (even
                # inside this create_task'd coroutine) blocks the event loop and
                # stalls the transcript relay. Offload to a thread so the loop
                # stays free to ship text.partial/text.final.
                capture_snapshot = await asyncio.to_thread(
                    get_session,
                    hint_db,
                    workspace_id=workspace.id,
                    session_id=capture_session_id,
                    materialize=False,
                )
                # Contextualize live retrieval with the current plan topic AND the
                # active open_questions so retrieved chunks stay relevant to what
                # the plan cares about. This uses the independent DB snapshot,
                # never the WebSocket session/lock.
                query_context = self._retrieval_query_context(capture_snapshot)
                expanded_query = f"{partial_text} {query_context}".strip()
                if _retrieve_context_chunks is not _ORIGINAL_RETRIEVE_CONTEXT_CHUNKS:
                    chunks, metadatas, scores = await asyncio.to_thread(
                        _retrieve_context_chunks,
                        hint_db,
                        workspace_id=workspace.id,
                        workspace_slug=workspace.slug,
                        session=capture_snapshot,
                        query=expanded_query,
                        top_k=3,
                    )
                else:
                    chunks, metadatas, scores = await _retrieve_context_chunks_async(
                        hint_db,
                        workspace_id=workspace.id,
                        workspace_slug=workspace.slug,
                        session=capture_snapshot,
                        query=expanded_query,
                        top_k=3,
                        retrieval_profile="oracle_live_fast",
                    )
                if generation is not None and state.partial_stt_generation != generation:
                    return
                state.last_retrieval_chunks = list(chunks)
                state.last_retrieval_metadatas = list(metadatas or [])
                state.last_retrieval_scores = list(scores or [])
                # Contradiction tracking does embedding/DB work synchronously;
                # keep it off the event loop too.
                result = await asyncio.to_thread(
                    process_capture_partial_hints,
                    hint_db,
                    workspace_id=workspace.id,
                    session_id=capture_session_id,
                    partial_text=partial_text,
                    retrieval_chunks=chunks,
                    retrieval_metadatas=metadatas,
                    client_turn_id=client_turn_id,
                    actor_user_id=user.id,
                )
        except Exception:
            logger.debug("live capture hints failed", exc_info=True)
            return
        candidates = result.get("contradiction_candidates") or []
        if candidates:
            state.last_contradiction_candidates = candidates
        # Silent oracle (b2): during capture the oracle keeps running (retrieval +
        # contradiction tracking) and ACCUMULATES candidates/chunks into session
        # state, but it never pushes content hints/relances. The only AI utterance
        # during capture is the section.finish timeline relance. The passive
        # "contexte retrouvé" panel is still fed via state.last_retrieval_* above.

    async def _maybe_detect_and_emit_active_section(
        self,
        websocket: WebSocket,
        db: DBSession,
        *,
        workspace: Workspace,
        state: VoiceSessionState,
        plan: Optional[Dict[str, Any]],
        partial_text: str,
        source: str,
    ) -> Optional[Dict[str, Any]]:
        """Lightweight live section detector (title overlap, no LLM).

        Emits ``section.active`` when confidence is high enough and the suggested
        section differs from the gateway's active section. Partial-path emits are
        throttled; turn commits always evaluate once.
        """
        from app.services.capture_knowledge_oracle import (
            LIVE_SECTION_DETECT_MIN_CONFIDENCE,
            detect_active_section_from_text,
        )

        text = (partial_text or "").strip()
        if len(text.split()) < 6:
            return None
        now = time.monotonic()
        if source == "partial":
            if (
                state.last_live_section_detect_at is not None
                and (now - state.last_live_section_detect_at) < _LIVE_SECTION_DETECT_PARTIAL_INTERVAL_S
            ):
                return None
        state.last_live_section_detect_at = now

        plan_dict = dict(plan or {})
        detected = detect_active_section_from_text(
            plan_dict.get("topics") or [],
            text,
            fallback_subtopic_id=state.active_subtopic_id,
        )
        confidence = float(detected.get("confidence") or 0.0)
        subtopic_id = detected.get("subtopic_id")
        topic_id = detected.get("topic_id")
        if not subtopic_id or confidence < LIVE_SECTION_DETECT_MIN_CONFIDENCE:
            return None
        if str(subtopic_id) == str(state.active_subtopic_id or ""):
            return None
        if source == "partial":
            if (
                state.last_live_section_emit_at is not None
                and (now - state.last_live_section_emit_at) < _LIVE_SECTION_DETECT_PARTIAL_INTERVAL_S
            ):
                return None
        state.last_live_section_emit_at = now

        manual_locked = (
            state.manual_section_until is not None and now < state.manual_section_until
        )
        if not manual_locked:
            state.active_subtopic_id = str(subtopic_id)
            state.active_topic_id = str(topic_id) if topic_id else None
            try:
                set_active_capture_section(
                    db,
                    workspace_id=workspace.id,
                    session_id=state.session_id,
                    topic_id=state.active_topic_id,
                    subtopic_id=state.active_subtopic_id,
                )
            except Exception:
                db.rollback()

        payload = {
            "status": "suggested",
            "topic_id": topic_id,
            "subtopic_id": subtopic_id,
            "confidence": confidence,
            "source": source,
            "manual_locked": manual_locked,
        }
        await self._send(websocket, state, "section.active", payload)
        return payload

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
        text = str(payload.get("text") or "").strip()
        ignored_reason = "stt_noise" if text and is_capture_text_noise(text) else None
        if ignored_reason:
            text = ""
        duration_ms = int(payload.get("duration_ms") or payload.get("latency_ms") or 0)
        # Realtime lane: the LiveKit sidecar already streamed the live partials
        # (text.partial -> retrieval hints + section detection) and now commits
        # the turn's final text. Echo it to the UI, then run the SAME persistence
        # seam as the batch endpoint STT (append_turn + section tagging + live
        # questions + silent oracle). No relance / conversation.step / TTS here:
        # heavy work stays deferred to section.finish / capture.finish.
        await self._send(
            websocket,
            state,
            "text.final",
            {
                **payload,
                "turn_id": turn_id,
                "speaker": payload.get("speaker") or "expert",
                "text": text,
                "empty": not bool(text),
                "reason": payload.get("reason") if text else (ignored_reason or payload.get("reason") or "empty_transcript"),
            },
        )
        if text:
            state.text_partials.append(text)
        self._ensure_capture_plan(db, workspace.id, state)
        latency = {
            "first_text": duration_ms,
            "final_text": duration_ms,
            "text_final_total_ms": duration_ms,
            "endpoint_stt_ms": duration_ms,
            "endpoint_stt_source": "realtime_stream",
            "endpoint_reason": str(payload.get("reason") or "realtime"),
            "runtime_provider": payload.get("provider") or state.runtime,
            "runtime_model": payload.get("model") or state.model,
            "transport": state.transport,
        }
        await self._persist_capture_turn(
            websocket,
            db,
            user=user,
            workspace=workspace,
            state=state,
            capture_session_id=state.session_id if state.capture_plan is not None else None,
            text=text,
            latency=latency,
            oracle_final_duration_ms=duration_ms,
            document_refs=payload.get("document_refs") if isinstance(payload.get("document_refs"), list) else [],
            visual_context=payload.get("visual_context") if isinstance(payload.get("visual_context"), dict) else None,
        )

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
        # Any in-flight incremental STT is superseded by this endpoint's
        # authoritative full-buffer transcription: cancel it so the endpoint
        # never queues behind a slow partial round-trip or behind db_lock held
        # by its post-STT hint pass. Committed partial text/chunk bookkeeping is
        # left intact so the reuse-partial fast path below still works.
        for task in list(state.partial_stt_tasks):
            if not task.done():
                task.cancel()
        if payload.get("question_id"):
            state.question_id = str(payload.get("question_id"))
        if not state.audio_chunks:
            await self._send_error(websocket, "empty_audio", "audio.endpoint received without audio frames", state=state)
            return
        endpoint_reason_raw = payload.get("reason")
        if not endpoint_reason_raw and payload.get("auto") is True:
            endpoint_reason_raw = "auto"
        endpoint_reason = str(endpoint_reason_raw or "manual").strip().lower()[:40] or "manual"
        endpoint_capture_mode = str(payload.get("capture_mode") or "").strip().lower()[:40] or None
        endpoint_document_refs = payload.get("document_refs") if isinstance(payload.get("document_refs"), list) else []
        endpoint_visual_context = payload.get("visual_context") if isinstance(payload.get("visual_context"), dict) else None
        endpoint_vad_settings: Dict[str, Any] = {}
        for key in (
            "silence_ms",
            "min_speech_ms",
            "endpoint_grace_ms",
            "vad_hangover_ms",
            "vad_min_silence_frames_ms",
            "since_voice_ms",
        ):
            value = payload.get(key)
            if isinstance(value, (int, float)) and math.isfinite(float(value)):
                endpoint_vad_settings[key] = int(round(float(value)))
        rms_threshold = payload.get("rms_threshold")
        if isinstance(rms_threshold, (int, float)) and math.isfinite(float(rms_threshold)):
            endpoint_vad_settings["rms_threshold"] = float(rms_threshold)

        state.endpoint_at = time.perf_counter()
        chunk_count = len(state.audio_chunks)
        audio_bytes = b"".join(state.audio_chunks)
        state.audio_chunks = []
        started = state.turn_started_at or state.endpoint_at
        turn_audio_capture_ms = max(0, int((state.endpoint_at - started) * 1000))
        # TASK 1 (reuse): if the last incremental partial transcribed the EXACT same
        # buffer (same chunk count == same bytes, since both join from chunk 0), its
        # text is already the complete utterance. Reuse it as the basis for text.final
        # and skip the redundant full-buffer STT round-trip. Correctness holds because
        # no new audio arrived after that partial; if any chunk arrived since, we fall
        # back to a fresh full transcription so text.final stays complete.
        reuse_partial = bool(
            state.last_partial_text
            and chunk_count > 0
            and state.last_partial_text_chunk_count == chunk_count
        )
        endpoint_stt_started_at = time.perf_counter()
        endpoint_stt_source = "reused_partial" if reuse_partial else "provider"
        if reuse_partial:
            transcript: Dict[str, Any] = {
                "text": state.last_partial_text,
                "transcript": state.last_partial_text,
                "provider": state.runtime,
                "model": state.model,
                "reused_partial": True,
            }
        else:
            try:
                provider = get_voice_runtime_provider(state.runtime, workspace_settings=workspace.settings)
            except VoiceProviderError as exc:
                await self._send_error(websocket, exc.code, str(exc), state=state)
                self._reset_turn_after_stt_failure(state)
                return
            try:
                transcript = await _transcribe_audio(
                    provider,
                    audio_bytes,
                    filename=f"{state.client_turn_id or 'voice-session'}.webm",
                    content_type=state.content_type,
                    language=state.language or "fr",
                )
            except VoiceProviderError as exc:
                # Full provider error stays server-side; the UI gets a clean,
                # actionable French message (raw OpenAI/fallback strings used to
                # be forwarded verbatim via session.error — trace 24a345).
                logger.warning(
                    "voice_endpoint_stt_failed",
                    error=str(exc),
                    code=exc.code,
                    session_id=state.session_id,
                    turn_id=state.client_turn_id,
                )
                await self._send_error(websocket, exc.code, _STT_SEGMENT_FAILED_MESSAGE, state=state)
                self._reset_turn_after_stt_failure(state)
                return
            except Exception as exc:
                logger.warning(
                    "voice_endpoint_stt_failed",
                    error=str(exc),
                    session_id=state.session_id,
                    turn_id=state.client_turn_id,
                )
                await self._send_error(websocket, "transcribe_failed", _STT_SEGMENT_FAILED_MESSAGE, state=state)
                self._reset_turn_after_stt_failure(state)
                return

        endpoint_stt_ms = max(0, int((time.perf_counter() - endpoint_stt_started_at) * 1000))
        text = str(transcript.get("text") or transcript.get("transcript") or "").strip()
        ignored_reason = "stt_noise" if text and is_capture_text_noise(text) else None
        if ignored_reason:
            text = ""
        first_text_ms = int((time.perf_counter() - started) * 1000)
        latency = {
            "first_text": first_text_ms,
            "final_text": first_text_ms,
            "text_final_total_ms": first_text_ms,
            "turn_audio_capture_ms": turn_audio_capture_ms,
            "endpoint_stt_ms": endpoint_stt_ms,
            "endpoint_stt_source": endpoint_stt_source,
            "endpoint_reason": endpoint_reason,
            "capture_mode": endpoint_capture_mode,
            **endpoint_vad_settings,
            "audio_bytes": len(audio_bytes),
            "runtime_provider": transcript.get("provider") or state.runtime,
            "runtime_requested_provider": transcript.get("requested_provider") or state.runtime,
            "runtime_model": transcript.get("model") or state.model,
            "fallback_used": bool(transcript.get("fallback")),
        }
        endpoint_oracle_events: list[Dict[str, Any]] = []
        if text:
            state.text_partials.append(text)
            partial_seq = None
            if state.tandem_oracle_enabled:
                endpoint_oracle_events = state.oracle.observe_partial(
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
                partial_seq = self._oracle_partial_seq(endpoint_oracle_events)
            await self._send(
                websocket,
                state,
                "text.partial",
                {
                    "turn_id": state.client_turn_id,
                    "partial_seq": partial_seq,
                    "text": text,
                    "latency_ms": first_text_ms,
                    "text_final_total_ms": first_text_ms,
                    "endpoint_stt_ms": endpoint_stt_ms,
                    "endpoint_stt_source": endpoint_stt_source,
                    "endpoint_reason": endpoint_reason,
                    "capture_mode": endpoint_capture_mode,
                },
            )
        # Raw-live contract (TASK 2 — "carde = final only"): the committed live
        # text.final stays as close to raw STT as possible. NO domain-term glossary
        # substitution happens here (no live carte->carde). All correction and
        # reformulation — glossary terms, linking words, BOM/acronym casing, oral
        # artifacts — is deferred to the FINAL phase (finalize_capture_section /
        # finalize_capture), so the live transcript is direct and never rewritten by
        # a correction pass mid-capture.
        segment_id = state.client_turn_id or str(uuid.uuid4())
        # Shared DB session: wait for any offloaded incremental-STT hint pass
        # still holding the lock before touching the session here.
        async with state.db_lock:
            capture_session = self._capture_session(db, workspace.id, state.session_id)
        if capture_session is not None and not state.capture_session_resolved:
            state.capture_plan = dict(capture_session.plan or {})
            state.capture_session_resolved = True
        corrected_text = text
        if text:
            # The raw STT text is both the live partial and the committed final. No
            # transcript.improved / reframed / glossary stage — the frontend renders the
            # flowing transcript directly from text.final.
            await self._send(
                websocket,
                state,
                "transcript.partial",
                {"segment_id": segment_id, "turn_id": state.client_turn_id, "text": text},
            )
        await self._send(
            websocket,
            state,
            "text.final",
            {
                "turn_id": state.client_turn_id,
                "speaker": "expert",
                "text": corrected_text,
                "reframed": False,
                "empty": not bool(text),
                "reason": None if text else (ignored_reason or "empty_transcript"),
                "confidence": transcript.get("confidence"),
                "latency_ms": first_text_ms,
                "text_final_total_ms": first_text_ms,
                "turn_audio_capture_ms": turn_audio_capture_ms,
                "endpoint_stt_ms": endpoint_stt_ms,
                "endpoint_stt_source": endpoint_stt_source,
                "endpoint_reason": endpoint_reason,
                "capture_mode": endpoint_capture_mode,
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
                "text_final_total_ms": first_text_ms,
                "turn_audio_capture_ms": turn_audio_capture_ms,
                "endpoint_stt_ms": endpoint_stt_ms,
                "endpoint_stt_source": endpoint_stt_source,
                "endpoint_reason": endpoint_reason,
                "capture_mode": endpoint_capture_mode,
            },
        )
        await self._send(
            websocket,
            state,
            "runtime.metric",
            {
                "metric": "endpoint_stt",
                "value_ms": endpoint_stt_ms,
                "turn_id": state.client_turn_id,
                "source": endpoint_stt_source,
                "audio_bytes": len(audio_bytes),
                "chunk_count": chunk_count,
                "turn_audio_capture_ms": turn_audio_capture_ms,
                "text_final_total_ms": first_text_ms,
                "endpoint_reason": endpoint_reason,
                "capture_mode": endpoint_capture_mode,
                "provider": transcript.get("provider") or state.runtime,
                "model": transcript.get("model") or state.model,
                "transport": state.transport,
                "fallback_used": bool(transcript.get("fallback")),
            },
        )
        if endpoint_oracle_events:
            await self._emit_oracle_events(
                websocket,
                db,
                user=user,
                workspace=workspace,
                state=state,
                events=endpoint_oracle_events,
            )

        await self._persist_capture_turn(
            websocket,
            db,
            user=user,
            workspace=workspace,
            state=state,
            capture_session_id=capture_session.id if capture_session else None,
            text=text,
            latency=latency,
            oracle_final_duration_ms=first_text_ms,
            document_refs=endpoint_document_refs,
            visual_context=endpoint_visual_context,
        )

    async def _persist_capture_turn(
        self,
        websocket: WebSocket,
        db: DBSession,
        *,
        user: User,
        workspace: Workspace,
        state: VoiceSessionState,
        capture_session_id: Optional[str],
        text: str,
        latency: Dict[str, Any],
        oracle_final_duration_ms: int,
        document_refs: Optional[List[Dict[str, Any]]] = None,
        visual_context: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Persist one committed expert turn and run the silent live oracle.

        Shared seam between the two STT lanes that both arrive with an already
        committed final ``text``:

        - the batch endpoint lane (``_handle_audio_endpoint``) after full-buffer
          STT, and
        - the realtime lane (``_handle_text_final``) where the LiveKit sidecar
          streamed ``gpt-realtime-whisper`` deltas and committed the turn.

        PENDANT la capture = fast capture + timeline only: the turn is persisted
        SILENTLY (no process_conversation_step, no relance, no next_prompt, no
        TTS, no proposal). All heavy work (reformulation, grounded questions,
        proposal synthesis) is deferred to section.finish / capture.finish. The
        turn is tagged with the active plan section so the FINAL per-section
        reformulation can map it to the plan hierarchy. Turn state is reset on
        exit so the next utterance starts clean.
        """
        if capture_session_id and text:
            turn_started = time.perf_counter()
            async with state.db_lock:
                # Silent capture path: skip the evaluate/relance work (computed
                # then thrown away here) and fold the per-turn voice_stream metrics
                # into append_turn's single commit (no second get_session+commit).
                turn_result = append_turn(
                    db,
                    workspace_id=workspace.id,
                    session_id=capture_session_id,
                    speaker="expert",
                    text=text,
                    question_id=state.question_id,
                    client_turn_id=state.client_turn_id,
                    retrieval_event_id=state.retrieval_event_id,
                    interruption_of_event_id=state.interruption_of_event_id,
                    turn_kind="correction" if state.interruption_of_event_id else "answer",
                    actor_user_id=user.id,
                    text_partials=state.text_partials[-5:],
                    latency_ms=latency,
                    contradiction_candidates=state.last_contradiction_candidates,
                    topic_id=state.active_topic_id,
                    subtopic_id=state.active_subtopic_id,
                    input_modality="voice",
                    document_refs=document_refs or [],
                    visual_context=visual_context,
                    compute_evaluation=False,
                    # Defer the growing transcript-column rewrite: the turn is on the
                    # append-only ledger; the column is rematerialized lazily on read
                    # and persisted at section.finish / capture.finish (no O(N^2)).
                    persist_transcript=False,
                    voice_stream_metrics={**latency},
                )
                turn_to_prompt_ms = int((time.perf_counter() - turn_started) * 1000)
            # Realtime feedback for journaled deictic view references ("comme on le
            # voit sur cette page"...). One lightweight push per referenced view on
            # the same stream that carries turns/questions, so the chips can flash
            # "référence journalisée" without polling.
            for ref in (turn_result or {}).get("view_references") or []:
                await self._send(
                    websocket,
                    state,
                    "capture.view.referenced",
                    {
                        "session_id": capture_session_id,
                        "document_id": ref.get("document_id"),
                        "filename": ref.get("filename"),
                        "title": ref.get("title"),
                        "page": ref.get("page"),
                        "slide": ref.get("slide"),
                        "image_index": ref.get("image_index"),
                        "turn_id": ref.get("turn_id"),
                        "timecode_ms": ref.get("timecode_ms"),
                        "statement": ref.get("statement"),
                        "trigger_phrase": ref.get("trigger_phrase"),
                    },
                )
            # Accumulate the committed expert text for the live grounded-question
            # context, scoped to the active plan section: switching sections
            # resets the buffer (and the questions, which belong to the old one).
            section_key = f"{state.active_topic_id or ''}:{state.active_subtopic_id or ''}"
            if state.committed_turns_section != section_key:
                state.committed_turns_section = section_key
                state.committed_turn_texts = []
                state.live_open_questions = []
                state.live_questions_generation += 1
                state.last_questions_word_count = 0
            state.committed_turn_texts.append(text)
            # Passive "contexte retrouvé" panel only — no content questions/relances.
            oracle_retrieval = {
                "chunks": format_retrieval_chunks(
                    state.last_retrieval_chunks,
                    state.last_retrieval_metadatas,
                    state.last_retrieval_scores,
                )
            }
            section_suggestion: Optional[Dict[str, Any]] = None
            try:
                section_suggestion = await self._maybe_detect_and_emit_active_section(
                    websocket,
                    db,
                    workspace=workspace,
                    state=state,
                    plan=state.capture_plan,
                    partial_text=text,
                    source="turn_commit",
                )
            except Exception:
                logger.debug("live_section_detect_on_turn_commit_failed", exc_info=True)

            await self._send(
                websocket,
                state,
                "evaluation.delta",
                {
                    "turn_id": state.client_turn_id,
                    "relance": {"kind": None, "text": None},
                    "suggestions": [],
                    # Re-send the latest LIVE questions: the frontend ingests any
                    # top-level open_questions array, so an empty list here would
                    # wipe the QUESTIONS IA panel on every committed turn.
                    "open_questions": list(state.live_open_questions),
                    "retrieval": oracle_retrieval,
                    "section_suggestion": section_suggestion or None,
                },
            )
            # Fire-and-forget: live grounded open questions for the QUESTIONS IA
            # panel. Never awaited on this path — adds zero latency to text.final.
            self._schedule_live_open_questions(
                websocket,
                state,
                workspace_id=str(workspace.id),
                workspace_slug=workspace.slug,
                capture_session_id=capture_session_id,
            )
            if state.tandem_oracle_enabled:
                # Inner-monologue track only (oracle "thinking"); no pushed prompt.
                oracle_events = state.oracle.commit_final(
                    text,
                    turn_id=state.client_turn_id or str(uuid.uuid4()),
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
        elif state.tandem_oracle_enabled and text:
            oracle_events = state.oracle.commit_final(
                text,
                turn_id=state.client_turn_id or str(uuid.uuid4()),
                duration_ms=oracle_final_duration_ms,
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

    def _schedule_live_open_questions(
        self,
        websocket: WebSocket,
        state: VoiceSessionState,
        *,
        workspace_id: str,
        workspace_slug: Optional[str] = None,
        capture_session_id: Optional[str] = None,
    ) -> None:
        """Fire-and-forget generation of LIVE grounded open questions.

        Called right after a capture turn is committed. Guards: live questions
        enabled, some accumulated expert text, at most ONE generation in flight
        per session, and generated either once enough NEW words accumulated since
        the last generation (``_LIVE_QUESTIONS_MIN_NEW_WORDS``) or after the time
        throttle (``_LIVE_QUESTIONS_MIN_INTERVAL_S``) elapsed. The context is the
        last ``_LIVE_QUESTIONS_CONTEXT_WORDS`` committed words rather than a fixed
        number of (short, VAD-sized) realtime turns. All inputs are snapshotted
        here because ``_handle_audio_endpoint`` clears ``last_retrieval_*`` and
        ``client_turn_id`` right after scheduling.
        """
        if not state.tandem_oracle_enabled or not state.live_questions_enabled:
            return
        if not capture_session_id or not state.committed_turn_texts:
            return
        if state.live_questions_in_flight:
            return
        now = time.monotonic()
        context_words = " ".join(state.committed_turn_texts).split()
        total_words = len(context_words)
        new_words = total_words - state.last_questions_word_count
        time_ready = (
            state.last_live_questions_at is None
            or (now - state.last_live_questions_at) >= _LIVE_QUESTIONS_MIN_INTERVAL_S
        )
        if new_words < _LIVE_QUESTIONS_MIN_NEW_WORDS and not time_ready:
            return
        state.live_questions_in_flight = True
        state.last_live_questions_at = now
        state.last_questions_word_count = total_words
        context = " ".join(context_words[-_LIVE_QUESTIONS_CONTEXT_WORDS:])
        plan_section = {
            "topic_id": state.active_topic_id,
            "subtopic_id": state.active_subtopic_id,
        }
        section_key = state.committed_turns_section
        turn_id = state.client_turn_id
        generation = state.live_questions_generation

        async def _run() -> None:
            try:
                from app.services.capture_knowledge_oracle import (
                    generate_grounded_open_questions_async,
                )
                from app.db.base import SessionLocal

                chunks: list = []
                metadatas: list = []
                if settings.voice_oracle_live_questions_retrieval_enabled:
                    with SessionLocal() as question_db:
                        # Synchronous DB read -> offload so the question pipeline never
                        # blocks the transcript relay (the symptom: a big chunk of
                        # transcript landing only AFTER the questions appear).
                        capture_snapshot = await asyncio.to_thread(
                            get_session,
                            question_db,
                            workspace_id=workspace_id,
                            session_id=capture_session_id,
                            materialize=False,
                        )
                        # Resolve the RAG collection once per session (off-loop) so
                        # the worker retrieval gets a pre-resolved collection and
                        # never re-hits the DB on the realtime loop.
                        if state.retrieval_collection_name is None:
                            state.retrieval_collection_name = await asyncio.to_thread(
                                lambda: _resolve_collection_name(
                                    _load_context(
                                        question_db,
                                        workspace_id,
                                        getattr(capture_snapshot, "context_id", None),
                                    )
                                )
                            )
                        query_context = self._retrieval_query_context(capture_snapshot)
                        retrieval_query = f"{context} {query_context}".strip()
                        # Worker-backed retrieval (separate GIL): fully fire-and-forget
                        # (already inside create_task). On timeout/empty it returns
                        # ([], [], []) and we fall back to statement-grounded questions
                        # below, so questions always appear.
                        chunks, metadatas, _scores = await _retrieve_context_chunks_async(
                            question_db,
                            workspace_id=workspace_id,
                            workspace_slug=workspace_slug,
                            session=capture_snapshot,
                            query=retrieval_query,
                            top_k=6,
                            retrieval_profile="oracle_grounded_async",
                            collection_name=state.retrieval_collection_name,
                        )
                    if chunks:
                        # Feed the passive "contexte retrouvé" panel from this turn-commit
                        # retrieval (runs at silence) so the panel survives even with the
                        # during-speech live hints disabled.
                        state.last_retrieval_chunks = list(chunks)
                        state.last_retrieval_metadatas = list(metadatas or [])
                        state.last_retrieval_scores = list(_scores or [])
                if state.live_questions_generation != generation or state.committed_turns_section != section_key:
                    return
                # chunks=None -> grounded on the expert's own statements only
                # (expert_statement_grounded). Pure async LLM call, no local
                # retrieval, so it never holds the GIL / freezes the next turn.
                raw_questions = await generate_grounded_open_questions_async(
                    context,
                    chunks or None,
                    metadatas or None,
                    plan_section,
                    workspace_id=workspace_id,
                    max_questions=4,
                )
                questions: list[Dict[str, Any]] = []
                for index, raw in enumerate(raw_questions or [], start=1):
                    if not isinstance(raw, dict):
                        continue
                    text_value = str(raw.get("text") or "").strip()
                    if not text_value:
                        continue
                    grounding_status = str(raw.get("grounding_status") or "kb_grounded").strip()
                    if grounding_status not in {"kb_grounded", "expert_statement_grounded"}:
                        continue
                    questions.append(
                        {
                            "id": raw.get("id") or f"live-{turn_id or 'turn'}-{index:02d}",
                            "text": text_value,
                            "topic_id": raw.get("topic_id") or plan_section["topic_id"],
                            "subtopic_id": raw.get("subtopic_id") or plan_section["subtopic_id"],
                            "priority": raw.get("priority", 0.7),
                            "status": raw.get("status") or "open",
                            "source": "oracle_live",
                            "grounding_status": grounding_status,
                        }
                    )
                if not questions:
                    return
                # Drop stale results if the expert moved to another section while
                # the generation was running.
                if state.live_questions_generation != generation or state.committed_turns_section != section_key:
                    return
                state.live_open_questions = questions
                if capture_session_id:
                    try:
                        from app.db.base import SessionLocal
                        from app.services.knowledge_capture import merge_live_open_questions_into_plan

                        with SessionLocal() as persist_db:
                            await asyncio.to_thread(
                                merge_live_open_questions_into_plan,
                                persist_db,
                                workspace_id=workspace_id,
                                session_id=capture_session_id,
                                questions=questions,
                            )
                    except Exception:
                        logger.warning("live open questions persist failed", exc_info=True)
                try:
                    await self._send(
                        websocket,
                        state,
                        "oracle.questions",
                        {"turn_id": turn_id, "open_questions": questions},
                    )
                except Exception:
                    # The websocket may have closed while the LLM call ran.
                    logger.debug("live open questions: websocket send failed", exc_info=True)
            except Exception:
                logger.warning("live open questions generation failed", exc_info=True)
            finally:
                state.live_questions_in_flight = False

        task = asyncio.create_task(_run())
        state.live_questions_tasks.add(task)
        task.add_done_callback(state.live_questions_tasks.discard)

    async def _handle_audio_pause(
        self,
        websocket: WebSocket,
        db: DBSession,
        *,
        user: User,
        workspace: Workspace,
        state: VoiceSessionState,
        payload: Dict[str, Any],
    ) -> None:
        """Pause mic = segment flush (B1): finalize the in-flight segment exactly
        like an endpoint — transcribe the buffered audio (reusing the latest
        full-buffer partial when valid), persist the turn via the same
        append_turn path and emit text.final — but with NO relance /
        conversation step / TTS (the continuous-capture endpoint path already
        does none of that, so we delegate to it with reason="pause"). After the
        flush the buffer is empty and partial state reset, so a resume genuinely
        starts a fresh turn under the frontend's new turn id (trace 24a345:
        keeping the buffer open across pauses emitted text.final under the
        stale turn id 524e65aa). A pause with an empty/silent buffer is normal:
        reset silently, never emit an ``empty_audio`` error."""
        await self._send(websocket, state, "audio.pause", {"status": "ok", **payload})
        if not state.audio_chunks:
            # No buffered speech: nothing to flush, just clear partial bookkeeping.
            self._reset_partial_stt_state(state)
            return
        await self._handle_audio_endpoint(
            websocket,
            db,
            user=user,
            workspace=workspace,
            state=state,
            payload={**payload, "reason": "pause"},
        )

    async def _handle_section_select(
        self,
        websocket: WebSocket,
        db: DBSession,
        *,
        workspace: Workspace,
        state: VoiceSessionState,
        payload: Dict[str, Any],
    ) -> None:
        """Jump directly to a plan section (B1). Sets the active topic/subtopic in
        session metrics so subsequent capture turns are tagged. NO relance."""
        topic_id = payload.get("topic_id") if payload.get("topic_id") else None
        subtopic_id = payload.get("subtopic_id") if payload.get("subtopic_id") else None
        state.active_topic_id = str(topic_id) if topic_id else None
        state.active_subtopic_id = str(subtopic_id) if subtopic_id else None
        if payload.get("manual"):
            state.manual_section_until = time.monotonic() + _MANUAL_SECTION_OVERRIDE_COOLDOWN_S
        capture_session = self._capture_session(db, workspace.id, state.session_id)
        if capture_session:
            try:
                set_active_capture_section(
                    db,
                    workspace_id=workspace.id,
                    session_id=capture_session.id,
                    topic_id=state.active_topic_id,
                    subtopic_id=state.active_subtopic_id,
                )
            except Exception:
                db.rollback()
        await self._send(
            websocket,
            state,
            "section.select",
            {
                "status": "ok",
                "topic_id": state.active_topic_id,
                "subtopic_id": state.active_subtopic_id,
            },
        )

    async def _handle_section_finish(
        self,
        websocket: WebSocket,
        db: DBSession,
        *,
        user: User,
        workspace: Workspace,
        state: VoiceSessionState,
        payload: Dict[str, Any],
    ) -> None:
        """Finish the current section (B1/C1/C2): trigger the FINAL per-section
        reformulation + grounded questions, then emit exactly ONE timeline relance
        via conversation.step. No content questions."""
        topic_id = payload.get("topic_id") or state.active_topic_id
        subtopic_id = payload.get("subtopic_id") or state.active_subtopic_id
        capture_session = self._capture_session(db, workspace.id, state.session_id)
        section_summary: Dict[str, Any] = {}
        if capture_session:
            try:
                section_summary = await finalize_capture_section(
                    db,
                    workspace_id=workspace.id,
                    session_id=capture_session.id,
                    topic_id=str(topic_id) if topic_id else None,
                    subtopic_id=str(subtopic_id) if subtopic_id else None,
                    workspace_slug=workspace.slug,
                    static_context=_resolve_rewrite_context(workspace),
                )
            except Exception as exc:
                logger.warning("voice_section_finish_failed", error=str(exc), session_id=state.session_id)
                db.rollback()
        await self._send(
            websocket,
            state,
            "conversation.step",
            {
                "turn_id": state.client_turn_id,
                "section": {"topic_id": topic_id, "subtopic_id": subtopic_id},
                "section_synthesis": section_summary,
                "next_prompt": SECTION_FINISH_RELANCE,
                "relance": {"kind": "timeline", "text": SECTION_FINISH_RELANCE},
                "suggestions": [],
                "open_questions": [],
            },
        )

    async def _handle_capture_finish(
        self,
        websocket: WebSocket,
        db: DBSession,
        *,
        user: User,
        workspace: Workspace,
        state: VoiceSessionState,
        payload: Dict[str, Any],
    ) -> None:
        """Finish the whole capture (B1/C*): close all remaining sections and
        build/refresh the proposal, then emit proposal-ready via conversation.step.

        While the heavy FINAL pass runs, honest stage events are streamed as
        ``capture.finalize.progress`` so the frontend loader can show the real
        work (plan restructuring / thematic blocks, dedupe, Andritz vocabulary
        alignment, per-section synthesis, report assembly)."""
        capture_session = self._capture_session(db, workspace.id, state.session_id)
        proposal_payload: Optional[Dict[str, Any]] = None
        session_payload: Optional[Dict[str, Any]] = None

        async def _emit_finalize_progress(progress_payload: Dict[str, Any]) -> None:
            try:
                await self._send(
                    websocket,
                    state,
                    "capture.finalize.progress",
                    {"turn_id": state.client_turn_id, **progress_payload},
                )
            except Exception:  # noqa: BLE001 - progress must never break finalization.
                pass

        await _emit_finalize_progress(
            {"stage": "start", "label": "Préparation de la synthèse finale…"}
        )
        if capture_session:
            try:
                proposal = await finalize_capture(
                    db,
                    workspace_id=workspace.id,
                    session_id=capture_session.id,
                    workspace_slug=workspace.slug,
                    static_context=_resolve_rewrite_context(workspace),
                    created_by_user_id=user.id,
                    progress=_emit_finalize_progress,
                )
                proposal_payload = serialize_proposal(proposal)
                if proposal_payload and proposal_payload.get("id"):
                    state.last_proposal_id = str(proposal_payload["id"])
                refreshed = self._capture_session(db, workspace.id, state.session_id)
                if refreshed:
                    session_payload = serialize_session(refreshed)
                # Background indexing batch (referenced views + full-share docs),
                # decoupled from the report return: the report is sent below from
                # the journaled refs while indexing runs off-loop in a worker
                # thread. Idempotent + guarded against concurrent runs.
                from app.db.base import SessionLocal

                index_task = asyncio.create_task(
                    asyncio.to_thread(
                        run_capture_finalize_index,
                        SessionLocal,
                        workspace_id=workspace.id,
                        session_id=capture_session.id,
                    )
                )
                state.finalize_tasks.add(index_task)
                index_task.add_done_callback(state.finalize_tasks.discard)
            except Exception as exc:
                logger.warning("voice_capture_finish_failed", error=str(exc), session_id=state.session_id)
                db.rollback()
                await _emit_finalize_progress(
                    {"stage": "error", "label": "La synthèse finale a rencontré une erreur."}
                )
        await self._send(
            websocket,
            state,
            "conversation.step",
            {
                "turn_id": state.client_turn_id,
                "capture_finished": True,
                "proposal": proposal_payload,
                "session": session_payload,
                "relance": {"kind": None, "text": None},
                "suggestions": [],
                "open_questions": [],
            },
        )

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
    def _sync_voice_state_from_capture_session(
        state: VoiceSessionState,
        capture_session: ExpertCaptureSession,
    ) -> None:
        """Align WS state with persisted capture session (active section, live Q)."""
        from app.services.knowledge_capture import _resolve_session_active_section

        metrics = capture_session.metrics or {}
        topic_id, subtopic_id = _resolve_session_active_section(capture_session)
        state.active_topic_id = str(topic_id) if topic_id else metrics.get("active_topic_id")
        state.active_subtopic_id = str(subtopic_id) if subtopic_id else metrics.get("active_subtopic_id")
        plan = capture_session.plan or {}
        state.capture_plan = dict(plan)
        state.capture_session_resolved = True
        live_questions = plan.get("live_open_questions") if isinstance(plan.get("live_open_questions"), list) else []
        if live_questions:
            state.live_open_questions = [dict(item) for item in live_questions if isinstance(item, dict)]

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
        for item in [
            q
            for q in open_questions
            if q.get("status") not in {"addressed", "answered", "dismissed", "deferred"}
        ][:3]:
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

    def _ensure_capture_plan(
        self,
        db: DBSession,
        workspace_id: str,
        state: VoiceSessionState,
    ) -> None:
        """Resolve the capture session plan ONCE per connection and cache it.

        The capture session id is ``state.session_id``; ``session.start`` already
        caches the plan when a capture session exists, so this only does a DB hit
        in the rare case the row is created after the WS handshake. After
        resolution ``state.capture_plan is not None`` means a capture session
        exists for this connection.
        """
        if state.capture_session_resolved:
            return
        state.capture_session_resolved = True
        capture_session = self._capture_session(db, workspace_id, state.session_id)
        if capture_session is not None:
            state.capture_plan = dict(capture_session.plan or {})

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
