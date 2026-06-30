"""Seed the Octocity Mission Room demo workspace.

Usage:
    poetry run python -m app.cli.seed_octocity_mission_room
"""
from __future__ import annotations

from app.db.base import SessionLocal
from app.services.mission_room import ensure_octocity_mission_room_workspace
from app.services.skills_registry import seed_skills_and_capabilities


def main() -> None:
    with SessionLocal() as db:
        registry_report = seed_skills_and_capabilities(db)
        octocity_report = ensure_octocity_mission_room_workspace(db)
    print(
        {
            "registry": registry_report,
            "octocity_mission_room": octocity_report,
        }
    )


if __name__ == "__main__":
    main()
