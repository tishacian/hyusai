"""Run SPL controlled wave V1 against Secure Deposit archives.

Usage:
    cd backend
    python -m scripts.promote_spl_wave_v1 --workspace andritz --dry-run
    python -m scripts.promote_spl_wave_v1 --workspace andritz --execute
    python -m scripts.promote_spl_wave_v1 --workspace andritz --execute --copy-from andritz-manuals-bba120-pilot
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
    V1_DEFAULT_COPY_FROM,
    build_wave_plan,
    copy_collection_documents,
    execute_wave_plan,
)


def _resolve_actor(db, workspace: Workspace) -> User:
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
    parser.add_argument("--archive", action="append", dest="archives", help="Deposit filename to include in wave")
    parser.add_argument("--dry-run", action="store_true", default=False)
    parser.add_argument("--execute", action="store_true", default=False)
    parser.add_argument(
        "--copy-from",
        default=V1_DEFAULT_COPY_FROM,
        help="Copy already-indexed originals from another collection slug before archive wave",
    )
    parser.add_argument("--skip-copy", action="store_true", help="Skip collection copy step on execute")
    args = parser.parse_args()

    if args.execute == args.dry_run:
        args.dry_run = not args.execute

    archives = tuple(args.archives or V1_DEFAULT_ARCHIVES)
    db = SessionLocal()
    try:
        workspace = db.query(Workspace).filter(Workspace.slug == args.workspace).first()
        if not workspace:
            raise SystemExit(f"Workspace not found: {args.workspace}")

        plan = build_wave_plan(
            db,
            workspace=workspace,
            collection_slug=args.collection,
            archive_filenames=archives,
            allow_repromote=True,
            dry_run=args.dry_run,
        )
        print(json.dumps(plan.as_dict(), ensure_ascii=False, indent=2))

        if args.dry_run:
            return

        user = _resolve_actor(db, workspace)
        copy_result = None
        if args.copy_from and not args.skip_copy:
            copy_result = copy_collection_documents(
                db,
                workspace=workspace,
                source_slug=args.copy_from,
                target_slug=args.collection,
            )
            print("copy_result:", json.dumps(copy_result, ensure_ascii=False))

        result = execute_wave_plan(
            db,
            workspace=workspace,
            user=user,
            plan=plan,
            allow_repromote=True,
        )
        print("wave_result:", json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        db.close()


if __name__ == "__main__":
    main()
