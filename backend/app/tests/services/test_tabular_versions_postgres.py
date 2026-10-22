"""Dataset version allocation against real concurrent PostgreSQL transactions.

Set DATASET_POSTGRES_URL to a disposable PostgreSQL database. Each test uses a
fresh schema and never queries or changes the database's existing tables.
"""

import os
from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from threading import Event
from time import monotonic
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.tabular import TabularDataset
from app.services.tabular_datasets import create_upload, register_frame, reserve_frame

pytestmark = pytest.mark.postgresql
NAME = "Claims facts"
SLUG = "claims-facts"


@pytest.fixture
def pg(tmp_path, monkeypatch):
    url = os.getenv("DATASET_POSTGRES_URL")
    if not url:
        pytest.skip("DATASET_POSTGRES_URL required for PostgreSQL qualification")
    schema = "dataset_version_probe_" + uuid4().hex
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(
        url,
        connect_args={
            "options": f"-csearch_path={schema} -clock_timeout=5000 -cstatement_timeout=10000"
        },
    )
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE workspaces (id varchar(36) PRIMARY KEY)"))
            connection.execute(text("CREATE TABLE systems (id varchar(36) PRIMARY KEY)"))
            connection.execute(text("INSERT INTO workspaces VALUES ('first'), ('other')"))
        TabularDataset.__table__.create(engine)
        monkeypatch.setattr(settings, "object_store_backend", "local")
        monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "store"))
        monkeypatch.setattr(settings, "tabular_data_enabled", True)
        monkeypatch.setattr(settings, "dataops_write_delta_enabled", False)
        yield engine
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def seed_version(engine, version):
    if version:
        with Session(engine) as db:
            db.add(
                TabularDataset(
                    workspace_id="first",
                    name=NAME,
                    slug=SLUG,
                    version=version,
                    source="postgresql",
                    status="deleted",
                )
            )
            db.commit()


def wait_for_database_lock(engine, pid):
    """Do not release the first transaction until the second really overlaps it.

    This observes any lock wait: the broken implementation waits on the unique
    index, then fails after the first commit; the fixed one waits before reading
    the last version. The race is observed in the database, not guessed from a
    delay between starting the threads.
    """
    deadline = monotonic() + 3
    pause = Event()
    while monotonic() < deadline:
        with engine.connect() as connection:
            waiting = connection.execute(
                text("SELECT EXISTS (SELECT 1 FROM pg_locks WHERE pid = :pid AND NOT granted)"),
                {"pid": pid},
            ).scalar()
        if waiting:
            return
        pause.wait(0.01)
    pytest.fail("Concurrent producer did not reach its database lock wait")


def produce(db, producer):
    if producer == "upload":
        return create_upload(
            db,
            workspace_id="first",
            name=NAME,
            filename="claims.csv",
            content_type="text/csv",
            payload=b"case_id\nC1\n",
        )
    if producer == "frame":
        import polars as pl

        return register_frame(
            db,
            workspace_id="first",
            name=NAME,
            frame=pl.DataFrame({"case_id": ["C1"]}),
            source="postgresql",
        )
    return reserve_frame(db, workspace_id="first", name=NAME, commit=False)


@pytest.mark.parametrize("previous", [0, 18])
@pytest.mark.parametrize("producer", ["upload", "frame", "reservation"])
def test_concurrent_producers_commit_distinct_versions(pg, previous, producer):
    seed_version(pg, previous)
    pids = Queue()

    def parallel():
        with Session(pg, autoflush=False, expire_on_commit=False) as db:
            pids.put(db.execute(text("SELECT pg_backend_pid()")).scalar())
            dataset = produce(db, producer)
            db.commit()
            return dataset.version

    with ThreadPoolExecutor(max_workers=1) as pool, Session(pg) as first:
        row = reserve_frame(first, workspace_id="first", name=NAME, commit=False)
        assert row.version == previous + 1
        result = pool.submit(parallel)
        try:
            wait_for_database_lock(pg, pids.get(timeout=3))
            first.commit()
        finally:
            first.rollback()
        assert result.result(timeout=5) == previous + 2

    with Session(pg) as db:
        versions = [
            version
            for (version,) in db.query(TabularDataset.version).order_by(TabularDataset.version)
        ]
    assert versions == ([previous] if previous else []) + [previous + 1, previous + 2]


def test_rollback_releases_version_for_waiting_producer(pg):
    seed_version(pg, 18)
    pids = Queue()

    def parallel():
        with Session(pg, expire_on_commit=False) as db:
            pids.put(db.execute(text("SELECT pg_backend_pid()")).scalar())
            return reserve_frame(db, workspace_id="first", name=NAME).version

    with ThreadPoolExecutor(max_workers=1) as pool, Session(pg) as first:
        abandoned = reserve_frame(first, workspace_id="first", name=NAME, commit=False)
        abandoned_id = abandoned.id
        result = pool.submit(parallel)
        try:
            wait_for_database_lock(pg, pids.get(timeout=3))
        finally:
            first.rollback()
        assert result.result(timeout=5) == 19
    with Session(pg) as db:
        assert db.get(TabularDataset, abandoned_id) is None
        assert db.query(TabularDataset).count() == 2


@pytest.mark.parametrize("workspace_id,name", [("other", NAME), ("first", "Other facts")])
def test_unrelated_dataset_lineages_do_not_wait(pg, workspace_id, name):
    def parallel():
        with Session(pg, expire_on_commit=False) as db:
            return reserve_frame(db, workspace_id=workspace_id, name=name).version

    with ThreadPoolExecutor(max_workers=1) as pool, Session(pg) as first:
        reserve_frame(first, workspace_id="first", name=NAME, commit=False)
        try:
            assert pool.submit(parallel).result(timeout=3) == 1
        finally:
            first.rollback()
