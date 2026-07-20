"""Promote SFTP FSE reference folders into ``andritz-fse-reference``.

Ops note (Phase C-1) — no new ingestion pipeline. Reuses the secure-deposit
promote APIs already used by Client360 / SPL waves.

Target deposit path prefixes (case-insensitive basename match on folder):
  - ``CIC reports/``  (or ``CIC_reports/``, ``cic reports/``)
  - ``RAPPORTS PHOTOS INTERVENTIONS/`` (and close spelling variants)

Destination collection (created on first promote):
  - slug/name: ``andritz-fse-reference``

Usage (from ``backend/``):

    # List matching received deposit files (no write)
    python -m scripts.promote_fse_reference_corpus --workspace andritz --dry-run

    # Promote matching files via secure_deposit.promote_files_to_collection_batch
    python -m scripts.promote_fse_reference_corpus --workspace andritz --promote

Equivalent HTTP (authenticated Agentium user with deposit promote rights):

    GET  /api/v1/sftp/deposits?status=received
    POST /api/v1/sftp/deposits/promote-bulk
         body: {"file_ids": [...], "collection_slug": "andritz-fse-reference"}

If the SFTP mirror is unreachable from this host, run the dry-run against a
synced deposit ledger (or use the HTTP promote-bulk from the UI) — the seam is
ready once files appear as ``DepositFile`` rows with ``status=received``.
"""

from __future__ import annotations

import argparse
import re
from typing import Any

from app.db.base import SessionLocal
from app.models.secure_deposit import DepositFile
from app.models.user import User
from app.models.workspace import Workspace
from app.services.knowledge_collections import create_or_get_collection
from app.services.secure_deposit import promote_files_to_collection_batch

FSE_REFERENCE_COLLECTION = "andritz-fse-reference"

_FOLDER_PATTERNS = (
    re.compile(r"(^|/)cic[_\s-]*reports(/|$)", re.IGNORECASE),
    re.compile(r"(^|/)rapports[_\s-]*photos[_\s-]*interventions(/|$)", re.IGNORECASE),
)


def _matches_fse_reference_deposit(filename: str) -> bool:
    name = str(filename or "").replace("\\", "/")
    if not name:
        return False
    return any(pattern.search(name) for pattern in _FOLDER_PATTERNS)


def _system_user(db, actor: str) -> User:
    user = db.query(User).filter(User.email == actor).first()
    if user:
        return user
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
        if _matches_fse_reference_deposit(row.filename or "") and row.status == "received"
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", default="andritz")
    parser.add_argument("--actor", default="system@agentium.local")
    parser.add_argument("--dry-run", action="store_true", default=False)
    parser.add_argument("--promote", action="store_true", default=False)
    args = parser.parse_args(argv)

    if not args.dry_run and not args.promote:
        args.dry_run = True

    db = SessionLocal()
    try:
        workspace = (
            db.query(Workspace)
            .filter(Workspace.slug == args.workspace, Workspace.deleted_at.is_(None))
            .first()
        )
        if not workspace:
            raise SystemExit(f"Workspace not found: {args.workspace}")

        promotable = _list_promotable(db, workspace)
        print(f"workspace={workspace.slug} matching_received={len(promotable)}")
        for row in promotable[:50]:
            print(f"  - {row.id}  {row.filename}")
        if len(promotable) > 50:
            print(f"  … {len(promotable) - 50} more")

        if args.dry_run or not args.promote:
            print("dry-run only (pass --promote to write)")
            return 0

        collection = create_or_get_collection(
            db,
            workspace=workspace,
            slug=FSE_REFERENCE_COLLECTION,
            name=FSE_REFERENCE_COLLECTION,
            description="FSE intervention reference corpus (CIC reports + photos)",
        )
        db.flush()
        if not promotable:
            print("nothing to promote")
            return 0
        actor = _system_user(db, args.actor)
        payload: dict[str, Any] = promote_files_to_collection_batch(
            db,
            deposit_files=promotable,
            workspace=workspace,
            user=actor,
            collection_slug=collection.slug,
        )
        db.commit()
        print(
            "promoted="
            f"{len(payload.get('promoted_files') or [])} "
            f"skipped={len(payload.get('skipped') or [])} "
            f"collection={collection.slug}"
        )
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
