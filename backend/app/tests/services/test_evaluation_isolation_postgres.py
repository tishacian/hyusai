"""Migration qualification on a disposable schema; no existing data is changed."""

import importlib.util
import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError


def test_145_upgrade_preserves_business_rows_and_downgrade_reverses():
    url = os.getenv("DATASET_POSTGRES_URL")
    if not url:
        pytest.skip("DATASET_POSTGRES_URL required")
    schema = "evaluation_migration_" + uuid4().hex
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    path = Path(__file__).resolve().parents[3] / "alembic/versions/145_evaluation_isolation.py"
    spec = importlib.util.spec_from_file_location("evaluation_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    try:
        with engine.begin() as connection:
            connection.execute(
                text("CREATE TABLE evaluation_campaigns (id varchar(36) PRIMARY KEY)")
            )
            for table in migration.TABLES:
                connection.execute(text(f"CREATE TABLE {table} (id varchar(36) PRIMARY KEY)"))
                connection.execute(text(f"INSERT INTO {table} VALUES ('business')"))
            migration.op = Operations(MigrationContext.configure(connection))
            migration.upgrade()
            for table in migration.TABLES:
                assert (
                    connection.execute(text(f"SELECT evaluation_campaign_id FROM {table}")).scalar()
                    is None
                )
                assert any(
                    i["column_names"] == ["evaluation_campaign_id"]
                    for i in inspect(connection).get_indexes(table)
                )
                assert (
                    inspect(connection).get_foreign_keys(table)[0]["options"]["ondelete"]
                    == "RESTRICT"
                )
            with pytest.raises(IntegrityError), connection.begin_nested():
                connection.execute(text("UPDATE runs SET evaluation_campaign_id='absent'"))
            connection.execute(text("INSERT INTO evaluation_campaigns VALUES ('campaign')"))
            connection.execute(text("INSERT INTO runs VALUES ('qa', 'campaign', '{}')"))
            with pytest.raises(IntegrityError), connection.begin_nested():
                connection.execute(text("DELETE FROM evaluation_campaigns WHERE id='campaign'"))
            migration.downgrade()
            for table in migration.TABLES:
                assert {column["name"] for column in inspect(connection).get_columns(table)} == {
                    "id"
                }
                assert (
                    connection.execute(
                        text(f"SELECT count(*) FROM {table} WHERE id='business'")
                    ).scalar()
                    == 1
                )
            migration.upgrade()
            migration.downgrade()
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()
