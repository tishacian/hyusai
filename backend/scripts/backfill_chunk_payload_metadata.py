"""Backfill chunk payloads (project_code, machine, wave_id, content_sha256).

Collections ingested before the manifest→chunk propagation carried these
fields have untagged Qdrant payloads, which keeps the cross-project filter in
log-only mode. This script pushes the per-document metadata from the
collection manifest + source ledger onto the existing points via
``set_payload`` — no re-parse, no re-embedding.

    cd backend
    python -m scripts.backfill_chunk_payload_metadata --workspace andritz [--collection slug] [--dry-run]

Idempotent: payload keys already present are overwritten with the same values.
"""
from __future__ import annotations

import argparse

from app.db.base import SessionLocal
from app.models.knowledge_collection import KnowledgeCollection, KnowledgeCollectionSource
from app.models.workspace import Workspace
from app.services.knowledge_collections import document_manifest_key
from app.services.object_store import get_object_store
from app.services.vector_db.factory import VectorDBFactory

_BACKFILL_KEYS = ("project_code", "machine", "wave_id", "content_sha256", "source_family", "archive_name")


def _manifest(collection: KnowledgeCollection) -> dict[str, dict]:
    import json

    store = get_object_store()
    key = document_manifest_key(collection)
    if not store.exists(key):
        return {}
    try:
        payload = json.loads(store.read_bytes(key).decode("utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    return {str(k): dict(v) for k, v in payload.items() if isinstance(v, dict)} if isinstance(payload, dict) else {}


def _backfill_collection(db, workspace: Workspace, collection: KnowledgeCollection, *, dry_run: bool) -> int:
    manifest = _manifest(collection)
    sources = (
        db.query(KnowledgeCollectionSource)
        .filter(KnowledgeCollectionSource.collection_id == collection.id)
        .all()
    )
    by_name: dict[str, dict] = {}
    for name, metadata in manifest.items():
        by_name[name] = dict(metadata)
    for row in sources:
        merged = by_name.setdefault(row.filename, {})
        for key, value in (row.source_metadata or {}).items():
            merged.setdefault(key, value)

    vector_db = VectorDBFactory.get_db(collection.slug, workspace_slug=workspace.slug)
    client = getattr(vector_db, "client", None)
    qdrant_collection = getattr(vector_db, "collection_name", None)
    if client is None or not qdrant_collection:
        print(f"skip collection={collection.slug}: no qdrant client")
        return 0

    from qdrant_client import models as qmodels

    updated = 0
    for filename, metadata in by_name.items():
        payload = {key: metadata[key] for key in _BACKFILL_KEYS if metadata.get(key)}
        if not payload:
            continue
        print(f"backfill collection={collection.slug} document={filename} keys={sorted(payload)}")
        if dry_run:
            updated += 1
            continue
        client.set_payload(
            collection_name=qdrant_collection,
            payload=payload,
            points=qmodels.Filter(
                must=[
                    qmodels.FieldCondition(
                        key="document_filename",
                        match=qmodels.MatchValue(value=filename),
                    )
                ]
            ),
        )
        updated += 1
    return updated


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True, help="Workspace slug")
    parser.add_argument("--collection", default=None, help="Only this collection slug")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        workspace = db.query(Workspace).filter(Workspace.slug == args.workspace).first()
        if not workspace:
            raise SystemExit(f"Workspace not found: {args.workspace}")
        query = db.query(KnowledgeCollection).filter(KnowledgeCollection.workspace_id == workspace.id)
        if args.collection:
            query = query.filter(KnowledgeCollection.slug == args.collection)
        total = 0
        for collection in query.all():
            total += _backfill_collection(db, workspace, collection, dry_run=args.dry_run)
        print(f"done documents_backfilled={total} dry_run={args.dry_run}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
