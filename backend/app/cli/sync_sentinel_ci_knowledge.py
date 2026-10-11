"""Synchronize SENTINEL-CI workspace sources into canonical RAG collections.

Usage:
    poetry run python -m app.cli.sync_sentinel_ci_knowledge
"""
from __future__ import annotations

import asyncio

from app.db.base import SessionLocal
from app.models.workspace import Workspace
from app.services.intelligence.batch import get_dashboard_data
from app.services.intelligence.knowledge_sync import sync_intelligence_to_knowledge
from app.services.mission_room import SENTINEL_WORKSPACE_SLUG, ensure_sentinel_ci_workspace
from app.services.mission_room_knowledge_sync import (
    sync_mission_room_fixtures_to_knowledge,
    sync_visual_observations_to_knowledge,
)
from app.services.skills_registry import seed_skills_and_capabilities
from app.services.systems.bootstrap import ensure_workspace_chat_system_default


async def _main() -> None:
    with SessionLocal() as db:
        seed_skills_and_capabilities(db)
        ensure_sentinel_ci_workspace(db)
        workspace = db.query(Workspace).filter_by(slug=SENTINEL_WORKSPACE_SLUG).one()
        ensure_workspace_chat_system_default(db, workspace.id)

        fixture_result = await sync_mission_room_fixtures_to_knowledge(db, workspace)
        intelligence_result = await sync_intelligence_to_knowledge(
            db,
            workspace,
            dashboard_payload=get_dashboard_data(db, workspace_id=workspace.id),
        )
        visual_result = await sync_visual_observations_to_knowledge(db, workspace)

    print(
        {
            "fixtures": fixture_result,
            "open_intelligence": intelligence_result,
            "visual_intelligence": visual_result,
        }
    )


if __name__ == "__main__":
    asyncio.run(_main())
