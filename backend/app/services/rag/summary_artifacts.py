"""Offline document/section summary artifacts for hierarchical retrieval."""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session as DBSession

from app.models.knowledge_collection import KnowledgeCollection, KnowledgeCollectionSource
from app.models.knowledge_document_fact import KnowledgeDocumentFact
from app.services.object_store import ObjectStore, get_object_store


SUMMARY_INDEX_VERSION = 1
SUMMARY_SAMPLE_LIMIT = 5
SUMMARY_TEXT_LIMIT = 1800
SUMMARY_INLINE_MAX_BYTES = 12_000_000
_TERM_RE = re.compile(r"[a-z0-9àâçéèêëîïôûùüÿñæœ_-]{3,}", re.IGNORECASE)


def summary_index_prefix(collection: KnowledgeCollection, *, store: ObjectStore | None = None) -> str:
    return (store or get_object_store()).key(collection.artifact_prefix, "derived", "summary_index")


def summary_index_jsonl_key(collection: KnowledgeCollection, *, store: ObjectStore | None = None) -> str:
    return (store or get_object_store()).key(summary_index_prefix(collection, store=store), "documents.jsonl")


def summary_index_manifest_key(collection: KnowledgeCollection, *, store: ObjectStore | None = None) -> str:
    return (store or get_object_store()).key(summary_index_prefix(collection, store=store), "manifest.json")


def _metadata_value(meta: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = meta.get(key)
        if value not in (None, ""):
            return str(value)
    return None


def _source_record(source: KnowledgeCollectionSource, collection: KnowledgeCollection) -> dict[str, Any]:
    meta = dict(source.source_metadata or {})
    return {
        "collection_id": collection.id,
        "collection_slug": collection.slug,
        "document_id": _metadata_value(meta, "document_id", "id"),
        "document_filename": source.filename,
        "source_kind": source.source_kind,
        "extension": source.extension,
        "status": source.status,
        "chunk_count": int(source.chunk_count or 0),
        "project_code": _metadata_value(meta, "project_code", "project", "machine", "line"),
        "machine": _metadata_value(meta, "machine", "equipment", "model"),
        "family": _metadata_value(meta, "family", "product_family", "line_family"),
        "section": _metadata_value(meta, "section"),
        "section_path": _metadata_value(meta, "section_path"),
        "chapter": _metadata_value(meta, "chapter"),
        "part_number": _metadata_value(meta, "part_number", "part_no", "reference"),
        "archive_name": _metadata_value(meta, "archive_name", "archive"),
        "language": _metadata_value(meta, "language", "lang"),
        "fact_count": 0,
        "facts_by_type": {},
        "sections": [],
        "sample_facts": [],
        "summary_text": "",
        "embedding_status": "not_embedded",
    }


def _record_key(record: dict[str, Any]) -> str:
    return str(record.get("document_id") or record.get("document_filename") or "")


def _fact_key(fact: KnowledgeDocumentFact) -> str:
    return str(fact.document_id or fact.document_filename or fact.id)


def _add_fact(record: dict[str, Any], fact: KnowledgeDocumentFact) -> None:
    semantic_type = str(fact.semantic_type or "fact")
    record["fact_count"] = int(record.get("fact_count") or 0) + 1
    by_type = dict(record.get("facts_by_type") or {})
    by_type[semantic_type] = int(by_type.get(semantic_type) or 0) + 1
    record["facts_by_type"] = by_type
    section = str(fact.section_path or "").strip()
    if section:
        sections = list(record.get("sections") or [])
        if section not in sections and len(sections) < 20:
            sections.append(section)
        record["sections"] = sections
    samples = list(record.get("sample_facts") or [])
    if len(samples) < SUMMARY_SAMPLE_LIMIT:
        samples.append(
            {
                "semantic_type": semantic_type,
                "subject": fact.subject,
                "predicate": fact.predicate,
                "value_raw": fact.value_raw,
                "page": fact.page,
                "section_path": fact.section_path,
                "content": str(fact.content or fact.value_raw or fact.subject or "")[:500],
            }
        )
        record["sample_facts"] = samples


def _summary_text(record: dict[str, Any]) -> str:
    title = str(record.get("document_filename") or record.get("document_id") or "document")
    chunks = int(record.get("chunk_count") or 0)
    kind = str(record.get("source_kind") or "document")
    parts = [f"Document summary: {title} ({kind}, {chunks} chunks)."]
    project = record.get("project_code")
    archive = record.get("archive_name")
    if project or archive:
        parts.append(f"Scope metadata: project={project or '-'} archive={archive or '-'}.")
    industrial = [
        f"{key}={record.get(key)}"
        for key in ("machine", "family", "section", "chapter", "part_number")
        if record.get(key)
    ]
    if industrial:
        parts.append("Industrial metadata: " + " ".join(industrial) + ".")
    facts_by_type = record.get("facts_by_type") or {}
    if facts_by_type:
        ordered = sorted(facts_by_type.items(), key=lambda item: (-int(item[1]), str(item[0])))
        parts.append("Fact coverage: " + ", ".join(f"{key}={value}" for key, value in ordered[:8]) + ".")
    sections = record.get("sections") or []
    if sections:
        parts.append("Sections: " + " | ".join(str(section) for section in sections[:8]) + ".")
    samples = record.get("sample_facts") or []
    if samples:
        sample_text = []
        for sample in samples[:SUMMARY_SAMPLE_LIMIT]:
            content = str(sample.get("content") or "").strip()
            if content:
                sample_text.append(f"{sample.get('semantic_type')}: {content}")
        if sample_text:
            parts.append("Representative facts: " + " ".join(sample_text))
    else:
        parts.append("No structured document facts are available for this source yet.")
    return " ".join(parts)[:SUMMARY_TEXT_LIMIT]


def _filter_matches(record: dict[str, Any], filters: dict[str, Any]) -> bool:
    for key, expected in (filters or {}).items():
        if expected in (None, "", []):
            continue
        actual = record.get("collection_slug") if key == "collection" else record.get(key)
        if isinstance(expected, (list, tuple, set)):
            values = {str(item) for item in expected if item not in (None, "")}
            if values and str(actual) not in values:
                return False
        elif str(actual) != str(expected):
            return False
    return True


def _query_terms(query: str) -> list[str]:
    terms: list[str] = []
    for raw in _TERM_RE.findall(str(query or "").lower()):
        token = raw.strip("_-")
        if len(token) >= 3 and token not in terms:
            terms.append(token)
    return terms[:12]


def _summary_score(record: dict[str, Any], terms: list[str]) -> float:
    if not terms:
        return float(record.get("fact_count") or 0)
    haystack = " ".join(
        str(value or "")
        for value in (
            record.get("document_filename"),
            record.get("document_id"),
            record.get("project_code"),
            record.get("archive_name"),
            record.get("summary_text"),
            " ".join(record.get("sections") or []),
        )
    ).lower()
    score = 0.0
    for term in terms:
        if term in haystack:
            score += 1.0
        if term and term in str(record.get("document_filename") or "").lower():
            score += 1.5
    score += min(float(record.get("fact_count") or 0), 10.0) / 20.0
    return score


def load_summary_index_records(
    *,
    collection: KnowledgeCollection,
    query: str,
    filters: dict[str, Any] | None = None,
    limit: int = 4,
    store: ObjectStore | None = None,
    max_bytes: int = SUMMARY_INLINE_MAX_BYTES,
) -> dict[str, Any]:
    """Load a small, ranked slice of a summary sidecar for online retrieval."""
    store = store or get_object_store()
    manifest_key = summary_index_manifest_key(collection, store=store)
    jsonl_key = summary_index_jsonl_key(collection, store=store)
    if not store.exists(manifest_key) or not store.exists(jsonl_key):
        return {"status": "missing", "records": [], "manifest_path": manifest_key, "jsonl_path": jsonl_key}
    size = store.size(jsonl_key) or 0
    if max_bytes > 0 and size > max_bytes:
        return {
            "status": "skipped",
            "reason": "summary_artifact_too_large_for_inline",
            "records": [],
            "manifest_path": manifest_key,
            "jsonl_path": jsonl_key,
            "size_bytes": size,
            "max_bytes": max_bytes,
        }
    try:
        manifest = json.loads(store.read_bytes(manifest_key).decode("utf-8"))
    except Exception:
        manifest = {}
    terms = _query_terms(query)
    candidates: list[tuple[float, dict[str, Any]]] = []
    scanned = 0
    raw = store.read_bytes(jsonl_key).decode("utf-8")
    for line in raw.splitlines():
        if not line.strip():
            continue
        scanned += 1
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict):
            continue
        if not _filter_matches(record, filters or {}):
            continue
        score = _summary_score(record, terms)
        if score <= 0 and terms:
            continue
        candidates.append((score, record))
    candidates.sort(key=lambda item: (-item[0], str(item[1].get("document_filename") or "")))
    return {
        "status": "ready",
        "records": [record for _score, record in candidates[: max(1, int(limit or 1))]],
        "scanned": scanned,
        "matched": len(candidates),
        "manifest": manifest,
        "manifest_path": manifest_key,
        "jsonl_path": jsonl_key,
        "size_bytes": size,
    }


def rebuild_summary_index_artifact(
    *,
    db: DBSession,
    collection: KnowledgeCollection,
    store: ObjectStore | None = None,
) -> dict[str, Any]:
    """Build a deterministic document-level summary sidecar from ledger + facts.

    This is intentionally not an LLM summarizer. It gives dense collections a
    cheap coarse layer that can be embedded/reindexed later, while remaining
    safe to run as a manual offline job today.
    """
    store = store or get_object_store()
    records: dict[str, dict[str, Any]] = {}
    filename_index: dict[str, str] = {}
    document_id_index: dict[str, str] = {}

    sources = (
        db.query(KnowledgeCollectionSource)
        .filter(
            KnowledgeCollectionSource.collection_id == collection.id,
            KnowledgeCollectionSource.status != "deleted",
        )
        .order_by(KnowledgeCollectionSource.filename.asc())
        .yield_per(500)
    )
    source_count = 0
    for source in sources:
        record = _source_record(source, collection)
        key = _record_key(record)
        if not key:
            continue
        records[key] = record
        source_count += 1
        filename = str(record.get("document_filename") or "")
        document_id = str(record.get("document_id") or "")
        if filename:
            filename_index[filename] = key
        if document_id:
            document_id_index[document_id] = key

    facts = (
        db.query(KnowledgeDocumentFact)
        .filter(KnowledgeDocumentFact.collection_id == collection.id)
        .order_by(KnowledgeDocumentFact.document_filename.asc(), KnowledgeDocumentFact.updated_at.desc())
        .yield_per(1000)
    )
    fact_count = 0
    for fact in facts:
        key = None
        if fact.document_id:
            key = document_id_index.get(str(fact.document_id))
        if key is None and fact.document_filename:
            key = filename_index.get(str(fact.document_filename))
        if key is None:
            key = _fact_key(fact)
            records.setdefault(
                key,
                {
                    "collection_id": collection.id,
                    "collection_slug": collection.slug,
                    "document_id": fact.document_id,
                    "document_filename": fact.document_filename,
                    "source_kind": fact.document_type or "document",
                    "extension": "",
                    "status": "fact_only",
                    "chunk_count": 0,
                    "project_code": None,
                    "machine": None,
                    "family": None,
                    "section": None,
                    "section_path": fact.section_path,
                    "chapter": None,
                    "part_number": None,
                    "archive_name": None,
                    "language": None,
                    "fact_count": 0,
                    "facts_by_type": {},
                    "sections": [],
                    "sample_facts": [],
                    "summary_text": "",
                    "embedding_status": "not_embedded",
                },
            )
        _add_fact(records[key], fact)
        fact_count += 1

    ordered_records = sorted(records.values(), key=lambda item: str(item.get("document_filename") or item.get("document_id") or ""))
    for record in ordered_records:
        record["summary_text"] = _summary_text(record)

    jsonl_key = summary_index_jsonl_key(collection, store=store)
    manifest_key = summary_index_manifest_key(collection, store=store)
    jsonl = "\n".join(json.dumps(record, ensure_ascii=False, sort_keys=True) for record in ordered_records)
    if jsonl:
        jsonl += "\n"
    store.write_text(jsonl_key, jsonl)
    manifest = {
        "status": "ready",
        "version": SUMMARY_INDEX_VERSION,
        "collection_id": collection.id,
        "collection_slug": collection.slug,
        "created_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "source_count": source_count,
        "document_summaries": len(ordered_records),
        "fact_count": fact_count,
        "jsonl_path": jsonl_key,
        "embedding_status": "not_embedded",
    }
    store.write_text(manifest_key, json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2))
    return {
        **manifest,
        "manifest_path": manifest_key,
    }
