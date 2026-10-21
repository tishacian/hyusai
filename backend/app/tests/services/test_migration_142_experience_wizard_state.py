"""The wizard-progress table is additive: no existing row is read or changed."""

import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def test_creates_an_empty_table_and_drops_it_on_downgrade():
    path = Path(__file__).resolve().parents[3] / "alembic/versions/142_experience_wizard_state.py"
    spec = importlib.util.spec_from_file_location("migration142", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.down_revision == "141_event_execution_principal"
    assert len(module.revision) <= 32
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(sa.text("CREATE TABLE workspaces (id TEXT PRIMARY KEY)"))
        connection.execute(sa.text("CREATE TABLE experiences (id TEXT PRIMARY KEY, name TEXT)"))
        connection.execute(
            sa.text("INSERT INTO experiences (id, name) VALUES ('existing', 'kept')")
        )
        module.op = Operations(MigrationContext.configure(connection))
        module.upgrade()
        inspector = sa.inspect(connection)
        assert {column["name"] for column in inspector.get_columns("experience_wizard_states")} == {
            "experience_id",
            "workspace_id",
            "step",
            "state",
            "updated_by",
            "updated_at",
        }
        assert (
            connection.execute(sa.text("SELECT COUNT(*) FROM experience_wizard_states")).scalar()
            == 0
        )
        assert connection.execute(sa.text("SELECT name FROM experiences")).scalar() == "kept"
        module.downgrade()
        assert "experience_wizard_states" not in sa.inspect(connection).get_table_names()
