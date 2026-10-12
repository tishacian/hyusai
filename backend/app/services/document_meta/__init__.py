"""Adapter over the vendored ``docmeta`` package (``document_meta/docmeta``).

Why this adapter exists
-----------------------
Before this module, chunk metadata stored in the vector DB was limited to
what the document parser surfaced (filename, chunk index, char offsets). That
was enough to retrieve text but not enough to answer "what is this document
about?" or to render human-readable citations in the chat UI.

The ``docmeta`` package handles PDF / Office / ODT / text / markup /
structured data / images and produces titles, authors, embedded + TF-IDF
keywords, token counts, page counts, etc. This module exposes it to the
backend through a single helper.

Design notes
------------
- ``docmeta`` is imported lazily on first use: its extractors pull optional
  parser deps, and a missing one must disable enrichment, not the import of
  this module.
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

from datetime import datetime
from typing import Any, Callable

from app.core.logging import get_logger

logger = get_logger(__name__)


_extract_metadata: Callable[..., Any] | None = None


def _docmeta_extract() -> Callable[..., Any] | None:
    """Return ``docmeta.core.extract_metadata``, or None if docmeta cannot load."""
    global _extract_metadata
    if _extract_metadata is None:
        try:
            from .docmeta import extractors  # noqa: F401 — triggers extension/MIME registration
            from .docmeta.core import extract_metadata
        except Exception as e:  # pragma: no cover — env-dependent
            logger.warning("docmeta import failed; metadata enrichment disabled", error=str(e))
            return None
        _extract_metadata = extract_metadata
        logger.info("docmeta ready")
    return _extract_metadata


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
    extract_metadata = _docmeta_extract()
    if extract_metadata is None:
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
