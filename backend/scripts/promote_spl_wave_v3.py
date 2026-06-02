"""Run SPL controlled wave V3 (remaining archives, folder/size batches).

Usage:
    cd backend
    python -m scripts.promote_spl_wave_v3 --workspace andritz --dry-run
    python -m scripts.promote_spl_wave_v3 --workspace andritz --execute
    python -m scripts.promote_spl_wave_v3 --workspace andritz --execute --batch 1
    python -m scripts.promote_spl_wave_v3 --workspace andritz --dry-run --folder A
    python -m scripts.promote_spl_wave_v3 --workspace andritz --execute --folder A --ocr off
"""
from __future__ import annotations

import argparse
import json

from app.db.base import SessionLocal
from app.models.user import User
from app.models.workspace import Workspace
from app.services.spl_wave_importer import (
    DEFAULT_SPL_COLLECTION,
    build_v3_wave_plans,
    execute_v3_wave_plans,
)


def _resolve_actor(db) -> User:
    user = (
        db.query(User)
        .filter(User.email.isnot(None))
        .order_by(User.created_at.asc())
        .first()
    )
    if not user:
        raise SystemExit("No user found to attribute wave promotion")
    return user


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", default="andritz")
    parser.add_argument("--collection", default=DEFAULT_SPL_COLLECTION)
    parser.add_argument("--folder", help="Limit to SPL subfolder letter (A, B, C, D)")
    parser.add_argument("--batch", type=int, help="1-based batch index from dry-run plan list")
    parser.add_argument("--dry-run", action="store_true", default=False)
    parser.add_argument("--execute", action="store_true", default=False)
    parser.add_argument("--force", action="store_true", help="Ignore wave ledger skips")
    parser.add_argument(
        "--ocr",
        choices=["auto", "off", "force"],
        default="auto",
        help="OCR policy for worker ingestion: auto scan detection, off for text-layer baseline, force for every PDF page",
    )
    args = parser.parse_args()

    if args.execute == args.dry_run:
        args.dry_run = not args.execute

    db = SessionLocal()
    try:
        workspace = db.query(Workspace).filter(Workspace.slug == args.workspace).first()
        if not workspace:
            raise SystemExit(f"Workspace not found: {args.workspace}")

        plans = build_v3_wave_plans(
            db,
            workspace=workspace,
            collection_slug=args.collection,
            dry_run=args.dry_run,
            skip_ledger=not args.force,
            folder=args.folder,
            batch_index=args.batch,
        )
        summary = {
            "batch_count": len(plans),
            "total_archives": sum(len(plan.archives) for plan in plans),
            "total_documents": sum(plan.total_documents for plan in plans),
            "plans": [plan.as_dict() for plan in plans],
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        if args.dry_run:
            return

        user = _resolve_actor(db)
        document_ocr = None
        if args.ocr == "off":
            document_ocr = {"enabled": False}
        elif args.ocr == "force":
            document_ocr = {"enabled": True, "force_ocr": True}
        results = execute_v3_wave_plans(
            db,
            workspace=workspace,
            user=user,
            collection_slug=args.collection,
            skip_ledger=not args.force,
            folder=args.folder,
            batch_index=args.batch,
            document_ocr=document_ocr,
        )
        print("wave_results:", json.dumps(results, ensure_ascii=False, indent=2))
    finally:
        db.close()


if __name__ == "__main__":
    main()
