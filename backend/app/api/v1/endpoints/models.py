"""Model management endpoints.

Auth gated (Vague D / D1): the model catalog is not sensitive per-se but
anonymous callers have no business probing which upstream LLMs are
wired, so we require an authenticated user.
"""
from fastapi import APIRouter, Depends, HTTPException
from typing import List
from app.core.auth import get_current_user
from app.core.logging import get_logger
from app.services.models import ModelService

logger = get_logger(__name__)
router = APIRouter(dependencies=[Depends(get_current_user)])
model_service = ModelService()


@router.get("")
async def list_models():
    """List available models"""
    try:
        models = await model_service.list_models()
        return {"models": models}
    except Exception as e:
        logger.error("Failed to list models", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{model_id}/status")
async def get_model_status(model_id: str):
    """Get model status"""
    try:
        status = await model_service.get_model_status(model_id)
        return {"model_id": model_id, "status": status}
    except Exception as e:
        logger.error("Failed to get model status", model_id=model_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

