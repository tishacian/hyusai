#!/usr/bin/env python3
"""Bounded PostgreSQL inventory and controlled-canary comparison.

Version 2 never materializes or serializes every database row. Each table is
represented by a row count and two domain-separated, commutative SHA-256 sums.
Only rows named by a strict private canary ledger receive per-row hashed
details. Canonical navigation events are represented by one bounded aggregate
per workspace. The SFTP lifecycle contract observes a baseline, an active link
after successful authentication, and the same link after revocation and a
denied authentication. Raw primary keys, access identifiers, and tenant row
values never leave the collector.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import stat
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import PurePath
from typing import Any

from sqlalchemy import MetaData, Table, inspect, select

from app.db.base import engine

SCHEMA_VERSION = 2
INVENTORY_PROFILE = "agentium-postgresql-row-inventory-v2"
COMPARISON_PROFILE = "agentium-controlled-canary-postgresql-v2"
SFTP_LEDGER_KIND = "agentium-release-a-sftp-postgres-private-input"
SFTP_RECEIPT_KIND = "agentium-release-a-sftp-postgres-ledger"
SFTP_RELEASE_A_CANARY_ACCESS_ID_PREFIX = "ra1_"
ACCUMULATOR_ALGORITHM = "sha256-domain-sum-mod-2^256-v1"
ACCUMULATOR_MODULUS = 1 << 256
ACCUMULATOR_DOMAINS = {
    "primary_key": "agentium.postgresql.multiset.primary-key.v1",
    "row_state": "agentium.postgresql.multiset.row-state.v1",
}
MAX_ARTIFACT_BYTES = 16 * 1024 * 1024
MAX_LEDGER_BYTES = 1024 * 1024
MAX_SFTP_LEDGER_BYTES = 64 * 1024
MAX_SFTP_RECEIPT_BYTES = 64 * 1024
MAX_SFTP_AUDIT_TO_RECEIPT_SECONDS = 300
MAX_CONTROLLED_INVOCATIONS = 10_000
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SQL_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
DEPLOYMENT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{5,95}$")
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
CONTAINER_ID_RE = re.compile(r"^[0-9a-f]{64}$")
IMAGE_ID_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
# Volatility is table-explicit. No prefix, schema, or product-wide exception is
# accepted by the comparator.
KEYCLOAK_VOLATILE_TABLES = frozenset(
    {
        "admin_event_entity",
        "authentication_session",
        "authentication_session_auth_note",
        "authentication_session_client_note",
        "authentication_session_execution",
        "client_session",
        "client_session_auth_status",
        "client_session_note",
        "event_entity",
        "offline_client_session",
        "offline_user_session",
        "user_session",
        "user_session_note",
    }
)
SFTP_STAGES = frozenset({"active", "revoked"})
SFTP_AUDIT_PHASES = (
    ("created", "deposit.link.created", "info"),
    ("auth_success", "deposit.sftp.auth.success", "info"),
    ("revoked", "deposit.link.revoked", "info"),
    (
        "auth_failed_inactive",
        "deposit.sftp.auth.failed",
        "warning",
    ),
)


class PostCanaryDatabaseError(RuntimeError):
    """Raised when PostgreSQL cannot be proven unchanged as declared."""


def _canonical(value: Any) -> Any:
    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise PostCanaryDatabaseError("non-finite numeric value in PostgreSQL row")
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, bytes):
        return {"bytes_base64": base64.b64encode(value).decode("ascii")}
    if isinstance(value, Mapping):
        return {str(key): _canonical(child) for key, child in sorted(value.items())}
    if isinstance(value, list | tuple):
        return [_canonical(child) for child in value]
    return str(value)


def _json_bytes(value: Any) -> bytes:
    return json.dumps(
        _canonical(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _sha(value: Any) -> str:
    return hashlib.sha256(_json_bytes(value)).hexdigest()


def _identity(candidate_sha: str, deployment_id: str) -> None:
    if SHA_RE.fullmatch(candidate_sha) is None:
        raise PostCanaryDatabaseError("candidate SHA is invalid")
    if DEPLOYMENT_ID_RE.fullmatch(deployment_id) is None:
        raise PostCanaryDatabaseError("deployment-id is invalid")


def _normalized_row(table_name: str, row: Mapping[str, Any]) -> dict[str, Any]:
    normalized = dict(row)
    if table_name == "users":
        normalized.pop("last_login", None)
    return normalized


def _business_projection(tables: Mapping[str, Any]) -> dict[str, Any]:
    return {name: value for name, value in tables.items() if name not in KEYCLOAK_VOLATILE_TABLES}


def _canonical_navigation_audit(
    row: Mapping[str, Any], *, workspace_slugs: Mapping[str, str]
) -> bool:
    details = row.get("details")
    workspace_id = str(row.get("workspace_id") or "")
    if not isinstance(details, dict):
        return False
    expected_detail_keys = {
        "schema_version",
        "requested_route",
        "resolved_route",
        "effective_workspace",
        "effective_surface",
        "redirect_owner",
        "redirect_reason",
        "redirected",
    }
    if (
        row.get("event_type") != "navigation.resolved"
        or row.get("actor") != "authenticated_user"
        or row.get("trace_id") is not None
        or row.get("agent_id") is not None
        or row.get("severity") != "info"
        or set(details) != expected_detail_keys
        or details.get("schema_version") != 1
        or not isinstance(details.get("redirected"), bool)
        or details.get("effective_workspace") != workspace_slugs.get(workspace_id)
    ):
        return False
    for key in expected_detail_keys - {"schema_version", "redirected"}:
        value = details.get(key)
        if not isinstance(value, str) or not value or "@" in value:
            return False
    for key in ("requested_route", "resolved_route"):
        value = str(details[key])
        if not value.startswith("/") or "?" in value or "#" in value:
            return False
    return True


def _domain_value(domain: str, primary_key_sha256: str, row_sha256: str | None) -> int:
    if SHA256_RE.fullmatch(primary_key_sha256) is None or (
        row_sha256 is not None and SHA256_RE.fullmatch(row_sha256) is None
    ):
        raise PostCanaryDatabaseError("internal PostgreSQL row hash is invalid")
    digest = hashlib.sha256()
    digest.update(domain.encode("ascii"))
    digest.update(b"\x00")
    digest.update(bytes.fromhex(primary_key_sha256))
    if row_sha256 is not None:
        digest.update(b"\x00")
        digest.update(bytes.fromhex(row_sha256))
    return int.from_bytes(digest.digest(), "big")


class _MultisetAccumulator:
    """Constant-space, order-independent digest of a multiset of rows."""

    __slots__ = ("count", "sums")

    def __init__(self) -> None:
        self.count = 0
        self.sums = {name: 0 for name in ACCUMULATOR_DOMAINS}

    def add_hashes(
        self,
        primary_key_sha256: str,
        row_sha256: str,
        *,
        multiplicity: int = 1,
    ) -> None:
        if not isinstance(multiplicity, int) or multiplicity <= 0:
            raise PostCanaryDatabaseError("row multiplicity is invalid")
        values = {
            "primary_key": _domain_value(
                ACCUMULATOR_DOMAINS["primary_key"], primary_key_sha256, None
            ),
            "row_state": _domain_value(
                ACCUMULATOR_DOMAINS["row_state"],
                primary_key_sha256,
                row_sha256,
            ),
        }
        self.count += multiplicity
        for name, value in values.items():
            self.sums[name] = (self.sums[name] + value * multiplicity) % ACCUMULATOR_MODULUS

    def contract(self) -> dict[str, Any]:
        return {
            "algorithm": ACCUMULATOR_ALGORITHM,
            "domains": dict(ACCUMULATOR_DOMAINS),
            "sums": {name: f"{self.sums[name]:064x}" for name in ACCUMULATOR_DOMAINS},
        }


def _ledger_ids(
    ledger: Mapping[str, Any], *, candidate_sha: str, deployment_id: str
) -> tuple[str, list[str]]:
    run_id = str(ledger.get("run_id") or "")
    invocation_ids = ledger.get("invocation_ids")
    if (
        ledger.get("kind") != "safe_controlled_chat_ledger"
        or ledger.get("outcome") != "passed"
        or ledger.get("commit_sha") != candidate_sha
        or ledger.get("deployment_id") != deployment_id
        or UUID_RE.fullmatch(run_id) is None
        or not isinstance(invocation_ids, list)
        or not invocation_ids
        or len(invocation_ids) > MAX_CONTROLLED_INVOCATIONS
        or any(UUID_RE.fullmatch(str(value)) is None for value in invocation_ids)
        or len(invocation_ids) != len(set(map(str, invocation_ids)))
    ):
        raise PostCanaryDatabaseError("controlled Chat ledger is invalid")
    return run_id, sorted(map(str, invocation_ids))


def _ledger_binding(
    *,
    run_id: str | None,
    invocation_ids: Sequence[str],
    ledger_sha256: str | None,
) -> dict[str, Any]:
    if run_id is None:
        return {
            "provided": False,
            "ledger_sha256": None,
            "controlled_run_primary_key_sha256": None,
            "controlled_invocation_count": 0,
            "controlled_invocation_primary_keys_sha256": None,
        }
    if ledger_sha256 is None or SHA256_RE.fullmatch(ledger_sha256) is None:
        raise PostCanaryDatabaseError("controlled Chat ledger digest is invalid")
    invocation_hashes = sorted(_sha([value]) for value in invocation_ids)
    return {
        "provided": True,
        "ledger_sha256": ledger_sha256,
        "controlled_run_primary_key_sha256": _sha([run_id]),
        "controlled_invocation_count": len(invocation_hashes),
        "controlled_invocation_primary_keys_sha256": _sha(invocation_hashes),
    }


def _require_sha256(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        raise PostCanaryDatabaseError(f"{label} digest is invalid")
    return value


def _sftp_ledger_contract(
    ledger: Mapping[str, Any], *, candidate_sha: str, deployment_id: str
) -> dict[str, Any]:
    """Validate the closed private input used to discover DB rows."""

    expected_keys = {
        "schema_version",
        "kind",
        "live_sha",
        "release_a_sha",
        "sftp_sha",
        "deployment_id",
        "hostname_sha256",
        "workspace_id",
        "link_id",
        "access_id",
        "operator_actor",
        "link_label",
        "credential_fingerprint_sha256",
        "sftp_container_id",
        "sftp_image_id",
        "sftp_port",
        "runtime_identity_sha256",
        "active_sftp_session_count",
    }
    if (
        not isinstance(ledger, dict)
        or set(ledger) != expected_keys
        or ledger.get("schema_version") != 1
        or ledger.get("kind") != SFTP_LEDGER_KIND
        or ledger.get("release_a_sha") != candidate_sha
        or ledger.get("deployment_id") != deployment_id
        or SHA_RE.fullmatch(str(ledger.get("live_sha") or "")) is None
        or SHA_RE.fullmatch(str(ledger.get("release_a_sha") or "")) is None
        or SHA_RE.fullmatch(str(ledger.get("sftp_sha") or "")) is None
        or ledger.get("live_sha") == ledger.get("release_a_sha")
        or UUID_RE.fullmatch(str(ledger.get("workspace_id") or "")) is None
        or UUID_RE.fullmatch(str(ledger.get("link_id") or "")) is None
        or not isinstance(ledger.get("access_id"), str)
        or not 1 <= len(ledger["access_id"].encode("utf-8")) <= 80
        or not ledger["access_id"].startswith(SFTP_RELEASE_A_CANARY_ACCESS_ID_PREFIX)
        or ledger["access_id"] != ledger["access_id"].strip()
        or any(ord(character) < 33 or ord(character) == 127 for character in ledger["access_id"])
        or not isinstance(ledger.get("operator_actor"), str)
        or not ledger["operator_actor"]
        or ledger["operator_actor"] != ledger["operator_actor"].strip()
        or not isinstance(ledger.get("link_label"), str)
        or not 1 <= len(ledger["link_label"]) <= 255
        or CONTAINER_ID_RE.fullmatch(str(ledger.get("sftp_container_id") or "")) is None
        or IMAGE_ID_RE.fullmatch(str(ledger.get("sftp_image_id") or "")) is None
        or not isinstance(ledger.get("sftp_port"), int)
        or isinstance(ledger.get("sftp_port"), bool)
        or not 1 <= int(ledger["sftp_port"]) <= 65_535
        or ledger.get("active_sftp_session_count") != 0
    ):
        raise PostCanaryDatabaseError("SFTP canary private ledger is invalid")
    for key in (
        "hostname_sha256",
        "credential_fingerprint_sha256",
        "runtime_identity_sha256",
    ):
        _require_sha256(ledger.get(key), label=f"SFTP {key}")
    return dict(ledger)


def _sftp_stage_primary_keys(ledger: Mapping[str, Any], *, stage: str) -> dict[str, set[str]]:
    if stage not in SFTP_STAGES:
        raise PostCanaryDatabaseError("SFTP canary snapshot stage is invalid")
    return {
        "deposit_access_links": {_sha([ledger["link_id"]])},
        "audit_logs": set(),
    }


def _sftp_expected_phases(stage: str) -> tuple[str, ...]:
    phases = tuple(row[0] for row in SFTP_AUDIT_PHASES)
    return phases[:2] if stage == "active" else phases


def _sftp_audit_phase(row: Mapping[str, Any], *, ledger: Mapping[str, Any]) -> str | None:
    details = row.get("details")
    if not isinstance(details, dict):
        return None
    for phase, event_type, severity in SFTP_AUDIT_PHASES:
        expected_keys = {"access_id", "link_id"}
        if phase == "created":
            expected_keys.add("label")
        elif phase == "auth_failed_inactive":
            expected_keys.add("reason")
        if (
            row.get("event_type") != event_type
            or row.get("severity") != severity
            or set(details) != expected_keys
            or details.get("access_id") != ledger["access_id"]
            or details.get("link_id") != ledger["link_id"]
        ):
            continue
        if phase == "created" and (
            details.get("label") != ledger["link_label"]
            or row.get("actor") != ledger["operator_actor"]
        ):
            continue
        if phase == "revoked" and row.get("actor") != ledger["operator_actor"]:
            continue
        if (
            phase in {"auth_success", "auth_failed_inactive"}
            and row.get("actor") != f"sftp:{ledger['access_id']}"
        ):
            continue
        if phase == "auth_failed_inactive" and details.get("reason") != ("inactive_or_expired"):
            continue
        return phase
    return None


def _sftp_controlled_row_semantics(
    *,
    table_name: str,
    row: Mapping[str, Any],
    row_sha256: str,
    primary_key_sha256: str,
    ledger: Mapping[str, Any],
    stage: str,
    observed_timestamps: dict[str, datetime],
) -> str | None:
    """Validate private row values and retain only timestamps in memory."""

    if table_name == "deposit_access_links":
        expected_columns = {
            "id",
            "workspace_id",
            "created_by_user_id",
            "label",
            "access_id",
            "password_hash",
            "status",
            "expires_at",
            "max_file_size_mb",
            "allowed_extensions",
            "created_at",
            "updated_at",
        }
        created_at = row.get("created_at")
        updated_at = row.get("updated_at")
        if (
            set(row) != expected_columns
            or UUID_RE.fullmatch(str(row.get("id") or "")) is None
            or row.get("id") != ledger["link_id"]
            or primary_key_sha256 != _sha([ledger["link_id"]])
            or row.get("workspace_id") != ledger["workspace_id"]
            or UUID_RE.fullmatch(str(row.get("created_by_user_id") or "")) is None
            or row.get("access_id") != ledger["access_id"]
            or row.get("label") != ledger["link_label"]
            or row.get("status") != stage
            or not isinstance(created_at, datetime)
            or not isinstance(updated_at, datetime)
            or row_sha256 != _sha(_normalized_row(table_name, row))
            or not isinstance(row.get("max_file_size_mb"), int)
            or isinstance(row.get("max_file_size_mb"), bool)
            or int(row["max_file_size_mb"]) <= 0
            or not isinstance(row.get("allowed_extensions"), list)
            or not isinstance(row.get("label"), str)
            or not row["label"]
            or not isinstance(row.get("access_id"), str)
            or not row["access_id"]
            or not isinstance(row.get("password_hash"), str)
            or not row["password_hash"]
            or (
                row.get("expires_at") is not None
                and not isinstance(row.get("expires_at"), datetime)
            )
        ):
            return False
        observed_timestamps["link_created"] = created_at
        observed_timestamps[f"link_{stage}_updated"] = updated_at
        return "link"

    if table_name != "audit_logs":
        return None
    timestamp = row.get("timestamp")
    details = row.get("details")
    if not isinstance(timestamp, datetime) or not isinstance(details, dict):
        return None
    phase = _sftp_audit_phase(row, ledger=ledger)
    if phase is None or phase not in _sftp_expected_phases(stage):
        return None
    expected_columns = {
        "id",
        "workspace_id",
        "timestamp",
        "event_type",
        "actor",
        "details",
        "trace_id",
        "agent_id",
        "severity",
    }
    if (
        set(row) != expected_columns
        or UUID_RE.fullmatch(str(row.get("id") or "")) is None
        or primary_key_sha256 != _sha([row.get("id")])
        or row.get("workspace_id") != ledger["workspace_id"]
        or row.get("trace_id") is not None
        or row.get("agent_id") is not None
        or row_sha256 != _sha(_normalized_row(table_name, row))
    ):
        return None
    if f"audit_{phase}" in observed_timestamps:
        raise PostCanaryDatabaseError(f"duplicate SFTP canary audit phase: {phase}")
    observed_timestamps[f"audit_{phase}"] = timestamp
    return phase


def _timestamp_key(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def _utc_timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    else:
        value = value.astimezone(UTC)
    return value.isoformat().replace("+00:00", "Z")


def _validate_sftp_observed_timestamps(observed: Mapping[str, datetime], *, stage: str) -> None:
    phases = ["created", "auth_success"]
    if stage == "revoked":
        phases.extend(("revoked", "auth_failed_inactive"))
    required = {
        "link_created",
        f"link_{stage}_updated",
        *(f"audit_{phase}" for phase in phases),
    }
    if set(observed) != required:
        raise PostCanaryDatabaseError("SFTP canary lifecycle timestamps are incomplete")
    audit_times = [_timestamp_key(observed[f"audit_{phase}"]) for phase in phases]
    link_created = _timestamp_key(observed["link_created"])
    link_updated = _timestamp_key(observed[f"link_{stage}_updated"])
    if (
        audit_times != sorted(audit_times)
        or link_created > audit_times[0]
        or link_updated < link_created
        or (stage == "active" and link_updated > audit_times[0])
        or (stage == "revoked" and link_updated < audit_times[1])
        or (stage == "revoked" and link_updated > audit_times[2])
    ):
        raise PostCanaryDatabaseError("SFTP canary lifecycle chronology is invalid")


def _table_payload(
    *,
    primary_keys: Sequence[str],
    accumulator: _MultisetAccumulator,
    normalization: Sequence[str],
    controlled_rows: Mapping[str, str],
    canonical_navigation: Mapping[str, _MultisetAccumulator],
    controlled_sftp_audits: Mapping[str, Mapping[str, Any]] | None = None,
    controlled_sftp_link: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "primary_key_columns": list(primary_keys),
        "row_count": accumulator.count,
        "multiset": accumulator.contract(),
        "normalization": list(normalization),
        "controlled_rows": dict(sorted(controlled_rows.items())),
        "controlled_sftp_audits": {
            phase: dict(value) for phase, value in sorted((controlled_sftp_audits or {}).items())
        },
        "controlled_sftp_link": (
            dict(controlled_sftp_link) if controlled_sftp_link is not None else None
        ),
        "canonical_navigation_by_workspace": {
            workspace_hash: {
                "row_count": value.count,
                "multiset": value.contract(),
            }
            for workspace_hash, value in sorted(canonical_navigation.items())
        },
    }


def _inventory_sha256(
    *,
    tables: Mapping[str, Any],
    workspace_identities: Sequence[Mapping[str, str]],
    ledger_binding: Mapping[str, Any],
) -> str:
    return _sha(
        {
            "tables": tables,
            "workspace_identities": workspace_identities,
            "ledger_binding": ledger_binding,
        }
    )


def build_inventory(
    *,
    candidate_sha: str,
    deployment_id: str,
    ledger: Mapping[str, Any] | None = None,
    ledger_sha256: str | None = None,
    sftp_ledger: Mapping[str, Any] | None = None,
    sftp_stage: str | None = None,
) -> dict[str, Any]:
    _identity(candidate_sha, deployment_id)
    if ledger is not None and sftp_ledger is not None:
        raise PostCanaryDatabaseError("Chat and SFTP ledgers cannot share a snapshot")
    run_id: str | None = None
    invocation_ids: list[str] = []
    controlled_expectations: dict[str, set[str]] = {}
    normalized_sftp_ledger: dict[str, Any] | None = None
    if ledger is not None:
        run_id, invocation_ids = _ledger_ids(
            ledger, candidate_sha=candidate_sha, deployment_id=deployment_id
        )
        controlled_expectations = {
            "runs": {_sha([run_id])},
            "skill_invocations": {_sha([value]) for value in invocation_ids},
        }
    elif ledger_sha256 is not None:
        raise PostCanaryDatabaseError("ledger digest supplied without a ledger")
    if sftp_ledger is not None:
        if sftp_stage is None:
            raise PostCanaryDatabaseError("SFTP ledger requires a snapshot stage")
        normalized_sftp_ledger = _sftp_ledger_contract(
            sftp_ledger,
            candidate_sha=candidate_sha,
            deployment_id=deployment_id,
        )
        controlled_expectations = _sftp_stage_primary_keys(normalized_sftp_ledger, stage=sftp_stage)
    elif sftp_stage is not None:
        raise PostCanaryDatabaseError("SFTP snapshot stage requires its ledger")
    binding = _ledger_binding(
        run_id=run_id,
        invocation_ids=invocation_ids,
        ledger_sha256=ledger_sha256,
    )

    tables: dict[str, Any] = {}
    sftp_observed_timestamps: dict[str, datetime] = {}
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as connection:
        transaction = connection.begin()
        try:
            inspector = inspect(connection)
            table_names = sorted(inspector.get_table_names(schema="public"))
            workspace_slugs: dict[str, str] = {}
            if "workspaces" in table_names:
                workspace_table = Table(
                    "workspaces", MetaData(), autoload_with=connection, schema="public"
                )
                workspace_slugs = {
                    str(row["id"]): str(row["slug"])
                    for row in connection.execute(
                        select(workspace_table.c.id, workspace_table.c.slug)
                    ).mappings()
                }

            for table_name in table_names:
                table = Table(
                    table_name,
                    MetaData(),
                    autoload_with=connection,
                    schema="public",
                )
                primary_keys = [column.name for column in table.primary_key.columns]
                if not primary_keys:
                    raise PostCanaryDatabaseError(
                        f"table without a primary key cannot be attested: {table_name}"
                    )
                if table_name in controlled_expectations and primary_keys != ["id"]:
                    raise PostCanaryDatabaseError(
                        f"controlled table primary key is unsupported: {table_name}"
                    )
                accumulator = _MultisetAccumulator()
                controlled_rows: dict[str, str] = {}
                controlled_sftp_audits: dict[str, dict[str, Any]] = {}
                controlled_sftp_link: dict[str, str] | None = None
                navigation: dict[str, _MultisetAccumulator] = {}
                statement = select(table).execution_options(stream_results=True, yield_per=1_000)
                for result in connection.execute(statement).mappings():
                    values = dict(result)
                    primary_key_hash = _sha([values.get(column) for column in primary_keys])
                    row_hash = _sha(_normalized_row(table_name, values))
                    accumulator.add_hashes(primary_key_hash, row_hash)
                    is_declared_control = primary_key_hash in controlled_expectations.get(
                        table_name, set()
                    )
                    sftp_phase: str | None = None
                    if (
                        normalized_sftp_ledger is not None
                        and sftp_stage is not None
                        and (is_declared_control or table_name == "audit_logs")
                    ):
                        sftp_phase = _sftp_controlled_row_semantics(
                            table_name=table_name,
                            row=values,
                            row_sha256=row_hash,
                            primary_key_sha256=primary_key_hash,
                            ledger=normalized_sftp_ledger,
                            stage=sftp_stage,
                            observed_timestamps=sftp_observed_timestamps,
                        )
                        if is_declared_control and sftp_phase is None:
                            raise PostCanaryDatabaseError(
                                f"SFTP controlled row contract differs: {table_name}"
                            )
                    if is_declared_control or sftp_phase is not None:
                        controlled_rows[primary_key_hash] = row_hash
                    if sftp_phase not in {None, "link"}:
                        controlled_sftp_audits[sftp_phase] = {
                            "primary_key_sha256": primary_key_hash,
                            "row_sha256": row_hash,
                            "occurred_at": _utc_timestamp(values["timestamp"]),
                        }
                    elif sftp_phase == "link":
                        controlled_sftp_link = {
                            "primary_key_sha256": primary_key_hash,
                            "row_sha256": row_hash,
                            "invariant_sha256": _sha(
                                {
                                    key: value
                                    for key, value in values.items()
                                    if key not in {"status", "updated_at"}
                                }
                            ),
                            "status": str(values["status"]),
                        }
                    if table_name == "audit_logs" and _canonical_navigation_audit(
                        values, workspace_slugs=workspace_slugs
                    ):
                        workspace_hash = _sha([values.get("workspace_id")])
                        navigation.setdefault(workspace_hash, _MultisetAccumulator()).add_hashes(
                            primary_key_hash, row_hash
                        )
                if (
                    table_name in controlled_expectations
                    and table_name != "audit_logs"
                    and (set(controlled_rows) != controlled_expectations[table_name])
                ):
                    raise PostCanaryDatabaseError(
                        f"controlled ledger rows are absent from table: {table_name}"
                    )
                if (
                    normalized_sftp_ledger is not None
                    and table_name == "audit_logs"
                    and (
                        set(controlled_sftp_audits) != set(_sftp_expected_phases(str(sftp_stage)))
                        or set(controlled_rows)
                        != {row["primary_key_sha256"] for row in controlled_sftp_audits.values()}
                    )
                ):
                    raise PostCanaryDatabaseError(
                        "SFTP controlled audit rows are incomplete or ambiguous"
                    )
                tables[table_name] = _table_payload(
                    primary_keys=primary_keys,
                    accumulator=accumulator,
                    normalization=["last_login"] if table_name == "users" else [],
                    controlled_rows=controlled_rows,
                    canonical_navigation=navigation,
                    controlled_sftp_audits=controlled_sftp_audits,
                    controlled_sftp_link=controlled_sftp_link,
                )
            if ledger is not None and not set(controlled_expectations).issubset(tables):
                raise PostCanaryDatabaseError("controlled ledger tables are absent from PostgreSQL")
            if sftp_ledger is not None:
                if not set(controlled_expectations).issubset(tables):
                    raise PostCanaryDatabaseError(
                        "SFTP controlled tables are absent from PostgreSQL"
                    )
                _validate_sftp_observed_timestamps(sftp_observed_timestamps, stage=str(sftp_stage))
        finally:
            transaction.rollback()

    workspace_identities = sorted(
        (
            {"slug": slug, "workspace_id_sha256": _sha([workspace_id])}
            for workspace_id, slug in workspace_slugs.items()
        ),
        key=lambda item: item["slug"],
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "postgresql_row_inventory",
        "profile": INVENTORY_PROFILE,
        "candidate_sha": candidate_sha,
        "deployment_id": deployment_id,
        "content_serialized": False,
        "detail_policy": "controlled-ledger-rows-and-navigation-workspace-aggregates-only",
        "table_count": len(tables),
        "tables": tables,
        "inventory_sha256": _inventory_sha256(
            tables=tables,
            workspace_identities=workspace_identities,
            ledger_binding=binding,
        ),
        "business_inventory_sha256": _sha(_business_projection(tables)),
        "workspace_identities": workspace_identities,
        "workspace_identities_sha256": _sha(workspace_identities),
        "ledger_binding": binding,
    }


def _read_json(path: str, *, label: str, maximum: int) -> tuple[dict[str, Any], bytes]:
    def reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise PostCanaryDatabaseError(f"{label} has duplicate JSON keys")
            result[key] = value
        return result

    def reject_constant(_value: str) -> None:
        raise PostCanaryDatabaseError(f"{label} contains an invalid number")

    try:
        with open(path, "rb") as handle:
            raw = handle.read(maximum + 1)
        if not raw or len(raw) > maximum:
            raise PostCanaryDatabaseError(f"{label} exceeds its bounded input contract")
        value = json.loads(
            raw,
            object_pairs_hook=reject_duplicate_pairs,
            parse_constant=reject_constant,
        )
    except PostCanaryDatabaseError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PostCanaryDatabaseError(f"{label} is unavailable or invalid") from exc
    if not isinstance(value, dict):
        raise PostCanaryDatabaseError(f"{label} must be a JSON object")
    return value, raw


def _read_private_sftp_ledger(path: str) -> tuple[dict[str, Any], bytes]:
    """Read one immutable, owner-only ledger without following symlinks."""

    pure = PurePath(path)
    if (
        not path
        or "\x00" in path
        or not pure.is_absolute()
        or os.path.normpath(path) != path
        or any(part in {"", ".", ".."} for part in pure.parts[1:])
    ):
        raise PostCanaryDatabaseError("SFTP ledger path is not canonical")
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    parent_descriptor = os.open("/", directory_flags)
    descriptor = -1
    try:
        for component in pure.parts[1:-1]:
            next_descriptor = os.open(
                component,
                directory_flags | nofollow,
                dir_fd=parent_descriptor,
            )
            os.close(parent_descriptor)
            parent_descriptor = next_descriptor
        before_path = os.stat(pure.name, dir_fd=parent_descriptor, follow_symlinks=False)
        descriptor = os.open(
            pure.name,
            os.O_RDONLY | os.O_CLOEXEC | nofollow,
            dir_fd=parent_descriptor,
        )
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.geteuid()
            or stat.S_IMODE(before.st_mode) not in {0o400, 0o600}
            or before.st_nlink != 1
            or not 0 < before.st_size <= MAX_SFTP_LEDGER_BYTES
        ):
            raise PostCanaryDatabaseError("SFTP ledger file is not private and stable")
        chunks: list[bytes] = []
        remaining = MAX_SFTP_LEDGER_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, min(65_536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        after = os.fstat(descriptor)
        after_path = os.stat(pure.name, dir_fd=parent_descriptor, follow_symlinks=False)

        def signature(value: os.stat_result) -> tuple[int, ...]:
            return (
                value.st_dev,
                value.st_ino,
                value.st_mode,
                value.st_uid,
                value.st_gid,
                value.st_nlink,
                value.st_size,
                value.st_mtime_ns,
                value.st_ctime_ns,
            )

        if (
            len(raw) != before.st_size
            or signature(before_path) != signature(before)
            or signature(before) != signature(after)
            or signature(after) != signature(after_path)
        ):
            raise PostCanaryDatabaseError("SFTP ledger changed while being read")
    except PostCanaryDatabaseError:
        raise
    except OSError as exc:
        raise PostCanaryDatabaseError("SFTP ledger is unavailable") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        os.close(parent_descriptor)
    ledger, parsed_raw = _strict_json_bytes(raw, label="SFTP ledger", maximum=MAX_SFTP_LEDGER_BYTES)
    canonical = _json_bytes(ledger) + b"\n"
    if parsed_raw != canonical:
        raise PostCanaryDatabaseError("SFTP ledger is not canonical JSON")
    return ledger, parsed_raw


def _strict_json_bytes(raw: bytes, *, label: str, maximum: int) -> tuple[dict[str, Any], bytes]:
    """Parse bounded JSON bytes with a closed duplicate-key policy."""

    def reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise PostCanaryDatabaseError(f"{label} has duplicate JSON keys")
            result[key] = value
        return result

    def reject_constant(_value: str) -> None:
        raise PostCanaryDatabaseError(f"{label} contains an invalid number")

    if not raw or len(raw) > maximum:
        raise PostCanaryDatabaseError(f"{label} exceeds its bounded input contract")
    try:
        value = json.loads(
            raw,
            object_pairs_hook=reject_duplicate_pairs,
            parse_constant=reject_constant,
        )
    except PostCanaryDatabaseError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise PostCanaryDatabaseError(f"{label} is unavailable or invalid") from exc
    if not isinstance(value, dict):
        raise PostCanaryDatabaseError(f"{label} must be a JSON object")
    return value, raw


def _load_json(path: str, *, label: str) -> dict[str, Any]:
    return _read_json(path, label=label, maximum=MAX_ARTIFACT_BYTES)[0]


def _parse_multiset(value: Any, *, label: str) -> dict[str, int]:
    if (
        not isinstance(value, dict)
        or set(value) != {"algorithm", "domains", "sums"}
        or value.get("algorithm") != ACCUMULATOR_ALGORITHM
        or value.get("domains") != ACCUMULATOR_DOMAINS
        or not isinstance(value.get("sums"), dict)
        or set(value["sums"]) != set(ACCUMULATOR_DOMAINS)
    ):
        raise PostCanaryDatabaseError(f"{label} multiset contract is invalid")
    result: dict[str, int] = {}
    for name in ACCUMULATOR_DOMAINS:
        encoded = value["sums"].get(name)
        if not isinstance(encoded, str) or SHA256_RE.fullmatch(encoded) is None:
            raise PostCanaryDatabaseError(f"{label} multiset sum is invalid")
        result[name] = int(encoded, 16)
    return result


def _aggregate(count: Any, multiset: Any, *, label: str) -> dict[str, Any]:
    if not isinstance(count, int) or isinstance(count, bool) or count < 0:
        raise PostCanaryDatabaseError(f"{label} row count is invalid")
    return {"count": count, "sums": _parse_multiset(multiset, label=label)}


def _zero_aggregate() -> dict[str, Any]:
    return {"count": 0, "sums": {name: 0 for name in ACCUMULATOR_DOMAINS}}


def _add_aggregates(*values: Mapping[str, Any]) -> dict[str, Any]:
    result = _zero_aggregate()
    for value in values:
        result["count"] += int(value["count"])
        for name in ACCUMULATOR_DOMAINS:
            result["sums"][name] = (
                result["sums"][name] + int(value["sums"][name])
            ) % ACCUMULATOR_MODULUS
    return result


def _subtract_aggregates(before: Mapping[str, Any], after: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "count": int(after["count"]) - int(before["count"]),
        "sums": {
            name: (int(after["sums"][name]) - int(before["sums"][name])) % ACCUMULATOR_MODULUS
            for name in ACCUMULATOR_DOMAINS
        },
    }


def _matches_delta(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    expected: Mapping[str, Any],
) -> bool:
    return _subtract_aggregates(before, after) == expected


def _controlled_rows(value: Any, *, label: str) -> dict[str, str]:
    if not isinstance(value, dict) or len(value) > MAX_CONTROLLED_INVOCATIONS + 1:
        raise PostCanaryDatabaseError(f"{label} controlled row details are invalid")
    result: dict[str, str] = {}
    for primary_key_hash, row_hash in value.items():
        if (
            not isinstance(primary_key_hash, str)
            or SHA256_RE.fullmatch(primary_key_hash) is None
            or not isinstance(row_hash, str)
            or SHA256_RE.fullmatch(row_hash) is None
        ):
            raise PostCanaryDatabaseError(f"{label} controlled row hash is invalid")
        result[primary_key_hash] = row_hash
    return result


def _controlled_sftp_audits(
    value: Any, *, label: str, controlled_rows: Mapping[str, str]
) -> dict[str, dict[str, str]]:
    if not isinstance(value, dict) or not set(value).issubset(
        {row[0] for row in SFTP_AUDIT_PHASES}
    ):
        raise PostCanaryDatabaseError(f"{label} SFTP audit details are invalid")
    result: dict[str, dict[str, str]] = {}
    for phase, row in value.items():
        if not isinstance(row, dict) or set(row) != {
            "primary_key_sha256",
            "row_sha256",
            "occurred_at",
        }:
            raise PostCanaryDatabaseError(f"{label} SFTP audit row is invalid")
        primary_key = _require_sha256(
            row.get("primary_key_sha256"), label=f"{label} SFTP audit primary key"
        )
        row_sha256 = _require_sha256(row.get("row_sha256"), label=f"{label} SFTP audit row")
        occurred_at = row.get("occurred_at")
        if (
            not isinstance(occurred_at, str)
            or not occurred_at.endswith("Z")
            or controlled_rows.get(primary_key) != row_sha256
        ):
            raise PostCanaryDatabaseError(f"{label} SFTP audit binding is invalid")
        try:
            parsed = datetime.fromisoformat(occurred_at.removesuffix("Z") + "+00:00")
        except ValueError as exc:
            raise PostCanaryDatabaseError(f"{label} SFTP audit timestamp is invalid") from exc
        if parsed.tzinfo != UTC or _utc_timestamp(parsed) != occurred_at:
            raise PostCanaryDatabaseError(f"{label} SFTP audit timestamp is invalid")
        result[str(phase)] = {
            "primary_key_sha256": primary_key,
            "row_sha256": row_sha256,
            "occurred_at": occurred_at,
        }
    if len({row["primary_key_sha256"] for row in result.values()}) != len(result):
        raise PostCanaryDatabaseError(f"{label} SFTP audit rows are duplicated")
    return result


def _controlled_sftp_link(
    value: Any, *, label: str, controlled_rows: Mapping[str, str]
) -> dict[str, str] | None:
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {
        "primary_key_sha256",
        "row_sha256",
        "invariant_sha256",
        "status",
    }:
        raise PostCanaryDatabaseError(f"{label} SFTP link detail is invalid")
    primary_key = _require_sha256(
        value.get("primary_key_sha256"), label=f"{label} SFTP link primary key"
    )
    row_sha256 = _require_sha256(value.get("row_sha256"), label=f"{label} SFTP link row")
    invariant_sha256 = _require_sha256(
        value.get("invariant_sha256"), label=f"{label} SFTP link invariant"
    )
    status = value.get("status")
    if status not in SFTP_STAGES or controlled_rows.get(primary_key) != row_sha256:
        raise PostCanaryDatabaseError(f"{label} SFTP link binding is invalid")
    return {
        "primary_key_sha256": primary_key,
        "row_sha256": row_sha256,
        "invariant_sha256": invariant_sha256,
        "status": str(status),
    }


def _navigation_aggregates(
    value: Any, *, label: str, workspace_hashes: set[str]
) -> dict[str, dict[str, Any]]:
    if not isinstance(value, dict):
        raise PostCanaryDatabaseError(f"{label} navigation aggregates are invalid")
    result: dict[str, dict[str, Any]] = {}
    for workspace_hash, aggregate in value.items():
        if (
            not isinstance(workspace_hash, str)
            or workspace_hash not in workspace_hashes
            or not isinstance(aggregate, dict)
            or set(aggregate) != {"row_count", "multiset"}
        ):
            raise PostCanaryDatabaseError(f"{label} navigation workspace aggregate is invalid")
        parsed = _aggregate(
            aggregate["row_count"],
            aggregate["multiset"],
            label=f"{label}.{workspace_hash[:12]}",
        )
        if parsed["count"] <= 0:
            raise PostCanaryDatabaseError(f"{label} contains an empty navigation aggregate")
        result[workspace_hash] = parsed
    return result


def _workspace_identities(inventory: Mapping[str, Any], *, label: str) -> dict[str, str]:
    raw = inventory.get("workspace_identities")
    if not isinstance(raw, list) or inventory.get("workspace_identities_sha256") != _sha(raw):
        raise PostCanaryDatabaseError(f"{label} workspace identities are invalid")
    result: dict[str, str] = {}
    hashes: set[str] = set()
    for row in raw:
        if not isinstance(row, dict) or set(row) != {
            "slug",
            "workspace_id_sha256",
        }:
            raise PostCanaryDatabaseError(f"{label} workspace identity row is invalid")
        slug = str(row["slug"])
        workspace_id_sha256 = str(row["workspace_id_sha256"])
        if (
            not slug
            or "@" in slug
            or SHA256_RE.fullmatch(workspace_id_sha256) is None
            or slug in result
            or workspace_id_sha256 in hashes
        ):
            raise PostCanaryDatabaseError(f"{label} workspace identity is ambiguous")
        result[slug] = workspace_id_sha256
        hashes.add(workspace_id_sha256)
    return result


def _validate_binding(value: Any, *, label: str) -> dict[str, Any]:
    expected_keys = {
        "provided",
        "ledger_sha256",
        "controlled_run_primary_key_sha256",
        "controlled_invocation_count",
        "controlled_invocation_primary_keys_sha256",
    }
    if not isinstance(value, dict) or set(value) != expected_keys:
        raise PostCanaryDatabaseError(f"{label} ledger binding is invalid")
    provided = value.get("provided")
    count = value.get("controlled_invocation_count")
    if not isinstance(provided, bool) or not isinstance(count, int) or isinstance(count, bool):
        raise PostCanaryDatabaseError(f"{label} ledger binding is invalid")
    if provided:
        if not 1 <= count <= MAX_CONTROLLED_INVOCATIONS or any(
            not isinstance(value.get(key), str) or SHA256_RE.fullmatch(value[key]) is None
            for key in (
                "ledger_sha256",
                "controlled_run_primary_key_sha256",
                "controlled_invocation_primary_keys_sha256",
            )
        ):
            raise PostCanaryDatabaseError(f"{label} ledger binding is invalid")
    elif count != 0 or any(
        value.get(key) is not None
        for key in (
            "ledger_sha256",
            "controlled_run_primary_key_sha256",
            "controlled_invocation_primary_keys_sha256",
        )
    ):
        raise PostCanaryDatabaseError(f"{label} ledger binding is invalid")
    return dict(value)


def _validate_inventory(
    inventory: Mapping[str, Any],
    *,
    label: str,
    candidate_sha: str,
    deployment_id: str,
) -> tuple[dict[str, dict[str, Any]], dict[str, str], dict[str, Any]]:
    expected_keys = {
        "schema_version",
        "kind",
        "profile",
        "candidate_sha",
        "deployment_id",
        "content_serialized",
        "detail_policy",
        "table_count",
        "tables",
        "inventory_sha256",
        "business_inventory_sha256",
        "workspace_identities",
        "workspace_identities_sha256",
        "ledger_binding",
    }
    tables = inventory.get("tables")
    if (
        set(inventory) != expected_keys
        or inventory.get("schema_version") != SCHEMA_VERSION
        or inventory.get("kind") != "postgresql_row_inventory"
        or inventory.get("profile") != INVENTORY_PROFILE
        or inventory.get("candidate_sha") != candidate_sha
        or inventory.get("deployment_id") != deployment_id
        or inventory.get("content_serialized") is not False
        or inventory.get("detail_policy")
        != "controlled-ledger-rows-and-navigation-workspace-aggregates-only"
        or not isinstance(tables, dict)
        or not tables
        or inventory.get("table_count") != len(tables)
        or not {"users", "runs", "skill_invocations", "audit_logs"}.issubset(tables)
    ):
        raise PostCanaryDatabaseError(f"{label} inventory contract is invalid")
    identities = _workspace_identities(inventory, label=label)
    binding = _validate_binding(inventory.get("ledger_binding"), label=label)
    if inventory.get("inventory_sha256") != _inventory_sha256(
        tables=tables,
        workspace_identities=inventory["workspace_identities"],
        ledger_binding=binding,
    ) or inventory.get("business_inventory_sha256") != _sha(_business_projection(tables)):
        raise PostCanaryDatabaseError(f"{label} inventory digest is invalid")

    workspace_hashes = set(identities.values())
    parsed: dict[str, dict[str, Any]] = {}
    table_keys = {
        "primary_key_columns",
        "row_count",
        "multiset",
        "normalization",
        "controlled_rows",
        "controlled_sftp_audits",
        "controlled_sftp_link",
        "canonical_navigation_by_workspace",
    }
    for table_name, table in tables.items():
        if (
            not isinstance(table_name, str)
            or SQL_IDENTIFIER_RE.fullmatch(table_name) is None
            or not isinstance(table, dict)
            or set(table) != table_keys
            or not isinstance(table.get("primary_key_columns"), list)
            or not table["primary_key_columns"]
            or any(
                not isinstance(column, str) or SQL_IDENTIFIER_RE.fullmatch(column) is None
                for column in table["primary_key_columns"]
            )
            or not isinstance(table.get("normalization"), list)
            or any(
                not isinstance(column, str) or SQL_IDENTIFIER_RE.fullmatch(column) is None
                for column in table["normalization"]
            )
        ):
            raise PostCanaryDatabaseError(f"{label} table contract is invalid: {table_name}")
        controlled = _controlled_rows(table["controlled_rows"], label=f"{label}.{table_name}")
        sftp_audits = _controlled_sftp_audits(
            table["controlled_sftp_audits"],
            label=f"{label}.{table_name}",
            controlled_rows=controlled,
        )
        sftp_link = _controlled_sftp_link(
            table["controlled_sftp_link"],
            label=f"{label}.{table_name}",
            controlled_rows=controlled,
        )
        navigation = _navigation_aggregates(
            table["canonical_navigation_by_workspace"],
            label=f"{label}.{table_name}",
            workspace_hashes=workspace_hashes,
        )
        if table_name != "audit_logs" and navigation:
            raise PostCanaryDatabaseError(f"{label} navigation aggregates escaped audit_logs")
        if table_name != "audit_logs" and sftp_audits:
            raise PostCanaryDatabaseError(f"{label} SFTP audit details escaped audit_logs")
        if table_name != "deposit_access_links" and sftp_link is not None:
            raise PostCanaryDatabaseError(f"{label} SFTP link detail escaped its table")
        parsed[table_name] = {
            "primary_key_columns": list(table["primary_key_columns"]),
            "normalization": list(table["normalization"]),
            "aggregate": _aggregate(
                table["row_count"],
                table["multiset"],
                label=f"{label}.{table_name}",
            ),
            "controlled_rows": controlled,
            "sftp_audits": sftp_audits,
            "sftp_link": sftp_link,
            "navigation": navigation,
        }
    return parsed, identities, binding


def _aggregate_controlled(rows: Mapping[str, str]) -> dict[str, Any]:
    accumulator = _MultisetAccumulator()
    for primary_key_hash, row_hash in rows.items():
        accumulator.add_hashes(primary_key_hash, row_hash)
    return {
        "count": accumulator.count,
        "sums": {name: accumulator.sums[name] for name in ACCUMULATOR_DOMAINS},
    }


def _navigation_delta(
    *,
    before: Mapping[str, Mapping[str, Any]],
    after: Mapping[str, Mapping[str, Any]],
    canary_workspace_hashes: set[str],
) -> tuple[dict[str, Any], bool, dict[str, int]]:
    expected = _zero_aggregate()
    valid = True
    counts: dict[str, int] = {}
    for workspace_hash in sorted(set(before) | set(after) | canary_workspace_hashes):
        old = before.get(workspace_hash, _zero_aggregate())
        new = after.get(workspace_hash, _zero_aggregate())
        if workspace_hash in canary_workspace_hashes:
            delta = _subtract_aggregates(old, new)
            counts[workspace_hash] = int(delta["count"])
            if delta["count"] <= 0:
                valid = False
            expected = _add_aggregates(expected, delta)
        elif old != new:
            valid = False
    return expected, valid, counts


def compare_inventory(
    *,
    baseline: Mapping[str, Any],
    post_canary: Mapping[str, Any],
    final: Mapping[str, Any],
    ledger: Mapping[str, Any],
    candidate_sha: str,
    deployment_id: str,
    ledger_sha256: str,
    baseline_file_sha256: str,
    post_canary_file_sha256: str,
    final_file_sha256: str,
    canary_workspace_ids: Sequence[str],
) -> dict[str, Any]:
    _identity(candidate_sha, deployment_id)
    for digest in (
        ledger_sha256,
        baseline_file_sha256,
        post_canary_file_sha256,
        final_file_sha256,
    ):
        if SHA256_RE.fullmatch(digest) is None:
            raise PostCanaryDatabaseError("comparison input digest is invalid")
    run_id, invocation_ids = _ledger_ids(
        ledger, candidate_sha=candidate_sha, deployment_id=deployment_id
    )
    expected_binding = _ledger_binding(
        run_id=run_id,
        invocation_ids=invocation_ids,
        ledger_sha256=ledger_sha256,
    )
    validated = {
        label: _validate_inventory(
            inventory,
            label=label,
            candidate_sha=candidate_sha,
            deployment_id=deployment_id,
        )
        for label, inventory in (
            ("baseline", baseline),
            ("post_canary", post_canary),
            ("final", final),
        )
    }
    baseline_tables, baseline_identities, baseline_binding = validated["baseline"]
    post_tables, post_identities, post_binding = validated["post_canary"]
    final_tables, final_identities, final_binding = validated["final"]
    if baseline_binding.get("provided") is not False:
        raise PostCanaryDatabaseError("baseline inventory must not contain ledger details")
    if post_binding != expected_binding or final_binding != expected_binding:
        raise PostCanaryDatabaseError("post-canary inventory ledger binding differs")
    if not (
        baseline_identities == post_identities == final_identities
        and set(baseline_tables) == set(post_tables) == set(final_tables)
    ):
        raise PostCanaryDatabaseError(
            "PostgreSQL table or workspace identity changed during canaries"
        )
    if any(table["controlled_rows"] for table in baseline_tables.values()):
        raise PostCanaryDatabaseError("baseline contains controlled row details")

    normalized_workspace_ids = sorted(set(map(str, canary_workspace_ids)))
    if len(normalized_workspace_ids) != 4 or any(
        UUID_RE.fullmatch(value) is None for value in normalized_workspace_ids
    ):
        raise PostCanaryDatabaseError("exactly four canonical canary workspace ids are required")
    requested_workspace_hashes = {_sha([value]) for value in normalized_workspace_ids}
    hash_to_slug = {workspace_hash: slug for slug, workspace_hash in baseline_identities.items()}
    try:
        canary_workspaces = sorted(
            (
                {
                    "slug": hash_to_slug[workspace_hash],
                    "workspace_id_sha256": workspace_hash,
                }
                for workspace_hash in requested_workspace_hashes
            ),
            key=lambda item: item["slug"],
        )
    except KeyError as exc:
        raise PostCanaryDatabaseError(
            "a canary workspace id is absent from the database inventory"
        ) from exc
    expected_controlled_keys = {
        "runs": {_sha([run_id])},
        "skill_invocations": {_sha([value]) for value in invocation_ids},
    }

    def compare_stage(
        label: str, current_tables: Mapping[str, Mapping[str, Any]]
    ) -> tuple[dict[str, Any], list[str], dict[str, int]]:
        results: dict[str, Any] = {}
        failed: list[str] = []
        additions: dict[str, int] = {}
        for table_name in sorted(baseline_tables):
            before = baseline_tables[table_name]
            after = current_tables[table_name]
            if (
                before["primary_key_columns"] != after["primary_key_columns"]
                or before["normalization"] != after["normalization"]
            ):
                raise PostCanaryDatabaseError(f"table contract changed: {table_name}")
            controlled = after["controlled_rows"]
            expected = _zero_aggregate()
            navigation_counts: dict[str, int] = {}
            exact = True
            if table_name in KEYCLOAK_VOLATILE_TABLES:
                if controlled or after["navigation"]:
                    raise PostCanaryDatabaseError(
                        f"volatile table carries forbidden details: {table_name}"
                    )
                result = "allowed_keycloak_session_or_event_volatility"
            else:
                if table_name in expected_controlled_keys:
                    if (
                        after["primary_key_columns"] != ["id"]
                        or set(controlled) != expected_controlled_keys[table_name]
                    ):
                        exact = False
                    expected = _aggregate_controlled(controlled)
                elif controlled:
                    raise PostCanaryDatabaseError(
                        f"controlled details escaped ledger tables: {table_name}"
                    )
                if table_name == "audit_logs":
                    expected, navigation_exact, navigation_counts = _navigation_delta(
                        before=before["navigation"],
                        after=after["navigation"],
                        canary_workspace_hashes=requested_workspace_hashes,
                    )
                    exact = exact and navigation_exact
                exact = exact and _matches_delta(before["aggregate"], after["aggregate"], expected)
                result = "passed" if exact else "failed"
                if not exact:
                    failed.append(table_name)
                elif expected["count"]:
                    additions[table_name] = int(expected["count"])
            results[table_name] = {
                "result": result,
                "before_count": int(before["aggregate"]["count"]),
                "after_count": int(after["aggregate"]["count"]),
                "observed_delta_count": int(after["aggregate"]["count"])
                - int(before["aggregate"]["count"]),
                "expected_delta_count": (
                    None if table_name in KEYCLOAK_VOLATILE_TABLES else int(expected["count"])
                ),
                "canonical_navigation_delta_counts": navigation_counts,
            }
        return results, failed, additions

    post_results, post_failed, post_additions = compare_stage("post_canary", post_tables)
    final_results, final_failed, final_additions = compare_stage("final", final_tables)
    failed = sorted(set(post_failed + final_failed))
    business_stable = post_canary["business_inventory_sha256"] == final["business_inventory_sha256"]
    if not business_stable:
        failed.append("post_to_final_business_inventory")
    additions_stable = post_additions == final_additions
    if not additions_stable:
        failed.append("post_to_final_expected_delta")
    expected_addition_tables = {"runs", "skill_invocations", "audit_logs"}
    nonvolatile_exact = not failed
    checks = {
        "schema_unchanged": True,
        "baseline_inventory_bound": True,
        "post_canary_inventory_bound": True,
        "final_inventory_bound": True,
        "preexisting_business_rows_preserved": nonvolatile_exact,
        "preexisting_business_rows_unmodified": nonvolatile_exact,
        "no_business_deletions": nonvolatile_exact,
        "users_only_last_login_normalized": (
            final_tables["users"]["normalization"] == ["last_login"]
            and final_results["users"]["result"] == "passed"
        ),
        "keycloak_volatility_limited": True,
        "controlled_run_addition_exact": (
            post_additions.get("runs") == final_additions.get("runs") == 1
        ),
        "controlled_invocations_addition_exact": (
            post_additions.get("skill_invocations")
            == final_additions.get("skill_invocations")
            == len(invocation_ids)
        ),
        "no_other_business_additions": (
            set(post_additions) == set(final_additions) == expected_addition_tables
        ),
        "navigation_audit_additions_canonical": (
            post_additions.get("audit_logs", 0) > 0
            and final_additions.get("audit_logs") == post_additions.get("audit_logs")
            and all(
                post_results["audit_logs"]["canonical_navigation_delta_counts"].get(workspace_hash)
                and final_results["audit_logs"]["canonical_navigation_delta_counts"].get(
                    workspace_hash
                )
                for workspace_hash in requested_workspace_hashes
            )
        ),
        "ledger_lineage_exact": True,
    }
    result = "passed" if not failed and all(checks.values()) else "failed"
    preexisting_rows = sum(
        int(table["aggregate"]["count"])
        for name, table in baseline_tables.items()
        if name not in KEYCLOAK_VOLATILE_TABLES
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "controlled_canary_database_comparison",
        "profile": COMPARISON_PROFILE,
        "sha": candidate_sha,
        "deployment_id": deployment_id,
        "result": result,
        "content_serialized": False,
        "checks": checks,
        "baseline_sha256": baseline_file_sha256,
        "post_canary_sha256": post_canary_file_sha256,
        "final_sha256": final_file_sha256,
        "baseline_business_sha256": baseline["business_inventory_sha256"],
        "post_canary_business_sha256": post_canary["business_inventory_sha256"],
        "final_business_sha256": final["business_inventory_sha256"],
        "controlled_run_primary_key_sha256": _sha([run_id]),
        "controlled_invocation_primary_keys_sha256": _sha(
            sorted(_sha([value]) for value in invocation_ids)
        ),
        "controlled_invocation_count": len(invocation_ids),
        "ledger_sha256": ledger_sha256,
        "canary_workspaces": canary_workspaces,
        "canary_workspaces_sha256": _sha(canary_workspaces),
        "failed_tables": sorted(set(failed)),
        "stages": {"post_canary": post_results, "final": final_results},
        "summary": {
            "table_count": len(baseline_tables),
            "preexisting_rows": preexisting_rows,
            "added_rows": sum(final_additions.values()),
            "added_rows_by_table": final_additions,
            "modified_preexisting_rows": 0 if result == "passed" else None,
            "deleted_preexisting_rows": 0 if result == "passed" else None,
            "normalized_columns": {"users": ["last_login"]},
            "volatile_tables": sorted(KEYCLOAK_VOLATILE_TABLES),
            "accumulator_algorithm": ACCUMULATOR_ALGORITHM,
            "accumulator_domains": dict(ACCUMULATOR_DOMAINS),
        },
    }


def _sha256_parts(domain: bytes, *values: str | bytes) -> str:
    digest = hashlib.sha256(domain)
    for value in values:
        digest.update(b"\x00")
        digest.update(value if isinstance(value, bytes) else value.encode("utf-8"))
    return digest.hexdigest()


def _release_a_identity_sha256(kind: str, value: str) -> str:
    return hashlib.sha256(
        f"agentium-release-a-sftp-{kind}-v1".encode("ascii") + b"\x00" + value.encode("utf-8")
    ).hexdigest()


def _release_a_ledger_binding(payload: Mapping[str, Any]) -> str:
    audits = payload["audits"]
    values = [
        str(payload[key])
        for key in (
            "live_sha",
            "release_a_sha",
            "sftp_sha",
            "deployment_id",
            "hostname_sha256",
            "workspace_id_sha256",
            "link_id_sha256",
            "access_id_sha256",
            "credential_fingerprint_sha256",
            "sftp_container_id",
            "sftp_image_id",
            "sftp_port",
            "runtime_identity_sha256",
            "link_status",
            "auth_failed_reason",
            "remaining_active_link_count",
            "active_sftp_session_count",
            "deposit_file_delta_count",
        )
    ]
    for name, _, _ in SFTP_AUDIT_PHASES:
        row = audits[name]
        values.extend(
            str(row[key])
            for key in (
                "event_type",
                "event_id_sha256",
                "event_digest_sha256",
                "count",
                "occurred_at",
            )
        )
    values.append(str(payload["collected_at"]))
    return _sha256_parts(b"agentium-release-a-sftp-ledger-v1", *values)


def compare_sftp_canary_inventory(
    *,
    baseline: Mapping[str, Any],
    post_canary: Mapping[str, Any],
    final: Mapping[str, Any],
    sftp_ledger: Mapping[str, Any],
    candidate_sha: str,
    deployment_id: str,
    sftp_ledger_sha256: str,
    baseline_file_sha256: str,
    post_canary_file_sha256: str,
    final_file_sha256: str,
) -> dict[str, Any]:
    """Prove and emit the exact Release A SFTP PostgreSQL ledger receipt."""

    _identity(candidate_sha, deployment_id)
    for digest in (
        sftp_ledger_sha256,
        baseline_file_sha256,
        post_canary_file_sha256,
        final_file_sha256,
    ):
        _require_sha256(digest, label="SFTP comparison input")
    ledger = _sftp_ledger_contract(
        sftp_ledger,
        candidate_sha=candidate_sha,
        deployment_id=deployment_id,
    )
    canonical_ledger = _json_bytes(ledger) + b"\n"
    if hashlib.sha256(canonical_ledger).hexdigest() != sftp_ledger_sha256:
        raise PostCanaryDatabaseError("SFTP ledger digest does not bind its contract")
    validated = {
        label: _validate_inventory(
            inventory,
            label=label,
            candidate_sha=candidate_sha,
            deployment_id=deployment_id,
        )
        for label, inventory in (
            ("baseline", baseline),
            ("post_canary", post_canary),
            ("final", final),
        )
    }
    baseline_tables, baseline_identities, baseline_binding = validated["baseline"]
    post_tables, post_identities, post_binding = validated["post_canary"]
    final_tables, final_identities, final_binding = validated["final"]
    if any(
        binding.get("provided") is not False
        for binding in (baseline_binding, post_binding, final_binding)
    ):
        raise PostCanaryDatabaseError(
            "SFTP inventory cannot contain controlled Chat ledger details"
        )
    if not (
        baseline_identities == post_identities == final_identities
        and set(baseline_tables) == set(post_tables) == set(final_tables)
    ):
        raise PostCanaryDatabaseError(
            "PostgreSQL table or workspace identity changed during SFTP canary"
        )
    required_tables = {"deposit_access_links", "deposit_files", "audit_logs"}
    if not required_tables.issubset(baseline_tables):
        raise PostCanaryDatabaseError("Secure Deposit tables are absent from inventory")
    if _sha([ledger["workspace_id"]]) not in set(baseline_identities.values()):
        raise PostCanaryDatabaseError("SFTP canary workspace is absent from the database inventory")
    if any(
        table["controlled_rows"] or table["sftp_audits"] or table["sftp_link"] is not None
        for table in baseline_tables.values()
    ):
        raise PostCanaryDatabaseError("SFTP baseline contains controlled row details")

    link_key = _sha([ledger["link_id"]])
    active_link = post_tables["deposit_access_links"]["controlled_rows"]
    revoked_link = final_tables["deposit_access_links"]["controlled_rows"]
    active_link_detail = post_tables["deposit_access_links"]["sftp_link"]
    revoked_link_detail = final_tables["deposit_access_links"]["sftp_link"]
    active_audits = post_tables["audit_logs"]["sftp_audits"]
    revoked_audits = final_tables["audit_logs"]["sftp_audits"]
    active_audit_rows = {
        row["primary_key_sha256"]: row["row_sha256"] for row in active_audits.values()
    }
    revoked_audit_rows = {
        row["primary_key_sha256"]: row["row_sha256"] for row in revoked_audits.values()
    }
    active_invariant = (
        active_link_detail.get("invariant_sha256") if isinstance(active_link_detail, dict) else None
    )
    revoked_invariant = (
        revoked_link_detail.get("invariant_sha256")
        if isinstance(revoked_link_detail, dict)
        else None
    )
    if (
        set(active_link) != {link_key}
        or set(revoked_link) != {link_key}
        or active_link[link_key] == revoked_link[link_key]
        or active_link_detail
        != {
            "primary_key_sha256": link_key,
            "row_sha256": active_link[link_key],
            "invariant_sha256": active_invariant,
            "status": "active",
        }
        or revoked_link_detail
        != {
            "primary_key_sha256": link_key,
            "row_sha256": revoked_link[link_key],
            "invariant_sha256": revoked_invariant,
            "status": "revoked",
        }
        or active_invariant != revoked_invariant
        or set(active_audits) != set(_sftp_expected_phases("active"))
        or set(revoked_audits) != set(_sftp_expected_phases("revoked"))
        or any(active_audits[name] != revoked_audits[name] for name in active_audits)
        or post_tables["audit_logs"]["controlled_rows"] != active_audit_rows
        or final_tables["audit_logs"]["controlled_rows"] != revoked_audit_rows
    ):
        raise PostCanaryDatabaseError("SFTP lifecycle controlled rows are not exact")

    expected_by_stage = {
        "active": {
            "deposit_access_links": active_link,
            "audit_logs": post_tables["audit_logs"]["controlled_rows"],
        },
        "revoked": {
            "deposit_access_links": revoked_link,
            "audit_logs": final_tables["audit_logs"]["controlled_rows"],
        },
    }
    for stage, tables in (("active", post_tables), ("revoked", final_tables)):
        for table_name in sorted(baseline_tables):
            before = baseline_tables[table_name]
            after = tables[table_name]
            if (
                before["primary_key_columns"] != after["primary_key_columns"]
                or before["normalization"] != after["normalization"]
            ):
                raise PostCanaryDatabaseError(f"table contract changed: {table_name}")
            allowed_rows = expected_by_stage[stage].get(table_name, {})
            if (
                after["controlled_rows"] != allowed_rows
                or not _matches_delta(
                    before["aggregate"],
                    after["aggregate"],
                    _aggregate_controlled(allowed_rows),
                )
                or before["navigation"] != after["navigation"]
                or (table_name != "audit_logs" and after["sftp_audits"])
                or (table_name != "deposit_access_links" and after["sftp_link"] is not None)
            ):
                raise PostCanaryDatabaseError(
                    f"unexpected SFTP canary database delta: {table_name}"
                )
    if (
        post_tables["deposit_files"]["aggregate"] != baseline_tables["deposit_files"]["aggregate"]
        or final_tables["deposit_files"]["aggregate"]
        != baseline_tables["deposit_files"]["aggregate"]
    ):
        raise PostCanaryDatabaseError("Secure Deposit file delta is not zero")

    audit_contract: dict[str, dict[str, Any]] = {}
    previous_time: datetime | None = None
    for name, event_type, _ in SFTP_AUDIT_PHASES:
        controlled = revoked_audits[name]
        occurred_at = str(controlled["occurred_at"])
        current_time = datetime.fromisoformat(occurred_at.removesuffix("Z") + "+00:00")
        if previous_time is not None and current_time < previous_time:
            raise PostCanaryDatabaseError("SFTP audit chronology is invalid")
        previous_time = current_time
        audit_contract[name] = {
            "event_type": event_type,
            "event_id_sha256": controlled["primary_key_sha256"],
            "event_digest_sha256": controlled["row_sha256"],
            "count": 1,
            "occurred_at": occurred_at,
        }
    collected_time = datetime.now(UTC)
    if (
        previous_time is None
        or collected_time < previous_time
        or (collected_time - previous_time).total_seconds() > MAX_SFTP_AUDIT_TO_RECEIPT_SECONDS
    ):
        raise PostCanaryDatabaseError("SFTP database lifecycle evidence is stale")
    collected_at = _utc_timestamp(collected_time)
    receipt: dict[str, Any] = {
        "schema_version": 1,
        "kind": SFTP_RECEIPT_KIND,
        "result": "passed",
        "live_sha": ledger["live_sha"],
        "release_a_sha": ledger["release_a_sha"],
        "sftp_sha": ledger["sftp_sha"],
        "deployment_id": deployment_id,
        "hostname_sha256": ledger["hostname_sha256"],
        "workspace_id_sha256": _release_a_identity_sha256("workspace-id", ledger["workspace_id"]),
        "link_id_sha256": _release_a_identity_sha256("link-id", ledger["link_id"]),
        "access_id_sha256": _release_a_identity_sha256("access-id", ledger["access_id"]),
        "credential_fingerprint_sha256": ledger["credential_fingerprint_sha256"],
        "sftp_container_id": ledger["sftp_container_id"],
        "sftp_image_id": ledger["sftp_image_id"],
        "sftp_port": ledger["sftp_port"],
        "runtime_identity_sha256": ledger["runtime_identity_sha256"],
        "link_status": "revoked",
        "auth_failed_reason": "inactive_or_expired",
        "remaining_active_link_count": 0,
        "active_sftp_session_count": ledger["active_sftp_session_count"],
        "deposit_file_delta_count": 0,
        "audits": audit_contract,
        "binding_sha256": "",
        "collected_at": collected_at,
    }
    receipt["binding_sha256"] = _release_a_ledger_binding(receipt)
    _canonical_sftp_receipt(receipt)
    return receipt


def _canonical_sftp_receipt(payload: Mapping[str, Any]) -> bytes:
    encoded = _json_bytes(payload) + b"\n"
    if len(encoded) > MAX_SFTP_RECEIPT_BYTES:
        raise PostCanaryDatabaseError("SFTP database receipt exceeds its size bound")
    return encoded


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("snapshot", "compare", "compare-sftp-canary"))
    parser.add_argument("--sha", required=True)
    parser.add_argument("--deployment-id", required=True)
    parser.add_argument("--baseline")
    parser.add_argument("--post-canary")
    parser.add_argument("--final")
    parser.add_argument("--ledger")
    parser.add_argument("--sftp-ledger")
    parser.add_argument("--sftp-stage", choices=sorted(SFTP_STAGES))
    parser.add_argument("--canary-workspace-id", action="append", default=[])
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "snapshot":
            ledger: dict[str, Any] | None = None
            ledger_sha256: str | None = None
            sftp_ledger: dict[str, Any] | None = None
            if args.ledger:
                ledger, ledger_bytes = _read_json(
                    args.ledger, label="ledger", maximum=MAX_LEDGER_BYTES
                )
                ledger_sha256 = hashlib.sha256(ledger_bytes).hexdigest()
            if args.sftp_ledger:
                sftp_ledger, _ = _read_private_sftp_ledger(args.sftp_ledger)
            payload = build_inventory(
                candidate_sha=args.sha,
                deployment_id=args.deployment_id,
                ledger=ledger,
                ledger_sha256=ledger_sha256,
                sftp_ledger=sftp_ledger,
                sftp_stage=args.sftp_stage,
            )
        elif args.command == "compare":
            if not args.baseline or not args.post_canary or not args.final or not args.ledger:
                raise PostCanaryDatabaseError(
                    "compare requires baseline, post-canary, final and ledger"
                )
            ledger, ledger_bytes = _read_json(args.ledger, label="ledger", maximum=MAX_LEDGER_BYTES)
            baseline, baseline_bytes = _read_json(
                args.baseline, label="baseline", maximum=MAX_ARTIFACT_BYTES
            )
            post_canary, post_canary_bytes = _read_json(
                args.post_canary,
                label="post-canary",
                maximum=MAX_ARTIFACT_BYTES,
            )
            final, final_bytes = _read_json(args.final, label="final", maximum=MAX_ARTIFACT_BYTES)
            payload = compare_inventory(
                baseline=baseline,
                post_canary=post_canary,
                final=final,
                ledger=ledger,
                candidate_sha=args.sha,
                deployment_id=args.deployment_id,
                ledger_sha256=hashlib.sha256(ledger_bytes).hexdigest(),
                baseline_file_sha256=hashlib.sha256(baseline_bytes).hexdigest(),
                post_canary_file_sha256=hashlib.sha256(post_canary_bytes).hexdigest(),
                final_file_sha256=hashlib.sha256(final_bytes).hexdigest(),
                canary_workspace_ids=args.canary_workspace_id,
            )
        else:
            if not args.baseline or not args.post_canary or not args.final or not args.sftp_ledger:
                raise PostCanaryDatabaseError(
                    "compare-sftp-canary requires baseline, post-canary, final " "and sftp-ledger"
                )
            sftp_ledger, sftp_ledger_bytes = _read_private_sftp_ledger(args.sftp_ledger)
            baseline, baseline_bytes = _read_json(
                args.baseline, label="baseline", maximum=MAX_ARTIFACT_BYTES
            )
            post_canary, post_canary_bytes = _read_json(
                args.post_canary,
                label="post-canary",
                maximum=MAX_ARTIFACT_BYTES,
            )
            final, final_bytes = _read_json(args.final, label="final", maximum=MAX_ARTIFACT_BYTES)
            payload = compare_sftp_canary_inventory(
                baseline=baseline,
                post_canary=post_canary,
                final=final,
                sftp_ledger=sftp_ledger,
                candidate_sha=args.sha,
                deployment_id=args.deployment_id,
                sftp_ledger_sha256=hashlib.sha256(sftp_ledger_bytes).hexdigest(),
                baseline_file_sha256=hashlib.sha256(baseline_bytes).hexdigest(),
                post_canary_file_sha256=hashlib.sha256(post_canary_bytes).hexdigest(),
                final_file_sha256=hashlib.sha256(final_bytes).hexdigest(),
            )
        if args.command == "compare-sftp-canary":
            sys.stdout.buffer.write(_canonical_sftp_receipt(payload))
        else:
            print(json.dumps(payload, indent=2, sort_keys=True) + "\n", end="")
        return 0 if payload.get("result", "passed") == "passed" else 1
    except PostCanaryDatabaseError as exc:
        print(f"Post-canary database audit failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
