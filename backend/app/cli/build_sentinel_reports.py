"""Build the SENTINEL-CI PDF reports used by the AYA demo (Phase F).

Usage:
    poetry run python -m app.cli.build_sentinel_reports [--force]
"""
from __future__ import annotations

import argparse

from app.db.base import SessionLocal
from app.models.workspace import Workspace
from app.services.mission_room import SENTINEL_WORKSPACE_SLUG
from app.services.sentinel_ci_reports import (
    build_prefet_report_pdf,
    ensure_prefet_report_in_object_store,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="Force regeneration.")
    args = parser.parse_args()

    build_result = build_prefet_report_pdf(force=args.force)
    print({"prefet_pdf": build_result})

    with SessionLocal() as db:
        workspace = db.query(Workspace).filter(Workspace.slug == SENTINEL_WORKSPACE_SLUG).first()
        if not workspace:
            print({"workspace": "missing", "skipped_object_store": True})
            return
        store_result = ensure_prefet_report_in_object_store(db, workspace)
        print({"object_store": store_result})


if __name__ == "__main__":
    main()
