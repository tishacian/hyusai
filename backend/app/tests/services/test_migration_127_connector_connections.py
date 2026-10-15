"""Run real connection DDL against populated predecessor secrets; protect downgrades."""

import importlib.util
from datetime import datetime
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext

from app.models.connector_connection import ConnectorConnection, ConnectorDelegation, ConnectorGrant
from app.models.secret import Secret


def load(name):
    path = Path(__file__).resolve().parents[3] / "alembic" / "versions" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_127_preserves_secrets_matches_models_and_refuses_destructive_downgrade():
    old, migration = load("124_secret_registry"), load("127_connector_connections")
    assert migration.down_revision == "126_service_contracts"
    assert len(migration.revision) <= 32
    engine = sa.create_engine("sqlite://")
    with engine.begin() as bind:
        metadata = sa.MetaData()
        for name in ("workspaces", "users", "systems", "system_versions"):
            sa.Table(name, metadata, sa.Column("id", sa.String(36), primary_key=True))
        metadata.create_all(bind)
        operations = Operations(MigrationContext.configure(bind))
        old.op = migration.op = operations
        old.upgrade()
        bind.execute(sa.text("INSERT INTO workspaces VALUES ('ws')"))
        bind.execute(sa.text("INSERT INTO users VALUES ('alice')"))
        values = dict(
            id="legacy",
            scope="workspace",
            workspace_id="ws",
            owner_key="ws",
            name="old",
            kind="password",
            backend="db",
            current_version=1,
            metadata={},
            created_at=datetime.utcnow(),
        )
        predecessor = sa.Table("secrets", sa.MetaData(), autoload_with=bind)
        bind.execute(predecessor.insert().values(**values))
        bind.execute(
            sa.text(
                "INSERT INTO secret_versions (id,secret_id,version,ciphertext,created_at) VALUES ('v1','legacy',1,'opaque-ciphertext',CURRENT_TIMESTAMP)"
            )
        )
        migration.upgrade()
        inspector = sa.inspect(bind)
        for model in (Secret, ConnectorConnection, ConnectorGrant, ConnectorDelegation):
            assert {c["name"] for c in inspector.get_columns(model.__tablename__)} == set(
                model.__table__.columns.keys()
            )
        assert (
            bind.execute(sa.text("SELECT ciphertext FROM secret_versions")).scalar()
            == "opaque-ciphertext"
        )
        current = sa.Table("secrets", sa.MetaData(), autoload_with=bind)
        bind.execute(
            current.insert().values(
                **(
                    values
                    | {
                        "id": "personal",
                        "scope": "user",
                        "user_id": "alice",
                        "owner_key": "pair",
                        "name": "oauth",
                    }
                )
            )
        )
        with pytest.raises(RuntimeError, match="personal secrets"):
            migration.downgrade()
        bind.execute(sa.text("DELETE FROM secrets WHERE id='personal'"))
        connection = sa.Table("connections", sa.MetaData(), autoload_with=bind)
        bind.execute(
            connection.insert().values(
                id="conn",
                workspace_id="ws",
                name="ERP",
                profile_key="postgresql",
                profile_version=1,
                values={},
                secret_refs={},
                access="read",
                allowed_schemas=[],
                allowed_tables=[],
                revision=1,
                created_by="alice",
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
        )
        with pytest.raises(RuntimeError, match="governance"):
            migration.downgrade()
        bind.execute(sa.text("DELETE FROM connections"))
        migration.downgrade()
        assert "connections" not in sa.inspect(bind).get_table_names()
        assert "user_id" not in {c["name"] for c in sa.inspect(bind).get_columns("secrets")}
        assert (
            bind.execute(sa.text("SELECT ciphertext FROM secret_versions")).scalar()
            == "opaque-ciphertext"
        )
