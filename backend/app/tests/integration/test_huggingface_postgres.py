"""Opt-in PostgreSQL concurrency checks in an isolated disposable schema.

RUN_HF_POSTGRES_TESTS=1 HF_TEST_POSTGRES_URL=postgresql+psycopg2://.../test_hf...
Each test owns a fresh schema; no application schema is reset or reused.
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models.huggingface import HubArtifact, HubImportReservation
from app.models.user import User
from app.models.workspace import Workspace
from app.models.workspace_job import WorkspaceJob
from app.services.huggingface import registry
from app.services.huggingface.errors import HFError

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_HF_POSTGRES_TESTS") != "1", reason="isolated PostgreSQL integration is opt-in"
)


@pytest.fixture
def postgres(monkeypatch):
    url = sa.engine.make_url(os.environ["HF_TEST_POSTGRES_URL"])
    if url.get_backend_name() != "postgresql" or not (url.database or "").startswith("test_hf"):
        raise RuntimeError("HF PostgreSQL tests require a database named test_hf*")
    schema = "hf_test_" + uuid4().hex
    admin = sa.create_engine(url)
    with admin.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    engine = sa.create_engine(
        url, connect_args={"options": f"-csearch_path={schema} -clock_timeout=5000"}
    )
    try:
        Base.metadata.create_all(engine)
        sessions = sessionmaker(bind=engine, autoflush=False)
        with sessions() as db:
            user = User(id=str(uuid4()), username="hf-test-admin")
            workspace = Workspace(
                id=str(uuid4()), name="HF concurrency", slug="hf-concurrency", settings={}
            )
            db.add_all([user, workspace])
            db.commit()
            workspace_id, user_id = workspace.id, user.id
        monkeypatch.setattr(registry.settings, "hf_disk_min_free_bytes", 0)
        monkeypatch.setattr(registry.settings, "hf_cache_dir", "/tmp")
        yield sessions, workspace_id, user_id
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        admin.dispose()


def metadata():
    return {
        "hub_endpoint": "https://huggingface.co",
        "kind": "model",
        "repo_id": "tests/concurrent-model",
        "revision": "a" * 40,
        "requested_ref": "main",
        "license": "mit",
        "license_text": "MIT terms",
        "files": [
            {
                "path": "Q4.gguf",
                "size_bytes": 8,
                "upstream_hash": {"algorithm": "sha256", "value": "b" * 64},
            },
            {
                "path": "Q8.gguf",
                "size_bytes": 16,
                "upstream_hash": {"algorithm": "sha256", "value": "c" * 64},
            },
        ],
    }


def submit(sessions, workspace_id, user_id, gate, *, variant="Q4.gguf", request_key=None):
    with sessions() as db:
        gate.wait(timeout=5)
        try:
            artifact, job = registry.request_import(
                db,
                workspace_id=workspace_id,
                actor_id=user_id,
                metadata=metadata(),
                selection={"format": "gguf", "variant": variant},
                job_key=request_key,
                dispatch=False,
            )
            return "accepted", artifact.id, job.id
        except HFError as exc:
            db.rollback()
            return exc.code, None, None


def test_two_concurrent_imports_cannot_exceed_one_reservation(postgres):
    sessions, workspace_id, user_id = postgres
    with sessions() as db:
        registry.set_limits(db, {"workspace_imports": 1}, actor=user_id)
    gate = Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as pool:
        tasks = [
            pool.submit(submit, sessions, workspace_id, user_id, gate, variant=variant)
            for variant in ("Q4.gguf", "Q8.gguf")
        ]
        results = [task.result(timeout=15) for task in tasks]
    assert sorted(item[0] for item in results) == ["HF_QUOTA_EXCEEDED", "accepted"]
    with sessions() as db:
        assert db.query(HubImportReservation).count() == 1
        assert db.query(HubArtifact).count() == 1
        assert db.query(WorkspaceJob).filter_by(kind="hf_import").count() == 1


def test_duplicate_concurrent_idempotency_key_publishes_one_job(postgres):
    sessions, workspace_id, user_id = postgres
    with sessions() as db:
        registry.set_limits(db, {"workspace_imports": 1}, actor=user_id)
    gate = Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as pool:
        tasks = [
            pool.submit(submit, sessions, workspace_id, user_id, gate, request_key="same-request")
            for _ in range(2)
        ]
        results = [task.result(timeout=15) for task in tasks]
    assert results[0] == results[1]
    assert results[0][0] == "accepted"
    with sessions() as db:
        assert db.query(HubImportReservation).count() == 1
        assert db.query(WorkspaceJob).filter_by(kind="hf_import").count() == 1


def test_admission_lock_blocks_other_connection_until_commit(postgres):
    sessions, _workspace_id, _user_id = postgres
    started, acquired = Event(), Event()
    with sessions() as first:
        registry.admission_lock(first)

        def competitor():
            with sessions() as second:
                started.set()
                registry.admission_lock(second)
                acquired.set()
                second.commit()

        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(competitor)
            assert started.wait(timeout=2)
            assert not acquired.wait(timeout=0.1)
            first.commit()
            pending.result(timeout=5)
        assert acquired.is_set()


def test_migration_upgrade_and_downgrade_on_postgresql(postgres, monkeypatch):
    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext

    from app.tests.services.test_migration_123_huggingface_connector import (
        HUB_TABLES,
        load_migration,
        predecessor_schema,
    )

    sessions, _workspace_id, _user_id = postgres
    engine = sessions.kw["bind"]
    schema = "hf_migration_" + uuid4().hex
    with engine.begin() as bind:
        bind.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
        bind.exec_driver_sql(f'SET LOCAL search_path TO "{schema}"')
        predecessor_schema(bind)
        migration = load_migration()
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(bind)))
        migration.upgrade()
        assert HUB_TABLES.issubset(sa.inspect(bind).get_table_names(schema=schema))
        assert bind.execute(
            sa.text("SELECT connection, policy FROM hf_platform_config WHERE id='default'")
        ).one() == ({}, {})
        assert bind.execute(
            sa.text(
                "SELECT embedding_model, vector_collection_name, active_generation FROM knowledge_collections"
            )
        ).one() == ("legacy-model", "ws__manuals", None)
        migration.downgrade()
        assert not HUB_TABLES.intersection(sa.inspect(bind).get_table_names(schema=schema))
        assert bind.execute(
            sa.text("SELECT embedding_model, vector_collection_name FROM knowledge_collections")
        ).one() == ("legacy-model", "ws__manuals")
        bind.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
