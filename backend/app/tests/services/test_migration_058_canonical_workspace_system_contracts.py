"""Round-trip tests for migration 058's canonical persistence contracts."""

from __future__ import annotations

import importlib.util
import sys
import types
from copy import deepcopy
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError


def _load_migration():
    path = (
        Path(__file__).resolve().parents[3]
        / "alembic"
        / "versions"
        / "058_canonical_workspace_system_contracts.py"
    )
    saved = sys.modules.get("alembic")
    stub = types.ModuleType("alembic")
    stub.op = types.SimpleNamespace(get_bind=lambda: None)
    sys.modules["alembic"] = stub
    try:
        spec = importlib.util.spec_from_file_location("migration_058", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        if saved is not None:
            sys.modules["alembic"] = saved
        else:
            sys.modules.pop("alembic", None)
    return module


MIG = _load_migration()


def _isolated_schema(bind):
    metadata = sa.MetaData()
    workspaces = sa.Table(
        "workspaces",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("slug", sa.String(100), nullable=False, unique=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("settings", sa.JSON()),
        sa.Column("mode", sa.String(32), nullable=True),
    )
    systems = sa.Table(
        "systems",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("settings", sa.JSON()),
        sa.Column("execution_profile", sa.JSON()),
        sa.Column("status", sa.String(20), nullable=True),
        sa.Column("execution_mode", sa.String(40), nullable=True),
    )
    entitlements = sa.Table(
        "workspace_member_app_entitlements",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("app_key", sa.String(80), nullable=False),
    )
    metadata.create_all(bind)
    return workspaces, systems, entitlements


class _SQLiteBatch:
    """Exercise Alembic batch intent against a real isolated SQLite schema."""

    def __init__(self, bind, table_name: str):
        self.bind = bind
        self.table_name = table_name
        self.created_checks: list[tuple[str, str]] = []
        self.dropped_checks: set[str] = set()
        self.altered_columns: dict[str, dict] = {}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        if exc_type is None and (
            self.created_checks or self.dropped_checks or self.altered_columns
        ):
            self._recreate_table()
        return False

    def create_check_constraint(self, name: str, condition: str):
        self.created_checks.append((name, condition))

    def drop_constraint(self, name: str, *, type_: str):
        assert type_ == "check"
        self.dropped_checks.add(name)

    def alter_column(self, name: str, **changes):
        self.altered_columns[name] = changes

    def _recreate_table(self):
        inspector = sa.inspect(self.bind)
        old = sa.Table(self.table_name, sa.MetaData(), autoload_with=self.bind)
        indexes = inspector.get_indexes(self.table_name)
        unique_constraints = inspector.get_unique_constraints(self.table_name)
        checks = [
            (item["name"], item["sqltext"])
            for item in inspector.get_check_constraints(self.table_name)
            if item["name"] not in self.dropped_checks
        ]
        checks.extend(self.created_checks)

        temporary_name = f"_alembic_tmp_{self.table_name}"
        metadata = sa.MetaData()
        columns = []
        for column in old.columns:
            changes = self.altered_columns.get(column.name, {})
            default = changes.get(
                "server_default",
                column.server_default.arg if column.server_default is not None else None,
            )
            columns.append(
                sa.Column(
                    column.name,
                    column.type,
                    primary_key=column.primary_key,
                    nullable=changes.get("nullable", column.nullable),
                    server_default=default,
                )
            )
        constraints = [
            sa.UniqueConstraint(
                *(item["column_names"]),
                name=item["name"],
            )
            for item in unique_constraints
            if item["column_names"]
        ]
        constraints.extend(sa.CheckConstraint(sqltext, name=name) for name, sqltext in checks)
        temporary = sa.Table(temporary_name, metadata, *columns, *constraints)
        temporary.create(self.bind)
        column_names = [column.name for column in old.columns]
        self.bind.execute(
            temporary.insert().from_select(
                column_names,
                sa.select(*(old.c[name] for name in column_names)),
            )
        )
        old.drop(self.bind)
        self.bind.execute(sa.text(f'ALTER TABLE "{temporary_name}" RENAME TO "{self.table_name}"'))
        rebuilt = sa.Table(self.table_name, sa.MetaData(), autoload_with=self.bind)
        for index in indexes:
            if index.get("unique"):
                continue
            sa.Index(
                index["name"],
                *(rebuilt.c[name] for name in index["column_names"]),
            ).create(self.bind)


class _SQLiteOps:
    def __init__(self, bind):
        self.bind = bind

    def get_bind(self):
        return self.bind

    def batch_alter_table(self, table_name: str):
        return _SQLiteBatch(self.bind, table_name)


def _settings(bind, workspaces):
    return bind.execute(
        sa.select(workspaces.c.settings).where(workspaces.c.id == "workspace-andritz")
    ).scalar_one()


@pytest.mark.parametrize(
    "before",
    [
        {"branding": {"name": "Andritz"}},
        {
            "branding": {"name": "Andritz"},
            "actions": {
                "enabled_packs": ["global_voice_v1"],
                "hidden_actions": ["voice.repeat"],
            },
        },
    ],
)
def test_andritz_pack_backfill_is_idempotent_and_downgrades_exactly(before):
    engine = sa.create_engine("sqlite://")
    expected = deepcopy(before)
    with engine.begin() as bind:
        workspaces, _, _ = _isolated_schema(bind)
        bind.execute(
            workspaces.insert().values(
                id="workspace-andritz",
                slug="andritz",
                name="Andritz",
                settings=deepcopy(before),
                mode="executive",
            )
        )

        MIG._stamp_workspace_contracts(bind)
        first_upgrade = _settings(bind, workspaces)
        assert MIG.ANDRITZ_ACTION_PACK in first_upgrade["actions"]["enabled_packs"]
        assert first_upgrade[MIG.MIGRATION_MARKER_KEY]["revision"] == MIG.revision

        MIG._stamp_workspace_contracts(bind)
        assert _settings(bind, workspaces) == first_upgrade

        first_upgrade["post_upgrade_setting"] = "preserve-me"
        bind.execute(
            workspaces.update()
            .where(workspaces.c.id == "workspace-andritz")
            .values(settings=first_upgrade)
        )
        MIG._restore_workspace_contracts(bind)

        restored = _settings(bind, workspaces)
        assert restored.pop("post_upgrade_setting") == "preserve-me"
        assert restored == expected


def test_andritz_downgrade_refuses_to_overwrite_action_packs_changed_after_upgrade():
    engine = sa.create_engine("sqlite://")
    with engine.begin() as bind:
        workspaces, _, _ = _isolated_schema(bind)
        bind.execute(
            workspaces.insert().values(
                id="workspace-andritz",
                slug="andritz",
                name="Andritz",
                settings={"actions": {"enabled_packs": []}},
                mode="executive",
            )
        )
        MIG._stamp_workspace_contracts(bind)
        settings = _settings(bind, workspaces)
        settings["actions"]["enabled_packs"].append("global_voice_v1")
        bind.execute(
            workspaces.update()
            .where(workspaces.c.id == "workspace-andritz")
            .values(settings=settings)
        )

        with pytest.raises(RuntimeError, match="changed after migration 058"):
            MIG._restore_workspace_contracts(bind)


def test_family_stamp_snapshots_legacy_resolution_and_restores_every_workspace():
    engine = sa.create_engine("sqlite://")
    rows = [
        ("andritz-name", "andritz-by-name", "Andritz Pilot", {}, "andritz"),
        ("sentinel-slug", "sentinel-ci", "Neutral", {}, "sentinel_ci"),
        ("generic", "generic-neutral", "Neutral", {}, "generic"),
        (
            "explicit",
            "sentinel-explicit",
            "Andritz",
            {"family": "generic"},
            "generic",
        ),
        (
            "industrial",
            "acme-manufacturing",
            "Acme Manufacturing",
            {"family": "industrial"},
            "industrial",
        ),
    ]
    with engine.begin() as bind:
        workspaces, _, _ = _isolated_schema(bind)
        bind.execute(
            workspaces.insert(),
            [
                {
                    "id": workspace_id,
                    "slug": slug,
                    "name": name,
                    "settings": deepcopy(settings),
                    "mode": "executive",
                }
                for workspace_id, slug, name, settings, _ in rows
            ],
        )

        MIG._stamp_workspace_contracts(bind)
        upgraded = {
            row.id: row.settings
            for row in bind.execute(sa.select(workspaces.c.id, workspaces.c.settings)).all()
        }
        assert {
            workspace_id: upgraded[workspace_id]["family"] for workspace_id, _, _, _, _ in rows
        } == {workspace_id: expected_family for workspace_id, _, _, _, expected_family in rows}
        assert all(MIG.MIGRATION_MARKER_KEY in upgraded[row[0]] for row in rows)

        MIG._stamp_workspace_contracts(bind)
        assert {
            row.id: row.settings
            for row in bind.execute(sa.select(workspaces.c.id, workspaces.c.settings)).all()
        } == upgraded

        MIG._restore_workspace_contracts(bind)
        restored = {
            row.id: row.settings
            for row in bind.execute(sa.select(workspaces.c.id, workspaces.c.settings)).all()
        }
        assert restored == {workspace_id: settings for workspace_id, _, _, settings, _ in rows}


def _assert_insert_rejected(bind, statement) -> None:
    with pytest.raises(IntegrityError), bind.begin_nested():
        bind.execute(statement)


def test_full_upgrade_installs_checks_and_downgrades(monkeypatch):
    engine = sa.create_engine("sqlite://")
    before = {
        "branding": {"name": "Andritz"},
        "actions": {"enabled_packs": ["global_voice_v1"], "keep": True},
    }
    with engine.begin() as bind:
        workspaces, systems, entitlements = _isolated_schema(bind)
        bind.execute(
            workspaces.insert(),
            [
                {
                    "id": "workspace-andritz",
                    "slug": "andritz",
                    "name": "Andritz",
                    "settings": deepcopy(before),
                    "mode": "executive",
                },
                {
                    "id": "workspace-other",
                    "slug": "other",
                    "name": "Other",
                    "settings": {},
                    "mode": None,
                },
            ],
        )
        bind.execute(
            systems.insert().values(
                id="system-legacy",
                settings={"actions": {"enabled_packs": ["global_voice_v1"]}},
                execution_profile={},
                status="archived",
                execution_mode="real_time",
            )
        )
        bind.execute(entitlements.insert().values(id=1, app_key="chat"))
        monkeypatch.setattr(MIG, "op", _SQLiteOps(bind))

        MIG.upgrade()

        assert (
            bind.execute(
                sa.select(workspaces.c.mode).where(workspaces.c.id == "workspace-other")
            ).scalar_one()
            == "executive"
        )
        workspace_mode_column = next(
            item for item in sa.inspect(bind).get_columns("workspaces") if item["name"] == "mode"
        )
        assert workspace_mode_column["nullable"] is False
        assert "executive" in str(workspace_mode_column["default"])
        other_settings = bind.execute(
            sa.select(workspaces.c.settings).where(workspaces.c.id == "workspace-other")
        ).scalar_one()
        assert other_settings["family"] == "generic"
        assert bind.execute(
            sa.select(systems.c.status, systems.c.execution_mode).where(
                systems.c.id == "system-legacy"
            )
        ).one() == ("retired", "real_time_decision")

        checks = {
            table_name: {
                item["name"] for item in sa.inspect(bind).get_check_constraints(table_name)
            }
            for table_name in (
                "workspaces",
                "systems",
                "workspace_member_app_entitlements",
            )
        }
        assert checks["workspaces"] == {MIG.CK_WORKSPACES_MODE}
        assert checks["systems"] == {
            MIG.CK_SYSTEMS_STATUS,
            MIG.CK_SYSTEMS_EXECUTION_MODE,
        }
        assert checks["workspace_member_app_entitlements"] == {MIG.CK_WORKSPACE_APPS}

        _assert_insert_rejected(
            bind,
            workspaces.insert().values(
                id="bad-workspace",
                slug="bad-workspace",
                name="Bad workspace",
                settings={},
                mode="invalid",
            ),
        )
        _assert_insert_rejected(
            bind,
            systems.insert().values(
                id="bad-system-status",
                settings={},
                execution_profile={},
                status="archived",
                execution_mode="real_time_decision",
            ),
        )
        _assert_insert_rejected(
            bind,
            entitlements.insert().values(id=2, app_key="unknown-app"),
        )

        upgraded = _settings(bind, workspaces)
        upgraded["post_upgrade_setting"] = "preserve-me"
        bind.execute(
            workspaces.update()
            .where(workspaces.c.id == "workspace-andritz")
            .values(settings=upgraded)
        )
        MIG.downgrade()

        restored = _settings(bind, workspaces)
        assert restored.pop("post_upgrade_setting") == "preserve-me"
        assert restored == before
        for table_name in checks:
            assert sa.inspect(bind).get_check_constraints(table_name) == []
        workspace_mode_column = next(
            item for item in sa.inspect(bind).get_columns("workspaces") if item["name"] == "mode"
        )
        assert workspace_mode_column["nullable"] is False
        assert "executive" in str(workspace_mode_column["default"])
        assert (
            bind.execute(
                sa.select(workspaces.c.settings).where(workspaces.c.id == "workspace-other")
            ).scalar_one()
            == {}
        )


@pytest.mark.parametrize(
    ("column", "invalid_value", "message"),
    [
        ("workspace_mode", "mystery", "workspaces.mode"),
        ("system_status", "stopped", "systems.status"),
        ("system_execution_mode", "streaming", "systems.execution_mode"),
        ("workspace_app", "admin", "workspace_member_app_entitlements.app_key"),
    ],
)
def test_upgrade_audits_unknown_persisted_enum_values_before_checks(
    column,
    invalid_value,
    message,
    monkeypatch,
):
    engine = sa.create_engine("sqlite://")
    with engine.begin() as bind:
        workspaces, systems, entitlements = _isolated_schema(bind)
        workspace_mode = invalid_value if column == "workspace_mode" else "executive"
        system_status = invalid_value if column == "system_status" else "draft"
        execution_mode = (
            invalid_value if column == "system_execution_mode" else "real_time_decision"
        )
        app_key = invalid_value if column == "workspace_app" else "chat"
        bind.execute(
            workspaces.insert().values(
                id="workspace-other",
                slug="other",
                name="Other",
                settings={},
                mode=workspace_mode,
            )
        )
        bind.execute(
            systems.insert().values(
                id="system",
                settings={},
                execution_profile={},
                status=system_status,
                execution_mode=execution_mode,
            )
        )
        bind.execute(entitlements.insert().values(id=1, app_key=app_key))
        monkeypatch.setattr(MIG, "op", _SQLiteOps(bind))

        with pytest.raises(RuntimeError, match=message):
            MIG.upgrade()


def test_upgrade_rejects_noncanonical_action_pack_representation(monkeypatch):
    engine = sa.create_engine("sqlite://")
    with engine.begin() as bind:
        workspaces, systems, entitlements = _isolated_schema(bind)
        bind.execute(
            workspaces.insert().values(
                id="workspace-other",
                slug="other",
                name="Other",
                settings={"actions": {"enabled_packs": [" global_voice_v1 "]}},
                mode="executive",
            )
        )
        bind.execute(
            systems.insert().values(
                id="system",
                settings={},
                execution_profile={},
                status="draft",
                execution_mode="real_time_decision",
            )
        )
        bind.execute(entitlements.insert().values(id=1, app_key="chat"))
        monkeypatch.setattr(MIG, "op", _SQLiteOps(bind))

        with pytest.raises(RuntimeError, match="Non-canonical action-pack list"):
            MIG.upgrade()


@pytest.mark.parametrize("invalid_settings", [None, [], "legacy-text", 42])
def test_upgrade_rejects_non_object_workspace_settings_without_mutation(
    invalid_settings,
    monkeypatch,
):
    engine = sa.create_engine("sqlite://")
    with engine.begin() as bind:
        workspaces, systems, entitlements = _isolated_schema(bind)
        bind.execute(
            workspaces.insert().values(
                id="workspace-invalid-settings",
                slug="invalid-settings",
                name="Invalid settings",
                settings=invalid_settings,
                mode="executive",
            )
        )
        bind.execute(
            systems.insert().values(
                id="system",
                settings={},
                execution_profile=None,
                status="draft",
                execution_mode="real_time_decision",
            )
        )
        bind.execute(entitlements.insert().values(id=1, app_key="chat"))
        monkeypatch.setattr(MIG, "op", _SQLiteOps(bind))

        with pytest.raises(RuntimeError, match="JSON settings must be an object"):
            MIG.upgrade()

        persisted = bind.execute(
            sa.select(workspaces.c.settings).where(workspaces.c.id == "workspace-invalid-settings")
        ).scalar_one()
        assert persisted == invalid_settings


def test_andritz_preexisting_marker_cannot_skip_action_pack_backfill():
    engine = sa.create_engine("sqlite://")
    with engine.begin() as bind:
        workspaces, _, _ = _isolated_schema(bind)
        settings = {"family": "andritz"}
        settings[MIG.MIGRATION_MARKER_KEY] = MIG._new_workspace_marker(
            settings,
            applied_family="andritz",
            snapshot_actions=False,
        )
        bind.execute(
            workspaces.insert().values(
                id="workspace-andritz",
                slug="andritz",
                name="Andritz",
                settings=settings,
                mode="executive",
            )
        )

        with pytest.raises(RuntimeError, match="missing its action-pack backfill"):
            MIG._stamp_workspace_contracts(bind)


def test_upgrade_rejects_preexisting_constraint_name_before_writes(monkeypatch):
    engine = sa.create_engine("sqlite://")
    with engine.begin() as bind:
        workspaces, systems, entitlements = _isolated_schema(bind)
        bind.execute(
            workspaces.insert().values(
                id="workspace",
                slug="workspace",
                name="Workspace",
                settings={"family": "generic"},
                mode="executive",
            )
        )
        bind.execute(
            systems.insert().values(
                id="system",
                settings={},
                execution_profile=None,
                status="draft",
                execution_mode="real_time_decision",
            )
        )
        bind.execute(entitlements.insert().values(id=1, app_key="chat"))
        monkeypatch.setattr(MIG, "op", _SQLiteOps(bind))
        monkeypatch.setattr(MIG, "_constraint_exists", lambda *_args: True)

        with pytest.raises(RuntimeError, match="constraint name collision"):
            MIG.upgrade()

        settings = bind.execute(
            sa.select(workspaces.c.settings).where(workspaces.c.id == "workspace")
        ).scalar_one()
        assert settings == {"family": "generic"}
