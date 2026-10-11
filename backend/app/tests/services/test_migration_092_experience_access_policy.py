"""Contract tests for the Experience access/identity repair migration."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest
import sqlalchemy as sa


def _load_migration():
    path = (
        Path(__file__).resolve().parents[3]
        / "alembic"
        / "versions"
        / "092_experience_access_policy.py"
    )
    saved = sys.modules.get("alembic")
    stub = types.ModuleType("alembic")
    stub.op = types.SimpleNamespace()
    sys.modules["alembic"] = stub
    try:
        spec = importlib.util.spec_from_file_location("migration_092", path)
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


@pytest.fixture()
def bind(monkeypatch):
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        metadata = sa.MetaData()
        sa.Table(
            "experiences",
            metadata,
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("slug", sa.String(120), nullable=False),
            sa.Column("pattern", sa.String(32), nullable=False),
            sa.Column("theme", sa.JSON(), nullable=False),
        )
        sa.Table(
            "experience_releases",
            metadata,
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("experience_id", sa.String(36), nullable=False),
            sa.Column("access_snapshot", sa.JSON(), nullable=False),
        )
        sa.Table(
            "experience_deployments",
            metadata,
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("experience_id", sa.String(36), nullable=False),
            sa.Column("channel", sa.String(16), nullable=False),
            sa.Column("audience", sa.JSON(), nullable=False),
        )
        metadata.create_all(connection)

        def add_column(table_name: str, column: sa.Column) -> None:
            type_sql = column.type.compile(dialect=connection.dialect)
            connection.execute(
                sa.text(
                    f'ALTER TABLE "{table_name}" ADD COLUMN "{column.name}" '
                    f"{type_sql} NOT NULL DEFAULT '{{}}'"
                )
            )

        monkeypatch.setattr(
            MIG,
            "op",
            types.SimpleNamespace(add_column=add_column, get_bind=lambda: connection),
        )
        yield connection, metadata


def test_upgrade_separates_access_and_backfills_every_release_identity(bind) -> None:
    connection, metadata = bind
    experiences = metadata.tables["experiences"]
    releases = metadata.tables["experience_releases"]
    deployments = metadata.tables["experience_deployments"]
    connection.execute(
        experiences.insert(),
        [
            {
                "id": "xp-valid",
                "name": "Published App",
                "slug": "published-app",
                "pattern": "dashboard",
                "theme": {
                    "mode": "light",
                    "audience": {
                        "role_templates": ["workspace_viewer"],
                        "groups": ["pilot-a"],
                    },
                },
            },
            {
                "id": "xp-malformed",
                "name": "Closed App",
                "slug": "closed-app",
                "pattern": "approval",
                "theme": {"audience": {"roles": "workspace_viewer"}},
            },
        ],
    )
    connection.execute(
        releases.insert(),
        [
            {"id": "r-valid", "experience_id": "xp-valid", "access_snapshot": {}},
            {"id": "r-closed", "experience_id": "xp-malformed", "access_snapshot": {}},
        ],
    )
    connection.execute(
        deployments.insert(),
        [
            {
                "id": "d-valid",
                "experience_id": "xp-valid",
                "channel": "live",
                "audience": {},
            },
            {
                "id": "d-closed",
                "experience_id": "xp-malformed",
                "channel": "live",
                "audience": {},
            },
        ],
    )

    MIG.upgrade()

    reflected = sa.MetaData()
    reflected.reflect(connection)
    xp = reflected.tables["experiences"]
    rel = reflected.tables["experience_releases"]
    dep = reflected.tables["experience_deployments"]
    valid = connection.execute(sa.select(xp).where(xp.c.id == "xp-valid")).one()._mapping
    closed = connection.execute(
        sa.select(xp).where(xp.c.id == "xp-malformed")
    ).one()._mapping
    assert valid["theme"] == {"mode": "light"}
    assert valid["access_policy"] == {
        "roles": ["workspace_viewer"],
        "groups": ["pilot-a"],
    }
    assert closed["access_policy"] == MIG._FAIL_CLOSED_POLICY

    release_rows = {
        row._mapping["id"]: row._mapping
        for row in connection.execute(sa.select(rel)).all()
    }
    assert release_rows["r-valid"]["access_snapshot"] == valid["access_policy"]
    assert release_rows["r-valid"]["identity_snapshot"] == {
        "name": "Published App",
        "slug": "published-app",
        "pattern": "dashboard",
    }
    assert release_rows["r-closed"]["access_snapshot"] == MIG._FAIL_CLOSED_POLICY
    deployment_rows = {
        row._mapping["id"]: row._mapping["audience"]
        for row in connection.execute(sa.select(dep)).all()
    }
    assert deployment_rows["d-valid"] == valid["access_policy"]
    assert deployment_rows["d-closed"] == MIG._FAIL_CLOSED_POLICY
