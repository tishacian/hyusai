"""Voice endpoints: STT (Whisper) and TTS (OpenAI).

Auth gated (Vague D / D1): this router proxies paid OpenAI APIs, so
unauthenticated callers would be a cost-abuse vector. Both transcription
and synthesis now require a valid session token.
"""

from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import openai

from app.core.auth import get_current_user
from app.core.config import settings

router = APIRouter(dependencies=[Depends(get_current_user)])

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = openai.OpenAI(api_key=settings.openai_api_key)
    return _client


class SynthesizeRequest(BaseModel):
    text: str
    voice: str = "nova"


@router.post("/transcribe")
async def transcribe_audio(file: UploadFile = File(...)):
    if not settings.openai_api_key:
        raise HTTPException(status_code=503, detail="OpenAI API key not configured")

    try:
        client = _get_client()
        result = client.audio.transcriptions.create(
            model="whisper-1",
            file=(file.filename, await file.read(), file.content_type or "audio/webm"),
        )
        return {"text": result.text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/synthesize")
async def synthesize_speech(req: SynthesizeRequest):
    if not settings.openai_api_key:
        raise HTTPException(status_code=503, detail="OpenAI API key not configured")

    if not req.text or len(req.text) > 4096:
        raise HTTPException(status_code=400, detail="Text must be 1-4096 characters")

    try:
        client = _get_client()
        response = client.audio.speech.create(
            model="tts-1",
            input=req.text,
            voice=req.voice,
            response_format="mp3",
        )

        def _stream():
            for chunk in response.iter_bytes(4096):
                yield chunk

        return StreamingResponse(_stream(), media_type="audio/mpeg")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
