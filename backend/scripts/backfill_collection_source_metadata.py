"""Backfill Knowledge source metadata from the stored document manifest.

Usage:
    poetry run python scripts/backfill_collection_source_metadata.py \
        --workspace andritz --collection andritz-notices-techniques-spl-pilot --dry-run
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

def _load_manifest(collection: Any, *, document_manifest_key: Any, get_object_store: Any) -> dict[str, dict[str, Any]]:
    store = get_object_store()
    key = document_manifest_key(collection)
    if not store.exists(key):
        return {}
    payload = json.loads(store.read_bytes(key).decode("utf-8"))
    if not isinstance(payload, dict):
        return {}
    return {
        str(name): dict(metadata)
        for name, metadata in payload.items()
        if isinstance(metadata, dict)
    }


def _merge_metadata(current: dict[str, Any] | None, manifest: dict[str, Any]) -> dict[str, Any]:
    merged = dict(current or {})
    for key, value in manifest.items():
        if value is None:
            continue
        if merged.get(key) in (None, "", [], {}):
            merged[key] = value
        elif key not in merged:
            merged[key] = value
    return merged


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True, help="Workspace slug")
    parser.add_argument("--collection", required=True, help="Knowledge collection slug")
    parser.add_argument("--dry-run", action="store_true", help="Report changes without committing")
    args = parser.parse_args()

    from app.db.base import SessionLocal
    from app.models.knowledge_collection import KnowledgeCollection, KnowledgeCollectionSource
    from app.models.workspace import Workspace
    from app.services.knowledge_collections import document_manifest_key
    from app.services.object_store import get_object_store

    db = SessionLocal()
    try:
        workspace = db.query(Workspace).filter(Workspace.slug == args.workspace).one()
        collection = (
            db.query(KnowledgeCollection)
            .filter(
                KnowledgeCollection.workspace_id == workspace.id,
                KnowledgeCollection.slug == args.collection,
            )
            .one()
        )
        manifest = _load_manifest(
            collection,
            document_manifest_key=document_manifest_key,
            get_object_store=get_object_store,
        )
        if not manifest:
            print(json.dumps({"status": "no_manifest", "updated": 0}, indent=2))
            return

        rows = (
            db.query(KnowledgeCollectionSource)
            .filter(KnowledgeCollectionSource.collection_id == collection.id)
            .all()
        )
        updated = 0
        matched = 0
        sample: list[dict[str, Any]] = []
        for row in rows:
            metadata = manifest.get(row.filename)
            if not metadata:
                continue
            matched += 1
            merged = _merge_metadata(row.source_metadata, metadata)
            if merged == (row.source_metadata or {}):
                continue
            updated += 1
            if len(sample) < 10:
                sample.append(
                    {
                        "filename": row.filename,
                        "added_keys": sorted(set(merged) - set(row.source_metadata or {})),
                    }
                )
            if not args.dry_run:
                row.source_metadata = merged

        if args.dry_run:
            db.rollback()
        else:
            db.commit()

        print(
            json.dumps(
                {
                    "status": "dry_run" if args.dry_run else "updated",
                    "workspace": workspace.slug,
                    "collection": collection.slug,
                    "manifest_entries": len(manifest),
                    "source_rows": len(rows),
                    "matched_rows": matched,
                    "updated_rows": updated,
                    "sample": sample,
                },
                indent=2,
                sort_keys=True,
            )
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
