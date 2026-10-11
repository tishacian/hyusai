"""Adapter over the monorepo `src/metadata_extraction/docmeta` package.

Why this shim exists
--------------------
Before this module, chunk metadata stored in the vector DB was limited to
what the document parser surfaced (filename, chunk index, char offsets). That
was enough to retrieve text but not enough to answer "what is this document
about?" or to render human-readable citations in the chat UI.

The existing ``docmeta`` package in ``src/metadata_extraction`` already
handles PDF / Office / ODT / text / markup / structured data / images and
produces titles, authors, embedded + TF-IDF keywords, token counts, page
counts, etc. Rather than duplicate that work we expose it to the backend via
a single helper while keeping the original package as the canonical source.

Design notes
------------
- We add ``src/metadata_extraction`` to ``sys.path`` lazily on first import.
  The source package uses absolute imports (``from docmeta.X``), so a plain
  sys.path shim is the least invasive option.
- Every public call is wrapped in a broad ``try/except`` so that a missing
  optional dep (``nltk`` corpora, ``PyMuPDF`` on a slim image, ...) or a
  corrupt file never breaks the ingestion pipeline. We log the failure and
  return an empty dict — callers merge our output into chunk metadata, so an
  empty dict is a no-op.
- Returned keys are prefixed with ``document_`` to avoid collisions with
  chunk-level keys already present in ``DocumentService`` (``document_id``,
  ``document_filename``, ``document_type``).
"""

from __future__ import annotations

import os
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)

_SYS_PATH_LOCK = threading.Lock()
_SYS_PATH_READY = False


def _ensure_docmeta_on_path() -> bool:
    """Insert ``src/metadata_extraction`` into ``sys.path`` once.

    Returns True if ``docmeta`` is importable after the call, False otherwise.
    """
    global _SYS_PATH_READY
    if _SYS_PATH_READY:
        return True

    with _SYS_PATH_LOCK:
        if _SYS_PATH_READY:
            return True

        # Resolve the monorepo root relative to this file.
        # backend/app/services/document_meta/__init__.py -> repo root
        here = Path(__file__).resolve()
        repo_root = here.parents[4]  # document_meta -> services -> app -> backend -> root
        candidate = repo_root / "src" / "metadata_extraction"

        # In case we're deployed from a copy that relocates the backend, honour
        # an explicit override so ops can point us at the right tree.
        override = os.environ.get("DOCMETA_SRC_DIR")
        if override:
            candidate = Path(override)

        if not candidate.is_dir():
            logger.warning(
                "docmeta source directory not found; metadata enrichment disabled",
                candidate=str(candidate),
            )
            return False

        path_str = str(candidate)
        if path_str not in sys.path:
            sys.path.insert(0, path_str)

        try:
            import docmeta  # noqa: F401
            import docmeta.extractors  # noqa: F401 — triggers extension/MIME registration

            _SYS_PATH_READY = True
            logger.info("docmeta ready", path=path_str)
            return True
        except Exception as e:  # pragma: no cover — env-dependent
            logger.warning(
                "docmeta import failed; metadata enrichment disabled",
                error=str(e),
                path=path_str,
            )
            return False


def _normalise_value(value: Any) -> Any:
    """Coerce docmeta values into JSON-safe primitives for the vector DB."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (list, tuple)):
        return [_normalise_value(v) for v in value]
    if isinstance(value, dict):
        return {k: _normalise_value(v) for k, v in value.items()}
    return value


# Fields we intentionally drop: they live on the filesystem side and bloat
# chunk metadata without helping retrieval or UI.
_DROPPED_KEYS = {
    "file_path",
    "file_permissions",
    "size",
    "creation_time",
    "last_modified_time",
    "last_accessed_time",
    "mime_type",
    "file_extension",
    "file_name",
    "encrypted",
    # Binary blobs from images
    "exif_data",
}


def extract_document_metadata(
    path: str,
    *,
    extract_keywords_language: str | None = "english",
    count_tokens: bool = True,
) -> dict[str, Any]:
    """Extract rich document metadata via docmeta.

    Args:
        path: Path to the source document on disk.
        extract_keywords_language: Language passed to the TF-IDF extractor.
            ``None`` disables keyword extraction. Short drops still cost very
            little; we keep it on by default so the chat can cite topics.
        count_tokens: Whether to run the tiktoken counter on the full text.

    Returns:
        A flat dict of ``document_*`` keys ready to be merged into chunk
        metadata. Returns ``{}`` if docmeta is unavailable or the extraction
        fails for any reason.
    """
    if not _ensure_docmeta_on_path():
        return {}

    try:
        from docmeta.core import extract_metadata  # type: ignore
    except Exception as e:  # pragma: no cover
        logger.warning("docmeta import failed at call-time", error=str(e))
        return {}

    try:
        raw = extract_metadata(
            path,
            count_tokens_flag=count_tokens,
            extract_keywords_language=extract_keywords_language,
        )
    except Exception as e:
        # Most common causes: optional parser dep missing (PyMuPDF, openpyxl),
        # NLTK stopwords corpus not downloaded (handled gracefully inside
        # docmeta), or a corrupt file. None of these should break ingestion.
        logger.warning(
            "docmeta extract_metadata failed; falling back to parser-only metadata",
            error=str(e),
            path=path,
        )
        return {}

    if not isinstance(raw, dict):
        return {}

    enriched: dict[str, Any] = {}
    for key, value in raw.items():
        if key in _DROPPED_KEYS:
            continue
        if value is None:
            continue
        # Avoid indexing empty collections as useful metadata.
        if isinstance(value, (list, tuple, dict)) and not value:
            continue
        enriched[f"document_{key}"] = _normalise_value(value)

    return enriched


__all__ = ["extract_document_metadata"]
