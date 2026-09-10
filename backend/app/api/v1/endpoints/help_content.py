"""Help content endpoint — serves persona-aware tooltips for the cockpit.

``GET`` is intentionally public (the frontend fetches it on boot, before
the user is authenticated, to populate static UI copy). ``POST /reload``
is admin/operator-only and therefore auth-gated.
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, Query

from app.core.auth import get_current_user
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


@router.post("/reload", dependencies=[Depends(get_current_user)])
async def reload_help_content():
    """Hot-reload the registry — useful in dev / after content edits."""
    index = load_help_index(force=True)
    return {"version": index.version, "count": len(index.items)}


@router.get("/guides/{guide_id}")
async def read_help_guide(guide_id: str, language: str = "en"):
    import json
    from pathlib import Path
    from fastapi import HTTPException
    guides = json.loads((Path(__file__).resolve().parents[3] / "content" / "adoption_guides.json").read_text())
    if guide_id not in guides or language not in {"en", "fr"}:
        raise HTTPException(status_code=404, detail="Guide not found")
    title, *paragraphs = guides[guide_id][language]
    return {"id": guide_id, "language": language, "title": title, "paragraphs": paragraphs}
