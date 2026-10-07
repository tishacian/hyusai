#!/usr/bin/env python3
"""Freeze and verify the private runtime environment used by a VM deployment.

The bundle is a reboot-safe transaction input.  Source paths and environment
values are never written to its manifest or standard output.  After capture,
all deployment processes consume only the copied files under the bundle.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit


SCHEMA_VERSION = 3
PROFILE = "agentium-runtime-env-bundle-v3"
MAX_SOURCE_BYTES = 1024 * 1024
MAX_VM_INSPECT_BYTES = 16 * 1024 * 1024
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
DEPLOYMENT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{5,95}$")
KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
REFERENCE_KEYS = {
    "application": "AGENTIUM_ENV_FILE",
    "qdrant": "AGENTIUM_QDRANT_ENV_FILE",
    "keycloak": "AGENTIUM_KEYCLOAK_ENV_FILE",
}
ROLES = frozenset({"compose_main", "application", "qdrant", "keycloak", "systemd"})
SENSITIVE_KEY_RE = re.compile(
    r"(?:PASSWORD|PASSWD|SECRET|TOKEN|API_KEY|PRIVATE_KEY|CREDENTIAL)$"
)
PLACEHOLDER_VALUES = frozenset(
    {
        "admin",
        "change-me",
        "change_me",
        "changeme",
        "default",
        "dev-key",
        "dev_key",
        "devkey",
        "example",
        "guest",
        "minioadmin",
        "password",
        "secret",
    }
)
VM_STORAGE_ENVIRONMENT = {
    "AGENTIUM_MINIO_VOLUME": "agentium_minio_block",
    "AGENTIUM_MINIO_VOLUME_EXTERNAL": "true",
    "AGENTIUM_QDRANT_VOLUME": "agentium_qdrant_block",
    "AGENTIUM_QDRANT_SNAPSHOT_PATH": "/srv/agentium-data/qdrant-snapshots",
}
VM_APPLICATION_STORAGE_ENVIRONMENT = {
    "AGENTIUM_FAISS_PATH": "/home/ubuntu/omnirag/backend/faiss_db",
    "AGENTIUM_OBJECT_STORE_PATH": "/srv/agentium-data/object_store",
    "AGENTIUM_RECIPE_ENVS_PATH": "/srv/agentium-data/recipe_envs",
    "AGENTIUM_SECURE_DEPOSIT_PATH": (
        "/home/ubuntu/omnirag/backend/data/secure_deposit"
    ),
}
VM_APPLICATION_STORAGE_MOUNTS = {
    "agentium-migrate": {
        "/data/object_store": ("AGENTIUM_OBJECT_STORE_PATH", True),
        "/data/secure_deposit": ("AGENTIUM_SECURE_DEPOSIT_PATH", True),
        "/data/faiss_db": ("AGENTIUM_FAISS_PATH", True),
    },
    "agentium-backend": {
        "/data/object_store": ("AGENTIUM_OBJECT_STORE_PATH", False),
        "/data/secure_deposit": ("AGENTIUM_SECURE_DEPOSIT_PATH", False),
        "/data/faiss_db": ("AGENTIUM_FAISS_PATH", False),
    },
    "agentium-worker-cpu": {
        "/data/object_store": ("AGENTIUM_OBJECT_STORE_PATH", False),
        "/data/secure_deposit": ("AGENTIUM_SECURE_DEPOSIT_PATH", True),
        "/data/faiss_db": ("AGENTIUM_FAISS_PATH", False),
        "/data/recipe_envs": ("AGENTIUM_RECIPE_ENVS_PATH", False),
    },
    "agentium-p4-maintenance": {
        "/data/object_store": ("AGENTIUM_OBJECT_STORE_PATH", False),
        "/data/secure_deposit": ("AGENTIUM_SECURE_DEPOSIT_PATH", True),
        "/data/faiss_db": ("AGENTIUM_FAISS_PATH", False),
    },
    "agentium-sftp": {
        "/data/secure_deposit": ("AGENTIUM_SECURE_DEPOSIT_PATH", False),
    },
}
VM_BIND_BACKED_VOLUMES = {
    "agentium_minio_block": "/srv/agentium-data/minio",
    "agentium_qdrant_block": "/srv/agentium-data/qdrant",
}
# Same image and protected mounts; separate pool for children awaited by Flows.
VM_APPLICATION_STORAGE_MOUNTS["agentium-worker-recipes"] = dict(
    VM_APPLICATION_STORAGE_MOUNTS["agentium-worker-cpu"]
)
# The forecasting workers (profile ml-ts): they read training datasets and write
# model directories, so they need the object store and nothing else — no
# secure deposit, no FAISS index, no recipe venvs.
for _ml_ts_service in ("agentium-worker-ml-ts", "agentium-worker-ml-ts-serve"):
    VM_APPLICATION_STORAGE_MOUNTS[_ml_ts_service] = {
        "/data/object_store": ("AGENTIUM_OBJECT_STORE_PATH", False),
    }
# Services that only exist when an opt-in Compose profile is active. Absent
# from a rendering without the profile and from a host that never enabled it,
# they are skipped; present, they are held to their contract like any other.
VM_OPTIONAL_PROFILE_SERVICES = frozenset({"agentium-worker-ml-ts", "agentium-worker-ml-ts-serve"})

# Targets added to the contract after their service already ran in
# production. The pre-mutation gate inspects the PREVIOUS container
# generation, which legitimately predates the bind; it may be absent on the
# running container but, when present, must match the contract exactly. The
# rendered-compose check still requires the bind unconditionally, so every
# generation created through the deploy script carries it. Remove an entry
# once no pre-contract generation can still be running.
VM_RUNTIME_TRANSITIONAL_TARGETS = {
    ("agentium-worker-cpu", "/data/recipe_envs"),
}
VM_DOCKER_VOLUME_ROOT = "/var/lib/docker/volumes"


class RuntimeEnvBundleError(RuntimeError):
    """Raised when a runtime environment cannot be frozen unambiguously."""


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_path(value: Path) -> str:
    return hashlib.sha256(os.fsencode(value)).hexdigest()


def _identity(candidate_sha: str, deployment_id: str) -> None:
    if SHA_RE.fullmatch(candidate_sha) is None:
        raise RuntimeEnvBundleError("candidate SHA is invalid")
    if DEPLOYMENT_ID_RE.fullmatch(deployment_id) is None:
        raise RuntimeEnvBundleError("deployment-id is invalid")


def _parse_dotenv(content: bytes, *, label: str) -> tuple[dict[str, str], list[str]]:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RuntimeEnvBundleError(f"{label} is not UTF-8") from exc
    values: dict[str, str] = {}
    ordered_keys: list[str] = []
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("export "):
            stripped = stripped[7:].lstrip()
        key, separator, raw_value = stripped.partition("=")
        key = key.strip()
        if not separator or KEY_RE.fullmatch(key) is None:
            raise RuntimeEnvBundleError(
                f"{label} has an unsupported entry at line {line_number}"
            )
        if key in values:
            raise RuntimeEnvBundleError(f"{label} contains a duplicate key")
        value = raw_value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
        ordered_keys.append(key)
    return values, ordered_keys


def _assert_canonical_source_path(path: Path, *, label: str) -> None:
    absolute = path.absolute()
    try:
        canonical = Path(os.path.realpath(absolute, strict=True))
    except OSError as exc:
        raise RuntimeEnvBundleError(f"{label} has an unavailable parent") from exc
    if canonical != absolute:
        raise RuntimeEnvBundleError(f"{label} path or parent is not canonical")


def _assert_private_source(
    details: os.stat_result, *, label: str, source_owner_uid: int
) -> None:
    if details.st_uid not in {0, source_owner_uid}:
        raise RuntimeEnvBundleError(f"{label} owner is not root or the deploy owner")
    if stat.S_IMODE(details.st_mode) not in {0o400, 0o600}:
        raise RuntimeEnvBundleError(f"{label} mode must be 0400 or 0600")
    if details.st_size > MAX_SOURCE_BYTES:
        raise RuntimeEnvBundleError(f"{label} exceeds the maximum size")


def _read_regular_file(
    path: Path,
    *,
    label: str,
    source_owner_uid: int | None = None,
) -> tuple[bytes, os.stat_result]:
    if source_owner_uid is not None:
        _assert_canonical_source_path(path, label=label)
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise RuntimeEnvBundleError(f"{label} is unavailable or unsafe") from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise RuntimeEnvBundleError(f"{label} is not a regular file")
        if before.st_nlink != 1:
            raise RuntimeEnvBundleError(f"{label} must not be hard-linked")
        if source_owner_uid is not None:
            _assert_private_source(
                before, label=label, source_owner_uid=source_owner_uid
            )
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    identity_before = (
        before.st_dev,
        before.st_ino,
        before.st_mode,
        before.st_uid,
        before.st_gid,
        before.st_nlink,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
    )
    identity_after = (
        after.st_dev,
        after.st_ino,
        after.st_mode,
        after.st_uid,
        after.st_gid,
        after.st_nlink,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    )
    if identity_before != identity_after:
        raise RuntimeEnvBundleError(f"{label} changed while being captured")
    content = b"".join(chunks)
    if len(content) != after.st_size:
        raise RuntimeEnvBundleError(f"{label} was read incompletely")
    return content, after


def _file_identity(details: os.stat_result) -> tuple[int, ...]:
    return (
        int(details.st_dev),
        int(details.st_ino),
        int(details.st_mode),
        int(details.st_uid),
        int(details.st_gid),
        int(details.st_nlink),
        int(details.st_size),
        int(details.st_mtime_ns),
        int(details.st_ctime_ns),
    )


def _parse_role_contents(contents: Mapping[str, bytes]) -> dict[str, dict[str, str]]:
    if set(contents) != ROLES:
        raise RuntimeEnvBundleError("runtime environment role contents are incomplete")
    return {
        role: _parse_dotenv(content, label=f"{role} environment")[0]
        for role, content in contents.items()
    }


def _assert_storage_environment(
    content: bytes, *, expected: Mapping[str, str], contract: str
) -> None:
    """Require literal storage identities without emitting their values."""

    values, _ = _parse_dotenv(content, label="VM Compose environment")
    if any(values.get(key) != value for key, value in expected.items()):
        raise RuntimeEnvBundleError(
            f"VM production storage environment differs from the {contract} contract"
        )


def assert_vm_storage_environment(content: bytes) -> None:
    """Require every literal VM storage identity before a deployment command."""

    _assert_storage_environment(
        content,
        expected=VM_STORAGE_ENVIRONMENT | VM_APPLICATION_STORAGE_ENVIRONMENT,
        contract="protected storage",
    )


def assert_vm_block_storage_environment(content: bytes) -> None:
    """Require block-volume identities in a portable production env bundle."""

    _assert_storage_environment(
        content, expected=VM_STORAGE_ENVIRONMENT, contract="block-backed storage"
    )


def _rendered_service_mounts(compose: Mapping[str, Any], service_name: str) -> dict[str, Any]:
    services = compose.get("services")
    if not isinstance(services, dict) or not isinstance(services.get(service_name), dict):
        raise RuntimeEnvBundleError("rendered VM Compose storage services are incomplete")
    mounts = services[service_name].get("volumes")
    if not isinstance(mounts, list):
        raise RuntimeEnvBundleError("rendered VM Compose storage mounts are invalid")
    result: dict[str, Any] = {}
    for mount in mounts:
        if not isinstance(mount, dict) or not isinstance(mount.get("target"), str):
            raise RuntimeEnvBundleError("rendered VM Compose storage mounts are invalid")
        target = mount["target"]
        if target in result:
            raise RuntimeEnvBundleError("rendered VM Compose storage target is duplicated")
        result[target] = mount
    return result


def assert_vm_compose_storage(compose: Any) -> None:
    """Check the rendered VM model before any Compose state-changing command."""

    if not isinstance(compose, dict) or not isinstance(compose.get("volumes"), dict):
        raise RuntimeEnvBundleError("rendered VM Compose model is invalid")
    volumes = compose["volumes"]
    expected_volume_mounts = {
        ("agentium-minio", "/data"): ("agentium_minio_block",),
        ("agentium-qdrant", "/qdrant/storage"): ("agentium_qdrant_block",),
    }
    mounts_by_service = {
        service: _rendered_service_mounts(compose, service)
        for service in {service for service, _ in expected_volume_mounts}
    }
    if set(mounts_by_service["agentium-minio"]) != {"/data"} or set(
        mounts_by_service["agentium-qdrant"]
    ) != {"/qdrant/storage", "/qdrant/snapshots"}:
        raise RuntimeEnvBundleError("rendered VM stateful mount targets differ")
    for (service, target), (expected_name,) in expected_volume_mounts.items():
        mount = mounts_by_service[service][target]
        logical_name = mount.get("source")
        definition = volumes.get(logical_name) if isinstance(logical_name, str) else None
        if (
            mount.get("type") != "volume"
            or mount.get("read_only", False) is not False
            or not isinstance(definition, dict)
            or definition.get("name") != expected_name
            or definition.get("external") is not True
        ):
            raise RuntimeEnvBundleError("rendered VM bind-backed volume contract differs")
    snapshot = mounts_by_service["agentium-qdrant"]["/qdrant/snapshots"]
    if (
        snapshot.get("type") != "bind"
        or snapshot.get("source") != VM_STORAGE_ENVIRONMENT["AGENTIUM_QDRANT_SNAPSHOT_PATH"]
        or snapshot.get("read_only", False) is not False
    ):
        raise RuntimeEnvBundleError("rendered VM Qdrant snapshot bind differs")

    protected_sources = {
        VM_APPLICATION_STORAGE_ENVIRONMENT[environment_key]
        for required in VM_APPLICATION_STORAGE_MOUNTS.values()
        for environment_key, _ in required.values()
    }
    protected_targets = {
        target
        for required in VM_APPLICATION_STORAGE_MOUNTS.values()
        for target in required
    }
    observed: set[tuple[str, str]] = set()
    services = compose["services"]
    for service_name, required in VM_APPLICATION_STORAGE_MOUNTS.items():
        if service_name in VM_OPTIONAL_PROFILE_SERVICES and service_name not in services:
            continue
        mounts = _rendered_service_mounts(compose, service_name)
        for target, (environment_key, must_be_read_only) in required.items():
            mount = mounts.get(target)
            if not isinstance(mount, dict):
                raise RuntimeEnvBundleError(
                    "rendered VM protected storage mount inventory is incomplete"
                )
            if (
                mount.get("type") != "bind"
                or mount.get("source")
                != VM_APPLICATION_STORAGE_ENVIRONMENT[environment_key]
                or mount.get("read_only", False) is not must_be_read_only
            ):
                raise RuntimeEnvBundleError(
                    "rendered VM protected storage source or access mode differs"
                )
            observed.add((service_name, target))
    for service_name, service in services.items():
        if not isinstance(service, dict):
            raise RuntimeEnvBundleError("rendered VM Compose storage services are invalid")
        mounts = service.get("volumes", [])
        if not isinstance(mounts, list):
            raise RuntimeEnvBundleError("rendered VM Compose storage mounts are invalid")
        for mount in mounts:
            if not isinstance(mount, dict):
                raise RuntimeEnvBundleError("rendered VM Compose storage mounts are invalid")
            source = mount.get("source")
            target = mount.get("target")
            if source not in protected_sources and target not in protected_targets:
                continue
            if (service_name, target) not in observed:
                raise RuntimeEnvBundleError(
                    "rendered VM protected storage is mounted outside the approved boundary"
                )


def assert_vm_volume_inspect(payload: Any, *, volume_name: str) -> None:
    """Validate one existing Docker local volume without creating it."""

    expected_device = VM_BIND_BACKED_VOLUMES.get(volume_name)
    if expected_device is None:
        raise RuntimeEnvBundleError("VM storage volume name is invalid")
    if not isinstance(payload, list) or len(payload) != 1 or not isinstance(payload[0], dict):
        raise RuntimeEnvBundleError("VM storage volume is missing or ambiguous")
    volume = payload[0]
    expected_mountpoint = f"{VM_DOCKER_VOLUME_ROOT}/{volume_name}/_data"
    if (
        volume.get("Name") != volume_name
        or volume.get("Driver") != "local"
        or volume.get("Mountpoint") != expected_mountpoint
        or volume.get("Options")
        != {"device": expected_device, "o": "bind", "type": "none"}
    ):
        raise RuntimeEnvBundleError("VM storage volume bind options differ")


def assert_vm_active_storage_mounts(payload: Any) -> None:
    """Require running stateful/application containers to use protected stores."""

    expected_container_names = {
        "agentium-minio",
        "qdrant",
    } | (set(VM_APPLICATION_STORAGE_MOUNTS) - {"agentium-migrate"})
    # The pre-switch inventory can still be from the release before this worker.
    if isinstance(payload, list) and not any(
        isinstance(row, dict) and row.get("Name") == "/agentium-worker-recipes"
        for row in payload
    ):
        expected_container_names.discard("agentium-worker-recipes")
    # An opt-in profile's containers are inspected only where they exist.
    present = {
        row.get("Name") for row in payload if isinstance(row, dict)
    } if isinstance(payload, list) else set()
    for optional in VM_OPTIONAL_PROFILE_SERVICES:
        if f"/{optional}" not in present:
            expected_container_names.discard(optional)
    if not isinstance(payload, list) or len(payload) != len(expected_container_names):
        raise RuntimeEnvBundleError("VM storage containers are missing or ambiguous")
    containers: dict[str, Mapping[str, Any]] = {}
    for container in payload:
        if not isinstance(container, dict) or not isinstance(container.get("Name"), str):
            raise RuntimeEnvBundleError("VM storage container inspection is invalid")
        name = container["Name"].removeprefix("/")
        if name in containers:
            raise RuntimeEnvBundleError("VM storage container inspection is duplicated")
        containers[name] = container
    if set(containers) != expected_container_names:
        raise RuntimeEnvBundleError("VM storage container identity differs")
    expected = {
        "agentium-minio": {
            "/data": ("volume", "agentium_minio_block", None, True),
        },
        "qdrant": {
            "/qdrant/storage": ("volume", "agentium_qdrant_block", None, True),
            "/qdrant/snapshots": (
                "bind",
                None,
                VM_STORAGE_ENVIRONMENT["AGENTIUM_QDRANT_SNAPSHOT_PATH"],
                True,
            ),
        },
    }
    for service_name, required in VM_APPLICATION_STORAGE_MOUNTS.items():
        if service_name == "agentium-migrate" or service_name not in expected_container_names:
            continue
        expected[service_name] = {
            target: (
                "bind",
                None,
                VM_APPLICATION_STORAGE_ENVIRONMENT[environment_key],
                not read_only,
            )
            for target, (environment_key, read_only) in required.items()
        }
    for name, required in expected.items():
        container = containers[name]
        state = container.get("State")
        mounts = container.get("Mounts")
        if not isinstance(state, dict) or state.get("Running") is not True:
            raise RuntimeEnvBundleError("VM storage container is not running")
        if not isinstance(mounts, list):
            raise RuntimeEnvBundleError("VM storage container mounts are invalid")
        by_target = {
            row.get("Destination"): row
            for row in mounts
            if isinstance(row, dict) and isinstance(row.get("Destination"), str)
        }
        applicable = {
            target: contract
            for target, contract in required.items()
            if (name, target) not in VM_RUNTIME_TRANSITIONAL_TARGETS
            or target in by_target
        }
        if len(by_target) != len(mounts) or set(by_target) != set(applicable):
            raise RuntimeEnvBundleError("VM active storage mount targets differ")
        for target, (kind, volume_name, source, read_write) in applicable.items():
            row = by_target[target]
            if (
                row.get("Type") != kind
                or row.get("RW") is not read_write
                or (volume_name is not None and row.get("Name") != volume_name)
                or (source is not None and row.get("Source") != source)
            ):
                raise RuntimeEnvBundleError("VM active storage mount identity differs")


def _read_json_stdin(*, label: str) -> Any:
    payload = sys.stdin.buffer.read(MAX_VM_INSPECT_BYTES + 1)
    if len(payload) > MAX_VM_INSPECT_BYTES:
        raise RuntimeEnvBundleError(f"{label} exceeds the size limit")
    try:
        return json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeEnvBundleError(f"{label} is invalid JSON") from exc


def _assert_no_placeholder_secrets(contents: Mapping[str, bytes]) -> None:
    for values in _parse_role_contents(contents).values():
        for key, value in values.items():
            normalized = value.strip().strip("'\"").lower()
            if SENSITIVE_KEY_RE.search(key.upper()) and (
                normalized in PLACEHOLDER_VALUES
                or normalized.startswith(("change-me-", "changeme-", "example-"))
            ):
                raise RuntimeEnvBundleError(
                    "runtime environment contains a placeholder secret"
                )


def _is_placeholder(value: str) -> bool:
    normalized = value.strip().strip("'\"").lower()
    return normalized in PLACEHOLDER_VALUES or normalized.startswith(
        ("change-me-", "changeme-", "example-")
    )


def _assert_literal_credential(value: str) -> None:
    if any(token in value for token in ("$", "`", "\x00", "\r", "\n")):
        raise RuntimeEnvBundleError(
            "runtime credential must be a literal, non-expanding value"
        )


def _assert_credential_url(value: str, *, schemes: frozenset[str]) -> None:
    _assert_literal_credential(value)
    try:
        parsed = urlsplit(value)
        username = unquote(parsed.username or "")
        password = unquote(parsed.password or "")
    except ValueError as exc:
        raise RuntimeEnvBundleError("runtime credential URL is invalid") from exc
    if (
        parsed.scheme not in schemes
        or not parsed.hostname
        or not username
        or not password
        or parsed.query
        or parsed.fragment
        or _is_placeholder(username)
        or _is_placeholder(password)
    ):
        raise RuntimeEnvBundleError(
            "runtime credential URL is incomplete or contains a placeholder"
        )


def _assert_production_contract(contents: Mapping[str, bytes]) -> None:
    values = _parse_role_contents(contents)
    required = {
        "compose_main": {
            "AGENTIUM_FAISS_PATH",
            "AGENTIUM_MINIO_VOLUME",
            "AGENTIUM_MINIO_VOLUME_EXTERNAL",
            "AGENTIUM_OBJECT_STORE_PATH",
            "AGENTIUM_QDRANT_SNAPSHOT_PATH",
            "AGENTIUM_QDRANT_VOLUME",
            "AGENTIUM_RABBITMQ_USER",
            "AGENTIUM_RABBITMQ_PASSWORD",
            "AGENTIUM_SECURE_DEPOSIT_PATH",
            "AGENTIUM_POSTGRES_PASSWORD",
            "AGENTIUM_MINIO_ROOT_USER",
            "AGENTIUM_MINIO_ROOT_PASSWORD",
            "AGENTIUM_MINIO_BUCKET",
            "AGENTIUM_POSTGRES_DB",
            "LIVEKIT_API_KEY",
            "LIVEKIT_API_SECRET",
            "AGENTIUM_POSTGRES_USER",
        },
        "application": {
            "DATABASE_URL",
            "CELERY_BROKER_URL",
            "FAISS_PERSIST_DIRECTORY",
            "OBJECT_STORE_BACKEND",
            "OBJECT_STORE_BASE_PATH",
            "OBJECT_STORE_S3_ACCESS_KEY",
            "OBJECT_STORE_S3_BUCKET",
            "OBJECT_STORE_S3_ENDPOINT_URL",
            "OBJECT_STORE_S3_SECRET_KEY",
            "QDRANT_API_KEY",
            "QDRANT_HOST",
            "QDRANT_HTTPS",
            "QDRANT_PORT",
            "SECURE_DEPOSIT_SFTP_HOST_KEY_PATH",
            "SECURE_DEPOSIT_SFTP_TEMP_DIR",
            "SECURE_DEPOSIT_STORAGE_DIR",
        },
        "qdrant": {
            "QDRANT__SERVICE__API_KEY",
            "QDRANT__SERVICE__READ_ONLY_API_KEY",
        },
        "keycloak": {
            "KC_DB",
            "KC_DB_PASSWORD",
            "KC_DB_URL",
            "KC_DB_USERNAME",
        },
        "systemd": {
            "CELERY_BROKER_URL",
            "DATABASE_URL",
            "FAISS_PERSIST_DIRECTORY",
            "OBJECT_STORE_BACKEND",
            "OBJECT_STORE_BASE_PATH",
            "OBJECT_STORE_S3_ACCESS_KEY",
            "OBJECT_STORE_S3_BUCKET",
            "OBJECT_STORE_S3_ENDPOINT_URL",
            "OBJECT_STORE_S3_SECRET_KEY",
            "QDRANT_API_KEY",
            "QDRANT_HOST",
            "QDRANT_HTTPS",
            "QDRANT_PORT",
            "SECURE_DEPOSIT_STORAGE_DIR",
        },
    }
    for role, keys in required.items():
        if any(
            not values[role].get(key, "").strip() or _is_placeholder(values[role][key])
            for key in keys
        ):
            raise RuntimeEnvBundleError(
                "runtime environment lacks an explicit production credential"
            )
        for key in keys:
            _assert_literal_credential(values[role][key])
    assert_vm_block_storage_environment(contents["compose_main"])
    _assert_credential_url(
        values["application"]["DATABASE_URL"],
        schemes=frozenset({"postgres", "postgresql", "postgresql+psycopg"}),
    )
    _assert_credential_url(
        values["systemd"]["DATABASE_URL"],
        schemes=frozenset({"postgres", "postgresql", "postgresql+psycopg"}),
    )
    _assert_credential_url(
        values["application"]["CELERY_BROKER_URL"],
        schemes=frozenset({"amqp", "amqps"}),
    )
    _assert_credential_url(
        values["systemd"]["CELERY_BROKER_URL"],
        schemes=frozenset({"amqp", "amqps"}),
    )
    postgres_database = values["compose_main"]["AGENTIUM_POSTGRES_DB"]
    postgres_user = values["compose_main"]["AGENTIUM_POSTGRES_USER"]
    if (
        re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", postgres_database) is None
        or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", postgres_user) is None
    ):
        raise RuntimeEnvBundleError("PostgreSQL runtime identity is invalid")
    application_database = urlsplit(values["application"]["DATABASE_URL"])
    systemd_database = urlsplit(values["systemd"]["DATABASE_URL"])
    if (
        unquote(application_database.username or "") != postgres_user
        or unquote(application_database.password or "")
        != values["compose_main"]["AGENTIUM_POSTGRES_PASSWORD"]
        or application_database.hostname != "agentium-pg"
        or (application_database.port or 5432) != 5432
        or application_database.path != f"/{postgres_database}"
        or unquote(systemd_database.username or "") != postgres_user
        or unquote(systemd_database.password or "")
        != values["compose_main"]["AGENTIUM_POSTGRES_PASSWORD"]
        or systemd_database.hostname not in {"127.0.0.1", "localhost"}
        or (systemd_database.port or 5432) != 5432
        or systemd_database.path != f"/{postgres_database}"
    ):
        raise RuntimeEnvBundleError(
            "application databases are not bound to the backed-up PostgreSQL runtime"
        )
    celery = urlsplit(values["application"]["CELERY_BROKER_URL"])
    if (
        unquote(celery.username or "")
        != values["compose_main"]["AGENTIUM_RABBITMQ_USER"]
        or unquote(celery.password or "")
        != values["compose_main"]["AGENTIUM_RABBITMQ_PASSWORD"]
        or celery.hostname != "agentium-rabbitmq"
        or (celery.port or 5672) != 5672
    ):
        raise RuntimeEnvBundleError(
            "Celery is not bound to the snapshotted Agentium RabbitMQ runtime"
        )
    systemd_celery = urlsplit(values["systemd"]["CELERY_BROKER_URL"])
    if (
        unquote(systemd_celery.username or "")
        != values["compose_main"]["AGENTIUM_RABBITMQ_USER"]
        or unquote(systemd_celery.password or "")
        != values["compose_main"]["AGENTIUM_RABBITMQ_PASSWORD"]
        or systemd_celery.hostname not in {"127.0.0.1", "localhost"}
        or (systemd_celery.port or 5672) != 5672
    ):
        raise RuntimeEnvBundleError(
            "systemd Celery is not bound to the snapshotted RabbitMQ runtime"
        )
    keycloak = values["keycloak"]
    expected_keycloak_url = f"jdbc:postgresql://agentium-pg:5432/{postgres_database}"
    if (
        keycloak["KC_DB"] != "postgres"
        or keycloak["KC_DB_URL"] != expected_keycloak_url
        or keycloak["KC_DB_USERNAME"] != postgres_user
        or keycloak["KC_DB_PASSWORD"]
        != values["compose_main"]["AGENTIUM_POSTGRES_PASSWORD"]
    ):
        raise RuntimeEnvBundleError(
            "Keycloak is not bound to the backed-up Agentium PostgreSQL database"
        )
    for path_key in (
        "AGENTIUM_FAISS_PATH",
        "AGENTIUM_OBJECT_STORE_PATH",
        "AGENTIUM_SECURE_DEPOSIT_PATH",
    ):
        path_value = values["compose_main"][path_key]
        if (
            not path_value.startswith("/")
            or path_value == "/"
            or ".." in Path(path_value).parts
        ):
            raise RuntimeEnvBundleError(
                "runtime storage paths must be explicit absolute paths"
            )
    qdrant_admin = values["qdrant"]["QDRANT__SERVICE__API_KEY"]
    qdrant_read_only = values["qdrant"]["QDRANT__SERVICE__READ_ONLY_API_KEY"]
    if qdrant_admin == qdrant_read_only:
        raise RuntimeEnvBundleError(
            "Qdrant admin and read-only credentials are not separated"
        )
    if min(len(qdrant_admin), len(qdrant_read_only)) < 32:
        raise RuntimeEnvBundleError(
            "Qdrant credentials must contain at least 32 characters"
        )
    if values["application"]["QDRANT_API_KEY"] != qdrant_read_only:
        raise RuntimeEnvBundleError(
            "application Qdrant credential is not the read-only runtime key"
        )
    systemd = values["systemd"]
    if (
        systemd["QDRANT_API_KEY"] != qdrant_admin
        or systemd["QDRANT_HOST"] not in {"127.0.0.1", "localhost"}
        or systemd["QDRANT_PORT"] != "6333"
        or systemd["QDRANT_HTTPS"].lower() not in {"false", "0"}
    ):
        raise RuntimeEnvBundleError(
            "systemd Qdrant client is not bound to the protected admin runtime"
        )
    application = values["application"]
    if (
        application["QDRANT_HOST"] != "agentium-qdrant"
        or application["QDRANT_PORT"] != "6333"
        or application["QDRANT_HTTPS"].lower() not in {"false", "0"}
    ):
        raise RuntimeEnvBundleError(
            "application Qdrant endpoint is not the protected runtime"
        )
    if (
        application["OBJECT_STORE_BACKEND"] not in {"local", "s3"}
        or application["OBJECT_STORE_BASE_PATH"] != "/data/object_store"
        or application["OBJECT_STORE_S3_ENDPOINT_URL"]
        != "http://agentium-minio:9000"
        or application["OBJECT_STORE_S3_BUCKET"]
        != values["compose_main"]["AGENTIUM_MINIO_BUCKET"]
    ):
        raise RuntimeEnvBundleError(
            "application ObjectStore is not bound to the protected runtime"
        )
    expected_container_paths = {
        "FAISS_PERSIST_DIRECTORY": "/data/faiss_db",
        "SECURE_DEPOSIT_STORAGE_DIR": "/data/secure_deposit",
        "SECURE_DEPOSIT_SFTP_HOST_KEY_PATH": (
            "/data/secure_deposit/sftp_host_key"
        ),
        "SECURE_DEPOSIT_SFTP_TEMP_DIR": "/data/secure_deposit/_sftp_uploads",
    }
    if any(application[key] != expected for key, expected in expected_container_paths.items()):
        raise RuntimeEnvBundleError(
            "application filesystem paths are not bound to protected mounts"
        )
    systemd_object_endpoint = urlsplit(systemd["OBJECT_STORE_S3_ENDPOINT_URL"])
    if (
        systemd["OBJECT_STORE_BACKEND"] != application["OBJECT_STORE_BACKEND"]
        or systemd["OBJECT_STORE_BASE_PATH"]
        != values["compose_main"]["AGENTIUM_OBJECT_STORE_PATH"]
        or systemd["OBJECT_STORE_S3_BUCKET"]
        != values["compose_main"]["AGENTIUM_MINIO_BUCKET"]
        or systemd_object_endpoint.scheme != "http"
        or systemd_object_endpoint.hostname not in {"127.0.0.1", "localhost"}
        or (systemd_object_endpoint.port or 80) != 9000
        or systemd["OBJECT_STORE_S3_ACCESS_KEY"]
        != application["OBJECT_STORE_S3_ACCESS_KEY"]
        or systemd["OBJECT_STORE_S3_SECRET_KEY"]
        != application["OBJECT_STORE_S3_SECRET_KEY"]
        or systemd["FAISS_PERSIST_DIRECTORY"]
        != values["compose_main"]["AGENTIUM_FAISS_PATH"]
        or systemd["SECURE_DEPOSIT_STORAGE_DIR"]
        != values["compose_main"]["AGENTIUM_SECURE_DEPOSIT_PATH"]
    ):
        raise RuntimeEnvBundleError(
            "systemd stateful clients are not bound to protected host stores"
        )


def _assert_object_store_credentials_separated(contents: Mapping[str, bytes]) -> None:
    values = _parse_role_contents(contents)
    application = values["application"]
    systemd = values["systemd"]
    compose_main = values["compose_main"]
    app_access = application.get("OBJECT_STORE_S3_ACCESS_KEY", "")
    app_secret = application.get("OBJECT_STORE_S3_SECRET_KEY", "")
    root_access = compose_main.get("AGENTIUM_MINIO_ROOT_USER", "")
    root_secret = compose_main.get("AGENTIUM_MINIO_ROOT_PASSWORD", "")
    if (
        not app_access
        or not app_secret
        or not root_access
        or not root_secret
        or app_access == root_access
        or app_secret == root_secret
        or systemd.get("OBJECT_STORE_S3_ACCESS_KEY") != app_access
        or systemd.get("OBJECT_STORE_S3_SECRET_KEY") != app_secret
    ):
        raise RuntimeEnvBundleError(
            "ObjectStore application and MinIO root credentials are not separated"
        )


def _resolve_reference(value: str, *, compose_dir: Path, label: str) -> Path:
    if not value or "\x00" in value or "$" in value:
        raise RuntimeEnvBundleError(f"{label} reference is empty or dynamic")
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = compose_dir / candidate
    return candidate.absolute()


def _write_private(path: Path, content: bytes) -> None:
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
        0o600,
    )
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _json_bytes(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        + "\n"
    ).encode("utf-8")


def _effective_main(
    content: bytes,
    *,
    final_bundle: Path,
    role_files: Mapping[str, str],
) -> bytes:
    # Parsing first makes replacement fail-closed on duplicate keys.  Keep all
    # unrelated bytes human-readable and replace only the indirect paths.
    _parse_dotenv(content, label="compose main environment")
    reference_keys = set(REFERENCE_KEYS.values())
    lines: list[str] = []
    for raw_line in content.decode("utf-8").splitlines():
        stripped = raw_line.strip()
        candidate = (
            stripped[7:].lstrip() if stripped.startswith("export ") else stripped
        )
        key = candidate.partition("=")[0].strip()
        if key in reference_keys:
            continue
        lines.append(raw_line)
    if lines and lines[-1]:
        lines.append("")
    lines.append("# Paths below are frozen by agentium-runtime-env-bundle-v3.")
    for role, key in REFERENCE_KEYS.items():
        lines.append(f"{key}={final_bundle / role_files[role]}")
    return ("\n".join(lines) + "\n").encode("utf-8")


def _effective_systemd(content: bytes, *, candidate_sha: str) -> bytes:
    values, _ = _parse_dotenv(content, label="systemd environment")
    if "AGENTIUM_IMAGE_REVISION" in values:
        raise RuntimeEnvBundleError(
            "systemd source must not define the orchestrator-owned image revision"
        )
    text = content.decode("utf-8")
    if text and not text.endswith("\n"):
        text += "\n"
    return (text + f"AGENTIUM_IMAGE_REVISION={candidate_sha}\n").encode("utf-8")


def freeze_bundle(
    *,
    main_env: Path,
    compose_dir: Path,
    systemd_env: Path,
    output_dir: Path,
    candidate_sha: str,
    deployment_id: str,
    source_owner_uid: int,
) -> str:
    _identity(candidate_sha, deployment_id)
    if source_owner_uid < 0:
        raise RuntimeEnvBundleError("source owner uid is invalid")
    if not output_dir.is_absolute() or output_dir.name != "runtime-env":
        raise RuntimeEnvBundleError(
            "output directory must be an absolute runtime-env path"
        )
    if output_dir.exists():
        return verify_bundle(
            bundle_dir=output_dir,
            candidate_sha=candidate_sha,
            deployment_id=deployment_id,
        )
    output_dir.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(output_dir.parent, 0o700)
    temporary = output_dir.parent / f".{output_dir.name}.{os.getpid()}"
    if temporary.exists() or temporary.is_symlink():
        raise RuntimeEnvBundleError("temporary bundle path already exists")
    temporary.mkdir(mode=0o700)
    try:
        main_content, main_stat = _read_regular_file(
            main_env,
            label="compose main environment",
            source_owner_uid=source_owner_uid,
        )
        main_values, _ = _parse_dotenv(main_content, label="compose main environment")
        source_paths: dict[str, Path] = {"compose_main": main_env.absolute()}
        for role, key in REFERENCE_KEYS.items():
            if not main_values.get(key):
                raise RuntimeEnvBundleError(
                    f"compose main environment must explicitly define {key}"
                )
            source_paths[role] = _resolve_reference(
                main_values[key],
                compose_dir=compose_dir.absolute(),
                label=role,
            )
        source_paths["systemd"] = systemd_env.absolute()

        roles: dict[str, dict[str, Any]] = {}
        files: dict[str, dict[str, Any]] = {}
        aliases: dict[tuple[int, int], tuple[str, bytes]] = {}
        role_files: dict[str, str] = {}
        role_contents: dict[str, bytes] = {}
        role_source_contents: dict[str, bytes] = {}
        role_source_identities: dict[str, tuple[int, ...]] = {}
        for role, source_path in source_paths.items():
            if role == "compose_main":
                content, source_stat = main_content, main_stat
            else:
                content, source_stat = _read_regular_file(
                    source_path,
                    label=f"{role} environment",
                    source_owner_uid=source_owner_uid,
                )
                _parse_dotenv(content, label=f"{role} environment")
            source_content = content
            if role == "systemd":
                content = _effective_systemd(content, candidate_sha=candidate_sha)
            inode_identity = (int(source_stat.st_dev), int(source_stat.st_ino))
            existing = aliases.get(inode_identity)
            if existing is not None:
                filename, previous_content = existing
                if previous_content != content:
                    raise RuntimeEnvBundleError(
                        "aliased environment changed during capture"
                    )
            else:
                filename = f"source-{len(aliases):03d}.env"
                _write_private(temporary / filename, content)
                aliases[inode_identity] = (filename, content)
                files[filename] = {
                    "sha256": _sha256_bytes(content),
                    "size": len(content),
                }
            role_files[role] = filename
            role_contents[role] = content
            role_source_contents[role] = source_content
            role_source_identities[role] = _file_identity(source_stat)
            roles[role] = {
                "file": filename,
                "source_path_sha256": _sha256_path(source_path),
                "source_device": int(source_stat.st_dev),
                "source_inode": int(source_stat.st_ino),
                "source_mtime_ns": int(source_stat.st_mtime_ns),
            }

        # A per-file stable read is insufficient for a transaction made from
        # several dotenv files: one file could rotate after it was copied while
        # the remaining roles are still being read. Re-open every source after
        # the complete first pass and require both content and file identity to
        # match before the bundle can be published.
        for role, source_path in source_paths.items():
            second_content, second_stat = _read_regular_file(
                source_path,
                label=f"{role} environment second pass",
                source_owner_uid=source_owner_uid,
            )
            if (
                second_content != role_source_contents[role]
                or _file_identity(second_stat) != role_source_identities[role]
            ):
                raise RuntimeEnvBundleError(
                    "runtime environment sources changed across the capture"
                )

        _assert_object_store_credentials_separated(role_contents)
        _assert_no_placeholder_secrets(role_contents)
        _assert_production_contract(role_contents)

        effective = _effective_main(
            main_content,
            final_bundle=output_dir,
            role_files=role_files,
        )
        effective_name = "compose.effective.env"
        _write_private(temporary / effective_name, effective)
        files[effective_name] = {
            "sha256": _sha256_bytes(effective),
            "size": len(effective),
        }
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "profile": PROFILE,
            "candidate_sha": candidate_sha,
            "deployment_id": deployment_id,
            "files": files,
            "roles": roles,
            "effective_compose_file": effective_name,
            "effective_references": {
                key: role_files[role] for role, key in REFERENCE_KEYS.items()
            },
            "checks": {
                "object_store_minio_credentials_separated": True,
                "placeholder_secrets_rejected": True,
                "production_credentials_explicit": True,
                "source_files_private": True,
                "storage_paths_explicit": True,
                "systemd_revision_bound": True,
            },
        }
        manifest_content = _json_bytes(manifest)
        _write_private(temporary / "manifest.json", manifest_content)
        _fsync_directory(temporary)
        os.replace(temporary, output_dir)
        _fsync_directory(output_dir.parent)
    except BaseException:
        if temporary.is_dir():
            for child in temporary.iterdir():
                child.unlink(missing_ok=True)
            temporary.rmdir()
        raise
    return verify_bundle(
        bundle_dir=output_dir,
        candidate_sha=candidate_sha,
        deployment_id=deployment_id,
    )


def _load_manifest(path: Path) -> tuple[dict[str, Any], bytes]:
    content, _ = _read_regular_file(path, label="runtime environment manifest")
    try:
        value = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeEnvBundleError("runtime environment manifest is invalid") from exc
    if not isinstance(value, dict):
        raise RuntimeEnvBundleError("runtime environment manifest is invalid")
    return value, content


def verify_bundle(
    *,
    bundle_dir: Path,
    candidate_sha: str,
    deployment_id: str,
    expected_manifest_sha256: str | None = None,
) -> str:
    _identity(candidate_sha, deployment_id)
    try:
        bundle_stat = bundle_dir.lstat()
    except OSError as exc:
        raise RuntimeEnvBundleError(
            "runtime environment bundle is unavailable"
        ) from exc
    if not stat.S_ISDIR(bundle_stat.st_mode) or bundle_dir.is_symlink():
        raise RuntimeEnvBundleError(
            "runtime environment bundle is not a real directory"
        )
    if stat.S_IMODE(bundle_stat.st_mode) != 0o700:
        raise RuntimeEnvBundleError("runtime environment bundle mode must be 0700")
    manifest, manifest_content = _load_manifest(bundle_dir / "manifest.json")
    manifest_sha256 = _sha256_bytes(manifest_content)
    if expected_manifest_sha256 and manifest_sha256 != expected_manifest_sha256:
        raise RuntimeEnvBundleError("runtime environment manifest digest differs")
    if (
        manifest.get("schema_version") != SCHEMA_VERSION
        or manifest.get("profile") != PROFILE
        or manifest.get("candidate_sha") != candidate_sha
        or manifest.get("deployment_id") != deployment_id
        or manifest.get("checks")
        != {
            "object_store_minio_credentials_separated": True,
            "placeholder_secrets_rejected": True,
            "production_credentials_explicit": True,
            "source_files_private": True,
            "storage_paths_explicit": True,
            "systemd_revision_bound": True,
        }
    ):
        raise RuntimeEnvBundleError("runtime environment manifest identity differs")
    files = manifest.get("files")
    roles = manifest.get("roles")
    references = manifest.get("effective_references")
    effective_name = manifest.get("effective_compose_file")
    if (
        not isinstance(files, dict)
        or not isinstance(roles, dict)
        or not isinstance(references, dict)
    ):
        raise RuntimeEnvBundleError("runtime environment manifest shape is invalid")
    if set(roles) != ROLES:
        raise RuntimeEnvBundleError("runtime environment role set is invalid")
    if effective_name != "compose.effective.env" or effective_name not in files:
        raise RuntimeEnvBundleError("effective Compose environment is missing")
    expected_files = {"manifest.json", *map(str, files)}
    actual_files = {child.name for child in bundle_dir.iterdir()}
    if actual_files != expected_files:
        raise RuntimeEnvBundleError("runtime environment bundle has unexpected files")
    owner = (bundle_stat.st_uid, bundle_stat.st_gid)
    manifest_stat = (bundle_dir / "manifest.json").stat(follow_symlinks=False)
    if (
        stat.S_IMODE(manifest_stat.st_mode) != 0o600
        or (manifest_stat.st_uid, manifest_stat.st_gid) != owner
        or manifest_stat.st_nlink != 1
    ):
        raise RuntimeEnvBundleError("runtime environment manifest permissions differ")
    seen_file_identities = {(manifest_stat.st_dev, manifest_stat.st_ino)}
    file_contents: dict[str, bytes] = {}
    for filename, contract in files.items():
        if not isinstance(filename, str) or Path(filename).name != filename:
            raise RuntimeEnvBundleError("runtime environment filename is invalid")
        if (
            not isinstance(contract, dict)
            or set(contract) != {"sha256", "size"}
            or not isinstance(contract.get("sha256"), str)
            or re.fullmatch(r"[0-9a-f]{64}", contract["sha256"]) is None
            or not isinstance(contract.get("size"), int)
            or isinstance(contract.get("size"), bool)
            or contract["size"] < 0
        ):
            raise RuntimeEnvBundleError("runtime environment file contract is invalid")
        path = bundle_dir / filename
        content, file_stat = _read_regular_file(
            path, label="frozen runtime environment"
        )
        if (
            stat.S_IMODE(file_stat.st_mode) != 0o600
            or (file_stat.st_uid, file_stat.st_gid) != owner
            or file_stat.st_nlink != 1
            or contract.get("sha256") != _sha256_bytes(content)
            or contract.get("size") != len(content)
        ):
            raise RuntimeEnvBundleError("frozen runtime environment differs")
        file_identity = (file_stat.st_dev, file_stat.st_ino)
        if file_identity in seen_file_identities:
            raise RuntimeEnvBundleError("runtime environment files reuse an inode")
        seen_file_identities.add(file_identity)
        file_contents[filename] = content
    source_identity_files: dict[tuple[int, int], str] = {}
    role_file_sources: dict[str, tuple[int, int]] = {}
    for role, contract in roles.items():
        if not isinstance(contract, dict) or set(contract) != {
            "file",
            "source_path_sha256",
            "source_device",
            "source_inode",
            "source_mtime_ns",
        }:
            raise RuntimeEnvBundleError("runtime environment role contract is invalid")
        if contract.get("file") not in files:
            raise RuntimeEnvBundleError("runtime environment role file is missing")
        digest = contract.get("source_path_sha256")
        if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise RuntimeEnvBundleError(
                "runtime environment source identity is invalid"
            )
        for field in ("source_device", "source_inode", "source_mtime_ns"):
            if (
                not isinstance(contract.get(field), int)
                or isinstance(contract[field], bool)
                or contract[field] < 0
            ):
                raise RuntimeEnvBundleError(
                    "runtime environment source stat is invalid"
                )
        source_identity = (contract["source_device"], contract["source_inode"])
        filename = contract["file"]
        previous_filename = source_identity_files.setdefault(source_identity, filename)
        previous_source = role_file_sources.setdefault(filename, source_identity)
        if previous_filename != filename or previous_source != source_identity:
            raise RuntimeEnvBundleError(
                "runtime environment role inode alias is inconsistent"
            )
    if set(files) != {
        effective_name,
        *(contract["file"] for contract in roles.values()),
    }:
        raise RuntimeEnvBundleError("runtime environment file inventory is invalid")
    if references != {key: roles[role]["file"] for role, key in REFERENCE_KEYS.items()}:
        raise RuntimeEnvBundleError("effective environment references differ")
    role_contents = {
        role: file_contents[contract["file"]] for role, contract in roles.items()
    }
    _assert_object_store_credentials_separated(role_contents)
    _assert_no_placeholder_secrets(role_contents)
    _assert_production_contract(role_contents)
    systemd_values, _ = _parse_dotenv(
        role_contents["systemd"], label="frozen systemd environment"
    )
    if systemd_values.get("AGENTIUM_IMAGE_REVISION") != candidate_sha:
        raise RuntimeEnvBundleError(
            "frozen systemd revision differs from candidate SHA"
        )
    effective_content = file_contents[effective_name]
    effective_values, _ = _parse_dotenv(
        effective_content, label="effective Compose environment"
    )
    for role, key in REFERENCE_KEYS.items():
        expected = str(bundle_dir / roles[role]["file"])
        if effective_values.get(key) != expected:
            raise RuntimeEnvBundleError("effective environment path escaped the bundle")
    return manifest_sha256


def bundle_role_path(
    *,
    bundle_dir: Path,
    role: str,
    candidate_sha: str,
    deployment_id: str,
    expected_manifest_sha256: str,
) -> Path:
    """Return a verified, bundle-internal path for one frozen environment role."""
    verify_bundle(
        bundle_dir=bundle_dir,
        candidate_sha=candidate_sha,
        deployment_id=deployment_id,
        expected_manifest_sha256=expected_manifest_sha256,
    )
    if role not in ROLES:
        raise RuntimeEnvBundleError("runtime environment role is invalid")
    manifest, _ = _load_manifest(bundle_dir / "manifest.json")
    filename = manifest["roles"][role]["file"]
    path = bundle_dir / filename
    if path.parent != bundle_dir or not path.is_file() or path.is_symlink():
        raise RuntimeEnvBundleError("runtime environment role escaped the bundle")
    return path


def bundle_role_value(
    *,
    bundle_dir: Path,
    role: str,
    key: str,
    candidate_sha: str,
    deployment_id: str,
    expected_manifest_sha256: str,
) -> str:
    """Read one canonical value from a verified role without diagnostic leakage."""

    if KEY_RE.fullmatch(key) is None:
        raise RuntimeEnvBundleError("runtime environment key is invalid")
    role_path = bundle_role_path(
        bundle_dir=bundle_dir,
        role=role,
        candidate_sha=candidate_sha,
        deployment_id=deployment_id,
        expected_manifest_sha256=expected_manifest_sha256,
    )
    manifest, manifest_content = _load_manifest(bundle_dir / "manifest.json")
    if _sha256_bytes(manifest_content) != expected_manifest_sha256:
        raise RuntimeEnvBundleError("runtime environment manifest digest differs")
    contract = manifest["files"][manifest["roles"][role]["file"]]
    content, _ = _read_regular_file(
        role_path, label="requested runtime environment role"
    )
    if contract.get("sha256") != _sha256_bytes(content) or contract.get("size") != len(
        content
    ):
        raise RuntimeEnvBundleError("requested runtime environment role differs")
    values, _ = _parse_dotenv(content, label="requested runtime environment role")
    if key not in values:
        raise RuntimeEnvBundleError("requested runtime environment key is missing")
    return values[key]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    freeze = subparsers.add_parser("freeze")
    freeze.add_argument("--main-env", type=Path, required=True)
    freeze.add_argument("--compose-dir", type=Path, required=True)
    freeze.add_argument("--systemd-env", type=Path, required=True)
    freeze.add_argument("--bundle-dir", type=Path, required=True)
    freeze.add_argument("--source-owner-uid", type=int, required=True)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--bundle-dir", type=Path, required=True)
    verify.add_argument("--expected-manifest-sha256")
    role_path = subparsers.add_parser("role-path")
    role_path.add_argument("--bundle-dir", type=Path, required=True)
    role_path.add_argument("--expected-manifest-sha256", required=True)
    role_path.add_argument(
        "--role",
        choices=("compose_main", "application", "qdrant", "keycloak", "systemd"),
        required=True,
    )
    value = subparsers.add_parser("value")
    value.add_argument("--bundle-dir", type=Path, required=True)
    value.add_argument("--expected-manifest-sha256", required=True)
    value.add_argument(
        "--role",
        choices=tuple(sorted(ROLES)),
        required=True,
    )
    value.add_argument("--key", required=True)
    vm_storage_env = subparsers.add_parser("vm-storage-env-check")
    vm_storage_env.add_argument("--env-file", type=Path, required=True)
    subparsers.add_parser("vm-storage-compose-check")
    vm_storage_volume = subparsers.add_parser("vm-storage-volume-check")
    vm_storage_volume.add_argument(
        "--name", choices=tuple(sorted(VM_BIND_BACKED_VOLUMES)), required=True
    )
    subparsers.add_parser("vm-storage-runtime-check")
    for command in (freeze, verify, role_path, value):
        command.add_argument("--sha", required=True)
        command.add_argument("--deployment-id", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "freeze":
            digest = freeze_bundle(
                main_env=args.main_env,
                compose_dir=args.compose_dir,
                systemd_env=args.systemd_env,
                output_dir=args.bundle_dir,
                candidate_sha=args.sha,
                deployment_id=args.deployment_id,
                source_owner_uid=args.source_owner_uid,
            )
        elif args.command == "verify":
            digest = verify_bundle(
                bundle_dir=args.bundle_dir,
                candidate_sha=args.sha,
                deployment_id=args.deployment_id,
                expected_manifest_sha256=args.expected_manifest_sha256,
            )
        elif args.command == "role-path":
            path = bundle_role_path(
                bundle_dir=args.bundle_dir,
                role=args.role,
                candidate_sha=args.sha,
                deployment_id=args.deployment_id,
                expected_manifest_sha256=args.expected_manifest_sha256,
            )
            print(path)
            return 0
        elif args.command == "value":
            value = bundle_role_value(
                bundle_dir=args.bundle_dir,
                role=args.role,
                key=args.key,
                candidate_sha=args.sha,
                deployment_id=args.deployment_id,
                expected_manifest_sha256=args.expected_manifest_sha256,
            )
            print(value)
            return 0
        elif args.command == "vm-storage-env-check":
            content, _ = _read_regular_file(
                args.env_file, label="frozen VM Compose environment"
            )
            assert_vm_storage_environment(content)
            return 0
        elif args.command == "vm-storage-compose-check":
            assert_vm_compose_storage(_read_json_stdin(label="rendered VM Compose model"))
            return 0
        elif args.command == "vm-storage-volume-check":
            assert_vm_volume_inspect(
                _read_json_stdin(label="VM storage volume inspection"),
                volume_name=args.name,
            )
            return 0
        else:
            assert_vm_active_storage_mounts(
                _read_json_stdin(label="VM storage container inspection")
            )
            return 0
    except RuntimeEnvBundleError as exc:
        print(f"Runtime environment bundle failed: {exc}", file=sys.stderr)
        return 1
    print(digest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
