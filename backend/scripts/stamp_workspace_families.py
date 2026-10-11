"""Deprecated compatibility command for pre-058 family stamping.

The family used to be inferred per-request by substring matching on the
workspace slug/name. This script persists the inferred family into workspace
settings so exact resolution (app/services/workspace_features.py) takes over.
Migration 058 now owns this one-shot, reversible transition. This command is
kept only for deployments pinned before 058:

    cd backend
    python -m scripts.stamp_workspace_families [--dry-run]

Idempotent: workspaces already stamped with a known family are left untouched.
"""

from __future__ import annotations

import argparse

from sqlalchemy.orm.attributes import flag_modified

from app.db.base import SessionLocal
from app.models.workspace import Workspace
from app.services.workspace_features import KNOWN_FAMILIES


def _pre_058_family(workspace: Workspace) -> str:
    """Frozen compatibility snapshot; never imported by application runtime."""

    slug = str(workspace.slug or "").lower()
    name = str(workspace.name or "").lower()
    if "andritz" in slug or "andritz" in name:
        return "andritz"
    if slug == "sentinel-ci" or "sentinel" in slug:
        return "sentinel_ci"
    return "generic"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Report without writing")
    args = parser.parse_args()

    db = SessionLocal()
    stamped = 0
    skipped = 0
    try:
        workspaces = db.query(Workspace).filter(Workspace.deleted_at.is_(None)).all()
        for workspace in workspaces:
            settings = dict(workspace.settings or {})
            current = str(settings.get("family") or "").strip().lower()
            if current in KNOWN_FAMILIES:
                skipped += 1
                continue
            family = _pre_058_family(workspace)
            print(f"stamp workspace={workspace.slug} family={family}")
            if not args.dry_run:
                settings["family"] = family
                workspace.settings = settings
                flag_modified(workspace, "settings")
            stamped += 1
        if not args.dry_run:
            db.commit()
        print(f"done stamped={stamped} skipped={skipped} dry_run={args.dry_run}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
