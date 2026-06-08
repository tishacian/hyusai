"""Seed the SENTINEL-CI demo workspace.

Usage:
    poetry run python -m app.cli.seed_sentinel_ci
"""
from __future__ import annotations

from app.db.base import SessionLocal
from app.models.workspace import Workspace
from app.services.mission_room import SENTINEL_WORKSPACE_SLUG, ensure_sentinel_ci_workspace
from app.services.skills_registry import seed_skills_and_capabilities
from app.services.systems.bootstrap import ensure_workspace_chat_system_default


def main() -> None:
    with SessionLocal() as db:
        registry_report = seed_skills_and_capabilities(db)
        sentinel_report = ensure_sentinel_ci_workspace(db)
        workspace = db.query(Workspace).filter_by(slug=SENTINEL_WORKSPACE_SLUG).one()
        chat_system = ensure_workspace_chat_system_default(db, workspace.id)
    print(
        {
            "registry": registry_report,
            "sentinel_ci": sentinel_report,
            "workspace_chat_system": chat_system.id if chat_system else None,
        }
    )


if __name__ == "__main__":
    main()
