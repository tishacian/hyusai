"""Round-trip contract for migration 082's product taxonomy backfill."""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import sqlalchemy as sa


def _load_migration():
    path = (
        Path(__file__).resolve().parents[3]
        / "alembic"
        / "versions"
        / "082_skill_category.py"
    )
    saved = sys.modules.get("alembic")
    stub = types.ModuleType("alembic")
    stub.op = types.SimpleNamespace()
    sys.modules["alembic"] = stub
    try:
        spec = importlib.util.spec_from_file_location("migration_082", path)
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

    def create_index(self, name, table_name, columns):
        self.bind.execute(
            sa.text(f'CREATE INDEX "{name}" ON "{table_name}" ({", ".join(columns)})')
        )

    def drop_index(self, name, table_name=None):
        self.bind.execute(sa.text(f'DROP INDEX "{name}"'))


def test_revision_chains_onto_the_publication_posture_head():
    assert MIG.revision == "082_skill_category"
    assert MIG.down_revision == "081_flow_publication_default_posture"


def test_upgrade_categorises_the_catalog_and_leaves_unknown_slugs_null(monkeypatch):
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
                {"id": "s2", "slug": "voice_tts_v1", "name": "Voice TTS"},
                # A workspace-defined Skill predating the column: the backfill
                # must not invent a taxonomy for a slug it does not know.
                {"id": "s3", "slug": "acme_custom_op_v1", "name": "Acme custom"},
            ],
        )
        monkeypatch.setattr(MIG, "op", _SQLiteOps(bind))

        MIG.upgrade()

        rows = dict(
            bind.execute(sa.text("SELECT slug, category FROM skills")).all()
        )
        assert rows == {
            "semantic_search_v1": "Retrieval",
            "voice_tts_v1": "Voice",
            "acme_custom_op_v1": None,
        }

        MIG.downgrade()

        columns = {column["name"] for column in sa.inspect(bind).get_columns("skills")}
        assert "category" not in columns
        assert bind.execute(sa.text("SELECT COUNT(*) FROM skills")).scalar_one() == 3
