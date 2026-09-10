"""Additive adoption migrations preserve history and scope retry claims."""
from datetime import datetime
import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from alembic.migration import MigrationContext
from alembic.operations import Operations


def test_adoption_migrations_preserve_rows_and_enforce_scoped_claims():
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        for table in ["users", "workspaces", "sessions", "workspace_members", "decisions"]:
            connection.exec_driver_sql(f"CREATE TABLE {table} (id VARCHAR(36) PRIMARY KEY)")
            connection.exec_driver_sql(f"INSERT INTO {table} (id) VALUES ('existing')")
        migrations = []
        directory = Path(__file__).resolve().parents[3] / "alembic" / "versions"
        for name in ["101_member_experience", "102_assistant_requests", "103_human_confirmation"]:
            spec = importlib.util.spec_from_file_location(name, directory / f"{name}.py")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            module.op = Operations(MigrationContext.configure(connection))
            module.upgrade()
            migrations.append(module)
        assert (
            connection.exec_driver_sql("SELECT experience_progress FROM workspace_members").scalar()
            is None
        )
        assert (
            connection.exec_driver_sql("SELECT human_confirmed_by FROM decisions").scalar() is None
        )
        receipt = sa.Table("assistant_requests", sa.MetaData(), autoload_with=connection)
        row = dict(
            id="a",
            workspace_id="existing",
            user_id="existing",
            session_id="existing",
            request_id="retry",
            fingerprint="f" * 64,
            state="completed",
            created_at=datetime.utcnow(),
        )
        connection.execute(receipt.insert(), row)
        with pytest.raises(IntegrityError), connection.begin_nested():
            connection.execute(receipt.insert(), {**row, "id": "duplicate"})
        connection.exec_driver_sql("INSERT INTO users (id) VALUES ('other')")
        connection.execute(receipt.insert(), {**row, "id": "other", "user_id": "other"})
        connection.exec_driver_sql("DELETE FROM sessions WHERE id='existing'")
        assert connection.execute(sa.select(sa.func.count()).select_from(receipt)).scalar() == 0
        for module in reversed(migrations):
            module.downgrade()
        assert "assistant_requests" not in sa.inspect(connection).get_table_names()
        assert connection.exec_driver_sql("SELECT id FROM decisions").scalar() == "existing"
        assert connection.exec_driver_sql("SELECT id FROM workspace_members").scalar() == "existing"
