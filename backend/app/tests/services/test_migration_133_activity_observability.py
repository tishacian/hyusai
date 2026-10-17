import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext

from app.models.activity import Activity, ActivityCommand, ActivityEvent, ActivityWorkspaceCursor
from app.tests.services.test_migration_127_connector_connections import load


def test_133_schema_matches_models_and_reversible_when_empty():
    migration = load("133_activity_observability")
    assert migration.down_revision == "132_connector_sync"
    engine = sa.create_engine("sqlite://")
    with engine.begin() as bind:
        metadata = sa.MetaData()
        for name in ("users", "workspaces"):
            sa.Table(name, metadata, sa.Column("id", sa.String(36), primary_key=True))
        metadata.create_all(bind)
        migration.op = Operations(MigrationContext.configure(bind))
        migration.upgrade()
        for model in (Activity, ActivityCommand, ActivityEvent, ActivityWorkspaceCursor):
            table = model.__table__
            # Columns added by later revisions (138: typed finish and duration).
            later = {"activities": {"finished_at", "duration_ms"}}.get(table.name, set())
            assert {column["name"] for column in sa.inspect(bind).get_columns(table.name)} == set(table.columns.keys()) - later
            expected_unique = {tuple(column.name for column in constraint.columns) for constraint in table.constraints if isinstance(constraint, sa.UniqueConstraint)}
            actual_unique = {tuple(constraint["column_names"]) for constraint in sa.inspect(bind).get_unique_constraints(table.name)}
            assert actual_unique == expected_unique
        migration.downgrade()
        assert not set(sa.inspect(bind).get_table_names()).intersection({"activities", "activity_events", "activity_commands", "activity_workspace_cursors"})
