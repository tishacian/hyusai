from __future__ import annotations

import pytest

from app.cli import seed_agentium_video_demo as video_seed
from app.models.capability import Capability
from app.models.system import System
from app.models.workspace import Workspace
from app.services.seed_catalog_safety import (
    SeedCatalogCollisionError,
    SeedWorkspaceBoundaryError,
    owned_capability_for_seed,
    visible_capability_for_seed,
)
from scripts import seed_hana_demo_flow as hana_seed
from scripts import seed_showcase_workspace as showcase_seed


def _workspace(identifier: str) -> Workspace:
    return Workspace(id=identifier, slug=identifier, name=identifier)


@pytest.mark.parametrize("foreign_owner", [None, "workspace-foreign"])
def test_owned_seed_lookup_never_adopts_global_or_foreign_capability(
    db_session,
    foreign_owner,
):
    target = _workspace("workspace-seed-target")
    if foreign_owner is not None:
        db_session.add(_workspace(foreign_owner))
    collision = Capability(
        id="capability-seed-collision",
        workspace_id=foreign_owner,
        slug="video_contract_risk",
        name="Do not mutate",
        description="foreign payload",
    )
    db_session.add_all([target, collision])
    db_session.commit()

    with pytest.raises(SeedCatalogCollisionError, match="seed refused"):
        owned_capability_for_seed(
            db_session,
            workspace=target,
            slug=collision.slug,
        )

    db_session.refresh(collision)
    assert collision.workspace_id == foreign_owner
    assert collision.name == "Do not mutate"


def test_video_seed_refuses_slug_collision_without_reparenting(db_session):
    target = _workspace("workspace-video-target")
    foreign = _workspace("workspace-video-foreign")
    system = System(
        id="system-video-target",
        workspace_id=target.id,
        name="Contract Risk Copilot",
        objective="test",
    )
    collision = Capability(
        id="capability-video-foreign",
        workspace_id=foreign.id,
        slug="video_contract_risk",
        name="Foreign capability",
    )
    db_session.add_all([target, foreign, system, collision])
    db_session.commit()

    with pytest.raises(SeedCatalogCollisionError):
        video_seed._ensure_video_capability(
            db_session,
            target,
            dict(video_seed.PORTFOLIO_RUNS[-1]),
            system,
        )

    db_session.refresh(collision)
    assert collision.workspace_id == foreign.id
    assert collision.name == "Foreign capability"
    assert system.capability_id is None


def test_showcase_seed_refuses_global_collision_before_overwrite(db_session):
    target = _workspace("workspace-showcase-target")
    collision = Capability(
        id="capability-showcase-global",
        workspace_id=None,
        slug=showcase_seed.CAPABILITIES[0]["slug"],
        name="Global capability",
        description="must remain byte-for-byte owned by global catalog",
    )
    db_session.add_all([target, collision])
    db_session.commit()

    with pytest.raises(SeedCatalogCollisionError):
        showcase_seed.ensure_capabilities(db_session, target)

    db_session.refresh(collision)
    assert collision.workspace_id is None
    assert collision.name == "Global capability"


def test_showcase_seed_refuses_to_adopt_an_existing_unmarked_workspace(db_session):
    target = Workspace(
        id="workspace-showcase-boundary",
        slug="operator-controlled-slug",
        name="Andritz must remain untouched",
        mode="builder",
        settings={"family": "andritz", "features": {"value_loop_v1": True}},
    )
    db_session.add(target)
    db_session.commit()

    with pytest.raises(SeedWorkspaceBoundaryError, match="not structurally owned"):
        showcase_seed.ensure_workspace(
            db_session,
            target.slug,
            "Attacker-selected Showcase name",
        )

    db_session.refresh(target)
    assert target.name == "Andritz must remain untouched"
    assert target.mode == "builder"
    assert target.settings == {
        "family": "andritz",
        "features": {"value_loop_v1": True},
    }


def test_showcase_seed_cli_exposes_no_destructive_reset(monkeypatch):
    monkeypatch.setattr(
        showcase_seed.sys,
        "argv",
        ["seed_showcase_workspace", "--owner-email", "owner@example.test", "--reset"],
    )
    with pytest.raises(SystemExit) as rejected:
        showcase_seed.parse_args()
    assert rejected.value.code == 2


def test_hana_seed_requires_preexisting_showcase_marker_before_any_mutation(
    db_session,
    monkeypatch,
):
    target = Workspace(
        id="workspace-hana-boundary",
        slug="andritz-selected-by-operator",
        name="Andritz",
        mode="builder",
        settings={"family": "andritz"},
    )
    db_session.add(target)
    db_session.commit()
    seeded_registry = False

    def forbidden_registry_seed(_db):
        nonlocal seeded_registry
        seeded_registry = True

    monkeypatch.setattr(hana_seed, "seed_skills_and_capabilities", forbidden_registry_seed)

    with pytest.raises(SeedWorkspaceBoundaryError, match="not structurally owned"):
        hana_seed.ensure_hana_demo(
            db_session,
            target,
            configure_connector=False,
        )

    db_session.refresh(target)
    assert seeded_registry is False
    assert target.settings == {"family": "andritz"}
    assert db_session.query(Capability).count() == 0
    assert db_session.query(System).count() == 0


def test_hana_seed_refuses_foreign_collision_without_reparenting(db_session, monkeypatch):
    target = _workspace("workspace-hana-target")
    foreign = _workspace("workspace-hana-foreign")
    collision = Capability(
        id="capability-hana-foreign",
        workspace_id=foreign.id,
        slug=hana_seed.HANA_CAPABILITY_SLUG,
        name="Foreign HANA capability",
        description="must remain owned by the foreign workspace",
    )
    db_session.add_all([target, foreign, collision])
    db_session.commit()
    monkeypatch.setattr(hana_seed, "_skill_ids", lambda _db, _slugs: [])

    with pytest.raises(SeedCatalogCollisionError):
        hana_seed.ensure_hana_capability(db_session, target)

    db_session.refresh(collision)
    assert collision.workspace_id == foreign.id
    assert collision.name == "Foreign HANA capability"


def test_visible_seed_binding_allows_unhidden_universal_and_rejects_foreign(db_session):
    target = _workspace("workspace-visible-target")
    foreign = _workspace("workspace-visible-foreign")
    universal = Capability(
        id="capability-visible-global",
        workspace_id=None,
        slug="expert_knowledge_capture",
        name="Universal Knowledge Capture",
        tier="universal",
    )
    db_session.add_all([target, foreign, universal])
    db_session.commit()

    assert (
        visible_capability_for_seed(
            db_session,
            workspace=target,
            slug=universal.slug,
        )
        is universal
    )

    universal.workspace_id = foreign.id
    db_session.commit()
    with pytest.raises(SeedCatalogCollisionError, match="not visible"):
        visible_capability_for_seed(
            db_session,
            workspace=target,
            slug=universal.slug,
        )
