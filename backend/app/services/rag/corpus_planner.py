"""Corpus planning for dense Knowledge collections.

The planner is deliberately lightweight and deterministic. It turns the user's
plain question into an internal retrieval scope without asking the user to pick
filters first.
"""
from __future__ import annotations

import re
import time
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping

from sqlalchemy import case, or_
from sqlalchemy.orm import Session as DBSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models.knowledge_collection import KnowledgeCollection, KnowledgeCollectionSource
from app.models.knowledge_document_fact import KnowledgeDocumentFact
from app.services.knowledge_collections import collection_source_rows
from app.services.rag.conversation_anchors import (
    LINE_POSITION_RE,
    line_position_terms,
    session_document_anchors,
    strip_conversation_anchor,
)
from app.services.rag.project_references import (
    extract_query_project_codes,
    numeric_project_candidates,
    project_reference_terms,
)
from app.services.rag.retrieval_policy import RetrievalPolicy
from app.services.rag.source_facets import expanded_terms_for_query, score_source_family_match
from app.services.rag.summary_artifacts import load_summary_index_records

logger = get_logger(__name__)


LatencyProfile = str

_CATALOGUE_PHRASE_RE = re.compile(
    r"(?:de\s+quelles?\s+donn[ée]es?|quelles?\s+donn[ée]es?|what\s+data|available\s+data)",
    re.IGNORECASE,
)
_CATALOGUE_OBJECT_RE = re.compile(
    r"\b(?:data|donn[ée]es?|docs?|documents?|sources?|fichiers?|files?|collections?)\b",
    re.IGNORECASE,
)
_CATALOGUE_CARDINALITY_RE = re.compile(
    r"\b(?:combien(?:\s+de)?|nombre(?:\s+de)?|count(?:\s+of)?|how\s+many)\b"
    r"(?:[\s\W]+[\wÀ-ÿ-]+){0,4}?[\s\W]+"
    r"(?:data|donn[ée]es?|docs?|documents?|sources?|fichiers?|files?|collections?)\b",
    re.IGNORECASE,
)
_CATALOGUE_LIST_RE = re.compile(
    r"\b(?:liste(?:r)?|list)\b"
    r"(?:[\s\W]+[\wÀ-ÿ-]+){0,4}?[\s\W]+"
    r"(?:data|donn[ée]es?|docs?|documents?|sources?|fichiers?|files?|collections?)\b",
    re.IGNORECASE,
)
_PROJECT_SUMMARY_REQUEST_RE = re.compile(
    r"\b(?:"
    r"r[eé]sum(?:e(?:s|z)?|er|[eé](?:e|es|s)?)|"
    r"synth[eè]se|synth[ée]tis(?:e|er|es|ez)|"
    r"summary|summari[sz](?:e|ing)|aper[cç]u|overview"
    r")\b",
    re.IGNORECASE,
)
_EXPLICIT_CATALOGUE_REQUEST_RE = re.compile(
    r"\b(?:catalogue|inventaire|inventory|combien|nombre|count|how\s+many|"
    r"types?|formats?|extensions?)\b",
    re.IGNORECASE,
)
_COMPARE_RE = re.compile(r"\b(compare|comparer|diff[ée]rences?|versus|vs\.?)\b", re.IGNORECASE)
_PROCEDURE_RE = re.compile(
    r"\b(proc[ée]dure|procedure|mode\s+op[ée]ratoire|instruction|manuel|manual|"
    r"warning|caution|safety|s[ée]curit[ée])\b",
    re.IGNORECASE,
)
_AUDIT_RE = re.compile(
    r"\b(audit|diagnostic|qualit[ée]|coverage|couverture|clusters?)\b", re.IGNORECASE
)
_CONTENT_SEARCH_HINT_RE = re.compile(
    r"\b(parle(?:nt)?|about|sur|contien(?:t|nent)|mentionn(?:e|ent)|trait(?:e|ent)|concerne|couvre|covers?)\b",
    re.IGNORECASE,
)
_SOURCE_LOOKUP_HINT_RE = re.compile(
    r"\b(retrouve(?:r)?|retrouver|find|locate|source|document|fichier|file|manual|manuel|notice|couvre|covers?)\b",
    re.IGNORECASE,
)
_DOCUMENT_DISCOVERY_RE = re.compile(
    r"\bquels?\s+documents?\b.*\b(?:parle(?:nt)?|pour|sur|concerne|concernent|de\s+[a-z0-9_-]{3,})\b",
    re.IGNORECASE,
)
_TABLE_VALUE_LOOKUP_RE = re.compile(
    r"\b(que\s+vaut|valeur|value|label|table|feuille|sheet|cellule|cell|ligne|row|colonne|column)\b",
    re.IGNORECASE,
)
_EXTENSION_ALIASES = {
    "pdf": ("pdf",),
    "excel": ("spreadsheet", "xlsx", "xls", "xlsm"),
    "xlsx": ("xlsx",),
    "xls": ("xls",),
    "html": ("html", "htm"),
    "image": ("image", "jpg", "jpeg", "png"),
    "jpg": ("jpg", "jpeg"),
    "docx": ("docx",),
    "word": ("docx",),
    "csv": ("csv",),
}
_SOURCE_KIND_ALIASES = {
    "pdf": "pdf",
    "excel": "spreadsheet",
    "xlsx": "spreadsheet",
    "xls": "spreadsheet",
    "tableur": "spreadsheet",
    "spreadsheet": "spreadsheet",
    "html": "markup",
    "htm": "markup",
    "xml": "markup",
    "markup": "markup",
    "image": "image",
    "jpg": "image",
    "jpeg": "image",
    "png": "image",
    "docx": "document",
    "word": "document",
}
_TERM_RE = re.compile(r"[a-z0-9àâçéèêëîïôûùüÿñæœ_-]{3,}", re.IGNORECASE)
_QUERY_STOPWORDS = {
    "about",
    "avec",
    "dans",
    "des",
    "does",
    "donne",
    "explain",
    "explique",
    "for",
    "from",
    "how",
    "les",
    "manual",
    "manuel",
    "procedure",
    "procédure",
    "quels",
    "quoi",
    "source",
    "sur",
    "the",
    "une",
    "what",
}


@dataclass
class CorpusPlan:
    intent: str
    dense: bool
    source_count: int
    chunk_count: int
    latency_profile: LatencyProfile
    deadline_seconds: float
    top_k: int
    candidate_pool_k: int
    synthesis_k: int
    source_display_k: int
    retrieval_scope: dict[str, Any] = field(default_factory=dict)
    retrieval_plan: dict[str, Any] = field(default_factory=dict)
    filters: dict[str, Any] = field(default_factory=dict)
    scope_confidence: float = 0.0
    scope_reason: str = "No corpus scope inferred."
    dense_policy: str = "standard"
    use_hybrid: bool | None = None
    allow_hah_chah: bool = True
    allow_legacy_hybrid: bool = True
    max_variants: int = 3
    max_candidates: int = 80
    fallback_reason: str | None = None
    deep_retrieval_recommended: bool = False
    # Additive ("soft boost") document scope. Unlike ``filters`` this never
    # restricts the main query: retrieval runs the unscoped path AND, in
    # addition, a scope-searched pass over these documents, then unions the
    # results. Used for balanced fact-scope on large ledger-backed collections,
    # where a hard document_filename filter would starve answers living in
    # unstructured chunks the fact ledger never lifted, but the large collection
    # still needs *some* scope to be touched at all (guardrailed against unscoped
    # global search) so fact-backed answers that only live there are retrieved.
    soft_scope_filters: dict[str, Any] = field(default_factory=dict)
    soft_scope_reason: str = ""
    # Scope collections that retrieval should search with ``soft_scope_filters``
    # (the large ledger-backed ones) instead of an unscoped global chunk search
    # that is too slow/low-value on them. Small collections in the scope keep the
    # unscoped pass; the per-collection results are unioned.
    soft_scope_collections: list[str] = field(default_factory=list)
    # Recall floor (additive, strictly gated). When a HARD ``document_filename``
    # allowlist was emitted by the ledger scope on a LARGE collection, the
    # filename-keyword targeting can miss an answer document whose name lacks the
    # query's surface terms; the hard filter then excludes that answer chunk
    # before retrieval ever runs. To keep the hard scope's precision while
    # restoring recall, retrieval ALSO runs a bounded UNSCOPED dense pass
    # (``recall_floor_top_n`` results) over the SAME large collection(s) and
    # unions it into the candidate pool before rerank. Purely additive; a no-op
    # unless a hard document_filename filter is in effect on a large collection.
    # Cross-project contamination is removed downstream by the
    # require_project_code_match policy filter.
    recall_floor_collections: list[str] = field(default_factory=list)
    recall_floor_top_n: int = 0
    recall_floor_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize_latency_profile(value: Any, *, deep_retrieval: Any = None) -> LatencyProfile:
    if bool(deep_retrieval):
        return "deep"
    parsed = str(value or "").strip().lower()
    if parsed in {"oracle_fast", "oracle-fast", "oracle"}:
        return "fast"
    if parsed in {"chat"}:
        return "balanced"
    if parsed in {"deep_async", "deep-async"}:
        return "deep"
    if parsed in {"deep", "balanced", "fast"}:
        return parsed
    return "fast"


def is_catalogue_query(query: str) -> bool:
    text = strip_conversation_anchor(query).strip()
    if not text:
        return False
    if _is_scoped_project_summary_query(text):
        return False
    if re.search(
        r"\b(?:quel|quelle|which|what)\b.*\b(?:source|document|fichier|file)\b.*\b(?:contient|contains?)\b",
        text,
        re.IGNORECASE,
    ):
        return False
    if _CATALOGUE_PHRASE_RE.search(text):
        return True
    if re.search(r"\b(?:catalogue|inventaire|inventory)\b", text, re.IGNORECASE):
        return True
    if _CATALOGUE_CARDINALITY_RE.search(text):
        return True
    if _CATALOGUE_LIST_RE.search(text):
        return True
    if re.search(r"\b(?:types?|formats?|extensions?)\b", text, re.IGNORECASE):
        return bool(_CATALOGUE_OBJECT_RE.search(text))
    if re.search(
        r"\b(?:disposes?-?tu|as[-\s]?tu|available)\b", text, re.IGNORECASE
    ):
        return bool(_CATALOGUE_OBJECT_RE.search(text))
    return False


def classify_intent(query: str) -> str:
    text = strip_conversation_anchor(query)
    # Citation/source wording is answer-shaping context for a scoped project
    # summary, not a request to enumerate the corpus.  Resolve this strong
    # grammar before the generic document/source and catalogue branches.
    if _is_scoped_project_summary_query(text):
        return "content_search"
    if _DOCUMENT_DISCOVERY_RE.search(text) or (
        re.search(r"\b(?:quels?|which|what)\b", text, re.IGNORECASE)
        and _CONTENT_SEARCH_HINT_RE.search(text)
    ):
        return "content_search"
    if _TABLE_VALUE_LOOKUP_RE.search(text) and not re.search(
        r"\b(combien|nombre|count|how\s+many|types?|formats?|extensions?)\b",
        text,
        re.IGNORECASE,
    ):
        return "content_search"
    if (
        re.search(r"\b(?:quel|quelle|which|what|peux[-\s]?tu|can\s+you)\b", text, re.IGNORECASE)
        and _SOURCE_LOOKUP_HINT_RE.search(text)
        and not re.search(
            r"\b(combien|nombre|count|how\s+many|types?|formats?|extensions?)\b",
            text,
            re.IGNORECASE,
        )
    ):
        return "source_lookup"
    if is_catalogue_query(text):
        return "catalogue"
    if _AUDIT_RE.search(text):
        return "deep_audit"
    if _COMPARE_RE.search(text):
        return "compare"
    if _PROCEDURE_RE.search(text):
        return "procedure"
    if re.search(r"\b(source|document|fichier|file|manual|manuel)\b", text, re.IGNORECASE):
        return "source_lookup"
    return "content_search"


def _is_scoped_project_summary_query(query: str) -> bool:
    """Return whether a project summary outranks incidental source wording.

    ``documents``/``sources`` alone are deliberately broad catalogue hints.
    When a real SPL or Needlepunch project reference is paired with an explicit
    summary action, those nouns usually ask for citations (for example
    ``résume le projet 61035 en citant les documents``).  Explicit inventory,
    catalogue or cardinality wording remains authoritative and is not
    overridden here.
    """

    text = str(query or "").strip()
    if not text or not _PROJECT_SUMMARY_REQUEST_RE.search(text):
        return False
    if _EXPLICIT_CATALOGUE_REQUEST_RE.search(text) or _CATALOGUE_PHRASE_RE.search(text):
        return False
    return bool(extract_query_project_codes(text))


def _clean_filter_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        return value or None
    if isinstance(value, (list, tuple, set)):
        out = []
        for item in value:
            cleaned = _clean_filter_value(item)
            if cleaned is not None and cleaned not in out:
                out.append(cleaned)
        return out or None
    return value


def _request_filters(request: Mapping[str, Any] | None) -> dict[str, Any]:
    raw = request.get("retrieval_filters") if isinstance(request, Mapping) else None
    if not isinstance(raw, Mapping):
        return {}
    allowed = {
        "collection",
        "collection_slug",
        "document_id",
        "document_filename",
        "source_kind",
        "extension",
        "status",
        "project_code",
        "archive_name",
        "language",
    }
    out: dict[str, Any] = {}
    for key in allowed:
        value = _clean_filter_value(raw.get(key))
        if value is not None:
            out[key] = value
    return out


# Above these per-collection sizes, loading and Python-scanning the full source
# ledger on the interactive chat path costs tens of seconds. Such collections
# use bounded DB-side candidate targeting instead (see _rows_for_collections).
_LEDGER_TARGETING_MIN_SOURCES = 5000
_LEDGER_TARGETING_MIN_CHUNKS = 50000

# A query term that already matches more than this many facts in the scoped
# collection carries no document-scoping signal (e.g. "machine" on an industrial
# corpus matches ~13% of all facts). Such terms are dropped from the candidate
# gate in _infer_fact_document_scope: keeping them both crowds out the specific
# multi-term fact and makes the trigram index unselective (the planner falls back
# to a full sequential scan). Detection is a bounded, index-friendly count that
# stops at the threshold, so it stays cheap even for the common term itself.
_FACT_SCOPE_COMMON_TERM_MAX = 15000


_SOURCE_LOOKUP_GENERIC_TERMS = {
    "carrier",
    "comment",
    "document",
    "fichier",
    "manual",
    "manuel",
    "notice",
    "operation",
    "operator",
    "operatormanual",
    "parts",
    "projet",
    "retrouver",
    "source",
    "spare",
}


def _source_lookup_terms(project_codes: list[str], source_lookup_query: str | None) -> set[str]:
    """Bounded ILIKE/substring lookup terms shared by the SQL source targeting
    and the document_names targeting. Keeping them identical guarantees the two
    candidate paths surface the same docs regardless of which ledger holds them.
    """
    lookup_terms: set[str] = set()
    query_numeric_candidates = set(numeric_project_candidates(source_lookup_query or ""))
    for code in project_codes[:4]:
        compact = _compact_text(code).upper()
        variants = {code, compact}
        split = re.match(r"^([A-Z]+)(\d[A-Z0-9]*)$", compact)
        if split:
            prefix, suffix = split.groups()
            variants.update({f"{prefix} {suffix}", f"{prefix}-{suffix}", f"{prefix}_{suffix}"})
        lookup_terms.update(variant for variant in variants if variant)
    for term in _expanded_query_terms(source_lookup_query or "")[:20]:
        compact_term = _compact_text(term)
        # Five-digit project candidates are also useful filename anchors, but a
        # measurement such as ``10000 rpm`` must not become an ILIKE
        # ``%10000%`` source lookup: that substring is ubiquitous inside long
        # industrial part/drawing numbers.  Reuse the shared measurement-safe
        # numeric candidate grammar while leaving the explicit ``project_codes``
        # injected above untouched.
        if (
            compact_term.isdigit()
            and len(compact_term) == 5
            and compact_term not in query_numeric_candidates
        ):
            continue
        # A line position is shorter than the >=5 filename signal below, but it
        # is the only token that separates the J1 documents from every other
        # conveyor document of the deposit, so it targets on its own.
        if LINE_POSITION_RE.fullmatch(compact_term):
            lookup_terms.add(compact_term)
            continue
        # >=5 mirrors the strong filename signal in _infer_ledger_document_scope
        # (len(compact_term) >= 5 in source_only_compact). This keeps the DB
        # candidate set aligned with what the Python scorer would have matched.
        if len(compact_term) >= 5 and compact_term not in _SOURCE_LOOKUP_GENERIC_TERMS:
            lookup_terms.add(term)
            lookup_terms.add(compact_term)
    return lookup_terms


def _targeted_collection_source_rows(
    db: DBSession,
    *,
    collection: KnowledgeCollection,
    project_codes: list[str],
    source_lookup_query: str | None = None,
    limit: int = 200,
) -> list[Any]:
    cap = max(1, int(limit))
    code_terms = _source_lookup_terms(project_codes, None)
    content_terms = _source_lookup_terms(project_codes, source_lookup_query) - code_terms

    def _run(
        terms: set[str],
        *,
        exact_project_codes: list[str] | None = None,
    ) -> list[Any]:
        clauses: list[Any] = []
        for lookup_term in terms:
            like = f"%{lookup_term}%"
            clauses.extend(
                [
                    KnowledgeCollectionSource.filename.ilike(like),
                    KnowledgeCollectionSource.normalized_name.ilike(like),
                ]
            )
        if exact_project_codes:
            clauses.append(
                KnowledgeCollectionSource.source_metadata["project_code"]
                .as_string()
                .in_(exact_project_codes)
            )
        if not clauses:
            return []
        return (
            db.query(KnowledgeCollectionSource)
            .filter(
                KnowledgeCollectionSource.collection_id == collection.id,
                KnowledgeCollectionSource.status != "deleted",
                or_(*clauses),
            )
            .order_by(KnowledgeCollectionSource.filename.asc())
            .limit(cap)
            .all()
        )

    # Fetch project-code rows on their own budget. A single combined OR with a
    # filename-ordered LIMIT lets a common content term ("machine", "transfert")
    # fill every slot with non-project rows that sort earlier alphabetically,
    # silently dropping the project's own documents and collapsing the inferred
    # scope to the dense guardrail. Querying the code separately guarantees the
    # project documents always reach the candidate set.
    code_rows = _run(code_terms, exact_project_codes=project_codes)
    if not content_terms:
        return code_rows
    merged = list(code_rows)
    seen = {row.id for row in merged}
    for row in _run(content_terms):
        if row.id in seen:
            continue
        merged.append(row)
        seen.add(row.id)
    return merged


def _targeted_document_name_rows(
    collection: KnowledgeCollection,
    *,
    project_codes: list[str],
    source_lookup_query: str | None,
    existing_rows: list[Any],
    limit: int = 200,
) -> list[Any]:
    """Bounded, term/code-targeted slice of collection.document_names.

    Large/ledger-backed collections hold documents that exist only in
    collection.document_names (and Qdrant) but never landed in
    knowledge_collection_sources — e.g. the Manual_BBA120 archive on the
    andritz SPL pilot. The bounded SQL targeting in
    _targeted_collection_source_rows cannot see those rows, so a project-scoped
    question ("resume le projet BBA120") would infer no scope and bail to the
    "trop dense" degraded reply. We restore that recall here without the full
    ~100k-row Python scan that caused the original latency bug: plain lowercased
    substring matching against the same lookup terms, capped at ``limit``.
    """
    names = [
        str(name or "").strip()
        for name in (collection.document_names or [])
        if str(name or "").strip()
    ]
    if not names:
        return []
    code_lowered = {term.lower() for term in _source_lookup_terms(project_codes, None) if term}
    lowered_terms = {
        term.lower() for term in _source_lookup_terms(project_codes, source_lookup_query) if term
    }
    if not lowered_terms:
        return []
    # Scan project-code matches first so a common content term cannot fill the
    # cap with non-project names and drop the project's own documents (mirrors
    # the separate-budget targeting in _targeted_collection_source_rows). Stable
    # sort preserves original order within each group.
    if code_lowered:
        names.sort(key=lambda n: 0 if any(term in n.lower() for term in code_lowered) else 1)
    existing = {
        _search_text(getattr(row, "filename", "") or getattr(row, "normalized_name", "") or "")
        for row in existing_rows
    }
    out: list[Any] = []
    cap = max(1, int(limit))
    for index, filename in enumerate(names):
        normalized = " ".join(filename.split())
        name_lower = normalized.lower()
        if not any(term in name_lower for term in lowered_terms):
            continue
        key = _search_text(normalized)
        if key in existing:
            continue
        existing.add(key)
        ext = Path(normalized).suffix.lower().lstrip(".")
        out.append(
            SimpleNamespace(
                id=f"document-name-{collection.id}-{index}",
                workspace_id=collection.workspace_id,
                collection_id=collection.id,
                filename=normalized,
                normalized_name=normalized,
                source_kind=_source_kind_from_name(normalized),
                extension=ext,
                mime_type="",
                origin="legacy_document_names",
                size_bytes=None,
                chunk_count=0,
                status=collection.status or "ready",
                source_metadata={"fallback": True},
                updated_at=collection.updated_at,
                collection=collection,
            )
        )
        if len(out) >= cap:
            break
    return out


def _rows_for_collections(
    db: DBSession,
    collections: list[str],
    workspace_id: str | None,
    *,
    source_lookup_query: str | None = None,
) -> tuple[list[Any], list[KnowledgeCollection]]:
    rows: list[Any] = []
    collection_rows: list[KnowledgeCollection] = []
    project_codes = _query_project_codes(source_lookup_query or "") if source_lookup_query else []
    lookup_project_codes = list(
        dict.fromkeys(
            [
                *project_codes,
                *numeric_project_candidates(source_lookup_query or ""),
            ]
        )
    )
    for ref in collections:
        query = db.query(KnowledgeCollection).filter(
            (KnowledgeCollection.slug == ref) | (KnowledgeCollection.id == ref)
        )
        if workspace_id:
            query = query.filter(KnowledgeCollection.workspace_id == workspace_id)
        collection = query.first()
        if not collection:
            continue
        collection_rows.append(collection)
        # Only large collections take the bounded DB-targeting path. Small
        # collections keep the exact original behaviour (full row load + legacy
        # document_names fallback): scanning a few thousand rows in Python is
        # cheap, and preserving it avoids any retrieval-scope change where there
        # is no latency to win. project-code lookups always target (unchanged).
        large_collection = (
            int(getattr(collection, "document_count", 0) or 0) > _LEDGER_TARGETING_MIN_SOURCES
            or int(getattr(collection, "chunk_count", 0) or 0) > _LEDGER_TARGETING_MIN_CHUNKS
        )
        if source_lookup_query and (lookup_project_codes or large_collection):
            # Bounded DB-side targeting. We deliberately skip the *full* legacy
            # document_names rebuild here — on ledger-backed collections that
            # array can hold ~100k entries and rebuilding it wholesale in Python
            # would re-introduce the full-corpus scan we are avoiding.
            source_rows = _targeted_collection_source_rows(
                db,
                collection=collection,
                project_codes=lookup_project_codes,
                source_lookup_query=source_lookup_query,
            )
            for row in source_rows:
                try:
                    row.collection = collection
                except Exception:
                    pass
            rows.extend(source_rows)
            # But we MUST still consult document_names in a bounded, targeted
            # way: docs that exist only there (and in Qdrant) — never in
            # knowledge_collection_sources — would otherwise be invisible to the
            # interactive planner, making project-scoped questions bail to the
            # "trop dense" degraded reply (regression introduced when the legacy
            # rebuild was dropped here). This adds only term/code-matching names.
            name_rows = _targeted_document_name_rows(
                collection,
                project_codes=lookup_project_codes,
                source_lookup_query=source_lookup_query,
                existing_rows=source_rows,
            )
            rows.extend(name_rows)
        else:
            source_rows = collection_source_rows(db, collection=collection)
            for row in source_rows:
                try:
                    row.collection = collection
                except Exception:
                    pass
            rows.extend(source_rows)
            rows.extend(_missing_document_name_rows(collection, source_rows))
    return rows, collection_rows


def _source_kind_from_name(filename: str) -> str:
    ext = Path(filename).suffix.lower().lstrip(".")
    if ext == "pdf":
        return "pdf"
    if ext in {"html", "htm", "md", "txt", "xml"}:
        return "markup" if ext in {"html", "htm", "xml"} else "text"
    if ext in {"xlsx", "xls", "xlsm", "csv"}:
        return "spreadsheet"
    if ext in {"jpg", "jpeg", "png", "tif", "tiff"}:
        return "image"
    if ext in {"doc", "docx"}:
        return "document"
    return "document"


def _missing_document_name_rows(
    collection: KnowledgeCollection, existing_rows: list[Any]
) -> list[Any]:
    names = [
        str(name or "").strip()
        for name in (collection.document_names or [])
        if str(name or "").strip()
    ]
    if not names:
        return []
    existing = {
        _search_text(getattr(row, "filename", "") or getattr(row, "normalized_name", "") or "")
        for row in existing_rows
    }
    fallback: list[Any] = []
    for index, filename in enumerate(names):
        normalized = " ".join(filename.split())
        if _search_text(normalized) in existing:
            continue
        ext = Path(normalized).suffix.lower().lstrip(".")
        fallback.append(
            SimpleNamespace(
                id=f"document-name-{collection.id}-{index}",
                workspace_id=collection.workspace_id,
                collection_id=collection.id,
                filename=normalized,
                normalized_name=normalized,
                source_kind=_source_kind_from_name(normalized),
                extension=ext,
                mime_type="",
                origin="legacy_document_names",
                size_bytes=None,
                chunk_count=0,
                status=collection.status or "ready",
                source_metadata={"fallback": True},
                updated_at=collection.updated_at,
                collection=collection,
            )
        )
    return fallback


def _workspace_collections(db: DBSession, workspace_id: str | None) -> list[KnowledgeCollection]:
    if not workspace_id:
        return []
    return (
        db.query(KnowledgeCollection)
        .filter(KnowledgeCollection.workspace_id == workspace_id)
        .order_by(KnowledgeCollection.updated_at.desc())
        .all()
    )


def _deep_ledger_is_large(db: DBSession, collections: list[str], workspace_id: str | None) -> bool:
    """Cheap size probe used to bound the deep planner on large corpora.

    Deep historically loaded and Python-scanned the *full* source ledger to
    infer scope. On large ledger-backed collections (e.g. ~99k sources /
    ~1.49M chunks on andritz-notices-spl-pilot) that scan was measured at
    ~55-120s and dominates the deep deadline — broad/unscoped deep jobs then
    time out with 0 passages while the actual Qdrant retrieval is sub-second.
    When any targeted collection is large we route deep through the same
    bounded DB-side ILIKE targeting fast/balanced already use. Reads only the
    indexed size columns, never the source rows.
    """
    for ref in collections:
        query = db.query(
            KnowledgeCollection.document_count, KnowledgeCollection.chunk_count
        ).filter((KnowledgeCollection.slug == ref) | (KnowledgeCollection.id == ref))
        if workspace_id:
            query = query.filter(KnowledgeCollection.workspace_id == workspace_id)
        row = query.first()
        if not row:
            continue
        document_count = int(row[0] or 0)
        chunk_count = int(row[1] or 0)
        if (
            document_count > _LEDGER_TARGETING_MIN_SOURCES
            or chunk_count > _LEDGER_TARGETING_MIN_CHUNKS
        ):
            return True
    return False


def _collection_source_count(db: DBSession, collection: KnowledgeCollection) -> int:
    try:
        return int(
            db.query(KnowledgeCollectionSource)
            .filter(
                KnowledgeCollectionSource.collection_id == collection.id,
                KnowledgeCollectionSource.status != "deleted",
            )
            .count()
            or 0
        )
    except Exception:  # pragma: no cover - count is advisory for planning only.
        return 0


def _corpus_version(rows: list[Any], collection_rows: list[KnowledgeCollection]) -> str:
    values: list[str] = []
    for row in collection_rows:
        updated_at = getattr(row, "updated_at", None)
        if updated_at is not None:
            values.append(str(updated_at))
    for row in rows:
        updated_at = getattr(row, "updated_at", None)
        if updated_at is not None:
            values.append(str(updated_at))
    return max(values) if values else "unknown"


def _source_metadata(row: Any) -> dict[str, Any]:
    value = getattr(row, "source_metadata", None)
    return dict(value or {}) if isinstance(value, Mapping) else {}


def _fold_text(value: Any) -> str:
    raw = str(value or "")
    folded = unicodedata.normalize("NFKD", raw).encode("ascii", "ignore").decode("ascii")
    return folded.lower()


def _search_text(value: Any) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", _fold_text(value)).split())


def _compact_text(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", _fold_text(value))


def _row_search_payload(row: Any) -> tuple[str, str]:
    meta = _source_metadata(row)
    values: list[str] = [
        getattr(row, "filename", "") or "",
        getattr(row, "normalized_name", "") or "",
        getattr(row, "source_kind", "") or "",
        getattr(row, "extension", "") or "",
        getattr(row, "mime_type", "") or "",
    ]
    collection = getattr(row, "collection", None)
    if collection is not None:
        values.extend(
            [
                getattr(collection, "slug", "") or "",
                getattr(collection, "name", "") or "",
                getattr(collection, "display_name", "") or "",
            ]
        )
    for key in (
        "document_id",
        "document_filename",
        "project_code",
        "project",
        "machine",
        "line",
        "archive_name",
        "source",
        "title",
        "language",
    ):
        value = meta.get(key)
        if isinstance(value, (str, int, float)):
            values.append(str(value))
    joined = " ".join(values)
    return _search_text(joined), _compact_text(joined)


def _row_collection_ref(row: Any) -> str | None:
    collection = getattr(row, "collection", None)
    if collection is None:
        return None
    ref = str(getattr(collection, "slug", "") or getattr(collection, "id", "") or "").strip()
    return ref or None


def _spreadsheet_collection_refs(rows: list[Any]) -> list[str]:
    refs: list[str] = []
    for row in rows:
        kind = str(getattr(row, "source_kind", "") or "").lower()
        ext = str(getattr(row, "extension", "") or "").lower().lstrip(".")
        filename = str(getattr(row, "filename", "") or "").lower()
        if (
            kind != "spreadsheet"
            and ext not in {"xlsx", "xls", "xlsm", "csv"}
            and not filename.endswith((".xlsx", ".xls", ".xlsm", ".csv"))
        ):
            continue
        ref = _row_collection_ref(row)
        if ref and ref not in refs:
            refs.append(ref)
    return refs


def _query_project_codes(
    query: str,
    *,
    known_codes: set[str] | list[str] | tuple[str, ...] | None = None,
) -> list[str]:
    return extract_query_project_codes(query, known_codes=known_codes)


def _is_broad_format_scope_query(query: str) -> bool:
    text = _search_text(query)
    if not re.search(r"\b(fichiers?|files?|documents?|sources?|docs?)\b", text):
        return False
    if not any(
        re.search(rf"\b{re.escape(token)}\b", text)
        for token in (*_EXTENSION_ALIASES, *_SOURCE_KIND_ALIASES)
    ):
        return False
    return not bool(
        _query_project_codes(query) or re.search(r"\b(retrouve(?:r)?|find|locate)\b", text)
    )


def _expanded_query_terms(query: str, policy: RetrievalPolicy | None = None) -> list[str]:
    text = _search_text(query)
    terms: list[str] = []

    # Line positions are two or three characters ("j1", "c1", "j2s") yet carry
    # the most selective signal of a station question, so they bypass the
    # generic short-token floor instead of being dropped as noise.
    def add(*values: str) -> None:
        for value in values:
            cleaned = _search_text(value)
            if (len(cleaned) >= 3 or LINE_POSITION_RE.fullmatch(cleaned)) and cleaned not in terms:
                terms.append(cleaned)

    for token in text.split():
        if (len(token) >= 3 or LINE_POSITION_RE.fullmatch(token)) and token not in _QUERY_STOPWORDS:
            add(token)
    add(*expanded_terms_for_query(query, policy))
    return terms[:40]


# Navigation/boilerplate documents (menus, picture frames, image/asset files)
# carry the project code in their path and therefore tie with real technical
# sections under the project-code bonus. They are never an answer source, so we
# demote them before the top-N cut to keep technical content in scope.
_DEMOTE_SOURCE_RE = re.compile(
    r"(?:^|__)(?:menu|pictures?|images?|img|frames?|css|js|assets?|fonts?)__"
    r"|\.(?:jpe?g|png|gif|bmp|ico|tiff?|svg|webp|css|js)(?:$|__)"
    r"|(?:^|__)(?:accueil|index|sommaire|home|menu|frames?|nexline-index)[-_ ]?[^_]*\.html?(?:$|__)",
    re.IGNORECASE,
)

# Above the project-code base (+12 for a filename code hit), only a strong
# filename-term match (+8) or an equipment-family match lifts a document. Below
# this, the documents are merely "this project's files in alphabetical order",
# so a filename allowlist drops deep content PDFs whose names don't advertise the
# answer (e.g. a German pump datasheet). In that case scope by project instead.
_PROJECT_SCOPE_STRONG_MATCH = 20.0


def _session_document_anchors(
    request: Mapping[str, Any] | None,
    *,
    query: str,
    policy: RetrievalPolicy | None,
) -> list[str]:
    """Documents this session already answered from, for the same station/family.

    The chat endpoints persist ``salient_entities`` on each assistant turn and
    replay them in ``context``; the planner reads them here so a follow-up is
    not replanned from scratch onto another machine's folder.
    """
    context = request.get("context") if isinstance(request, Mapping) else None
    entities = context.get("salient_entities") if isinstance(context, Mapping) else None
    return session_document_anchors(entities, query=query, policy=policy)


def _compact_anchor_documents(anchor_documents: list[str] | None) -> list[str]:
    """Compact forms of the session's anchor documents, long enough to match.

    Substring matching a short anchor would tag half the ledger, so anything
    below six characters is dropped rather than allowed to widen the scope.
    """
    compacted = [_compact_text(name) for name in (anchor_documents or [])]
    return [name for name in compacted if len(name) >= 6]


def _infer_ledger_document_scope(
    query: str,
    rows: list[Any],
    *,
    policy: RetrievalPolicy | None = None,
    anchor_documents: list[str] | None = None,
) -> tuple[dict[str, Any], float, str, list[str]]:
    if not rows:
        return {}, 0.0, "", []
    terms = _expanded_query_terms(query, policy)
    query_positions = set(line_position_terms(query))
    anchors = _compact_anchor_documents(anchor_documents)
    family_expanded_terms = {_search_text(term) for term in expanded_terms_for_query(query, policy)}
    project_codes = _query_project_codes(
        query,
        known_codes=_candidate_project_codes(rows),
    )
    if not project_codes and _is_broad_format_scope_query(query):
        return {}, 0.0, "", []
    compact_query = _compact_text(query)
    has_source_lookup_signal = bool(
        re.search(
            r"\b(spare|parts?|spl|document|docs?|fichier|source|manual|manuel|notice|pompe|pump|inject|strip|carrier|maintenance|convoyeur|conveyor|cabinet|pneumatic|pneumatique|table|feuille|sheet)\b",
            _search_text(query),
            re.IGNORECASE,
        )
    )
    if not terms and not project_codes:
        return {}, 0.0, "", []

    scored: list[tuple[float, bool, bool, bool, Any]] = []
    for row in rows:
        filename = str(getattr(row, "filename", "") or "")
        if not filename:
            continue
        haystack, compact_haystack = _row_search_payload(row)
        source_metadata = _source_metadata(row)
        source_only_text = " ".join(
            str(value or "")
            for value in (
                filename,
                getattr(row, "normalized_name", ""),
                getattr(row, "source_kind", ""),
                getattr(row, "extension", ""),
                getattr(row, "mime_type", ""),
                *source_metadata.values(),
            )
        )
        source_only_compact = _compact_text(source_only_text)
        score = 0.0
        matched_project = False
        strong_phrase_match = False
        strong_source_term_match = False
        # A filename that carries the station the question names is about *that*
        # machine, not merely about the same family of machines. Guarded so the
        # scan only runs for the questions that name a station.
        position_in_source = bool(
            query_positions and query_positions.intersection(line_position_terms(source_only_text))
        )
        if position_in_source:
            score += 3.0
        if anchors and any(anchor in source_only_compact for anchor in anchors):
            # A document an earlier turn already answered from stays a
            # candidate even when this turn's wording no longer matches its
            # filename. It is a bonus, never a phrase match: the anchor must
            # widen the scope, not become the new lock-in.
            score += 6.0
        metadata_project_code = _compact_text(source_metadata.get("project_code")).upper()
        for code in project_codes:
            # A Needlepunch numeric5 identifier is a project only when the
            # canonical source metadata says so. Filename substring matching
            # would otherwise turn unrelated references such as BID6100194
            # into a false project 61001 scope. Historical SPL identifiers keep
            # their established filename/ledger fallback.
            if code.isdigit() and len(code) == 5:
                if metadata_project_code == code:
                    matched_project = True
                    score += 12.0
                continue
            if code and code.lower() in source_only_compact:
                matched_project = True
                score += 12.0
            elif code and code.lower() in compact_haystack:
                matched_project = True
                score += 4.0
        if project_codes and not matched_project:
            # A project-qualified question should not be polluted by another
            # project unless the filename is an exceptionally strong phrase hit.
            score -= 4.0
        for term in terms:
            compact_term = _compact_text(term)
            if not compact_term or len(compact_term) < 3:
                continue
            if f" {term} " in f" {haystack} ":
                score += 2.2
            elif compact_term in compact_haystack:
                score += 1.5
            is_project_term = compact_term.upper() in project_codes
            is_family_term = _search_text(term) in family_expanded_terms
            if (
                len(compact_term) >= 5
                and compact_term in source_only_compact
                and not is_project_term
                and not is_family_term
            ):
                score += 8.0
                strong_source_term_match = True
        family_score, family_matches = score_source_family_match(
            query=query,
            row_text=source_only_text,
            metadata=source_metadata,
            policy=policy,
        )
        if family_score:
            score += family_score
            # A family hit ("conveyor", "spare parts") describes a KIND of
            # document, not this one: dozens of machines carry a conveyor
            # section. Alone it used to set strong_phrase_match, and the phrase
            # filter below then reduced the whole scope to one arbitrary family
            # document of an unrelated machine while the answer sat in another
            # line's spare-parts list. Require a second, document-specific
            # signal: the project the question named, the station it named, or
            # a long non-family term (part/drawing number) in the filename.
            if matched_project or position_in_source or strong_source_term_match:
                strong_phrase_match = True
        if compact_query and compact_query in compact_haystack:
            score += 4.0
            strong_phrase_match = True
        elif any(
            len(_compact_text(term)) >= 6
            and _compact_text(term).upper() not in project_codes
            and _search_text(term) not in family_expanded_terms
            and _compact_text(term) in compact_haystack
            for term in terms
        ):
            # Family words are excluded here for the same reason as above: a
            # long term only identifies a document when it is not the name of
            # the family every sibling document shares.
            strong_phrase_match = True
        if has_source_lookup_signal:
            score += min(max(int(getattr(row, "chunk_count", 0) or 0), 0), 100) / 200.0
        if _DEMOTE_SOURCE_RE.search(filename):
            score -= 10.0
            strong_phrase_match = False
        threshold = 6.0 if project_codes else 7.0
        if score >= threshold:
            scored.append((score, matched_project, strong_phrase_match, position_in_source, row))
    if not scored:
        return {}, 0.0, "", []
    if project_codes and any(item[1] for item in scored):
        scored = [item for item in scored if item[1]]
        phrase_scored = [item for item in scored if item[2]]
        if phrase_scored and max(item[0] for item in phrase_scored) >= max(
            item[0] for item in scored
        ):
            scored = phrase_scored
    elif project_codes:
        return {}, 0.0, f"No ledger source matched project/code {', '.join(project_codes[:3])}.", []
    else:
        phrase_scored = [item for item in scored if item[2]]
        if phrase_scored:
            scored = phrase_scored

    ranked = sorted(
        scored, key=lambda item: (-item[0], str(getattr(item[4], "filename", "") or "").lower())
    )[:20]
    filenames: list[str] = []
    collection_refs: list[str] = []
    for _, _matched_project, _strong_phrase_match, _position_in_source, row in ranked:
        filename = str(getattr(row, "filename", "") or "").strip()
        if filename and filename not in filenames:
            filenames.append(filename)
        collection_ref = _row_collection_ref(row)
        if collection_ref and collection_ref not in collection_refs:
            collection_refs.append(collection_ref)
    if not filenames:
        return {}, 0.0, "", []
    top_score = float(ranked[0][0])
    # Only emit a project_code filter for codes that are actually indexed as a
    # ``project_code`` payload value among the matched rows. A query identifier
    # that merely appears inside filenames (e.g. a sub-component code like
    # CU250S, whose documents carry parent-project codes such as
    # ACJ100/AKI300/AMM100) is never a project_code value, so the Qdrant
    # project_code filter would match zero chunks, collapse retrieval and trip
    # the exact-match guardrail. In that case fall through to the precise
    # document_filename allowlist below instead.
    indexed_project_codes = {
        _compact_text(_source_metadata(row).get("project_code")).upper()
        for *_unused, row in ranked
    }
    indexed_project_codes.discard("")
    scoped_codes = [code for code in project_codes if code in indexed_project_codes]
    broad_project_scope = bool(project_codes) and top_score < _PROJECT_SCOPE_STRONG_MATCH
    if broad_project_scope and scoped_codes:
        # Generic project question (no document scored clearly above the
        # project-code base): scope the dense search to the whole project so
        # ranking can surface content-bearing documents the filename allowlist
        # would otherwise drop.
        confidence = min(0.85, 0.62 + min(top_score, 16.0) / 40.0)
        reason = (
            f"project scope for {', '.join(scoped_codes[:3])} "
            f"({len(filenames)} filename candidates, top_score={top_score:.1f} below strong-match)"
        )
        return {"project_code": scoped_codes}, confidence, reason, collection_refs
    if query_positions and not any(item[3] for item in ranked):
        # The question names a station (J1, C1, J2S) and not one candidate
        # filename carries it: every candidate was selected on family or word
        # overlap alone. That is how "la référence de la toile du convoyeur J1"
        # locked onto the first conveyor section of an unrelated machine while
        # the belt reference sat in another line's spare-parts list — a hard
        # filename allowlist makes that answer unreachable before retrieval
        # runs. Keep the real project scope when the question named one, and
        # otherwise emit no scope: a bounded open search plus the queued deep
        # refinement beats a precise wrong scope.
        positions = ", ".join(sorted(query_positions)[:3])
        if scoped_codes:
            confidence = min(0.85, 0.62 + min(top_score, 16.0) / 40.0)
            reason = (
                f"project scope for {', '.join(scoped_codes[:3])}; no candidate filename "
                f"carries line position {positions}"
            )
            return {"project_code": scoped_codes}, confidence, reason, collection_refs
        reason = (
            f"no document scope: line position {positions} is absent from all "
            f"{len(filenames)} family/keyword candidate(s)"
        )
        return {}, 0.0, reason, []
    confidence = min(0.94, 0.66 + min(top_score, 12.0) / 35.0)
    reason = f"ledger source scope matched {len(filenames)} candidate document(s)"
    if project_codes:
        reason += f" for project/code {', '.join(project_codes[:3])}"
    return {"document_filename": filenames}, confidence, reason, collection_refs


def _candidate_project_codes(rows: list[Any]) -> set[str]:
    codes: set[str] = set()
    for row in rows:
        meta = _source_metadata(row)
        for key in ("project_code", "project", "machine", "line", "archive_name"):
            value = str(meta.get(key) or "").strip().upper()
            if key == "project_code" and value:
                codes.add(value)
            elif value:
                # Only the canonical ``project_code`` field is authoritative
                # for an otherwise bare numeric identifier.  Other metadata
                # fields may contain machine, part or archive numbers; they
                # retain legacy SPL discovery but cannot self-authorise a
                # Needlepunch numeric code.
                codes.update(project_reference_terms(value))
        codes.update(project_reference_terms(str(getattr(row, "filename", "") or "")))
    return codes


def _infer_filters(query: str, rows: list[Any]) -> tuple[dict[str, Any], float, str]:
    text = str(query or "")
    lower = text.lower()
    filters: dict[str, Any] = {}
    reasons: list[str] = []
    confidence = 0.0

    for token, extensions in _EXTENSION_ALIASES.items():
        if re.search(rf"\b{re.escape(token)}\b", lower):
            extension = extensions[0]
            if extension != "spreadsheet" and extension != "image":
                filters["extension"] = extension
                reasons.append(f"extension={extension}")
                confidence = max(confidence, 0.55)
            break

    for token, kind in _SOURCE_KIND_ALIASES.items():
        if re.search(rf"\b{re.escape(token)}\b", lower):
            filters["source_kind"] = kind
            reasons.append(f"source_kind={kind}")
            confidence = max(confidence, 0.60)
            break

    if re.search(r"\b(erreur|errors?|failed|failed sources?)\b", lower):
        filters["status"] = "error"
        reasons.append("status=error")
        confidence = max(confidence, 0.70)
    elif re.search(r"\b(index[ée]s?|ready|indexed|actifs?)\b", lower):
        filters["status"] = "ready"
        reasons.append("status=ready")
        confidence = max(confidence, 0.50)

    candidate_codes = _candidate_project_codes(rows)
    query_codes = _query_project_codes(text, known_codes=candidate_codes)
    matched_codes = [code for code in query_codes if code in candidate_codes]
    numeric_candidates = set(numeric_project_candidates(text))
    # Strong project grammar is authoritative for numeric5 even before that
    # project's first source has been indexed. Exact known numeric codes remain
    # covered by ``matched_codes``; document-like numbers (notice 12345), part
    # references and measurements never enter this source-independent set.
    strong_numeric_codes = [
        code for code in _query_project_codes(text) if code in numeric_candidates
    ]
    scoped_codes = list(dict.fromkeys([*matched_codes, *strong_numeric_codes]))
    if scoped_codes:
        filters["project_code"] = scoped_codes[0] if len(scoped_codes) == 1 else scoped_codes
        reasons.append(f"project_code={','.join(scoped_codes)}")
        confidence = max(confidence, 0.82)

    # If a source document is named very explicitly in the question, use its
    # document_id from the ledger. Keep the list small: Qdrant MatchAny should
    # select a candidate set, not carry the whole corpus.
    source_hits: list[str] = []
    words = {w for w in re.findall(r"[a-z0-9]{4,}", lower) if len(w) >= 4}
    query_project_codes = query_codes
    if words and (not query_project_codes or matched_codes):
        scored: list[tuple[int, Any]] = []
        for row in rows:
            filename = str(getattr(row, "filename", "") or "")
            stem_words = set(re.findall(r"[a-z0-9]{4,}", Path(filename).stem.lower()))
            overlap = len(words & stem_words)
            if overlap >= 2:
                scored.append((overlap, row))
        for _, row in sorted(scored, key=lambda item: item[0], reverse=True)[:20]:
            document_id = _source_metadata(row).get("document_id")
            if document_id and document_id not in source_hits:
                source_hits.append(str(document_id))
        if source_hits:
            filters["document_id"] = source_hits
            reasons.append(f"document_id_match={len(source_hits)}")
            confidence = max(confidence, 0.75)

    reason = (
        "; ".join(reasons)
        if reasons
        else "No strong metadata scope inferred; using bounded semantic retrieval."
    )
    return filters, confidence, reason


def _query_terms(query: str) -> list[str]:
    # Long word tokens (>=5) mirror the strong filename/source signal used
    # elsewhere (project codes and _source_lookup_terms both require len >= 5).
    # Short tokens that carry a digit are kept too: model numbers, sizes and part
    # codes ("1500", "ø1500"->"1500", "s35ppp") are the most selective signal for
    # measurement/parameter lookups, yet the blanket len>=5 rule used to drop them
    # and leave only common words ("poids", "machine") that cannot pinpoint a
    # document. _infer_fact_document_scope still demotes ubiquitous terms, so the
    # extra numeric tokens sharpen scope without flooding the candidate scan.
    terms: list[str] = []
    for raw in _TERM_RE.findall(str(query or "").lower()):
        token = raw.strip("_-")
        if token in _QUERY_STOPWORDS:
            continue
        if len(token) < 5 and not any(ch.isdigit() for ch in token):
            continue
        if token not in terms:
            terms.append(token)
    return terms[:8]


def _fact_text(fact: KnowledgeDocumentFact) -> str:
    return " ".join(
        str(value or "")
        for value in (
            fact.document_filename,
            fact.semantic_type,
            fact.subject,
            fact.predicate,
            fact.value_raw,
            fact.section_path,
            fact.content,
        )
    ).lower()


# Candidate gating ILIKEs the structured fact fields, not the free-text content
# column: the answer-bearing value for measurement/parameter facts lives in
# subject/value_raw, content is the main source of ubiquitous-term noise, and the
# trigram indexes back exactly these columns (migration 045).
_FACT_SCOPE_CANDIDATE_COLUMNS = (
    KnowledgeDocumentFact.subject,
    KnowledgeDocumentFact.value_raw,
    KnowledgeDocumentFact.section_path,
    KnowledgeDocumentFact.document_filename,
)


def _fact_term_predicates(term: str) -> list[Any]:
    like = f"%{term}%"
    return [column.ilike(like) for column in _FACT_SCOPE_CANDIDATE_COLUMNS]


def _infer_fact_document_scope(
    db: DBSession,
    *,
    collection_rows: list[KnowledgeCollection],
    query: str,
    intent: str,
) -> tuple[dict[str, Any], float, str]:
    terms = _query_terms(query)
    if not terms or not collection_rows:
        return {}, 0.0, ""
    collection_ids = [row.id for row in collection_rows if row.id]
    workspace_id = collection_rows[0].workspace_id if collection_rows else None
    if not collection_ids or not workspace_id:
        return {}, 0.0, ""

    base = db.query(KnowledgeDocumentFact).filter(
        KnowledgeDocumentFact.workspace_id == workspace_id,
        KnowledgeDocumentFact.collection_id.in_(collection_ids),
    )

    # Drop ubiquitous terms that cannot scope to a document. The bounded count
    # short-circuits at the threshold, so even the common term stays cheap.
    discriminating: list[str] = []
    for term in terms:
        hits = (
            base.filter(or_(*_fact_term_predicates(term)))
            .limit(_FACT_SCOPE_COMMON_TERM_MAX + 1)
            .count()
        )
        if 0 < hits <= _FACT_SCOPE_COMMON_TERM_MAX:
            discriminating.append(term)
    if not discriminating:
        # Every term is either absent or ubiquitous: fall back to all present
        # terms so a single-rare-term query (e.g. one short code) still scopes.
        discriminating = terms

    predicates: list[Any] = []
    for term in discriminating:
        predicates.extend(_fact_term_predicates(term))

    # Rank candidates by how many DISTINCT discriminating terms each fact matches
    # (NULL-safe via CASE), not by raw confidence. The answer-bearing fact often
    # has only modest confidence and is otherwise evicted by the high-confidence
    # volume of a single common term (the Q7 crowd-out pattern); confidence only
    # breaks ties between equally specific facts.
    coverage = None
    for term in discriminating:
        piece = case((or_(*_fact_term_predicates(term)), 1), else_=0)
        coverage = piece if coverage is None else coverage + piece

    query_rows = (
        base.filter(or_(*predicates))
        .order_by(
            coverage.desc(),
            KnowledgeDocumentFact.confidence.desc(),
            KnowledgeDocumentFact.updated_at.desc(),
        )
        .limit(800)
        .all()
    )
    if not query_rows:
        return {}, 0.0, ""

    intent_bonus = {
        "procedure": ("procedure", "warning", "safety"),
        "compare": ("definition", "parameter", "procedure"),
        "deep_audit": ("procedure", "warning", "definition", "parameter"),
    }.get(intent, ())
    scored: dict[str, dict[str, Any]] = {}
    for fact in query_rows:
        filename = str(fact.document_filename or "").strip()
        document_id = str(fact.document_id or "").strip()
        key = filename or document_id
        if not key:
            continue
        haystack = _fact_text(fact)
        score = 0.0
        for term in discriminating:
            if term in haystack:
                score += 1.0
            if filename and term in filename.lower():
                score += 1.5
        if intent_bonus and any(
            token in str(fact.semantic_type or "").lower() for token in intent_bonus
        ):
            score += 1.25
        score += min(max(float(fact.confidence or 0.0), 0.0), 1.0) * 0.5
        if score < 1.5:
            continue
        bucket = scored.setdefault(
            key,
            {
                "score": 0.0,
                "filename": filename,
                "document_id": document_id,
                "facts": 0,
            },
        )
        bucket["score"] += score
        bucket["facts"] += 1
    if not scored:
        return {}, 0.0, ""

    ranked = sorted(scored.values(), key=lambda item: (-float(item["score"]), -int(item["facts"])))[
        :40
    ]
    filenames = [str(item["filename"]) for item in ranked if item.get("filename")]
    document_ids = [str(item["document_id"]) for item in ranked if item.get("document_id")]
    if filenames:
        filters = {"document_filename": filenames}
    elif document_ids:
        filters = {"document_id": document_ids}
    else:
        return {}, 0.0, ""
    top_score = float(ranked[0]["score"])
    confidence = min(0.92, 0.62 + min(top_score, 8.0) / 40.0)
    reason = f"document facts scoped retrieval to {len(ranked)} candidate document(s)"
    return filters, confidence, reason


def _infer_summary_document_scope(
    *,
    collection_rows: list[KnowledgeCollection],
    query: str,
    limit: int = 80,
) -> tuple[dict[str, Any], float, str]:
    """Use offline document summaries as the coarse layer for deep dense search.

    This keeps HAH/C-HAH aligned with the intended coarse-to-fine shape: first
    pick likely documents/sections from cheap artifacts, then query Qdrant with
    payload filters. If artifacts are missing or too large for inline loading,
    the caller falls back to the existing dense policy rather than blocking.
    """
    ranked: list[dict[str, Any]] = []
    skipped_reasons: list[str] = []
    for collection in collection_rows:
        try:
            summary = load_summary_index_records(
                collection=collection,
                query=query,
                limit=limit,
            )
        except Exception as exc:  # noqa: BLE001 - planner must stay non-blocking.
            skipped_reasons.append(str(exc))
            continue
        status = str(summary.get("status") or "")
        if status != "ready":
            reason = str(summary.get("reason") or status or "summary_artifact_missing")
            if reason:
                skipped_reasons.append(reason)
            continue
        for record in summary.get("records") or []:
            if isinstance(record, Mapping):
                ranked.append(dict(record))
        if len(ranked) >= limit:
            break

    if not ranked:
        reason = "; ".join(skipped_reasons[:2]) if skipped_reasons else ""
        return {}, 0.0, reason

    filenames: list[str] = []
    document_ids: list[str] = []
    for record in ranked[:limit]:
        filename = str(record.get("document_filename") or "").strip()
        document_id = str(record.get("document_id") or "").strip()
        if filename and filename not in filenames:
            filenames.append(filename)
        if document_id and document_id not in document_ids:
            document_ids.append(document_id)

    if filenames:
        filters = {"document_filename": filenames}
    elif document_ids:
        filters = {"document_id": document_ids}
    else:
        return {}, 0.0, ""
    confidence = min(0.78, 0.54 + min(len(ranked), 80) / 400.0)
    reason = (
        f"summary artifacts scoped deep retrieval to {len(ranked[:limit])} candidate document(s)"
    )
    return filters, confidence, reason


def _fast_ledger_candidate_rows(
    query: str,
    rows: list[Any],
    *,
    policy: RetrievalPolicy | None = None,
    anchor_documents: list[str] | None = None,
    limit: int = 600,
) -> list[Any]:
    """Return a cheap candidate subset before expensive source-ledger scoring.

    On large industrial ledgers, scoring every source row can spend tens of
    seconds in Python string normalization. Fast chat only needs a small
    high-signal subset; if none is obvious, retrieval falls back to bounded
    sparse search instead of blocking the direct answer.
    """
    project_codes = _query_project_codes(
        query,
        known_codes=_candidate_project_codes(rows),
    )
    terms = [
        _compact_text(term)
        for term in _expanded_query_terms(query, policy)
        if len(_compact_text(term)) >= 5
    ][:24]
    anchors = _compact_anchor_documents(anchor_documents)
    if len(rows) <= limit and not project_codes:
        return rows
    if not project_codes and not terms and not anchors:
        return []

    scored: list[tuple[int, str, Any]] = []
    for row in rows:
        meta = _source_metadata(row)
        collection = getattr(row, "collection", None)
        text = " ".join(
            str(value or "")
            for value in (
                getattr(row, "filename", ""),
                getattr(row, "normalized_name", ""),
                getattr(row, "source_kind", ""),
                getattr(row, "extension", ""),
                getattr(collection, "slug", "") if collection is not None else "",
                getattr(collection, "name", "") if collection is not None else "",
                getattr(collection, "display_name", "") if collection is not None else "",
                meta.get("document_filename"),
                meta.get("project_code"),
                meta.get("archive_name"),
                meta.get("machine"),
                meta.get("line"),
                meta.get("source_family"),
            )
        )
        compact = _compact_text(text)
        if not compact:
            continue
        score = 0
        for code in project_codes:
            if code.lower() in compact:
                score += 12
        if project_codes and score <= 0:
            continue
        anchored = bool(anchors) and any(anchor in compact for anchor in anchors)
        if anchored:
            score += 6
        term_hits = 0
        for term in terms:
            if term and term in compact:
                term_hits += 1
                score += 2
        if term_hits or project_codes:
            family_score, _family_matches = score_source_family_match(
                query=query,
                row_text=text,
                metadata=meta,
                policy=policy,
            )
            if family_score:
                term_hits += 1
                score += int(round(family_score))
        if not project_codes and term_hits < 2 and not anchored:
            # A document the session already answered from survives this cheap
            # pre-filter on the anchor alone; the ledger scorer still has to
            # rank it against the rest.
            continue
        filename = str(getattr(row, "filename", "") or "").lower()
        scored.append((score, filename, row))

    if not scored:
        return []
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [row for _score, _filename, row in scored[: max(1, int(limit))]]


def _layer_status(
    *, enabled: bool, reason: str, budget_ms: int | None = None, top_k: int | None = None
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "enabled": bool(enabled),
        "status": "enabled" if enabled else "skipped",
        "reason": reason,
    }
    if budget_ms is not None:
        payload["budget_ms"] = int(budget_ms)
    if top_k is not None:
        payload["top_k"] = int(top_k)
    return payload


def _build_retrieval_plan(
    *,
    intent: str,
    dense: bool,
    latency_profile: LatencyProfile,
    dense_policy: str,
    filters: dict[str, Any],
    use_hybrid: bool | None,
    allow_hah_chah: bool,
    allow_legacy_hybrid: bool,
    deadline: float,
    top_k: int,
    candidate_pool_k: int,
    synthesis_k: int,
    max_variants: int,
    max_candidates: int,
    deep_retrieval_recommended: bool,
) -> dict[str, Any]:
    deadline_ms = int(max(float(deadline or 0.0), 0.0) * 1000)
    scoped = bool(filters)
    sparse_enabled = bool(
        use_hybrid
        and not allow_legacy_hybrid
        and (scoped or not dense or dense_policy == "fast_sparse_direct")
    )
    summaries_enabled = latency_profile == "deep" or (dense and scoped)
    deep_async_enabled = bool(deep_retrieval_recommended and latency_profile != "deep")
    return {
        "profile": latency_profile,
        "intent": intent,
        "dense_policy": dense_policy,
        "deadline_ms": deadline_ms,
        "top_k": top_k,
        "candidate_pool_k": candidate_pool_k,
        "synthesis_k": synthesis_k,
        "max_variants": max_variants,
        "max_candidates": max_candidates,
        "coarse_to_fine": bool(dense),
        "layers": {
            "inventory": _layer_status(
                enabled=intent == "catalogue" or dense,
                reason="catalogue/inventory answer"
                if intent == "catalogue"
                else "dense corpus guardrail and scope discovery",
                budget_ms=min(deadline_ms, 500),
            ),
            "facts": _layer_status(
                enabled=dense and (intent in {"procedure", "compare", "deep_audit"} or scoped),
                reason="fact ledger narrows candidate documents before chunk retrieval"
                if dense
                else "small corpus can retrieve chunks directly",
                budget_ms=min(deadline_ms, 1200),
            ),
            "summaries": _layer_status(
                enabled=summaries_enabled,
                reason="document/section summaries are the coarse layer for dense/deep retrieval"
                if summaries_enabled
                else "summary artifacts are optional unless dense scope or deep retrieval is active",
                budget_ms=min(deadline_ms, 2500),
                top_k=min(max(candidate_pool_k, 20), max_candidates),
            ),
            "dense_qdrant": _layer_status(
                enabled=not (dense and not scoped),
                reason="payload-filtered dense chunk retrieval"
                if scoped
                else "global dense retrieval skipped on dense unscoped corpus",
                budget_ms=min(deadline_ms, 3500),
                top_k=candidate_pool_k,
            ),
            "sparse": _layer_status(
                enabled=sparse_enabled,
                reason="external sparse backend only; legacy in-process BM25 is disabled for dense corpus"
                if sparse_enabled
                else (
                    "catalogue/dense fast policy skips sparse"
                    if dense_policy.startswith(("catalogue", "fast_scoped_dense"))
                    else (
                        "external sparse skipped until a system scope is inferred"
                        if dense and not scoped
                        else "legacy hybrid allowed for non-dense corpus"
                    )
                ),
                budget_ms=min(deadline_ms, 2500),
                top_k=candidate_pool_k,
            ),
            "hah_chah": _layer_status(
                enabled=allow_hah_chah,
                reason="budget-aware layered HAH/C-HAH enabled"
                if allow_hah_chah
                else "interactive dense guardrail downgrades HAH/C-HAH to bounded retrieval",
                budget_ms=deadline_ms,
                top_k=max_candidates,
            ),
            "rerank": _layer_status(
                enabled=True,
                reason="normalize/fuse/rerank only the bounded candidate pool",
                budget_ms=min(deadline_ms, 1200),
                top_k=synthesis_k,
            ),
            "deep_async": _layer_status(
                enabled=deep_async_enabled,
                reason="queued refinement for dense degraded/unguarded queries"
                if deep_async_enabled
                else "not needed for this interactive plan",
                budget_ms=int(settings.rag_deep_retrieval_deadline_seconds * 1000),
            ),
        },
        "guardrails": {
            "allow_legacy_hybrid": allow_legacy_hybrid,
            "global_chunk_search_allowed": not dense,
            "scoped_chunk_search_allowed": not (dense and not scoped),
            "user_scope_required": False,
        },
    }


def plan_corpus(
    *,
    db: DBSession,
    profile: Mapping[str, Any],
    query: str,
    request: Mapping[str, Any] | None = None,
    retrieval_policy: RetrievalPolicy | None = None,
) -> CorpusPlan:
    started = time.time()
    latency_profile = normalize_latency_profile(
        profile.get("latency_profile"),
        deep_retrieval=profile.get("deep_retrieval") or (request or {}).get("deep_retrieval"),
    )
    collections = [
        str(item)
        for item in (profile.get("collections") or [profile.get("collection") or "documents"])
        if item
    ]
    raw_authoritative = (request or {}).get("authoritative_collections")
    authoritative_collections = (
        list(
            dict.fromkeys(
                str(item).strip() for item in raw_authoritative if str(item or "").strip()
            )
        )
        if isinstance(raw_authoritative, (list, tuple, set))
        else []
    )
    if authoritative_collections:
        collections = authoritative_collections
    workspace_id = str(profile.get("workspace_id") or "") or None
    # Interactive profiles (fast + balanced) must never load and scan the full
    # source ledger in Python: on large industrial corpora (e.g. ~100k sources
    # in one collection) that costs ~45-90s on the chat hot path. They pass the
    # query so _rows_for_collections performs a bounded DB-side ILIKE targeting
    # of candidate sources (filename/normalized_name) instead of loading every
    # row. The Python ledger/filter scoring then runs over that bounded set,
    # preserving the inferred scope.
    #
    # Deep (async, backgrounded) historically kept the exhaustive full-ledger
    # load. That is safe on small corpora but on large ledger-backed corpora the
    # full Python scan was measured at ~55-120s and dominates the deep deadline,
    # so broad/unscoped deep jobs time out with 0 passages even though the Qdrant
    # retrieval itself is sub-second. Deep therefore takes the same bounded
    # targeting as fast/balanced *on large collections only*; small-corpus deep
    # keeps its exhaustive scan unchanged.
    if latency_profile == "deep":
        source_lookup_query = (
            query if _deep_ledger_is_large(db, collections, workspace_id) else None
        )
    else:
        source_lookup_query = query
    anchor_documents = _session_document_anchors(request, query=query, policy=retrieval_policy)
    if source_lookup_query and anchor_documents:
        # Candidate targeting is filename-substring based, so an anchored
        # document has to be part of the lookup text or the bounded candidate
        # set can never contain it and the anchor bonus would score nothing.
        source_lookup_query = " ".join([source_lookup_query, *anchor_documents])
    rows, collection_rows = _rows_for_collections(
        db,
        collections,
        workspace_id,
        source_lookup_query=source_lookup_query,
    )
    workspace_rows = rows
    fast_local_ledger_rows: list[Any] = []
    if latency_profile == "fast":
        fast_local_ledger_rows = _fast_ledger_candidate_rows(
            query,
            rows,
            policy=retrieval_policy,
            anchor_documents=anchor_documents,
        )
    if workspace_id and not authoritative_collections:
        should_expand_workspace = True
        if latency_profile == "fast":
            project_codes = _query_project_codes(
                query,
                known_codes=_candidate_project_codes(rows),
            )
            table_lookup_requested = bool(_TABLE_VALUE_LOOKUP_RE.search(query))
            should_expand_workspace = bool(
                table_lookup_requested or (project_codes and not fast_local_ledger_rows)
            )
        if should_expand_workspace:
            workspace_collection_refs = [
                str(row.slug or row.id)
                for row in _workspace_collections(db, workspace_id)
                if str(row.slug or row.id)
            ]
        else:
            workspace_collection_refs = []
        if workspace_collection_refs and set(workspace_collection_refs) != set(collections):
            candidate_rows, _candidate_collection_rows = _rows_for_collections(
                db,
                workspace_collection_refs,
                workspace_id,
                source_lookup_query=source_lookup_query,
            )
            if candidate_rows:
                workspace_rows = candidate_rows
    intent = classify_intent(query)
    explicit_filters = _request_filters(request)
    inferred_filters, confidence, reason = _infer_filters(query, workspace_rows)
    if explicit_filters:
        ledger_filters, ledger_confidence, ledger_reason, ledger_collections = {}, 0.0, "", []
    else:
        ledger_rows = workspace_rows
        if latency_profile == "fast":
            ledger_rows = fast_local_ledger_rows or _fast_ledger_candidate_rows(
                query,
                workspace_rows,
                policy=retrieval_policy,
                anchor_documents=anchor_documents,
            )
        (
            ledger_filters,
            ledger_confidence,
            ledger_reason,
            ledger_collections,
        ) = _infer_ledger_document_scope(
            query,
            ledger_rows,
            policy=retrieval_policy,
            anchor_documents=anchor_documents,
        )
    table_lookup_collections = (
        _spreadsheet_collection_refs(workspace_rows) if _TABLE_VALUE_LOOKUP_RE.search(query) else []
    )
    if authoritative_collections:
        table_lookup_collections = [
            item for item in table_lookup_collections if item in authoritative_collections
        ]
    if table_lookup_collections:
        collections = table_lookup_collections
        rows, collection_rows = _rows_for_collections(db, collections, workspace_id)
        # The collection selection is already the system scope. Do not add
        # payload filters here: older spreadsheet Qdrant payloads may miss
        # kind/extension fields, and broad filename-overlap document_id
        # filters can erase valid table chunks such as GEOTEX "Def strips".
        inferred_filters = {
            key: value
            for key, value in inferred_filters.items()
            if key
            not in {
                "source_kind",
                "extension",
                "document_id",
                "document_filename",
                "project_code",
                "archive_name",
            }
        }
        ledger_filters = {}
        ledger_collections = []
        confidence = max(confidence, 0.72)
        reason = f"table value lookup scoped retrieval to {len(table_lookup_collections)} spreadsheet collection(s)"
    elif ledger_collections:
        if authoritative_collections:
            unbounded_ledger_collections = list(ledger_collections)
            ledger_collections = [
                item for item in ledger_collections if item in authoritative_collections
            ]
            if unbounded_ledger_collections and not ledger_collections:
                ledger_filters = {}
                ledger_confidence = 0.0
                ledger_reason = ""
    if ledger_collections and not table_lookup_collections:
        if set(ledger_collections) != set(collections):
            collections = ledger_collections
            rows, collection_rows = _rows_for_collections(
                db,
                collections,
                workspace_id,
                source_lookup_query=source_lookup_query,
            )
        else:
            collections = ledger_collections
    ledger_source_count = len(rows)
    collection_source_count = sum(
        int(c.document_count or 0) or _collection_source_count(db, c) for c in collection_rows
    )
    ledger_chunk_count = sum(int(getattr(row, "chunk_count", 0) or 0) for row in rows)
    collection_chunk_count = sum(int(c.chunk_count or 0) for c in collection_rows)
    source_count = max(ledger_source_count, collection_source_count)
    chunk_count = max(ledger_chunk_count, collection_chunk_count)
    dense = bool(
        chunk_count > int(settings.rag_dense_chunk_threshold)
        or source_count > int(settings.rag_dense_source_threshold)
    )
    if ledger_filters:
        # Source-ledger matches are the preferred coarse layer for dense
        # workspaces. Avoid AND-ing project/archive metadata with filenames:
        # older Qdrant payloads may not have those fields even when the ledger
        # does, and the filename filter is already the precise scope.
        inferred_filters = dict(ledger_filters)
        confidence = max(confidence, ledger_confidence)
        reason = ledger_reason
    filters = {**inferred_filters, **explicit_filters}
    # Fact-scope inference scopes retrieval to the documents whose facts carry
    # the query's discriminating terms (GIN pg_trgm indexes, migration 045).
    # Crucially it only admits documents that have *extracted facts* matching the
    # terms, so on a large corpus it silently drops documents whose answer lives
    # in unstructured chunks that were never lifted into the fact ledger. A HARD
    # document_filename filter then starves the dense search of those answer
    # chunks.
    #
    # On large ledger-backed collections the answer is NOT to gate fact-scope off
    # for balanced (the previous hard-gate): that left fact queries in the
    # unscoped dense fallback, which is guardrailed against running a global
    # chunk search on the huge collection. Fact-backed answers that only live in
    # that collection were then never retrieved.
    #
    # Instead fact-scope becomes ADDITIVE ("soft boost") for balanced + large:
    #   (a) the query keeps the unscoped fast_sparse_direct path, so non-fact
    #       answers whose chunks are not in the fact ledger are NOT starved; AND
    #   (b) the fact-matched documents are scope-searched IN ADDITION, which is
    #       the only way the guardrailed large collection gets touched for
    #       fact-backed answers — and the results are unioned in retrieval.
    # The bounded fact scan is index-backed (pg_trgm GIN, migration 045) and
    # demotes ubiquitous terms, so it stays interactive (single-digit seconds).
    # Deep and balanced+small keep the precise hard document_filename filter.
    large_collection_slugs: list[str] = []
    for c in collection_rows:
        if (
            int(getattr(c, "document_count", 0) or 0) > _LEDGER_TARGETING_MIN_SOURCES
            or int(getattr(c, "chunk_count", 0) or 0) > _LEDGER_TARGETING_MIN_CHUNKS
        ):
            # Emit both slug and id so retrieval matches whichever identifier the
            # emitted ``collections`` list ends up carrying.
            large_collection_slugs.extend(
                str(ref)
                for ref in (getattr(c, "slug", ""), getattr(c, "id", ""))
                if str(ref or "").strip()
            )
    large_collection_slugs = list(dict.fromkeys(large_collection_slugs))
    large_collection_scope = bool(large_collection_slugs)
    run_fact_scope = latency_profile in {"deep", "balanced"}
    soft_fact_scope = latency_profile == "balanced" and large_collection_scope
    soft_scope_filters: dict[str, Any] = {}
    soft_scope_reason = ""
    soft_scope_collections: list[str] = []
    if explicit_filters:
        confidence = max(confidence, 0.95)
        reason = f"System/agent retrieval filters supplied: {', '.join(sorted(explicit_filters))}."
    elif dense and not filters and intent != "catalogue" and run_fact_scope:
        fact_filters, fact_confidence, fact_reason = _infer_fact_document_scope(
            db,
            collection_rows=collection_rows,
            query=query,
            intent=intent,
        )
        if fact_filters and soft_fact_scope:
            # Additive soft boost: leave ``filters`` empty so the unscoped
            # fast_sparse_direct path still runs over the SMALL scope
            # collections; retrieval searches the LARGE collection(s) with this
            # scoped filter instead (an unscoped global chunk search there is too
            # slow/low-value) and unions the per-collection results.
            soft_scope_filters = fact_filters
            soft_scope_reason = fact_reason
            soft_scope_collections = list(large_collection_slugs)
        elif fact_filters:
            filters = fact_filters
            confidence = max(confidence, fact_confidence)
            reason = fact_reason
        else:
            summary_filters, summary_confidence, summary_reason = _infer_summary_document_scope(
                collection_rows=collection_rows,
                query=query,
                limit=80 if latency_profile == "deep" else 20,
            )
            if summary_filters:
                filters = summary_filters
                confidence = max(confidence, summary_confidence)
                reason = summary_reason
            elif summary_reason:
                reason = f"{reason} Summary artifact scope unavailable: {summary_reason}."
    elif dense and not filters and intent != "catalogue":
        summary_filters, summary_confidence, summary_reason = _infer_summary_document_scope(
            collection_rows=collection_rows,
            query=query,
            limit=20,
        )
        if summary_filters:
            filters = summary_filters
            confidence = max(confidence, summary_confidence)
            reason = summary_reason
        else:
            reason = (
                "Dense fast retrieval skipped expensive fact scope inference; "
                "using inventory/diagnostics and queued deep refinement."
            )
            if summary_reason:
                reason = f"{reason} Summary artifact scope unavailable: {summary_reason}."

    if latency_profile == "deep":
        deadline = float(settings.rag_deep_retrieval_deadline_seconds)
        top_k = min(max(int(profile.get("top_k") or 8), 1), 24)
        synthesis_k = min(max(int(profile.get("synthesis_k") or 24), top_k), 48)
        candidate_pool_k = min(max(int(profile.get("candidate_pool_k") or 80), synthesis_k), 200)
        max_variants = 6
        max_candidates = min(max(candidate_pool_k, 80), 200)
    elif latency_profile == "balanced":
        deadline = min(float(settings.rag_fast_retrieval_deadline_seconds) * 2, 20.0)
        top_k = min(max(int(profile.get("top_k") or 8), 1), 12)
        synthesis_k = min(max(int(profile.get("synthesis_k") or 12), top_k), 24)
        candidate_pool_k = min(max(int(profile.get("candidate_pool_k") or 40), synthesis_k), 80)
        max_variants = 3
        max_candidates = min(max(candidate_pool_k, 40), 80)
    else:
        deadline = float(settings.rag_fast_retrieval_deadline_seconds)
        top_k = min(max(int(profile.get("top_k") or 5), 1), 8)
        source_display_k = min(max(int(profile.get("source_display_k") or top_k), 1), 8)
        synthesis_k = min(
            max(int(profile.get("synthesis_k") or source_display_k), source_display_k), 12
        )
        candidate_pool_k = min(max(int(profile.get("candidate_pool_k") or 20), synthesis_k), 20)
        max_variants = 3
        max_candidates = 20

    if latency_profile != "fast":
        source_display_k = min(max(int(profile.get("source_display_k") or top_k), 1), 24)

    # Recall floor (see CorpusPlan.recall_floor_*). A hard ``document_filename``
    # allowlist from the ledger scope is a filename-keyword guess: it is precise
    # but can omit the actual answer document when that document's filename does
    # not advertise the query's surface terms. On a LARGE collection the missed
    # document is unreachable (the hard filter excludes it before retrieval). We
    # keep the hard scope as the primary precision layer and, in addition, flag
    # the large scoped collection(s) for a bounded UNSCOPED dense recall-floor
    # pass that retrieval unions into the candidate pool. Strictly gated: only a
    # hard document_filename filter on a large collection arms it; small
    # collections and non-document-filename scopes are a no-op (unchanged).
    recall_floor_collections: list[str] = []
    recall_floor_top_n = 0
    recall_floor_reason = ""
    hard_document_filename_scope = bool(
        not explicit_filters
        and isinstance(ledger_filters, Mapping)
        and ledger_filters.get("document_filename")
        and filters.get("document_filename")
    )
    if dense and large_collection_scope and hard_document_filename_scope:
        recall_floor_collections = list(large_collection_slugs)
        recall_floor_top_n = max(10, min(int(candidate_pool_k or 0) or 20, 20))
        recall_floor_reason = (
            "recall floor: bounded unscoped dense pass over "
            f"{len(recall_floor_collections)} large collection(s) unioned with the hard "
            "document_filename scope so a filename-keyword miss cannot starve the answer doc"
        )

    allow_hah_chah = True
    allow_legacy_hybrid = True
    use_hybrid: bool | None = None
    dense_policy = "standard"
    fallback_reason: str | None = None
    deep_retrieval_recommended = False
    requested_mode = (
        str(profile.get("rag_mode") or profile.get("rag_pipeline_mode") or "auto").strip().lower()
    )
    dense_only_requested = requested_mode in {"vector", "vector_only", "dense", "dense_only"}

    if intent == "catalogue":
        dense_policy = "catalogue_inventory"
        use_hybrid = False
        allow_hah_chah = False
    elif dense and latency_profile != "deep":
        allow_legacy_hybrid = False
        if not filters:
            # Unscoped dense retrieval (no inferred scope): balanced runs the
            # same real bounded vector/sparse search as fast. The HNSW vector
            # search is sub-second regardless of corpus size; runtime evidence
            # showed the former balanced guardrail returned only a synthetic
            # inventory while fast surfaced the actual answer (e.g. filter
            # nominal capacity for a flow-rate question), making balanced
            # strictly worse than fast despite a larger latency budget. Deep
            # refinement is still queued via deep_retrieval_recommended.
            dense_policy = "fast_sparse_direct"
            use_hybrid = True
            fallback_reason = None
            allow_hah_chah = False
            deep_retrieval_recommended = True
        else:
            dense_policy = "fast_scoped_dense"
            allow_hah_chah = latency_profile == "balanced"
            use_hybrid = not dense_only_requested
    elif dense and latency_profile == "deep":
        dense_policy = "deep_hierarchical_dense"
        allow_legacy_hybrid = False
        if filters and not dense_only_requested:
            use_hybrid = True
        elif not filters:
            use_hybrid = False
            allow_hah_chah = False
            fallback_reason = "dense_unscoped_deep_policy"

    if authoritative_collections:
        collections = authoritative_collections
        soft_scope_collections = [
            item for item in soft_scope_collections if item in authoritative_collections
        ]
        recall_floor_collections = [
            item for item in recall_floor_collections if item in authoritative_collections
        ]
    retrieval_scope = {
        "collections": collections,
        "filters": filters,
        "intent": intent,
        "dense": dense,
        "source_count": source_count,
        "chunk_count": chunk_count,
        "confidence": round(float(confidence), 3),
        "reason": reason,
        "corpus_version": _corpus_version(rows, collection_rows),
        "soft_scope_filters": soft_scope_filters,
        "soft_scope_collections": soft_scope_collections,
        "recall_floor_collections": recall_floor_collections,
        "recall_floor_top_n": recall_floor_top_n,
        "planner_ms": int((time.time() - started) * 1000),
    }
    retrieval_plan = _build_retrieval_plan(
        intent=intent,
        dense=dense,
        latency_profile=latency_profile,
        dense_policy=dense_policy,
        filters=filters,
        use_hybrid=use_hybrid,
        allow_hah_chah=allow_hah_chah,
        allow_legacy_hybrid=allow_legacy_hybrid,
        deadline=deadline,
        top_k=top_k,
        candidate_pool_k=candidate_pool_k,
        synthesis_k=synthesis_k,
        max_variants=max_variants,
        max_candidates=max_candidates,
        deep_retrieval_recommended=deep_retrieval_recommended,
    )
    return CorpusPlan(
        intent=intent,
        dense=dense,
        source_count=source_count,
        chunk_count=chunk_count,
        latency_profile=latency_profile,
        deadline_seconds=deadline,
        top_k=top_k,
        candidate_pool_k=candidate_pool_k,
        synthesis_k=synthesis_k,
        source_display_k=source_display_k,
        retrieval_scope=retrieval_scope,
        retrieval_plan=retrieval_plan,
        filters=filters,
        scope_confidence=round(float(confidence), 3),
        scope_reason=reason,
        dense_policy=dense_policy,
        use_hybrid=use_hybrid,
        allow_hah_chah=allow_hah_chah,
        allow_legacy_hybrid=allow_legacy_hybrid,
        max_variants=max_variants,
        max_candidates=max_candidates,
        fallback_reason=fallback_reason,
        deep_retrieval_recommended=deep_retrieval_recommended,
        soft_scope_filters=soft_scope_filters,
        soft_scope_reason=soft_scope_reason,
        soft_scope_collections=soft_scope_collections,
        recall_floor_collections=recall_floor_collections,
        recall_floor_top_n=recall_floor_top_n,
        recall_floor_reason=recall_floor_reason,
    )
