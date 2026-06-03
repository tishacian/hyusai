"""Offline OpenSearch sparse index rebuilds for hierarchical retrieval."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from typing import Any

import httpx
from sqlalchemy.orm import Session as DBSession

from app.core.config import settings
from app.models.knowledge_collection import KnowledgeCollection
from app.services.object_store import ObjectStore, get_object_store
from app.services.rag.summary_artifacts import (
    rebuild_summary_index_artifact,
    summary_index_jsonl_key,
    summary_index_manifest_key,
)

SPARSE_INDEX_VERSION = 1
DEFAULT_BULK_BATCH_SIZE = 500


def opensearch_sparse_index_name(collection_slug: str, *, index_prefix: str | None = None) -> str:
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in str(collection_slug or "").lower())
    return f"{index_prefix or settings.rag_opensearch_index_prefix}-{safe}"


def _load_summary_records(
    *,
    db: DBSession,
    collection: KnowledgeCollection,
    store: ObjectStore,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    manifest_key = summary_index_manifest_key(collection, store=store)
    jsonl_key = summary_index_jsonl_key(collection, store=store)
    if not store.exists(manifest_key) or not store.exists(jsonl_key):
        manifest = rebuild_summary_index_artifact(db=db, collection=collection, store=store)
    else:
        try:
            manifest = json.loads(store.read_bytes(manifest_key).decode("utf-8"))
        except json.JSONDecodeError:
            manifest = rebuild_summary_index_artifact(db=db, collection=collection, store=store)

    rows: list[dict[str, Any]] = []
    for line in store.read_bytes(jsonl_key).decode("utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return manifest, rows


def _doc_id(collection: KnowledgeCollection, row: dict[str, Any]) -> str:
    raw = "|".join(
        str(value or "")
        for value in (
            collection.slug,
            row.get("document_id"),
            row.get("document_filename"),
        )
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _index_document(collection: KnowledgeCollection, row: dict[str, Any]) -> dict[str, Any]:
    metadata_keys = (
        "collection_id",
        "collection_slug",
        "document_id",
        "document_filename",
        "source_kind",
        "extension",
        "status",
        "project_code",
        "archive_name",
        "language",
        "chunk_count",
        "fact_count",
        "facts_by_type",
        "sections",
    )
    metadata = {key: row.get(key) for key in metadata_keys if row.get(key) not in (None, "")}
    return {
        "collection": collection.slug,
        "content": row.get("summary_text") or "",
        "title": row.get("document_filename") or row.get("document_id") or collection.slug,
        "document_id": row.get("document_id"),
        "document_filename": row.get("document_filename"),
        "source_kind": row.get("source_kind"),
        "extension": row.get("extension"),
        "status": row.get("status"),
        "project_code": row.get("project_code"),
        "archive_name": row.get("archive_name"),
        "language": row.get("language"),
        "chunk_count": int(row.get("chunk_count") or 0),
        "fact_count": int(row.get("fact_count") or 0),
        "metadata": {
            **metadata,
            "retrieval_artifact": "summary_sparse",
            "sparse_index_version": SPARSE_INDEX_VERSION,
        },
    }


def _chunks(items: list[dict[str, Any]], batch_size: int) -> Iterable[list[dict[str, Any]]]:
    size = max(1, int(batch_size or DEFAULT_BULK_BATCH_SIZE))
    for offset in range(0, len(items), size):
        yield items[offset : offset + size]


def _index_mapping() -> dict[str, Any]:
    keyword = {"type": "keyword", "ignore_above": 512}
    return {
        "mappings": {
            "properties": {
                "collection": keyword,
                "content": {"type": "text"},
                "title": {"type": "text", "fields": {"keyword": keyword}},
                "document_id": keyword,
                "document_filename": {"type": "text", "fields": {"keyword": keyword}},
                "source_kind": keyword,
                "extension": keyword,
                "status": keyword,
                "project_code": keyword,
                "archive_name": keyword,
                "language": keyword,
                "chunk_count": {"type": "integer"},
                "fact_count": {"type": "integer"},
                "metadata": {"type": "object", "enabled": True},
            }
        }
    }


def _ensure_index(client: httpx.Client, *, base_url: str, index_name: str) -> None:
    response = client.put(f"{base_url.rstrip('/')}/{index_name}", json=_index_mapping())
    if response.status_code == 400:
        try:
            payload = response.json()
        except Exception:  # noqa: BLE001
            payload = {}
        error_type = ((payload.get("error") or {}).get("type") or "").lower()
        if error_type == "resource_already_exists_exception":
            return
    response.raise_for_status()


def _delete_collection_docs(
    client: httpx.Client,
    *,
    base_url: str,
    index_name: str,
    collection_slug: str,
) -> None:
    response = client.post(
        f"{base_url.rstrip('/')}/{index_name}/_delete_by_query?conflicts=proceed&refresh=true",
        json={"query": {"term": {"collection": collection_slug}}},
    )
    response.raise_for_status()


def _bulk_payload(collection: KnowledgeCollection, index_name: str, rows: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for row in rows:
        lines.append(json.dumps({"index": {"_index": index_name, "_id": _doc_id(collection, row)}}, sort_keys=True))
        lines.append(json.dumps(_index_document(collection, row), ensure_ascii=False, sort_keys=True))
    return "\n".join(lines) + "\n"


def rebuild_opensearch_sparse_index(
    *,
    db: DBSession,
    collection: KnowledgeCollection,
    store: ObjectStore | None = None,
    batch_size: int = DEFAULT_BULK_BATCH_SIZE,
) -> dict[str, Any]:
    """Index document-summary artifacts into OpenSearch BM25.

    This is intentionally offline/manual. It gives HAH/CHAH a sparse coarse
    layer without any runtime BM25 warmup against the full Qdrant collection.
    """
    if str(settings.rag_sparse_backend or "").strip().lower() != "opensearch":
        return {
            "status": "skipped",
            "configured": False,
            "reason": "sparse_backend_not_opensearch",
            "backend": settings.rag_sparse_backend or "disabled",
        }
    if not settings.rag_opensearch_url:
        return {
            "status": "skipped",
            "configured": False,
            "reason": "opensearch_unconfigured",
            "backend": "opensearch",
        }

    store = store or get_object_store()
    manifest, rows = _load_summary_records(db=db, collection=collection, store=store)
    rows = [row for row in rows if str(row.get("summary_text") or "").strip()]
    if not rows:
        return {
            "status": "skipped",
            "configured": True,
            "reason": "no_summary_records",
            "backend": "opensearch",
            "summary_index": manifest,
        }

    index_name = opensearch_sparse_index_name(collection.slug)
    timeout = max(5.0, min(float(settings.rag_deep_retrieval_deadline_seconds or 120.0), 120.0))
    base_url = str(settings.rag_opensearch_url).rstrip("/")
    indexed = 0
    batches = 0
    with httpx.Client(timeout=timeout) as client:
        _ensure_index(client, base_url=base_url, index_name=index_name)
        _delete_collection_docs(client, base_url=base_url, index_name=index_name, collection_slug=collection.slug)
        for batch in _chunks(rows, batch_size):
            payload = _bulk_payload(collection, index_name, batch)
            response = client.post(
                f"{base_url}/{index_name}/_bulk?refresh=true",
                content=payload,
                headers={"Content-Type": "application/x-ndjson"},
            )
            response.raise_for_status()
            data = response.json()
            if data.get("errors"):
                raise RuntimeError(f"OpenSearch sparse bulk indexing reported errors for {index_name}")
            indexed += len(batch)
            batches += 1

    return {
        "status": "ready",
        "configured": True,
        "backend": "opensearch",
        "index_name": index_name,
        "documents_indexed": indexed,
        "batches": batches,
        "version": SPARSE_INDEX_VERSION,
        "summary_index": manifest,
        "jsonl_path": summary_index_jsonl_key(collection, store=store),
        "manifest_path": summary_index_manifest_key(collection, store=store),
    }
