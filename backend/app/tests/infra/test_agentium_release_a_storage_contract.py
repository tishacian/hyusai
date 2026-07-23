"""Closed contract tests for Release A candidate stateful mounts."""

from __future__ import annotations

import ast
import copy
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
SPEC = importlib.util.spec_from_file_location(
    "agentium_release_a_storage_contract_test",
    ROOT / "scripts" / "agentium_release_a_storage_contract.py",
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
StorageContractError = MODULE.StorageContractError
verify_storage_contract = MODULE.verify_storage_contract


def _fixtures() -> tuple[
    dict, dict[str, list[dict]], dict[str, list[dict]], dict[str, list[dict]]
]:
    specifications = {
        "agentium-pg": (
            "agentium-pg",
            {"/var/lib/postgresql/data": ("volume", "pg", "agentium_pgdata")},
        ),
        "agentium-rabbitmq": (
            "agentium-rabbitmq",
            {"/var/lib/rabbitmq": ("volume", "rabbit", "agentium_rabbitmq")},
        ),
        "agentium-qdrant": (
            "qdrant",
            {
                "/qdrant/storage": (
                    "volume",
                    "qdrant",
                    "agentium_qdrant_block",
                ),
                "/qdrant/snapshots": ("bind", "/srv/agentium-data/qdrant_snapshots", ""),
            },
        ),
        "agentium-minio": (
            "agentium-minio",
            {"/data": ("volume", "minio", "agentium_minio_block")},
        ),
    }
    published_ports = {
        "agentium-pg": [(5432, 5432)],
        "agentium-rabbitmq": [(5672, 5672), (15672, 15672)],
        "agentium-qdrant": [(6333, 6333), (6334, 6334)],
        "agentium-minio": [(9000, 9000), (9001, 9001)],
    }
    compose: dict = {
        "services": {},
        "volumes": {},
        "networks": {"agentium-net": {"name": "agentium-net", "external": True}},
    }
    containers: dict[str, list[dict]] = {}
    volumes: dict[str, list[dict]] = {}
    images: dict[str, list[dict]] = {}
    for service, (container, mounts) in specifications.items():
        image_reference = f"example/{service}:pinned"
        image_id = f"sha256:{service.encode().hex():0<64}"[:71]
        image_command = ["run"]
        effective_command = image_command
        if service == "agentium-minio":
            effective_command = ["server", "/data", "--console-address", ":9001"]
        compose["services"][service] = {
            "image": image_reference,
            "networks": {"agentium-net": None},
            "ports": [
                {
                    "mode": "ingress",
                    "target": target,
                    "published": str(published),
                    "protocol": "tcp",
                    "host_ip": "127.0.0.1",
                }
                for target, published in published_ports[service]
            ],
            "volumes": [],
        }
        if service == "agentium-minio":
            compose["services"][service]["command"] = effective_command
        if service == "agentium-qdrant":
            compose["services"][service]["environment"] = {
                "QDRANT__SERVICE__API_KEY": "admin-secret-not-emitted",
                "QDRANT__SERVICE__READ_ONLY_API_KEY": "read-only-secret-not-emitted",
            }
        images[image_reference] = [
            {
                "Id": image_id,
                "Config": {
                    "Entrypoint": ["/entrypoint"],
                    "Cmd": image_command,
                    "User": "1000:1000",
                    "Env": ["PATH=/usr/bin"],
                },
            }
        ]
        live_mounts = []
        for target, (kind, source, resolved) in mounts.items():
            if kind == "volume":
                logical = f"logical_{source}"
                mountpoint = f"/var/lib/docker/volumes/{resolved}/_data"
                if resolved in {"agentium_qdrant_block", "agentium_minio_block"}:
                    compose["volumes"][logical] = {
                        "name": resolved,
                        "external": True,
                    }
                    device = (
                        "/srv/agentium-data/qdrant"
                        if resolved == "agentium_qdrant_block"
                        else "/srv/agentium-data/minio"
                    )
                    options = {"device": device, "o": "bind", "type": "none"}
                else:
                    compose["volumes"][logical] = {"name": resolved}
                    options = None
                compose["services"][service]["volumes"].append(
                    {"type": "volume", "source": logical, "target": target}
                )
                volumes[resolved] = [
                    {
                        "Name": resolved,
                        "Driver": "local",
                        "Mountpoint": mountpoint,
                        "Options": options,
                    }
                ]
                live_mounts.append(
                    {
                        "Type": "volume",
                        "Name": resolved,
                        "Driver": "local",
                        "Source": mountpoint,
                        "Destination": target,
                        "RW": True,
                    }
                )
            else:
                compose["services"][service]["volumes"].append(
                    {"type": "bind", "source": source, "target": target}
                )
                live_mounts.append(
                    {
                        "Type": "bind",
                        "Name": "",
                        "Source": source,
                        "Destination": target,
                        "RW": True,
                    }
                )
        port_bindings = {
            f"{target}/tcp": [
                {"HostIp": "127.0.0.1", "HostPort": str(published)}
            ]
            for target, published in published_ports[service]
        }
        containers[container] = [
            {
                "Image": image_id,
                "Config": {
                    "Image": image_reference,
                    "Entrypoint": ["/entrypoint"],
                    "Cmd": effective_command,
                    "User": "1000:1000",
                    "Env": ["PATH=/usr/bin"],
                },
                "HostConfig": {
                    "NetworkMode": "agentium-net",
                    "PortBindings": port_bindings,
                    "CapAdd": None,
                    "CapDrop": None,
                    "SecurityOpt": None,
                    "Privileged": False,
                    "ReadonlyRootfs": False,
                },
                "NetworkSettings": {
                    "Networks": {"agentium-net": {}},
                    "Ports": copy.deepcopy(port_bindings),
                },
                "Mounts": live_mounts,
            }
        ]
    application_sources = {
        "/data/object_store": "/srv/agentium-data/object_store",
        "/data/secure_deposit": "/home/ubuntu/omnirag/backend/data/secure_deposit",
        "/data/faiss_db": "/home/ubuntu/omnirag/backend/faiss_db",
    }
    containers["agentium-backend"] = [
        {
            "Mounts": [
                {
                    "Type": "bind",
                    "Name": "",
                    "Source": source,
                    "Destination": target,
                    "RW": True,
                }
                for target, source in application_sources.items()
            ]
        }
    ]
    containers["agentium-sftp"] = [
        {
            "Mounts": [
                {
                    "Type": "bind",
                    "Name": "",
                    "Source": application_sources["/data/secure_deposit"],
                    "Destination": "/data/secure_deposit",
                    "RW": True,
                }
            ]
        }
    ]
    for service, targets in {
        "agentium-backend": application_sources,
        "agentium-worker-cpu": application_sources,
        "agentium-p4-maintenance": application_sources,
        "agentium-migrate": application_sources,
        "agentium-sftp": {
            "/data/secure_deposit": application_sources["/data/secure_deposit"]
        },
    }.items():
        compose["services"][service] = {
            "volumes": [
                {
                    "type": "bind",
                    "source": source,
                    "target": target,
                    "read_only": True,
                }
                for target, source in targets.items()
            ]
        }
    return compose, containers, volumes, images


def _verify(compose: dict, containers: dict, volumes: dict, images: dict) -> dict:
    return verify_storage_contract(
        compose,
        inspect_container=lambda name: containers[name],
        inspect_volume=lambda name: volumes[name],
        inspect_image=lambda name: images[name],
    )


def test_exact_candidate_and_live_storage_contract_passes_content_free() -> None:
    compose, containers, volumes, images = _fixtures()
    receipt = _verify(compose, containers, volumes, images)

    assert receipt["result"] == "passed"
    assert receipt["protected_service_count"] == 9
    assert receipt["mount_count"] == 18
    encoded = str(receipt)
    assert "/srv/agentium-data" not in encoded
    assert "/var/lib/docker" not in encoded
    assert "agentium_pgdata" not in encoded
    assert "example/agentium" not in encoded
    assert "agentium-net" not in encoded
    assert "127.0.0.1" not in encoded
    assert "/entrypoint" not in encoded
    assert "admin-secret-not-emitted" not in encoded
    assert "QDRANT__SERVICE__API_KEY" not in encoded
    runtime_proofs = [
        row for row in receipt["mounts"] if "runtime_identity_sha256" in row
    ]
    assert len(runtime_proofs) == 5
    assert all(len(row["runtime_identity_sha256"]) == 64 for row in runtime_proofs)


@pytest.mark.parametrize("difference", ["candidate", "live", "driver", "mode"])
def test_any_storage_identity_difference_fails_closed(difference: str) -> None:
    compose, containers, volumes, images = _fixtures()
    compose = copy.deepcopy(compose)
    containers = copy.deepcopy(containers)
    volumes = copy.deepcopy(volumes)
    if difference == "candidate":
        compose["volumes"]["logical_qdrant"]["name"] = "other_qdrant_data"
        volumes["other_qdrant_data"] = volumes["agentium_qdrant_block"]
    elif difference == "live":
        containers["qdrant"][0]["Mounts"][0]["Source"] = "/wrong"
    elif difference == "driver":
        volumes["agentium_qdrant_block"][0]["Driver"] = "other"
    else:
        containers["qdrant"][0]["Mounts"][0]["RW"] = False

    with pytest.raises(StorageContractError):
        _verify(compose, containers, volumes, images)


def test_extra_or_missing_mount_target_fails_closed() -> None:
    compose, containers, volumes, images = _fixtures()
    compose["services"]["agentium-minio"]["volumes"].append(
        {"type": "bind", "source": "/tmp/other", "target": "/other"}
    )

    with pytest.raises(StorageContractError):
        _verify(compose, containers, volumes, images)


@pytest.mark.parametrize("difference", ["rebound", "writable"])
def test_application_storage_allows_only_same_source_to_read_only(
    difference: str,
) -> None:
    compose, containers, volumes, images = _fixtures()
    row = compose["services"]["agentium-worker-cpu"]["volumes"][0]
    if difference == "rebound":
        row["source"] = "/srv/other"
    else:
        row["read_only"] = False

    with pytest.raises(StorageContractError):
        _verify(compose, containers, volumes, images)


@pytest.mark.parametrize(
    "difference",
    [
        "resolved_image_id",
        "image_reference",
        "entrypoint",
        "command",
        "user",
        "network_mode",
        "attached_network",
        "candidate_port",
        "runtime_port",
        "cap_add",
        "cap_drop",
        "security_opt",
        "privileged",
        "read_only_rootfs",
        "non_allowlisted_environment",
        "minio_environment",
    ],
)
def test_any_stateful_runtime_identity_difference_fails_closed(
    difference: str,
) -> None:
    compose, containers, volumes, images = _fixtures()
    compose = copy.deepcopy(compose)
    containers = copy.deepcopy(containers)
    images = copy.deepcopy(images)
    service = compose["services"]["agentium-qdrant"]
    live = containers["qdrant"][0]
    image_reference = service["image"]

    if difference == "resolved_image_id":
        images[image_reference][0]["Id"] = "sha256:" + "f" * 64
    elif difference == "image_reference":
        replacement = "example/agentium-qdrant:other"
        images[replacement] = copy.deepcopy(images[image_reference])
        service["image"] = replacement
    elif difference == "entrypoint":
        service["entrypoint"] = ["/other-entrypoint"]
    elif difference == "command":
        service["command"] = ["other-command"]
    elif difference == "user":
        service["user"] = "0"
    elif difference == "network_mode":
        live["HostConfig"]["NetworkMode"] = "bridge"
    elif difference == "attached_network":
        live["NetworkSettings"]["Networks"] = {"other-network": {}}
    elif difference == "candidate_port":
        service["ports"][0]["published"] = "16333"
    elif difference == "runtime_port":
        live["NetworkSettings"]["Ports"]["6333/tcp"][0]["HostPort"] = "16333"
    elif difference == "cap_add":
        service["cap_add"] = ["SYS_ADMIN"]
    elif difference == "cap_drop":
        service["cap_drop"] = ["NET_RAW"]
    elif difference == "security_opt":
        service["security_opt"] = ["no-new-privileges:true"]
    elif difference == "privileged":
        service["privileged"] = True
    elif difference == "read_only_rootfs":
        service["read_only"] = True
    elif difference == "non_allowlisted_environment":
        service["environment"]["QDRANT__LOG_LEVEL"] = "debug"
    else:
        compose["services"]["agentium-minio"]["environment"] = {
            "MINIO_DOMAIN": "other.invalid"
        }

    with pytest.raises(StorageContractError):
        _verify(compose, containers, volumes, images)


def test_qdrant_auth_rotation_is_the_only_allowed_runtime_delta() -> None:
    compose, containers, volumes, images = _fixtures()
    containers["qdrant"][0]["Config"]["Env"].extend(
        [
            "QDRANT__SERVICE__API_KEY=previous-admin-secret",
            "QDRANT__SERVICE__READ_ONLY_API_KEY=previous-read-only-secret",
        ]
    )

    receipt = _verify(compose, containers, volumes, images)

    assert receipt["result"] == "passed"
    assert "previous-admin-secret" not in str(receipt)
    assert "read-only-secret-not-emitted" not in str(receipt)


@pytest.mark.parametrize("difference", ["missing_admin", "missing_read_only", "same"])
def test_qdrant_candidate_requires_two_distinct_auth_values(difference: str) -> None:
    compose, containers, volumes, images = _fixtures()
    environment = compose["services"]["agentium-qdrant"]["environment"]
    if difference == "missing_admin":
        environment.pop("QDRANT__SERVICE__API_KEY")
    elif difference == "missing_read_only":
        environment.pop("QDRANT__SERVICE__READ_ONLY_API_KEY")
    else:
        environment["QDRANT__SERVICE__READ_ONLY_API_KEY"] = environment[
            "QDRANT__SERVICE__API_KEY"
        ]

    with pytest.raises(StorageContractError):
        _verify(compose, containers, volumes, images)


def test_non_digest_docker_image_id_fails_closed() -> None:
    compose, containers, volumes, images = _fixtures()
    image_reference = compose["services"]["agentium-minio"]["image"]
    images[image_reference][0]["Id"] = "example/agentium-minio:pinned"
    containers["agentium-minio"][0]["Image"] = "example/agentium-minio:pinned"

    with pytest.raises(StorageContractError):
        _verify(compose, containers, volumes, images)


@pytest.mark.parametrize(
    "difference", ["device", "mount_option", "type", "external", "extra_definition"]
)
def test_bind_backed_volume_driver_contract_fails_closed(difference: str) -> None:
    compose, containers, volumes, images = _fixtures()
    definition = compose["volumes"]["logical_qdrant"]
    volume = volumes["agentium_qdrant_block"][0]
    if difference == "device":
        volume["Options"]["device"] = "/srv/agentium-data/other"
    elif difference == "mount_option":
        volume["Options"]["o"] = "rw"
    elif difference == "type":
        volume["Options"]["type"] = "tmpfs"
    elif difference == "external":
        definition["external"] = False
    else:
        definition["driver"] = "local"

    with pytest.raises(StorageContractError):
        _verify(compose, containers, volumes, images)


def test_helper_contains_no_optimisation_sensitive_assert_gate() -> None:
    tree = ast.parse(
        (ROOT / "scripts" / "agentium_release_a_storage_contract.py").read_text(
            encoding="utf-8"
        )
    )

    assert not any(isinstance(node, ast.Assert) for node in ast.walk(tree))
