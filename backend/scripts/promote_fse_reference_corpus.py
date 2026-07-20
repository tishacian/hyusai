"""Promote SFTP FSE reference folders into ``andritz-fse-reference``.

Ops note (Phase C-1) — no new ingestion pipeline. Reuses the secure-deposit
promote APIs already used by Client360 / SPL waves.

Priority tiers (lower number = promote first):
  1. ESN + EX70 checklists / procédures (~15 Mo) — Experience Sharing Notes,
     P APG EX70*, P KNW EX70*, Automation / Mechanical checklists, Weekly
     Service Initiative Report.
  2. OneDrive manuals and larger reference trees (secondary).

Secret exclusion (never promote):
  - basename matches ``PASSWORD*``
  - extension ``.uic``
  - configurable ``--exclude-pattern`` regexes (repeatable)

Target deposit path prefixes (case-insensitive basename match on folder):
  - ``CIC reports/``  (or ``CIC_reports/``, ``cic reports/``)
  - ``RAPPORTS PHOTOS INTERVENTIONS/`` (and close spelling variants)
  - ``Experience Sharing`` / ``APG Filed service`` / ``OneDrive`` trees when
    mirrored into the deposit ledger

Destination collection (created on first promote):
  - slug/name: ``andritz-fse-reference``

Usage (from ``backend/``):

    # List matching received deposit files (no write), ordered by priority
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

Do not run live ingest from this script unless an operator passes ``--promote``.
"""

from __future__ import annotations

import argparse
import re
from pathlib import PurePosixPath
from typing import Any, Iterable, List, Sequence, Tuple

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
    re.compile(r"(^|/)apg[_\s-]*filed[_\s-]*service", re.IGNORECASE),
    re.compile(r"(^|/)experience[_\s-]*sharing", re.IGNORECASE),
    re.compile(r"(^|/)onedrive", re.IGNORECASE),
)

# Tier 1: ESN + EX70 procedures / checklists (promote first).
_TIER1_PATTERNS = (
    re.compile(r"experience\s*sharing\s*note", re.IGNORECASE),
    re.compile(r"\besn\b", re.IGNORECASE),
    re.compile(r"p\s*apg\s*ex70", re.IGNORECASE),
    re.compile(r"p\s*knw\s*ex70", re.IGNORECASE),
    re.compile(r"weekly\s*service\s*initiative\s*report", re.IGNORECASE),
    re.compile(r"automation\s*check\s*list", re.IGNORECASE),
    re.compile(r"mechanical\s*check\s*list", re.IGNORECASE),
    re.compile(r"pre\s*check[-_\s]*work\s*conditions", re.IGNORECASE),
    re.compile(r"hts\s*confirmation", re.IGNORECASE),
)

_DEFAULT_SECRET_PATTERNS = (
    re.compile(r"(^|/)PASSWORD[^/]*$", re.IGNORECASE),
    re.compile(r"\.uic$", re.IGNORECASE),
)


def _normalize_path(filename: str) -> str:
    return str(filename or "").replace("\\", "/")


def _basename(filename: str) -> str:
    return PurePosixPath(_normalize_path(filename)).name


def is_secret_deposit_path(
    filename: str,
    *,
    extra_patterns: Sequence[re.Pattern[str]] | None = None,
) -> bool:
    """True when the deposit path must never be promoted into the corpus."""
    path = _normalize_path(filename)
    if not path:
        return False
    patterns: List[re.Pattern[str]] = list(_DEFAULT_SECRET_PATTERNS)
    if extra_patterns:
        patterns.extend(extra_patterns)
    return any(pattern.search(path) for pattern in patterns)


def priority_tier(filename: str) -> int:
    """1 = ESN/EX70 first, 2 = OneDrive/manuals, 99 = unmatched."""
    path = _normalize_path(filename)
    base = _basename(path)
    haystack = f"{path} {base}"
    if any(pattern.search(haystack) for pattern in _TIER1_PATTERNS):
        return 1
    if re.search(r"(^|/)onedrive", path, re.IGNORECASE):
        return 2
    if any(pattern.search(path) for pattern in _FOLDER_PATTERNS):
        return 2
    return 99


def _matches_fse_reference_deposit(filename: str) -> bool:
    name = _normalize_path(filename)
    if not name:
        return False
    if priority_tier(name) == 1:
        return True
    return any(pattern.search(name) for pattern in _FOLDER_PATTERNS)


def _system_user(db, actor: str) -> User:
    user = db.query(User).filter(User.email == actor).first()
    if user:
        return user
    user = db.query(User).order_by(User.created_at.asc()).first()
    if not user:
        raise SystemExit("No user available to act as promote actor")
    return user


def _compile_extra_patterns(raw: Iterable[str] | None) -> List[re.Pattern[str]]:
    patterns: List[re.Pattern[str]] = []
    for item in raw or []:
        text = str(item or "").strip()
        if not text:
            continue
        patterns.append(re.compile(text, re.IGNORECASE))
    return patterns


def _list_promotable(
    db,
    workspace: Workspace,
    *,
    extra_secret_patterns: Sequence[re.Pattern[str]] | None = None,
) -> list[DepositFile]:
    rows = (
        db.query(DepositFile)
        .filter(DepositFile.workspace_id == workspace.id)
        .order_by(DepositFile.uploaded_at.asc())
        .all()
    )
    matched = [
        row
        for row in rows
        if _matches_fse_reference_deposit(row.filename or "")
        and row.status == "received"
        and not is_secret_deposit_path(
            row.filename or "",
            extra_patterns=extra_secret_patterns,
        )
    ]
    matched.sort(
        key=lambda row: (
            priority_tier(row.filename or ""),
            str(row.uploaded_at or ""),
            row.filename or "",
        )
    )
    return matched


def classify_deposit_filename(
    filename: str,
    *,
    extra_secret_patterns: Sequence[re.Pattern[str]] | None = None,
) -> Tuple[bool, int, bool]:
    """Return ``(matches, tier, is_secret)`` for unit tests / dry-run tooling."""
    secret = is_secret_deposit_path(filename, extra_patterns=extra_secret_patterns)
    if secret:
        return False, priority_tier(filename), True
    matches = _matches_fse_reference_deposit(filename)
    return matches, priority_tier(filename), False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", default="andritz")
    parser.add_argument("--actor", default="system@agentium.local")
    parser.add_argument("--dry-run", action="store_true", default=False)
    parser.add_argument("--promote", action="store_true", default=False)
    parser.add_argument(
        "--exclude-pattern",
        action="append",
        default=[],
        help="Extra regex (case-insensitive) of deposit paths to exclude as secrets",
    )
    parser.add_argument(
        "--tier",
        type=int,
        choices=(1, 2),
        default=None,
        help="Only list/promote a single priority tier (1=ESN+EX70, 2=OneDrive)",
    )
    args = parser.parse_args(argv)

    if not args.dry_run and not args.promote:
        args.dry_run = True

    extra_secret = _compile_extra_patterns(args.exclude_pattern)

    db = SessionLocal()
    try:
        workspace = (
            db.query(Workspace)
            .filter(Workspace.slug == args.workspace, Workspace.deleted_at.is_(None))
            .first()
        )
        if not workspace:
            raise SystemExit(f"Workspace not found: {args.workspace}")

        promotable = _list_promotable(
            db,
            workspace,
            extra_secret_patterns=extra_secret,
        )
        if args.tier is not None:
            promotable = [
                row for row in promotable if priority_tier(row.filename or "") == args.tier
            ]
        print(f"workspace={workspace.slug} matching_received={len(promotable)}")
        for row in promotable[:50]:
            tier = priority_tier(row.filename or "")
            print(f"  - tier={tier}  {row.id}  {row.filename}")
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
            description="FSE intervention reference corpus (ESN/EX70 + manuals)",
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
