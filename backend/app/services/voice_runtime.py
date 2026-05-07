"""Voice runtime providers for capture and chat surfaces.

The product path starts with a reliable cascade provider (recording -> STT
-> knowledge oracle -> TTS). Realtime/GPU providers can be added behind
the same interface once user tests justify the operational cost.
"""
from __future__ import annotations

import asyncio
import os
from base64 import b64encode
from dataclasses import dataclass
from typing import Any, AsyncIterator, Dict, Iterable, Literal, Protocol

import openai

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_TRANSCRIBE_MODEL = os.getenv("OPENAI_TRANSCRIBE_MODEL", "gpt-4o-mini-transcribe")
_TTS_MODEL = os.getenv("OPENAI_TTS_MODEL", "gpt-4o-mini-tts")
_sync_client: openai.OpenAI | None = None
_async_client: openai.AsyncOpenAI | None = None


@dataclass
class SpeechResponse:
    response: Any
    model: str


@dataclass
class VoiceToken:
    kind: Literal["semantic", "acoustic", "text", "control"]
    payload: bytes | str | Dict[str, Any]
    ts_ms: int
    confidence: float | None = None
    meta: Dict[str, Any] | None = None


class VoiceRuntimeProvider(Protocol):
    slug: str

    async def transcribe(
        self,
        audio_bytes: bytes,
        *,
        filename: str = "recording.webm",
        content_type: str = "audio/webm",
    ) -> Dict[str, Any]:
        ...

    async def create_speech(self, text: str, *, voice: str = "nova") -> SpeechResponse:
        ...

    async def synthesize_bytes(self, text: str, *, voice: str = "nova") -> Dict[str, Any]:
        ...

    async def stream_in(self, frames: AsyncIterator[bytes]) -> AsyncIterator[VoiceToken]:
        ...

    async def stream_out(self, tokens: AsyncIterator[VoiceToken]) -> AsyncIterator[bytes]:
        ...


def _get_client() -> openai.OpenAI:
    global _sync_client
    if _sync_client is None:
        _sync_client = openai.OpenAI(api_key=settings.openai_api_key)
    return _sync_client


def _get_async_client() -> openai.AsyncOpenAI:
    global _async_client
    if _async_client is None:
        _async_client = openai.AsyncOpenAI(api_key=settings.openai_api_key)
    return _async_client


class CascadeVoiceRuntime:
    """OpenAI-backed cascade provider used by the Phase 0 product path."""

    slug = "cascade"

    async def transcribe(
        self,
        audio_bytes: bytes,
        *,
        filename: str = "recording.webm",
        content_type: str = "audio/webm",
    ) -> Dict[str, Any]:
        if not settings.openai_api_key:
            raise RuntimeError("OpenAI API key not configured")

        async def _call(model: str) -> Dict[str, Any]:
            client = _get_async_client()
            result = await client.audio.transcriptions.create(
                model=model,
                file=(filename, audio_bytes, content_type),
            )
            text = result.text or ""
            logger.info(
                "voice_runtime.transcribe: completed",
                provider=self.slug,
                model=model,
                text_chars=len(text),
            )
            return {"text": text, "transcript": text, "model": model, "provider": self.slug}

        try:
            return await _call(_TRANSCRIBE_MODEL)
        except Exception as primary_err:
            logger.warning(
                "voice_runtime.transcribe: primary model failed",
                model=_TRANSCRIBE_MODEL,
                error=str(primary_err),
            )
            if _TRANSCRIBE_MODEL != "whisper-1":
                fallback = await _call("whisper-1")
                fallback["fallback"] = True
                return fallback
            raise

    async def create_speech(self, text: str, *, voice: str = "nova") -> SpeechResponse:
        if not settings.openai_api_key:
            raise RuntimeError("OpenAI API key not configured")
        if not text or len(text) > 4096:
            raise ValueError("Text must be 1-4096 characters")

        def _create(model: str):
            client = _get_client()
            return client.audio.speech.create(
                model=model,
                input=text,
                voice=voice,
                response_format="mp3",
            )

        loop = asyncio.get_running_loop()
        try:
            response = await loop.run_in_executor(None, _create, _TTS_MODEL)
            return SpeechResponse(response=response, model=_TTS_MODEL)
        except Exception as primary_err:
            logger.warning(
                "voice_runtime.synthesize: primary model failed",
                model=_TTS_MODEL,
                error=str(primary_err),
            )
            if _TTS_MODEL == "tts-1":
                raise
            response = await loop.run_in_executor(None, _create, "tts-1")
            return SpeechResponse(response=response, model="tts-1")

    async def synthesize_bytes(self, text: str, *, voice: str = "nova") -> Dict[str, Any]:
        speech = await self.create_speech(text, voice=voice)
        audio_bytes = b"".join(speech.response.iter_bytes(4096))
        return {
            "audio_bytes": audio_bytes,
            "audio_base64": b64encode(audio_bytes).decode("ascii"),
            "content_type": "audio/mpeg",
            "model": speech.model,
            "provider": self.slug,
            "bytes": len(audio_bytes),
        }

    async def stream_in(self, frames: AsyncIterator[bytes]) -> AsyncIterator[VoiceToken]:
        """Streaming-compatible cascade shim.

        The cascade provider still transcribes complete audio segments. This
        method gives the gateway a provider-neutral shape for J1 and lets a
        realtime provider later yield native semantic/acoustic tokens.
        """
        chunks: list[bytes] = []
        async for frame in frames:
            chunks.append(frame)
            yield VoiceToken(kind="control", payload={"event": "audio.frame", "bytes": len(frame)}, ts_ms=0)
        if not chunks:
            return
        result = await self.transcribe(b"".join(chunks))
        text = str(result.get("text") or "")
        yield VoiceToken(kind="text", payload=text, ts_ms=0, meta={"provider": self.slug, "model": result.get("model")})

    async def stream_out(self, tokens: AsyncIterator[VoiceToken]) -> AsyncIterator[bytes]:
        async for token in tokens:
            if token.kind != "text" or not isinstance(token.payload, str):
                continue
            audio = await self.synthesize_bytes(token.payload)
            yield audio["audio_bytes"]


class RealtimeVoiceRuntime:
    """Experimental GPU lane placeholder for Moshi/KAME-like providers."""

    slug = "realtime_gpu"

    async def transcribe(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        raise NotImplementedError("Realtime GPU voice runtime is experimental and not bound")

    async def create_speech(self, *args: Any, **kwargs: Any) -> SpeechResponse:
        raise NotImplementedError("Realtime GPU voice runtime is experimental and not bound")

    async def synthesize_bytes(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        raise NotImplementedError("Realtime GPU voice runtime is experimental and not bound")

    async def stream_in(self, *args: Any, **kwargs: Any) -> AsyncIterator[VoiceToken]:
        raise NotImplementedError("Realtime GPU voice runtime is experimental and not bound")

    async def stream_out(self, *args: Any, **kwargs: Any) -> AsyncIterator[bytes]:
        raise NotImplementedError("Realtime GPU voice runtime is experimental and not bound")


def get_voice_runtime_provider(slug: str = "cascade") -> VoiceRuntimeProvider:
    if slug in {"cascade", "openai", "phase0"}:
        return CascadeVoiceRuntime()
    if slug in {"realtime", "realtime_gpu", "moshi", "kame"}:
        return RealtimeVoiceRuntime()
    raise ValueError(f"Unknown voice runtime provider: {slug}")


def list_voice_runtime_providers() -> Dict[str, Any]:
    return {
        "providers": [
            {
                "slug": "cascade",
                "status": "bound",
                "description": "Phase 0 provider: recording -> STT -> knowledge oracle -> segmented TTS.",
                "requires_gpu": False,
                "capabilities": {
                    "chunked_capture": True,
                    "segmented_tts": True,
                    "barge_in_ui": True,
                    "streaming_ws": True,
                    "full_duplex": False,
                },
            },
            {
                "slug": "realtime_gpu",
                "status": "experimental",
                "description": "GPU spike lane for Moshi/KAME-like realtime speech guided by the platform oracle.",
                "requires_gpu": True,
                "capabilities": {
                    "chunked_capture": True,
                    "segmented_tts": True,
                    "barge_in_ui": True,
                    "streaming_ws": True,
                    "full_duplex": True,
                },
            },
        ],
        "decision_rule": (
            "Use realtime_gpu as a product dependency only if user tests improve fluency "
            "without reducing capture precision, auditability or governance."
        ),
    }


def stream_response_bytes(response: Any, chunk_size: int = 4096) -> Iterable[bytes]:
    for chunk in response.iter_bytes(chunk_size):
        yield chunk
