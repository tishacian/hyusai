#!/usr/bin/env python3
"""Attest the Qdrant write barrier used during a closed deployment canary.

The script deliberately never accepts an API key as a CLI argument and never
serializes key material or key digests.  ``host-contract`` reads the effective
container environments through Docker.  ``probe-client`` is suitable for
``docker exec ... python -m scripts.audit_qdrant_write_barrier`` and uses only
the effective ``QDRANT_API_KEY`` already present in that container.

The negative write probe is safe even if authentication is misconfigured: it
first proves that a deployment-specific guard collection does not exist, then
attempts to delete only that absent collection. A genuine read-only key must
reject the operation; an expected admin key must admit the route and return
not-found. The collection is checked again afterwards, while the absent target
guarantees that neither profile can delete business data.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SHA_RE = re.compile(r"^[0-9a-f]{40}$")
DEPLOYMENT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{5,95}$")
HOST_RE = re.compile(r"^[A-Za-z0-9_.:-]+$")
CONTAINER_ID_RE = re.compile(r"^[0-9a-f]{12,64}$")
LOOPBACK_HOSTS = {"127.0.0.1", "::1"}
AUTH_REJECTION_CODES = {401, 403}
MIN_KEY_LENGTH = 32
DEFAULT_QDRANT_IMAGE = "qdrant/qdrant:v1.12.5-unprivileged"
CLIENT_ACCESS_MODES = {"read-only", "admin"}


class QdrantBarrierError(RuntimeError):
    """Fail-closed barrier error whose message never contains key material."""


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _validate_identity(sha: str, deployment_id: str) -> None:
    if not SHA_RE.fullmatch(sha):
        raise QdrantBarrierError("sha must be a complete lowercase Git SHA")
    if not DEPLOYMENT_ID_RE.fullmatch(deployment_id):
        raise QdrantBarrierError("deployment-id is invalid")


def _run_json(command: Sequence[str]) -> Any:
    try:
        completed = subprocess.run(
            list(command),
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise QdrantBarrierError(
            f"command failed without exposing its output: {command[0]}"
        ) from exc
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise QdrantBarrierError(f"command returned invalid JSON: {command[0]}") from exc


def _inspect_container(name: str) -> dict[str, Any]:
    payload = _run_json(["docker", "inspect", name])
    if not isinstance(payload, list) or len(payload) != 1 or not isinstance(payload[0], dict):
        raise QdrantBarrierError(f"invalid Docker inspection for {name}")
    return payload[0]


def _docker_running_names() -> list[str]:
    try:
        completed = subprocess.run(
            ["docker", "ps", "--filter", "status=running", "--format", "{{.Names}}"],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise QdrantBarrierError("cannot inventory running Docker containers") from exc
    names = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    if len(names) != len(set(names)):
        raise QdrantBarrierError("duplicate Docker container names")
    return names


def _environment(inspect: Mapping[str, Any]) -> dict[str, str]:
    raw = inspect.get("Config", {}).get("Env", [])
    if not isinstance(raw, list):
        raise QdrantBarrierError("invalid Docker environment inventory")
    result: dict[str, str] = {}
    for item in raw:
        if not isinstance(item, str) or "=" not in item:
            continue
        key, value = item.split("=", 1)
        result[key] = value
    return result


def _networks(inspect: Mapping[str, Any]) -> set[str]:
    raw = inspect.get("NetworkSettings", {}).get("Networks", {})
    if not isinstance(raw, dict):
        raise QdrantBarrierError("invalid Docker network inventory")
    return {str(name) for name in raw}


def _assert_qdrant_ports_loopback(inspect: Mapping[str, Any]) -> dict[str, Any]:
    raw = inspect.get("NetworkSettings", {}).get("Ports", {})
    if not isinstance(raw, dict):
        raise QdrantBarrierError("invalid Qdrant port inventory")
    checked = 0
    for port in ("6333/tcp", "6334/tcp"):
        bindings = raw.get(port)
        if not isinstance(bindings, list) or not bindings:
            raise QdrantBarrierError(f"Qdrant {port} is not published on loopback")
        for binding in bindings:
            if not isinstance(binding, dict) or binding.get("HostIp") not in LOOPBACK_HOSTS:
                raise QdrantBarrierError(f"Qdrant {port} has a non-loopback binding")
            if not str(binding.get("HostPort") or "").isdigit():
                raise QdrantBarrierError(f"Qdrant {port} has an invalid host port")
            checked += 1
    return {"published_bindings_checked": checked, "loopback_only": True}


def _assert_server_keys(env: Mapping[str, str]) -> tuple[str, str]:
    admin = env.get("QDRANT__SERVICE__API_KEY", "")
    read_only = env.get("QDRANT__SERVICE__READ_ONLY_API_KEY", "")
    if len(admin) < MIN_KEY_LENGTH:
        raise QdrantBarrierError("Qdrant admin API key is absent or too short")
    if len(read_only) < MIN_KEY_LENGTH:
        raise QdrantBarrierError("Qdrant read-only API key is absent or too short")
    if admin == read_only:
        raise QdrantBarrierError("Qdrant admin and read-only API keys are not distinct")
    return admin, read_only


def _http_status(
    base_url: str,
    method: str,
    path: str,
    *,
    api_key: str | None,
) -> tuple[int, Any | None]:
    headers = {"Accept": "application/json"}
    if api_key:
        headers["api-key"] = api_key
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        method=method,
        headers=headers,
    )
    # Qdrant is an internal/loopback dependency. Never leak its credential to
    # an HTTP(S)_PROXY inherited from the operator shell or application image.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=15) as response:  # noqa: S310 - validated internal endpoint.
            status = int(response.status)
            body = response.read(16 * 1024 * 1024)
    except urllib.error.HTTPError as exc:
        # Never include the response body: an upstream proxy must not be able to
        # inject secrets into the deployment log.
        return int(exc.code), None
    except (OSError, urllib.error.URLError) as exc:
        raise QdrantBarrierError("Qdrant endpoint is unreachable") from exc
    if not body:
        return status, None
    try:
        return status, json.loads(body)
    except json.JSONDecodeError as exc:
        raise QdrantBarrierError("Qdrant returned non-JSON success content") from exc


def _guard_collection_name(sha: str, deployment_id: str) -> str:
    suffix = hashlib.sha256(deployment_id.encode("utf-8")).hexdigest()[:16]
    return f"agentium_guard_absent_{sha[:16]}_{suffix}"


def probe_key_access(
    *,
    base_url: str,
    api_key: str,
    sha: str,
    deployment_id: str,
    expected_access: str,
) -> dict[str, Any]:
    """Prove access using a DELETE that can never target business data."""
    if not api_key:
        raise QdrantBarrierError("effective Qdrant client key is absent")
    if expected_access not in CLIENT_ACCESS_MODES:
        raise QdrantBarrierError("expected Qdrant client access is invalid")
    unauthenticated_status, _ = _http_status(base_url, "GET", "/collections", api_key=None)
    if unauthenticated_status not in AUTH_REJECTION_CODES:
        raise QdrantBarrierError("Qdrant permits unauthenticated collection reads")

    read_status, read_payload = _http_status(base_url, "GET", "/collections", api_key=api_key)
    collections = (
        read_payload.get("result", {}).get("collections")
        if isinstance(read_payload, dict)
        else None
    )
    if read_status != 200 or not isinstance(collections, list):
        raise QdrantBarrierError("effective Qdrant client key cannot read collections")

    guard = urllib.parse.quote(_guard_collection_name(sha, deployment_id), safe="")
    before_status, _ = _http_status(base_url, "GET", f"/collections/{guard}", api_key=api_key)
    if before_status != 404:
        raise QdrantBarrierError("safe Qdrant guard collection is unexpectedly present")

    mutation_status, _ = _http_status(base_url, "DELETE", f"/collections/{guard}", api_key=api_key)
    if expected_access == "read-only":
        if mutation_status not in AUTH_REJECTION_CODES:
            raise QdrantBarrierError("effective Qdrant client key is not read-only")
        write_rejected = True
        write_route_authorized = False
    else:
        # Authorization precedes collection lookup in Qdrant. A 404 for this
        # proven-absent target demonstrates that the write route was admitted,
        # without ever creating, changing or deleting a collection.
        if mutation_status != 404:
            raise QdrantBarrierError("effective Qdrant admin key cannot access the write route")
        write_rejected = False
        write_route_authorized = True

    after_status, _ = _http_status(base_url, "GET", f"/collections/{guard}", api_key=api_key)
    if after_status != 404:
        raise QdrantBarrierError("safe Qdrant guard collection changed during probe")

    return {
        "unauthenticated_read_status": unauthenticated_status,
        "authenticated_read_status": read_status,
        "absent_guard_before_status": before_status,
        "delete_status": mutation_status,
        "absent_guard_after_status": after_status,
        "collection_count": len(collections),
        "expected_access": expected_access,
        "read_allowed": True,
        "write_rejected": write_rejected,
        "write_route_authorized": write_route_authorized,
        "guard_remained_absent": True,
    }


def probe_read_only_key(
    *,
    base_url: str,
    api_key: str,
    sha: str,
    deployment_id: str,
) -> dict[str, Any]:
    """Backward-compatible wrapper for the closed-phase probe."""
    return probe_key_access(
        base_url=base_url,
        api_key=api_key,
        sha=sha,
        deployment_id=deployment_id,
        expected_access="read-only",
    )


def _client_base_url(env: Mapping[str, str]) -> str:
    host = env.get("QDRANT_HOST", "").strip()
    port = env.get("QDRANT_PORT", "6333").strip()
    https = env.get("QDRANT_HTTPS", "false").strip().lower()
    if not host or not HOST_RE.fullmatch(host) or "/" in host or "@" in host:
        raise QdrantBarrierError("QDRANT_HOST is invalid")
    if not port.isdigit() or not 1 <= int(port) <= 65535:
        raise QdrantBarrierError("QDRANT_PORT is invalid")
    if https not in {"true", "false", "1", "0"}:
        raise QdrantBarrierError("QDRANT_HTTPS is invalid")
    scheme = "https" if https in {"true", "1"} else "http"
    return f"{scheme}://{host}:{port}"


def _client_container_id() -> str:
    try:
        value = Path("/etc/hostname").read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise QdrantBarrierError("client container identity is unreadable") from exc
    if not CONTAINER_ID_RE.fullmatch(value):
        raise QdrantBarrierError("client container identity is not a Docker runtime id")
    return value


def _validate_host_qdrant_url(value: str) -> str:
    try:
        parsed = urllib.parse.urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise QdrantBarrierError("Qdrant host URL is invalid") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or port is None
        or not 1 <= port <= 65535
    ):
        raise QdrantBarrierError("Qdrant host URL must be a credential-free loopback endpoint")
    return value.rstrip("/")


def build_client_probe(
    *, sha: str, deployment_id: str, expected_access: str = "read-only"
) -> dict[str, Any]:
    _validate_identity(sha, deployment_id)
    key = os.environ.get("QDRANT_API_KEY", "")
    probe = probe_key_access(
        base_url=_client_base_url(os.environ),
        api_key=key,
        sha=sha,
        deployment_id=deployment_id,
        expected_access=expected_access,
    )
    profile = (
        "agentium-qdrant-read-only-client-v1"
        if expected_access == "read-only"
        else "agentium-qdrant-admin-ready-client-v1"
    )
    return {
        "schema_version": 1,
        "kind": "agentium_qdrant_client_write_barrier",
        "profile": profile,
        "deployment_id": deployment_id,
        "sha": sha,
        "captured_at": _utc_now(),
        "result": "passed",
        "client_identity": {"container_id": _client_container_id()},
        "probe": probe,
        "secrets_serialized": False,
        "assurance": (
            "server_rejected_absent_target_delete"
            if expected_access == "read-only"
            else "server_authorized_absent_target_delete"
        ),
    }


def build_host_contract(
    *,
    sha: str,
    deployment_id: str,
    qdrant_container: str,
    client_containers: Sequence[str],
    qdrant_url: str,
    expected_image: str,
    expected_network: str,
    expected_client_access: str = "read-only",
    running_names: Sequence[str] | None = None,
) -> dict[str, Any]:
    _validate_identity(sha, deployment_id)
    if not client_containers:
        raise QdrantBarrierError("at least one candidate client container is required")
    if len(client_containers) != len(set(client_containers)):
        raise QdrantBarrierError("candidate client container names must be unique")
    qdrant_url = _validate_host_qdrant_url(qdrant_url)

    qdrant = _inspect_container(qdrant_container)
    if qdrant.get("State", {}).get("Running") is not True:
        raise QdrantBarrierError("Qdrant container is not running")
    if qdrant.get("Config", {}).get("Image") != expected_image:
        raise QdrantBarrierError("Qdrant image is not the pinned deployment image")
    qdrant_networks = _networks(qdrant)
    if expected_network not in qdrant_networks:
        raise QdrantBarrierError("Qdrant is not attached to the expected internal network")
    port_contract = _assert_qdrant_ports_loopback(qdrant)
    admin, read_only = _assert_server_keys(_environment(qdrant))
    if expected_client_access not in CLIENT_ACCESS_MODES:
        raise QdrantBarrierError("expected Qdrant client access is invalid")
    expected_client_key = read_only if expected_client_access == "read-only" else admin

    client_identities: dict[str, dict[str, str]] = {}
    for name in client_containers:
        client = _inspect_container(name)
        if client.get("State", {}).get("Running") is not True:
            raise QdrantBarrierError(f"candidate Qdrant client is not running: {name}")
        if expected_network not in _networks(client):
            raise QdrantBarrierError(f"candidate client is outside the Qdrant network: {name}")
        if _environment(client).get("QDRANT_API_KEY", "") != expected_client_key:
            if expected_client_access == "read-only":
                raise QdrantBarrierError(f"candidate client does not use the read-only key: {name}")
            raise QdrantBarrierError(f"candidate client does not use the admin key: {name}")
        client_id = str(client.get("Id") or "")
        runtime_id = str(client.get("Config", {}).get("Hostname") or "")
        if not CONTAINER_ID_RE.fullmatch(client_id):
            raise QdrantBarrierError(f"candidate client has no immutable container id: {name}")
        if not CONTAINER_ID_RE.fullmatch(runtime_id) or not client_id.startswith(runtime_id):
            raise QdrantBarrierError(
                f"candidate client runtime identity does not match Docker inspect: {name}"
            )
        client_identities[name] = {
            "container_id": runtime_id,
            "docker_inspect_id": client_id,
        }

    peer_names = list(running_names) if running_names is not None else _docker_running_names()
    qdrant_id = str(qdrant.get("Id") or "")
    qdrant_image_id = str(qdrant.get("Image") or "")
    if not qdrant_id or not qdrant_image_id:
        raise QdrantBarrierError("Qdrant immutable container/image identity is absent")
    peer_count = 0
    credentialed_peer_count = 0
    for name in peer_names:
        if name == qdrant_container:
            continue
        peer = _inspect_container(name)
        if expected_network not in _networks(peer):
            continue
        peer_count += 1
        key = _environment(peer).get("QDRANT_API_KEY", "")
        if not key:
            continue
        credentialed_peer_count += 1
        if key != expected_client_key:
            # This also rejects granular JWTs, unknown keys and credentials
            # left over from another deployment phase.
            message = (
                "a running internal-network peer retains a non-read-only Qdrant credential"
                if expected_client_access == "read-only"
                else "a running internal-network peer retains a non-admin Qdrant credential"
            )
            raise QdrantBarrierError(message)

    admin_status, admin_payload = _http_status(qdrant_url, "GET", "/collections", api_key=admin)
    admin_collections = (
        admin_payload.get("result", {}).get("collections")
        if isinstance(admin_payload, dict)
        else None
    )
    if admin_status != 200 or not isinstance(admin_collections, list):
        raise QdrantBarrierError("Qdrant admin key cannot read collections")
    cluster_status, cluster_payload = _http_status(qdrant_url, "GET", "/cluster", api_key=admin)
    cluster = cluster_payload.get("result") if isinstance(cluster_payload, dict) else None
    if (
        cluster_status != 200
        or not isinstance(cluster, dict)
        or cluster.get("status") != "disabled"
        or cluster.get("peers") not in ({}, None)
    ):
        raise QdrantBarrierError("Qdrant is not the expected standalone single-node deployment")
    probe = probe_key_access(
        base_url=qdrant_url,
        api_key=expected_client_key,
        sha=sha,
        deployment_id=deployment_id,
        expected_access=expected_client_access,
    )
    if len(admin_collections) != probe["collection_count"]:
        raise QdrantBarrierError("Qdrant collection inventory changed during barrier probe")

    return {
        "schema_version": 1,
        "kind": "agentium_qdrant_write_barrier",
        "profile": (
            "agentium-qdrant-read-only-validation-v1"
            if expected_client_access == "read-only"
            else "agentium-qdrant-admin-ready-v1"
        ),
        "deployment_id": deployment_id,
        "sha": sha,
        "captured_at": _utc_now(),
        "result": "passed",
        "qdrant": {
            "container_id": qdrant_id,
            "image_id": qdrant_image_id,
            "image": expected_image,
            "internal_network_present": True,
            "port_contract": port_contract,
            "admin_key_present": True,
            "read_only_key_present": True,
            "keys_distinct": True,
            "cluster_mode": "standalone",
        },
        "clients": {
            "expected_count": len(client_containers),
            "identities": dict(sorted(client_identities.items())),
            "container_id_by_name": {
                name: identity["container_id"]
                for name, identity in sorted(client_identities.items())
            },
            "all_running": True,
            "expected_access": expected_client_access,
            "all_expected_access": True,
            "all_read_only": expected_client_access == "read-only",
            "all_admin_ready": expected_client_access == "admin",
        },
        "network_guard": {
            "running_peer_count": peer_count,
            "credentialed_peer_count": credentialed_peer_count,
            "non_read_only_peer_count": 0,
        },
        "probe": probe,
        "secrets_serialized": False,
        "assurance": (
            "server_key_separation_plus_negative_write_probe"
            if expected_client_access == "read-only"
            else "server_key_separation_plus_admin_ready_probe"
        ),
        "proof_ceiling": "runner_verified",
        "limitations": [
            "trusted host administrators remain outside the container credential barrier",
            "logical immutability is paired with a separate before/after inventory",
            "this is not block-device disaster recovery",
        ],
    }


def _write_json(payload: Mapping[str, Any], destination: str) -> None:
    serialized = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if destination == "-":
        sys.stdout.write(serialized)
        return
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        parent_descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(parent_descriptor)
        finally:
            os.close(parent_descriptor)
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    probe = subparsers.add_parser("probe-client")
    probe.add_argument("--sha", required=True)
    probe.add_argument("--deployment-id", required=True)
    probe.add_argument(
        "--expected-access", choices=sorted(CLIENT_ACCESS_MODES), default="read-only"
    )
    probe.add_argument("--output", default="-")

    host = subparsers.add_parser("host-contract")
    host.add_argument("--sha", required=True)
    host.add_argument("--deployment-id", required=True)
    host.add_argument("--qdrant-container", default="qdrant")
    host.add_argument("--client-container", action="append", required=True)
    host.add_argument("--qdrant-url", default="http://127.0.0.1:6333")
    host.add_argument("--expected-image", default=DEFAULT_QDRANT_IMAGE)
    host.add_argument("--expected-network", default="agentium-net")
    host.add_argument(
        "--expected-client-access",
        choices=sorted(CLIENT_ACCESS_MODES),
        default="read-only",
    )
    host.add_argument("--output", default="-")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "probe-client":
            payload = build_client_probe(
                sha=args.sha,
                deployment_id=args.deployment_id,
                expected_access=args.expected_access,
            )
        else:
            payload = build_host_contract(
                sha=args.sha,
                deployment_id=args.deployment_id,
                qdrant_container=args.qdrant_container,
                client_containers=args.client_container,
                qdrant_url=args.qdrant_url,
                expected_image=args.expected_image,
                expected_network=args.expected_network,
                expected_client_access=args.expected_client_access,
            )
        _write_json(payload, args.output)
    except QdrantBarrierError as exc:
        print(f"Qdrant write barrier failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
