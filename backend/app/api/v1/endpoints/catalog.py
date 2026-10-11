"""Agentium surface catalog endpoints."""

from fastapi import APIRouter, Depends, Request

from app.core.auth import get_current_user
from app.models.user import User
from app.services.surface_catalog import build_endpoint_catalog, surface_metadata

router = APIRouter(dependencies=[Depends(get_current_user)])


@router.get("/endpoints")
async def list_endpoint_catalog(
    request: Request,
    _: User = Depends(get_current_user),
) -> dict:
    """Return concrete OpenAPI routes enriched with Agentium surface metadata."""

    return build_endpoint_catalog(request.app.openapi())


@router.get("/surfaces")
async def list_surfaces(_: User = Depends(get_current_user)) -> dict:
    """Return prefix-level mental model metadata used by docs and the UI."""

    return {"surfaces": surface_metadata()}
