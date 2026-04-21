"""Help content endpoint — serves persona-aware tooltips for the cockpit."""
from typing import List, Optional

from fastapi import APIRouter, Query

from app.schemas.help import HelpContentIndex
from app.services.help_content import get_help_index, load_help_index

router = APIRouter()


@router.get("", response_model=HelpContentIndex)
async def list_help_content(
    ids: Optional[List[str]] = Query(default=None, description="Filter by id[]."),
):
    """Return the full help registry or a subset.

    The frontend ``HelpService`` fetches this once on boot and caches it
    locally; the persona filtering happens on the client so switching
    persona is instant.
    """
    return get_help_index(ids)


@router.post("/reload")
async def reload_help_content():
    """Hot-reload the registry — useful in dev / after content edits."""
    index = load_help_index(force=True)
    return {"version": index.version, "count": len(index.items)}
