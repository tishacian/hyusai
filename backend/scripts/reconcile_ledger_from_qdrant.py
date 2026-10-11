"""Reconcile the Postgres per-document ledger from the Qdrant index.

Qdrant is the source of truth for what is actually indexed. Some ingestion
paths (``secure_deposit`` promotion, ``spl_wave_importer``) populate Qdrant +
``KnowledgeCollection.document_names`` but never wrote the per-document ledger
(``knowledge_collection_sources``), leaving the ledger empty or partial. The
corpus planner then falls back to ``document_names`` rows that carry no
``chunk_count`` and no ``project_code`` metadata, which degrades retrieval
scoping (e.g. the AKK200 pump regression).

This script rebuilds the ledger idempotently by aggregating Qdrant points per
``document_filename`` and upserting one ``KnowledgeCollectionSource`` row per
document, with the real chunk count and the project/source metadata read back
from the vectors.

Idempotency: upsert keys on ``(collection_id, normalized_name)`` via
``upsert_collection_source``; re-running only updates drifted ``chunk_count`` /
metadata. It never deletes rows.

Usage (inside the backend container):
    python -m scripts.reconcile_ledger_from_qdrant --workspace andritz            # dry-run (default)
    python -m scripts.reconcile_ledger_from_qdrant --workspace andritz --apply    # write
    python -m scripts.reconcile_ledger_from_qdrant --workspace andritz \
        --collection andritz-notices-techniques-spl-pilot --apply
"""
from __future__ import annotations

import argparse

from app.core.config import settings
from app.db.base import SessionLocal
from app.models.knowledge_collection import KnowledgeCollection, KnowledgeCollectionSource
from app.models.workspace import Workspace
from app.services.knowledge_collections import normalize_source_name, upsert_collection_source

# Payload fields pulled from Qdrant. Kept to a small, stable subset so the full
# scroll stays cheap (no vectors, no large text payloads).
_META_FIELDS = [
    "document_filename",
    "project_code",
    "archive_name",
    "source_family",
    "source_origin",
    "inner_document_path",
    "document_type",
    "extension",
    "file_size",
    "initial_buyer_code",
    "project_position",
    "project_reference_kind",
    "source_deposit_path",
]

# Metadata copied into KnowledgeCollectionSource.source_metadata. Excludes
# volatile/large fields (extension/file_size handled separately).
_META_COPY = (
    "project_code",
    "archive_name",
    "source_family",
    "source_origin",
    "inner_document_path",
    "document_type",
    "initial_buyer_code",
    "project_position",
    "project_reference_kind",
    "source_deposit_path",
)

_COMMIT_EVERY = 2000


def _client():
    from qdrant_client import QdrantClient

    return QdrantClient(
        host=settings.qdrant_host,
        port=settings.qdrant_port,
        api_key=settings.qdrant_api_key or None,
        https=settings.qdrant_https,
        timeout=settings.qdrant_timeout_seconds,
    )


def _resolve_collection(client, base: str) -> str:
    """Resolve the physical Qdrant collection for a logical alias base name."""
    try:
        if client.collection_exists(base):
            return base
    except Exception:
        pass
    try:
        for alias in client.get_aliases().aliases:
            if alias.alias_name == base:
                return alias.collection_name
    except Exception:
        pass
    cands = sorted(
        c.name for c in client.get_collections().collections if c.name.startswith(base + "__hybrid")
    )
    return cands[-1] if cands else base


def _aggregate(client, coll: str, batch: int = 2000):
    """Aggregate Qdrant points per document_filename -> [chunk_count, sample_meta]."""
    agg: dict[str, list] = {}
    next_offset = None
    scanned = 0
    while True:
        points, next_offset = client.scroll(
            collection_name=coll,
            limit=batch,
            offset=next_offset,
            with_payload=_META_FIELDS,
            with_vectors=False,
        )
        for point in points:
            payload = point.payload or {}
            filename = str(payload.get("document_filename") or "").strip()
            if not filename:
                continue
            entry = agg.get(filename)
            if entry is None:
                agg[filename] = [1, payload]
            else:
                entry[0] += 1
        scanned += len(points)
        if next_offset is None:
            break
    return agg, scanned


def _source_metadata(meta: dict) -> dict:
    out: dict = {}
    for key in _META_COPY:
        value = meta.get(key)
        if value not in (None, ""):
            out[str(key)] = value
    out["reconciled_from"] = "qdrant"
    return out


def _size(meta: dict):
    try:
        return int(meta.get("file_size"))
    except (TypeError, ValueError):
        return None


def reconcile_collection(db, client, collection: KnowledgeCollection, apply: bool) -> dict:
    base = collection.vector_collection_name
    coll = _resolve_collection(client, base)
    agg, scanned = _aggregate(client, coll)

    existing = {
        row.normalized_name: row
        for row in db.query(KnowledgeCollectionSource)
        .filter(KnowledgeCollectionSource.collection_id == collection.id)
        .all()
    }

    to_create = to_update = in_sync = 0
    qdrant_norms: set[str] = set()
    pending = 0
    for filename, (chunk_count, meta) in agg.items():
        norm = normalize_source_name(filename)
        qdrant_norms.add(norm)
        row = existing.get(norm)
        if row is None:
            to_create += 1
        elif int(row.chunk_count or 0) != chunk_count:
            to_update += 1
        else:
            in_sync += 1
        if apply:
            upsert_collection_source(
                db,
                collection=collection,
                filename=filename,
                status="ready",
                origin="qdrant_reconcile",
                size_bytes=_size(meta),
                chunk_count=chunk_count,
                source_metadata=_source_metadata(meta),
            )
            pending += 1
            if pending >= _COMMIT_EVERY:
                db.commit()
                pending = 0

    orphans = sum(1 for norm in existing if norm not in qdrant_norms)
    if apply and pending:
        db.commit()

    return {
        "collection": collection.slug,
        "qdrant_coll": coll,
        "scanned_chunks": scanned,
        "qdrant_docs": len(agg),
        "ledger_existing": len(existing),
        "to_create": to_create,
        "to_update": to_update,
        "in_sync": in_sync,
        "ledger_orphans": orphans,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", default="andritz", help="Workspace slug")
    parser.add_argument("--collection", default=None, help="Limit to a single collection slug")
    parser.add_argument("--apply", action="store_true", help="Write changes (default: dry-run)")
    args = parser.parse_args()

    db = SessionLocal()
    client = _client()
    try:
        workspace = db.query(Workspace).filter(Workspace.slug == args.workspace).first()
        if not workspace:
            raise SystemExit(f"workspace not found: {args.workspace}")
        query = db.query(KnowledgeCollection).filter(KnowledgeCollection.workspace_id == workspace.id)
        if args.collection:
            query = query.filter(KnowledgeCollection.slug == args.collection)
        collections = query.order_by(KnowledgeCollection.slug.asc()).all()

        mode = "APPLY" if args.apply else "DRY-RUN"
        print(f"=== ledger reconcile [{mode}] workspace={args.workspace} collections={len(collections)} ===")
        totals = {"to_create": 0, "to_update": 0, "in_sync": 0, "ledger_orphans": 0, "qdrant_docs": 0}
        for collection in collections:
            result = reconcile_collection(db, client, collection, args.apply)
            for key in totals:
                totals[key] += result[key]
            print(
                f"[{result['collection']}] qdrant_docs={result['qdrant_docs']} "
                f"chunks={result['scanned_chunks']} ledger_existing={result['ledger_existing']} "
                f"-> create={result['to_create']} update={result['to_update']} "
                f"in_sync={result['in_sync']} orphans={result['ledger_orphans']} "
                f"(coll={result['qdrant_coll']})"
            )
        print(
            f"=== TOTAL qdrant_docs={totals['qdrant_docs']} create={totals['to_create']} "
            f"update={totals['to_update']} in_sync={totals['in_sync']} "
            f"orphans={totals['ledger_orphans']} ==="
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
