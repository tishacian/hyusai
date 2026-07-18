"""Deterministic domain-anchor extraction for conversational retrieval.

Multi-turn follow-ups ("et pour cette machine ?") reach retrieval without the
entity established earlier in the conversation. These helpers extract the
salient domain anchors — project/machine references (ACO150, AKK200, BBA120)
and document names — from prior turns with plain regexes: zero latency, no
LLM, and the user's exact domain terms are preserved verbatim.

Used in two places:
- chat endpoint: precompute ``salient_entities`` when persisting a turn, so
  the next turn reads them without re-scanning history;
- rag context: fold the anchors into the retrieval query for referential
  follow-ups (see ``_history_augmented_query``).
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from app.services.rag.project_references import project_reference_terms

_DOCUMENT_RE = re.compile(
    r"\b[\w][\w\- ()]{0,60}\.(?:pdf|xlsx?|docx?|csv|pptx?)\b",
    re.IGNORECASE,
)

_MAX_TERMS_PER_KIND = 6

# Marker that ``_history_augmented_query`` uses to append retrieval-only anchor
# terms to a follow-up query. Kept here as the single source of truth so intent
# classification can strip the suffix back off (see ``strip_conversation_anchor``).
ANCHOR_PREFIX = "Previous user context:"


def strip_conversation_anchor(text: Any) -> str:
    """Drop the retrieval-only anchor suffix folded into a follow-up query.

    Anchor terms (project/machine codes and document filenames) are appended to
    the retrieval query to boost recall for anaphoric follow-ups. They must never
    influence *intent* classification: a document filename ending in ``.doc``
    would otherwise match the catalogue/inventory regex (``\\bdocs?\\b``) and
    misroute a plain content question to the synthetic collection-inventory
    pipeline. Classification therefore runs on the user portion only.
    """
    raw = str(text or "")
    idx = raw.find(ANCHOR_PREFIX)
    if idx == -1:
        return raw
    head = raw[:idx].rstrip()
    while head.endswith("|"):
        head = head[:-1].rstrip()
    return head


def extract_salient_entities(*texts: Any) -> dict[str, list[str]]:
    """Extract project/machine references and document names from texts."""
    references: list[str] = []
    documents: list[str] = []
    for raw in texts:
        text = str(raw or "")
        if not text:
            continue
        for term in project_reference_terms(text):
            if term not in references:
                references.append(term)
        for match in _DOCUMENT_RE.finditer(text):
            term = match.group(0).strip()
            if term not in documents:
                documents.append(term)
    return {
        "references": references[:_MAX_TERMS_PER_KIND],
        "documents": documents[:_MAX_TERMS_PER_KIND],
    }


def anchor_terms(entities: Mapping[str, Any] | None, *, limit: int = 2) -> list[str]:
    """Flatten salient entities into at most ``limit`` retrieval anchor terms.

    References (project/machine codes) carry the most retrieval signal and
    come first; a document name is only added if a slot remains.
    """
    if not isinstance(entities, Mapping):
        return []
    terms: list[str] = []
    for key in ("references", "documents"):
        values = entities.get(key)
        if not isinstance(values, list):
            continue
        for value in values:
            term = str(value or "").strip()
            if term and term not in terms:
                terms.append(term)
            if len(terms) >= limit:
                return terms
    return terms


def has_reference(text: str) -> bool:
    """Whether the text already carries its own project/machine reference."""
    return bool(project_reference_terms(str(text or "")))
