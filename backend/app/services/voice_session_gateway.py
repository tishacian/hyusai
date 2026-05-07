"""WebSocket gateway for streaming-compatible voice sessions.

J1 keeps the cascade provider as the concrete runtime while introducing the
protocol shape needed for lower-latency voice loops: typed events, inner
monologue text track, minimal latency metrics and HTTP fallback compatibility.
"""
from __future__ import annotations

import base64
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from fastapi import HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session as DBSession

from app.core.auth import decode_token
from app.core.iam.dependencies import enforce_permission
from app.models.expert_capture import ExpertCaptureSession
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services.knowledge_capture import append_turn, get_session
from app.services.voice_runtime import get_voice_runtime_provider


@dataclass
class VoiceSessionState:
    session_id: str
    runtime: str = "cascade"
    capability: str = "expert_knowledge_capture"
    mode: str = "conversation_only"
    codec: Dict[str, Any] = field(default_factory=dict)
    sequence: int = 0
    audio_chunks: list[bytes] = field(default_factory=list)
    text_partials: list[str] = field(default_factory=list)
    client_turn_id: Optional[str] = None
    question_id: Optional[str] = None
    retrieval_event_id: Optional[str] = None
    interruption_of_event_id: Optional[str] = None
    content_type: str = "audio/webm"
    turn_started_at: Optional[float] = None
    endpoint_at: Optional[float] = None


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
        auth = self._authenticate(db, token=token, workspace_slug=workspace_slug)
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
                resource_attrs={"capability": "expert_knowledge_capture"},
                audit_prefix="kc",
            )
        except HTTPException as exc:
            await self._send_error(websocket, "forbidden", str(exc.detail))
            await websocket.close(code=4403)
            return

        state = VoiceSessionState(session_id=session_id)
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

        await self._send(websocket, state, "session.ready", {"runtime": state.runtime, "provider": "cascade"})
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
            state.runtime = str(payload.get("runtime") or "cascade")
            state.capability = str(payload.get("capability") or state.capability)
            state.mode = str(payload.get("mode") or state.mode)
            state.codec = payload.get("codec") if isinstance(payload.get("codec"), dict) else {}
            await self._send(websocket, state, "runtime.metric", {"metric": "session_started", "value_ms": 0})
            return
        if event_type == "audio.frame":
            await self._handle_audio_frame(websocket, state, payload)
            return
        if event_type == "audio.endpoint":
            await self._handle_audio_endpoint(websocket, db, user=user, workspace=workspace, state=state, payload=payload)
            return
        if event_type == "barge_in":
            await self._send(websocket, state, "barge_in", {"status": "accepted", **payload})
            return
        if event_type == "session.close":
            await self._send(websocket, state, "session.close", {"status": "ok"})
            await websocket.close(code=1000)
            return
        await self._send_error(websocket, "unknown_event", f"Unknown voice event: {event_type}", state=state)

    async def _handle_audio_frame(
        self,
        websocket: WebSocket,
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
            await self._send(websocket, state, "runtime.metric", {"metric": "audio_started", "value_ms": 0})
        state.audio_chunks.append(chunk)

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
        provider = get_voice_runtime_provider(state.runtime)
        audio_bytes = b"".join(state.audio_chunks)
        state.audio_chunks = []
        started = state.turn_started_at or state.endpoint_at
        try:
            transcript = await provider.transcribe(
                audio_bytes,
                filename=f"{state.client_turn_id or 'voice-session'}.webm",
                content_type=state.content_type,
            )
        except Exception as exc:
            await self._send_error(websocket, "transcribe_failed", str(exc), state=state)
            state.turn_started_at = None
            return

        text = str(transcript.get("text") or transcript.get("transcript") or "").strip()
        first_text_ms = int((time.perf_counter() - started) * 1000)
        latency = {
            "first_text": first_text_ms,
            "final_text": first_text_ms,
            "audio_bytes": len(audio_bytes),
            "runtime_provider": state.runtime,
        }
        if text:
            state.text_partials.append(text)
            await self._send(
                websocket,
                state,
                "text.partial",
                {"turn_id": state.client_turn_id, "text": text, "latency_ms": first_text_ms},
            )
            await self._send(
                websocket,
                state,
                "text.final",
                {
                    "turn_id": state.client_turn_id,
                    "speaker": "expert",
                    "text": text,
                    "confidence": transcript.get("confidence"),
                    "latency_ms": first_text_ms,
                    "source": f"{state.runtime}_stt",
                },
            )
        await self._send(
            websocket,
            state,
            "runtime.metric",
            {"metric": "time_to_first_text", "value_ms": first_text_ms, "turn_id": state.client_turn_id},
        )

        capture_session = self._capture_session(db, workspace.id, state.session_id)
        if capture_session and text:
            turn_started = time.perf_counter()
            result = append_turn(
                db,
                workspace_id=workspace.id,
                session_id=capture_session.id,
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
            )
            turn_to_prompt_ms = int((time.perf_counter() - turn_started) * 1000)
            self._merge_capture_metrics(db, workspace.id, capture_session.id, {**latency, "turn_end_to_prompt": turn_to_prompt_ms})
            await self._send(
                websocket,
                state,
                "evaluation.delta",
                {
                    "turn_id": state.client_turn_id,
                    "evaluation": result.get("evaluation"),
                    "next_question_id": result.get("next_question_id"),
                    "session": result.get("session"),
                },
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

        state.turn_started_at = None
        state.endpoint_at = None
        state.text_partials = []
        state.client_turn_id = None
        state.retrieval_event_id = None
        state.interruption_of_event_id = None

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
        except Exception as exc:
            await self._send_error(websocket, "synthesize_failed", str(exc), state=state)
            return
        first_audio_ms = int((time.perf_counter() - started) * 1000)
        await self._send(
            websocket,
            state,
            "runtime.metric",
            {"metric": "time_to_first_audio", "value_ms": first_audio_ms, "turn_id": state.client_turn_id},
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
                "latency_ms": first_audio_ms,
            },
        )

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
            metrics["voice_stream"] = voice_metrics
            session.metrics = metrics
            db.commit()
        except Exception:
            db.rollback()

    def _authenticate(
        self,
        db: DBSession,
        *,
        token: Optional[str],
        workspace_slug: Optional[str],
    ) -> Optional[tuple[User, Workspace]]:
        if not token:
            return None
        raw = token.strip()
        if raw.lower().startswith("bearer "):
            raw = raw[7:].strip()
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
