"""Seed the SENTINEL-CI demo workspace.

Usage:
    poetry run python -m app.cli.seed_sentinel_ci
"""
from __future__ import annotations

from app.db.base import SessionLocal
from app.services.mission_room import ensure_sentinel_ci_workspace
from app.services.skills_registry import seed_skills_and_capabilities


def main() -> None:
    with SessionLocal() as db:
        registry_report = seed_skills_and_capabilities(db)
        sentinel_report = ensure_sentinel_ci_workspace(db)
    print({"registry": registry_report, "sentinel_ci": sentinel_report})


if __name__ == "__main__":
    main()
