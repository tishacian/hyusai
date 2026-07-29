"""Promote Client360 deposit files and sync the SPL adapter.

Usage:
    cd backend
    python -m scripts.promote_client360_installed_base --workspace andritz --dry-run
    python -m scripts.promote_client360_installed_base --workspace andritz --promote
    python -m scripts.promote_client360_installed_base --workspace andritz --sync
    python -m scripts.promote_client360_installed_base --workspace andritz --rehydrate-mvp

Promote vault only (no adapter sync) — Histo_Achat / SPC / large exports:
    python -m scripts.promote_client360_installed_base --workspace andritz --promote

Sync after promote (opt-in heavy feeds; registry always syncs when present):
    python -m scripts.promote_client360_installed_base \\
      --workspace andritz --sync --include-purchase-history --include-spc

    # Or enable both heavy feeds via adapter scope (distinct from engine scope_mode):
    python -m scripts.promote_client360_installed_base \\
      --workspace andritz --sync --scope all

Idempotent promote of deposit files whose path matches:
  - Installed_base_SPL/<allowlisted xlsx>  (SAP exports; large files —
    Histo_Achat, SPC, Liste Projets, Sales Orders — allowed up to 60MB)
  - Client360_Pilot/*xlsx  (optional pilot folder only)

Does NOT match bare SEPTONA / Needlepunch / CIC / photos / notices via substring.
Does not archive MVP sources unless --archive-mvp is passed (still dry-run by
default; require --archive-mvp-apply for real archive).

Ops sequence: docs/ops/client360-generalized-app.md
"""

from __future__ import annotations

import argparse
import json
from typing import Any

from sqlalchemy.orm.attributes import flag_modified

from app.db.base import SessionLocal
from app.models.client360 import Client360DataSource
from app.models.secure_deposit import DepositFile
from app.models.user import User
from app.models.workspace import Workspace
from app.services.client360_contract import (
    CLIENT360_INSTALLED_BASE_COLLECTION_NAME,
    CLIENT360_INSTALLED_BASE_COLLECTION_SLUG,
    CLIENT360_PILOT_DATASET_MARKER,
)
from app.services.client360_spl_adapter import (
    preview_archive_mvp_orphan_sources,
    rehydrate_pilot_mvp_into_collection,
    sync_sources_from_collection,
)
from app.services.knowledge_collections import create_or_get_collection
from app.services.secure_deposit import promote_files_to_collection_batch

# Exact basenames under Installed_base_SPL/ (case-insensitive).
SPL_BASENAME_ALLOWLIST = frozenset(
    {
        "family - opportunity.xlsx",
        "family_opportunity.xlsx",
        "installed base - machine.xlsx",
        "installed base - spc.xlsx",
        "sales_by_country.xlsx",
        "materials_consumptions.xlsx",
        "histo_achat_pieces_machines_montbonnot.xlsx",
        "liste projets _ clients.xlsx",
        "liste sales orders d800 mnt spl 2011_2026 va05.xlsx",
    }
)
# Large SPL exports allowed up to 60MB (default promote cap is 20MB).
LARGE_SPL_BASENAMES = frozenset(
    {
        "histo_achat_pieces_machines_montbonnot.xlsx",
        "installed base - spc.xlsx",
        "liste projets _ clients.xlsx",
        "liste sales orders d800 mnt spl 2011_2026 va05.xlsx",
    }
)
LARGE_SPL_MAX_PROMOTE_BYTES = 60_000_000


def _deposit_basename(filename: str) -> str:
    return str(filename or "").replace("\\", "/").rsplit("/", 1)[-1]


def _effective_max_promote_bytes(filename: str, default_max: int) -> int:
    """Allow listed large SPL exports up to 60MB; other files keep the default cap."""
    if _deposit_basename(filename).lower() in LARGE_SPL_BASENAMES:
        return max(default_max, LARGE_SPL_MAX_PROMOTE_BYTES)
    return default_max


def _matches_client360_deposit(filename: str) -> bool:
    """True only for allowlisted SPL xlsx or Client360_Pilot/*.xlsx path prefixes."""
    name = str(filename or "")
    if not name:
        return False
    lower = name.lower()
    if not lower.endswith(".xlsx"):
        return False
    if name.startswith("Installed_base_SPL/") or name.startswith("Installed_base_SPL\\"):
        return _deposit_basename(name).lower() in SPL_BASENAME_ALLOWLIST
    if name.startswith("Client360_Pilot/") or name.startswith("Client360_Pilot\\"):
        return True
    return False


def _system_user(db, workspace: Workspace, actor: str) -> User:
    user = (
        db.query(User)
        .filter(User.email == actor)
        .first()
    )
    if user:
        return user
    # Prefer any workspace-linked admin-ish user via email pattern, else first user.
    user = db.query(User).order_by(User.created_at.asc()).first()
    if not user:
        raise SystemExit("No user available to act as promote actor")
    return user


def _list_promotable(db, workspace: Workspace) -> list[DepositFile]:
    rows = (
        db.query(DepositFile)
        .filter(DepositFile.workspace_id == workspace.id)
        .order_by(DepositFile.uploaded_at.asc())
        .all()
    )
    return [
        row
        for row in rows
        if _matches_client360_deposit(row.filename or "") and row.status == "received"
    ]


def _already_promoted(db, workspace: Workspace, collection_slug: str) -> list[dict[str, Any]]:
    rows = (
        db.query(DepositFile)
        .filter(
            DepositFile.workspace_id == workspace.id,
            DepositFile.promoted_collection_slug == collection_slug,
            DepositFile.status == "promoted",
        )
        .all()
    )
    return [
        {"id": row.id, "filename": row.filename, "status": row.status}
        for row in rows
        if _matches_client360_deposit(row.filename or "")
    ]


def _archive_mvp(db, workspace: Workspace, *, apply: bool) -> dict[str, Any]:
    preview = preview_archive_mvp_orphan_sources(db, workspace)
    if not apply:
        return preview
    archived = []
    for item in preview.get("archive_candidates") or []:
        row = (
            db.query(Client360DataSource)
            .filter(
                Client360DataSource.workspace_id == workspace.id,
                Client360DataSource.id == item["id"],
            )
            .first()
        )
        if row is None:
            continue
        row.status = "archived"
        meta = dict(row.meta_data or {})
        meta["archived_reason"] = "replaced_by_unified_collection"
        meta["pilot_dataset"] = meta.get("pilot_dataset") or CLIENT360_PILOT_DATASET_MARKER
        row.meta_data = meta
        flag_modified(row, "meta_data")
        archived.append(item["id"])
    db.flush()
    return {"dry_run": False, "archived_ids": archived, "count": len(archived)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", default="andritz")
    parser.add_argument("--collection", default=CLIENT360_INSTALLED_BASE_COLLECTION_SLUG)
    parser.add_argument("--actor", default="system:client360-promote@local")
    parser.add_argument("--dry-run", action="store_true", help="Report only")
    parser.add_argument("--ensure-collection", action="store_true", default=True)
    parser.add_argument(
        "--promote",
        action="store_true",
        help="Promote matching deposit files (vault only; may be used without --sync)",
    )
    parser.add_argument("--sync", action="store_true", help="Run SPL adapter sync")
    parser.add_argument(
        "--scope",
        default="phase1",
        choices=["phase1", "all"],
        help=(
            "Adapter sync scope: phase1 (default) or all "
            "(all also enables SPC + purchase_history). "
            "Not the same as workspace settings client360_pdr_scope.scope_mode "
            "(pilot|all) used by the opportunities engine."
        ),
    )
    parser.add_argument(
        "--include-purchase-history",
        action="store_true",
        help="Include Histo_Achat purchase_history when syncing (also implied by --scope all)",
    )
    parser.add_argument(
        "--include-spc",
        action="store_true",
        help=(
            "Include Installed base SPC when syncing "
            "(also implied by --scope all; heavy ~56MB / 50k+ lines)"
        ),
    )
    parser.add_argument(
        "--rehydrate-mvp",
        action="store_true",
        help="Link MVP Client360DataSource records to the collection when pilot xlsx missing",
    )
    parser.add_argument(
        "--archive-mvp",
        action="store_true",
        help="Preview archive of orphan MVP sources (safe)",
    )
    parser.add_argument(
        "--archive-mvp-apply",
        action="store_true",
        help="Actually archive orphan MVP sources (destructive)",
    )
    parser.add_argument(
        "--max-promote-bytes",
        type=int,
        default=20_000_000,
        help="Skip individual deposit files larger than this (default 20MB; SPC ~56MB)",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        workspace = db.query(Workspace).filter(Workspace.slug == args.workspace).first()
        if not workspace:
            raise SystemExit(f"Workspace not found: {args.workspace}")

        report: dict[str, Any] = {
            "workspace": workspace.slug,
            "collection_slug": args.collection,
            "dry_run": args.dry_run,
        }

        if args.ensure_collection:
            collection = create_or_get_collection(
                db,
                workspace=workspace,
                name=CLIENT360_INSTALLED_BASE_COLLECTION_NAME,
                description="Unified Client360 installed-base vault",
                slug=args.collection,
            )
            if not args.dry_run:
                db.commit()
            report["collection"] = {
                "id": collection.id,
                "slug": collection.slug,
                "document_count": collection.document_count,
            }

        promotable = _list_promotable(db, workspace)
        skipped_large = [
            {"id": f.id, "filename": f.filename, "size_bytes": f.size_bytes}
            for f in promotable
            if int(f.size_bytes or 0)
            > _effective_max_promote_bytes(f.filename or "", args.max_promote_bytes)
        ]
        promotable = [
            f
            for f in promotable
            if int(f.size_bytes or 0)
            <= _effective_max_promote_bytes(f.filename or "", args.max_promote_bytes)
        ]
        report["promotable"] = [
            {"id": f.id, "filename": f.filename, "size_bytes": f.size_bytes, "status": f.status}
            for f in promotable
        ]
        report["skipped_large"] = skipped_large
        report["already_promoted"] = _already_promoted(db, workspace, args.collection)

        if args.promote and promotable:
            if args.dry_run:
                report["promote"] = {"dry_run": True, "would_promote": len(promotable)}
            else:
                user = _system_user(db, workspace, args.actor)
                result = promote_files_to_collection_batch(
                    db,
                    deposit_files=promotable,
                    workspace=workspace,
                    user=user,
                    collection_slug=args.collection,
                )
                db.commit()
                report["promote"] = result
        elif args.promote:
            report["promote"] = {"promoted": 0, "note": "no_received_matching_files"}

        if args.rehydrate_mvp:
            report["rehydrate_mvp"] = rehydrate_pilot_mvp_into_collection(
                db,
                workspace,
                collection_slug=args.collection,
                dry_run=args.dry_run,
            )
            if not args.dry_run:
                db.commit()

        if args.sync:
            report["sync"] = sync_sources_from_collection(
                db,
                workspace,
                collection_slug=args.collection,
                dry_run=args.dry_run,
                scope=args.scope,
                include_purchase_history=args.include_purchase_history,
                include_spc=args.include_spc,
            )
            if args.dry_run:
                db.rollback()
            else:
                db.commit()

        if args.archive_mvp or args.archive_mvp_apply:
            report["archive_mvp"] = _archive_mvp(
                db, workspace, apply=bool(args.archive_mvp_apply) and not args.dry_run
            )
            if args.archive_mvp_apply and not args.dry_run:
                db.commit()

        print(json.dumps(report, ensure_ascii=False, default=str))
    finally:
        db.close()


if __name__ == "__main__":
    main()
