"""NoSQL query shapes and egress are constrained before any driver runs."""

import socket
import sys
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.services.connectors.adapters import nosql
from app.services.connectors.adapters.driver_egress import pinned_python_driver
from app.services.connectors.adapters.sql import AdapterError
from app.services.connectors.network_policy import ConnectorNetworkError


def deadline():
    return (datetime.now(UTC) + timedelta(minutes=1)).isoformat()


def assert_observed(monkeypatch, profile, output, version):
    from app.services.connectors import runtime_identity

    monkeypatch.setattr(runtime_identity.settings, "connector_runner_image_sha256", "a" * 64)
    monkeypatch.setattr(runtime_identity.metadata, "version", lambda _: "1.2.3")
    monkeypatch.setattr(
        runtime_identity, "kit_identity", lambda: {"version": "fixture-v1", "sha256": "b" * 64}
    )
    identity = runtime_identity.observe(profile, output)
    assert identity is not None and identity["server_version"] == version


@pytest.mark.parametrize("forbidden", [False, True])
def test_mongodb_observes_build_version_not_config(monkeypatch, tmp_path, forbidden):
    commands = []

    class Client:
        def __init__(self, **kwargs):
            assert kwargs["tls"] is True and kwargs["tlsAllowInvalidCertificates"] is False
            self.admin = self

        def command(self, name):
            commands.append(name)
            if name == "buildInfo" and forbidden:
                exc = RuntimeError("remote text must not leave adapter")
                exc.code = 13
                raise exc
            return {"ok": 1, "version": "8.0.12"} if name == "buildInfo" else {"ok": 1}

        def __getitem__(self, name):
            return self

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setitem(sys.modules, "pymongo", SimpleNamespace(MongoClient=Client))
    monkeypatch.setattr(nosql, "pinned_python_driver", lambda *a: nullcontext())
    output = nosql.execute(
        "test",
        {"host": "db.example", "database": "fixture", "server_version": "999-config"},
        {},
        {},
        deadline(),
        tmp_path,
        dialect="mongodb",
    )
    assert commands == ["ping", "buildInfo"]
    if forbidden:
        assert output["connected"] and output["server_version"] is None
        assert output["identity_error_code"] == "CONNECTOR_SERVER_VERSION_FORBIDDEN"
        assert "remote text" not in str(output)
    else:
        assert_observed(monkeypatch, "mongodb", output, "8.0.12")


@pytest.mark.parametrize("engine", ["elasticsearch", "opensearch"])
def test_search_observes_version_number_from_guarded_root(monkeypatch, tmp_path, engine):
    calls = []

    def request(method, url, **kwargs):
        calls.append((method, url))
        return {}, {"version": {"number": "8.17.3"}}

    monkeypatch.setattr(nosql.http, "json_request", request)
    output = nosql.execute(
        "test", {"endpoint": "https://search.example"}, {}, {}, deadline(), tmp_path, dialect=engine
    )
    assert calls == [("GET", "https://search.example/")]
    assert_observed(monkeypatch, engine, output, "8.17.3")


@pytest.mark.parametrize("forbidden", [False, True])
def test_cassandra_observes_release_version_query(monkeypatch, tmp_path, forbidden):
    calls = []

    class UnauthorizedError(Exception):
        pass

    def execute(statement, *, timeout):
        calls.append(statement)
        assert 0 < timeout <= 30
        if forbidden:
            raise UnauthorizedError("remote text must not leave adapter")
        return SimpleNamespace(one=lambda: {"release_version": "5.0.4"})

    session = SimpleNamespace(execute=execute)
    cluster = SimpleNamespace(connect=lambda: session, shutdown=lambda: calls.append("closed"))
    for name, value in {
        "cassandra": SimpleNamespace(Unauthorized=UnauthorizedError),
        "cassandra.auth": SimpleNamespace(PlainTextAuthProvider=lambda **kw: object()),
        "cassandra.cluster": SimpleNamespace(Cluster=lambda **kw: cluster),
        "cassandra.io.asyncioreactor": SimpleNamespace(AsyncioConnection=object),
        "cassandra.policies": SimpleNamespace(WhiteListRoundRobinPolicy=lambda ips: ips),
        "cassandra.query": SimpleNamespace(SimpleStatement=object, dict_factory=object()),
    }.items():
        monkeypatch.setitem(sys.modules, name, value)
    monkeypatch.setattr(
        nosql,
        "pinned_python_driver",
        lambda *a: nullcontext([SimpleNamespace(address="127.0.0.2")]),
    )
    output = nosql.execute(
        "test",
        {"host": "db.example", "keyspace": "fixture", "username": "reader"},
        {"password": "fixture-only"},
        {},
        deadline(),
        tmp_path,
        dialect="cassandra",
    )
    assert calls == ["SELECT release_version FROM system.local", "closed"]
    if forbidden:
        assert output["connected"] and output["server_version"] is None
        assert output["identity_error_code"] == "CONNECTOR_SERVER_VERSION_FORBIDDEN"
        assert "remote text" not in str(output)
    else:
        assert_observed(monkeypatch, "cassandra", output, "5.0.4")


@pytest.mark.parametrize("version", [None, {}, {"number": None}, {"number": ""}, {"number": 8}])
def test_unobservable_version_is_not_filled_from_configuration(monkeypatch, tmp_path, version):
    from app.services.connectors import runtime_identity

    monkeypatch.setattr(
        nosql.http, "json_request", lambda *a, **kw: ({}, {"name": "fixture", "version": version})
    )
    output = nosql.execute(
        "test",
        {"endpoint": "https://search.example", "server_version": "8.17.3"},
        {},
        {},
        deadline(),
        tmp_path,
        dialect="elasticsearch",
    )
    assert output["connected"] is True and output["server_version"] is None
    monkeypatch.setattr(runtime_identity.settings, "connector_runner_image_sha256", "a" * 64)
    assert runtime_identity.observe("elasticsearch", output) is None


@pytest.mark.parametrize(
    "query",
    [
        {"$where": "sleep(5)"},
        {"x": {"$function": {"body": "code"}}},
        {"$expr": {"$accumulator": "code"}},
        {"$text": {"$search": "unbounded"}},
    ],
)
def test_mongo_executable_operators_are_refused_recursively(query):
    with pytest.raises(AdapterError, match="CONNECTOR_FILTER_FORBIDDEN"):
        nosql.validate_filter(query, kind="mongo")


@pytest.mark.parametrize(
    "query",
    [
        {"script": {"source": "x"}},
        {"bool": {"filter": [{"script_fields": {}}]}},
        {"wrapper": {"query": "encoded DSL"}},
    ],
)
def test_search_scripts_and_encoded_dsl_are_refused(query):
    with pytest.raises(AdapterError, match="CONNECTOR_FILTER_FORBIDDEN"):
        nosql.validate_filter(query, kind="search")


def test_filters_accept_comparisons_but_limit_nesting():
    assert nosql.validate_filter({"$and": [{"id": {"$gte": 1}}, {"active": True}]}, kind="mongo")
    tree = {}
    for _ in range(25):
        tree = {"x": tree}
    with pytest.raises(AdapterError, match="CONNECTOR_FILTER_INVALID"):
        nosql.validate_filter(tree, kind="mongo")


def test_driver_preserves_hostname_for_tls_and_denies_discovered_hosts(monkeypatch):
    from app.services.connectors.adapters import driver_egress
    from app.services.connectors.network_policy import Destination

    monkeypatch.setattr(
        driver_egress, "resolve_destination", lambda h, p: Destination(h, "93.184.216.34", p)
    )
    calls = []

    def dns(host, port, *a, **kw):
        calls.append((host, port))
        return []

    monkeypatch.setattr(socket, "getaddrinfo", dns)
    with pinned_python_driver([("db.test", 27017)]):
        socket.getaddrinfo("db.test", 27017)
        assert calls == [("93.184.216.34", 27017)]
        with pytest.raises(ConnectorNetworkError, match="CONNECTOR_DISCOVERED_HOST_DENIED"):
            socket.getaddrinfo("metadata.test", 27017)
        with socket.socket() as sock:
            with pytest.raises(ConnectorNetworkError):
                sock.connect(("169.254.169.254", 80))
    assert socket.getaddrinfo is dns


def test_variable_documents_preserve_nulls_and_unicode(tmp_path):
    output = nosql._stage(
        iter([{"a": None}, {"b": "é漢字"}]),
        "import",
        {},
        tmp_path,
        (datetime.now(UTC) + timedelta(minutes=1)).isoformat(),
    )
    assert output["row_count"] == 2 and output["columns"] == ["document"]
    assert "é漢字" in (tmp_path / "rows.jsonl").read_text()


def test_nosql_scope_applies_to_direct_collection_names():
    with pytest.raises(AdapterError, match="CONNECTOR_SOURCE_FORBIDDEN"):
        nosql._scope({"database": "approved"}, {"table": "secret"}, {"allowed_tables": ["visible"]})


def test_search_terms_lookup_cannot_escape_authorized_index():
    with pytest.raises(AdapterError, match="CONNECTOR_FILTER_FORBIDDEN"):
        nosql.validate_search_query(
            {"terms": {"id": {"index": "other-private-index", "id": "secret", "path": "ids"}}}
        )
    assert nosql.validate_search_query(
        {"bool": {"filter": [{"terms": {"id": [1, 2]}}, {"range": {"ts": {"gte": 12}}}]}}
    )


def test_document_json_keeps_missing_distinct_from_null_and_flattens_explicitly(tmp_path):
    import json

    output = nosql._stage(
        iter([{"id": 1, "nested": {"value": None}}, {"id": 2, "nested": {"value": "é"}}]),
        "preview",
        {},
        tmp_path,
        (datetime.now(UTC) + timedelta(minutes=1)).isoformat(),
        flatten_paths=["nested.value"],
    )
    assert output["columns"] == ["document", "nested.value"]
    assert json.loads(output["rows"][0][0])["nested"] == {"value": None}
    assert output["rows"][1][1] == "é"
