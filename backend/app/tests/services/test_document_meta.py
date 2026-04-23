"""Unit tests for ``app.services.document_meta``.

These guard against regressions in the adapter over the monorepo
``src/metadata_extraction/docmeta`` package. The adapter is the single entry
point used by ``DocumentService`` to enrich chunk metadata (title, keywords,
token count) so the chat UI can render real citations instead of the legacy
"Policy chunk N" placeholder.

We deliberately exercise markdown + plain-text paths only here: PDF/Office
parsers need native deps that may not be present on every dev box. The richer
end-to-end coverage lives in ``test_rag_service.py`` (full ingestion).
"""
from __future__ import annotations

import os
import tempfile

import pytest

from app.services.document_meta import extract_document_metadata


@pytest.fixture
def sample_markdown() -> str:
    """Write a non-trivial markdown sample and return its absolute path.

    The file must live inside a tmpdir with a *real* filename because the
    docmeta text extractor uses the path's extension to pick the right
    subroutine. Using ``NamedTemporaryFile`` directly would yield a name like
    ``tmpXXXXXX.md`` which is fine for extension routing but defeats the
    purpose of the adapter (preserving the original filename in metadata).
    """
    body = (
        "# Slides Admin Cockpit\n\n"
        "Vue d'ensemble de la cockpit administration OmniRAG.\n\n"
        "## Utilisateurs\n- Alice (admin)\n- Bob (editor)\n\n"
        "## Workspaces\nEach tenant is isolated with its own RAG presets.\n"
    )
    tmp_dir = tempfile.mkdtemp()
    path = os.path.join(tmp_dir, "slides_admin_cockpit.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(body)
    yield path
    try:
        os.unlink(path)
        os.rmdir(tmp_dir)
    except OSError:
        pass


def test_extract_document_metadata_markdown_happy_path(sample_markdown: str) -> None:
    enriched = extract_document_metadata(
        sample_markdown, extract_keywords_language="english"
    )

    # When docmeta + its optional deps are installed we expect rich output.
    # If the dev environment lacks tiktoken/nltk/..., the adapter returns {}
    # — we still want the adapter itself to not raise in that case.
    if not enriched:
        pytest.skip("docmeta optional deps not available in this environment")

    # Every returned key is prefixed so it can be merged into chunk metadata
    # without colliding with parser-supplied fields (``document_id``,
    # ``document_filename``, ``document_type``).
    assert all(k.startswith("document_") for k in enriched), (
        f"Unexpected unprefixed key in {list(enriched.keys())}"
    )

    # The text extractor should always give us basic counts.
    assert enriched["document_word_count"] > 0
    assert enriched["document_line_count"] > 0

    # Token count is opt-in via the adapter's default; we pass
    # ``count_tokens=True`` implicitly so it must be present.
    assert "document_token_count" in enriched
    assert isinstance(enriched["document_token_count"], int)
    assert enriched["document_token_count"] > 0

    # Dropped fields (filesystem-only noise) must not leak through.
    for dropped in ("file_path", "file_permissions", "size", "mime_type"):
        assert f"document_{dropped}" not in enriched


def test_extract_document_metadata_missing_file_returns_empty() -> None:
    # The adapter must never raise on a bad path — callers rely on an empty
    # dict to mean "just skip enrichment".
    result = extract_document_metadata("/nonexistent/path/to/file.md")
    assert result == {}


def test_extract_document_metadata_disables_keywords() -> None:
    body = "# Short\n\nOne small paragraph.\n"
    tmp_dir = tempfile.mkdtemp()
    path = os.path.join(tmp_dir, "short.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(body)
    try:
        enriched = extract_document_metadata(path, extract_keywords_language=None)
        if not enriched:
            pytest.skip("docmeta optional deps not available in this environment")
        assert "document_extracted_keywords" not in enriched
    finally:
        os.unlink(path)
        os.rmdir(tmp_dir)
