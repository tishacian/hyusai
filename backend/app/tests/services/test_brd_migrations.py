"""Exercise additive BRD migrations and their replay constraints."""
import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
import sqlalchemy as sa


def test_brd_migrations_upgrade_constraints_and_downgrade():
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        for table in ("workspaces", "users", "systems"):
            connection.exec_driver_sql(f"CREATE TABLE {table} (id VARCHAR(36) PRIMARY KEY)")
        connection.exec_driver_sql("INSERT INTO workspaces VALUES ('workspace')")
        connection.exec_driver_sql("INSERT INTO users VALUES ('author')")
        migrations = []
        for filename in ("106_brd_documents.py", "107_brd_proposals.py"):
            path = Path(__file__).resolve().parents[3] / "alembic" / "versions" / filename
            spec = importlib.util.spec_from_file_location(filename[:-3], path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            module.op = Operations(MigrationContext.configure(connection))
            module.upgrade()
            migrations.append(module)
        metadata = sa.MetaData()
        metadata.reflect(connection)
        documents = metadata.tables["brd_documents"]
        proposals = metadata.tables["brd_proposals"]
        from datetime import datetime
        document = dict(id="doc", workspace_id="workspace", created_by_user_id="author",
                        sha256="a" * 64, size_bytes=3, filename="brd.docx", storage_key="key",
                        extraction={}, created_at=datetime.now())
        connection.execute(documents.insert().values(**document))
        with pytest.raises(sa.exc.IntegrityError):
            with connection.begin_nested():
                connection.execute(documents.insert().values(**{**document, "id": "duplicate"}))
        proposal = dict(id="proposal", workspace_id="workspace", document_id="doc",
                        created_by_user_id="author", request_key="key", sha256="b" * 64,
                        proposal={}, status="proposed", created_at=datetime.now())
        connection.execute(proposals.insert().values(**proposal))
        with pytest.raises(sa.exc.IntegrityError):
            with connection.begin_nested():
                connection.execute(proposals.insert().values(**{**proposal, "id": "duplicate"}))
        for module in reversed(migrations):
            module.downgrade()
        assert set(sa.inspect(connection).get_table_names()) == {"workspaces", "users", "systems"}
