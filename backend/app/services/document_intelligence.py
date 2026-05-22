"""Provider-neutral document intelligence for manuals and procedures.

This module complements table_intelligence.py. Tables keep their specialised
fact store for calculations; this layer extracts source-grounded facts from
PDF/DOCX/Markdown/Text style documents so retrieval can cite procedures,
warnings, parameters and definitions outside vector top-k.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.knowledge_collection import KnowledgeCollection
from app.models.knowledge_document_fact import KnowledgeDocumentFact
from app.models.system import System
from app.models.workspace import Workspace
from app.services.object_store import get_object_store
from app.services.rag.knowledge_scopes import normalize_knowledge_scopes, select_scope

logger = get_logger(__name__)


GLOBAL_DOCUMENT_PROFILE = {
    "key": "generic_document",
    "label": "Generic document analysis",
    "synonyms": {},
    "max_candidate_facts": 5000,
    "max_evidence_rows": 24,
}

_WORD_RE = re.compile(r"[A-Za-zÀ-ÿ0-9][A-Za-zÀ-ÿ0-9_.-]*")
_WARNING_RE = re.compile(r"\b(warning|caution|danger|attention|avertissements?|sécurité|securite|prudence|important)\b", re.I)
_PROCEDURE_RE = re.compile(r"\b(procedure|procédure|procedure|step|étape|etape|instruction|consigne|maintenance|commissioning|démarrage|demarrage|arrêt|arret)\b", re.I)
_PARAMETER_RE = re.compile(
    r"^\s*(?P<name>[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ0-9_/%°() .+-]{2,60})\s*(?:[:=]|—|-)\s*(?P<value>[^\n]{1,160})\s*$"
)
_DEFINITION_RE = re.compile(r"\b(is defined as|means|corresponds to|est défini|est definie|signifie|correspond à|correspond a)\b", re.I)
_HEADING_RE = re.compile(r"^\s*(?:(?P<num>\d+(?:\.\d+){0,5})\s+)?(?P<title>[A-ZÀ-Ý][A-Za-zÀ-ÿ0-9 /_().,:+-]{3,120})\s*$")
_DOC_QUERY_RE = re.compile(
    r"\b("
    r"procedure|procédure|procedure|étape|etape|instruction|consigne|warning|caution|danger|"
    r"avertissement|sécurité|securite|paramètre|parametre|parameter|réglage|reglage|"
    r"maintenance|troubleshooting|panne|définition|definition|manuel|manual|page|section|"
    r"compare|comparaison"
    r")\b",
    re.I,
)
_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "de", "des", "du", "en", "est", "et",
    "for", "in", "is", "la", "le", "les", "of", "on", "pour", "quelle", "quel",
    "sur", "the", "to", "un", "une",
}


@dataclass(frozen=True)
class EffectiveDocumentProfile:
    profile: dict[str, Any]
    source: str
    scope: dict[str, Any] | None = None


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


def _doc_type(parsed_doc: Any) -> str:
    value = getattr(getattr(parsed_doc, "document_type", None), "value", None)
    return str(value or getattr(parsed_doc, "document_type", "") or "").strip()


def _normalize(value: Any) -> str:
    return " ".join(_WORD_RE.findall(_safe_text(value).lower()))


def _tokens(text: str) -> list[str]:
    out: list[str] = []
    for token in _WORD_RE.findall(text.lower()):
        if token in _STOPWORDS:
            continue
        if len(token) <= 1 and not token.isalpha():
            continue
        if token not in out:
            out.append(token)
    return out


def _parse_numeric(value: Any) -> float | None:
    raw = _safe_text(value)
    if not raw:
        return None
    cleaned = raw.replace("\u202f", "").replace(" ", "").replace(",", ".")
    match = re.search(r"[-+]?\d+(?:\.\d+)?", cleaned)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def _unit_from_value(value: Any) -> str | None:
    raw = _safe_text(value)
    match = re.search(r"\b(mm|cm|m|kg|g|mg|bar|mbar|°c|c|%|rpm|m/min|n/50\s*mm)\b", raw, re.I)
    return match.group(0) if match else None


def _merged_profile(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = {**merged[key], **value}
        else:
            merged[key] = value
    return merged


def resolve_document_profile(
    *,
    workspace: Workspace,
    scope: dict[str, Any] | None = None,
    system: System | None = None,
    request_profile_key: str | None = None,
) -> EffectiveDocumentProfile:
    settings = _as_dict(workspace.settings)
    doc_settings = _as_dict(settings.get("document_intelligence"))
    profiles = [p for p in _as_list(doc_settings.get("profiles")) if isinstance(p, dict)]
    by_key = {_safe_text(p.get("key")): p for p in profiles if _safe_text(p.get("key"))}
    system_settings = _as_dict(getattr(system, "settings", None))
    system_doc = _as_dict(system_settings.get("document_intelligence"))
    key = (
        _safe_text(request_profile_key)
        or _safe_text(system_doc.get("profile_key"))
        or _safe_text((scope or {}).get("document_profile_key"))
        or _safe_text(doc_settings.get("default_profile"))
    )
    selected = GLOBAL_DOCUMENT_PROFILE
    source = "global_default"
    if key and key in by_key:
        selected = _merged_profile(GLOBAL_DOCUMENT_PROFILE, by_key[key])
        source = "workspace_profile"
    if system_doc.get("override"):
        selected = _merged_profile(selected, _as_dict(system_doc.get("override")))
        source = "system_override"
    return EffectiveDocumentProfile(profile=selected, source=source, scope=scope)


def ensure_document_artifacts(parsed_doc: Any) -> dict[str, Any]:
    """Add DocumentArtifact v1 data to ParsedDocument. Safe for all non-table docs."""
    structured = _as_dict(getattr(parsed_doc, "structured_content", None))
    if structured.get("document_artifacts"):
        return structured["document_artifacts"]
    if _doc_type(parsed_doc) in {"spreadsheet", "csv"}:
        structured["document_artifacts"] = {"schema_version": "document_artifact_v1", "structure": [], "facts": [], "diagnostics": {"skipped": "table_document"}}
        parsed_doc.structured_content = structured
        return structured["document_artifacts"]

    structure: list[dict[str, Any]] = []
    facts: list[dict[str, Any]] = []
    headings = _as_list(structured.get("headings"))
    for heading in headings:
        if not isinstance(heading, dict):
            continue
        text = _safe_text(heading.get("text"))
        if not text:
            continue
        structure.append(
            {
                "artifact_type": "heading",
                "title": text,
                "level": heading.get("level") or 1,
                "paragraph_index": heading.get("paragraph_index"),
            }
        )
        facts.append(
            {
                "semantic_type": "document_heading",
                "subject": text,
                "predicate": "heading",
                "value_raw": text,
                "content": f"Document heading: {text}",
                "section_path": text,
                "paragraph_index": heading.get("paragraph_index"),
                "confidence": 0.8,
            }
        )

    paragraphs = _paragraphs_from_document(parsed_doc)
    current_section = headings[0].get("text") if headings and isinstance(headings[0], dict) else None
    for paragraph in paragraphs[:2500]:
        text = _safe_text(paragraph.get("text"))
        if not text:
            continue
        parameter = _PARAMETER_RE.match(text)
        is_warning = bool(_WARNING_RE.search(text))
        is_step = bool(_PROCEDURE_RE.search(text) or re.match(r"^\s*(\d+[\).]|[-•])\s+\S", text))
        heading_match = _HEADING_RE.match(text)
        if heading_match and len(text) <= 140 and not parameter and not is_warning and not is_step:
            current_section = text
            if not any(item.get("title") == text for item in structure):
                structure.append(
                    {
                        "artifact_type": "heading",
                        "title": text,
                        "level": 1,
                        "page": paragraph.get("page"),
                        "paragraph_index": paragraph.get("paragraph_index"),
                }
            )
            continue

        base = {
            "page": paragraph.get("page"),
            "section_path": paragraph.get("section_path") or current_section,
            "paragraph_index": paragraph.get("paragraph_index"),
            "evidence_locator": {
                "page": paragraph.get("page"),
                "section_path": paragraph.get("section_path") or current_section,
                "paragraph_index": paragraph.get("paragraph_index"),
            },
        }
        if is_warning:
            facts.append(
                {
                    **base,
                    "semantic_type": "document_warning",
                    "subject": current_section or getattr(parsed_doc, "filename", None),
                    "predicate": "warning",
                    "value_raw": text,
                    "content": f"Warning: {text}",
                    "confidence": 0.75,
                }
            )
        if is_step:
            facts.append(
                {
                    **base,
                    "semantic_type": "document_procedure_step",
                    "subject": current_section or getattr(parsed_doc, "filename", None),
                    "predicate": "procedure_step",
                    "value_raw": text,
                    "content": f"Procedure step: {text}",
                    "confidence": 0.65,
                }
            )
        if parameter and not is_warning:
            name = parameter.group("name").strip()
            value = parameter.group("value").strip()
            facts.append(
                {
                    **base,
                    "semantic_type": "document_parameter",
                    "subject": name,
                    "predicate": "has_value",
                    "value_raw": value,
                    "value_numeric": _parse_numeric(value),
                    "unit": _unit_from_value(value),
                    "content": f"Parameter: {name} = {value}",
                    "confidence": 0.7,
                }
            )
        elif _DEFINITION_RE.search(text):
            subject = text.split(" ", 1)[0][:80]
            facts.append(
                {
                    **base,
                    "semantic_type": "document_definition",
                    "subject": subject,
                    "predicate": "definition",
                    "value_raw": text,
                    "content": f"Definition: {text}",
                    "confidence": 0.6,
                }
            )
        if len(facts) >= 1000:
            break

    for table in _as_list(getattr(parsed_doc, "tables", None) or structured.get("tables"))[:100]:
        if not isinstance(table, dict):
            continue
        table_index = table.get("table_index") or table.get("index")
        structure.append(
            {
                "artifact_type": "table",
                "table_index": table_index,
                "rows": table.get("rows") or table.get("data"),
                "row_count": table.get("row_count") or table.get("rows"),
                "col_count": table.get("col_count") or table.get("cols"),
            }
        )
        facts.append(
            {
                "semantic_type": "document_table",
                "subject": f"table {table_index or len(structure)}",
                "predicate": "table",
                "value_raw": _safe_text(table.get("rows") or table.get("data"))[:1000],
                "table_index": table_index,
                "content": f"Document table {table_index or ''}: {_safe_text(table.get('rows') or table.get('data'))[:1000]}",
                "confidence": 0.6,
            }
        )

    artifact = {
        "schema_version": "document_artifact_v1",
        "structure": structure[:1200],
        "facts": facts[:1200],
        "diagnostics": {
            "structure_count": min(len(structure), 1200),
            "fact_count": min(len(facts), 1200),
            "document_type": _doc_type(parsed_doc),
        },
    }
    structured["document_artifacts"] = artifact
    parsed_doc.structured_content = structured
    return artifact


def _paragraphs_from_document(parsed_doc: Any) -> list[dict[str, Any]]:
    structured = _as_dict(getattr(parsed_doc, "structured_content", None))
    paragraphs = [p for p in _as_list(structured.get("paragraphs")) if isinstance(p, dict)]
    if paragraphs:
        return paragraphs
    out: list[dict[str, Any]] = []
    for chunk in _as_list(getattr(parsed_doc, "chunks", None)):
        if not isinstance(chunk, dict):
            continue
        page = chunk.get("page")
        chunk_index = chunk.get("chunk_index")
        for line_index, line in enumerate(str(chunk.get("content") or "").splitlines(), start=1):
            text = line.strip()
            if len(text) < 8:
                continue
            out.append(
                {
                    "paragraph_index": (chunk_index or 0) * 1000 + line_index,
                    "text": text,
                    "page": page,
                }
            )
    if out:
        return out
    raw = str(getattr(parsed_doc, "raw_content", "") or "")
    return [
        {"paragraph_index": i, "text": text.strip()}
        for i, text in enumerate(raw.splitlines(), start=1)
        if len(text.strip()) >= 8
    ]


def replace_document_facts(
    db: Session,
    *,
    workspace: Workspace,
    collection: KnowledgeCollection,
    parsed_doc: Any,
) -> list[KnowledgeDocumentFact]:
    artifact = ensure_document_artifacts(parsed_doc)
    facts = [fact for fact in _as_list(artifact.get("facts")) if isinstance(fact, dict)]
    db.query(KnowledgeDocumentFact).filter(
        KnowledgeDocumentFact.workspace_id == workspace.id,
        KnowledgeDocumentFact.collection_id == collection.id,
        KnowledgeDocumentFact.document_id == getattr(parsed_doc, "id", None),
    ).delete(synchronize_session=False)
    if not facts:
        return []
    now = datetime.utcnow()
    rows = [
        _fact_row(raw, workspace=workspace, collection=collection, parsed_doc=parsed_doc, now=now)
        for raw in facts
    ]
    db.add_all(rows)
    _write_document_fact_jsonl(collection, parsed_doc, rows)
    return rows


def _fact_row(
    raw: dict[str, Any],
    *,
    workspace: Workspace,
    collection: KnowledgeCollection,
    parsed_doc: Any,
    now: datetime,
) -> KnowledgeDocumentFact:
    value_raw = _safe_text(raw.get("value_raw"))
    return KnowledgeDocumentFact(
        workspace_id=workspace.id,
        collection_id=collection.id,
        collection_slug=collection.slug,
        document_id=getattr(parsed_doc, "id", None),
        document_filename=getattr(parsed_doc, "filename", None),
        document_type=_doc_type(parsed_doc),
        source_path=_safe_text(getattr(parsed_doc, "file_path", None)) or _safe_text(_as_dict(getattr(parsed_doc, "metadata", None)).get("source_path")),
        semantic_type=_safe_text(raw.get("semantic_type")) or "document_fact",
        subject=_safe_text(raw.get("subject")) or None,
        predicate=_safe_text(raw.get("predicate")) or None,
        value_raw=value_raw or None,
        value_numeric=raw.get("value_numeric") if isinstance(raw.get("value_numeric"), (int, float)) else _parse_numeric(value_raw),
        unit=_safe_text(raw.get("unit")) or None,
        page=raw.get("page") if isinstance(raw.get("page"), int) else None,
        section_path=_safe_text(raw.get("section_path")) or None,
        paragraph_index=raw.get("paragraph_index") if isinstance(raw.get("paragraph_index"), int) else None,
        table_index=raw.get("table_index") if isinstance(raw.get("table_index"), int) else None,
        evidence_locator=_as_dict(raw.get("evidence_locator")),
        qualifiers=_as_dict(raw.get("qualifiers")),
        semantic_tags=[str(item) for item in _as_list(raw.get("semantic_tags"))],
        confidence=float(raw.get("confidence") or 0.65),
        content=_safe_text(raw.get("content")) or value_raw or _safe_text(raw.get("subject")),
        created_at=now,
        updated_at=now,
    )


def _write_document_fact_jsonl(collection: KnowledgeCollection, parsed_doc: Any, rows: list[KnowledgeDocumentFact]) -> None:
    try:
        store = get_object_store()
        key = f"{collection.artifact_prefix.rstrip('/')}/derived/document_facts/{getattr(parsed_doc, 'id', 'document')}.jsonl"
        payload = "\n".join(json.dumps(serialize_document_fact(row), ensure_ascii=False, default=str) for row in rows)
        store.write_text(key, payload)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not write document facts JSONL", error=str(exc), filename=getattr(parsed_doc, "filename", None))


def serialize_document_fact(fact: KnowledgeDocumentFact) -> dict[str, Any]:
    return {
        "id": fact.id,
        "collection_slug": fact.collection_slug,
        "document_id": fact.document_id,
        "document_filename": fact.document_filename,
        "document_type": fact.document_type,
        "semantic_type": fact.semantic_type,
        "subject": fact.subject,
        "predicate": fact.predicate,
        "value_raw": fact.value_raw,
        "value_numeric": fact.value_numeric,
        "unit": fact.unit,
        "page": fact.page,
        "section_path": fact.section_path,
        "paragraph_index": fact.paragraph_index,
        "table_index": fact.table_index,
        "evidence_locator": fact.evidence_locator or {},
        "qualifiers": fact.qualifiers or {},
        "semantic_tags": fact.semantic_tags or [],
        "confidence": fact.confidence,
        "content": fact.content,
        "source_path": fact.source_path,
    }


class DocumentQueryEngine:
    """Query structured document facts with a source-first contract."""

    def __init__(self, db: Session):
        self.db = db

    def query(
        self,
        *,
        workspace: Workspace,
        question: str,
        collection_or_scope: str | None = None,
        mode: str = "auto",
        filters: dict[str, Any] | None = None,
        system_id: str | None = None,
        document_profile_key: str | None = None,
        include_evidence: bool = True,
    ) -> dict[str, Any]:
        filters = filters or {}
        scope = self._resolve_scope(workspace, collection_or_scope)
        collections = self._resolve_collections(workspace, collection_or_scope, scope)
        system = self._resolve_system(workspace, system_id)
        profile = resolve_document_profile(
            workspace=workspace,
            scope=scope,
            system=system,
            request_profile_key=document_profile_key,
        )
        intent = _intent(question, mode)
        terms = _expand_terms(question, profile.profile)
        facts = self._load_facts(workspace, collections, filters, profile.profile)
        ranked = _rank_facts(facts, terms, question, intent)
        answer_payload, evidence, warnings = _compose_answer(intent, ranked, profile.profile)
        return {
            "intent": intent,
            "plan": {
                "intent": intent,
                "collections": collections,
                "terms": terms[:40],
                "filters": filters,
                "profile_source": profile.source,
                "scope": scope.get("key") if scope else None,
            },
            "answer_payload": answer_payload,
            "evidence_rows": [serialize_document_fact(row) for row in evidence] if include_evidence else [],
            "warnings": warnings,
            "effective_profile": {
                "key": profile.profile.get("key", "generic_document"),
                "label": profile.profile.get("label", "Generic document analysis"),
                "source": profile.source,
            },
        }

    def _resolve_scope(self, workspace: Workspace, collection_or_scope: str | None) -> dict[str, Any] | None:
        scopes = normalize_knowledge_scopes(_as_dict(workspace.settings).get("knowledge_scopes"))
        if not scopes:
            return None
        if collection_or_scope:
            return next((scope for scope in scopes if scope.get("key") == collection_or_scope), None)
        return select_scope(scopes, None, "documents")

    def _resolve_collections(self, workspace: Workspace, collection_or_scope: str | None, scope: dict[str, Any] | None) -> list[str]:
        if scope and (not collection_or_scope or collection_or_scope == scope.get("key")):
            return list(scope.get("collection_slugs") or [])
        if collection_or_scope:
            return [collection_or_scope]
        if scope:
            return list(scope.get("collection_slugs") or [])
        return []

    def _resolve_system(self, workspace: Workspace, system_id: str | None) -> System | None:
        if not system_id:
            return None
        return self.db.query(System).filter(System.workspace_id == workspace.id, System.id == system_id).first()

    def _load_facts(
        self,
        workspace: Workspace,
        collections: list[str],
        filters: dict[str, Any],
        profile: dict[str, Any],
    ) -> list[KnowledgeDocumentFact]:
        query = self.db.query(KnowledgeDocumentFact).filter(KnowledgeDocumentFact.workspace_id == workspace.id)
        if collections:
            query = query.filter(KnowledgeDocumentFact.collection_slug.in_(collections))
        if filters.get("semantic_type"):
            query = query.filter(KnowledgeDocumentFact.semantic_type == str(filters["semantic_type"]))
        if filters.get("predicate"):
            query = query.filter(KnowledgeDocumentFact.predicate == str(filters["predicate"]))
        if filters.get("document_filename"):
            query = query.filter(KnowledgeDocumentFact.document_filename.ilike(f"%{filters['document_filename']}%"))
        if filters.get("page") is not None:
            query = query.filter(KnowledgeDocumentFact.page == int(filters["page"]))
        limit = int(profile.get("max_candidate_facts") or GLOBAL_DOCUMENT_PROFILE["max_candidate_facts"])
        return query.limit(max(100, min(limit, 20000))).all()


def _intent(question: str, mode: str) -> str:
    explicit = (mode or "auto").strip().lower()
    if explicit in {"procedure", "parameter", "warning", "compare", "definition", "troubleshooting", "evidence_gap"}:
        return explicit
    if re.search(r"\b(compare|comparaison|diff[ée]rence|versus)\b", question, re.I):
        return "compare"
    if _WARNING_RE.search(question):
        return "warning"
    if re.search(r"\b(param[èe]tre|parameter|valeur|value|réglage|reglage|couple|torque|setting)\b", question, re.I):
        return "parameter"
    if _PROCEDURE_RE.search(question):
        return "procedure"
    if _DEFINITION_RE.search(question) or re.search(r"\b(d[ée]finition|definition|signifie|means)\b", question, re.I):
        return "definition"
    return "evidence_gap"


def _expand_terms(question: str, profile: dict[str, Any]) -> list[str]:
    terms = _tokens(question)
    expanded = list(terms)
    for key, aliases in _as_dict(profile.get("synonyms")).items():
        candidates = [key, *_as_list(aliases)]
        candidate_terms = {_normalize(item) for item in candidates}
        if any(token and token in " ".join(terms) for token in candidate_terms):
            for candidate in candidates:
                for token in _tokens(str(candidate)):
                    if token not in expanded:
                        expanded.append(token)
    return [term for term in expanded if term]


def _rank_facts(
    facts: list[KnowledgeDocumentFact],
    terms: list[str],
    question: str,
    intent: str,
) -> list[tuple[float, KnowledgeDocumentFact]]:
    normalized_question = _normalize(question)
    ranked: list[tuple[float, KnowledgeDocumentFact]] = []
    preferred_type = {
        "procedure": "document_procedure_step",
        "parameter": "document_parameter",
        "warning": "document_warning",
        "definition": "document_definition",
    }.get(intent)
    for fact in facts:
        haystack = _normalize(
            " ".join(
                str(value or "")
                for value in (
                    fact.content,
                    fact.document_filename,
                    fact.section_path,
                    fact.subject,
                    fact.predicate,
                    fact.value_raw,
                    fact.unit,
                    " ".join(fact.semantic_tags or []),
                )
            )
        )
        if not haystack:
            continue
        score = 0.0
        matched = False
        for term in terms:
            if not term:
                continue
            if _normalize(fact.subject) == term:
                score += 6.0
                matched = True
            elif re.search(rf"\b{re.escape(term)}\b", haystack):
                score += 2.0
                matched = True
            elif len(term) > 2 and term in haystack:
                score += 0.75
                matched = True
        if preferred_type and fact.semantic_type == preferred_type:
            score += 2.0
        if normalized_question and normalized_question in haystack:
            score += 3.0
        if matched or preferred_type == fact.semantic_type:
            ranked.append((score, fact))
    ranked.sort(key=lambda item: (item[0], item[1].confidence or 0.0), reverse=True)
    return ranked


def _compose_answer(
    intent: str,
    ranked: list[tuple[float, KnowledgeDocumentFact]],
    profile: dict[str, Any],
) -> tuple[dict[str, Any], list[KnowledgeDocumentFact], list[str]]:
    if not ranked:
        return {"status": "no_evidence", "kind": intent, "text": "No matching document facts were found."}, [], ["no_document_fact_match"]
    limit = int(profile.get("max_evidence_rows") or GLOBAL_DOCUMENT_PROFILE["max_evidence_rows"])
    evidence = [fact for _score, fact in ranked[:limit]]
    best = evidence[0]
    locator = []
    if best.page:
        locator.append(f"page {best.page}")
    if best.section_path:
        locator.append(best.section_path)
    text = best.content or best.value_raw or best.subject or "Document fact"
    if locator:
        text = f"{text} ({', '.join(locator)})"
    warnings: list[str] = []
    if len(evidence) > 1:
        warnings.append("multiple_candidate_document_facts")
    return {
        "status": "answered",
        "kind": intent,
        "text": text,
        "subject": best.subject,
        "predicate": best.predicate,
        "value": best.value_raw,
        "unit": best.unit,
        "page": best.page,
        "section_path": best.section_path,
    }, evidence, warnings


def should_run_document_analysis(question: str) -> bool:
    return bool(_DOC_QUERY_RE.search(question or ""))
