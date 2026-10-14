#!/usr/bin/env python3
"""Run from checkout: stdin-only candidate check inside the existing backend.

No source is installed on the VM. PostgreSQL transaction is read-only; the only
HANA queries are the connector's DUMMY test and SELECT 1 in a read-only transaction.
Passwords and raw driver errors never leave the backend process.
"""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
PATHS = (
    "backend/app/services/connectors/hana/network_policy.py",
    "backend/app/services/connectors/hana/service.py",
)
sources = {path: (ROOT / path).read_text() for path in PATHS}
remote = r'''
import datetime, hashlib, importlib.metadata, json, logging, os, ssl, sys, types
logging.disable(logging.CRITICAL)
from sqlalchemy import text
from app.db.base import SessionLocal
from app.models.workspace import Workspace
from app.services.connectors.hana import service as deployed_service
from app.core.config import settings
from hdbcli import dbapi
report = {
    "observed_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "workspace_slug": "agentium-showcase",
    "execution": "candidate modules in memory in a separate docker exec process; no deployment or HTTP route qualification",
    "postgresql_read_only": True,
    "hdbcli_version": importlib.metadata.version("hdbcli"),
    "openssl_version": ssl.OPENSSL_VERSION,
    "runtime_image_revision": os.environ.get("AGENTIUM_IMAGE_REVISION"),
    "candidate_source_sha256": {p: hashlib.sha256(s.encode()).hexdigest() for p,s in sources.items()},
    "operations": [],
}
try:
    with SessionLocal() as db:
        db.execute(text("SET TRANSACTION READ ONLY"))
        workspace = db.query(Workspace).filter(Workspace.slug == "agentium-showcase").one()
        report["workspace_id"] = str(workspace.id)
        report["connector_enabled"] = deployed_service.is_workspace_enabled(workspace)
        stored = (workspace.settings or {}).get("connectors", {}).get("sap_hana", {})
        safe = ("host", "port", "user", "encrypt", "ssl_validate_certificate", "demo_mode")
        report["stored_nonsecret_config"] = {k:stored[k] for k in safe if k in stored}
        report["stored_tls_verification_present"] = "ssl_validate_certificate" in stored
        report["stored_demo_mode_present"] = "demo_mode" in stored
        for path, name in zip(sources, ("app.services.connectors.hana.network_policy", "hana_candidate_service")):
            module = types.ModuleType(name)
            sys.modules[name] = module
            exec(compile(sources[path], "<candidate:" + path + ">", "exec"), module.__dict__)
        candidate = sys.modules["hana_candidate_service"]
        report["candidate_effective_config"] = candidate.get_config(workspace)
        report["candidate_effective_policy"] = {
            "hana_allow_insecure_tls": getattr(settings, "hana_allow_insecure_tls", False),
            "hana_writes_enabled": getattr(settings, "hana_writes_enabled", False),
            "hana_network_policy_mode": getattr(settings, "hana_network_policy_mode", "report"),
        }
        config = candidate.get_config(workspace, include_secrets=True)
        report["workspace_password_resolved"] = bool(config.get("password"))
        original_connect = dbapi.connect
        def observed_connect(**kwargs):
            attempt = {k:kwargs.get(k) for k in ("address", "port", "encrypt", "sslValidateCertificate", "sslHostNameInCertificate", "sslSNIHostname", "distributionMode", "communicationTimeout", "connectTimeout")}
            assert kwargs["encrypt"] is True
            assert kwargs["sslValidateCertificate"] is True
            assert kwargs["sslHostNameInCertificate"] == config["host"]
            attempts.append(attempt)
            try:
                conn = original_connect(**kwargs)
                attempt["connected"] = True
                return conn
            except Exception as exc:
                message = str(exc).lower()
                attempt.update(connected=False, driver_error_type=type(exc).__name__, driver_error_code=exc.args[0] if exc.args and isinstance(exc.args[0], int) else None,
                    certificate_validation_error=any(s in message for s in ("certificate", "ssl validation", "ssl_validate")),
                    authentication_error="authentication failed" in message,
                    timeout_error="timeout" in message or "timed out" in message,
                    diagnostic_terms=[s for s in ("connection refused", "cannot create ssl context", "ssl", "crypto", "sapssl", "invalid", "unknown", "host", "unreachable", "network", "name resolution", "rte", "socket closed", "closed", "connect failed", "connection failed", "connection reset", "timeout", "parameter", "trust", "authentication") if s in message],
                    sanitized_driver_message=str(exc).replace(config["password"], "<redacted>")[:1200])
                raise
        dbapi.connect = observed_connect
        for operation in ("test_connection", "select_one_read_only"):
            attempts = []
            entry = {"operation": operation, "connection_attempts": attempts}
            try:
                if operation == "test_connection":
                    result = candidate.test_connection(config)
                else:
                    entry.update(sql="SELECT 1 FROM DUMMY", max_rows=1, allow_writes=False)
                    result = candidate.run_query(config, "SELECT 1 FROM DUMMY", max_rows=1, allow_writes=False)
                entry.update(ok=True, result=result)
            except candidate.HanaConnectorError as exc:
                entry.update(ok=False, code=exc.code, status_code=exc.status_code)
            except Exception as exc:
                entry.update(ok=False, error_type=type(exc).__name__)
            report["operations"].append(entry)
        dbapi.connect = original_connect
        report["diagnostic_hostname_connection"] = {"address_mode": "configured hostname, unpinned diagnostic only", "encrypt": True, "sslValidateCertificate": True}
        try:
            conn = original_connect(address=config["host"], port=config["port"], user=config["user"], password=config["password"], encrypt=True, sslValidateCertificate=True, connectTimeout=3000, communicationTimeout=10000)
            try:
                conn.setautocommit(False)
                cursor = conn.cursor()
                cursor.execute("SET TRANSACTION READ ONLY")
                cursor.execute("SELECT 1 FROM DUMMY")
                report["diagnostic_hostname_connection"].update(ok=True, rows=[list(row) for row in cursor.fetchmany(1)])
                cursor.close()
            finally:
                conn.close()
        except Exception as exc:
            report["diagnostic_hostname_connection"].update(ok=False, error_type=type(exc).__name__, sanitized_driver_message=str(exc).replace(config["password"], "<redacted>")[:1200])
        config.clear()
        db.rollback()
except Exception as exc:
    report["probe_error_type"] = type(exc).__name__
report["all_live_checks_passed"] = (
    not report.get("probe_error_type")
    and len(report["operations"]) == 2
    and all(o.get("ok") is True for o in report["operations"])
    and report["operations"][1].get("result", {}).get("source") == "hana_live"
)
print(json.dumps(report, indent=2, sort_keys=True))
'''
program = "sources = " + repr(sources) + "\n" + remote
try:
    result = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", "omnirag-demo", "docker exec -i -e PYTHONDONTWRITEBYTECODE=1 agentium-backend python -"], input=program, text=True, capture_output=True, timeout=55)
except (OSError, subprocess.TimeoutExpired) as exc:
    print(json.dumps({"transport_error_type": type(exc).__name__}))
    raise SystemExit(1)
try:
    report = json.loads(result.stdout)
except ValueError:
    print(json.dumps({"transport_exit_code": result.returncode, "invalid_json": True}))
    raise SystemExit(1)
print(json.dumps(report, indent=2, sort_keys=True))
raise SystemExit(0 if result.returncode == 0 and report.get("all_live_checks_passed") is True else 1)
