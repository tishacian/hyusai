"""Backfill the blank ``project_code`` in the Postgres per-document ledger.

Qdrant is the source of truth for what is actually indexed. Some ledger rows in
``knowledge_collection_sources`` carry no ``source_metadata->>'project_code'``
even though the project is unambiguous, which degrades facets / evaluation /
other ledger consumers (retrieval itself reads the chunk payloads, so this gap
is *not* what breaks a query -- it is a consistency issue in the ledger).

Two distinct populations of blank rows exist (observed on the andritz pilot):

* **Documents that have Qdrant chunks** (status ``ready``/``indexed``). The
  authoritative ``project_code`` is the value carried on *that document's* own
  chunks. If the document's chunks have a single consistent non-null
  ``project_code`` we use it (and cross-check it does not contradict the
  ingestion-time derivation).
* **Deduplicated documents** (status ``deduplicated``) which were never indexed
  (their content is identical to a canonical document of a *different* project),
  so they have **no own chunks**. Their correct ``project_code`` is *their own*
  project, recovered with the exact ingestion-time derivation
  (:func:`app.services.secure_deposit._extract_andritz_project_reference`, i.e.
  the ``_ANDRITZ_PROJECT_RE`` / archive-namespace path derivation) applied to
  the document's own identity (its archive-namespace prefix, not the inner
  document path -- see :func:`_archive_namespace`). Inheriting the canonical's
  code, or a component/model reference from deep in the path, would be wrong.

Resolution per blank row (fill-only, never overwrites an existing value):

* ``qdrant``  -- the document's chunks have one consistent non-null code; the
  ingestion derivation is empty or agrees with it -> write that code.
* ``path``    -- the document has no usable Qdrant code (deduplicated / chunks
  all-null) but the ingestion derivation yields a code -> write the derived
  code + its companion reference fields.
* unresolved  -- ``no_code`` (no Qdrant code and no derivation),
  ``conflict`` (chunks carry several distinct codes) or ``disagree`` (the single
  Qdrant code contradicts the ingestion derivation): left blank, reported.

Idempotency: only rows whose ``project_code`` is currently NULL/empty are
considered, so a re-run is a no-op. Reuses the reconcile script's Qdrant
plumbing (``_client`` / ``_resolve_collection``) and the same document-identity
key (``normalize_source_name``) so PG and Qdrant rows are matched consistently.

A companion ``--qdrant`` mode fills the *chunk payloads* themselves (via
``set_payload``, vectors untouched) for the same fill-only discipline: existing
points whose ``project_code`` is null get the namespace-derived code +
``project_reference_kind`` so retrieval / facets (incl. the transversal
inventory) can see the now-resolvable projects without a reindex. It is scoped
per ``document_filename`` and skips any document whose other chunks already
carry a divergent code.

Usage (inside the backend container):
    python -m scripts.backfill_project_code --workspace andritz            # dry-run (default)
    python -m scripts.backfill_project_code --workspace andritz --apply    # write
    python -m scripts.backfill_project_code --workspace andritz \
        --collection andritz-notices-techniques-spl-pilot --apply
    python -m scripts.backfill_project_code --all-workspaces                # every workspace
    python -m scripts.backfill_project_code --workspace andritz --qdrant            # chunk-payload dry-run
    python -m scripts.backfill_project_code --workspace andritz --qdrant --apply    # chunk-payload write
"""
from __future__ import annotations

import argparse
from collections import Counter

from sqlalchemy import text

from app.db.base import SessionLocal
from app.models.knowledge_collection import KnowledgeCollection, KnowledgeCollectionSource
from app.models.workspace import Workspace
from app.services.knowledge_collections import normalize_source_name
from app.services.rag.project_references import using_workspace_project_scheme
from app.services.secure_deposit import _extract_andritz_project_reference

# Reuse the reconcile script's Qdrant plumbing verbatim so collection
# resolution and client construction stay identical across both maintenance
# scripts.
from scripts.reconcile_ledger_from_qdrant import _client, _resolve_collection

# SQL predicate for "project_code is NULL or blank". ``source_metadata`` is a
# plain ``json`` column, so the ``->>`` text accessor is used (the ``?`` jsonb
# key operator is unavailable). Pushed to Postgres so only blank rows load.
_BLANK_PREDICATE = "nullif(trim(source_metadata->>'project_code'), '') IS NULL"

# Reference fields produced by the ingestion derivation that travel with
# project_code. Written together so the ledger stays internally consistent.
_REFERENCE_FIELDS = (
    "project_code",
    "initial_buyer_code",
    "project_position",
    "project_reference_kind",
)

_COMMIT_EVERY = 2000
_CONFLICT = object()  # sentinel: a document's chunks carry >1 distinct code
_EXAMPLES_PER_BUCKET = 6


def _qdrant_facet_codes(client, coll: str) -> set[str]:
    """Best-effort set of every non-null project_code in the collection.

    Used only to report how many path-derived fills are corroborated by an
    actual Qdrant value (i.e. the derived project really exists in the index).
    Degrades to an empty set if the server/client lacks the facet API.
    """
    try:
        result = client.facet(collection_name=coll, key="project_code", limit=1000, exact=True)
    except Exception:
        return set()
    codes: set[str] = set()
    for hit in getattr(result, "hits", []) or []:
        value = getattr(hit, "value", None)
        if isinstance(value, str) and value.strip():
            codes.add(value.strip())
    return codes


def _doc_project_codes(client, coll: str, document_filename: str, batch: int = 256) -> set[str]:
    """Distinct non-null project_codes carried by one document's own chunks."""
    from qdrant_client import models

    flt = models.Filter(
        must=[models.FieldCondition(key="document_filename", match=models.MatchValue(value=document_filename))]
    )
    codes: set[str] = set()
    next_offset = None
    while True:
        points, next_offset = client.scroll(
            collection_name=coll,
            scroll_filter=flt,
            limit=batch,
            offset=next_offset,
            with_payload=["project_code"],
            with_vectors=False,
        )
        for point in points:
            code = str((point.payload or {}).get("project_code") or "").strip()
            if code:
                codes.add(code)
        if next_offset is None:
            break
    return codes


def _archive_namespace(normalized_name: str) -> str:
    """Archive-namespace prefix (``parent__stem``) of a flattened document name.

    Flattened names look like ``{parent}__{archive_stem}__{inner/path/__/...}``
    where the archive namespace (built by ``secure_deposit`` as ``parent`` +
    ``__`` + ``archive_stem``, e.g. ``R__REN100`` or ``N__NBD100ZH``) carries
    the document's *own* project. The inner path may contain component or model
    references (a Hydac ``HDA4400`` sensor, a URACA ``PHP01`` pump, a carding
    ``TCF3750``) that must NOT be mistaken for a project code. Deriving from the
    namespace prefix instead of the full path avoids those inner-path false
    positives; archives whose stem carries no Andritz code (``NBD100ZH``,
    ``L10080``) then correctly resolve to no code rather than to inner noise.
    """
    tokens = str(normalized_name or "").split("__")
    return "__".join(tokens[:2]) if len(tokens) > 1 else (tokens[0] if tokens else "")


def _derive_reference(row: KnowledgeCollectionSource) -> dict:
    """Ingestion-time project derivation from the document's own identity.

    Mirrors how ``secure_deposit`` computes the reference at ingest with
    ``_ANDRITZ_PROJECT_RE``, but scans only project-level identifiers (the
    deposit/archive path and the archive-namespace prefix), never the inner
    document path, so component/model references buried inside a document are
    not promoted to a project code.
    """
    meta = row.source_metadata or {}
    return _extract_andritz_project_reference(
        meta.get("source_deposit_path"),
        _archive_namespace(row.normalized_name),
    )


def _resolve_qdrant_code(codes: set[str]):
    """Map a document's chunk project_codes to a single value / conflict / none."""
    if not codes:
        return None
    if len(codes) == 1:
        return next(iter(codes))
    return _CONFLICT


def _blank_qdrant_filter(models, document_filename: str | None = None):
    """Filter for points whose ``project_code`` is null/missing (fill-only).

    ``IsEmptyCondition`` matches null, missing, or empty-array payloads, so a
    re-run after a fill is a no-op (the filled points are no longer empty) and a
    point that already carries a code is never selected for overwrite. An
    optional ``document_filename`` scopes the filter to a single document.
    """
    must = [models.IsEmptyCondition(is_empty=models.PayloadField(key="project_code"))]
    if document_filename is not None:
        must.append(
            models.FieldCondition(
                key="document_filename", match=models.MatchValue(value=document_filename)
            )
        )
    return models.Filter(must=must)


def _blank_doc_point_counts(client, coll: str, batch: int = 2000) -> Counter:
    """Count blank-``project_code`` points grouped by ``document_filename``."""
    from qdrant_client import models

    counts: Counter = Counter()
    next_offset = None
    while True:
        points, next_offset = client.scroll(
            collection_name=coll,
            scroll_filter=_blank_qdrant_filter(models),
            limit=batch,
            offset=next_offset,
            with_payload=["document_filename"],
            with_vectors=False,
        )
        for point in points:
            name = str((point.payload or {}).get("document_filename") or "").strip()
            if name:
                counts[name] += 1
        if next_offset is None:
            break
    return counts


def qdrant_fill_collection(client, collection: KnowledgeCollection, apply: bool) -> dict:
    """Fill ``project_code`` on existing Qdrant chunks (no reindex, fill-only).

    For every document that still carries blank chunks, derive its project code
    from the archive-namespace prefix (the same discipline as the ledger
    backfill) and ``set_payload`` ``project_code`` + ``project_reference_kind``
    on *only* the blank points of that document, scoped by ``document_filename``.
    Vectors are untouched. A document whose other chunks already carry a
    *different* code is flagged and skipped rather than made inconsistent.
    """
    from qdrant_client import models

    base = collection.vector_collection_name
    try:
        coll = _resolve_collection(client, base)
    except Exception:
        coll = base

    blank_counts = _blank_doc_point_counts(client, coll)
    stats = Counter()
    code_points: Counter = Counter()
    code_docs: Counter = Counter()
    fill_docs = fill_points = 0
    flagged: list = []
    no_code: list = []
    examples: list = []

    for name, blank_points in blank_counts.items():
        stats["blank_docs"] += 1
        stats["blank_points"] += blank_points
        derived = _extract_andritz_project_reference(_archive_namespace(name)).get("project_code")
        if not derived:
            stats["no_code_docs"] += 1
            stats["no_code_points"] += blank_points
            if len(no_code) < _EXAMPLES_PER_BUCKET:
                no_code.append((name, _archive_namespace(name)))
            continue

        # Fill-only safety: if the document's *other* chunks already carry a
        # code, only proceed when it equals the derived value; a divergent code
        # is reported, never overwritten or mixed.
        existing = _doc_project_codes(client, coll, name)
        conflicting = {code for code in existing if code != derived}
        if conflicting:
            stats["flagged_docs"] += 1
            if len(flagged) < _EXAMPLES_PER_BUCKET:
                flagged.append((name, f"derived={derived} existing={sorted(existing)}"))
            continue

        fill_docs += 1
        fill_points += blank_points
        code_points[derived] += blank_points
        code_docs[derived] += 1
        if len(examples) < _EXAMPLES_PER_BUCKET:
            examples.append((name, derived))

        if apply:
            client.set_payload(
                collection_name=coll,
                payload={"project_code": derived, "project_reference_kind": "andritz_project"},
                points=_blank_qdrant_filter(models, name),
                wait=True,
            )

    return {
        "collection": collection.slug,
        "qdrant_coll": coll,
        "blank_docs": stats["blank_docs"],
        "blank_points": stats["blank_points"],
        "fill_docs": fill_docs,
        "fill_points": fill_points,
        "no_code_docs": stats["no_code_docs"],
        "no_code_points": stats["no_code_points"],
        "flagged_docs": stats["flagged_docs"],
        "distinct_codes": sorted(code_docs),
        "code_docs": code_docs.most_common(12),
        "code_points": dict(code_points),
        "examples": examples,
        "no_code_examples": no_code,
        "flagged": flagged,
    }


def _print_qdrant_result(result: dict, apply: bool) -> None:
    verb = "filled" if apply else "fillable"
    print(
        f"[{result['collection']}] blank_points={result['blank_points']} "
        f"blank_docs={result['blank_docs']} -> {verb}: "
        f"docs={result['fill_docs']} points={result['fill_points']} | "
        f"unresolved: no_code_docs={result['no_code_docs']} "
        f"(points={result['no_code_points']}) flagged_docs={result['flagged_docs']} "
        f"(coll={result['qdrant_coll']})"
    )
    if result["code_docs"]:
        spread = ", ".join(
            f"{code}:{docs}d/{result['code_points'].get(code, 0)}p"
            for code, docs in result["code_docs"]
        )
        print(f"    {verb} codes (docs/points): {spread}")
    if result["distinct_codes"]:
        print(f"    distinct codes: {', '.join(result['distinct_codes'])}")
    for name, code in result["examples"][:3]:
        print(f"    [fill    ] {code:18s} <- {name[:90]}")
    for name, info in result["no_code_examples"][:3]:
        print(f"    [no_code ] {info:18s} <- {name[:90]}")
    for name, info in result["flagged"]:
        print(f"    [FLAGGED ] {info} <- {name[:90]}")


def _iter_blank_batches(db, collection_id: str, batch: int):
    """Yield blank rows in memory-bounded, resumable keyset batches.

    Pages on the primary key (``id > last_id``) instead of loading every blank
    row at once, so the working set stays at ``batch`` rows regardless of
    collection size. Keyset paging advances correctly in both modes: filled
    rows simply drop out of the blank predicate, and unresolved rows are stepped
    over by the id cursor. The session is expunged after each batch to release
    the ORM objects. Re-running after an interruption resumes naturally because
    already-filled rows are no longer blank.
    """
    last_id = ""
    while True:
        rows = (
            db.query(KnowledgeCollectionSource)
            .filter(KnowledgeCollectionSource.collection_id == collection_id)
            .filter(text(_BLANK_PREDICATE))
            .filter(KnowledgeCollectionSource.id > last_id)
            .order_by(KnowledgeCollectionSource.id.asc())
            .limit(batch)
            .all()
        )
        if not rows:
            return
        last_id = rows[-1].id
        yield rows
        db.expunge_all()


def backfill_collection(db, client, collection: KnowledgeCollection, apply: bool) -> dict:
    base = collection.vector_collection_name
    try:
        coll = _resolve_collection(client, base)
    except Exception:
        coll = base
    facet_codes = _qdrant_facet_codes(client, coll)

    stats = Counter()
    code_counter: Counter = Counter()
    path_corroborated = 0
    examples: dict[str, list] = {"qdrant": [], "path": [], "no_code": [], "conflict": [], "disagree": []}

    for rows in _iter_blank_batches(db, collection.id, _COMMIT_EVERY):
        wrote = False
        for row in rows:
            stats["blank"] += 1
            reference = _derive_reference(row)
            derived_code = reference.get("project_code")

            # Deduplicated rows were never indexed, so they have no own chunks;
            # skip the (always-empty) Qdrant lookup and resolve from derivation.
            if str(row.status or "").lower() == "deduplicated":
                qdrant_code = None
            else:
                try:
                    qdrant_code = _resolve_qdrant_code(_doc_project_codes(client, coll, row.normalized_name))
                except Exception:
                    qdrant_code = None

            source = None
            patch: dict = {}
            if qdrant_code is _CONFLICT:
                stats["conflict"] += 1
                if len(examples["conflict"]) < _EXAMPLES_PER_BUCKET:
                    examples["conflict"].append((row.normalized_name, "<multiple>"))
                continue
            if qdrant_code:
                if derived_code and derived_code != qdrant_code:
                    stats["disagree"] += 1
                    if len(examples["disagree"]) < _EXAMPLES_PER_BUCKET:
                        examples["disagree"].append((row.normalized_name, f"qdrant={qdrant_code} derived={derived_code}"))
                    continue
                source = "qdrant"
                # Prefer the full reference (buyer/position) when the derivation
                # agrees; otherwise persist just the authoritative code.
                patch = dict(reference) if derived_code == qdrant_code else {"project_code": qdrant_code}
                patch["project_code"] = qdrant_code
            elif derived_code:
                source = "path"
                patch = {key: reference[key] for key in _REFERENCE_FIELDS if reference.get(key)}
                if derived_code in facet_codes:
                    path_corroborated += 1
            else:
                stats["no_code"] += 1
                if len(examples["no_code"]) < _EXAMPLES_PER_BUCKET:
                    examples["no_code"].append((row.normalized_name, "-"))
                continue

            final_code = patch["project_code"]
            stats[f"fill_{source}"] += 1
            code_counter[final_code] += 1
            if len(examples[source]) < _EXAMPLES_PER_BUCKET:
                examples[source].append((row.normalized_name, final_code))

            if apply:
                patch["project_code_source"] = source
                merged = dict(row.source_metadata or {})
                merged.update(patch)
                row.source_metadata = merged
                wrote = True

        if apply and wrote:
            db.commit()

    blank_after = (
        db.query(KnowledgeCollectionSource)
        .filter(KnowledgeCollectionSource.collection_id == collection.id)
        .filter(text(_BLANK_PREDICATE))
        .count()
    )

    return {
        "collection": collection.slug,
        "qdrant_coll": coll,
        "blank": stats["blank"],
        "fill_qdrant": stats["fill_qdrant"],
        "fill_path": stats["fill_path"],
        "path_corroborated": path_corroborated,
        "no_code": stats["no_code"],
        "conflict": stats["conflict"],
        "disagree": stats["disagree"],
        "blank_after": blank_after,
        "top_codes": code_counter.most_common(8),
        "examples": examples,
    }


def _print_result(result: dict, apply: bool) -> None:
    print(
        f"[{result['collection']}] blank={result['blank']} -> "
        f"fill_qdrant={result['fill_qdrant']} fill_path={result['fill_path']} "
        f"(path_corroborated={result['path_corroborated']}) | "
        f"unresolved: no_code={result['no_code']} conflict={result['conflict']} "
        f"disagree={result['disagree']} | blank_after={result['blank_after']} "
        f"(coll={result['qdrant_coll']})"
    )
    if result["top_codes"]:
        top = ", ".join(f"{code}:{count}" for code, count in result["top_codes"])
        print(f"    top fill codes: {top}")
    for bucket in ("qdrant", "path", "disagree", "conflict", "no_code"):
        rows = result["examples"].get(bucket) or []
        for name, info in rows[:3]:
            print(f"    [{bucket:8s}] {info:18s} <- {name[:90]}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", default="andritz", help="Workspace slug")
    parser.add_argument("--all-workspaces", action="store_true", help="Process every workspace")
    parser.add_argument("--collection", default=None, help="Limit to a single collection slug")
    parser.add_argument("--apply", action="store_true", help="Write changes (default: dry-run)")
    parser.add_argument(
        "--qdrant",
        action="store_true",
        help="Fill project_code on existing Qdrant chunks (set_payload, no reindex) instead of the ledger",
    )
    args = parser.parse_args()

    db = SessionLocal()
    client = _client()
    try:
        if args.all_workspaces:
            workspaces = db.query(Workspace).order_by(Workspace.slug.asc()).all()
        else:
            workspace = db.query(Workspace).filter(Workspace.slug == args.workspace).first()
            if not workspace:
                raise SystemExit(f"workspace not found: {args.workspace}")
            workspaces = [workspace]

        mode = "APPLY" if args.apply else "DRY-RUN"
        target = "qdrant-payload" if args.qdrant else "ledger"
        totals = Counter()
        for workspace in workspaces:
            query = db.query(KnowledgeCollection).filter(KnowledgeCollection.workspace_id == workspace.id)
            if args.collection:
                query = query.filter(KnowledgeCollection.slug == args.collection)
            collections = query.order_by(KnowledgeCollection.slug.asc()).all()
            print(
                f"=== project_code backfill [{mode}/{target}] workspace={workspace.slug} "
                f"collections={len(collections)} ==="
            )
            with using_workspace_project_scheme(workspace):
                for collection in collections:
                    if args.qdrant:
                        result = qdrant_fill_collection(client, collection, args.apply)
                        for key in (
                            "blank_docs", "blank_points", "fill_docs", "fill_points",
                            "no_code_docs", "no_code_points", "flagged_docs",
                        ):
                            totals[key] += result[key]
                        _print_qdrant_result(result, args.apply)
                    else:
                        result = backfill_collection(db, client, collection, args.apply)
                        for key in ("blank", "fill_qdrant", "fill_path", "no_code", "conflict", "disagree", "blank_after"):
                            totals[key] += result[key]
                        _print_result(result, args.apply)

        if args.qdrant:
            print(
                f"=== TOTAL [{mode}/qdrant-payload] blank_docs={totals['blank_docs']} "
                f"blank_points={totals['blank_points']} -> fill_docs={totals['fill_docs']} "
                f"fill_points={totals['fill_points']} | unresolved("
                f"no_code_docs={totals['no_code_docs']} flagged_docs={totals['flagged_docs']}) ==="
            )
        else:
            print(
                f"=== TOTAL [{mode}] blank={totals['blank']} "
                f"fill_qdrant={totals['fill_qdrant']} fill_path={totals['fill_path']} "
                f"unresolved(no_code={totals['no_code']} conflict={totals['conflict']} "
                f"disagree={totals['disagree']}) blank_after={totals['blank_after']} ==="
            )
    finally:
        db.close()


if __name__ == "__main__":
    main()
