"""In-memory loader for the persona-aware help registry.

The YAML file lives in ``backend/app/content/help_content.yaml`` and is
loaded once per process then memoised. Reload happens on-demand via
``load_help_index(force=True)`` for hot-swap in dev / tests.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Optional

import yaml

from app.schemas.help import HelpContent, HelpContentIndex


_CONTENT_PATH = Path(__file__).resolve().parent.parent.parent / "content" / "help_content.yaml"


def _load_from_disk() -> HelpContentIndex:
    if not _CONTENT_PATH.exists():
        return HelpContentIndex(
            version="0.0.0",
            personas=["builder", "operator", "executive"],
            items=[],
        )
    raw = yaml.safe_load(_CONTENT_PATH.read_text(encoding="utf-8")) or {}
    items = [HelpContent(**row) for row in (raw.get("items") or [])]
    return HelpContentIndex(
        version=raw.get("version", "dev"),
        personas=raw.get("personas", ["builder", "operator", "executive"]),
        items=items,
    )


@lru_cache(maxsize=1)
def _cached_index() -> HelpContentIndex:
    return _load_from_disk()


def load_help_index(*, force: bool = False) -> HelpContentIndex:
    if force:
        _cached_index.cache_clear()
    return _cached_index()


def get_help_index(ids: Optional[list[str]] = None) -> HelpContentIndex:
    index = load_help_index()
    if not ids:
        return index
    wanted = set(ids)
    filtered = [i for i in index.items if i.id in wanted]
    return HelpContentIndex(version=index.version, personas=index.personas, items=filtered)
