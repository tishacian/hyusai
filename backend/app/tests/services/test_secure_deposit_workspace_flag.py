"""Secure Deposit is enabled per workspace, and by nothing else.

The capability used to fall back to a comma-separated list of slugs in global
config, which made one customer's feature a property of the deployment.
Migration 110 stamps what that list answered onto every workspace so the
setting can become the only source of truth.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from uuid import uuid4

import sqlalchemy as sa

from app.models.workspace import Workspace
from app.services.secure_deposit import is_workspace_enabled

MIGRATION = (
    Path(__file__).resolve().parents[3]
    / "alembic"
    / "versions"
    / "110_secure_deposit_workspace_flag.py"
)


def _workspace(slug: str, settings: dict | None) -> Workspace:
    return Workspace(id=str(uuid4()), name=slug, slug=slug, settings=settings)


def test_only_the_workspace_setting_decides():
    assert is_workspace_enabled(_workspace("acme", {"features": {"secure_deposit": True}}))
    assert not is_workspace_enabled(
        _workspace("acme", {"features": {"secure_deposit": False}})
    )


def test_a_workspace_that_was_named_by_the_old_list_is_no_longer_special():
    """The slug used to be enough. It is not, which is the point of the change."""

    assert not is_workspace_enabled(_workspace("andritz", {}))
    assert not is_workspace_enabled(_workspace("andritz", None))


def _load_migration(monkeypatch, bind):
    spec = importlib.util.spec_from_file_location("migration_110_unit", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    sys.modules["migration_110_unit"] = module
    spec.loader.exec_module(module)

    class _Op:
        @staticmethod
        def get_bind():
            return bind

    monkeypatch.setattr(module, "op", _Op)
    return module


def _table(metadata: sa.MetaData) -> sa.Table:
    return sa.Table(
        "workspaces",
        metadata,
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("slug", sa.String(length=100)),
        sa.Column("settings", sa.JSON()),
    )


def test_the_migration_stamps_what_the_old_list_answered(monkeypatch):
    engine = sa.create_engine("sqlite://")
    metadata = sa.MetaData()
    workspaces = _table(metadata)
    with engine.begin() as bind:
        metadata.create_all(bind)
        bind.execute(
            workspaces.insert(),
            [
                {"id": "w-named", "slug": "andritz", "settings": {}},
                {"id": "w-other", "slug": "acme", "settings": {"mode": "builder"}},
                {
                    "id": "w-decided",
                    "slug": "beta",
                    "settings": {"features": {"secure_deposit": True}},
                },
            ],
        )

        module = _load_migration(monkeypatch, bind)
        monkeypatch.delenv(module.ENV_VAR, raising=False)
        module.upgrade()

        rows = {
            r._mapping["id"]: r._mapping["settings"]
            for r in bind.execute(sa.select(workspaces.c.id, workspaces.c.settings))
        }

    assert rows["w-named"]["features"]["secure_deposit"] is True
    assert rows["w-other"]["features"]["secure_deposit"] is False
    assert rows["w-other"]["mode"] == "builder"  # untouched
    # An explicit decision is never overwritten, and carries no marker.
    assert rows["w-decided"]["features"]["secure_deposit"] is True
    assert module.MARKER_KEY not in rows["w-decided"]


def test_the_migration_honours_a_deployment_that_changed_the_list(monkeypatch):
    engine = sa.create_engine("sqlite://")
    metadata = sa.MetaData()
    workspaces = _table(metadata)
    with engine.begin() as bind:
        metadata.create_all(bind)
        bind.execute(
            workspaces.insert(),
            [
                {"id": "w-a", "slug": "andritz", "settings": {}},
                {"id": "w-b", "slug": "nawa", "settings": {}},
            ],
        )
        module = _load_migration(monkeypatch, bind)
        monkeypatch.setenv(module.ENV_VAR, "nawa")
        module.upgrade()
        rows = {
            r._mapping["id"]: r._mapping["settings"]
            for r in bind.execute(sa.select(workspaces.c.id, workspaces.c.settings))
        }

    assert rows["w-b"]["features"]["secure_deposit"] is True
    assert rows["w-a"]["features"]["secure_deposit"] is False


def test_the_downgrade_removes_exactly_what_it_wrote(monkeypatch):
    engine = sa.create_engine("sqlite://")
    metadata = sa.MetaData()
    workspaces = _table(metadata)
    with engine.begin() as bind:
        metadata.create_all(bind)
        bind.execute(
            workspaces.insert(),
            [
                {"id": "w-named", "slug": "andritz", "settings": {}},
                {
                    "id": "w-decided",
                    "slug": "beta",
                    "settings": {"features": {"secure_deposit": True}},
                },
            ],
        )
        module = _load_migration(monkeypatch, bind)
        monkeypatch.delenv(module.ENV_VAR, raising=False)
        module.upgrade()
        module.downgrade()
        rows = {
            r._mapping["id"]: r._mapping["settings"]
            for r in bind.execute(sa.select(workspaces.c.id, workspaces.c.settings))
        }

    assert rows["w-named"] == {}  # back to where it started
    assert rows["w-decided"] == {"features": {"secure_deposit": True}}  # never ours
