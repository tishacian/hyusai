"""Secret-free build identity for deployment attestations."""
from __future__ import annotations

import re

from fastapi import APIRouter

from app.core.config import settings

router = APIRouter()

_FULL_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")


@router.get("")
def build_info() -> dict[str, object]:
    revision = str(settings.agentium_image_revision or "development").strip().lower()
    return {
        "service": "backend",
        "revision": revision,
        "revision_verified": bool(_FULL_GIT_SHA.fullmatch(revision)),
        "version": settings.app_version,
    }
