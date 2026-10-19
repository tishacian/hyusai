"""New unattended grants are opt-in; migration never invents an identity."""

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def test_nullable_upgrade_no_backfill_and_guarded_downgrade():
    path = Path(__file__).resolve().parents[3] / "alembic/versions/141_event_execution_principal.py"
    spec = importlib.util.spec_from_file_location("migration141", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.down_revision == "140_mlops_prod_explanations"
    assert len(module.revision) <= 32
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        for table in ("webhook_hooks", "run_schedules", "runs"):
            connection.execute(sa.text(f"CREATE TABLE {table} (id TEXT PRIMARY KEY)"))
            connection.execute(sa.text(f"INSERT INTO {table} (id) VALUES ('existing')"))
        module.op = Operations(MigrationContext.configure(connection))
        module.upgrade()
        for table, column in (
            ("webhook_hooks", "execution_identity"),
            ("run_schedules", "execution_identity"),
            ("runs", "execution_principal"),
        ):
            assert connection.execute(sa.text(f"SELECT {column} FROM {table}")).scalar() is None
        connection.execute(
            sa.text("UPDATE runs SET execution_principal = :principal"),
            {"principal": '{"kind":"delegated_user"}'},
        )
        with pytest.raises(RuntimeError, match="DOWNGRADE_NOT_EMPTY"):
            module.downgrade()
        connection.execute(sa.text("UPDATE runs SET execution_principal = 'null'"))
        module.downgrade()
        for table in ("webhook_hooks", "run_schedules", "runs"):
            assert [column["name"] for column in sa.inspect(connection).get_columns(table)] == [
                "id"
            ]
