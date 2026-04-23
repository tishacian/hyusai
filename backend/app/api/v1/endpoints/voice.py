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

import asyncio
import os

from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import openai

from app.core.auth import get_current_user
from app.core.config import settings

router = APIRouter(dependencies=[Depends(get_current_user)])

_sync_client: openai.OpenAI | None = None
_async_client: openai.AsyncOpenAI | None = None


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


# Allow ops to pin the model without a redeploy. ``gpt-4o-mini-transcribe``
# is the fastest general-purpose STT as of April 2026; ``whisper-1`` is
# the slower legacy fallback.
_TRANSCRIBE_MODEL = os.getenv("OPENAI_TRANSCRIBE_MODEL", "gpt-4o-mini-transcribe")


class SynthesizeRequest(BaseModel):
    text: str
    voice: str = "nova"


@router.post("/transcribe")
async def transcribe_audio(file: UploadFile = File(...)):
    if not settings.openai_api_key:
        raise HTTPException(status_code=503, detail="OpenAI API key not configured")

    audio_bytes = await file.read()
    filename = file.filename or "recording.webm"
    content_type = file.content_type or "audio/webm"

    async def _call(model: str) -> dict:
        client = _get_async_client()
        result = await client.audio.transcriptions.create(
            model=model,
            file=(filename, audio_bytes, content_type),
        )
        return {"text": result.text, "model": model}

    try:
        return await _call(_TRANSCRIBE_MODEL)
    except Exception as primary_err:
        # Some accounts haven't been rolled the GPT-4o audio family yet —
        # retry with the legacy whisper-1 before surfacing the failure.
        if _TRANSCRIBE_MODEL != "whisper-1":
            try:
                return {**(await _call("whisper-1")), "fallback": True}
            except Exception as fallback_err:
                raise HTTPException(status_code=500, detail=str(fallback_err))
        raise HTTPException(status_code=500, detail=str(primary_err))


@router.post("/synthesize")
async def synthesize_speech(req: SynthesizeRequest):
    if not settings.openai_api_key:
        raise HTTPException(status_code=503, detail="OpenAI API key not configured")

    if not req.text or len(req.text) > 4096:
        raise HTTPException(status_code=400, detail="Text must be 1-4096 characters")

    # Sync client in a threadpool so we don't block the event loop while
    # OpenAI serialises the MP3 — the streaming iterator is then safe to
    # consume from the FastAPI worker thread.
    def _create():
        client = _get_client()
        return client.audio.speech.create(
            model="tts-1",
            input=req.text,
            voice=req.voice,
            response_format="mp3",
        )

    try:
        response = await asyncio.get_running_loop().run_in_executor(None, _create)

        def _stream():
            for chunk in response.iter_bytes(4096):
                yield chunk

        return StreamingResponse(_stream(), media_type="audio/mpeg")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
