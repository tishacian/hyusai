"""The additive column never rewrites old versions or discards authored policy."""
import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def migration(connection):
    path = Path(__file__).resolve().parents[3] / "alembic/versions/108_flow_draft_control_policy.py"
    spec = importlib.util.spec_from_file_location("migration108", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.op = Operations(MigrationContext.configure(connection))
    return module


def test_additive_migration_keeps_existing_drafts_and_safe_empty_downgrade():
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(sa.text("CREATE TABLE system_flow_drafts (system_id TEXT PRIMARY KEY, revision INTEGER)"))
        connection.execute(sa.text("INSERT INTO system_flow_drafts VALUES ('old-system', 7)"))
        module = migration(connection)
        assert module.down_revision == "107_brd_proposals" and len(module.revision) <= 32
        module.upgrade()
        row = connection.execute(sa.text("SELECT * FROM system_flow_drafts")).mappings().one()
        assert dict(row) == {"system_id": "old-system", "revision": 7, "control_policy_snapshot": None}
        module.downgrade()
        assert [c["name"] for c in sa.inspect(connection).get_columns("system_flow_drafts")] == ["system_id", "revision"]


def test_downgrade_refuses_to_discard_an_authored_mandate():
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(sa.text("CREATE TABLE system_flow_drafts (system_id TEXT PRIMARY KEY)"))
        module = migration(connection)
        module.upgrade()
        connection.execute(sa.text("INSERT INTO system_flow_drafts VALUES ('draft', '{\"sha256\":\"persisted\"}')"))
        with pytest.raises(RuntimeError, match="Cannot drop authored"):
            module.downgrade()
        assert connection.execute(sa.text("SELECT control_policy_snapshot FROM system_flow_drafts")).scalar()
