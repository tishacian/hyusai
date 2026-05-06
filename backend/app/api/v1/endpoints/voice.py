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

from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.core.auth import get_current_user
from app.core.logging import get_logger
from app.services.voice_runtime import (
    get_voice_runtime_provider,
    list_voice_runtime_providers,
    stream_response_bytes,
)

logger = get_logger(__name__)

router = APIRouter(dependencies=[Depends(get_current_user)])


class SynthesizeRequest(BaseModel):
    text: str
    voice: str = "nova"


@router.get("/runtimes")
async def voice_runtimes():
    return list_voice_runtime_providers()


@router.post("/transcribe")
async def transcribe_audio(file: UploadFile = File(...)):
    audio_bytes = await file.read()
    filename = file.filename or "recording.webm"
    content_type = file.content_type or "audio/webm"
    logger.info(
        "transcribe: received audio",
        filename=filename,
        content_type=content_type,
        bytes=len(audio_bytes),
    )
    provider = get_voice_runtime_provider("cascade")
    try:
        return await provider.transcribe(
            audio_bytes,
            filename=filename,
            content_type=content_type,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("transcribe: failed", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/synthesize")
async def synthesize_speech(req: SynthesizeRequest):
    try:
        provider = get_voice_runtime_provider("cascade")
        speech = await provider.create_speech(req.text, voice=req.voice)
        logger.info(
            "synthesize: streaming",
            model=speech.model,
            text_chars=len(req.text),
        )
        return StreamingResponse(stream_response_bytes(speech.response), media_type="audio/mpeg")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("synthesize: failed", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc
