"""Migration contract tests for the Nawa Studio appearance (113).

The Agent Studio skin left the shared styles (ADR 0003 lot 2); the look it had
is now the workspace appearance of ``nawa``. Same claims as 065 and 085:
additive, idempotent, blind to every other workspace, and an appearance an
operator declared is not ours to replace or remove.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from copy import deepcopy
from pathlib import Path

import pytest
import sqlalchemy as sa

from app.schemas.brand_appearance import validate_appearance


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


MIG = _load("migration_113", "113_nawa_studio_appearance.py")

# The brand 065 and 085 leave on the workspace.
BRAND = {
    "label": "NAWA",
    "emblem": "/assets/nawa/nawa-logo.png",
    "emblem_light": "/assets/nawa/nawa-logo-transparent.png",
    "home": "/nawa/itsd",
}


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


def _settings(bind, workspaces, workspace_id="workspace-nawa"):
    return bind.execute(
        sa.select(workspaces.c.settings).where(workspaces.c.id == workspace_id)
    ).scalar_one()


def _seed(bind, workspaces, settings, *, slug=None, workspace_id="workspace-nawa"):
    bind.execute(
        workspaces.insert(),
        {"id": workspace_id, "slug": slug or MIG.NAWA_SLUG, "settings": settings},
    )


def test_the_appearance_is_one_the_product_accepts():
    assert validate_appearance(MIG.APPEARANCE) == MIG.APPEARANCE


def test_upgrade_without_a_nawa_workspace_is_a_no_op(bind):
    _schema(bind)
    MIG.upgrade()
    MIG.downgrade()


def test_upgrade_without_a_brand_gives_none(bind):
    workspaces = _schema(bind)
    _seed(bind, workspaces, {"features": {"experience_v1": True}})

    MIG.upgrade()

    assert _settings(bind, workspaces) == {"features": {"experience_v1": True}}


def test_upgrade_declares_the_studio_appearance_and_nothing_else(bind):
    workspaces = _schema(bind)
    other = {"navigation_profile": {"key": "standard"}, "demo_safe": True}
    _seed(bind, workspaces, {"platform_brand": deepcopy(BRAND), **deepcopy(other)})

    MIG.upgrade()

    settings = _settings(bind, workspaces)
    assert settings["platform_brand"] == {**BRAND, "appearance": MIG.APPEARANCE}
    assert {k: v for k, v in settings.items() if k != "platform_brand"} == other


def test_upgrade_is_idempotent(bind):
    workspaces = _schema(bind)
    _seed(bind, workspaces, {"platform_brand": deepcopy(BRAND)})

    MIG.upgrade()
    first = deepcopy(_settings(bind, workspaces))
    MIG.upgrade()

    assert _settings(bind, workspaces) == first


def test_an_operator_appearance_is_kept_both_ways(bind):
    workspaces = _schema(bind)
    authored = {**deepcopy(BRAND), "appearance": {"palette": "sand", "accent": "#c62f00"}}
    _seed(bind, workspaces, {"platform_brand": deepcopy(authored)})

    MIG.upgrade()
    assert _settings(bind, workspaces)["platform_brand"] == authored

    MIG.downgrade()
    assert _settings(bind, workspaces)["platform_brand"] == authored


def test_upgrade_ignores_every_other_workspace(bind):
    workspaces = _schema(bind)
    _seed(bind, workspaces, {"platform_brand": deepcopy(BRAND)})
    _seed(
        bind,
        workspaces,
        {"platform_brand": deepcopy(BRAND)},
        slug="agentium-showcase",
        workspace_id="workspace-other",
    )

    MIG.upgrade()

    assert "appearance" in _settings(bind, workspaces)["platform_brand"]
    assert _settings(bind, workspaces, "workspace-other")["platform_brand"] == BRAND


def test_downgrade_restores_the_brand_it_found(bind):
    workspaces = _schema(bind)
    _seed(bind, workspaces, {"platform_brand": deepcopy(BRAND)})

    MIG.upgrade()
    MIG.downgrade()

    assert _settings(bind, workspaces)["platform_brand"] == BRAND
