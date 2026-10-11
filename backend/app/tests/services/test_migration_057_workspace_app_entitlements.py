"""Migration contract tests for explicit workspace app entitlements (057)."""
from __future__ import annotations

import importlib.util
import sys
import types
from copy import deepcopy
from pathlib import Path

import pytest
import sqlalchemy as sa


def _load_migration():
    path = (
        Path(__file__).resolve().parents[3]
        / "alembic"
        / "versions"
        / "057_workspace_app_entitlements.py"
    )
    saved = sys.modules.get("alembic")
    stub = types.ModuleType("alembic")
    stub.op = types.SimpleNamespace(get_bind=lambda: None)
    sys.modules["alembic"] = stub
    try:
        spec = importlib.util.spec_from_file_location("migration_057", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        if saved is not None:
            sys.modules["alembic"] = saved
        else:
            sys.modules.pop("alembic", None)
    return mod


MIG = _load_migration()


class _SQLiteOps:
    """Small Alembic-op adapter exercising the migration against real SQLite."""

    def __init__(self, bind, *, suppress_app_key: str | None = None):
        self.bind = bind
        self.suppress_app_key = suppress_app_key

    def get_bind(self):
        return self.bind

    def create_table(self, name, *elements):
        metadata = sa.MetaData()
        metadata.reflect(bind=self.bind)
        table = sa.Table(name, metadata, *elements)
        table.create(self.bind)
        return table

    def create_index(self, name, table_name, columns):
        metadata = sa.MetaData()
        table = sa.Table(table_name, metadata, autoload_with=self.bind)
        sa.Index(name, *(table.c[column] for column in columns)).create(self.bind)
        if self.suppress_app_key and name == "ix_workspace_member_app_entitlements_app_key":
            app_key = self.suppress_app_key.replace("'", "''")
            self.bind.execute(
                sa.text(
                    f"""
                    CREATE TRIGGER suppress_one_057_grant
                    BEFORE INSERT ON workspace_member_app_entitlements
                    WHEN NEW.app_key = '{app_key}'
                    BEGIN
                        SELECT RAISE(IGNORE);
                    END
                    """
                )
            )

    def drop_index(self, name, *, table_name):
        del table_name
        self.bind.execute(sa.text(f'DROP INDEX "{name}"'))

    def drop_table(self, name):
        metadata = sa.MetaData()
        table = sa.Table(name, metadata, autoload_with=self.bind)
        table.drop(self.bind)


def _isolated_schema(bind):
    metadata = sa.MetaData()
    users = sa.Table(
        "users",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
    )
    workspaces = sa.Table(
        "workspaces",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("slug", sa.String(100), nullable=False, unique=True),
        sa.Column("settings", sa.JSON()),
    )
    members = sa.Table(
        "workspace_members",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "workspace_id",
            sa.String(36),
            sa.ForeignKey("workspaces.id"),
            nullable=False,
        ),
    )
    metadata.create_all(bind)
    return users, workspaces, members


def _seed(bind, andritz_settings):
    users, workspaces, members = _isolated_schema(bind)
    other_settings = {
        "branding": {"name": "Other"},
        "features": {
            MIG.APP_ENTITLEMENTS_FEATURE: False,
            MIG.WORKSPACE_EXPERIENCE_FEATURE: True,
        },
    }
    bind.execute(
        users.insert(),
        [{"id": "andritz-user-1"}, {"id": "andritz-user-2"}, {"id": "other-user"}],
    )
    bind.execute(
        workspaces.insert(),
        [
            {"id": "workspace-andritz", "slug": "andritz", "settings": andritz_settings},
            {"id": "workspace-other", "slug": "other", "settings": other_settings},
        ],
    )
    bind.execute(
        members.insert(),
        [
            {"id": 1, "user_id": "andritz-user-1", "workspace_id": "workspace-andritz"},
            {"id": 2, "user_id": "andritz-user-2", "workspace_id": "workspace-andritz"},
            {"id": 3, "user_id": "other-user", "workspace_id": "workspace-other"},
        ],
    )
    return workspaces, other_settings


def _workspace_settings(bind, workspaces, workspace_id):
    return bind.execute(
        sa.select(workspaces.c.settings).where(workspaces.c.id == workspace_id)
    ).scalar_one()


@pytest.mark.parametrize(
    "andritz_settings",
    [
        {"branding": {"name": "Andritz"}},
        {"branding": {"name": "Andritz"}, "features": {"keep": "original"}},
        {
            "branding": {"name": "Andritz"},
            "features": {
                MIG.APP_ENTITLEMENTS_FEATURE: False,
                MIG.WORKSPACE_EXPERIENCE_FEATURE: True,
                "keep": "original",
            },
        },
    ],
)
def test_upgrade_backfills_andritz_then_downgrade_restores_flags_exactly(
    andritz_settings, monkeypatch
):
    engine = sa.create_engine("sqlite://")
    before = deepcopy(andritz_settings)
    with engine.begin() as bind:
        workspaces, other_before = _seed(bind, deepcopy(before))
        monkeypatch.setattr(MIG, "op", _SQLiteOps(bind))

        MIG.upgrade()

        entitlements = sa.Table(
            "workspace_member_app_entitlements",
            sa.MetaData(),
            autoload_with=bind,
        )
        grants = bind.execute(
            sa.select(
                entitlements.c.workspace_member_id,
                entitlements.c.app_key,
                entitlements.c.grant_source,
            )
        ).all()
        assert len(grants) == 2 * len(MIG.APP_KEYS)
        for member_id in (1, 2):
            assert {row.app_key for row in grants if row.workspace_member_id == member_id} == set(
                MIG.APP_KEYS
            )
        assert all(row.workspace_member_id != 3 for row in grants)
        assert {row.grant_source for row in grants} == {MIG.BACKFILL_SOURCE}

        upgraded = _workspace_settings(bind, workspaces, "workspace-andritz")
        assert upgraded["features"][MIG.APP_ENTITLEMENTS_FEATURE] is True
        assert upgraded["features"][MIG.WORKSPACE_EXPERIENCE_FEATURE] is True
        marker = upgraded[MIG.MIGRATION_MARKER_KEY]
        assert marker["revision"] == MIG.revision
        assert marker["schema"] == MIG.MIGRATION_MARKER_SCHEMA
        assert _workspace_settings(bind, workspaces, "workspace-other") == other_before

        # A downgrade must not clobber unrelated settings changed after 057.
        upgraded["post_upgrade_setting"] = "preserve-me"
        upgraded["features"]["post_upgrade_feature"] = "preserve-me-too"
        bind.execute(
            sa.update(workspaces)
            .where(workspaces.c.id == "workspace-andritz")
            .values(settings=upgraded)
        )

        MIG.downgrade()

        restored = _workspace_settings(bind, workspaces, "workspace-andritz")
        prior_features = before.get("features", {})
        for key in (
            MIG.APP_ENTITLEMENTS_FEATURE,
            MIG.WORKSPACE_EXPERIENCE_FEATURE,
        ):
            if key in prior_features:
                assert restored["features"][key] == prior_features[key]
            else:
                assert key not in restored.get("features", {})
        assert restored["branding"] == before["branding"]
        assert restored["post_upgrade_setting"] == "preserve-me"
        assert restored["features"]["post_upgrade_feature"] == "preserve-me-too"
        assert MIG.MIGRATION_MARKER_KEY not in restored
        assert _workspace_settings(bind, workspaces, "workspace-other") == other_before
        assert not sa.inspect(bind).has_table("workspace_member_app_entitlements")


def test_feature_flags_are_not_enabled_when_backfill_validation_fails(monkeypatch):
    engine = sa.create_engine("sqlite://")
    before = {"branding": {"name": "Andritz"}, "features": {"keep": True}}
    with engine.begin() as bind:
        workspaces, _ = _seed(bind, deepcopy(before))
        monkeypatch.setattr(
            MIG,
            "op",
            _SQLiteOps(bind, suppress_app_key=MIG.APP_KEYS[-1]),
        )

        with pytest.raises(RuntimeError, match="backfill incomplete"):
            MIG.upgrade()

        assert _workspace_settings(bind, workspaces, "workspace-andritz") == before


def test_downgrade_fails_closed_when_andritz_marker_is_missing(monkeypatch):
    engine = sa.create_engine("sqlite://")
    with engine.begin() as bind:
        workspaces, _ = _seed(bind, {"branding": {"name": "Andritz"}})
        monkeypatch.setattr(MIG, "op", _SQLiteOps(bind))
        MIG.upgrade()

        settings = _workspace_settings(bind, workspaces, "workspace-andritz")
        settings.pop(MIG.MIGRATION_MARKER_KEY)
        bind.execute(
            sa.update(workspaces)
            .where(workspaces.c.id == "workspace-andritz")
            .values(settings=settings)
        )

        with pytest.raises(RuntimeError, match="marker is missing"):
            MIG.downgrade()
        assert sa.inspect(bind).has_table("workspace_member_app_entitlements")


def test_downgrade_refuses_to_destroy_post_migration_grants(monkeypatch):
    engine = sa.create_engine("sqlite://")
    with engine.begin() as bind:
        _seed(bind, {"branding": {"name": "Andritz"}})
        monkeypatch.setattr(MIG, "op", _SQLiteOps(bind))
        MIG.upgrade()

        entitlements = sa.Table(
            "workspace_member_app_entitlements",
            sa.MetaData(),
            autoload_with=bind,
        )
        bind.execute(
            entitlements.insert().values(
                workspace_member_id=3,
                app_key="chat",
                grant_source="member_admin_api",
            )
        )

        with pytest.raises(RuntimeError, match="post-migration or non-Andritz grants"):
            MIG.downgrade()
        assert sa.inspect(bind).has_table("workspace_member_app_entitlements")
