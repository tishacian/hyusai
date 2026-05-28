"""Run SPL controlled wave V2 (project-based batches) against Secure Deposit.

Usage:
    cd backend
    python -m scripts.promote_spl_wave_v2 --workspace andritz --dry-run
    python -m scripts.promote_spl_wave_v2 --workspace andritz --execute
    python -m scripts.promote_spl_wave_v2 --workspace andritz --seed-v1-ledger
"""
from __future__ import annotations

import argparse
import json

from app.db.base import SessionLocal
from app.models.user import User
from app.models.workspace import Workspace
from app.services.spl_wave_importer import (
    DEFAULT_SPL_COLLECTION,
    V1_DEFAULT_ARCHIVES,
    V2_DEFAULT_PROJECTS,
    build_v2_wave_plans,
    execute_v2_wave_plans,
    record_wave_ledger,
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
    parser.add_argument("--project", action="append", dest="projects", help="Project code filter")
    parser.add_argument("--dry-run", action="store_true", default=False)
    parser.add_argument("--execute", action="store_true", default=False)
    parser.add_argument(
        "--seed-v1-ledger",
        action="store_true",
        help="Record V1 archive filenames in the wave ledger without re-ingesting",
    )
    parser.add_argument("--force", action="store_true", help="Ignore wave ledger skips")
    args = parser.parse_args()

    if args.execute == args.dry_run and not args.seed_v1_ledger:
        args.dry_run = not args.execute

    projects = tuple(args.projects or V2_DEFAULT_PROJECTS)
    db = SessionLocal()
    try:
        workspace = db.query(Workspace).filter(Workspace.slug == args.workspace).first()
        if not workspace:
            raise SystemExit(f"Workspace not found: {args.workspace}")

        if args.seed_v1_ledger:
            record_wave_ledger(
                db,
                workspace=workspace,
                collection_slug=args.collection,
                wave_id="spl_v1",
                filenames=V1_DEFAULT_ARCHIVES,
                job_id=None,
                new_document_count=0,
            )
            db.commit()
            print(json.dumps({"status": "seeded", "filenames": list(V1_DEFAULT_ARCHIVES)}, indent=2))
            return

        plans = build_v2_wave_plans(
            db,
            workspace=workspace,
            collection_slug=args.collection,
            projects=projects,
            dry_run=args.dry_run,
            skip_ledger=not args.force,
        )
        print(json.dumps([plan.as_dict() for plan in plans], ensure_ascii=False, indent=2))
        if args.dry_run:
            return

        user = _resolve_actor(db)
        results = execute_v2_wave_plans(
            db,
            workspace=workspace,
            user=user,
            collection_slug=args.collection,
            projects=projects,
            skip_ledger=not args.force,
        )
        print("wave_results:", json.dumps(results, ensure_ascii=False, indent=2))
    finally:
        db.close()


if __name__ == "__main__":
    main()
