"""Migration 093 gives business-app actions a release-independent claim."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from alembic.migration import MigrationContext
from alembic.operations import Operations


def _load_migration():
    path = (
        Path(__file__).resolve().parents[3]
        / "alembic"
        / "versions"
        / "093_experience_run_idempotency.py"
    )
    saved = sys.modules.get("alembic")
    stub = types.ModuleType("alembic")
    stub.op = types.SimpleNamespace()
    sys.modules["alembic"] = stub
    try:
        spec = importlib.util.spec_from_file_location("migration_093", path)
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


def test_experience_idempotency_claim_is_unique_across_systems() -> None:
    assert MIG.revision == "093_experience_run_idempotency"
    assert MIG.down_revision == "092_experience_access_policy"
    engine = sa.create_engine("sqlite:///:memory:")
    metadata = sa.MetaData()
    runs = sa.Table(
        "runs",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("system_id", sa.String(36), nullable=False),
    )
    metadata.create_all(engine)

    with engine.begin() as connection:
        MIG.op = Operations(MigrationContext.configure(connection))
        MIG.upgrade()
        reflected = sa.Table("runs", sa.MetaData(), autoload_with=connection)
        connection.execute(
            reflected.insert(),
            {
                "id": "run-a",
                "system_id": "system-a",
                "experience_idempotency_key": "a" * 64,
            },
        )
        with pytest.raises(IntegrityError), connection.begin_nested():
            connection.execute(
                reflected.insert(),
                {
                    "id": "run-b",
                    "system_id": "system-b",
                    "experience_idempotency_key": "a" * 64,
                },
            )

        MIG.downgrade()
        assert "experience_idempotency_key" not in {
            column["name"] for column in sa.inspect(connection).get_columns("runs")
        }
