"""Plan a controlled transverse notice ingestion campaign.

Dry-run is the default and has no database or object-store side effect::

    cd backend
    python -m scripts.promote_notice_wave \
      --workspace andritz --profile needlepunch --project 61035

Execution is deliberately owned by the gated campaign runner, which requires
the exact hash printed by this dry-run::

    python -m scripts.run_notice_campaign \
      --workspace andritz --profile needlepunch --project 61035 \
      --plan-hash <sha256> --execute --actor-email <reviewer-or-admin> \
      --snapshot-ref <off-host-backup-reference>

The planner has no mutation mode.  This prevents a direct enqueue from
bypassing snapshot, capacity, Qdrant and postflight gates.
"""
from __future__ import annotations

import argparse
import json

from app.core.iam.roles import normalize_role_template
from app.db.base import SessionLocal
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services.iam.manifest import REVIEW_ROLES
from app.services.notice_wave_importer import (
    DEFAULT_NOTICE_COLLECTION,
    NOTICE_SOURCE_PROFILES,
    build_notice_wave_plan,
)


def _resolve_actor(db, *, workspace: Workspace, email: str) -> User:
    normalized_email = str(email or "").strip()
    user = db.query(User).filter(User.email == normalized_email).first()
    if not user:
        raise SystemExit(f"Actor user not found: {normalized_email}")
    if user.is_active is not True:
        raise SystemExit(f"Actor user is inactive: {normalized_email}")
    membership = (
        db.query(WorkspaceMember)
        .filter(
            WorkspaceMember.workspace_id == workspace.id,
            WorkspaceMember.user_id == user.id,
        )
        .first()
    )
    if membership is None:
        raise SystemExit(
            f"Actor is not a member of workspace {workspace.slug}: {normalized_email}"
        )
    role_template = normalize_role_template(
        membership.role_template,
        membership.role,
    )
    if role_template not in REVIEW_ROLES:
        raise SystemExit(
            "Notice promotion requires a workspace reviewer, admin, or owner actor: "
            f"{normalized_email}"
        )
    return user


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", default="andritz")
    parser.add_argument(
        "--collection",
        default=DEFAULT_NOTICE_COLLECTION,
        choices=[DEFAULT_NOTICE_COLLECTION],
        help="Authoritative transverse Andritz collection (fixed)",
    )
    parser.add_argument(
        "--profile",
        default="needlepunch",
        choices=sorted(NOTICE_SOURCE_PROFILES),
    )
    parser.add_argument(
        "--campaign",
        default="direct",
        choices=("direct", "legacy", "zip"),
        help="Explicit format campaign; direct is the safe default",
    )
    parser.add_argument(
        "--prefix",
        dest="source_prefix",
        help=(
            "Optional SFTP prefix below Notices_Techniques_Needlepunch/; "
            "the exact value is covered by the plan hash"
        ),
    )
    selectors = parser.add_mutually_exclusive_group(required=True)
    selectors.add_argument(
        "--project",
        action="append",
        dest="projects",
        help="Exact five-digit project code; repeat to select several projects",
    )
    selectors.add_argument(
        "--range",
        dest="project_range",
        help="Inclusive five-digit range, for example 60000-69999",
    )
    parser.add_argument("--dry-run", action="store_true", help="Plan only (default)")
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Omit the per-deposit classification list from dry-run JSON",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        workspace = db.query(Workspace).filter(Workspace.slug == args.workspace).first()
        if not workspace:
            raise SystemExit(f"Workspace not found: {args.workspace}")
        plan = build_notice_wave_plan(
            db,
            workspace=workspace,
            collection_slug=args.collection,
            profile_slug=args.profile,
            campaign=args.campaign,
            source_prefix=args.source_prefix,
            projects=args.projects,
            project_range=args.project_range,
        )
        print(
            json.dumps(
                {"mode": "dry-run", "plan": plan.as_dict(
                    include_items=not args.summary_only
                )},
                ensure_ascii=False,
                indent=2,
            )
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
