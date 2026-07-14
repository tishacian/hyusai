from __future__ import annotations

import pytest

from app.cli.seed_octocity_mission_room import (
    OCTOCITY_SEEDED_SYSTEM_NAMES,
    list_octocity_seeded_system_ids,
    pause_octocity_seeded_systems,
)
from app.models.system import System
from app.models.workspace import Workspace


def test_pause_octocity_seeded_systems_is_targeted_and_fail_closed(db_session) -> None:
    workspace = Workspace(
        id="workspace-octocity-rollback",
        slug="octocity-mission-room",
        name="Octocity Mission Room",
        mode="demo",
    )
    seeded = [
        System(
            id=f"seeded-{index}",
            workspace_id=workspace.id,
            name=name,
            status="active",
            created_by="system:octocity_seed",
        )
        for index, name in enumerate(OCTOCITY_SEEDED_SYSTEM_NAMES)
    ]
    reused = System(
        id="reused-octocity-system",
        workspace_id=workspace.id,
        name="OCTAVE Mission Room",
        status="active",
        created_by="existing-operator",
    )
    unrelated = System(
        id="seeded-but-unrelated",
        workspace_id=workspace.id,
        name="Workspace Chat",
        status="active",
        created_by="system:octocity_seed",
    )
    db_session.add_all([workspace, *seeded, reused, unrelated])
    db_session.commit()

    assert list_octocity_seeded_system_ids(db_session) == sorted(
        system.id for system in seeded
    )
    with pytest.raises(ValueError, match="missing, foreign, or in a mixed state"):
        pause_octocity_seeded_systems(
            db_session,
            system_ids=[seeded[0].id, reused.id, unrelated.id],
        )
    assert all(system.status == "active" for system in seeded)

    selected_ids = [seeded[0].id, seeded[2].id]
    first = pause_octocity_seeded_systems(
        db_session,
        system_ids=selected_ids,
    )
    second = pause_octocity_seeded_systems(
        db_session,
        system_ids=selected_ids,
    )

    assert first == {
        "workspace_slug": "octocity-mission-room",
        "paused": sorted([seeded[0].name, seeded[2].name]),
        "paused_ids": sorted(selected_ids),
        "already_paused": False,
    }
    assert second == {**first, "already_paused": True}
    with pytest.raises(ValueError, match="mixed state"):
        pause_octocity_seeded_systems(
            db_session,
            system_ids=[seeded[0].id, seeded[1].id],
        )
    assert seeded[0].status == "paused"
    assert seeded[1].status == "active"
    assert seeded[2].status == "paused"
    assert seeded[3].status == "active"
    assert reused.status == "active"
    assert unrelated.status == "active"


def test_pause_octocity_seeded_systems_fails_when_workspace_is_absent(
    db_session,
) -> None:
    assert list_octocity_seeded_system_ids(db_session) == []
    with pytest.raises(ValueError, match="missing, foreign, or in a mixed state"):
        pause_octocity_seeded_systems(db_session, system_ids=["missing"])
