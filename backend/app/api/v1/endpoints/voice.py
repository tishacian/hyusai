"""Voice endpoints: STT (Whisper/GPT-4o) and TTS (OpenAI).

Auth gated (Vague D / D1): this router proxies paid OpenAI APIs, so
unauthenticated callers would be a cost-abuse vector. Both transcription
and synthesis now require a valid session token.

Implementation notes:
- STT uses ``gpt-4o-mini-transcribe`` by default — ~3× faster than
  ``whisper-1`` at equivalent quality. Override via
  ``OPENAI_TRANSCRIBE_MODEL`` env to fall back to ``whisper-1`` if the
  account hasn't rolled out the GPT-4o audio family yet.
- STT uses ``AsyncOpenAI`` so the event loop stays responsive for other
  requests while Whisper/GPT-4o runs.
- TTS keeps the sync client but dispatches to a threadpool for the
  blocking call, preserving the streaming response pattern.
"""

import os
import time
from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, WebSocket
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from app.db.base import get_db
from app.core.iam.dependencies import PermissionContext, require_permission
from app.core.logging import get_logger
from app.models.expert_capture import ExpertCaptureSession
from sqlalchemy.orm import Session as DBSession
from app.services.voice_runtime import (
    VoiceProviderCapabilityUnsupported,
    VoiceProviderError,
    VoiceProviderNotAllowed,
    VoiceProviderUnavailable,
    audio_media_type,
    build_openai_realtime_session,
    create_openai_realtime_call,
    create_openai_realtime_client_secret,
    get_voice_runtime_provider,
    list_voice_runtime_providers,
    resolve_voice_runtime_slug,
    stream_response_bytes,
)
from app.services.voice_session_gateway import VoiceSessionGateway

logger = get_logger(__name__)

router = APIRouter()

voice_read = require_permission(
    "voice_runtime",
    "read",
    static_attrs={"capability": "voice2voice_interaction"},
    audit_prefix="kc",
)


class SynthesizeRequest(BaseModel):
    text: str
    # None lets the cascade resolve the workspace / env default voice + steering
    # (per-request override -> workspace voice settings -> env/code default).
    voice: Optional[str] = None
    instructions: Optional[str] = None
    provider: Optional[str] = None
    latency_profile: Optional[str] = None
    surface: Optional[str] = None
    format: Optional[str] = None


class RealtimeSessionRequest(BaseModel):
    provider: str = "openai_realtime"
    model: Optional[str] = None
    voice: str = "marin"
    instructions: Optional[str] = None
    input_language: Optional[str] = None
    output_language: Optional[str] = None
    transport: str = "webrtc"
    capability: str = "voice2voice_interaction"
    metadata: Dict[str, Any] = Field(default_factory=dict)


class RealtimeCallRequest(RealtimeSessionRequest):
    sdp: str


class VoiceMirrorEventRequest(BaseModel):
    type: str
    payload: Dict[str, Any] = Field(default_factory=dict)
    provider: Optional[str] = None
    model: Optional[str] = None
    transport: Optional[str] = None
    sequence: Optional[int] = None


@router.websocket("/sessions/{session_id}")
async def voice_session_socket(
    websocket: WebSocket,
    session_id: str,
    token: Optional[str] = Query(None),
    workspace_slug: Optional[str] = Query(None),
    db: DBSession = Depends(get_db),
):
    await VoiceSessionGateway().handle(
        websocket,
        session_id=session_id,
        token=token,
        workspace_slug=workspace_slug,
        db=db,
    )


@router.get("/runtimes")
async def voice_runtimes(permission: PermissionContext = Depends(voice_read)):
    return list_voice_runtime_providers(workspace=permission.workspace)


@router.post("/transcribe")
async def transcribe_audio(
    file: UploadFile = File(...),
    provider_slug: Optional[str] = Query(None, alias="provider"),
    language: Optional[str] = Query("fr", min_length=2, max_length=8),
    permission: PermissionContext = Depends(voice_read),
):
    audio_bytes = await file.read()
    filename = file.filename or "recording.webm"
    content_type = file.content_type or "audio/webm"
    logger.info(
        "transcribe: received audio",
        filename=filename,
        content_type=content_type,
        bytes=len(audio_bytes),
    )
    provider = get_voice_runtime_provider(provider_slug or "cascade_openai", workspace_settings=permission.workspace.settings)
    try:
        return await provider.transcribe(
            audio_bytes,
            filename=filename,
            content_type=content_type,
            language=language or "fr",
        )
    except VoiceProviderError as exc:
        status = 403 if isinstance(exc, VoiceProviderNotAllowed) else 503
        raise HTTPException(status_code=status, detail={"code": exc.code, "message": str(exc)}) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("transcribe: failed", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/synthesize")
async def synthesize_speech(
    req: SynthesizeRequest,
    permission: PermissionContext = Depends(voice_read),
):
    started_at = time.perf_counter()
    response_format = req.format or "mp3"
    latency_profile = (req.latency_profile or "balanced").strip().lower()
    surface = (req.surface or "unknown").strip() or "unknown"
    # Capture must not be stuck on the muffled low-latency model. Unless explicitly
    # opted back in via env, coerce capture surfaces off the "fast" profile so they
    # reach the higher-quality TTS model.
    if (
        "capture" in surface.lower()
        and latency_profile in {"fast", "low", "lowest", "realtime"}
        and os.getenv("CAPTURE_TTS_ALLOW_FAST", "").strip().lower() not in {"1", "true", "yes"}
    ):
        latency_profile = "balanced"
    try:
        provider = get_voice_runtime_provider(req.provider or "cascade_openai", workspace_settings=permission.workspace.settings)
        speech = await provider.create_speech(
            req.text,
            voice=req.voice,
            instructions=req.instructions,
            latency_profile=latency_profile,
            response_format=response_format,
        )
        logger.info(
            "synthesize: streaming",
            surface=surface,
            provider=getattr(provider, "slug", req.provider or "cascade_openai"),
            model=speech.model,
            latency_profile=latency_profile,
            text_chars=len(req.text),
            duration_ms=round((time.perf_counter() - started_at) * 1000),
        )
        return StreamingResponse(stream_response_bytes(speech.response), media_type=audio_media_type(response_format))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except VoiceProviderError as exc:
        status = 400 if isinstance(exc, VoiceProviderCapabilityUnsupported) else 503
        raise HTTPException(status_code=status, detail={"code": exc.code, "message": str(exc)}) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("synthesize: failed", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/realtime/client-secret")
async def realtime_client_secret(
    req: RealtimeSessionRequest,
    permission: PermissionContext = Depends(voice_read),
):
    try:
        provider = resolve_voice_runtime_slug(req.provider, workspace_settings=permission.workspace.settings)
        if provider != "openai_realtime":
            raise VoiceProviderCapabilityUnsupported("Ephemeral Realtime client secrets are only supported by openai_realtime")
        session = build_openai_realtime_session(
            model=req.model,
            voice=req.voice,
            instructions=req.instructions,
            input_language=req.input_language,
            output_language=req.output_language,
            capability=req.capability,
            metadata={
                **(req.metadata or {}),
                "workspace_id": permission.workspace.id,
                "user_id": permission.user.id,
                "transport": req.transport,
            },
        )
        token = await create_openai_realtime_client_secret(
            workspace_slug=permission.workspace.slug,
            session=session,
            workspace=permission.workspace,
        )
        return {"provider": provider, "session": session, "client_secret": token}
    except VoiceProviderError as exc:
        status = 403 if isinstance(exc, VoiceProviderNotAllowed) else 503
        if isinstance(exc, VoiceProviderCapabilityUnsupported):
            status = 400
        raise HTTPException(status_code=status, detail={"code": exc.code, "message": str(exc)}) from exc
    except httpx.HTTPStatusError as exc:
        logger.warning("voice.realtime.client_secret.http_error", status=exc.response.status_code, body=exc.response.text[:500])
        raise HTTPException(status_code=exc.response.status_code, detail={"code": "openai_realtime_error", "message": exc.response.text}) from exc


@router.post("/realtime/calls")
async def realtime_call(
    req: RealtimeCallRequest,
    permission: PermissionContext = Depends(voice_read),
):
    try:
        provider = resolve_voice_runtime_slug(req.provider, workspace_settings=permission.workspace.settings)
        if provider != "openai_realtime":
            raise VoiceProviderCapabilityUnsupported("Realtime WebRTC calls are only supported by openai_realtime")
        session = build_openai_realtime_session(
            model=req.model,
            voice=req.voice,
            instructions=req.instructions,
            input_language=req.input_language,
            output_language=req.output_language,
            capability=req.capability,
            metadata={
                **(req.metadata or {}),
                "workspace_id": permission.workspace.id,
                "user_id": permission.user.id,
                "transport": req.transport,
            },
        )
        answer_sdp = await create_openai_realtime_call(
            workspace_slug=permission.workspace.slug,
            sdp=req.sdp,
            session=session,
            workspace=permission.workspace,
        )
        return Response(answer_sdp, media_type="application/sdp")
    except VoiceProviderError as exc:
        status = 403 if isinstance(exc, VoiceProviderNotAllowed) else 503
        if isinstance(exc, VoiceProviderCapabilityUnsupported):
            status = 400
        raise HTTPException(status_code=status, detail={"code": exc.code, "message": str(exc)}) from exc
    except httpx.HTTPStatusError as exc:
        logger.warning("voice.realtime.calls.http_error", status=exc.response.status_code, body=exc.response.text[:500])
        raise HTTPException(status_code=exc.response.status_code, detail={"code": "openai_realtime_error", "message": exc.response.text}) from exc


@router.post("/sessions/{session_id}/events")
async def mirror_voice_session_event(
    session_id: str,
    req: VoiceMirrorEventRequest,
    permission: PermissionContext = Depends(voice_read),
    db: DBSession = Depends(get_db),
):
    session = (
        db.query(ExpertCaptureSession)
        .filter(
            ExpertCaptureSession.id == session_id,
            ExpertCaptureSession.workspace_id == permission.workspace.id,
        )
        .first()
    )
    if session:
        metrics = dict(session.metrics or {})
        mirror = dict(metrics.get("voice_mirror") or {})
        mirror["events"] = int(mirror.get("events") or 0) + 1
        mirror["last_event_type"] = req.type
        mirror["last_provider"] = req.provider
        mirror["last_model"] = req.model
        mirror["last_transport"] = req.transport
        metrics["voice_mirror"] = mirror
        session.metrics = metrics
        db.commit()
    return {
        "status": "recorded",
        "session_id": session_id,
        "event_type": req.type,
        "mirrored": bool(session),
    }
