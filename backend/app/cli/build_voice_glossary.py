"""Build the workspace voice transcript glossary from a collection's chunks.

Scans every chunk of a workspace-scoped collection, extracts acronym / part-number
style tokens (BOM, JETLACE, KD724, XS1, ZCT, ...) and distinctive domain nouns,
and writes the deduped, capped list into
``workspace.settings["voice"]["transcript_glossary"]``.

The extraction reuses the helpers from
``app.services.voice_transcript_glossary`` so the CLI-built glossary and the
live resolver stay coherent. Idempotent: re-running with the same data yields
the same glossary.

Examples::

    python -m app.cli.build_voice_glossary --workspace andritz \
        --collection andritz-notices-techniques-spl-pilot --dry-run
    python -m app.cli.build_voice_glossary --workspace andritz \
        --collection andritz-notices-techniques-spl-pilot --apply
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from typing import Any, List

from app.services.voice_transcript_glossary import (
    _is_acronym_token,
    extract_acronyms,
    extract_distinctive_terms,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Derive acronyms + distinctive domain terms from a collection into "
            "workspace.settings['voice']['transcript_glossary']."
        )
    )
    parser.add_argument("--workspace", required=True, help="Workspace slug, e.g. andritz")
    parser.add_argument(
        "--collection",
        required=True,
        help="Logical collection slug, e.g. andritz-notices-techniques-spl-pilot",
    )
    parser.add_argument(
        "--max-terms",
        type=int,
        default=None,
        help="Cap on total glossary terms. Defaults to settings.voice_transcript_glossary_max_terms.",
    )
    parser.add_argument(
        "--min-term-count",
        type=int,
        default=2,
        help="Minimum occurrences for a (non-acronym) distinctive term to be kept. Default: 2.",
    )
    parser.add_argument(
        "--scan-limit",
        type=int,
        default=0,
        help="Max chunks to scan (0 = all). Useful for quick dry-runs.",
    )
    parser.add_argument(
        "--dry-run",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Print the glossary without persisting. Default: true.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persist the glossary to workspace.settings (implies --no-dry-run).",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    return parser


def _workspace(db: Any, slug: str) -> Any:
    from app.models.workspace import Workspace

    row = db.query(Workspace).filter(Workspace.slug == slug).first()
    if not row:
        raise SystemExit(f"Workspace {slug!r} not found")
    return row


def _document_service(workspace: Any, collection: str) -> Any:
    from app.core.settings_manager import get_resolved_settings
    from app.services.rag.document_service import DocumentService
    from app.services.rag.vector_store_config import resolve_vector_db_type

    app_settings = get_resolved_settings(workspace_id=workspace.id)
    vector_db_type = resolve_vector_db_type(app_settings)
    return DocumentService(
        collection_name=collection,
        vector_db_type=vector_db_type,
        workspace_slug=workspace.slug,
    )


async def _scan_chunk_texts(doc_svc: Any, *, scan_limit: int = 0) -> List[str]:
    """Scroll all chunk payloads and return their text content."""
    texts: List[str] = []
    page = 500
    offset = 0
    while True:
        payloads = await doc_svc.vector_db.list_payloads(limit=page, offset=offset)
        if not payloads:
            break
        for payload in payloads:
            content = payload.get("content") or payload.get("page_content") or payload.get("text")
            if isinstance(content, str) and content.strip():
                texts.append(content)
        offset += len(payloads)
        if len(payloads) < page:
            break
        if scan_limit and offset >= scan_limit:
            break
    return texts


def _build_terms(
    texts: List[str],
    *,
    min_term_count: int,
    max_terms: int,
    acronym_ratio: float = 0.5,
) -> tuple[List[str], dict[str, Any]]:
    """Build an ordered, deduped, capped glossary surface list from chunk texts.

    The cap is split between acronyms and distinctive domain nouns so neither
    starves the other: acronyms get up to ``acronym_ratio`` of the cap, the rest
    goes to distinctive terms (frequency-ranked, meeting ``min_term_count``).
    Whichever category underfills donates its leftover budget to the other.
    Dedupe is case-insensitive (first/most-frequent surface wins).
    """
    acronym_counts: Counter[str] = Counter()
    acronym_surface: dict[str, str] = {}
    term_counts: Counter[str] = Counter()
    term_surface: dict[str, str] = {}

    for text in texts:
        for surface in extract_acronyms(text):
            key = surface.lower()
            acronym_counts[key] += 1
            acronym_surface.setdefault(key, surface)
        for surface in extract_distinctive_terms(text):
            key = surface.lower()
            term_counts[key] += 1
            # Prefer a capitalized surface if one is seen (proper-noun-ish).
            current = term_surface.get(key)
            if current is None or (surface[:1].isupper() and not current[:1].isupper()):
                term_surface[key] = surface

    acronyms_ranked = [acronym_surface[k] for k, _c in acronym_counts.most_common()]
    distinctive_ranked = [
        term_surface[k]
        for k, count in term_counts.most_common()
        if count >= min_term_count
    ]

    acronym_budget = min(len(acronyms_ranked), int(round(max_terms * acronym_ratio)))
    distinctive_budget = max_terms - acronym_budget
    # Donate unused capacity across categories so the cap is fully used.
    if len(distinctive_ranked) < distinctive_budget:
        acronym_budget = min(len(acronyms_ranked), max_terms - len(distinctive_ranked))
        distinctive_budget = max_terms - acronym_budget

    ordered: List[str] = []
    seen: set = set()
    for surface in acronyms_ranked[:acronym_budget]:
        key = surface.lower()
        if key in seen:
            continue
        seen.add(key)
        ordered.append(surface)
    distinctive_kept = 0
    for surface in distinctive_ranked:
        if distinctive_kept >= distinctive_budget:
            break
        key = surface.lower()
        if key in seen:
            continue
        seen.add(key)
        ordered.append(surface)
        distinctive_kept += 1

    capped = ordered[:max_terms]
    stats = {
        "acronyms_unique": len(acronym_counts),
        "distinctive_candidates": len(distinctive_ranked),
        "distinctive_kept": distinctive_kept,
        "terms_before_cap": len(ordered),
        "terms_after_cap": len(capped),
        "acronyms_in_glossary": sum(1 for t in capped if _is_acronym_token(t)),
    }
    return capped, stats


def _persist(db: Any, workspace: Any, terms: List[str]) -> None:
    from sqlalchemy.orm.attributes import flag_modified

    settings = dict(workspace.settings or {})
    voice_cfg = dict(settings.get("voice") or {})
    voice_cfg["transcript_glossary"] = terms
    settings["voice"] = voice_cfg
    workspace.settings = settings
    flag_modified(workspace, "settings")
    db.commit()


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    dry_run = args.dry_run and not args.apply

    from app.core.config import settings as cfg
    from app.db.base import SessionLocal

    max_terms = args.max_terms or int(getattr(cfg, "voice_transcript_glossary_max_terms", 120))

    db = SessionLocal()
    try:
        workspace = _workspace(db, args.workspace)
        doc_svc = _document_service(workspace, args.collection)
        texts = asyncio.run(_scan_chunk_texts(doc_svc, scan_limit=args.scan_limit))
        terms, stats = _build_terms(
            texts, min_term_count=args.min_term_count, max_terms=max_terms
        )

        applied = False
        if not dry_run:
            _persist(db, workspace, terms)
            applied = True

        payload = {
            "workspace": workspace.slug,
            "collection": args.collection,
            "chunks_scanned": len(texts),
            "dry_run": dry_run,
            "applied": applied,
            "max_terms": max_terms,
            "min_term_count": args.min_term_count,
            "terms_count": len(terms),
            "terms": terms,
            **stats,
        }
        if args.json:
            print(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True))
        else:
            print(
                f"workspace={workspace.slug} collection={args.collection} "
                f"chunks_scanned={len(texts)} dry_run={dry_run} applied={applied}"
            )
            print(
                f"  extracted {len(terms)} terms "
                f"(acronyms={stats['acronyms_in_glossary']}, "
                f"distinctive_kept={stats['distinctive_kept']}, "
                f"before_cap={stats['terms_before_cap']}, cap={max_terms})"
            )
            print("  " + ", ".join(terms[:60]) + (" ..." if len(terms) > 60 else ""))
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
