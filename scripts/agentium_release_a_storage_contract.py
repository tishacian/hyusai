#!/usr/bin/env python3
"""Fail-closed Release A check for candidate Compose stateful mounts.

The rendered Compose model is read from stdin and is never written to disk: it
may contain interpolated secrets.  The emitted receipt is content-free and can
therefore be retained in the private deployment journal.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from collections.abc import Callable, Mapping
from typing import Any

MAX_COMPOSE_BYTES = 16 * 1024 * 1024

# Compose service -> historical runtime container -> exact persistent targets.
PROTECTED_STORAGE: Mapping[str, tuple[str, frozenset[str]]] = {
    "agentium-pg": ("agentium-pg", frozenset({"/var/lib/postgresql/data"})),
    "agentium-rabbitmq": ("agentium-rabbitmq", frozenset({"/var/lib/rabbitmq"})),
    "agentium-qdrant": (
        "qdrant",
        frozenset({"/qdrant/storage", "/qdrant/snapshots"}),
    ),
    "agentium-minio": ("agentium-minio", frozenset({"/data"})),
}

APPLICATION_STORAGE: Mapping[str, frozenset[str]] = {
    "agentium-backend": frozenset(
        {"/data/object_store", "/data/secure_deposit", "/data/faiss_db"}
    ),
    "agentium-worker-cpu": frozenset(
        {"/data/object_store", "/data/secure_deposit", "/data/faiss_db"}
    ),
    "agentium-p4-maintenance": frozenset(
        {"/data/object_store", "/data/secure_deposit", "/data/faiss_db"}
    ),
    "agentium-migrate": frozenset(
        {"/data/object_store", "/data/secure_deposit", "/data/faiss_db"}
    ),
    "agentium-sftp": frozenset({"/data/secure_deposit"}),
}

APPLICATION_ANCHORS: Mapping[str, tuple[str, str]] = {
    "/data/object_store": ("agentium-backend", "/data/object_store"),
    "/data/secure_deposit": ("agentium-sftp", "/data/secure_deposit"),
    "/data/faiss_db": ("agentium-backend", "/data/faiss_db"),
}

# Release A is allowed to add/rotate only Qdrant's two authentication values.
# MinIO versioning and its application policy are control-plane changes made by
# the separately attested init job; they do not justify a container runtime
# delta.  In particular, images, commands, networks and privileges remain exact.
ALLOWED_ENVIRONMENT_DELTAS: Mapping[str, frozenset[str]] = {
    "agentium-pg": frozenset(),
    # First-boot seeds only: the broker was initialised long ago, the container
    # is never recreated (identity_only_no_recreation) and the deployment
    # principal is created through rabbitmqctl by the attested bootstrap, so a
    # rendered delta on these two variables cannot reach the running broker.
    "agentium-rabbitmq": frozenset(
        {
            "RABBITMQ_DEFAULT_USER",
            "RABBITMQ_DEFAULT_PASS",
        }
    ),
    "agentium-qdrant": frozenset(
        {
            "QDRANT__SERVICE__API_KEY",
            "QDRANT__SERVICE__READ_ONLY_API_KEY",
        }
    ),
    "agentium-minio": frozenset(),
}

STATEFUL_MUTATION_POLICY: Mapping[str, str] = {
    "agentium-pg": "identity_only_no_recreation",
    "agentium-rabbitmq": "identity_only_no_recreation",
    "agentium-qdrant": "identity_preserved_qdrant_auth_environment_only",
    "agentium-minio": "identity_preserved_external_versioning_only",
}

# These are the two existing Docker local volumes whose data is physically
# anchored on /dev/sdb.  Release A must reuse them as external volumes; it may
# neither silently select a similarly named volume nor change their local-bind
# driver options.
EXPECTED_BIND_BACKED_VOLUMES: Mapping[
    tuple[str, str], tuple[str, Mapping[str, str]]
] = {
    ("agentium-qdrant", "/qdrant/storage"): (
        "agentium_qdrant_block",
        {"device": "/srv/agentium-data/qdrant", "o": "bind", "type": "none"},
    ),
    ("agentium-minio", "/data"): (
        "agentium_minio_block",
        {"device": "/srv/agentium-data/minio", "o": "bind", "type": "none"},
    ),
}

_ENVIRONMENT_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}\Z")
_PORT_KEY = re.compile(r"([1-9][0-9]{0,4})/(tcp|udp|sctp)\Z")


class StorageContractError(ValueError):
    """The candidate definition does not preserve the live storage identity."""


def _one_inspect(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], dict):
        raise StorageContractError(f"{label} inspect must contain exactly one object")
    return value[0]


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sequence(value: Any, label: str, *, nullable: bool = False) -> list[str] | None:
    if value is None and nullable:
        return None
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise StorageContractError(f"{label} must be a rendered string list")
    return list(value)


def _environment(value: Any, label: str) -> dict[str, str]:
    """Return an effective environment without ever serialising its values."""

    if value is None:
        return {}
    rows: list[tuple[str, str]] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str) or not _ENVIRONMENT_KEY.fullmatch(key):
                raise StorageContractError(f"{label} contains an invalid key")
            if not isinstance(item, str):
                raise StorageContractError(f"{label} contains a non-rendered value")
            rows.append((key, item))
    elif isinstance(value, list):
        for item in value:
            if not isinstance(item, str):
                raise StorageContractError(f"{label} contains a non-string entry")
            key, separator, resolved = item.partition("=")
            if not separator:
                resolved = ""
            if not _ENVIRONMENT_KEY.fullmatch(key):
                raise StorageContractError(f"{label} contains an invalid key")
            rows.append((key, resolved))
    else:
        raise StorageContractError(f"{label} must be a rendered environment")

    result: dict[str, str] = {}
    for key, resolved in rows:
        if key in result:
            raise StorageContractError(f"{label} contains a duplicate key")
        result[key] = resolved
    return result


def _runtime_user(value: Any, label: str) -> str:
    if value is None:
        return ""
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise StorageContractError(f"{label} is invalid")
    return str(value)


def _string_set(value: Any, label: str) -> list[str]:
    if value is None:
        return []
    rows = _sequence(value, label)
    if rows is None:
        raise StorageContractError(f"{label} unexpectedly resolved to null")
    if len(rows) != len(set(rows)):
        raise StorageContractError(f"{label} contains duplicates")
    return sorted(rows)


def _boolean(value: Any, label: str, *, default: bool = False) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        raise StorageContractError(f"{label} must be boolean")
    return value


def _candidate_network_identity(
    compose: Mapping[str, Any], service: Mapping[str, Any], label: str
) -> tuple[str, list[str]]:
    raw = service.get("networks")
    if isinstance(raw, dict):
        logical_names = list(raw)
    elif isinstance(raw, list) and all(isinstance(item, str) for item in raw):
        logical_names = list(raw)
    else:
        raise StorageContractError(f"{label}.networks must be rendered")
    if len(logical_names) != 1:
        raise StorageContractError(f"{label} must attach to exactly one network")

    definitions = compose.get("networks")
    if not isinstance(definitions, dict):
        raise StorageContractError("Compose networks must be an object")
    definition = definitions.get(logical_names[0])
    if not isinstance(definition, dict):
        raise StorageContractError(f"{label} references an unknown network")
    resolved_name = definition.get("name")
    if not isinstance(resolved_name, str) or not resolved_name:
        raise StorageContractError(f"{label} network name is not rendered explicitly")

    explicit_mode = service.get("network_mode")
    if explicit_mode is not None:
        if not isinstance(explicit_mode, str) or explicit_mode != resolved_name:
            raise StorageContractError(f"{label}.network_mode is not the attached network")
        mode = explicit_mode
    else:
        mode = resolved_name
    return mode, [resolved_name]


def _candidate_port_bindings(value: Any, label: str) -> list[tuple[str, str, str]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise StorageContractError(f"{label} must be a rendered list")
    result: list[tuple[str, str, str]] = []
    for row in value:
        if not isinstance(row, dict):
            raise StorageContractError(f"{label} contains a non-object binding")
        target = row.get("target")
        published = row.get("published")
        protocol = row.get("protocol", "tcp")
        host_ip = row.get("host_ip", "")
        mode = row.get("mode", "ingress")
        if isinstance(target, bool) or not isinstance(target, (str, int)):
            raise StorageContractError(f"{label} target is invalid")
        if isinstance(published, bool) or not isinstance(published, (str, int)):
            raise StorageContractError(f"{label} published port must be fixed")
        target_text, published_text = str(target), str(published)
        if (
            not target_text.isdigit()
            or not published_text.isdigit()
            or not 1 <= int(target_text) <= 65535
            or not 1 <= int(published_text) <= 65535
            or protocol not in {"tcp", "udp", "sctp"}
            or not isinstance(host_ip, str)
            or mode != "ingress"
        ):
            raise StorageContractError(f"{label} contains an unsupported binding")
        result.append((f"{int(target_text)}/{protocol}", host_ip, str(int(published_text))))
    if len(result) != len(set(result)):
        raise StorageContractError(f"{label} contains duplicate bindings")
    return sorted(result)


def _live_port_bindings(value: Any, label: str) -> list[tuple[str, str, str]]:
    if value is None:
        return []
    if not isinstance(value, dict):
        raise StorageContractError(f"{label} must be an object")
    result: list[tuple[str, str, str]] = []
    for port_key, bindings in value.items():
        match = _PORT_KEY.fullmatch(port_key) if isinstance(port_key, str) else None
        if not match or int(match.group(1)) > 65535:
            raise StorageContractError(f"{label} contains an invalid container port")
        # NetworkSettings.Ports also contains exposed-but-unpublished null rows.
        if bindings is None:
            continue
        if not isinstance(bindings, list):
            raise StorageContractError(f"{label} contains invalid host bindings")
        for row in bindings:
            if not isinstance(row, dict):
                raise StorageContractError(f"{label} contains a non-object binding")
            host_ip, host_port = row.get("HostIp"), row.get("HostPort")
            if (
                not isinstance(host_ip, str)
                or not isinstance(host_port, str)
                or not host_port.isdigit()
                or not 1 <= int(host_port) <= 65535
            ):
                raise StorageContractError(f"{label} contains an invalid host binding")
            result.append((port_key, host_ip, str(int(host_port))))
    if len(result) != len(set(result)):
        raise StorageContractError(f"{label} contains duplicate bindings")
    return sorted(result)


def _runtime_identity(
    compose: Mapping[str, Any],
    service_name: str,
    service: Mapping[str, Any],
    live_container: Mapping[str, Any],
    image: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate and return a receipt-safe description of one stateful runtime."""

    image_config = image.get("Config")
    live_config = live_container.get("Config")
    host_config = live_container.get("HostConfig")
    network_settings = live_container.get("NetworkSettings")
    if not all(
        isinstance(value, dict)
        for value in (image_config, live_config, host_config, network_settings)
    ):
        raise StorageContractError(f"{service_name} image/runtime config is invalid")
    image_reference = service.get("image")
    image_id = image.get("Id")
    if not isinstance(image_reference, str) or not image_reference.strip():
        raise StorageContractError(f"{service_name} image is not rendered")
    if not isinstance(image_id, str) or not _IMAGE_ID.fullmatch(image_id):
        raise StorageContractError(f"{service_name} resolved image ID is not immutable")
    if image_id != live_container.get("Image"):
        raise StorageContractError(f"{service_name} resolved image ID differs from live")
    if live_config.get("Image") != image_reference:
        raise StorageContractError(f"{service_name} image reference differs from live")

    candidate_entrypoint_value = service.get("entrypoint")
    if candidate_entrypoint_value is None:
        candidate_entrypoint_value = image_config.get("Entrypoint")
    candidate_command_value = service.get("command")
    if candidate_command_value is None:
        candidate_command_value = image_config.get("Cmd")
    candidate_entrypoint = _sequence(
        candidate_entrypoint_value, f"{service_name}.entrypoint", nullable=True
    )
    candidate_command = _sequence(
        candidate_command_value, f"{service_name}.command", nullable=True
    )
    live_entrypoint = _sequence(
        live_config.get("Entrypoint"), f"{service_name} live entrypoint", nullable=True
    )
    live_command = _sequence(
        live_config.get("Cmd"), f"{service_name} live command", nullable=True
    )
    if candidate_entrypoint != live_entrypoint:
        raise StorageContractError(f"{service_name} entrypoint differs from live")
    if candidate_command != live_command:
        raise StorageContractError(f"{service_name} command differs from live")

    candidate_user = _runtime_user(
        service.get("user", image_config.get("User")), f"{service_name}.user"
    )
    live_user = _runtime_user(live_config.get("User"), f"{service_name} live user")
    if candidate_user != live_user:
        raise StorageContractError(f"{service_name} user differs from live")

    network_mode, candidate_networks = _candidate_network_identity(
        compose, service, service_name
    )
    live_networks_raw = network_settings.get("Networks")
    if not isinstance(live_networks_raw, dict) or not all(
        isinstance(key, str) and isinstance(value, dict)
        for key, value in live_networks_raw.items()
    ):
        raise StorageContractError(f"{service_name} live networks are invalid")
    live_networks = sorted(live_networks_raw)
    if host_config.get("NetworkMode") != network_mode:
        raise StorageContractError(f"{service_name} network mode differs from live")
    if candidate_networks != live_networks:
        raise StorageContractError(f"{service_name} attached networks differ from live")

    candidate_ports = _candidate_port_bindings(
        service.get("ports"), f"{service_name}.ports"
    )
    host_ports = _live_port_bindings(
        host_config.get("PortBindings"), f"{service_name} live host ports"
    )
    runtime_ports = _live_port_bindings(
        network_settings.get("Ports"), f"{service_name} live runtime ports"
    )
    if candidate_ports != host_ports or candidate_ports != runtime_ports:
        raise StorageContractError(f"{service_name} published ports differ from live")

    candidate_cap_add = _string_set(service.get("cap_add"), f"{service_name}.cap_add")
    candidate_cap_drop = _string_set(service.get("cap_drop"), f"{service_name}.cap_drop")
    candidate_security = _string_set(
        service.get("security_opt"), f"{service_name}.security_opt"
    )
    live_cap_add = _string_set(host_config.get("CapAdd"), f"{service_name} live CapAdd")
    live_cap_drop = _string_set(
        host_config.get("CapDrop"), f"{service_name} live CapDrop"
    )
    live_security = _string_set(
        host_config.get("SecurityOpt"), f"{service_name} live SecurityOpt"
    )
    candidate_privileged = _boolean(
        service.get("privileged"), f"{service_name}.privileged"
    )
    candidate_read_only_rootfs = _boolean(
        service.get("read_only"), f"{service_name}.read_only"
    )
    live_privileged = _boolean(
        host_config.get("Privileged"), f"{service_name} live Privileged"
    )
    live_read_only_rootfs = _boolean(
        host_config.get("ReadonlyRootfs"), f"{service_name} live ReadonlyRootfs"
    )
    if (
        candidate_cap_add != live_cap_add
        or candidate_cap_drop != live_cap_drop
        or candidate_security != live_security
        or candidate_privileged != live_privileged
        or candidate_read_only_rootfs != live_read_only_rootfs
    ):
        raise StorageContractError(f"{service_name} security context differs from live")

    candidate_environment = _environment(
        image_config.get("Env"), f"{service_name} image environment"
    )
    candidate_environment.update(
        _environment(service.get("environment"), f"{service_name}.environment")
    )
    live_environment = _environment(
        live_config.get("Env"), f"{service_name} live environment"
    )
    environment_deltas = {
        key
        for key in candidate_environment.keys() | live_environment.keys()
        if candidate_environment.get(key) != live_environment.get(key)
    }
    allowed_deltas = ALLOWED_ENVIRONMENT_DELTAS[service_name]
    if not environment_deltas <= allowed_deltas:
        raise StorageContractError(
            f"{service_name} has a non-allowlisted environment delta"
        )
    if service_name == "agentium-qdrant":
        admin = candidate_environment.get("QDRANT__SERVICE__API_KEY", "")
        read_only = candidate_environment.get(
            "QDRANT__SERVICE__READ_ONLY_API_KEY", ""
        )
        if not admin or not read_only or admin == read_only:
            raise StorageContractError(
                "agentium-qdrant requires two distinct non-empty auth values"
            )

    # Values are intentionally excluded: other private receipts bind the frozen
    # environment.  This helper records only its closed key-level delta policy.
    return {
        "service": service_name,
        "container": PROTECTED_STORAGE[service_name][0],
        "image_id": image_id,
        "image_reference": image_reference,
        "entrypoint": candidate_entrypoint,
        "command": candidate_command,
        "user": candidate_user,
        "network_mode": network_mode,
        "networks": candidate_networks,
        "ports": candidate_ports,
        "cap_add": candidate_cap_add,
        "cap_drop": candidate_cap_drop,
        "security_opt": candidate_security,
        "privileged": candidate_privileged,
        "read_only_rootfs": candidate_read_only_rootfs,
        "environment_keys": sorted(candidate_environment),
        "allowed_environment_delta_keys": sorted(environment_deltas),
        "mutation_policy": STATEFUL_MUTATION_POLICY[service_name],
    }


def verify_storage_contract(
    compose: Any,
    *,
    inspect_container: Callable[[str], Any],
    inspect_volume: Callable[[str], Any],
    inspect_image: Callable[[str], Any],
) -> dict[str, Any]:
    """Compare candidate mounts with the exact currently mounted identities."""

    if not isinstance(compose, dict):
        raise StorageContractError("Compose root must be an object")
    services = compose.get("services")
    volumes = compose.get("volumes")
    if not isinstance(services, dict) or not isinstance(volumes, dict):
        raise StorageContractError("Compose services and volumes must be objects")

    proof_rows: list[dict[str, Any]] = []
    contract_rows: list[dict[str, Any]] = []

    def candidate_rows(
        service_name: str, required_targets: frozenset[str]
    ) -> dict[str, Mapping[str, Any]]:
        service = services.get(service_name)
        if not isinstance(service, dict):
            raise StorageContractError(f"missing protected service {service_name}")
        candidate_mounts = service.get("volumes")
        if not isinstance(candidate_mounts, list):
            raise StorageContractError(f"{service_name}.volumes must be a list")
        result: dict[str, Mapping[str, Any]] = {}
        for row in candidate_mounts:
            if not isinstance(row, dict):
                raise StorageContractError(f"{service_name} has a non-object mount")
            target = row.get("target")
            if not isinstance(target, str) or not target.startswith("/"):
                raise StorageContractError(f"{service_name} has an invalid mount target")
            if target in result:
                raise StorageContractError(f"{service_name}:{target} is duplicated")
            result[target] = row
        if frozenset(result) != required_targets:
            raise StorageContractError(
                f"{service_name} mount targets differ from the closed contract"
            )
        return result

    def live_rows_from(
        container: Mapping[str, Any], container_name: str
    ) -> dict[str, Mapping[str, Any]]:
        rows = container.get("Mounts")
        if not isinstance(rows, list):
            raise StorageContractError(f"{container_name}.Mounts must be a list")
        result: dict[str, Mapping[str, Any]] = {}
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("Destination"), str):
                raise StorageContractError(f"{container_name} has an invalid live mount")
            target = row["Destination"]
            if target in result:
                raise StorageContractError(f"{container_name}:{target} is duplicated")
            result[target] = row
        return result

    def live_rows(container_name: str) -> dict[str, Mapping[str, Any]]:
        container = _one_inspect(
            inspect_container(container_name), f"container {container_name}"
        )
        return live_rows_from(container, container_name)

    for service_name, (container_name, required_targets) in PROTECTED_STORAGE.items():
        candidate_by_target = candidate_rows(service_name, required_targets)
        live_container = _one_inspect(
            inspect_container(container_name), f"container {container_name}"
        )
        live_by_target = live_rows_from(live_container, container_name)
        if frozenset(live_by_target) != required_targets:
            raise StorageContractError(
                f"{container_name} live mount targets differ from the closed contract"
            )
        service = services[service_name]
        image_reference = service.get("image")
        if not isinstance(image_reference, str) or not image_reference:
            raise StorageContractError(f"{service_name} image is not rendered")
        image = _one_inspect(inspect_image(image_reference), f"image {service_name}")
        runtime_identity = _runtime_identity(
            compose, service_name, service, live_container, image
        )
        runtime_encoded = json.dumps(
            runtime_identity, separators=(",", ":"), sort_keys=True
        )
        runtime_identity_sha256 = _sha(runtime_encoded)
        # The full identity remains in memory only.  The durable receipt carries
        # its digest and cannot disclose commands, ports, paths or credentials.
        contract_rows.append(
            {
                "service": service_name,
                "kind": "stateful_runtime",
                "runtime": runtime_identity,
            }
        )

        for target in sorted(required_targets):
            candidate = candidate_by_target[target]
            live = live_by_target[target]
            mount_type = candidate.get("type")
            source = candidate.get("source")
            read_only = candidate.get("read_only", False)
            if mount_type not in {"bind", "volume"} or not isinstance(source, str):
                raise StorageContractError(
                    f"{service_name}:{target} must be a named volume or an absolute bind"
                )
            if not isinstance(read_only, bool):
                raise StorageContractError(f"{service_name}:{target} read_only is invalid")
            if live.get("Type") != mount_type or live.get("RW") is not (not read_only):
                raise StorageContractError(f"{service_name}:{target} type/mode differs")

            identity: dict[str, Any] = {
                "service": service_name,
                "container": container_name,
                "target": target,
                "type": mount_type,
                "read_only": read_only,
            }
            if mount_type == "bind":
                if not source.startswith("/") or live.get("Source") != source:
                    raise StorageContractError(f"{service_name}:{target} bind source differs")
                if live.get("Name") not in {None, ""}:
                    raise StorageContractError(f"{service_name}:{target} bind has a volume name")
                identity["source"] = source
            else:
                definition = volumes.get(source)
                if not isinstance(definition, dict):
                    raise StorageContractError(
                        f"{service_name}:{target} references an unknown volume"
                    )
                resolved_name = definition.get("name")
                if not isinstance(resolved_name, str) or not resolved_name:
                    raise StorageContractError(
                        f"{service_name}:{target} volume name is not rendered explicitly"
                    )
                volume = _one_inspect(
                    inspect_volume(resolved_name), f"volume {resolved_name}"
                )
                driver = volume.get("Driver")
                mountpoint = volume.get("Mountpoint")
                if not isinstance(driver, str) or not driver:
                    raise StorageContractError(f"volume {resolved_name} driver is invalid")
                if not isinstance(mountpoint, str) or not mountpoint.startswith("/"):
                    raise StorageContractError(
                        f"volume {resolved_name} mountpoint is invalid"
                    )
                declared_driver = definition.get("driver")
                if declared_driver is not None and declared_driver != driver:
                    raise StorageContractError(
                        f"volume {resolved_name} declared driver differs from live"
                    )
                options_value = volume.get("Options")
                if options_value is None:
                    options: dict[str, str] = {}
                elif isinstance(options_value, dict) and all(
                    isinstance(key, str) and isinstance(value, str)
                    for key, value in options_value.items()
                ):
                    options = dict(options_value)
                else:
                    raise StorageContractError(
                        f"volume {resolved_name} driver options are invalid"
                    )
                declared_options_value = definition.get("driver_opts")
                if declared_options_value is None:
                    declared_options: dict[str, str] = {}
                elif isinstance(declared_options_value, dict) and all(
                    isinstance(key, str) and isinstance(value, str)
                    for key, value in declared_options_value.items()
                ):
                    declared_options = dict(declared_options_value)
                else:
                    raise StorageContractError(
                        f"volume {resolved_name} declared driver options are invalid"
                    )
                expected_bind = EXPECTED_BIND_BACKED_VOLUMES.get(
                    (service_name, target)
                )
                if expected_bind is not None:
                    expected_name, expected_options = expected_bind
                    if (
                        resolved_name != expected_name
                        or driver != "local"
                        or options != expected_options
                        or definition.get("external") is not True
                        or set(definition) != {"name", "external"}
                    ):
                        raise StorageContractError(
                            f"{service_name}:{target} bind-backed volume contract differs"
                        )
                elif options != declared_options:
                    raise StorageContractError(
                        f"volume {resolved_name} driver options differ from candidate"
                    )
                if (
                    volume.get("Name") != resolved_name
                    or live.get("Name") != resolved_name
                    or live.get("Driver") != driver
                    or live.get("Source") != mountpoint
                ):
                    raise StorageContractError(
                        f"{service_name}:{target} volume identity differs from live"
                    )
                identity.update(
                    {
                        "volume_name": resolved_name,
                        "driver": driver,
                        "driver_options": options,
                        "source": mountpoint,
                    }
                )

            encoded = json.dumps(identity, separators=(",", ":"), sort_keys=True)
            contract_rows.append(identity)
            proof_rows.append(
                {
                    "service": service_name,
                    "target": target,
                    "identity_sha256": _sha(encoded),
                    "runtime_identity_sha256": runtime_identity_sha256,
                }
            )

    anchor_cache: dict[str, Mapping[str, Any]] = {}
    for target, (container, live_target) in APPLICATION_ANCHORS.items():
        row = live_rows(container).get(live_target)
        if not isinstance(row, dict) or row.get("Type") != "bind":
            raise StorageContractError(f"live application anchor {target} is invalid")
        if not isinstance(row.get("Source"), str) or not row["Source"].startswith("/"):
            raise StorageContractError(f"live application anchor {target} source is invalid")
        anchor_cache[target] = row

    for service_name, required_targets in APPLICATION_STORAGE.items():
        candidate_by_target = candidate_rows(service_name, required_targets)
        for target in sorted(required_targets):
            candidate = candidate_by_target[target]
            source = candidate.get("source")
            if (
                candidate.get("type") != "bind"
                or not isinstance(source, str)
                or not source.startswith("/")
                or candidate.get("read_only", False) is not True
            ):
                raise StorageContractError(
                    f"{service_name}:{target} must be the canonical read-only bind"
                )
            if source != anchor_cache[target].get("Source"):
                raise StorageContractError(
                    f"{service_name}:{target} source differs from the live anchor"
                )
            identity = {
                "service": service_name,
                "target": target,
                "type": "bind",
                "source": source,
                "read_only": True,
                "live_transition": "rw_or_ro_to_ro",
            }
            encoded = json.dumps(identity, separators=(",", ":"), sort_keys=True)
            contract_rows.append(identity)
            proof_rows.append(
                {
                    "service": service_name,
                    "target": target,
                    "identity_sha256": _sha(encoded),
                }
            )

    contract_encoded = json.dumps(
        contract_rows, separators=(",", ":"), sort_keys=True
    )
    return {
        "schema_version": 1,
        "kind": "agentium-release-a-candidate-storage-contract",
        "result": "passed",
        "protected_service_count": len(PROTECTED_STORAGE) + len(APPLICATION_STORAGE),
        "mount_count": len(proof_rows),
        "contract_sha256": _sha(contract_encoded),
        "mounts": proof_rows,
    }


def _docker_json(*arguments: str) -> Any:
    result = subprocess.run(
        ["docker", *arguments],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise StorageContractError("Docker identity lookup failed")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise StorageContractError("Docker identity lookup returned invalid JSON") from exc


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("verify",))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    _parse_args(sys.argv[1:] if argv is None else argv)
    payload = sys.stdin.buffer.read(MAX_COMPOSE_BYTES + 1)
    if len(payload) > MAX_COMPOSE_BYTES:
        raise StorageContractError("rendered Compose model exceeds the size limit")
    try:
        compose = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StorageContractError("rendered Compose model is invalid JSON") from exc
    receipt = verify_storage_contract(
        compose,
        inspect_container=lambda name: _docker_json("inspect", "--type", "container", name),
        inspect_volume=lambda name: _docker_json("volume", "inspect", name),
        inspect_image=lambda name: _docker_json("image", "inspect", name),
    )
    json.dump(receipt, sys.stdout, separators=(",", ":"), sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except StorageContractError as exc:
        print(f"storage contract rejected: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
