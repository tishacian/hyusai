"""Provider-neutral table intelligence services.

The first production goal is modest and important: keep spreadsheet evidence
queryable outside vector top-k, so lookups and calculations can be exhaustive
and auditable. Domain interpretation stays in workspace profiles and Knowledge
Guides; this module only understands generic tables, cells, values and labels.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from statistics import mean
from typing import Any

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.knowledge_collection import KnowledgeCollection
from app.models.knowledge_table_fact import KnowledgeTableFact
from app.models.system import System
from app.models.workspace import Workspace
from app.services.object_store import get_object_store
from app.services.rag.knowledge_scopes import normalize_knowledge_scopes, select_scope

logger = get_logger(__name__)

GLOBAL_TABLE_PROFILE = {
    "key": "generic",
    "label": "Generic table analysis",
    "synonyms": {},
    "metric_aliases": {},
    "aggregation_policy": {
        "allow_mean": True,
        "require_compatible_units": True,
        "exclude_non_numeric": True,
    },
    "ambiguity_policy": "ask_when_metric_unclear",
    "evidence_policy": {
        "require_cell_citations": True,
        "show_excluded_values": True,
    },
    "max_candidate_facts": 5000,
    "max_evidence_rows": 50,
}

_WORD_RE = re.compile(r"[A-Za-zÀ-ÿ0-9][A-Za-zÀ-ÿ0-9_.-]*")
_AGGREGATE_RE = re.compile(r"\b(moyenne|average|mean|avg|somme|sum|total|min|max|count|nombre)\b", re.I)
_COMPARE_RE = re.compile(r"\b(compare|comparaison|diff[ée]rence|diff[ée]rent|plusieurs|global|tous|toutes)\b", re.I)
_LOOKUP_RE = re.compile(r"\b(valeur|value|label|libell[ée]|lettre|letter|cellule|cell|combien|quel|quelle)\b", re.I)
_EXPLAIN_RE = re.compile(r"\b(explique|explain|définition|definition|pourquoi|comment)\b", re.I)
_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "de",
    "des",
    "du",
    "en",
    "est",
    "et",
    "for",
    "in",
    "is",
    "la",
    "le",
    "les",
    "of",
    "on",
    "pour",
    "quelle",
    "quel",
    "sur",
    "the",
    "to",
    "un",
    "une",
}


@dataclass(frozen=True)
class EffectiveTableProfile:
    profile: dict[str, Any]
    source: str
    scope: dict[str, Any] | None = None


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


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


def _merged_profile(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = {**merged[key], **value}
        else:
            merged[key] = value
    return merged


def _workspace_table_profiles(workspace: Workspace) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    settings = _as_dict(workspace.settings)
    table_settings = _as_dict(settings.get("table_intelligence"))
    profiles = [p for p in _as_list(table_settings.get("profiles")) if isinstance(p, dict)]
    default_key = _safe_text(table_settings.get("default_profile"))
    return {"default_profile": default_key, **table_settings}, profiles


def resolve_table_profile(
    *,
    workspace: Workspace,
    scope: dict[str, Any] | None = None,
    system: System | None = None,
    request_profile_key: str | None = None,
    request_override: dict[str, Any] | None = None,
) -> EffectiveTableProfile:
    """Resolve the effective profile without hardcoding any domain terms."""
    table_settings, profiles = _workspace_table_profiles(workspace)
    by_key = {_safe_text(item.get("key")): item for item in profiles if _safe_text(item.get("key"))}

    system_settings = _as_dict(getattr(system, "settings", None))
    system_table = _as_dict(system_settings.get("table_intelligence"))
    key = (
        _safe_text(request_profile_key)
        or _safe_text(system_table.get("profile_key"))
        or _safe_text((scope or {}).get("table_profile_key"))
        or _safe_text(table_settings.get("default_profile"))
    )
    source = "global_default"
    selected = GLOBAL_TABLE_PROFILE
    if key and key in by_key:
        selected = _merged_profile(GLOBAL_TABLE_PROFILE, by_key[key])
        source = "workspace_profile"
    if system_table.get("override"):
        selected = _merged_profile(selected, _as_dict(system_table.get("override")))
        source = "system_override"
    if request_override:
        selected = _merged_profile(selected, request_override)
        source = "request_override"
    return EffectiveTableProfile(profile=selected, source=source, scope=scope)


def clear_collection_table_facts(db: Session, *, workspace_id: str, collection_id: str) -> int:
    deleted = (
        db.query(KnowledgeTableFact)
        .filter(KnowledgeTableFact.workspace_id == workspace_id, KnowledgeTableFact.collection_id == collection_id)
        .delete(synchronize_session=False)
    )
    return int(deleted or 0)


def replace_document_table_facts(
    db: Session,
    *,
    workspace: Workspace,
    collection: KnowledgeCollection,
    parsed_doc: Any,
) -> list[KnowledgeTableFact]:
    """Persist structured table facts for one parsed spreadsheet/CSV document."""
    if not parsed_doc or not getattr(parsed_doc, "structured_content", None):
        return []

    db.query(KnowledgeTableFact).filter(
        KnowledgeTableFact.workspace_id == workspace.id,
        KnowledgeTableFact.collection_id == collection.id,
        KnowledgeTableFact.document_id == getattr(parsed_doc, "id", None),
    ).delete(synchronize_session=False)

    artifact = _as_dict(parsed_doc.structured_content).get("table_artifacts")
    artifact = _as_dict(artifact)
    now = datetime.utcnow()
    rows: list[KnowledgeTableFact] = []
    for raw in _as_list(artifact.get("cell_facts")):
        if isinstance(raw, dict):
            rows.append(_fact_from_artifact(raw, "spreadsheet_cell_fact", workspace, collection, parsed_doc, now))
    for raw in _as_list(artifact.get("table_facts")):
        if isinstance(raw, dict):
            rows.append(_fact_from_artifact(raw, "spreadsheet_table_fact", workspace, collection, parsed_doc, now))

    if not rows:
        return []

    db.add_all(rows)
    _write_table_fact_jsonl(collection, parsed_doc, rows)
    return rows


def _fact_from_artifact(
    raw: dict[str, Any],
    semantic_type: str,
    workspace: Workspace,
    collection: KnowledgeCollection,
    parsed_doc: Any,
    now: datetime,
) -> KnowledgeTableFact:
    row_label = _safe_text(raw.get("row_label"))
    column_header = _safe_text(raw.get("column_header"))
    value_raw = _safe_text(raw.get("value") or raw.get("value_raw"))
    subject = column_header or row_label or _safe_text(raw.get("subject"))
    measure = row_label or column_header or _safe_text(raw.get("measure"))
    sheet = _safe_text(raw.get("sheet_name"))
    cell_ref = _safe_text(raw.get("cell_ref") or raw.get("value_cell"))
    content = _fact_content(
        sheet=sheet,
        row_index=raw.get("row_index"),
        row_label=row_label,
        column_header=column_header,
        value_raw=value_raw,
        unit=raw.get("unit"),
        cell_ref=cell_ref,
    )
    qualifiers = {
        key: value
        for key, value in raw.items()
        if key
        in {
            "label_cell",
            "value_cell",
            "formula",
            "table_region_id",
        }
        and value is not None
    }
    return KnowledgeTableFact(
        workspace_id=workspace.id,
        collection_id=collection.id,
        collection_slug=collection.slug,
        document_id=getattr(parsed_doc, "id", None),
        document_filename=getattr(parsed_doc, "filename", None),
        document_type=getattr(getattr(parsed_doc, "document_type", None), "value", None),
        source_path=_safe_text(_as_dict(getattr(parsed_doc, "metadata", {})).get("source_path") or getattr(parsed_doc, "file_path", "")),
        sheet_name=sheet or None,
        table_region_id=_safe_text(raw.get("table_region_id")) or None,
        semantic_type=semantic_type,
        row_index=_int_or_none(raw.get("row_index")),
        column_index=_int_or_none(raw.get("column_index")),
        cell_ref=cell_ref or None,
        cell_range=_safe_text(raw.get("cell_range")) or None,
        row_label=row_label or None,
        column_header=column_header or None,
        subject=subject or None,
        measure=measure or None,
        value_raw=value_raw or None,
        value_numeric=_parse_numeric(value_raw),
        unit=_safe_text(raw.get("unit")) or None,
        qualifiers=qualifiers,
        semantic_tags=_semantic_tags(row_label, column_header, sheet),
        confidence=0.8 if semantic_type == "spreadsheet_cell_fact" else 0.65,
        content=content,
        created_at=now,
        updated_at=now,
    )


def _fact_content(
    *,
    sheet: str,
    row_index: Any,
    row_label: str,
    column_header: str,
    value_raw: str,
    unit: Any,
    cell_ref: str,
) -> str:
    parts = [f"sheet={sheet}" if sheet else "", f"row={row_index}" if row_index else ""]
    if row_label:
        parts.append(f"row_label={row_label}")
    if column_header:
        parts.append(f"column_header={column_header}")
    if cell_ref:
        parts.append(f"cell={cell_ref}")
    if value_raw:
        parts.append(f"value={value_raw}")
    if unit:
        parts.append(f"unit={unit}")
    if row_label and value_raw:
        parts.append(f"{row_label} = {value_raw}")
    return " | ".join(part for part in parts if part)


def _semantic_tags(*values: str) -> list[str]:
    tags: list[str] = []
    for value in values:
        for token in _tokens(value):
            if token not in tags:
                tags.append(token)
    return tags[:32]


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _write_table_fact_jsonl(collection: KnowledgeCollection, parsed_doc: Any, rows: list[KnowledgeTableFact]) -> None:
    try:
        filename = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(getattr(parsed_doc, "filename", "table"))).strip("_")
        key = get_object_store().key(collection.artifact_prefix, "derived", "table_facts", f"{filename}.jsonl")
        payload = "\n".join(json.dumps(serialize_fact(row), ensure_ascii=False) for row in rows)
        get_object_store().write_text(key, payload + "\n")
    except Exception as exc:  # noqa: BLE001
        logger.warning("table_intelligence: failed to write JSONL artifact", error=str(exc))


def serialize_fact(fact: KnowledgeTableFact) -> dict[str, Any]:
    return {
        "id": fact.id,
        "collection_slug": fact.collection_slug,
        "document_id": fact.document_id,
        "document_filename": fact.document_filename,
        "document_type": fact.document_type,
        "source_path": fact.source_path,
        "sheet_name": fact.sheet_name,
        "table_region_id": fact.table_region_id,
        "semantic_type": fact.semantic_type,
        "row_index": fact.row_index,
        "column_index": fact.column_index,
        "cell_ref": fact.cell_ref,
        "cell_range": fact.cell_range,
        "row_label": fact.row_label,
        "column_header": fact.column_header,
        "subject": fact.subject,
        "measure": fact.measure,
        "value_raw": fact.value_raw,
        "value_numeric": fact.value_numeric,
        "unit": fact.unit,
        "qualifiers": fact.qualifiers or {},
        "semantic_tags": fact.semantic_tags or [],
        "confidence": fact.confidence,
        "content": fact.content,
    }


class TableQueryEngine:
    """Query structured table facts with an analytic, source-first contract."""

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
        table_profile_key: str | None = None,
        include_evidence: bool = True,
        allowed_collections: list[str] | None = None,
    ) -> dict[str, Any]:
        filters = filters or {}
        scope = self._resolve_scope(workspace, collection_or_scope)
        collections = self._resolve_collections(workspace, collection_or_scope, scope)
        if allowed_collections is not None:
            collections = [item for item in collections if item in allowed_collections] or ["__none__"]
        system = self._resolve_system(workspace, system_id)
        effective_profile = resolve_table_profile(
            workspace=workspace,
            scope=scope,
            system=system,
            request_profile_key=table_profile_key,
        )
        intent = _intent(question, mode)
        query_terms = _expand_terms(question, effective_profile.profile)
        facts = self._load_facts(workspace, collections, filters, effective_profile.profile)
        ranked = _rank_facts(facts, query_terms, question)
        plan = {
            "intent": intent,
            "collections": collections,
            "terms": query_terms[:40],
            "filters": filters,
            "profile_source": effective_profile.source,
            "scope": scope.get("key") if scope else None,
        }
        if intent == "aggregate":
            answer_payload, evidence, excluded, warnings = _compose_aggregate(ranked, effective_profile.profile)
        elif intent == "compare":
            answer_payload, evidence, excluded, warnings = _compose_compare(ranked, effective_profile.profile)
        else:
            answer_payload, evidence, excluded, warnings = _compose_lookup(ranked, effective_profile.profile)

        return {
            "intent": intent,
            "plan": plan,
            "answer_payload": answer_payload,
            "evidence_rows": [serialize_fact(row) for row in evidence] if include_evidence else [],
            "excluded_rows": excluded,
            "warnings": warnings,
            "effective_profile": {
                "key": effective_profile.profile.get("key", "generic"),
                "label": effective_profile.profile.get("label", "Generic table analysis"),
                "source": effective_profile.source,
            },
        }

    def _resolve_scope(self, workspace: Workspace, collection_or_scope: str | None) -> dict[str, Any] | None:
        settings = _as_dict(workspace.settings)
        scopes = normalize_knowledge_scopes(settings.get("knowledge_scopes"))
        if not scopes:
            return None
        if collection_or_scope:
            for scope in scopes:
                if scope.get("key") == collection_or_scope:
                    return scope
            return None
        return select_scope(scopes, None, "documents")

    def _resolve_collections(
        self,
        workspace: Workspace,
        collection_or_scope: str | None,
        scope: dict[str, Any] | None,
    ) -> list[str]:
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
        return (
            self.db.query(System)
            .filter(System.workspace_id == workspace.id, System.id == system_id)
            .first()
        )

    def _load_facts(
        self,
        workspace: Workspace,
        collections: list[str],
        filters: dict[str, Any],
        profile: dict[str, Any],
    ) -> list[KnowledgeTableFact]:
        query = self.db.query(KnowledgeTableFact).filter(KnowledgeTableFact.workspace_id == workspace.id)
        if collections:
            query = query.filter(KnowledgeTableFact.collection_slug.in_(collections))
        if filters.get("sheet_name"):
            query = query.filter(KnowledgeTableFact.sheet_name.ilike(f"%{filters['sheet_name']}%"))
        if filters.get("semantic_type"):
            query = query.filter(KnowledgeTableFact.semantic_type == str(filters["semantic_type"]))
        if filters.get("unit"):
            query = query.filter(KnowledgeTableFact.unit == str(filters["unit"]))
        if filters.get("document_filename"):
            query = query.filter(KnowledgeTableFact.document_filename.ilike(f"%{filters['document_filename']}%"))
        if filters.get("value_numeric_min") is not None:
            query = query.filter(KnowledgeTableFact.value_numeric >= float(filters["value_numeric_min"]))
        if filters.get("value_numeric_max") is not None:
            query = query.filter(KnowledgeTableFact.value_numeric <= float(filters["value_numeric_max"]))
        limit = int(profile.get("max_candidate_facts") or GLOBAL_TABLE_PROFILE["max_candidate_facts"])
        return query.limit(max(100, min(limit, 20000))).all()


def _intent(question: str, mode: str) -> str:
    explicit = (mode or "auto").strip().lower()
    if explicit in {"lookup", "filter", "compare", "aggregate", "enumerate", "explain", "evidence_gap"}:
        return explicit
    if _AGGREGATE_RE.search(question):
        return "aggregate"
    if _COMPARE_RE.search(question):
        return "compare"
    if _EXPLAIN_RE.search(question):
        return "explain"
    if _LOOKUP_RE.search(question):
        return "lookup"
    return "lookup"


def _expand_terms(question: str, profile: dict[str, Any]) -> list[str]:
    terms = _tokens(question)
    dictionaries = [_as_dict(profile.get("synonyms")), _as_dict(profile.get("metric_aliases"))]
    expanded = list(terms)
    for mapping in dictionaries:
        for key, aliases in mapping.items():
            alias_tokens = {_normalize(key), *(_normalize(item) for item in _as_list(aliases))}
            if any(token and token in " ".join(terms) for token in alias_tokens):
                for candidate in [key, *_as_list(aliases)]:
                    for token in _tokens(str(candidate)):
                        if token not in expanded:
                            expanded.append(token)
    return [term for term in expanded if term]


def _rank_facts(
    facts: list[KnowledgeTableFact],
    terms: list[str],
    question: str,
) -> list[tuple[float, KnowledgeTableFact]]:
    normalized_question = _normalize(question)
    ranked: list[tuple[float, KnowledgeTableFact]] = []
    for fact in facts:
        haystack = _normalize(
            " ".join(
                str(value or "")
                for value in (
                    fact.content,
                    fact.document_filename,
                    fact.sheet_name,
                    fact.row_label,
                    fact.column_header,
                    fact.subject,
                    fact.measure,
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
            if _normalize(fact.row_label) == term or _normalize(fact.column_header) == term:
                score += 8.0
                matched = True
            elif re.search(rf"\b{re.escape(term)}\b", haystack):
                score += 2.0
                matched = True
            elif len(term) > 2 and term in haystack:
                score += 0.75
                matched = True
        if matched and fact.value_numeric is not None:
            score += 0.25
        if matched and fact.semantic_type == "spreadsheet_cell_fact":
            score += 0.4
        if normalized_question and normalized_question in haystack:
            score += 4.0
        if score > 0:
            ranked.append((score, fact))
    ranked.sort(key=lambda item: (item[0], item[1].confidence or 0.0), reverse=True)
    return ranked


def _compose_lookup(
    ranked: list[tuple[float, KnowledgeTableFact]],
    profile: dict[str, Any],
) -> tuple[dict[str, Any], list[KnowledgeTableFact], list[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    if not ranked:
        return {"status": "no_evidence", "text": "No matching table facts were found."}, [], [], ["no_table_fact_match"]
    limit = int(profile.get("max_evidence_rows") or 50)
    evidence = [fact for _score, fact in ranked[:limit]]
    best = evidence[0]
    text = f"{best.measure or best.row_label or best.subject or 'Value'} = {best.value_raw}"
    if best.unit:
        text += f" {best.unit}"
    if best.sheet_name or best.cell_ref:
        text += f" ({best.sheet_name or 'sheet'}, {best.cell_ref or 'cell unknown'})"
    if len(evidence) > 1:
        warnings.append("multiple_candidate_facts")
    return {
        "status": "answered",
        "kind": "lookup",
        "text": text,
        "value": best.value_raw,
        "value_numeric": best.value_numeric,
        "unit": best.unit,
        "source_cell": best.cell_ref,
    }, evidence, [], warnings


def _compose_compare(
    ranked: list[tuple[float, KnowledgeTableFact]],
    profile: dict[str, Any],
) -> tuple[dict[str, Any], list[KnowledgeTableFact], list[dict[str, Any]], list[str]]:
    answer, evidence, excluded, warnings = _compose_lookup(ranked, profile)
    unique_values = []
    for fact in evidence:
        key = (fact.value_raw, fact.unit, fact.measure, fact.row_label)
        if key not in unique_values:
            unique_values.append(key)
    answer.update({"kind": "compare", "distinct_values": len(unique_values)})
    if len(unique_values) > 1:
        warnings.append("values_differ_across_evidence")
    else:
        warnings.append("single_value_in_retrieved_evidence_not_global_proof")
    return answer, evidence, excluded, warnings


def _compose_aggregate(
    ranked: list[tuple[float, KnowledgeTableFact]],
    profile: dict[str, Any],
) -> tuple[dict[str, Any], list[KnowledgeTableFact], list[dict[str, Any]], list[str]]:
    policy = _as_dict(profile.get("aggregation_policy"))
    allow_mean = policy.get("allow_mean", True)
    if not allow_mean:
        return {"status": "blocked", "kind": "aggregate", "text": "Mean aggregation is disabled by profile."}, [], [], ["mean_disabled"]

    evidence: list[KnowledgeTableFact] = []
    excluded: list[dict[str, Any]] = []
    units: set[str] = set()
    for _score, fact in ranked:
        if fact.value_numeric is None:
            excluded.append({"fact": serialize_fact(fact), "reason": "non_numeric"})
            continue
        if fact.unit:
            units.add(fact.unit)
        evidence.append(fact)
        if len(evidence) >= int(profile.get("max_evidence_rows") or 50):
            break

    warnings: list[str] = []
    if not evidence:
        return {"status": "no_numeric_evidence", "kind": "aggregate"}, [], excluded[:20], ["no_numeric_table_facts"]
    if policy.get("require_compatible_units", True) and len(units) > 1:
        return {
            "status": "unit_mismatch",
            "kind": "aggregate",
            "units": sorted(units),
            "text": "Cannot compute a global aggregate because units differ.",
        }, evidence, excluded[:20], ["unit_mismatch"]
    values = [float(fact.value_numeric) for fact in evidence if fact.value_numeric is not None]
    if len(values) < 2:
        warnings.append("single_numeric_value")
    return {
        "status": "answered",
        "kind": "aggregate",
        "operation": "mean",
        "mean": mean(values),
        "count": len(values),
        "min": min(values),
        "max": max(values),
        "unit": next(iter(units)) if len(units) == 1 else None,
        "text": f"Mean={mean(values):.4g} across {len(values)} value(s).",
    }, evidence, excluded[:20], warnings


def should_run_table_analysis(question: str) -> bool:
    return bool(_AGGREGATE_RE.search(question) or _LOOKUP_RE.search(question) or _COMPARE_RE.search(question))
