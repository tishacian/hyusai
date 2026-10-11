"""Model management endpoints.

Auth gated (Vague D / D1): the model catalog is not sensitive per-se but
anonymous callers have no business probing which upstream LLMs are
wired, so we require an authenticated user.
"""
from fastapi import APIRouter, Depends, HTTPException
from app.core.auth import get_current_user, get_current_workspace
from app.models.workspace import Workspace
from app.services.model_plane import providers
from app.core.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(dependencies=[Depends(get_current_user)])


@router.get("")
async def list_models(workspace: Workspace = Depends(get_current_workspace)):
    """List available models"""
    try:
        models = await providers.list_models(workspace=workspace)
        return {"models": models}
    except Exception as e:
        logger.error("Failed to list models", error=str(e))
        raise HTTPException(status_code=502, detail={"code": "MODEL_CATALOG_UNAVAILABLE", "message": "The model catalogue could not be loaded."})


@router.get("/{model_id:path}/status")
async def get_model_status(model_id: str, workspace: Workspace = Depends(get_current_workspace)):
    """Return the same workspace-scoped discovery state as the catalogue."""
    try:
        catalog = await providers.list_models(workspace=workspace)
    except Exception as e:
        logger.error("Failed to get model status", model_id=model_id, error=str(e))
        raise HTTPException(status_code=502, detail={"code": "MODEL_CATALOG_UNAVAILABLE", "message": "The model catalogue could not be loaded."}) from e
    matches = [item for item in catalog if item.get("id") == model_id]
    if not matches:
        matches = [item for item in catalog if model_id in {item.get("model"), item.get("name")}]
    if not matches:
        raise HTTPException(status_code=404, detail={"code": "MODEL_NOT_FOUND", "message": "This model is absent from the workspace catalogue."})
    if len(matches) > 1:
        raise HTTPException(status_code=409, detail={"code": "MODEL_AMBIGUOUS", "message": "Choose the provider-qualified model identifier."})
    return {**matches[0], "model_id": model_id, "generation_verified": False}
