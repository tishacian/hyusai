"""Refresh the SENTINEL-CI macro indicators cache (Phase B).

Usage:
    poetry run python -m app.cli.refresh_macro_indicators [--force]
"""
from __future__ import annotations

import argparse

from app.db.base import SessionLocal
from app.models.workspace import Workspace
from app.services.macro_indicators import fetch_civ_indicators
from app.services.mission_room import SENTINEL_WORKSPACE_SLUG


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="Force refresh (ignore TTL).")
    args = parser.parse_args()

    with SessionLocal() as db:
        workspace = db.query(Workspace).filter(Workspace.slug == SENTINEL_WORKSPACE_SLUG).first()
        if not workspace:
            print({"workspace": "missing"})
            return
        result = fetch_civ_indicators(db, workspace, force=args.force)
    print(result)


if __name__ == "__main__":
    main()
