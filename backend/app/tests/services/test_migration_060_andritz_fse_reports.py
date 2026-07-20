"""Migration contract tests for the Andritz FSE report surface (060)."""
from __future__ import annotations

import importlib.util
import sys
import types
from contextlib import contextmanager
from pathlib import Path

import sqlalchemy as sa


def _load_migration():
    path = (
        Path(__file__).resolve().parents[3]
        / "alembic"
        / "versions"
        / "060_andritz_fse_reports.py"
    )
    saved = sys.modules.get("alembic")
    stub = types.ModuleType("alembic")
    stub.op = types.SimpleNamespace(get_bind=lambda: None)
    sys.modules["alembic"] = stub
    try:
        spec = importlib.util.spec_from_file_location("migration_060", path)
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
    """Run data changes while leaving CHECK DDL to PostgreSQL deployment tests."""

    def __init__(self, bind):
        self.bind = bind

    def get_bind(self):
        return self.bind

    @contextmanager
    def batch_alter_table(self, _table_name):
        yield types.SimpleNamespace(
            drop_constraint=lambda *args, **kwargs: None,
            create_check_constraint=lambda *args, **kwargs: None,
        )


def _schema(bind):
    metadata = sa.MetaData()
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
        sa.Column("workspace_id", sa.String(36), nullable=False),
    )
    entitlements = sa.Table(
        "workspace_member_app_entitlements",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("workspace_member_id", sa.Integer(), nullable=False),
        sa.Column("app_key", sa.String(80), nullable=False),
        sa.Column("granted_at", sa.DateTime(), nullable=False),
        sa.Column("granted_by_user_id", sa.String(36)),
        sa.Column("grant_source", sa.String(80), nullable=False),
        sa.UniqueConstraint(
            "workspace_member_id",
            "app_key",
            name="uq_workspace_member_app_entitlement",
        ),
    )
    capabilities = sa.Table(
        "capabilities",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("slug", sa.String(100), nullable=False),
    )
    systems = sa.Table(
        "systems",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("objective", sa.Text()),
        sa.Column("capability_id", sa.String(36)),
        sa.Column("skill_ids", sa.JSON()),
        sa.Column("flow_definition", sa.JSON()),
        sa.Column("settings", sa.JSON()),
        sa.Column("execution_mode", sa.String(80)),
        sa.Column("execution_profile", sa.JSON()),
        sa.Column("coordination_pattern", sa.String(80)),
        sa.Column("status", sa.String(40)),
        sa.Column("created_by", sa.String(255)),
        sa.Column("retrieval_mode_default", sa.String(40)),
        sa.Column("created_at", sa.DateTime()),
        sa.Column("updated_at", sa.DateTime()),
    )
    metadata.create_all(bind)
    return workspaces, members, entitlements, capabilities, systems


def test_upgrade_uses_integer_entitlement_ids_and_is_reversible(monkeypatch):
    engine = sa.create_engine("sqlite://")
    with engine.begin() as bind:
        workspaces, members, _, capabilities, _ = _schema(bind)
        bind.execute(
            workspaces.insert(),
            {
                "id": "workspace-andritz",
                "slug": MIG.ANDRITZ_SLUG,
                "settings": {
                    "navigation_profile": {
                        "key": "business_end_user",
                        "primary_surfaces": list(MIG.PREV_APP_KEYS),
                    }
                },
            },
        )
        bind.execute(
            members.insert(),
            [
                {"id": 1, "workspace_id": "workspace-andritz"},
                {"id": 2, "workspace_id": "workspace-andritz"},
            ],
        )
        bind.execute(
            capabilities.insert(),
            {"id": "capability-capture", "slug": MIG.CAPABILITY_SLUG},
        )

        monkeypatch.setattr(MIG, "op", _SQLiteOps(bind))
        MIG.upgrade()

        reflected = sa.MetaData()
        grants = sa.Table(
            "workspace_member_app_entitlements",
            reflected,
            autoload_with=bind,
        )
        rows = bind.execute(sa.select(grants).order_by(grants.c.id)).mappings().all()
        assert [row["id"] for row in rows] == [1, 2]
        assert all(isinstance(row["id"], int) for row in rows)
        assert {row["workspace_member_id"] for row in rows} == {1, 2}
        assert {row["app_key"] for row in rows} == {MIG.FSE_APP_KEY}
        assert {row["grant_source"] for row in rows} == {MIG.BACKFILL_SOURCE}

        workspace_settings = bind.execute(
            sa.select(workspaces.c.settings).where(workspaces.c.id == "workspace-andritz")
        ).scalar_one()
        assert workspace_settings["navigation_profile"]["primary_surfaces"] == [
            *MIG.PREV_APP_KEYS,
            MIG.FSE_APP_KEY,
        ]

        systems = sa.Table("systems", reflected, autoload_with=bind)
        system = bind.execute(sa.select(systems)).mappings().one()
        assert system["name"] == MIG.SYSTEM_NAME
        assert system["settings"]["capture"]["template_id"] == MIG.TEMPLATE_ID

        MIG.downgrade()
        assert bind.execute(sa.select(sa.func.count()).select_from(grants)).scalar_one() == 0
        assert bind.execute(sa.select(systems.c.status)).scalar_one() == "retired"
