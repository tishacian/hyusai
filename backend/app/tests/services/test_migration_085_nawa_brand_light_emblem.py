"""Migration contract tests for the Nawa light-surface emblem (085).

Same three claims as 065, whose brand this revision extends: additive,
idempotent, and blind to every other workspace — plus the one that is specific
here, that a brand an operator authored is not ours to enrich.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from copy import deepcopy
from pathlib import Path

import pytest
import sqlalchemy as sa


def _load(name: str, filename: str):
    path = Path(__file__).resolve().parents[3] / "alembic" / "versions" / filename
    saved = sys.modules.get("alembic")
    stub = types.ModuleType("alembic")
    stub.op = types.SimpleNamespace(get_bind=lambda: None)
    sys.modules["alembic"] = stub
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        if saved is not None:
            sys.modules["alembic"] = saved
        else:
            sys.modules.pop("alembic", None)
    return mod


MIG = _load("migration_085", "085_nawa_brand_light_emblem.py")
MIG_065 = _load("migration_065_for_085", "065_nawa_itsd.py")


def _schema(bind):
    metadata = sa.MetaData()
    workspaces = sa.Table(
        "workspaces",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("slug", sa.String(100), nullable=False, unique=True),
        sa.Column("settings", sa.JSON()),
    )
    metadata.create_all(bind)
    return workspaces


@pytest.fixture()
def bind(monkeypatch):
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        monkeypatch.setattr(MIG, "op", types.SimpleNamespace(get_bind=lambda: connection))
        yield connection


def _brand(bind, workspaces, workspace_id="workspace-nawa"):
    return bind.execute(
        sa.select(workspaces.c.settings).where(workspaces.c.id == workspace_id)
    ).scalar_one().get("platform_brand")


def _seed(bind, workspaces, settings, *, slug=None, workspace_id="workspace-nawa"):
    bind.execute(
        workspaces.insert(),
        {"id": workspace_id, "slug": slug or MIG.NAWA_SLUG, "settings": settings},
    )


def test_upgrade_without_a_nawa_workspace_is_a_no_op(bind):
    """The workspace is created by the operator, possibly after this runs."""
    _schema(bind)
    MIG.upgrade()  # must not raise
    MIG.downgrade()  # nor this


def test_upgrade_without_a_brand_is_a_no_op(bind):
    """065 may not have run its seeding half — no brand, nothing to vary."""
    workspaces = _schema(bind)
    _seed(bind, workspaces, {"features": {"voice": True}})

    MIG.upgrade()

    settings = bind.execute(
        sa.select(workspaces.c.settings).where(workspaces.c.id == "workspace-nawa")
    ).scalar_one()
    assert settings == {"features": {"voice": True}}


def test_upgrade_adds_the_light_variant_to_the_brand_we_wrote(bind):
    workspaces = _schema(bind)
    _seed(bind, workspaces, {"platform_brand": deepcopy(MIG_065.PLATFORM_BRAND)})

    MIG.upgrade()

    brand = _brand(bind, workspaces)
    assert brand["emblem_light"] == MIG.EMBLEM_LIGHT
    # Purely additive: the identity 065 declared is untouched.
    assert {k: v for k, v in brand.items() if k != "emblem_light"} == MIG_065.PLATFORM_BRAND


def test_upgrade_touches_nothing_but_the_brand(bind):
    workspaces = _schema(bind)
    other_keys = {
        "features": {"rpa_bridge": False},
        "navigation_profile": {"key": "standard", "primary_surfaces": ["chat"]},
        "demo_safe": True,
    }
    _seed(
        bind,
        workspaces,
        {"platform_brand": deepcopy(MIG_065.PLATFORM_BRAND), **deepcopy(other_keys)},
    )

    MIG.upgrade()

    settings = bind.execute(
        sa.select(workspaces.c.settings).where(workspaces.c.id == "workspace-nawa")
    ).scalar_one()
    assert {k: v for k, v in settings.items() if k != "platform_brand"} == other_keys


def test_upgrade_is_idempotent(bind):
    workspaces = _schema(bind)
    _seed(bind, workspaces, {"platform_brand": deepcopy(MIG_065.PLATFORM_BRAND)})

    MIG.upgrade()
    first = deepcopy(_brand(bind, workspaces))
    MIG.upgrade()

    assert _brand(bind, workspaces) == first


def test_upgrade_leaves_an_operator_authored_brand_alone(bind):
    """A brand we did not write is not ours to enrich: the operator chose that
    artwork, and adding a second one behind their back would change what the
    title bar shows on half the theme range."""
    workspaces = _schema(bind)
    authored = {
        "label": "NAWA",
        "emblem": "/assets/nawa/operator-choice.png",
        "home": "/nawa/itsd",
    }
    _seed(bind, workspaces, {"platform_brand": deepcopy(authored)})

    MIG.upgrade()
    assert _brand(bind, workspaces) == authored

    # ...and what we did not write is not ours to remove either.
    MIG.downgrade()
    assert _brand(bind, workspaces) == authored


def test_upgrade_keeps_an_operator_authored_light_variant(bind):
    """The operator already answered the question this migration asks."""
    workspaces = _schema(bind)
    authored = {**deepcopy(MIG_065.PLATFORM_BRAND), "emblem_light": "/assets/nawa/theirs.svg"}
    _seed(bind, workspaces, {"platform_brand": deepcopy(authored)})

    MIG.upgrade()
    assert _brand(bind, workspaces) == authored

    MIG.downgrade()
    assert _brand(bind, workspaces) == authored


def test_upgrade_ignores_every_other_workspace(bind):
    """The brand is per-workspace and so is its light variant."""
    workspaces = _schema(bind)
    _seed(bind, workspaces, {"platform_brand": deepcopy(MIG_065.PLATFORM_BRAND)})
    # Same brand payload, different workspace: slug is the only thing that says
    # whose brand this is.
    _seed(
        bind,
        workspaces,
        {"platform_brand": deepcopy(MIG_065.PLATFORM_BRAND)},
        slug="andritz",
        workspace_id="workspace-other",
    )

    MIG.upgrade()

    assert "emblem_light" in _brand(bind, workspaces)
    assert _brand(bind, workspaces, "workspace-other") == MIG_065.PLATFORM_BRAND


def test_downgrade_restores_the_brand_065_recognises_as_its_own(bind):
    """065's downgrade removes the brand only when it still equals its literal.
    Downgrading in revision order must hand it back exactly that."""
    workspaces = _schema(bind)
    _seed(bind, workspaces, {"platform_brand": deepcopy(MIG_065.PLATFORM_BRAND)})

    MIG.upgrade()
    MIG.downgrade()

    assert _brand(bind, workspaces) == MIG_065.PLATFORM_BRAND


def test_downgrade_is_idempotent(bind):
    workspaces = _schema(bind)
    _seed(bind, workspaces, {"platform_brand": deepcopy(MIG_065.PLATFORM_BRAND)})

    MIG.upgrade()
    MIG.downgrade()
    MIG.downgrade()

    assert _brand(bind, workspaces) == MIG_065.PLATFORM_BRAND


def test_the_light_variant_points_at_a_file_that_ships(bind):
    """A brand pointing at a 404 would show a broken image in the title bar."""
    asset = (
        Path(__file__).resolve().parents[4]
        / "frontend-ng"
        / "src"
        / MIG.EMBLEM_LIGHT.lstrip("/")
    )
    assert asset.is_file(), asset
