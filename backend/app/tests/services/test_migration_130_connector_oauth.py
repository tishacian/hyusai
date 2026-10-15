"""OAuth state DDL matches ORM and protects one-use history against rollback."""

from datetime import datetime, timedelta

import pytest
import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext

from app.models.connector_oauth_state import ConnectorOAuthState
from app.tests.services.test_migration_127_connector_connections import load


def test_oauth_130_ddl_keeps_state_history_and_matches_model():
    migration = load("130_connector_oauth_states")
    assert migration.down_revision == "129_connector_governance"
    engine = sa.create_engine("sqlite://")
    with engine.begin() as bind:
        meta = sa.MetaData()
        sa.Table("users", meta, sa.Column("id", sa.String(36), primary_key=True))
        sa.Table(
            "connections",
            meta,
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("workspace_id", sa.String(36)),
            sa.UniqueConstraint("workspace_id", "id"),
        )
        meta.create_all(bind)
        migration.op = Operations(MigrationContext.configure(bind))
        migration.upgrade()
        columns = {c["name"] for c in sa.inspect(bind).get_columns("connector_oauth_states")}
        assert columns == set(ConnectorOAuthState.__table__.columns.keys())
        table = sa.Table("connector_oauth_states", sa.MetaData(), autoload_with=bind)
        bind.execute(
            table.insert().values(
                id="state",
                state_sha256="a" * 64,
                workspace_id="ws",
                connection_id="connection",
                connection_revision=1,
                owner_user_id="user",
                verifier_ref="secret://user/user/opaque",
                redirect_uri="https://agentium.example/connectors/connections",
                scopes=["read"],
                expires_at=datetime.utcnow() + timedelta(minutes=10),
                created_at=datetime.utcnow(),
            )
        )
        with pytest.raises(RuntimeError, match="authorization records"):
            migration.downgrade()
        assert bind.execute(sa.select(table.c.state_sha256)).scalar() == "a" * 64
        bind.execute(table.delete())
        migration.downgrade()
        assert "connector_oauth_states" not in sa.inspect(bind).get_table_names()
