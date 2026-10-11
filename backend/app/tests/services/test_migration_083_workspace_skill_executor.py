"""Round-trip contract for migration 083's workspace runtime binding column."""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest
import sqlalchemy as sa

from app.services.skills_registry.binding import SkillBindingError
from app.services.skills_registry.executors import bind_executor


def _load_migration():
    path = (
        Path(__file__).resolve().parents[3]
        / "alembic"
        / "versions"
        / "083_workspace_skill_executor.py"
    )
    saved = sys.modules.get("alembic")
    stub = types.ModuleType("alembic")
    stub.op = types.SimpleNamespace()
    sys.modules["alembic"] = stub
    try:
        spec = importlib.util.spec_from_file_location("migration_083", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        if saved is not None:
            sys.modules["alembic"] = saved
        else:
            sys.modules.pop("alembic", None)
    return module


MIG = _load_migration()


class _SQLiteOps:
    def __init__(self, bind):
        self.bind = bind

    def get_bind(self):
        return self.bind

    def add_column(self, table_name, column):
        assert table_name == "skills"
        type_sql = column.type.compile(dialect=self.bind.dialect)
        self.bind.execute(
            sa.text(f'ALTER TABLE "{table_name}" ADD COLUMN "{column.name}" {type_sql}')
        )

    def drop_column(self, table_name, column_name):
        assert table_name == "skills"
        self.bind.execute(sa.text(f'ALTER TABLE "{table_name}" DROP COLUMN "{column_name}"'))


def test_revision_chains_onto_the_taxonomy_head():
    assert MIG.revision == "083_workspace_skill_executor"
    assert MIG.down_revision == "082_skill_category"


def test_upgrade_adds_a_null_binding_and_downgrade_keeps_the_rows(monkeypatch):
    engine = sa.create_engine("sqlite://")
    metadata = sa.MetaData()
    skills = sa.Table(
        "skills",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("slug", sa.String(160), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
    )
    metadata.create_all(engine)

    with engine.begin() as bind:
        bind.execute(
            skills.insert(),
            [
                {"id": "s1", "slug": "semantic_search_v1", "name": "Semantic Search"},
                {"id": "s2", "slug": "acme_custom_op_v1", "name": "Acme custom"},
            ],
        )
        monkeypatch.setattr(MIG, "op", _SQLiteOps(bind))

        MIG.upgrade()

        rows = dict(bind.execute(sa.text("SELECT slug, executor FROM skills")).all())
        assert rows == {"semantic_search_v1": None, "acme_custom_op_v1": None}

        MIG.downgrade()

        columns = {column["name"] for column in sa.inspect(bind).get_columns("skills")}
        assert "executor" not in columns
        assert bind.execute(sa.text("SELECT COUNT(*) FROM skills")).scalar_one() == 2


def test_a_row_cannot_become_runnable_merely_by_acquiring_the_column():
    """Why the upgrade backfills nothing.

    Every pre-existing row -- including the Skills a workspace already owns
    through ``enabled_skills`` side effects -- gets a null binding, and a null
    binding is not executable.
    """

    with pytest.raises(SkillBindingError) as refused:
        bind_executor(None)
    assert refused.value.code == "executor_required"
