"""Deterministic domain-anchor extraction for conversational retrieval.

Multi-turn follow-ups ("et pour cette machine ?") reach retrieval without the
entity established earlier in the conversation. These helpers extract the
salient domain anchors — project/machine references (ACO150, AKK200, BBA120)
and document names — from prior turns with plain regexes: zero latency, no
LLM, and the user's exact domain terms are preserved verbatim.

Used in three places:
- chat endpoint: precompute ``salient_entities`` when persisting a turn, so
  the next turn reads them without re-scanning history;
- rag context: fold the anchors into the retrieval query for referential
  follow-ups (see ``_history_augmented_query``);
- corpus planner: reuse the line-position grammar and offer the documents an
  earlier turn already answered from as extra scope candidates.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from app.services.rag.project_references import project_reference_terms
from app.services.rag.retrieval_policy import RetrievalPolicy
from app.services.rag.source_facets import score_source_family_match

_DOCUMENT_RE = re.compile(
    r"\b[\w][\w\- ()]{0,60}\.(?:pdf|xlsx?|docx?|csv|pptx?)\b",
    re.IGNORECASE,
)

# A line position ("J1", "C1", "C3", "J2S") names a station on the production
# line. It is a sibling grammar to ``LEGACY_PROJECT_REFERENCE_RE`` and never a
# project code (that one needs three letters and 2-4 digits), yet it is what a
# station question turns on: "la toile du convoyeur J1" and "la distance entre
# le C1 et le J1" are about different machines of the same family. The
# alphanumeric look-around is the important boundary — it keeps drawing, part
# and machine numbers out (``TTN16697J``, ``KD724-G``, ``2310PW``, ``AVA100``).
LINE_POSITION_RE = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]{1,2}\d{1,2}[A-Za-z]?(?![A-Za-z0-9])")

# Anchoring a document from a turn that answered "je n'ai pas trouvé" pins the
# next turn to the scope that already failed. Absence wording is therefore a
# veto on the document anchors only; the references and positions the user
# typed stay valid.
_ANSWER_ABSENCE_RE = re.compile(
    r"(?:"
    r"n(?:e\s+figure|'appara[iî]t|e\s+contient|'est\s+pas\s+(?:pr[ée]cis|mentionn|indiqu|disponible))|"
    r"(?:je\s+n'ai|nous\s+n'avons)\s+pas\s+(?:trouv|de\s|d')|"
    r"aucun[e]?\s+(?:document|source|information|donn[ée]e|r[ée]sultat|extrait)|"
    r"pas\s+(?:d'information|de\s+r[ée]ponse|de\s+source|de\s+document)|"
    r"corpus\s+trop\s+dense|"
    r"(?:could\s+not|couldn't|did\s+not|didn't)\s+find|"
    r"no\s+(?:relevant\s+)?(?:document|source|information|result)|"
    r"not\s+(?:found|available|specified|mentioned)"
    r")",
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


def line_position_terms(text: Any) -> tuple[str, ...]:
    """Uppercased line positions carried by a query, an answer or a file path."""
    positions: list[str] = []
    for match in LINE_POSITION_RE.finditer(str(text or "")):
        term = match.group(0).upper()
        if term not in positions:
            positions.append(term)
    return tuple(positions)


def reports_absence(text: Any) -> bool:
    """Whether a turn said it could not answer from the corpus."""
    return bool(_ANSWER_ABSENCE_RE.search(str(text or "")))


def extract_salient_entities(
    *texts: Any,
    scheme: str | None = None,
) -> dict[str, list[str]]:
    """Extract project/machine references, line positions and document names.

    ``documents`` are dropped when one of the texts reports an absence: they
    describe the scope the turn already searched without finding an answer, and
    re-anchoring a failed scope is how a session stays locked on the wrong
    machine family.  Project/machine codes follow the active project-reference
    scheme (Andritz only); line positions stay a sibling grammar.
    """
    references: list[str] = []
    positions: list[str] = []
    documents: list[str] = []
    absent = False
    for raw in texts:
        text = str(raw or "")
        if not text:
            continue
        absent = absent or reports_absence(text)
        for term in project_reference_terms(text, scheme=scheme):
            if term not in references:
                references.append(term)
        for term in line_position_terms(text):
            if term not in positions:
                positions.append(term)
        for match in _DOCUMENT_RE.finditer(text):
            term = match.group(0).strip()
            if term not in documents:
                documents.append(term)
    return {
        "references": references[:_MAX_TERMS_PER_KIND],
        "positions": positions[:_MAX_TERMS_PER_KIND],
        "documents": [] if absent else documents[:_MAX_TERMS_PER_KIND],
    }


def session_document_anchors(
    entities: Mapping[str, Any] | None,
    *,
    query: str,
    policy: RetrievalPolicy | None = None,
    limit: int = 3,
) -> list[str]:
    """Documents an earlier turn answered from that still fit this question.

    A session that already produced the ISOJET conveyor notice for "la distance
    entre le C1 et le J1" must not be replanned from scratch into another
    machine's carding-servo folder. The earlier document is handed back to the
    planner as an extra candidate — never as an exclusive filter — when it
    shares the question's station (line position) or its source family
    (conveyor, spare parts list, ...). Documents from a turn that reported an
    absence never reach this point: ``extract_salient_entities`` drops them.
    """
    if not isinstance(entities, Mapping):
        return []
    documents = [
        str(value or "").strip()
        for value in (entities.get("documents") or [])
        if str(value or "").strip()
    ]
    if not documents:
        return []
    query_positions = set(line_position_terms(query))
    session_positions = {str(value or "").upper() for value in (entities.get("positions") or [])}
    same_station = bool(query_positions & session_positions)
    anchored: list[str] = []
    for name in documents:
        family_score, _matched = score_source_family_match(
            query=query,
            row_text=name,
            policy=policy,
        )
        if not (
            family_score or same_station or query_positions & set(line_position_terms(name))
        ):
            continue
        if name not in anchored:
            anchored.append(name)
        if len(anchored) >= limit:
            break
    return anchored


def anchor_terms(entities: Mapping[str, Any] | None, *, limit: int = 2) -> list[str]:
    """Flatten salient entities into at most ``limit`` retrieval anchor terms.

    References (project/machine codes) carry the most retrieval signal and come
    first, then the line position that identifies the station being discussed;
    a document name is only added if a slot remains.
    """
    if not isinstance(entities, Mapping):
        return []
    terms: list[str] = []
    for key in ("references", "positions", "documents"):
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


def has_reference(text: str, *, scheme: str | None = None) -> bool:
    """Whether the text already carries its own project/machine reference."""
    return bool(project_reference_terms(str(text or ""), scheme=scheme))
