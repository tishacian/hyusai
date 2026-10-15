"""The live runner cannot turn missing scenarios or raw errors into evidence."""

import json
import os

import pytest

from app.core.config import settings
from app.services.connectors.evidence_store import ProofReport
from app.tests.connectors.kit import live


@pytest.fixture
def configured(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "connector_network_policy_mode", "report")
    monkeypatch.setattr(settings, "hana_network_policy_mode", "report")
    monkeypatch.setattr(settings, "connector_runner_image_sha256", "")
    config = {
        "profile_key": "postgresql",
        "values": {"host": "bench.example.test", "database": "bench", "username": "reader"},
        "credentials": {"password": "never-output-this"},
        "source_revision": "a" * 40,
        "runner_image_sha256": "b" * 64,
        "environment": "test_account",
        "environment_id": "isolated-bench",
        "source": "real",
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config))
    os.chmod(path, 0o600)
    return path, config


def test_private_configuration_rejects_group_read_and_symlink(configured, tmp_path):
    path, _ = configured
    assert live.load_config(path)["profile_key"] == "postgresql"
    os.chmod(path, 0o640)
    with pytest.raises(ValueError, match="PRIVATE_CONFIG"):
        live.load_config(path)
    os.chmod(path, 0o600)
    link = tmp_path / "link"
    link.symlink_to(path)
    with pytest.raises(OSError):
        live.load_config(link)


def test_raw_driver_error_is_never_written_to_report(configured, tmp_path, monkeypatch):
    _, config = configured
    bench = live.Bench(config, tmp_path / "reports")

    def fail(suite):
        raise RuntimeError("never-output-this host and password")

    monkeypatch.setattr(bench, "case", fail)
    report = bench.run("connection")
    assert report.status == "failed" and report.code == "KIT_CASE_FAILED"
    assert "never-output-this" not in "".join(
        path.read_text() for path in (tmp_path / "reports").rglob("*.json")
    )
    report_file = next((tmp_path / "reports" / "reports").glob("*.json"))
    assert ProofReport.model_validate_json(report_file.read_text()) == report
    assert os.stat(report_file).st_mode & 0o777 == 0o600


def test_absent_fault_recipe_stays_skipped_and_identity_null(configured, tmp_path, monkeypatch):
    _, config = configured
    bench = live.Bench(config, tmp_path / "reports")
    monkeypatch.setattr(bench, "_connected", lambda: {"connected": True})
    report = bench.run("write_unknown_outcome")
    assert report.status == "skipped"
    assert report.code == "KIT_LOST_COMMIT_REPLY_REQUIRED"
    assert json.loads((tmp_path / "reports" / "metadata.json").read_text())["identity"] is None


def test_existing_reports_cannot_be_reused_as_current_proof(configured, tmp_path):
    _, config = configured
    directory = tmp_path / "existing" / "reports"
    directory.mkdir(parents=True)
    (directory / "old.json").write_text("{}")
    with pytest.raises(ValueError, match="FRESH_REPORT_DIRECTORY"):
        live.Bench(config, directory.parent)


def test_reports_have_unique_suite_files_after_lexical_insertion(configured, tmp_path, monkeypatch):
    _, config = configured
    bench = live.Bench(config, tmp_path / "reports")
    monkeypatch.setattr(bench, "case", lambda suite: {"row_count": 1})
    bench.run("read")
    bench.run("connection")
    reports = [
        ProofReport.model_validate_json(path.read_text())
        for path in (tmp_path / "reports" / "reports").glob("*.json")
    ]
    assert sorted(row.suite for row in reports) == ["connection", "read"]


def test_demo_or_fake_environment_never_loaded_as_live(configured):
    path, config = configured
    config["values"]["demo_mode"] = True
    path.write_text(json.dumps(config))
    with pytest.raises(ValueError, match="DEMO_FORBIDDEN"):
        live.load_config(path)


@pytest.mark.parametrize(
    "invalid",
    [
        {"cidr": "10.0.0.0/8"},
        {"cidr": "127.0.0.0/24"},
        {"cidr": "169.254.1.0/24"},
        {"ports": [True]},
        {"ports": [65536]},
        {"expires_at": "2030-01-01T00:00:00Z"},
        {"expires_at": "2020-01-01T00:00:00Z"},
        {"expires_at": "2026-01-01"},
        {"exception_id": "invented"},
        {"allow_all": True},
    ],
)
def test_operator_exception_export_remains_narrow_and_expiring(configured, invalid):
    from datetime import UTC, datetime, timedelta

    path, config = configured
    config["network_grants"] = [
        {
            "exception_id": "12345678-1234-1234-1234-123456789012",
            "cidr": "10.22.33.0/24",
            "ports": [5432],
            "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
            **invalid,
        }
    ]
    path.write_text(json.dumps(config))
    with pytest.raises(ValueError, match="KIT_NETWORK_GRANTS_INVALID"):
        live.load_config(path)


def test_operator_exception_applies_only_to_bench_call_and_is_recorded(
    configured, tmp_path, monkeypatch
):
    import socket
    from datetime import UTC, datetime, timedelta

    from app.services.connectors.network_policy import ConnectorNetworkError, resolve_destination

    path, config = configured
    config["network_grants"] = [
        {
            "exception_id": "12345678-1234-1234-1234-123456789012",
            "cidr": "10.22.33.0/24",
            "ports": [5432],
            "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
        }
    ]
    path.write_text(json.dumps(config))
    bench = live.Bench(live.load_config(path), tmp_path / "output")
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda host, port, **kw: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.22.33.7", port))
        ],
    )

    def execute(*args, **kwargs):
        assert resolve_destination("bench.example.test", 5432).address == "10.22.33.7"
        return {"ok": True}

    monkeypatch.setattr(live, "execute", execute)
    assert bench._call("catalog") == {"ok": True}
    with pytest.raises(ConnectorNetworkError):
        resolve_destination("bench.example.test", 5432)
    bench.save()
    metadata = json.loads((tmp_path / "output" / "metadata.json").read_text())
    assert metadata["network_exception_ids"] == [config["network_grants"][0]["exception_id"]]
    assert "10.22.33" not in json.dumps(metadata)
