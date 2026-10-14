"""Independent-review regressions at the rollout and storage boundaries."""

import importlib.util
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text

from app.api.v1.endpoints import dataops, service_contracts
from app.core.config import settings
from app.services.catalog_visibility import skill_is_visible
from app.services.dataops.compiler import expression
from app.services.dataops.preview import native_schema
from app.services.object_store import get_object_store
from app.tests.services.test_catalog_visibility import _skill, _workspace
from app.tests.services.test_service_contracts import candidate
from app.tests.services.test_service_contracts import setup as service_setup


@pytest.fixture
def setup(db_session, tmp_path, monkeypatch):
    return service_setup.__wrapped__(db_session, tmp_path, monkeypatch)


def client_for(api, setup):
    app = FastAPI()
    app.include_router(api.router, prefix="/review")
    app.dependency_overrides[api.get_db] = lambda: setup.db
    app.dependency_overrides[api.get_current_workspace] = lambda: setup.workspace
    app.dependency_overrides[api.get_current_user] = lambda: setup.owner
    return TestClient(app, base_url="http://testserver/review/")


def test_every_dataops_route_is_closed_before_any_processing(setup, monkeypatch):
    monkeypatch.setattr(settings, "dataops_enabled", False)
    client = client_for(dataops, setup)
    for route in dataops.router.routes:
        path = route.path.replace("{execution_id}", "missing")
        for method in route.methods:
            response = client.request(method, path, json={})
            assert response.status_code == 404, (method, path, response.text)
            assert response.json()["detail"]["code"] == "DATAPREP_DISABLED"
    setup.workspace.settings = {"features": {"dataops_enabled": True}}
    setup.db.commit()
    assert client.get("/catalog").status_code == 200


@pytest.mark.parametrize("owned", [False, True])
def test_narration_hidden_even_when_catalog_overridden(setup, monkeypatch, owned):
    monkeypatch.setattr(settings, "narration_enabled", False)
    workspace = _workspace(
        "showcase", settings={"catalog": {"enabled_skills": ["narration_run_v1"]}}
    )
    skill = _skill("narration_run_v1", workspace_id=workspace.id if owned else None)
    assert not skill_is_visible(skill, workspace, {skill.id})
    workspace.settings = {**workspace.settings, "features": {"narration_enabled": True}}
    assert skill_is_visible(skill, workspace, {skill.id})


def test_publication_rejects_callers_old_fence_before_using_current_lease(setup, monkeypatch):
    _, window, _, _, _ = candidate(setup)
    window.fence += 1
    setup.db.commit()
    monkeypatch.setattr(
        service_contracts.services,
        "publish_delivery",
        lambda *a, **k: pytest.fail("stale caller must be rejected before publication"),
    )
    response = client_for(service_contracts, setup).post(
        f"/windows/{window.id}/publish",
        json={"decision_id": "old-reviewed-decision", "fence": window.fence - 1},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "SERVICE_STALE_LEASE"


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("strftime(d, '%Y-%m')", "2026-10"),
        ("date_trunc('month', d)", datetime(2026, 10, 1)),
        ("strpos(s, 'world')", 7),
        ("regexp_matches(s, '^hello')", True),
    ],
)
def test_documented_functions_survive_parser_normalization(source, expected):
    sql = expression(source, ["s", "d"])
    with duckdb.connect() as conn:
        assert (
            conn.execute(
                f"SELECT {sql} FROM (SELECT 'hello world' AS s, DATE '2026-10-13' AS d)"
            ).fetchone()[0]
            == expected
        )


@pytest.mark.parametrize("delta", [False, True])
def test_native_schema_preserves_physical_types_instead_of_profile_json(setup, tmp_path, delta):
    from app.services.dataops.storage import write_batches

    schema = pa.schema(
        [
            pa.field("amount", pa.decimal128(18, 4)),
            pa.field("seen_at", pa.timestamp("us", tz="UTC")),
        ]
    )
    table = pa.Table.from_pylist(
        [{"amount": Decimal("123.4567"), "seen_at": datetime(2026, 10, 13)}], schema=schema
    )
    store = get_object_store()
    key = "test/native/delta" if delta else "test/native/data.parquet"
    if delta:
        write_batches(store._local_path(key), table.to_batches(), schema=schema, delta=True)
    else:
        path = store._local_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(table, path)
    dataset = SimpleNamespace(
        storage_key=key,
        lineage_json={},
        schema_json=[{"name": "amount", "kind": "float"}, {"name": "seen_at", "kind": "text"}],
    )
    assert native_schema(dataset) == schema


_TABLES = (
    "service_incidents",
    "delivery_receipts",
    "service_attempts",
    "service_windows",
    "service_contracts",
    "asset_qualifications",
    "asset_versions",
)


@pytest.mark.parametrize("populated", _TABLES)
def test_downgrade_refuses_any_persisted_fact_before_dropping_tables(populated):
    path = Path(__file__).parents[3] / "alembic" / "versions" / "126_service_contracts.py"
    spec = importlib.util.spec_from_file_location("review_migration_126", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        for table in _TABLES:
            connection.execute(text(f'CREATE TABLE "{table}" (id TEXT PRIMARY KEY)'))
        connection.execute(text(f"INSERT INTO \"{populated}\" (id) VALUES ('fact')"))
        migration.op = Operations(MigrationContext.configure(connection))
        with pytest.raises(RuntimeError, match="governed records exist"):
            migration.downgrade()
        assert set(inspect(connection).get_table_names()) == set(_TABLES)
        assert connection.execute(text(f'SELECT id FROM "{populated}"')).scalar() == "fact"
