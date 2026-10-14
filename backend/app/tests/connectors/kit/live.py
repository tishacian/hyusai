"""Opt-in supplier bench. This emits reports, never an accepted evidence bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from app.core.config import settings
from app.services.connectors.adapters import execute
from app.services.connectors.adapters.sql import AdapterError, _json_value
from app.services.connectors.artifacts import parquet_artifact
from app.services.connectors.certification import required_suites
from app.services.connectors.evidence_store import ProofReport
from app.services.connectors.kit_identity import kit_identity
from app.services.connectors.network_exceptions import NetworkGrant, checked_network, network_grants
from app.services.connectors.profiles import get_profile
from app.services.connectors.runtime_identity import observe


class PendingError(RuntimeError):
    pass


def _digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def load_config(path):
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(descriptor) as handle:
        mode = os.fstat(handle.fileno())
        if (
            not stat.S_ISREG(mode.st_mode)
            or stat.S_IMODE(mode.st_mode) != 0o600
            or mode.st_uid != os.getuid()
            or mode.st_size > 65536
        ):
            raise ValueError("KIT_PRIVATE_CONFIG_REQUIRED")
        config = json.load(handle)
    if not isinstance(config, dict) or set(config) - {
        "profile_key",
        "values",
        "credentials",
        "source_revision",
        "runner_image_sha256",
        "environment",
        "environment_id",
        "source",
        "read",
        "writes",
        "allow_writes",
        "timeout_s",
        "scratch_dir",
        "network_grants",
    }:
        raise ValueError("KIT_CONFIG_INVALID")
    if not re.fullmatch(
        r"[a-f0-9]{40}", str(config.get("source_revision", ""))
    ) or not re.fullmatch(r"[a-f0-9]{64}", str(config.get("runner_image_sha256", ""))):
        raise ValueError("KIT_IDENTITY_REQUIRED")
    if (
        config.get("environment") not in {"test_account", "container"}
        or config.get("source") != "real"
    ):
        raise ValueError("KIT_TEST_ENVIRONMENT_REQUIRED")
    if not re.fullmatch(r"[\w.+:/@-]{1,160}", str(config.get("environment_id", ""))):
        raise ValueError("KIT_ENVIRONMENT_ID_REQUIRED")
    if config.get("values", {}).get("demo_mode"):
        raise ValueError("KIT_DEMO_FORBIDDEN")
    if type(config.get("timeout_s", 30)) is not int or not 1 <= config.get("timeout_s", 30) <= 300:
        raise ValueError("KIT_TIMEOUT_INVALID")
    if "allow_writes" in config and type(config["allow_writes"]) is not bool:
        raise ValueError("KIT_WRITE_ARM_INVALID")
    _network_grants(config)
    return config


def _network_grants(config):
    """A private operator file may carry a bounded export of approved exceptions.

    This is not a user/API grant: its administrator provenance must be checked
    by the bench operator. Expiry and address/port limits are always enforced.
    """
    entries = config.get("network_grants", [])
    if not isinstance(entries, list) or len(entries) > 32:
        raise ValueError("KIT_NETWORK_GRANTS_INVALID")
    now = datetime.now(UTC)
    grants = []
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {
            "exception_id",
            "cidr",
            "ports",
            "expires_at",
        }:
            raise ValueError("KIT_NETWORK_GRANTS_INVALID")
        if not re.fullmatch(
            r"[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}", str(entry["exception_id"])
        ):
            raise ValueError("KIT_NETWORK_GRANTS_INVALID")
        ports = entry["ports"]
        if (
            not isinstance(ports, list)
            or not 1 <= len(ports) <= 32
            or any(type(p) is not int or not 1 <= p <= 65535 for p in ports)
        ):
            raise ValueError("KIT_NETWORK_GRANTS_INVALID")
        try:
            expiry = datetime.fromisoformat(entry["expires_at"])
            network = checked_network(entry["cidr"])
        except Exception:
            raise ValueError("KIT_NETWORK_GRANTS_INVALID") from None
        if expiry.tzinfo is None or not now < expiry <= now + timedelta(days=90):
            raise ValueError("KIT_NETWORK_GRANTS_INVALID")
        grants.append(NetworkGrant(str(network), tuple(ports), expiry))
    return tuple(grants)


def _golden(path):
    import pyarrow.parquet as pq

    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 16 * 1024**2:
        raise PendingError("KIT_BOUNDED_GOLDEN_REQUIRED")
    with pq.ParquetFile(path) as parquet:
        if parquet.metadata.num_rows > 5000:
            raise PendingError("KIT_BOUNDED_GOLDEN_REQUIRED")
        table = parquet.read()
    return table


def _rows(table):
    # Column identity, nulls, decimal/date/binary representations and row
    # multiplicity all participate. Source ordering is deliberately irrelevant.
    values = [{key: _json_value(value) for key, value in row.items()} for row in table.to_pylist()]
    return sorted(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
        for value in values
    )


class Bench:
    def __init__(self, config, reports):
        self.config, self.directory = config, Path(reports)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.report_directory = self.directory / "reports"
        if self.report_directory.exists() and any(self.report_directory.iterdir()):
            raise ValueError("KIT_FRESH_REPORT_DIRECTORY_REQUIRED")
        self.report_directory.mkdir(mode=0o700, exist_ok=True)
        self.profile = get_profile(config["profile_key"])
        self.values = self.profile.validate_values(
            config.get("values", {}),
            {key: "private-reference" for key in config.get("credentials", {})},
        )
        self.identity, self.connection_result = None, None
        self.reports = {}
        self.write_results = {}
        settings.connector_network_policy_mode = "enforce"
        settings.hana_network_policy_mode = "enforce"
        settings.connector_runner_image_sha256 = config["runner_image_sha256"]

    def _call(self, operation, parameters=None, execution=None):
        parameters = dict(parameters or {})
        if operation == "import":
            parameters["max_rows"] = min(parameters.get("max_rows", 5000), 5000)
            parameters["max_bytes"] = min(parameters.get("max_bytes", 32 * 1024**2), 32 * 1024**2)
        timeout = self.config.get("timeout_s", 30)
        deadline = (datetime.now(UTC) + timedelta(seconds=timeout)).isoformat()
        with (
            network_grants(_network_grants(self.config)),
            tempfile.TemporaryDirectory(
                prefix="agentium-kit-", dir=self.config.get("scratch_dir")
            ) as scratch,
        ):
            result = execute(
                operation,
                self.values,
                self.config.get("credentials", {}),
                parameters or {},
                deadline,
                Path(scratch),
                family=self.profile.family,
                dialect=self.profile.dialect,
                access={"mode": "read_write" if self.config.get("allow_writes") else "read"},
                limits=self.profile.limits.model_dump(),
                execution=execution,
            )
            if operation == "import":
                import pyarrow.parquet as pq

                result = parquet_artifact(result, Path(scratch), deadline)
                return result, pq.read_table(Path(scratch) / result["artifact"])
            return result

    def _connected(self):
        if self.connection_result is None:
            result = self._call("test")
            if result.get("connected") is not True or result.get("source") != "real":
                raise AdapterError("KIT_REAL_CONNECTION_REQUIRED")
            self.connection_result = result
            self.identity = observe(self.profile.key, result)
        return self.connection_result

    def _read(self, **extra):
        data = self.config.get("read") or {}
        if not data.get("golden_parquet") or not isinstance(data.get("parameters"), dict):
            raise PendingError("KIT_GOLDEN_READ_REQUIRED")
        golden = _golden(data["golden_parquet"])
        parameters = {**data["parameters"], "max_rows": 5000, "max_bytes": 32 * 1024**2, **extra}
        result, table = self._call("import", parameters)
        if _rows(table) != _rows(golden):
            raise AdapterError("KIT_GOLDEN_MISMATCH")
        return result, table

    def _write(self, operation):
        if not self.config.get("allow_writes"):
            raise PendingError("KIT_WRITES_NOT_ARMED")
        config = (self.config.get("writes") or {}).get(operation)
        if not isinstance(config, dict) or not all(
            config.get(key)
            for key in ("parameters", "input_parquet", "before_parquet", "after_parquet")
        ):
            raise PendingError("KIT_ISOLATED_WRITE_FIXTURE_REQUIRED")
        if operation == "export_files":
            raise PendingError("KIT_OBJECT_EXPORT_READER_REQUIRED")
        parameters = dict(config["parameters"])
        read_source = (self.config.get("read") or {}).get("parameters") or {}
        if all(parameters.get(key) == read_source.get(key) for key in ("schema", "table")):
            raise PendingError("KIT_SEPARATE_WRITE_TARGET_REQUIRED")
        before, after, source = (
            _golden(config[key]) for key in ("before_parquet", "after_parquet", "input_parquet")
        )
        _, current = self._call("import", {key: parameters[key] for key in ("schema", "table")})
        if _rows(current) != _rows(before):
            raise AdapterError("KIT_WRITE_FIXTURE_DIRTY")
        path = Path(config["input_parquet"]).resolve()
        inputs = [hashlib.sha256(path.read_bytes()).hexdigest()]
        execution = {
            "operation_id": str(uuid4()),
            "contract_digest": _digest(
                {"operation": operation, "parameters": parameters, "inputs": inputs}
            ),
            "input_files": [str(path)],
            "input_sha256": _digest(inputs),
            "write_operation": operation,
        }
        result = self._call(operation, parameters, execution)
        if result.get("applied") is not True or any(
            result.get(key) != execution[key] for key in ("operation_id", "contract_digest")
        ):
            raise AdapterError("KIT_WRITE_RECEIPT_INVALID")
        _, current = self._call("import", {key: parameters[key] for key in ("schema", "table")})
        if _rows(current) != _rows(after):
            raise AdapterError("KIT_WRITE_GOLDEN_MISMATCH")
        self.write_results[operation] = (parameters, execution, result)
        return {"row_count": source.num_rows, "result_digest": _digest(_rows(current))}

    def case(self, suite):
        self._connected()
        if suite == "connection":
            if self.identity is None:
                raise PendingError("KIT_RUNTIME_IDENTITY_INCOMPLETE")
            return {"result_digest": _digest(self.identity)}
        if suite == "contract":
            # Checks the actual loaded immutable profile and the live adapter
            # response. This does not claim all type/driver cases are covered.
            if not self.profile.digest or not self.connection_result:
                raise AdapterError("KIT_CONTRACT_INVALID")
            return {"result_digest": self.profile.digest}
        if suite == "introspection":
            result = self._call("catalog")
            if not isinstance(result, dict) or not result:
                raise AdapterError("KIT_CATALOG_INVALID")
            if self.profile.family in {"dbapi", "adbc", "sqlalchemy"}:
                parameters = (self.config.get("read") or {}).get("parameters") or {}
                table = self._call("table", parameters)
                if not table.get("columns"):
                    raise AdapterError("KIT_SCHEMA_INVALID")
            return {"result_digest": _digest(result)}
        if suite == "read":
            result, table = self._read()
            return {"row_count": table.num_rows, "result_digest": _digest(_rows(table))}
        if suite == "read_partitioned":
            source = self.config.get("read") or {}
            column = source.get("partition_column")
            if not column:
                raise PendingError("KIT_PARTITION_FIXTURE_REQUIRED")
            golden = _golden(source["golden_parquet"])
            if column not in golden.column_names or not golden.column(column).null_count:
                raise PendingError("KIT_NULL_PARTITION_FIXTURE_REQUIRED")
            result, table = self._read(partitions={"column": column, "count": 3})
            if result.get(
                "read_consistency"
            ) != self.profile.capabilities.consistency or not result.get("partition_bounds"):
                raise AdapterError("KIT_PARTITION_EVIDENCE_INVALID")
            return {"row_count": table.num_rows, "result_digest": _digest(_rows(table))}
        if suite == "read_incremental":
            source = self.config.get("read") or {}
            incremental = source.get("incremental")
            if not incremental:
                raise PendingError("KIT_INCREMENTAL_FIXTURE_REQUIRED")
            golden = _golden(source["golden_parquet"])
            ordered = sorted(
                golden.to_pylist(),
                key=lambda row: (
                    row[incremental["watermark_column"]],
                    row[incremental["key_column"]],
                ),
            )
            if (
                len(ordered) < 3
                or ordered[0][incremental["watermark_column"]]
                != ordered[1][incremental["watermark_column"]]
            ):
                raise PendingError("KIT_SHARED_WATERMARK_FIXTURE_REQUIRED")
            after = [
                ordered[0][key]
                for key in (incremental["watermark_column"], incremental["key_column"])
            ]
            after = [value.isoformat() if isinstance(value, datetime) else value for value in after]
            result, table = self._call(
                "import",
                {
                    **source["parameters"],
                    "incremental": {**incremental, "overlap": 0},
                    "max_rows": 5000,
                },
                {"read_checkpoint": {"after": after, "revision": 0}},
            )
            import pyarrow as pa

            if _rows(table) != _rows(
                pa.Table.from_pylist(ordered[1:], schema=golden.schema)
            ) or not result.get("next_checkpoint"):
                raise AdapterError("KIT_INCREMENTAL_MISMATCH")
            return {"row_count": table.num_rows, "result_digest": _digest(_rows(table))}
        if suite.startswith("consistency:"):
            result, table = self._read()
            if result.get("consistency") != suite.split(":", 1)[1]:
                raise AdapterError("KIT_CONSISTENCY_MISMATCH")
            if not suite.endswith(":none"):
                raise PendingError("KIT_CONCURRENT_SOURCE_CHANGE_REQUIRED")
            return {"row_count": table.num_rows, "result_digest": _digest(_rows(table))}
        if suite in {"write_append", "write_overwrite", "write_upsert", "export_files"}:
            return self._write(suite)
        if suite.startswith("outcome:") and not suite.endswith(":none"):
            if not self.write_results:
                raise PendingError("KIT_COMPLETED_WRITE_REQUIRED")
            for parameters, execution, expected in self.write_results.values():
                result = self._call("reconcile_write", parameters, execution)
                if (
                    result.get("applied") is not True
                    or result.get("contract_digest") != execution["contract_digest"]
                ):
                    raise AdapterError("KIT_RECONCILIATION_INVALID")
            return {"result_digest": _digest(result)}
        if suite.startswith("unsupported:"):
            operation = suite.split(":", 1)[1]
            if operation in {"read_partitioned", "read_incremental", "create_table"}:
                raise PendingError("KIT_CAPABILITY_REFUSAL_SCENARIO_REQUIRED")
            operation = {"read": "import", "export_files": "export"}.get(operation, operation)
            try:
                self._call(operation)
            except AdapterError as exc:
                if exc.code == "CONNECTOR_OPERATION_UNSUPPORTED":
                    return {"result_digest": _digest({"operation": operation, "code": exc.code})}
                raise AdapterError("KIT_REFUSAL_CODE_MISMATCH") from None
            raise AdapterError("KIT_UNSUPPORTED_OPERATION_EXECUTED")
        pending = {
            "security": "KIT_ADVERSARIAL_TRANSPORT_REQUIRED",
            "revocation": "KIT_LIVE_REVOCATION_REQUIRED",
            "resilience": "KIT_LIVE_FAULT_INJECTION_REQUIRED",
            "lineage": "KIT_WORKSPACE_FLOW_REQUIRED",
            "write_unknown_outcome": "KIT_LOST_COMMIT_REPLY_REQUIRED",
            "write_read_only_refusal": "KIT_READ_ONLY_ROLE_REQUIRED",
            "write_dry_run": "KIT_APPROVAL_PREVIEW_REQUIRED",
            "watch": "KIT_REAL_WATCH_CHANGE_REQUIRED",
        }
        raise PendingError(pending.get(suite, "KIT_SCENARIO_REQUIRED"))

    def run(self, suite):
        started = time.monotonic()
        output = {}
        try:
            output = self.case(suite)
            status, code = "passed", "KIT_PASSED"
        except PendingError as exc:
            status, code = "skipped", str(exc)
        except BaseException as exc:
            status, code = "failed", getattr(exc, "code", "KIT_CASE_FAILED")
            if not isinstance(code, str) or not re.fullmatch(
                r"(?:CONNECTOR|HANA|KIT)_[A-Z_]+", code
            ):
                code = "KIT_CASE_FAILED"
        report = ProofReport(
            suite=suite,
            status=status,
            code=code,
            elapsed_ms=min(604800000, int((time.monotonic() - started) * 1000)),
            rows=output.get("row_count"),
            result_digest=output.get("result_digest"),
        )
        self.reports[suite] = report.model_dump(mode="json")
        self.save()
        return report

    def save(self):
        metadata = {
            key: self.config[key]
            for key in ("source_revision", "environment", "environment_id", "source")
        }
        metadata.update(
            identity=self.identity,
            completed_at=datetime.now(UTC).isoformat(),
            kit=kit_identity(),
            network_exception_ids=[
                entry["exception_id"] for entry in self.config.get("network_grants", [])
            ],
        )
        files = [
            (Path("metadata.json"), metadata),
            (Path("reports.json"), list(self.reports.values())),
        ]
        for index, (suite, report) in enumerate(sorted(self.reports.items())):
            safe = re.sub(r"[^A-Za-z0-9_-]", "_", suite)
            files.append((Path("reports") / f"{index:02d}-{safe}.json", report))
        # The suite set grows monotonically during a run. Use a suite-derived
        # filename so insertion of an alphabetically earlier case cannot leave
        # an old numbered report behind as a duplicate proof.
        for old in self.report_directory.glob("*.json"):
            old.unlink()
        for name, value in files:
            target = self.directory / name
            temporary = self.directory / (str(name) + ".tmp")
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(descriptor, "w") as handle:
                json.dump(value, handle, indent=2, allow_nan=False)
            temporary.replace(target)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Run an explicitly configured supplier bench; no deployment or automatic qualification"
    )
    parser.add_argument("--config", required=True)
    parser.add_argument("--reports", required=True)
    args = parser.parse_args(argv)
    try:
        bench = Bench(load_config(args.config), args.reports)
        suites = sorted(
            required_suites(bench.profile.capabilities),
            key=lambda name: (name.startswith("outcome:"), name),
        )
        for suite in suites:
            report = bench.run(suite)
            print(f"{report.suite}: {report.status} ({report.code})")
        return (
            0
            if bench.identity and all(item["status"] == "passed" for item in bench.reports.values())
            else 2
        )
    except Exception:
        print("KIT_CONFIGURATION_OR_RUNTIME_FAILED")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
