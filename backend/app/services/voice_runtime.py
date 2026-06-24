"""Voice runtime providers for capture, chat and Flow Builder nodes.

Agentium keeps the production path provider-neutral: OpenAI Realtime is an
optional low-latency lane, while local/open-source STT, TTS and future
speech-to-speech runtimes can implement the same contract over HTTP or WS.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
from dataclasses import dataclass
from typing import Any, AsyncIterator, Dict, Iterable, Literal, Protocol, Sequence

import httpx
import openai

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_TRANSCRIBE_MODEL = os.getenv("OPENAI_TRANSCRIBE_MODEL", "gpt-4o-mini-transcribe")
_TTS_MODEL = os.getenv("OPENAI_TTS_MODEL", "gpt-4o-mini-tts")
_TTS_FAST_MODEL = os.getenv("OPENAI_TTS_FAST_MODEL", "tts-1")
_sync_client: openai.OpenAI | None = None
_async_client: openai.AsyncOpenAI | None = None

VOICE_CAPABILITIES = (
    "batch_transcription",
    "streaming_transcription",
    "tts",
    "speech_to_speech",
    "translation",
    "barge_in",
    "tool_calls",
    "micro_turn_streaming",
    "oracle_injection",
    "simultaneous_output",
    "background_tool_calls",
    "time_awareness",
)
VOICE_EVENTS = (
    "text.partial",
    "text.final",
    "audio.out",
    "translation.partial",
    "translation.final",
    "barge_in",
    "oracle.delta",
    "oracle.action",
    "oracle.commit",
    "oracle.superseded",
    "runtime.metric",
)

_ALIASES = {
    "cascade": "cascade_openai",
    "openai": "cascade_openai",
    "phase0": "cascade_openai",
    "openai_cascade": "cascade_openai",
    "cascade_openai": "cascade_openai",
    "realtime": "openai_realtime",
    "gpt_realtime": "openai_realtime",
    "gpt-realtime": "openai_realtime",
    "openai_realtime": "openai_realtime",
    "whisper": "local_stt",
    "local_whisper": "local_stt",
    "local_stt": "local_stt",
    "local_tts": "local_tts",
    "local_voice": "local_realtime",
    "local_realtime": "local_realtime",
    "realtime_gpu": "realtime_gpu",
    "moshi": "realtime_gpu",
    "kame": "realtime_gpu",
}


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


class VoiceProviderError(RuntimeError):
    code = "voice_provider_error"


class VoiceProviderCapabilityUnsupported(VoiceProviderError):
    code = "provider_capability_unsupported"


class VoiceProviderNotAllowed(VoiceProviderError):
    code = "provider_not_allowed"


class VoiceProviderUnavailable(VoiceProviderError):
    code = "provider_unavailable"


class VoiceRuntimeProvider(Protocol):
    slug: str
    capabilities: Dict[str, bool]

    async def transcribe(
        self,
        audio_bytes: bytes,
        *,
        filename: str = "recording.webm",
        content_type: str = "audio/webm",
        language: str | None = None,
    ) -> Dict[str, Any]:
        ...

    async def create_speech(
        self,
        text: str,
        *,
        voice: str | None = None,
        instructions: str | None = None,
        latency_profile: str | None = None,
        response_format: str = "mp3",
    ) -> SpeechResponse:
        ...

    async def synthesize_bytes(
        self,
        text: str,
        *,
        voice: str | None = None,
        instructions: str | None = None,
        latency_profile: str | None = None,
        response_format: str = "mp3",
    ) -> Dict[str, Any]:
        ...

    async def stream_in(self, frames: AsyncIterator[bytes]) -> AsyncIterator[VoiceToken]:
        ...

    async def stream_out(self, tokens: AsyncIterator[VoiceToken]) -> AsyncIterator[bytes]:
        ...


def _split_csv(value: str | Sequence[str] | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return [str(part).strip() for part in value if str(part).strip()]


def _voice_settings(workspace_settings: Any | None = None) -> Dict[str, Any]:
    if not isinstance(workspace_settings, dict):
        return {}
    value = workspace_settings.get("voice_runtime") or workspace_settings.get("voice") or {}
    return value if isinstance(value, dict) else {}


def normalize_voice_provider_slug(slug: str | None) -> str:
    raw = (slug or settings.voice_runtime_default_provider or "cascade_openai").strip()
    return _ALIASES.get(raw, raw)


def allowed_voice_providers(workspace_settings: Any | None = None) -> list[str]:
    voice = _voice_settings(workspace_settings)
    raw = voice.get("allowed_providers") or settings.voice_runtime_allowed_providers
    providers = [normalize_voice_provider_slug(item) for item in _split_csv(raw)]
    return providers or ["cascade_openai"]


def fallback_voice_providers(workspace_settings: Any | None = None) -> list[str]:
    voice = _voice_settings(workspace_settings)
    raw = voice.get("fallback_providers") or settings.voice_runtime_fallback_providers
    allowed = set(allowed_voice_providers(workspace_settings))
    return [provider for provider in (normalize_voice_provider_slug(item) for item in _split_csv(raw)) if provider in allowed]


def resolve_voice_runtime_slug(
    requested: str | None = None,
    *,
    workspace_settings: Any | None = None,
    system_voice: Dict[str, Any] | None = None,
    node_config: Dict[str, Any] | None = None,
) -> str:
    """Resolve node -> system -> workspace -> global provider priority."""
    voice = _voice_settings(workspace_settings)
    candidate = (
        (node_config or {}).get("provider")
        or (node_config or {}).get("runtime")
        or (system_voice or {}).get("provider")
        or (system_voice or {}).get("runtime")
        or requested
        or voice.get("default_provider")
        or settings.voice_runtime_default_provider
    )
    slug = normalize_voice_provider_slug(str(candidate) if candidate else None)
    allowed = set(allowed_voice_providers(workspace_settings))
    if slug not in allowed:
        raise VoiceProviderNotAllowed(f"Voice provider '{slug}' is not allowed for this workspace")
    return slug


def fallback_voice_runtime_slug(failed_slug: str, workspace_settings: Any | None = None) -> str | None:
    failed = normalize_voice_provider_slug(failed_slug)
    for provider in fallback_voice_providers(workspace_settings):
        if provider != failed:
            return provider
    return None


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


def _assert_capability(provider: VoiceRuntimeProvider, capability: str) -> None:
    if not provider.capabilities.get(capability):
        raise VoiceProviderCapabilityUnsupported(
            f"Voice provider '{provider.slug}' does not support capability '{capability}'"
        )


def _normalize_audio_format(value: str | None) -> str:
    candidate = (value or "mp3").strip().lower()
    return candidate if candidate in {"mp3", "opus", "aac", "flac", "wav", "pcm"} else "mp3"


def audio_media_type(response_format: str | None) -> str:
    fmt = _normalize_audio_format(response_format)
    return {
        "mp3": "audio/mpeg",
        "opus": "audio/ogg",
        "aac": "audio/aac",
        "flac": "audio/flac",
        "wav": "audio/wav",
        "pcm": "audio/pcm",
    }.get(fmt, "audio/mpeg")


_TTS_FAST_PROFILES = frozenset({"fast", "low", "lowest", "realtime"})


def _select_tts_model(latency_profile: str | None) -> str:
    """Map a latency profile to a TTS model.

    Only the explicit low-latency profiles fall back to the faster, lower-fidelity
    model (``tts-1`` by default). Every other profile — including ``balanced``,
    ``quality`` and the unset default — uses the higher-quality model
    (``gpt-4o-mini-tts`` by default). Both are env-overridable via
    ``OPENAI_TTS_MODEL`` / ``OPENAI_TTS_FAST_MODEL``.
    """
    profile = (latency_profile or "").strip().lower()
    if profile in _TTS_FAST_PROFILES:
        return _TTS_FAST_MODEL
    return _TTS_MODEL


def _model_supports_instructions(model: str | None) -> bool:
    """Whether a TTS model accepts the steering ``instructions`` field.

    Only the GPT-4o TTS family (e.g. ``gpt-4o-mini-tts``) is steerable. Passing
    ``instructions`` to ``tts-1`` / ``tts-1-hd`` raises a 400, so it must be
    dropped for those models — including on the fast fallback path.
    """
    name = (model or "").strip().lower()
    return name.startswith("gpt-4o") and "tts" in name


def _resolve_tts_voice(workspace_settings: Any | None, override: str | None) -> str:
    """Per-request override -> workspace voice settings -> env/code default."""
    if override:
        return override
    voice = _voice_settings(workspace_settings)
    candidate = voice.get("voice")
    if isinstance(candidate, str) and candidate.strip():
        return candidate.strip()
    return settings.openai_tts_voice or "sage"


def _resolve_tts_instructions(workspace_settings: Any | None, override: str | None) -> str | None:
    """Per-request override -> workspace voice settings -> env/code default.

    A workspace (or request) may set an empty string to explicitly disable
    steering; that is honoured and returns ``None`` (no instructions sent).
    """
    if override is not None:
        text = override.strip()
        return text or None
    voice = _voice_settings(workspace_settings)
    if "instructions" in voice:
        candidate = voice.get("instructions")
        text = str(candidate).strip() if candidate is not None else ""
        return text or None
    default = (settings.openai_tts_instructions or "").strip()
    return default or None


# Generic, domain-neutral STT steering prompt. Workspaces specialise the domain
# framing via ``settings.voice.transcript_context`` (e.g. an industrial vendor or
# product line); the live Andritz workspace pins its exact legacy string through
# the ``046_andritz_voice_capture_overrides`` migration.
_DEFAULT_TRANSCRIPT_CONTEXT = "Transcription en français d'un expert industriel."
_TRANSCRIBE_NOISE_HINT = "Ignore les bruits, la musique et les sons sans parole."


def _resolve_transcript_context(workspace_settings: Any | None) -> str:
    """Workspace ``settings.voice.transcript_context`` -> generic default.

    An explicit empty string disables the domain framing (only the noise hint is
    sent). Absent key falls back to the domain-neutral default.
    """
    voice = _voice_settings(workspace_settings)
    if "transcript_context" in voice:
        candidate = voice.get("transcript_context")
        return str(candidate).strip() if candidate is not None else ""
    return _DEFAULT_TRANSCRIPT_CONTEXT


class CascadeVoiceRuntime:
    """OpenAI-backed cascade provider used by the production-safe path."""

    slug = "cascade_openai"
    capabilities = {
        "batch_transcription": True,
        "streaming_transcription": False,
        "tts": True,
        "speech_to_speech": False,
        "translation": False,
        "barge_in": True,
        "tool_calls": False,
        "micro_turn_streaming": False,
        "oracle_injection": True,
        "simultaneous_output": False,
        "background_tool_calls": True,
        "time_awareness": True,
    }

    def __init__(self, workspace_settings: Any | None = None) -> None:
        # Retained so voice + steering instructions resolve from the workspace
        # the provider was created for, even on call sites (voice loop, skills)
        # that don't thread voice settings through every synthesize call.
        self._workspace_settings = workspace_settings

    async def transcribe(
        self,
        audio_bytes: bytes,
        *,
        filename: str = "recording.webm",
        content_type: str = "audio/webm",
        language: str | None = "fr",
    ) -> Dict[str, Any]:
        _assert_capability(self, "batch_transcription")
        if not settings.openai_api_key:
            raise VoiceProviderUnavailable("OpenAI API key not configured")

        async def _call(model: str) -> Dict[str, Any]:
            client = _get_async_client()
            kwargs: Dict[str, Any] = {
                "model": model,
                "file": (filename, audio_bytes, content_type),
            }
            if language:
                kwargs["language"] = language
                context = _resolve_transcript_context(self._workspace_settings)
                kwargs["prompt"] = (
                    f"{context} {_TRANSCRIBE_NOISE_HINT}" if context else _TRANSCRIBE_NOISE_HINT
                )
            result = await client.audio.transcriptions.create(
                **kwargs,
            )
            text = result.text or ""
            logger.info(
                "voice_runtime.transcribe.completed",
                provider=self.slug,
                model=model,
                text_chars=len(text),
            )
            return {"text": text, "transcript": text, "model": model, "provider": self.slug}

        try:
            return await _call(_TRANSCRIBE_MODEL)
        except Exception as primary_err:
            logger.warning(
                "voice_runtime.transcribe.primary_failed",
                model=_TRANSCRIBE_MODEL,
                error=str(primary_err),
            )
            if _TRANSCRIBE_MODEL != "whisper-1":
                fallback = await _call("whisper-1")
                fallback["fallback"] = True
                fallback["fallback_reason"] = "primary_transcribe_model_failed"
                return fallback
            raise

    async def create_speech(
        self,
        text: str,
        *,
        voice: str | None = None,
        instructions: str | None = None,
        latency_profile: str | None = None,
        response_format: str = "mp3",
    ) -> SpeechResponse:
        _assert_capability(self, "tts")
        if not settings.openai_api_key:
            raise VoiceProviderUnavailable("OpenAI API key not configured")
        if not text or len(text) > 4096:
            raise ValueError("Text must be 1-4096 characters")
        fmt = _normalize_audio_format(response_format)
        model = _select_tts_model(latency_profile)
        resolved_voice = _resolve_tts_voice(self._workspace_settings, voice)
        resolved_instructions = _resolve_tts_instructions(self._workspace_settings, instructions)

        def _create(model: str):
            client = _get_client()
            kwargs: Dict[str, Any] = {
                "model": model,
                "input": text,
                "voice": resolved_voice,
                "response_format": fmt,
            }
            # `instructions` steering is only valid for the GPT-4o TTS family.
            # Dropping it for tts-1 / tts-1-hd (incl. the fast fallback) avoids a
            # 400 and is the one place steering is allowed to degrade gracefully.
            if resolved_instructions and _model_supports_instructions(model):
                kwargs["instructions"] = resolved_instructions
            return client.audio.speech.create(**kwargs)

        loop = asyncio.get_running_loop()
        try:
            response = await loop.run_in_executor(None, _create, model)
            return SpeechResponse(response=response, model=model)
        except Exception as primary_err:
            logger.warning(
                "voice_runtime.synthesize.primary_failed",
                model=model,
                latency_profile=latency_profile,
                error=str(primary_err),
            )
            if model == "tts-1":
                raise
            fallback_model = _TTS_FAST_MODEL if _TTS_FAST_MODEL != model else "tts-1"
            response = await loop.run_in_executor(None, _create, fallback_model)
            return SpeechResponse(response=response, model=fallback_model)

    async def synthesize_bytes(
        self,
        text: str,
        *,
        voice: str | None = None,
        instructions: str | None = None,
        latency_profile: str | None = None,
        response_format: str = "mp3",
    ) -> Dict[str, Any]:
        speech = await self.create_speech(
            text,
            voice=voice,
            instructions=instructions,
            latency_profile=latency_profile,
            response_format=response_format,
        )
        audio_bytes = b"".join(speech.response.iter_bytes(4096))
        return {
            "audio_bytes": audio_bytes,
            "audio_base64": base64.b64encode(audio_bytes).decode("ascii"),
            "content_type": audio_media_type(response_format),
            "model": speech.model,
            "provider": self.slug,
            "latency_profile": latency_profile or "balanced",
            "bytes": len(audio_bytes),
        }

    async def stream_in(self, frames: AsyncIterator[bytes]) -> AsyncIterator[VoiceToken]:
        chunks: list[bytes] = []
        async for frame in frames:
            chunks.append(frame)
            yield VoiceToken(kind="control", payload={"event": "audio.frame", "bytes": len(frame)}, ts_ms=0)
        if not chunks:
            return
        result = await self.transcribe(b"".join(chunks))
        text = str(result.get("text") or "")
        yield VoiceToken(
            kind="text",
            payload=text,
            ts_ms=0,
            meta={"provider": self.slug, "model": result.get("model"), "fallback": result.get("fallback", False)},
        )

    async def stream_out(self, tokens: AsyncIterator[VoiceToken]) -> AsyncIterator[bytes]:
        async for token in tokens:
            if token.kind != "text" or not isinstance(token.payload, str):
                continue
            audio = await self.synthesize_bytes(token.payload)
            yield audio["audio_bytes"]


class OpenAIRealtimeVoiceRuntime:
    """Realtime lane descriptor with cascade fallback for batch calls.

    Browser-grade speech-to-speech uses the `/voice/realtime/*` endpoints to
    mint an OpenAI session or proxy SDP. The legacy batch methods remain usable
    by falling back to cascade_openai so existing Capture flows do not break
    when a system is configured with `openai_realtime`.
    """

    slug = "openai_realtime"
    capabilities = {
        "batch_transcription": False,
        "streaming_transcription": True,
        "tts": False,
        "speech_to_speech": True,
        "translation": True,
        "barge_in": True,
        "tool_calls": True,
        "micro_turn_streaming": True,
        "oracle_injection": True,
        "simultaneous_output": True,
        "background_tool_calls": True,
        "time_awareness": True,
    }

    def __init__(self, workspace_settings: Any | None = None) -> None:
        self._workspace_settings = workspace_settings

    def _cascade(self) -> "CascadeVoiceRuntime":
        return CascadeVoiceRuntime(workspace_settings=self._workspace_settings)

    async def transcribe(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        fallback = await self._cascade().transcribe(*args, **kwargs)
        fallback["requested_provider"] = self.slug
        fallback["fallback"] = True
        fallback["fallback_reason"] = "openai_realtime_batch_transcription_uses_cascade"
        return fallback

    async def create_speech(
        self,
        text: str,
        *,
        voice: str | None = None,
        instructions: str | None = None,
        latency_profile: str | None = None,
        response_format: str = "mp3",
    ) -> SpeechResponse:
        return await self._cascade().create_speech(
            text,
            voice=voice,
            instructions=instructions,
            latency_profile=latency_profile,
            response_format=response_format,
        )

    async def synthesize_bytes(
        self,
        text: str,
        *,
        voice: str | None = None,
        instructions: str | None = None,
        latency_profile: str | None = None,
        response_format: str = "mp3",
    ) -> Dict[str, Any]:
        fallback = await self._cascade().synthesize_bytes(
            text,
            voice=voice,
            instructions=instructions,
            latency_profile=latency_profile,
            response_format=response_format,
        )
        fallback["requested_provider"] = self.slug
        fallback["fallback"] = True
        fallback["fallback_reason"] = "openai_realtime_tts_uses_cascade"
        return fallback

    async def stream_in(self, *args: Any, **kwargs: Any) -> AsyncIterator[VoiceToken]:
        raise VoiceProviderCapabilityUnsupported("OpenAI Realtime streaming is exposed through WebRTC/WS session endpoints")

    async def stream_out(self, *args: Any, **kwargs: Any) -> AsyncIterator[bytes]:
        raise VoiceProviderCapabilityUnsupported("OpenAI Realtime streaming is exposed through WebRTC/WS session endpoints")


class LocalHttpVoiceRuntime:
    """Local/open-source provider via a stable HTTP contract."""

    def __init__(
        self,
        slug: str,
        endpoint_url: str | None,
        capabilities: Dict[str, bool],
        model: str | None = None,
        workspace_settings: Any | None = None,
    ):
        self.slug = slug
        self.endpoint_url = endpoint_url
        self.capabilities = capabilities
        self.model = model
        self._workspace_settings = workspace_settings

    def _endpoint(self) -> str:
        if not self.endpoint_url:
            raise VoiceProviderUnavailable(f"Local provider '{self.slug}' endpoint is not configured")
        return self.endpoint_url.rstrip("/")

    async def transcribe(
        self,
        audio_bytes: bytes,
        *,
        filename: str = "recording.webm",
        content_type: str = "audio/webm",
        language: str | None = None,
    ) -> Dict[str, Any]:
        _assert_capability(self, "batch_transcription")
        payload = {
            "audio_base64": base64.b64encode(audio_bytes).decode("ascii"),
            "filename": filename,
            "content_type": content_type,
            "model": self.model,
            "language": language,
        }
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(f"{self._endpoint()}/transcribe", json=payload)
            response.raise_for_status()
            data = response.json()
        text = str(data.get("text") or data.get("transcript") or "")
        return {
            **data,
            "text": text,
            "transcript": text,
            "provider": self.slug,
            "model": data.get("model") or self.model,
        }

    async def create_speech(
        self,
        text: str,
        *,
        voice: str | None = None,
        instructions: str | None = None,
        latency_profile: str | None = None,
        response_format: str = "mp3",
    ) -> SpeechResponse:
        _assert_capability(self, "tts")
        result = await self.synthesize_bytes(
            text,
            voice=voice,
            instructions=instructions,
            latency_profile=latency_profile,
            response_format=response_format,
        )
        return SpeechResponse(response=_BytesSpeechResponse(result["audio_bytes"]), model=result.get("model") or self.model or self.slug)

    async def synthesize_bytes(
        self,
        text: str,
        *,
        voice: str | None = None,
        instructions: str | None = None,
        latency_profile: str | None = None,
        response_format: str = "mp3",
    ) -> Dict[str, Any]:
        _assert_capability(self, "tts")
        payload = {
            "text": text,
            "voice": _resolve_tts_voice(self._workspace_settings, voice),
            "model": self.model,
            "latency_profile": latency_profile or "balanced",
            "format": _normalize_audio_format(response_format),
        }
        resolved_instructions = _resolve_tts_instructions(self._workspace_settings, instructions)
        if resolved_instructions:
            payload["instructions"] = resolved_instructions
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(f"{self._endpoint()}/synthesize", json=payload)
            response.raise_for_status()
            content_type = response.headers.get("content-type") or "audio/wav"
            if content_type.startswith("application/json"):
                data = response.json()
                raw = base64.b64decode(str(data.get("audio_base64") or ""))
                content_type = data.get("content_type") or "audio/wav"
                model = data.get("model") or self.model
            else:
                raw = response.content
                model = self.model
        return {
            "audio_bytes": raw,
            "audio_base64": base64.b64encode(raw).decode("ascii"),
            "content_type": content_type,
            "model": model,
            "provider": self.slug,
            "latency_profile": latency_profile or "balanced",
            "bytes": len(raw),
        }

    async def stream_in(self, *args: Any, **kwargs: Any) -> AsyncIterator[VoiceToken]:
        raise VoiceProviderCapabilityUnsupported(f"Provider '{self.slug}' streaming input is not bound in-process")

    async def stream_out(self, *args: Any, **kwargs: Any) -> AsyncIterator[bytes]:
        raise VoiceProviderCapabilityUnsupported(f"Provider '{self.slug}' streaming output is not bound in-process")


class RealtimeVoiceRuntime:
    """Experimental GPU lane placeholder for Moshi/KAME-like providers."""

    slug = "realtime_gpu"
    capabilities = {
        "batch_transcription": False,
        "streaming_transcription": True,
        "tts": False,
        "speech_to_speech": True,
        "translation": False,
        "barge_in": True,
        "tool_calls": True,
        "micro_turn_streaming": True,
        "oracle_injection": True,
        "simultaneous_output": True,
        "background_tool_calls": True,
        "time_awareness": True,
    }

    async def transcribe(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        raise VoiceProviderUnavailable("Realtime GPU voice runtime is experimental and not bound")

    async def create_speech(self, *args: Any, **kwargs: Any) -> SpeechResponse:
        raise VoiceProviderUnavailable("Realtime GPU voice runtime is experimental and not bound")

    async def synthesize_bytes(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        raise VoiceProviderUnavailable("Realtime GPU voice runtime is experimental and not bound")

    async def stream_in(self, *args: Any, **kwargs: Any) -> AsyncIterator[VoiceToken]:
        raise VoiceProviderUnavailable("Realtime GPU voice runtime is experimental and not bound")

    async def stream_out(self, *args: Any, **kwargs: Any) -> AsyncIterator[bytes]:
        raise VoiceProviderUnavailable("Realtime GPU voice runtime is experimental and not bound")


class _BytesSpeechResponse:
    def __init__(self, audio_bytes: bytes):
        self._audio_bytes = audio_bytes

    def iter_bytes(self, chunk_size: int = 4096) -> Iterable[bytes]:
        for idx in range(0, len(self._audio_bytes), chunk_size):
            yield self._audio_bytes[idx : idx + chunk_size]


def get_voice_runtime_provider(
    slug: str | None = "cascade_openai",
    *,
    workspace_settings: Any | None = None,
) -> VoiceRuntimeProvider:
    resolved = resolve_voice_runtime_slug(slug, workspace_settings=workspace_settings)
    if resolved == "cascade_openai":
        return CascadeVoiceRuntime(workspace_settings=workspace_settings)
    if resolved == "openai_realtime":
        return OpenAIRealtimeVoiceRuntime(workspace_settings=workspace_settings)
    if resolved == "local_stt":
        return LocalHttpVoiceRuntime(
            "local_stt",
            settings.local_stt_endpoint_url,
            {
                "batch_transcription": True,
                "streaming_transcription": True,
                "tts": False,
                "speech_to_speech": False,
                "translation": False,
                "barge_in": False,
                "tool_calls": False,
                "micro_turn_streaming": True,
                "oracle_injection": False,
                "simultaneous_output": False,
                "background_tool_calls": False,
                "time_awareness": True,
            },
        )
    if resolved == "local_tts":
        return LocalHttpVoiceRuntime(
            "local_tts",
            settings.local_tts_endpoint_url,
            {
                "batch_transcription": False,
                "streaming_transcription": False,
                "tts": True,
                "speech_to_speech": False,
                "translation": False,
                "barge_in": False,
                "tool_calls": False,
                "micro_turn_streaming": False,
                "oracle_injection": False,
                "simultaneous_output": False,
                "background_tool_calls": False,
                "time_awareness": True,
            },
            workspace_settings=workspace_settings,
        )
    if resolved == "local_realtime":
        return LocalHttpVoiceRuntime(
            "local_realtime",
            settings.local_realtime_endpoint_url,
            {
                "batch_transcription": False,
                "streaming_transcription": True,
                "tts": True,
                "speech_to_speech": True,
                "translation": True,
                "barge_in": True,
                "tool_calls": True,
                "micro_turn_streaming": True,
                "oracle_injection": True,
                "simultaneous_output": True,
                "background_tool_calls": True,
                "time_awareness": True,
            },
            workspace_settings=workspace_settings,
        )
    if resolved == "realtime_gpu":
        return RealtimeVoiceRuntime()
    raise ValueError(f"Unknown voice runtime provider: {resolved}")


def _provider_status(slug: str, workspace_slug: str | None = None) -> str:
    if slug == "cascade_openai":
        return "bound" if settings.openai_api_key else "unconfigured"
    if slug == "openai_realtime":
        if not settings.openai_realtime_enabled:
            return "disabled"
        if workspace_slug and workspace_slug not in set(_split_csv(settings.openai_realtime_enabled_workspace_slugs)):
            return "workspace_disabled"
        return "bound" if settings.openai_api_key else "unconfigured"
    if slug == "local_stt":
        return "bound" if settings.local_stt_endpoint_url else "unconfigured"
    if slug == "local_tts":
        return "bound" if settings.local_tts_endpoint_url else "unconfigured"
    if slug == "local_realtime":
        return "bound" if settings.local_realtime_endpoint_url else "unconfigured"
    if slug == "realtime_gpu":
        return "experimental"
    return "unknown"


def _provider_descriptor(slug: str, workspace_slug: str | None = None) -> Dict[str, Any]:
    provider = get_voice_runtime_provider(slug, workspace_settings={"voice_runtime": {"allowed_providers": [slug]}})
    descriptions = {
        "cascade_openai": "Reliable fallback lane: recorded chunks -> STT -> Agentium oracle -> segmented TTS.",
        "openai_realtime": "Optional OpenAI Realtime lane for live speech-to-speech, transcription, translation and tool calls.",
        "local_stt": "Local/open-source transcription lane exposed through Agentium's HTTP provider contract.",
        "local_tts": "Local/open-source speech synthesis lane exposed through Agentium's HTTP provider contract.",
        "local_realtime": "Future local speech-to-speech lane exposed through Agentium's provider contract.",
        "realtime_gpu": "Experimental GPU lane for Moshi/KAME-like realtime speech runtimes.",
    }
    return {
        "slug": slug,
        "status": _provider_status(slug, workspace_slug=workspace_slug),
        "description": descriptions.get(slug, ""),
        "requires_gpu": slug in {"local_realtime", "realtime_gpu"},
        "transport": "webrtc" if slug == "openai_realtime" else "backend_ws",
        "models": _provider_models(slug),
        "capabilities": {cap: bool(provider.capabilities.get(cap)) for cap in VOICE_CAPABILITIES},
    }


def _provider_models(slug: str) -> list[str]:
    if slug == "cascade_openai":
        return list(dict.fromkeys([_TRANSCRIBE_MODEL, _TTS_MODEL, _TTS_FAST_MODEL]))
    if slug == "openai_realtime":
        return [
            settings.openai_realtime_model,
            settings.openai_realtime_transcribe_model,
            settings.openai_realtime_translate_model,
        ]
    return []


def list_voice_runtime_providers(workspace: Any | None = None) -> Dict[str, Any]:
    workspace_settings = getattr(workspace, "settings", None) if workspace is not None else None
    workspace_slug = getattr(workspace, "slug", None) if workspace is not None else None
    allowed = allowed_voice_providers(workspace_settings)
    default_provider = resolve_voice_runtime_slug(None, workspace_settings=workspace_settings)
    return {
        "default_provider": default_provider,
        "allowed_providers": allowed,
        "fallback_providers": fallback_voice_providers(workspace_settings),
        "events": list(VOICE_EVENTS),
        "providers": [_provider_descriptor(slug, workspace_slug=workspace_slug) for slug in allowed],
        "decision_rule": (
            "Use realtime providers only when user tests improve fluency without reducing "
            "capture precision, transcript quality, auditability or governance."
        ),
    }


def build_openai_realtime_session(
    *,
    model: str | None = None,
    voice: str = "marin",
    instructions: str | None = None,
    input_language: str | None = None,
    output_language: str | None = None,
    capability: str = "voice2voice_interaction",
    metadata: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    session: Dict[str, Any] = {
        "type": "realtime",
        "model": model or settings.openai_realtime_model,
        "audio": {"output": {"voice": voice}},
        "metadata": {"agentium_capability": capability, **(metadata or {})},
    }
    if instructions:
        session["instructions"] = instructions
    if input_language:
        session.setdefault("audio", {}).setdefault("input", {})["language"] = input_language
    if output_language:
        session["metadata"]["output_language"] = output_language
    return session


def _ensure_openai_realtime_enabled(workspace_slug: str | None = None) -> None:
    if not settings.openai_realtime_enabled:
        raise VoiceProviderUnavailable("OpenAI Realtime is disabled for this environment")
    if workspace_slug and workspace_slug not in set(_split_csv(settings.openai_realtime_enabled_workspace_slugs)):
        raise VoiceProviderNotAllowed("OpenAI Realtime is not enabled for this workspace")
    if not settings.openai_api_key:
        raise VoiceProviderUnavailable("OpenAI API key not configured")


async def create_openai_realtime_client_secret(
    *,
    workspace_slug: str | None,
    session: Dict[str, Any],
) -> Dict[str, Any]:
    _ensure_openai_realtime_enabled(workspace_slug)
    url = f"{settings.openai_realtime_api_base.rstrip('/')}/realtime/client_secrets"
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            url,
            headers={"Authorization": f"Bearer {settings.openai_api_key}", "Content-Type": "application/json"},
            json={"session": session},
        )
        response.raise_for_status()
        return response.json()


async def create_openai_realtime_call(
    *,
    workspace_slug: str | None,
    sdp: str,
    session: Dict[str, Any],
) -> str:
    _ensure_openai_realtime_enabled(workspace_slug)
    if not settings.voice_realtime_webrtc_enabled:
        raise VoiceProviderUnavailable("OpenAI Realtime WebRTC proxy is disabled for this environment")
    url = f"{settings.openai_realtime_api_base.rstrip('/')}/realtime/calls"
    files = {
        "sdp": (None, sdp, "application/sdp"),
        "session": (None, json.dumps(session), "application/json"),
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(url, headers={"Authorization": f"Bearer {settings.openai_api_key}"}, files=files)
        response.raise_for_status()
        return response.text


def stream_response_bytes(response: Any, chunk_size: int = 4096) -> Iterable[bytes]:
    for chunk in response.iter_bytes(chunk_size):
        yield chunk
