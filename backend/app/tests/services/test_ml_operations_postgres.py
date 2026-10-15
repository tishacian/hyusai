"""Real PostgreSQL transaction/lease qualification; entirely local, no sends."""

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.db.base import Base
from app.models.ml_operations import (
    MLAlert,
    MLAlertChannel,
    MLAlertDelivery,
    MLInferenceUsage,
    MLUsageRollup,
)
from app.models.tabular import MLModel
from app.models.workspace import Workspace
from app.services import ml_alerts as alerts
from app.services import ml_operations as usage


@pytest.fixture
def pg(monkeypatch):
    url = os.getenv("MLOPS_POSTGRES_URL")
    if not url:
        pytest.skip("MLOPS_POSTGRES_URL required for PostgreSQL qualification")
    schema = "mlops_probe_" + uuid4().hex
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
        Base.metadata.create_all(engine)
        monkeypatch.setitem(settings.__dict__, "ml_operations_enabled", True)
        monkeypatch.setitem(settings.__dict__, "ml_alerts_enabled", True)
        with Session(engine) as db:
            db.add(Workspace(id="mlops-pg", slug="mlops-pg", name="PG probe"))
            db.flush()
            db.add(
                MLModel(
                    id="model",
                    workspace_id="mlops-pg",
                    name="Model",
                    slug="model",
                    task="classification",
                    algo="linear",
                    target="label",
                    status="ready",
                )
            )
            db.add(
                MLAlertChannel(
                    id="channel",
                    workspace_id="mlops-pg",
                    name="Local stub",
                    kind="email",
                    destination_email="stub@example.invalid",
                    created_by="operator",
                )
            )
            db.commit()
        yield engine
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def seed_usage(pg):
    with Session(pg) as db:
        model = db.get(MLModel, "model")
        for i in range(12):
            usage.record_inference(
                db,
                requested=model,
                served=model,
                caller="api_key",
                row_count=10,
                duration_ms=20,
                event_id=str(i),
            )
        db.commit()


def seed_alert(pg):
    with Session(pg) as db:
        result = alerts.emit_alert(
            db,
            model=db.get(MLModel, "model"),
            event_type="monitor_failed",
            state="failed",
            source_id="run",
        )
        db.commit()
        return result.id


def test_rollup_skip_locked_rollback_and_replay_are_exact(pg):
    seed_usage(pg)
    with Session(pg) as first, ThreadPoolExecutor(max_workers=1) as pool:
        assert usage.rollup_usage(first) == 12

        def parallel():
            with Session(pg) as second:
                count = usage.rollup_usage(second)
                second.commit()
                return count

        assert pool.submit(parallel).result(timeout=5) == 0
        first.rollback()
        assert pool.submit(parallel).result(timeout=5) == 12
        assert pool.submit(parallel).result(timeout=5) == 0
    with Session(pg) as db:
        aggregate = db.query(MLUsageRollup).one()
        assert (aggregate.requests, aggregate.rows) == (12, 120)
        assert db.query(MLInferenceUsage).filter_by(rolled_up_at=None).count() == 0


def test_alert_and_outbox_rollback_atomically(pg):
    with Session(pg) as db:
        alerts.emit_alert(
            db,
            model=db.get(MLModel, "model"),
            event_type="monitor_failed",
            state="failed",
            source_id="rolled-back",
        )
        db.rollback()
    with Session(pg) as db:
        assert db.query(MLAlert).count() == db.query(MLAlertDelivery).count() == 0


def test_outbox_claim_skips_locked_then_reclaims_after_rollback(pg):
    seed_alert(pg)
    now = datetime.utcnow()
    with Session(pg) as first, ThreadPoolExecutor(max_workers=1) as pool:
        claim = alerts.claim_delivery(first, now=now)

        def parallel():
            with Session(pg) as second:
                result = alerts.claim_delivery(second, now=now)
                second.commit()
                return result

        assert pool.submit(parallel).result(timeout=5) is None
        first.rollback()
        next_claim = pool.submit(parallel).result(timeout=5)
        assert next_claim["id"] == claim["id"]
        assert next_claim["token"] != claim["token"]
    with Session(pg) as db:
        assert db.get(MLAlertDelivery, claim["id"]).attempts == 1


def test_expired_sender_cannot_acknowledge_replacement_lease(pg):
    seed_alert(pg)
    now = datetime.utcnow()
    sessions = sessionmaker(pg)
    replacement = []

    def sender(_db, row):
        # No network: emulate the first worker stalling past its lease.
        with Session(pg) as next_worker:
            replacement.append(alerts.claim_delivery(next_worker, now=now + timedelta(seconds=91)))
            next_worker.commit()
        return None

    assert alerts.deliver_pending(sessions, limit=1, sender=sender, now=now) == 0
    with Session(pg) as db:
        row = db.get(MLAlertDelivery, replacement[0]["id"])
        assert row.status == "sending"
        assert row.lease_token == replacement[0]["token"]
        assert row.delivered_at is None


def test_migration_137_roundtrip_and_guard_on_postgres(pg, monkeypatch):
    import importlib.util
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import inspect

    path = Path(__file__).resolve().parents[3] / "alembic/versions/137_mlops_operations.py"
    spec = importlib.util.spec_from_file_location("mlops_migration_137", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    names = [
        "ml_alert_sources",
        "ml_alert_deliveries",
        "ml_alerts",
        "ml_alert_states",
        "ml_alert_channels",
        "ml_usage_rollups",
        "ml_inference_usage",
    ]
    with pg.begin() as connection:
        for name in names:
            Base.metadata.tables[name].drop(connection)
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
        migration.upgrade()
        columns = {row["name"] for row in inspect(connection).get_columns("ml_usage_rollups")}
        assert {"tariff_rows", "cpu_requests"} <= columns
        migration.downgrade()
        assert not set(names) & set(inspect(connection).get_table_names())
        migration.upgrade()
    seed_usage(pg)
    with pg.begin() as connection:
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
        with pytest.raises(RuntimeError, match="DOWNGRADE_NOT_EMPTY"):
            migration.downgrade()
        assert set(names) <= set(inspect(connection).get_table_names())
