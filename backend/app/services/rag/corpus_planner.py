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
from typing import Any, Mapping
from types import SimpleNamespace

from sqlalchemy import or_
from sqlalchemy.orm import Session as DBSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models.knowledge_document_fact import KnowledgeDocumentFact
from app.models.knowledge_collection import KnowledgeCollection
from app.services.knowledge_collections import collection_source_rows
from app.services.rag.retrieval_policy import RetrievalPolicy
from app.services.rag.source_facets import expanded_terms_for_query, score_source_family_match
from app.services.rag.summary_artifacts import load_summary_index_records

logger = get_logger(__name__)

LatencyProfile = str

_CATALOGUE_RE = re.compile(
    r"\b("
    r"disposes?-?tu|as[-\s]?tu|donn[ée]es?|data|datasets?|catalogue|inventaire|"
    r"sources?|fichiers?|docs?|documents?|collections?|types?|formats?|extensions?|"
    r"combien|nombre|count|how\s+many|what\s+data|available\s+data"
    r")\b",
    re.IGNORECASE,
)
_CATALOGUE_PHRASE_RE = re.compile(
    r"(?:de\s+quelles?\s+donn[ée]es?|quelles?\s+donn[ée]es?|what\s+data|available\s+data)",
    re.IGNORECASE,
)
_COMPARE_RE = re.compile(r"\b(compare|comparer|diff[ée]rences?|versus|vs\.?)\b", re.IGNORECASE)
_PROCEDURE_RE = re.compile(
    r"\b(proc[ée]dure|procedure|mode\s+op[ée]ratoire|instruction|manuel|manual|"
    r"warning|caution|safety|s[ée]curit[ée])\b",
    re.IGNORECASE,
)
_AUDIT_RE = re.compile(r"\b(audit|diagnostic|qualit[ée]|coverage|couverture|clusters?)\b", re.IGNORECASE)
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
_PROJECT_CODE_RE = re.compile(r"\b[A-Z]{2,}[A-Z0-9]{1,}\d{2,}[A-Z0-9]*\b")
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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize_latency_profile(value: Any, *, deep_retrieval: Any = None) -> LatencyProfile:
    if bool(deep_retrieval):
        return "deep"
    parsed = str(value or "").strip().lower()
    if parsed in {"deep", "balanced", "fast"}:
        return parsed
    return "fast"


def is_catalogue_query(query: str) -> bool:
    text = str(query or "").strip()
    if not text:
        return False
    if re.search(
        r"\b(?:quel|quelle|which|what)\b.*\b(?:source|document|fichier|file)\b.*\b(?:contient|contains?)\b",
        text,
        re.IGNORECASE,
    ):
        return False
    if _CATALOGUE_PHRASE_RE.search(text):
        return True
    return bool(_CATALOGUE_RE.search(text) and re.search(r"\b(data|donn[ée]es?|docs?|documents?|sources?|fichiers?|collections?)\b", text, re.IGNORECASE))


def classify_intent(query: str) -> str:
    text = str(query or "")
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
        and not re.search(r"\b(combien|nombre|count|how\s+many|types?|formats?|extensions?)\b", text, re.IGNORECASE)
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


def _rows_for_collections(db: DBSession, collections: list[str], workspace_id: str | None) -> tuple[list[Any], list[KnowledgeCollection]]:
    rows: list[Any] = []
    collection_rows: list[KnowledgeCollection] = []
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


def _missing_document_name_rows(collection: KnowledgeCollection, existing_rows: list[Any]) -> list[Any]:
    names = [str(name or "").strip() for name in (collection.document_names or []) if str(name or "").strip()]
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
        if kind != "spreadsheet" and ext not in {"xlsx", "xls", "xlsm", "csv"} and not filename.endswith((".xlsx", ".xls", ".xlsm", ".csv")):
            continue
        ref = _row_collection_ref(row)
        if ref and ref not in refs:
            refs.append(ref)
    return refs


def _query_project_codes(query: str) -> list[str]:
    folded = _fold_text(query).upper()
    codes: list[str] = []
    for match in _PROJECT_CODE_RE.findall(folded):
        compact = _compact_text(match).upper()
        if len(compact) >= 5 and compact not in codes:
            codes.append(compact)
    for prefix, suffix in re.findall(r"\b([A-Z]{2,}[A-Z0-9]*)\s*[-_/ ]\s*(\d{2,}[A-Z0-9]*)\b", folded):
        compact = f"{prefix}{suffix}".upper()
        if len(compact) >= 5 and compact not in codes:
            codes.append(compact)
    return codes


def _is_broad_format_scope_query(query: str) -> bool:
    text = _search_text(query)
    if not re.search(r"\b(fichiers?|files?|documents?|sources?|docs?)\b", text):
        return False
    if not any(re.search(rf"\b{re.escape(token)}\b", text) for token in (*_EXTENSION_ALIASES, *_SOURCE_KIND_ALIASES)):
        return False
    return not bool(_query_project_codes(query) or re.search(r"\b(retrouve(?:r)?|find|locate)\b", text))


def _expanded_query_terms(query: str, policy: RetrievalPolicy | None = None) -> list[str]:
    text = _search_text(query)
    terms: list[str] = []

    def add(*values: str) -> None:
        for value in values:
            cleaned = _search_text(value)
            if len(cleaned) >= 3 and cleaned not in terms:
                terms.append(cleaned)

    for token in text.split():
        if len(token) >= 3 and token not in _QUERY_STOPWORDS:
            add(token)
    add(*expanded_terms_for_query(query, policy))
    return terms[:40]


def _infer_ledger_document_scope(
    query: str,
    rows: list[Any],
    *,
    policy: RetrievalPolicy | None = None,
) -> tuple[dict[str, Any], float, str, list[str]]:
    if not rows:
        return {}, 0.0, "", []
    terms = _expanded_query_terms(query, policy)
    family_expanded_terms = {_search_text(term) for term in expanded_terms_for_query(query, policy)}
    project_codes = _query_project_codes(query)
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

    scored: list[tuple[float, bool, bool, Any]] = []
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
        for code in project_codes:
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
            if len(compact_term) >= 5 and compact_term in source_only_compact and not is_project_term and not is_family_term:
                score += 8.0
        family_score, family_matches = score_source_family_match(
            query=query,
            row_text=source_only_text,
            metadata=source_metadata,
            policy=policy,
        )
        if family_score:
            score += family_score
            strong_phrase_match = True
        if compact_query and compact_query in compact_haystack:
            score += 4.0
            strong_phrase_match = True
        elif any(len(_compact_text(term)) >= 6 and _compact_text(term) in compact_haystack for term in terms):
            strong_phrase_match = strong_phrase_match or bool(family_matches)
        if has_source_lookup_signal:
            score += min(max(int(getattr(row, "chunk_count", 0) or 0), 0), 100) / 200.0
        threshold = 6.0 if project_codes else 7.0
        if score >= threshold:
            scored.append((score, matched_project, strong_phrase_match, row))
    if not scored:
        return {}, 0.0, "", []
    if project_codes and any(item[1] for item in scored):
        scored = [item for item in scored if item[1]]
        phrase_scored = [item for item in scored if item[2]]
        if phrase_scored and max(item[0] for item in phrase_scored) >= max(item[0] for item in scored):
            scored = phrase_scored
    elif project_codes:
        return {}, 0.0, f"No ledger source matched project/code {', '.join(project_codes[:3])}.", []
    else:
        phrase_scored = [item for item in scored if item[2]]
        if phrase_scored:
            scored = phrase_scored

    ranked = sorted(scored, key=lambda item: (-item[0], str(getattr(item[3], "filename", "") or "").lower()))[:20]
    filenames: list[str] = []
    collection_refs: list[str] = []
    for _, _matched_project, _strong_phrase_match, row in ranked:
        filename = str(getattr(row, "filename", "") or "").strip()
        if filename and filename not in filenames:
            filenames.append(filename)
        collection_ref = _row_collection_ref(row)
        if collection_ref and collection_ref not in collection_refs:
            collection_refs.append(collection_ref)
    if not filenames:
        return {}, 0.0, "", []
    top_score = float(ranked[0][0])
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
            if value and len(value) >= 3:
                codes.add(value)
        for match in _PROJECT_CODE_RE.findall(str(getattr(row, "filename", "") or "").upper()):
            codes.add(match)
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

    query_upper = text.upper()
    candidate_codes = _candidate_project_codes(rows)
    matched_codes = [code for code in sorted(candidate_codes, key=len, reverse=True) if code and code in query_upper]
    if matched_codes:
        filters["project_code"] = matched_codes[0]
        reasons.append(f"project_code={matched_codes[0]}")
        confidence = max(confidence, 0.82)

    # If a source document is named very explicitly in the question, use its
    # document_id from the ledger. Keep the list small: Qdrant MatchAny should
    # select a candidate set, not carry the whole corpus.
    source_hits: list[str] = []
    words = {w for w in re.findall(r"[a-z0-9]{4,}", lower) if len(w) >= 4}
    query_project_codes = _query_project_codes(text)
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

    reason = "; ".join(reasons) if reasons else "No strong metadata scope inferred; using bounded semantic retrieval."
    return filters, confidence, reason


def _query_terms(query: str) -> list[str]:
    terms: list[str] = []
    for raw in _TERM_RE.findall(str(query or "").lower()):
        token = raw.strip("_-")
        if len(token) < 4 or token in _QUERY_STOPWORDS:
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

    predicates = []
    for term in terms:
        like = f"%{term}%"
        predicates.extend(
            [
                KnowledgeDocumentFact.content.ilike(like),
                KnowledgeDocumentFact.subject.ilike(like),
                KnowledgeDocumentFact.value_raw.ilike(like),
                KnowledgeDocumentFact.section_path.ilike(like),
                KnowledgeDocumentFact.document_filename.ilike(like),
            ]
        )
    query_rows = (
        db.query(KnowledgeDocumentFact)
        .filter(
            KnowledgeDocumentFact.workspace_id == workspace_id,
            KnowledgeDocumentFact.collection_id.in_(collection_ids),
            or_(*predicates),
        )
        .order_by(KnowledgeDocumentFact.confidence.desc(), KnowledgeDocumentFact.updated_at.desc())
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
        for term in terms:
            if term in haystack:
                score += 1.0
            if filename and term in filename.lower():
                score += 1.5
        if intent_bonus and any(token in str(fact.semantic_type or "").lower() for token in intent_bonus):
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

    ranked = sorted(scored.values(), key=lambda item: (-float(item["score"]), -int(item["facts"])))[:40]
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
    reason = f"summary artifacts scoped deep retrieval to {len(ranked[:limit])} candidate document(s)"
    return filters, confidence, reason


def _layer_status(*, enabled: bool, reason: str, budget_ms: int | None = None, top_k: int | None = None) -> dict[str, Any]:
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
    sparse_enabled = bool(use_hybrid and not allow_legacy_hybrid and (scoped or not dense))
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
                reason="catalogue/inventory answer" if intent == "catalogue" else "dense corpus guardrail and scope discovery",
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
    collections = [str(item) for item in (profile.get("collections") or [profile.get("collection") or "documents"]) if item]
    workspace_id = str(profile.get("workspace_id") or "") or None
    rows, collection_rows = _rows_for_collections(db, collections, workspace_id)
    workspace_rows = rows
    if workspace_id:
        workspace_collection_refs = [
            str(row.slug or row.id)
            for row in _workspace_collections(db, workspace_id)
            if str(row.slug or row.id)
        ]
        if workspace_collection_refs and set(workspace_collection_refs) != set(collections):
            candidate_rows, _candidate_collection_rows = _rows_for_collections(db, workspace_collection_refs, workspace_id)
            if candidate_rows:
                workspace_rows = candidate_rows
    intent = classify_intent(query)
    explicit_filters = _request_filters(request)
    inferred_filters, confidence, reason = _infer_filters(query, workspace_rows)
    if explicit_filters:
        ledger_filters, ledger_confidence, ledger_reason, ledger_collections = {}, 0.0, "", []
    else:
        ledger_filters, ledger_confidence, ledger_reason, ledger_collections = _infer_ledger_document_scope(
            query,
            workspace_rows,
            policy=retrieval_policy,
        )
    table_lookup_collections = _spreadsheet_collection_refs(workspace_rows) if _TABLE_VALUE_LOOKUP_RE.search(query) else []
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
            if key not in {"source_kind", "extension", "document_id", "document_filename", "project_code", "archive_name"}
        }
        ledger_filters = {}
        ledger_collections = []
        confidence = max(confidence, 0.72)
        reason = f"table value lookup scoped retrieval to {len(table_lookup_collections)} spreadsheet collection(s)"
    elif ledger_collections:
        collections = ledger_collections
        rows, collection_rows = _rows_for_collections(db, collections, workspace_id)
    ledger_source_count = len(rows)
    collection_source_count = sum(int(c.document_count or 0) for c in collection_rows)
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
    if explicit_filters:
        confidence = max(confidence, 0.95)
        reason = f"System/agent retrieval filters supplied: {', '.join(sorted(explicit_filters))}."
    elif dense and not filters and intent != "catalogue" and latency_profile != "fast":
        fact_filters, fact_confidence, fact_reason = _infer_fact_document_scope(
            db,
            collection_rows=collection_rows,
            query=query,
            intent=intent,
        )
        if fact_filters:
            filters = fact_filters
            confidence = max(confidence, fact_confidence)
            reason = fact_reason
        elif latency_profile == "deep":
            summary_filters, summary_confidence, summary_reason = _infer_summary_document_scope(
                collection_rows=collection_rows,
                query=query,
                limit=80,
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
        synthesis_k = min(max(int(profile.get("synthesis_k") or source_display_k), source_display_k), 12)
        candidate_pool_k = min(max(int(profile.get("candidate_pool_k") or 20), synthesis_k), 20)
        max_variants = 3
        max_candidates = 20

    if latency_profile != "fast":
        source_display_k = min(max(int(profile.get("source_display_k") or top_k), 1), 24)

    allow_hah_chah = True
    allow_legacy_hybrid = True
    use_hybrid: bool | None = None
    dense_policy = "standard"
    fallback_reason: str | None = None
    deep_retrieval_recommended = False
    requested_mode = str(profile.get("rag_mode") or profile.get("rag_pipeline_mode") or "auto").strip().lower()

    if intent == "catalogue":
        dense_policy = "catalogue_inventory"
        use_hybrid = False
        allow_hah_chah = False
    elif dense and latency_profile != "deep":
        allow_legacy_hybrid = False
        if not filters:
            dense_policy = "fast_scoped_dense_auto"
            use_hybrid = False
            allow_hah_chah = False
            deep_retrieval_recommended = True
            fallback_reason = "dense_unscoped_fast_policy"
        else:
            dense_policy = "fast_scoped_dense"
            allow_hah_chah = latency_profile == "balanced"
            if allow_hah_chah and requested_mode not in {"naive", "naive_rag", "vector", "dense"}:
                use_hybrid = True
            else:
                use_hybrid = False
    elif dense and latency_profile == "deep":
        dense_policy = "deep_hierarchical_dense"
        allow_legacy_hybrid = False
        if filters and requested_mode not in {"naive", "naive_rag", "vector", "dense"}:
            use_hybrid = True
        elif not filters:
            use_hybrid = False
            allow_hah_chah = False
            fallback_reason = "dense_unscoped_deep_policy"

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
    )
