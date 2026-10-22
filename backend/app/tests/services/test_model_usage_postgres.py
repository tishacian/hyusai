"""Real PostgreSQL reservation races; each test owns a disposable schema."""

import os
import threading
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models.model_usage import (
    ModelUsageCall,
    UsageBudgetBucket,
    UsageBudgetPolicy,
    UsageReservation,
)
from app.models.system import System
from app.models.tabular import TabularDataset
from app.models.workspace import Workspace
from app.services import model_usage as usage


@pytest.fixture
def pg_usage(monkeypatch):
    url = os.getenv("MODEL_USAGE_POSTGRES_URL")
    if not url:
        pytest.skip("MODEL_USAGE_POSTGRES_URL required")
    schema = "model_usage_" + uuid4().hex
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(
        url,
        connect_args={
            "options": f"-csearch_path={schema} -clock_timeout=8000 -cstatement_timeout=15000"
        },
    )
    try:
        Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine)
        monkeypatch.setattr(usage, "SessionLocal", factory)
        monkeypatch.setattr(usage, "budget_readiness", lambda _: {"ready": True})
        with factory() as db:
            workspace = Workspace(id="usage-ws", name="Usage", slug="usage")
            system = System(id="usage-app", workspace_id=workspace.id, name="App")
            db.add(workspace)
            db.flush()
            db.add(system)
            db.commit()
            actor = SimpleNamespace(id="test-operator")
            usage.create_tariff(
                db,
                workspace,
                actor,
                provider="openai",
                model="test",
                currency="USD",
                input_per_million="1000",
                output_per_million="2000",
            )
            usage.save_budget(
                db,
                workspace,
                actor,
                scope="workspace",
                enabled=True,
                max_tokens=200,
                currency_limits={"USD": "0.3"},
                expected_revision=0,
            )
            usage.save_budget(
                db,
                workspace,
                actor,
                scope="system",
                system_id=system.id,
                enabled=True,
                max_tokens=200,
                currency_limits={"USD": "0.3"},
                expected_revision=0,
            )
        yield SimpleNamespace(
            factory=factory, ctx=usage.UsageContext("usage-ws", system_id="usage-app")
        )
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def _prepare(s, key):
    return usage.prepare_call(
        s.ctx,
        request_key=key,
        provider="openai",
        model="test",
        input_token_bound=100,
        output_token_bound=100,
        admission_qualified=True,
    )


def test_concurrent_admission_only_one_call_fits_all_shared_limits(pg_usage):
    s = pg_usage
    barrier = threading.Barrier(2)

    def attempt(key):
        barrier.wait(timeout=5)
        try:
            return _prepare(s, key)["status"]
        except usage.UsageError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(attempt, str(i)) for i in range(2)]
        results = [f.result(timeout=10) for f in futures]
    assert sorted(results) == ["USAGE_BUDGET_EXHAUSTED", "prepared"]
    with s.factory() as db:
        assert db.query(UsageReservation).count() == 2
        buckets = db.query(UsageBudgetBucket).all()
        assert len(buckets) == 2
        assert all(b.reserved_tokens == 200 and b.consumed_tokens == 0 for b in buckets)
        assert all(Decimal(b.reserved_amounts["USD"]) == Decimal("0.3") for b in buckets)


def _dataset():
    return TabularDataset(
        id=str(uuid4()),
        workspace_id="usage-ws",
        name="Scored",
        slug=uuid4().hex,
        source="score",
        status="ingesting",
    )


@pytest.mark.parametrize("legacy_for_update", [False, True])
def test_usage_lock_allows_concurrent_canonical_dataset_fk_insert(pg_usage, legacy_for_update):
    """A budget transaction must not stall DataOps' workspace FK validation."""
    with pg_usage.factory() as budget, pg_usage.factory() as dataops:
        if legacy_for_update:
            budget.query(Workspace).filter_by(id="usage-ws").with_for_update().one()
        else:
            usage._workspace_lock(budget, "usage-ws")
        dataops.execute(text("SET LOCAL lock_timeout = '500ms'"))
        dataset = _dataset()
        dataops.add(dataset)
        # Real INSERT checks the Workspace FK using PostgreSQL FOR KEY SHARE.
        # FOR UPDATE in the budget transaction makes this fail on lock_timeout.
        if legacy_for_update:
            with pytest.raises(OperationalError) as error:
                dataops.commit()
            assert error.value.orig.pgcode == "55P03"  # lock_not_available
            dataops.rollback()
        else:
            dataops.commit()
            assert dataops.get(TabularDataset, dataset.id) is not None
        budget.rollback()


def test_uncommitted_dataset_fk_allows_budget_update_and_provider_admission(pg_usage):
    """A pending native publication must not block usage admission or a policy edit."""
    with pg_usage.factory() as dataops, pg_usage.factory() as budgets:
        dataops.add(_dataset())
        dataops.flush()  # Keep the actual FK KEY SHARE lock until rollback below.
        budgets.execute(text("SET LOCAL lock_timeout = '1000ms'"))
        workspace = budgets.get(Workspace, "usage-ws")
        policy = usage.save_budget(
            budgets,
            workspace,
            SimpleNamespace(id="test-operator"),
            scope="workspace",
            enabled=True,
            max_tokens=200,
            currency_limits={"USD": "0.3"},
            expected_revision=1,
        )
        assert policy["revision"] == 2
        assert _prepare(pg_usage, "during-native-publication")["status"] == "prepared"
        with pytest.raises(usage.UsageError, match="USAGE_BUDGET_EXHAUSTED"):
            _prepare(pg_usage, "second-during-native-publication")
        dataops.rollback()
    with pg_usage.factory() as db:
        assert db.query(TabularDataset).count() == 0
        assert db.query(UsageReservation).count() == 2
        assert all(b.reserved_tokens == 200 for b in db.query(UsageBudgetBucket).all())


def test_concurrent_budget_edits_keep_one_revision_owner(pg_usage):
    """NO KEY UPDATE remains exclusive between budget writers in one workspace."""
    barrier = threading.Barrier(2)

    def edit():
        with pg_usage.factory() as db:
            workspace = db.get(Workspace, "usage-ws")
            barrier.wait(timeout=5)
            try:
                result = usage.save_budget(
                    db,
                    workspace,
                    SimpleNamespace(id="test-operator"),
                    scope="workspace",
                    enabled=True,
                    max_tokens=200,
                    currency_limits={"USD": "0.3"},
                    expected_revision=1,
                )
                return str(result["revision"])
            except usage.UsageError as exc:
                return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [future.result(timeout=10) for future in [pool.submit(edit), pool.submit(edit)]]
    assert sorted(results) == ["2", "USAGE_BUDGET_REVISION_CONFLICT"]
    with pg_usage.factory() as db:
        policy = db.query(UsageBudgetPolicy).filter_by(scope_key="workspace").one()
        assert policy.revision == 2
        assert [entry["revision"] for entry in policy.history] == [1, 2]


def test_concurrent_duplicate_reservation_and_dispatch_are_single_owner(pg_usage):
    s = pg_usage
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(_prepare, s, "same") for _ in range(2)]
        calls = [future.result(timeout=10) for future in futures]
    assert calls[0]["id"] == calls[1]["id"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(usage.mark_dispatched, [calls[0]["id"]] * 2))
    assert sorted(claims) == [False, True]
    with s.factory() as db:
        assert db.query(ModelUsageCall).count() == 1
        assert db.query(UsageReservation).count() == 2


def test_concurrent_settlement_is_idempotent(pg_usage):
    s = pg_usage
    call = _prepare(s, "one")
    usage.mark_dispatched(call["id"])

    def settle():
        return usage.settle_call(call["id"], usage={"input_tokens": 10, "output_tokens": 10})

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(settle) for _ in range(2)]
        for future in futures:
            future.result(timeout=10)
    with s.factory() as db:
        assert all(
            row.consumed_tokens == 20 and row.reserved_tokens == 0
            for row in db.query(UsageBudgetBucket).all()
        )


def test_native_hook_failure_rolls_back_both_scopes(pg_usage):
    s = pg_usage

    def reject(db, call):
        db.flush()
        assert db.query(UsageReservation).count() == 2
        raise RuntimeError("native budget denied")

    with pytest.raises(RuntimeError, match="native budget denied"):
        usage.prepare_call(
            s.ctx,
            request_key="hook",
            provider="openai",
            model="test",
            input_token_bound=100,
            output_token_bound=100,
            admission_qualified=True,
            admission_hook=reject,
        )
    assert _prepare(s, "after-rollback")["status"] == "prepared"


def test_migration_creates_identical_usage_contract_and_reverses(pg_usage):
    import importlib.util
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import inspect

    path = Path(__file__).resolve().parents[3] / "alembic/versions/146_model_usage_budgets.py"
    spec = importlib.util.spec_from_file_location("usage_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with pg_usage.factory().get_bind().begin() as connection:
        module.op = Operations(MigrationContext.configure(connection))
        module.downgrade()
        assert "model_usage_calls" not in inspect(connection).get_table_names()
        module.upgrade()
        names = {column["name"] for column in inspect(connection).get_columns("model_usage_calls")}
        assert names == set(ModelUsageCall.__table__.columns.keys())
        assert inspect(connection).get_unique_constraints("model_usage_reservations")[0][
            "column_names"
        ] == ["call_id", "bucket_id"]
        module.downgrade()
        assert "model_usage_calls" not in inspect(connection).get_table_names()
