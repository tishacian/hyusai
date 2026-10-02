"""Explorer ACLs, bounded reads, exact values and native snapshot provenance."""

from contextlib import contextmanager
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from psycopg2 import sql

from app.api.v1.endpoints import postgresql as api
from app.core.config import settings
from app.core.iam.roles import WORKSPACE_OWNER
from app.models.tabular import TabularDataset
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services import tabular_datasets
from app.services.connectors.generic import postgresql_browser as browser

SECRET = "postgres-test-secret-never-returned"
CONFIG = {
    "configured": True,
    "values": {
        "host": "database.example.test",
        "port": "5432",
        "database": "demo",
        "username": "reader",
    },
    "secrets": {"password": SECRET},
}


def column(name="id", pg_type="int8", **extra):
    return {
        "relation_oid": 123,
        "name": name,
        "dtype": pg_type,
        "pg_type": pg_type,
        "type_schema": "pg_catalog",
        "nullable": True,
        "primary_key": name == "id",
        **extra,
    }


class Cursor:
    def __init__(self, connection, named=False):
        self.connection, self.named, self.rows, self.offset = connection, named, [], 0

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def execute(self, query, params=None):
        self.connection.calls.append((query, params))
        if self.named:
            self.rows = [(True, *row) for row in self.connection.rows[: params[0]]]
        elif isinstance(query, str) and "format_type" in query:
            self.rows = self.connection.columns
        elif isinstance(query, str) and "AS kind" in query:
            self.rows = self.connection.tables

    def fetchall(self):
        return self.rows

    def fetchmany(self, size):
        result = self.rows[self.offset : self.offset + size]
        self.offset += size
        return result


class Connection:
    def __init__(self):
        self.calls, self.session = [], None
        self.rows = [(1,), (2,)]
        self.columns = [column()]
        self.tables = [{"schema": "showcase_ecommerce", "name": "claims", "kind": "table"}]
        self.rolled_back = self.closed = False

    def cursor(self, name=None, **_):
        return Cursor(self, named=bool(name))

    def set_session(self, **kwargs):
        self.session = kwargs

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


@pytest.fixture()
def setup(db_session, monkeypatch, tmp_path):
    workspace = Workspace(
        id=str(uuid4()), name="Explorer QA", slug=f"pg-{uuid4().hex[:8]}", settings={}
    )
    owner = User(
        id=str(uuid4()),
        username=f"pg-{uuid4().hex[:8]}",
        email=f"pg-{uuid4().hex[:8]}@example.test",
        role="user",
    )
    member = User(
        id=str(uuid4()),
        username=f"pg-{uuid4().hex[:8]}",
        email=f"pg-{uuid4().hex[:8]}@example.test",
        role="user",
    )
    db_session.add_all([workspace, owner, member])
    db_session.add_all(
        [
            WorkspaceMember(
                workspace_id=workspace.id,
                user_id=owner.id,
                role="owner",
                role_template=WORKSPACE_OWNER,
            ),
            WorkspaceMember(workspace_id=workspace.id, user_id=member.id, role="member"),
        ]
    )
    db_session.commit()
    connection = Connection()

    @contextmanager
    def connect(_workspace):
        yield connection, CONFIG

    monkeypatch.setattr(browser, "_connection", connect)
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "store"))
    monkeypatch.setattr(settings, "tabular_data_enabled", True)

    def client(user=owner):
        app = FastAPI()
        app.include_router(api.router, prefix="/postgresql")
        app.dependency_overrides[api.get_current_workspace] = lambda: workspace
        app.dependency_overrides[api.get_current_user] = lambda: user
        app.dependency_overrides[api.get_db] = lambda: db_session
        return TestClient(app)

    return client, connection, workspace, member


def selection(client):
    result = client.get(
        "/postgresql/table", params={"schema": "showcase_ecommerce", "table": "claims"}
    )
    assert result.status_code == 200
    return {
        "schema": "showcase_ecommerce",
        "table": "claims",
        "columns": ["id"],
        "fingerprint": result.json()["fingerprint"],
    }


def test_member_cannot_use_saved_database_credentials(setup):
    client, connection, _, member = setup
    body = selection(client())
    connection.calls.clear()
    c = client(member)
    responses = [
        c.get("/postgresql/catalog"),
        c.get("/postgresql/table", params={"schema": "x", "table": "y"}),
        c.post("/postgresql/preview", json=body),
        c.post("/postgresql/import", json={**body, "name": "Claims", "request_id": str(uuid4())}),
    ]
    assert [r.status_code for r in responses] == [403] * 4
    assert not connection.calls, "permission is checked before touching PostgreSQL"


def test_preview_is_live_bounded_and_never_echoes_credentials(setup):
    client, connection, _, _ = setup
    c = client()
    body = selection(c)
    connection.rows = [(i,) for i in range(40)]
    result = c.post("/postgresql/preview", json={**body, "limit": 25})
    assert result.status_code == 200
    payload = result.json()
    assert payload["row_count"] == 25 and payload["has_more"] is True
    assert payload["ordered_by"] == ["id"] and payload["captured_at"]
    assert "native_rows" not in payload and SECRET not in result.text
    assert c.post("/postgresql/preview", json={**body, "limit": 101}).status_code == 422
    assert (
        c.post("/postgresql/preview", json={**body, "sql": "DROP TABLE claims"}).status_code == 422
    )


def test_projection_must_match_discovered_columns_and_schema(setup):
    client, connection, _, _ = setup
    c = client()
    body = selection(c)
    for columns in [["id; DROP TABLE claims"], ["id", "id"]]:
        assert c.post("/postgresql/preview", json={**body, "columns": columns}).status_code == 422
    connection.columns.append(column("amount", "numeric"))
    changed = c.post("/postgresql/preview", json=body)
    assert changed.status_code == 409 and changed.json()["detail"]["code"] == "PG_SOURCE_CHANGED"


def test_odd_identifiers_are_quoted_identifiers_not_sql(setup):
    client, connection, _, _ = setup
    name = 'amount"; DROP TABLE claims; --'
    connection.columns = [column(name, "text")]
    connection.rows = [("safe",)]
    c = client()
    body = selection(c)
    result = c.post("/postgresql/preview", json={**body, "columns": [name]})
    assert result.status_code == 200
    query = next(
        query
        for query, _ in connection.calls
        if isinstance(query, sql.Composed) and "agentium_source" in str(query)
    )

    def parts(value):
        if isinstance(value, sql.Composed):
            return [part for child in value.seq for part in parts(child)]
        return [value]

    assert sql.Identifier(name) in parts(query)
    assert all(name not in part.string for part in parts(query) if isinstance(part, sql.SQL))


def test_import_rereads_all_rows_and_registers_versioned_native_parquet(setup, db_session):
    client, connection, workspace, _ = setup
    c = client()
    body = selection(c)
    assert c.post("/postgresql/preview", json={**body, "limit": 1}).json()["row_count"] == 1
    connection.rows = [(1,), (2,), (3,)]
    request = {**body, "name": "Claims", "request_id": str(uuid4())}
    first = c.post("/postgresql/import", json=request)
    assert first.status_code == 200, first.text
    payload = first.json()["dataset"]
    assert payload["source"] == "postgresql" and payload["status"] == "ready"
    assert payload["row_count"] == 3 and payload["version"] == 1
    pg = payload["lineage"]["postgresql"]
    assert pg["mode"] == "snapshot" and pg["truncated"] is False
    assert pg["columns"] == ["id"] and len(pg["snapshot_sha256"]) == 64
    assert "request_id" not in payload["lineage"] and SECRET not in first.text
    row = tabular_datasets.get_dataset(
        db_session, workspace_id=workspace.id, dataset_id=payload["id"]
    )
    frame = tabular_datasets.read_frame(row)
    assert frame["id"].to_list() == [1, 2, 3]
    calls = len(connection.calls)
    replay = c.post("/postgresql/import", json=request).json()
    assert replay["replayed"] is True and replay["dataset"]["id"] == payload["id"]
    assert len(connection.calls) == calls, "a replay does not read the changing source"
    assert c.post("/postgresql/import", json={**request, "name": "Changed"}).status_code == 409
    second = c.post("/postgresql/import", json={**request, "request_id": str(uuid4())}).json()[
        "dataset"
    ]
    assert second["version"] == 2


def test_import_overflow_creates_no_partial_dataset(setup, db_session, monkeypatch):
    client, connection, _, _ = setup
    c = client()
    body = selection(c)
    connection.rows = [(i,) for i in range(4)]
    monkeypatch.setattr(browser, "MAX_IMPORT_ROWS", 3)
    response = c.post(
        "/postgresql/import", json={**body, "name": "Claims", "request_id": str(uuid4())}
    )
    assert (
        response.status_code == 413 and response.json()["detail"]["code"] == "PG_IMPORT_ROW_LIMIT"
    )
    assert db_session.query(TabularDataset).count() == 0


def test_a_native_version_conflict_rolls_back_and_retries_without_duplicates(
    setup, db_session, monkeypatch
):
    client, _, _, _ = setup
    c = client()
    body = selection(c)
    c.post("/postgresql/import", json={**body, "name": "Claims", "request_id": str(uuid4())})
    request = {**body, "name": "Claims", "request_id": str(uuid4())}
    allocate = tabular_datasets.next_version
    monkeypatch.setattr(tabular_datasets, "next_version", lambda *args, **kwargs: 1)
    conflict = c.post("/postgresql/import", json=request)
    assert (
        conflict.status_code == 409 and conflict.json()["detail"]["code"] == "PG_REQUEST_CONFLICT"
    )
    assert db_session.query(TabularDataset).count() == 1
    monkeypatch.setattr(tabular_datasets, "next_version", allocate)
    retry = c.post("/postgresql/import", json=request).json()["dataset"]
    assert retry["version"] == 2 and db_session.query(TabularDataset).count() == 2


def test_a_retired_snapshot_is_not_reported_as_ready_on_retry(setup, db_session):
    client, _, _, _ = setup
    c = client()
    body = {**selection(c), "name": "Claims", "request_id": str(uuid4())}
    created = c.post("/postgresql/import", json=body).json()["dataset"]
    dataset = db_session.get(TabularDataset, created["id"])
    dataset.status = "deleted"
    db_session.commit()
    assert c.post("/postgresql/import", json=body).status_code == 409
    assert db_session.query(TabularDataset).count() == 1


def test_payload_bound_and_feature_flag_fail_before_persisting(setup, db_session, monkeypatch):
    client, connection, _, _ = setup
    c = client()
    body = selection(c)
    monkeypatch.setattr(browser, "MAX_IMPORT_BYTES", 1)
    assert (
        c.post(
            "/postgresql/import", json={**body, "name": "Claims", "request_id": str(uuid4())}
        ).status_code
        == 413
    )
    assert db_session.query(TabularDataset).count() == 0
    monkeypatch.setattr(settings, "tabular_data_enabled", False)
    connection.calls.clear()
    assert (
        c.post(
            "/postgresql/import", json={**body, "name": "Claims", "request_id": str(uuid4())}
        ).status_code
        == 409
    )
    assert not connection.calls


def test_exact_decimal_json_and_utc_timestamps_survive_native_snapshot(setup, db_session):
    client, connection, workspace, _ = setup
    connection.columns = [
        column("amount", "numeric"),
        column("facts", "jsonb"),
        column("at", "timestamptz"),
    ]
    exact = "12345678901234567890.12345678901234567890"
    json_exact = '{"amount": 12345678901234567890.12345678901234567890}'
    instant = datetime(2026, 10, 2, 10, 0, tzinfo=timezone.utc)
    connection.rows = [(exact, json_exact, instant)]
    c = client()
    body = selection(c)
    result = c.post(
        "/postgresql/import",
        json={
            **body,
            "columns": ["amount", "facts", "at"],
            "name": "Exact",
            "request_id": str(uuid4()),
        },
    )
    assert result.status_code == 200, result.text
    dataset = result.json()["dataset"]
    assert dataset["lineage"]["postgresql"]["text_columns"] == ["amount", "facts"]
    row = tabular_datasets.get_dataset(
        db_session, workspace_id=workspace.id, dataset_id=dataset["id"]
    )
    frame = tabular_datasets.read_frame(row)
    assert (
        frame["amount"][0] == exact
        and frame["facts"][0] == json_exact
        and frame["at"][0] == instant
    )


def test_same_request_in_a_different_workspace_creates_a_different_dataset(setup, db_session):
    client, connection, workspace, _ = setup
    c = client()
    body = selection(c)
    request = {**body, "name": "Claims", "request_id": str(uuid4())}
    first = c.post("/postgresql/import", json=request).json()["dataset"]
    other = Workspace(id=str(uuid4()), name="Other", slug=f"other-{uuid4().hex[:8]}", settings={})
    db_session.add(other)
    db_session.flush()
    dataset = db_session.get(TabularDataset, first["id"])
    dataset.workspace_id = other.id
    db_session.commit()
    second = c.post("/postgresql/import", json=request).json()["dataset"]
    assert first["id"] != second["id"] and second["version"] == 1


def test_connections_are_read_only_closed_and_errors_are_sanitized(monkeypatch):
    connection = Connection()
    monkeypatch.setattr(browser, "get_config", lambda *a, **kw: CONFIG)
    monkeypatch.setattr("psycopg2.connect", lambda **kwargs: connection)
    browser.catalog(object())
    assert connection.session == {
        "isolation_level": "READ COMMITTED",
        "readonly": True,
        "autocommit": False,
    }
    assert connection.rolled_back and connection.closed
    assert any(
        "statement_timeout" in query for query, _ in connection.calls if isinstance(query, str)
    )

    def fail(**kwargs):
        raise RuntimeError(SECRET)

    monkeypatch.setattr("psycopg2.connect", fail)
    with pytest.raises(browser.PostgresBrowseError) as error:
        browser.catalog(object())
    assert error.value.code == "PG_UNAVAILABLE" and SECRET not in str(error.value)


def test_incomplete_credentials_do_not_fall_back_to_backend_environment(monkeypatch):
    monkeypatch.setattr(
        browser,
        "get_config",
        lambda *a, **kw: {
            "configured": True,
            "values": {"host": "remote.example.test", "database": "demo"},
            "secrets": {},
        },
    )
    calls = []
    monkeypatch.setattr("psycopg2.connect", lambda **kwargs: calls.append(kwargs))
    with pytest.raises(browser.PostgresBrowseError) as error:
        browser.catalog(object())
    assert error.value.code == "PG_NOT_CONFIGURED" and not calls


def test_int64_preview_stays_exact_and_empty_snapshots_keep_the_schema(setup, db_session):
    client, connection, workspace, _ = setup
    c = client()
    body = selection(c)
    connection.rows = [(9223372036854775807,)]
    preview = c.post("/postgresql/preview", json=body).json()
    assert preview["rows"][0]["id"] == "9223372036854775807"
    exact = c.post(
        "/postgresql/import", json={**body, "name": "Exact ids", "request_id": str(uuid4())}
    ).json()["dataset"]
    assert exact["preview"][0]["id"] == "9223372036854775807"
    dataset = db_session.get(TabularDataset, exact["id"])
    assert tabular_datasets.read_page(dataset)["rows"][0]["id"] == "9223372036854775807"
    assert tabular_datasets.read_frame(dataset)["id"][0] == 9223372036854775807
    connection.rows = []
    dataset = c.post(
        "/postgresql/import", json={**body, "name": "Empty", "request_id": str(uuid4())}
    ).json()["dataset"]
    assert dataset["row_count"] == 0 and dataset["schema"][0]["kind"] == "integer"
