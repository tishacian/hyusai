"""READ-ONLY reconciliation between the Postgres source ledger and Qdrant.

For each Knowledge collection of a target workspace (default ``andritz``), this
script compares:

* PG side: ``KnowledgeCollectionSource`` rows grouped by collection, with
  per-document ``status`` and ``chunk_count``.
* Qdrant side: the matching physical Qdrant collection, scrolled and aggregated
  into the set of distinct ``document_id`` (and ``document_filename``) actually
  present, plus a per-document vector/chunk count.

The two sides are joined on ``document_id`` (fallback ``document_filename``) and
each PG source is classified into one of:

* ``present_ok``               - in Qdrant, counts roughly match.
* ``present_count_mismatch``   - in Qdrant but PG chunk_count vs Qdrant vector
                                 count diverge significantly.
* ``missing_in_qdrant``        - PG status in {ready, indexed} but 0 vectors in
                                 Qdrant => THE GAP.
* ``deduplicated``             - PG status ``deduplicated`` (expected, NOT a gap).
* ``error``                    - PG status ``error``.
* ``never_enqueued``           - PG status ``queued`` (never queued / pending).
* ``other``                    - any remaining status (e.g. deleted, ingesting).

The script is strictly READ-ONLY: it only issues SELECT queries against PG and
``scroll``/``get_collections`` against Qdrant. Nothing is written, re-ingested or
mutated.

Configuration is read from ``os.environ`` (no argv, runs over stdin):

* ``RECON_WORKSPACE``        workspace slug to target (default ``andritz``).
* ``RECON_WORKSPACE_ID``     optional explicit workspace id (overrides slug).
* ``RECON_SCROLL_LIMIT``     points per scroll page (default 2000).
* ``RECON_MAX_POINTS``       per-collection scroll cap, 0 = unlimited (default 0).
* ``RECON_MISMATCH_RATIO``   relative divergence threshold (default 0.25).
"""

from __future__ import annotations

import os
import sys
from collections import defaultdict
from typing import Dict, Optional, Tuple


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
def _cfg() -> dict:
    return {
        "workspace_slug": os.environ.get("RECON_WORKSPACE", "andritz").strip(),
        "workspace_id": (os.environ.get("RECON_WORKSPACE_ID") or "").strip() or None,
        "scroll_limit": int(os.environ.get("RECON_SCROLL_LIMIT", "2000")),
        "max_points": int(os.environ.get("RECON_MAX_POINTS", "0")),
        "mismatch_ratio": float(os.environ.get("RECON_MISMATCH_RATIO", "0.25")),
    }


# --------------------------------------------------------------------------- #
# Workspace resolution
# --------------------------------------------------------------------------- #
def _resolve_workspace_ids(db, slug: str, explicit_id: Optional[str]) -> list:
    """Return list of workspace ids matching the slug (or the explicit id)."""
    if explicit_id:
        return [explicit_id]
    # Workspace model has a ``slug`` column; query defensively via raw reflection.
    try:
        from app.models.workspace import Workspace  # type: ignore

        rows = (
            db.query(Workspace.id, getattr(Workspace, "slug", Workspace.id))
            .all()
        )
        ids = []
        for row in rows:
            wid = row[0]
            wslug = row[1] if len(row) > 1 else None
            wname = getattr(row, "name", None)
            if (str(wslug or "").lower() == slug.lower()) or (
                str(wname or "").lower() == slug.lower()
            ):
                ids.append(wid)
        if ids:
            return ids
    except Exception as exc:  # pragma: no cover - best effort
        print(f"[warn] workspace slug lookup failed: {exc!r}", file=sys.stderr)

    # Fallback: discover workspace ids from the collections themselves whose
    # vector_collection_name / slug contains the workspace slug.
    from app.models.knowledge_collection import KnowledgeCollection

    ids = set()
    for coll in db.query(KnowledgeCollection).all():
        haystack = " ".join(
            str(x or "")
            for x in (coll.slug, coll.vector_collection_name, coll.artifact_prefix)
        ).lower()
        if slug.lower() in haystack:
            ids.add(coll.workspace_id)
    return sorted(ids)


# --------------------------------------------------------------------------- #
# Qdrant helpers
# --------------------------------------------------------------------------- #
def _build_qdrant_client():
    from qdrant_client import QdrantClient
    from app.core.config import settings

    return QdrantClient(
        host=settings.qdrant_host,
        port=settings.qdrant_port,
        api_key=settings.qdrant_api_key or None,
        https=settings.qdrant_https,
        timeout=settings.qdrant_timeout_seconds,
    )


def _list_physical_collections(client, workspace_slug: str) -> list:
    """All physical Qdrant collection names whose name references the workspace."""
    names = []
    for c in client.get_collections().collections:
        name = c.name
        if workspace_slug.lower() in name.lower():
            names.append(name)
    return sorted(names)


def _match_physical_collection(
    physical_names: list, coll_slug: str, vector_collection_name: str
) -> list:
    """Return physical collection names that belong to a logical collection.

    Physical names look like
    ``<workspace>__<collection-slug>__hybrid_<timestamp>``.
    We match on the logical slug appearing as a segment.
    """
    candidates = []
    keys = {str(coll_slug or "").lower(), str(vector_collection_name or "").lower()}
    keys.discard("")
    for name in physical_names:
        lname = name.lower()
        for key in keys:
            # match the slug as a delimited segment to avoid prefix collisions
            if f"__{key}__" in lname or lname == key or f"__{key}" == lname[-(len(key) + 2):]:
                candidates.append(name)
                break
            if key and lname.startswith(key + "__") or (key and ("__" + key) in lname):
                candidates.append(name)
                break
    return sorted(set(candidates))


def _scroll_aggregate(
    client, collection_name: str, scroll_limit: int, max_points: int
) -> Tuple[Dict[str, int], Dict[str, str], int, bool, int]:
    """Scroll a physical collection and aggregate per-document vector counts.

    Returns:
        doc_vec_counts: {document_id: vector_count}
        doc_filenames:  {document_id: document_filename}
        total_points:   total points scanned
        capped:         whether scrolling stopped due to ``max_points``
        no_docid:       points lacking a document_id payload (counted separately)
    """
    doc_vec_counts: Dict[str, int] = defaultdict(int)
    doc_filenames: Dict[str, str] = {}
    total = 0
    no_docid = 0
    capped = False
    offset = None

    while True:
        records, offset = client.scroll(
            collection_name=collection_name,
            with_payload=["document_id", "document_filename"],
            with_vectors=False,
            limit=scroll_limit,
            offset=offset,
        )
        if not records:
            break
        for rec in records:
            total += 1
            payload = rec.payload or {}
            doc_id = payload.get("document_id")
            fname = payload.get("document_filename")
            key = str(doc_id) if doc_id not in (None, "") else None
            if key is None:
                # fall back to filename so the document is not lost entirely
                key = f"__filename__:{fname}" if fname else None
            if key is None:
                no_docid += 1
                continue
            doc_vec_counts[key] += 1
            if fname and key not in doc_filenames:
                doc_filenames[key] = str(fname)
        if max_points and total >= max_points:
            capped = True
            break
        if offset is None:
            break

    return dict(doc_vec_counts), doc_filenames, total, capped, no_docid


# --------------------------------------------------------------------------- #
# Classification
# --------------------------------------------------------------------------- #
def _classify(pg_status: str, pg_chunks: int, qd_vectors: int, mismatch_ratio: float) -> str:
    status = (pg_status or "").lower()

    if status == "deduplicated":
        return "deduplicated"
    if status == "error":
        return "error"
    if status == "queued":
        return "never_enqueued"
    if status in ("deleted",):
        return "other"

    if status in ("ready", "indexed"):
        if qd_vectors <= 0:
            return "missing_in_qdrant"
        if pg_chunks and pg_chunks > 0:
            denom = float(max(pg_chunks, qd_vectors))
            if denom > 0 and abs(pg_chunks - qd_vectors) / denom > mismatch_ratio:
                return "present_count_mismatch"
        return "present_ok"

    # ingesting / unknown statuses
    if qd_vectors > 0:
        return "present_ok"
    return "other"


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main() -> int:
    cfg = _cfg()
    print("=" * 88)
    print("READ-ONLY PG <-> Qdrant ingestion reconciliation")
    print(f"  workspace slug       : {cfg['workspace_slug']}")
    print(f"  explicit workspace id: {cfg['workspace_id'] or '(none)'}")
    print(f"  scroll limit/page    : {cfg['scroll_limit']}")
    print(f"  max points/collection: {cfg['max_points'] or 'unlimited'}")
    print(f"  mismatch ratio       : {cfg['mismatch_ratio']}")
    print("=" * 88)

    from app.db.base import SessionLocal
    from app.models.knowledge_collection import KnowledgeCollection, KnowledgeCollectionSource

    db = SessionLocal()
    try:
        ws_ids = _resolve_workspace_ids(db, cfg["workspace_slug"], cfg["workspace_id"])
        if not ws_ids:
            print(f"[error] no workspace resolved for slug={cfg['workspace_slug']!r}")
            return 2
        print(f"[info] resolved workspace ids: {ws_ids}")

        collections = (
            db.query(KnowledgeCollection)
            .filter(KnowledgeCollection.workspace_id.in_(ws_ids))
            .order_by(KnowledgeCollection.slug)
            .all()
        )
        if not collections:
            print("[error] no knowledge_collections for these workspace ids")
            return 2
        print(f"[info] {len(collections)} knowledge collection(s) found")

        client = _build_qdrant_client()
        physical_names = _list_physical_collections(client, cfg["workspace_slug"])
        print(f"[info] {len(physical_names)} physical Qdrant collection(s) reference "
              f"the workspace slug:")
        for n in physical_names:
            try:
                cnt = client.count(collection_name=n, exact=True).count
            except Exception as exc:
                cnt = f"<count failed: {exc!r}>"
            print(f"         - {n}  (points={cnt})")

        grand_totals: Dict[str, int] = defaultdict(int)

        for coll in collections:
            print("\n" + "#" * 88)
            print(f"# COLLECTION: {coll.slug}")
            print(f"#   id                   : {coll.id}")
            print(f"#   workspace_id         : {coll.workspace_id}")
            print(f"#   status               : {coll.status}")
            print(f"#   vector_collection_name: {coll.vector_collection_name}")
            print(f"#   document_count (meta) : {coll.document_count}  chunk_count={coll.chunk_count}")
            print("#" * 88)

            # ---- PG side ----
            sources = (
                db.query(KnowledgeCollectionSource)
                .filter(KnowledgeCollectionSource.collection_id == coll.id)
                .all()
            )
            pg_status_counts: Dict[str, int] = defaultdict(int)
            for s in sources:
                pg_status_counts[(s.status or "").lower()] += 1
            print(f"[PG] {len(sources)} source row(s). status breakdown: "
                  f"{dict(sorted(pg_status_counts.items()))}")

            # ---- Qdrant side ----
            matched_physical = _match_physical_collection(
                physical_names, coll.slug, coll.vector_collection_name
            )
            print(f"[Qdrant] matched physical collection(s): {matched_physical or '(NONE)'}")

            doc_vec_counts: Dict[str, int] = defaultdict(int)
            doc_filenames: Dict[str, str] = {}
            fname_to_vec: Dict[str, int] = defaultdict(int)
            total_points = 0
            any_capped = False
            total_no_docid = 0

            for pname in matched_physical:
                try:
                    counts, fnames, total, capped, no_docid = _scroll_aggregate(
                        client, pname, cfg["scroll_limit"], cfg["max_points"]
                    )
                except Exception as exc:
                    print(f"   [warn] scroll failed for {pname}: {exc!r}")
                    continue
                for k, v in counts.items():
                    doc_vec_counts[k] += v
                for k, v in fnames.items():
                    doc_filenames.setdefault(k, v)
                total_points += total
                any_capped = any_capped or capped
                total_no_docid += no_docid
                print(f"   scrolled {pname}: points={total} distinct_docs={len(counts)} "
                      f"no_docid_points={no_docid} capped={capped}")

            # build filename-keyed index for fallback join
            for key, vc in doc_vec_counts.items():
                fn = doc_filenames.get(key)
                if fn:
                    fname_to_vec[fn.lower()] += vc

            print(f"[Qdrant] total points scanned={total_points} "
                  f"distinct document keys={len(doc_vec_counts)} "
                  f"points_without_document_id={total_no_docid} capped={any_capped}")

            # ---- Join + classify ----
            class_counts: Dict[str, int] = defaultdict(int)
            missing: list = []
            mismatches: list = []
            matched_qdrant_keys = set()

            for s in sources:
                doc_id = None
                meta = s.source_metadata or {}
                if isinstance(meta, dict):
                    doc_id = meta.get("document_id") or meta.get("document_uid") or meta.get("id")
                key = str(doc_id) if doc_id else None

                qd_vectors = 0
                used_key = None
                if key and key in doc_vec_counts:
                    qd_vectors = doc_vec_counts[key]
                    used_key = key
                else:
                    # fallback on filename / normalized_name
                    for cand in (s.filename, s.normalized_name):
                        if not cand:
                            continue
                        lc = str(cand).lower()
                        if lc in fname_to_vec:
                            qd_vectors = fname_to_vec[lc]
                            used_key = f"__filename__:{lc}"
                            break
                        fk = f"__filename__:{cand}"
                        if fk in doc_vec_counts:
                            qd_vectors = doc_vec_counts[fk]
                            used_key = fk
                            break
                if used_key:
                    matched_qdrant_keys.add(used_key)

                klass = _classify(s.status, s.chunk_count or 0, qd_vectors, cfg["mismatch_ratio"])
                class_counts[klass] += 1
                grand_totals[klass] += 1

                if klass == "missing_in_qdrant":
                    cause = _missing_cause(s)
                    missing.append((s.filename, s.status, s.chunk_count, s.last_error, cause))
                elif klass == "present_count_mismatch":
                    mismatches.append((s.filename, s.chunk_count, qd_vectors))

            # ---- per-collection summary ----
            print("\n--- CLASSIFICATION SUMMARY (per PG source) ---")
            order = [
                "present_ok",
                "present_count_mismatch",
                "missing_in_qdrant",
                "deduplicated",
                "error",
                "never_enqueued",
                "other",
            ]
            for k in order:
                print(f"   {k:<24}: {class_counts.get(k, 0)}")
            ready_indexed = pg_status_counts.get("ready", 0) + pg_status_counts.get("indexed", 0)
            print(f"   {'PG ready+indexed':<24}: {ready_indexed}")
            print(f"   {'Qdrant distinct docs':<24}: {len(doc_vec_counts)}")

            if mismatches:
                print("\n--- COUNT MISMATCHES (pg_chunks vs qdrant_vectors) ---")
                for fn, pg_c, qd_v in sorted(mismatches, key=lambda x: -abs((x[1] or 0) - x[2]))[:50]:
                    print(f"   {fn}: pg_chunk_count={pg_c} qdrant_vectors={qd_v}")
                if len(mismatches) > 50:
                    print(f"   ... and {len(mismatches) - 50} more")

            if missing:
                print("\n--- MISSING IN QDRANT (THE GAP) ---")
                for fn, st, pg_c, err, cause in sorted(missing, key=lambda x: str(x[0])):
                    err_s = (str(err)[:160] + "...") if err and len(str(err)) > 160 else (err or "")
                    print(f"   {fn} | pg_status={st} pg_chunk_count={pg_c} | cause={cause}"
                          + (f" | last_error={err_s}" if err_s else ""))
            else:
                print("\n--- MISSING IN QDRANT (THE GAP): none ---")

        # ---- grand totals ----
        print("\n" + "=" * 88)
        print("GRAND TOTALS across all collections (per PG source classification):")
        for k in [
            "present_ok",
            "present_count_mismatch",
            "missing_in_qdrant",
            "deduplicated",
            "error",
            "never_enqueued",
            "other",
        ]:
            print(f"   {k:<24}: {grand_totals.get(k, 0)}")
        print("=" * 88)
        return 0
    finally:
        db.close()


def _missing_cause(source) -> str:
    """Best-effort probable cause for a missing_in_qdrant document."""
    status = (source.status or "").lower()
    chunks = source.chunk_count or 0
    err = source.last_error
    if err:
        return "indexing/extraction error logged in last_error"
    if chunks == 0 and status in ("ready", "indexed"):
        return "0 chunks produced (probable parse/extraction failure)"
    if chunks > 0 and status in ("ready", "indexed"):
        return ("PG marked ready with chunks but no vectors in Qdrant "
                "(probable upsert/index failure or stale physical collection)")
    return "unknown"


if __name__ == "__main__":
    sys.exit(main())
