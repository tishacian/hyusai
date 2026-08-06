"""Migration 080 backfills the unified trigger delivery ledger."""

from __future__ import annotations

import importlib.util
import sys
import types
from datetime import datetime
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from alembic.migration import MigrationContext
from alembic.operations import Operations


def _load_migration():
    path = Path(__file__).resolve().parents[3] / "alembic" / "versions" / "080_trigger_event_claims.py"
    saved = sys.modules.get("alembic")
    stub = types.ModuleType("alembic")
    stub.op = types.SimpleNamespace()
    sys.modules["alembic"] = stub
    try:
        spec = importlib.util.spec_from_file_location("migration_080", path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        if saved is not None:
            sys.modules["alembic"] = saved
        else:
            sys.modules.pop("alembic", None)
    return module


MIG = _load_migration()


def test_revision_extends_atomic_run_claim_migration() -> None:
    assert MIG.revision == "080_trigger_event_claims"
    assert MIG.down_revision == "079_trigger_run_dedup"
    assert len(MIG.revision) <= 32


def test_backfill_promotes_only_durable_run_claimants() -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    metadata = sa.MetaData()
    runs = sa.Table(
        "runs",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36)),
        sa.Column("system_id", sa.String(36)),
        sa.Column("status", sa.String(40)),
        sa.Column("trigger_dedup_key", sa.String(255)),
        sa.Column("started_at", sa.DateTime()),
    )
    claims = sa.Table(
        "trigger_event_claims",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36)),
        sa.Column("system_id", sa.String(36), nullable=False),
        sa.Column("dedup_key", sa.String(255), nullable=False),
        sa.Column("outcome", sa.String(20), nullable=False),
        sa.Column("run_id", sa.String(36)),
        sa.Column("created_at", sa.DateTime()),
        sa.UniqueConstraint("system_id", "dedup_key"),
    )
    metadata.create_all(engine)
    now = datetime(2026, 8, 6, 12, 0, 0)
    with engine.begin() as connection:
        connection.execute(
            runs.insert(),
            [
                {
                    "id": "run-live",
                    "workspace_id": "ws",
                    "system_id": "system",
                    "status": "pending",
                    "trigger_dedup_key": "live-key",
                    "started_at": now,
                },
                {
                    "id": "run-simulated",
                    "workspace_id": "ws",
                    "system_id": "system",
                    "status": "simulated",
                    "trigger_dedup_key": "sim-key",
                    "started_at": now,
                },
                {
                    "id": "run-manual",
                    "workspace_id": "ws",
                    "system_id": "system",
                    "status": "pending",
                    "trigger_dedup_key": None,
                    "started_at": now,
                },
            ],
        )

        MIG._backfill_claims(connection)

        rows = {
            row["run_id"]: row
            for row in connection.execute(sa.select(claims)).mappings()
        }
        assert rows["run-live"]["outcome"] == "run"
        assert rows["run-simulated"]["outcome"] == "simulated"
        assert "run-manual" not in rows


def test_upgrade_constraints_outbox_check_and_safe_downgrade() -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    metadata = sa.MetaData()
    workspaces = sa.Table(
        "workspaces",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
    )
    systems = sa.Table(
        "systems",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36)),
    )
    runs = sa.Table(
        "runs",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36)),
        sa.Column("system_id", sa.String(36)),
        sa.Column("status", sa.String(40)),
        sa.Column("trigger_dedup_key", sa.String(255)),
        sa.Column("started_at", sa.DateTime()),
    )
    sa.Table(
        "run_inbox",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
    )
    sa.Table(
        "run_dispatch_outbox",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.CheckConstraint(
            "event_type IN ('subflow_run', 'subflow_parent_resume', "
            "'subflow_hitl_resume', 'run_hitl_resume')",
            name=MIG.OUTBOX_CHECK,
        ),
    )
    metadata.create_all(engine)

    with engine.begin() as connection:
        connection.execute(workspaces.insert(), {"id": "ws"})
        connection.execute(systems.insert(), {"id": "system", "workspace_id": "ws"})
        connection.execute(
            runs.insert(),
            {
                "id": "run",
                "workspace_id": "ws",
                "system_id": "system",
                "status": "pending",
                "trigger_dedup_key": "dedup",
                "started_at": datetime(2026, 8, 6, 12, 0, 0),
            },
        )
        MIG.op = Operations(MigrationContext.configure(connection))
        MIG.upgrade()

        inspector = sa.inspect(connection)
        assert "trigger_event_claims" in inspector.get_table_names()
        checks = {
            item["name"]: item["sqltext"]
            for item in inspector.get_check_constraints("run_dispatch_outbox")
        }
        assert "trigger_run" in checks[MIG.OUTBOX_CHECK]
        claim = sa.Table("trigger_event_claims", sa.MetaData(), autoload_with=connection)
        assert connection.execute(sa.select(claim.c.run_id)).scalar_one() == "run"
        with pytest.raises(IntegrityError), connection.begin_nested():
            connection.execute(
                claim.insert(),
                {
                    "id": "invalid-target",
                    "workspace_id": "ws",
                    "system_id": "system",
                    "dedup_key": "other",
                    "outcome": "inbox",
                    "run_id": "run",
                },
            )

        current_outbox = sa.Table(
            "run_dispatch_outbox",
            sa.MetaData(),
            autoload_with=connection,
        )
        connection.execute(
            current_outbox.insert(),
            {"id": "trigger-event", "event_type": "trigger_run"},
        )
        MIG.downgrade()

        inspector = sa.inspect(connection)
        assert "trigger_event_claims" not in inspector.get_table_names()
        checks = {
            item["name"]: item["sqltext"]
            for item in inspector.get_check_constraints("run_dispatch_outbox")
        }
        assert "trigger_run" not in checks[MIG.OUTBOX_CHECK]
        downgraded_outbox = sa.Table(
            "run_dispatch_outbox",
            sa.MetaData(),
            autoload_with=connection,
        )
        assert connection.execute(sa.select(sa.func.count()).select_from(downgraded_outbox)).scalar_one() == 0
