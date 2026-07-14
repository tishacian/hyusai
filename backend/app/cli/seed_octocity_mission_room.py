"""Seed the Octocity Mission Room demo workspace.

Usage:
    poetry run python -m app.cli.seed_octocity_mission_room
    poetry run python -m app.cli.seed_octocity_mission_room --list-seeded-system-ids
    poetry run python -m app.cli.seed_octocity_mission_room \
        --pause-seeded-systems --system-id <id>
"""
from __future__ import annotations

import argparse

from app.db.base import SessionLocal
from app.models.system import System
from app.models.workspace import Workspace
from app.services.mission_room import ensure_octocity_mission_room_workspace
from app.services.skills_registry import seed_skills_and_capabilities

OCTOCITY_WORKSPACE_SLUG = "octocity-mission-room"
OCTOCITY_SEEDED_SYSTEM_NAMES = (
    "OCTAVE Mission Room",
    "OCTAVE Territorial Map",
    "OCTAVE Open Intelligence",
    "OCTAVE Decision Desk",
)


def _octocity_seeded_systems_query(db):
    workspace = (
        db.query(Workspace)
        .filter(Workspace.slug == OCTOCITY_WORKSPACE_SLUG)
        .first()
    )
    if workspace is None:
        return None, None
    return workspace, db.query(System).filter(
        System.workspace_id == workspace.id,
        System.created_by == "system:octocity_seed",
        System.name.in_(OCTOCITY_SEEDED_SYSTEM_NAMES),
    )


def list_octocity_seeded_system_ids(db) -> list[str]:
    _, query = _octocity_seeded_systems_query(db)
    if query is None:
        return []
    return sorted(system.id for system in query.all())


def pause_octocity_seeded_systems(
    db,
    *,
    system_ids: list[str],
) -> dict[str, object]:
    """Pause only Systems created by this seed; never mutate reused Systems."""
    requested_ids = sorted(set(system_ids))
    workspace, query = _octocity_seeded_systems_query(db)
    if workspace is None or query is None:
        raise ValueError(
            "requested Octocity seed Systems are missing, foreign, or in a mixed state"
        )

    systems = query.filter(System.id.in_(requested_ids)).all()
    statuses = {system.status for system in systems}
    if {system.id for system in systems} != set(requested_ids) or statuses not in (
        {"active"},
        {"paused"},
    ):
        raise ValueError(
            "requested Octocity seed Systems are missing, foreign, or in a mixed state"
        )
    paused = sorted(system.name for system in systems)
    paused_ids = sorted(system.id for system in systems)
    already_paused = statuses == {"paused"}
    if not already_paused:
        for system in systems:
            system.status = "paused"
        db.commit()
    return {
        "workspace_slug": workspace.slug,
        "paused": paused,
        "paused_ids": paused_ids,
        "already_paused": already_paused,
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pause-seeded-systems",
        action="store_true",
        help="pause selected OCTAVE Systems created by this seed",
    )
    parser.add_argument(
        "--system-id",
        action="append",
        default=[],
        help="seed-created System id to pause; repeat for each id",
    )
    parser.add_argument(
        "--list-seeded-system-ids",
        action="store_true",
        help="print one seed-created OCTAVE System id per line",
    )
    args = parser.parse_args(argv)
    if args.pause_seeded_systems and not args.system_id:
        parser.error("--pause-seeded-systems requires at least one --system-id")
    if args.list_seeded_system_ids and args.pause_seeded_systems:
        parser.error("list and pause modes are mutually exclusive")
    with SessionLocal() as db:
        if args.list_seeded_system_ids:
            for system_id in list_octocity_seeded_system_ids(db):
                print(system_id)
            return
        if args.pause_seeded_systems:
            print(
                {
                    "octocity_mission_room_rollback": pause_octocity_seeded_systems(
                        db,
                        system_ids=args.system_id,
                    )
                }
            )
            return
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
