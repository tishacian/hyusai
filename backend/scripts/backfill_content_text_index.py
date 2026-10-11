"""Backfill the Qdrant full-text index on ``content`` for retrieval collections.

The exhaustive inventory facet (``project_inventory``) filters chunk ``content``
with ``MatchText``. Without a full-text index that degrades to a full payload
scan (~44 s over 1.57 M points, under the 60 s timeout) and needs a
case-variant hack because the scan is case-sensitive. A text index turns the
scan into a sub-second inverted-index lookup and, with ``lowercase=True``, makes
matching case-insensitive (so the hack can be dropped).

Phase 1 (qdrant_db.py) creates this index lazily (``wait=False``) for *new*
collections. This one-off backfills *existing* collections: it builds the index
with ``wait=True`` and verifies ``get_collection(...).payload_schema`` reports
``content`` as a ``text`` index.

Index params are the single source of truth in
``app.services.vector_db.qdrant_db._content_text_index_schema`` (decided in the
rollout's Phase 0 measurement: multilingual tokenizer, min/max token len 2/30,
lowercase, on_disk).

Growth rule (Phase 0): ~1.65 GiB RAM and ~0.61 GB disk per 1 M points for this
index (~2.6 GiB RAM / ~0.95 GB disk at 1.57 M points). The dominant growth
constraint is the dense 1536-d vectors held in RAM (``on_disk=None``), NOT this
index; moving dense vectors ``on_disk`` is the future lever if the box saturates.
Monitor Qdrant RSS with ``docker stats`` during/after this backfill to confirm
it stays within the ~+2.6 GiB envelope.

The build runs on the live collection (Phase 0 validated headroom) and is fully
reversible via ``client.delete_payload_index(collection, "content")``.

Usage (inside the backend container):
    python -m scripts.backfill_content_text_index                 # dry-run, prefix andritz
    python -m scripts.backfill_content_text_index --apply
    python -m scripts.backfill_content_text_index --apply --collection <exact_name>
    python -m scripts.backfill_content_text_index --apply --prefix andritz
"""
from __future__ import annotations

import argparse
import time

from app.core.config import settings
from app.services.vector_db.qdrant_db import (
    _CONTENT_TEXT_INDEX_FIELD,
    _content_text_index_schema,
)

# Generous timeout: building a text index with wait=True on ~1.5 M points blocks
# the HTTP request until the build completes, well past the default 60 s.
_BUILD_TIMEOUT_SECONDS = 3600.0


def _client(timeout: float):
    from qdrant_client import QdrantClient

    return QdrantClient(
        host=settings.qdrant_host,
        port=settings.qdrant_port,
        api_key=settings.qdrant_api_key or None,
        https=settings.qdrant_https,
        timeout=timeout,
    )


def _is_retrieval_collection(name: str, prefix: str) -> bool:
    """Chat retrieval collections are ``<prefix>__*__hybrid_*``.

    ``*__metadata_v1_*`` / ``*__eval_*`` collections do not carry the ``content``
    used by chat, so they are skipped.
    """
    if not name.startswith(f"{prefix}__"):
        return False
    if "__hybrid_" not in name:
        return False
    if "__metadata_v1_" in name or "__eval_" in name:
        return False
    return True


def _content_schema_type(client, collection: str) -> str | None:
    """Return the payload schema data type of ``content`` (e.g. 'text'), or None."""
    info = client.get_collection(collection_name=collection)
    schema = getattr(info, "payload_schema", None) or {}
    entry = schema.get(_CONTENT_TEXT_INDEX_FIELD)
    if entry is None:
        return None
    data_type = getattr(entry, "data_type", entry)
    return str(getattr(data_type, "value", data_type)).lower()


def backfill_collection(client, collection: str, *, apply: bool) -> dict:
    started = time.time()
    before = _content_schema_type(client, collection)
    point_count = client.count(collection_name=collection, exact=True).count

    if not apply:
        return {
            "collection": collection,
            "points": point_count,
            "before": before,
            "after": before,
            "built": False,
            "ok": before == "text",
            "elapsed_s": 0.0,
        }

    schema = _content_text_index_schema()
    if schema is None:
        raise SystemExit("qdrant-client lacks TextIndexParams; cannot build text index")

    client.create_payload_index(
        collection_name=collection,
        field_name=_CONTENT_TEXT_INDEX_FIELD,
        field_schema=schema,
        wait=True,
    )
    after = _content_schema_type(client, collection)
    return {
        "collection": collection,
        "points": point_count,
        "before": before,
        "after": after,
        "built": True,
        "ok": after == "text",
        "elapsed_s": round(time.time() - started, 1),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", default="andritz", help="Workspace/collection name prefix")
    parser.add_argument("--collection", default=None, help="Limit to a single exact collection name")
    parser.add_argument("--apply", action="store_true", help="Build the index (default: dry-run)")
    parser.add_argument(
        "--timeout",
        type=float,
        default=_BUILD_TIMEOUT_SECONDS,
        help="Qdrant client timeout in seconds for the blocking build",
    )
    args = parser.parse_args()

    client = _client(args.timeout)
    all_names = sorted(c.name for c in client.get_collections().collections)
    if args.collection:
        targets = [args.collection] if args.collection in all_names else []
        if not targets:
            raise SystemExit(f"collection not found: {args.collection}")
    else:
        targets = [name for name in all_names if _is_retrieval_collection(name, args.prefix)]

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"=== content text index backfill [{mode}] prefix={args.prefix} collections={len(targets)} ===")
    if not targets:
        print("(no matching collections)")
        return

    all_ok = True
    for collection in targets:
        result = backfill_collection(client, collection, apply=args.apply)
        all_ok = all_ok and result["ok"]
        print(
            f"[{result['collection']}] points={result['points']} "
            f"before={result['before']} after={result['after']} "
            f"built={result['built']} ok={result['ok']} elapsed_s={result['elapsed_s']}"
        )
    print(f"=== DONE all_ok={all_ok} ===")
    if not all_ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
