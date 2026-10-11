#!/usr/bin/env python3
"""Prepare, initialise and configure the Agentium OpenBao (stdlib only, runs on the VM host).

    prepare    create the static unseal key (hex, 0400, owned by the OpenBao uid)
               and the raft/audit subdirectories of the protected data path.
    init       sys/init with one recovery key (static seal: no unseal keys),
               then `configure` with the initial root token.
    configure  idempotent: KV v2 at agentium/, check the declarative file audit
               device, AppRole auth, policies and roles backend / worker /
               hub-fetch / snapshot, fresh secret_ids written to
               <runtime-env>/openbao-<role>.env (0600). The root token is
               revoked at the end, success or not. Re-run later with a root
               token regenerated from the recovery key
               (`bao operator generate-root`), passed in BAO_TOKEN.

Nothing secret is ever printed: only file paths and role names.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

MOUNT = "agentium"
AUDIT_PATH = "agentium-file/"
UNSEAL_KEY_NAME = "openbao-unseal.key"
RECOVERY_FILE_NAME = "openbao-recovery.env"

POLICIES = {
    "agentium-backend": f"""
path "{MOUNT}/data/*" {{ capabilities = ["create", "read", "update"] }}
path "{MOUNT}/destroy/*" {{ capabilities = ["update"] }}
path "{MOUNT}/metadata/*" {{ capabilities = ["read", "list"] }}
""",
    "agentium-worker": f"""
path "{MOUNT}/data/*" {{ capabilities = ["read"] }}
""",
    "agentium-hub-fetch": f"""
path "{MOUNT}/data/platform/+/nodes/*" {{ capabilities = ["read"] }}
path "{MOUNT}/data/workspace/+/nodes/*" {{ capabilities = ["read"] }}
""",
    "agentium-snapshot": """
path "sys/storage/raft/snapshot" { capabilities = ["read"] }
""",
}
ROLES = {
    "backend": "agentium-backend",
    "worker": "agentium-worker",
    "hub-fetch": "agentium-hub-fetch",
    "snapshot": "agentium-snapshot",
}
ROLE_SETTINGS = {
    "token_ttl": "1h",
    "token_max_ttl": "4h",
    "secret_id_ttl": "0",
    "secret_id_num_uses": 0,
    "token_no_default_policy": True,
}


class BootstrapError(RuntimeError):
    pass


Request = Callable[..., tuple[int, dict]]


def http_request(
    addr: str, method: str, path: str, *, token: str | None = None, body: dict | None = None
) -> tuple[int, dict]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{addr.rstrip('/')}/v1/{path}", data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("X-Vault-Token", token)
    try:
        with urllib.request.urlopen(req, timeout=10) as response:  # noqa: S310
            raw = response.read()
            return response.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            return exc.code, json.loads(raw) if raw else {}
        except ValueError:
            return exc.code, {}
    except OSError as exc:
        raise BootstrapError(f"OpenBao unreachable at {addr}: {type(exc).__name__}") from exc


def write_private(path: Path, content: str, *, mode: int = 0o600) -> None:
    tmp = path.with_name(f".{path.name}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, content.encode())
        os.fchmod(fd, mode)
    finally:
        os.close(fd)
    os.replace(tmp, path)


def prepare(runtime_env: Path, data_path: Path, uid: int, gid: int) -> None:
    if not runtime_env.is_dir():
        raise BootstrapError(f"{runtime_env} is not a directory")
    if not data_path.is_dir() or data_path.is_symlink():
        raise BootstrapError(f"{data_path} must be a pre-provisioned real directory")
    key = runtime_env / UNSEAL_KEY_NAME
    if key.exists():
        print(f"unseal key already present: {key}")
    else:
        # No trailing newline: the static seal decodes exactly 64 hex characters.
        write_private(key, secrets.token_hex(32), mode=0o400)
        print(f"unseal key written: {key}")
    os.chown(key, uid, gid)
    # Compose requires every overlay env_file to exist before `init` can render
    # the model; empty files leave clients unconfigured, hence fail-closed.
    for role in ROLES:
        placeholder = runtime_env / f"openbao-{role}.env"
        if not placeholder.exists():
            write_private(placeholder, "")
    os.chown(data_path, uid, gid)
    os.chmod(data_path, 0o700)
    for sub in ("raft", "audit"):
        path = data_path / sub
        path.mkdir(mode=0o700, exist_ok=True)
        os.chown(path, uid, gid)
    print(f"data path ready: {data_path}")


def _check(status: int, body: dict, what: str, ok: tuple[int, ...] = (200, 204)) -> dict:
    if status not in ok:
        errors = body.get("errors") if isinstance(body, dict) else None
        raise BootstrapError(f"{what} failed ({status}): {errors or ''}")
    return body


def wait_ready(request: Request, *, attempts: int = 30, delay: float = 2.0) -> dict:
    for _ in range(attempts):
        try:
            status, body = request("GET", "sys/health?sealedcode=200&uninitcode=200")
            if status == 200:
                return body
        except BootstrapError:
            pass
        time.sleep(delay)
    raise BootstrapError("OpenBao did not answer sys/health")


def init(request: Request, runtime_env: Path) -> str:
    health = wait_ready(request)
    if health.get("initialized"):
        raise BootstrapError(
            "OpenBao is already initialised; use `configure` with a regenerated root token"
        )
    body = _check(
        *request("POST", "sys/init", body={"recovery_shares": 1, "recovery_threshold": 1}),
        "sys/init",
    )
    recovery = (body.get("recovery_keys_b64") or body.get("recovery_keys") or [None])[0]
    root = body.get("root_token")
    if not recovery or not root:
        raise BootstrapError("sys/init returned no recovery key or root token")
    write_private(runtime_env / RECOVERY_FILE_NAME, f"OPENBAO_RECOVERY_KEY={recovery}\n")
    print(f"recovery key written: {runtime_env / RECOVERY_FILE_NAME}")
    for _ in range(30):
        if not wait_ready(request).get("sealed"):
            break
        time.sleep(1)
    else:
        raise BootstrapError("OpenBao stayed sealed after init (static seal key?)")
    return root


def configure(request: Request, token: str, runtime_env: Path) -> None:
    try:
        _configure(request, token, runtime_env)
    finally:
        status, _ = request("POST", "auth/token/revoke-self", token=token)
        print("root token revoked" if status in (200, 204) else f"root token revoke: {status}")


def _configure(request: Request, token: str, runtime_env: Path) -> None:
    def call(method: str, path: str, body: dict | None = None, ok=(200, 204)) -> dict:
        return _check(*request(method, path, token=token, body=body), f"{method} {path}", ok)

    mounts = call("GET", "sys/mounts")
    mounts = mounts.get("data", mounts)
    existing = mounts.get(f"{MOUNT}/")
    if existing is None:
        call("POST", f"sys/mounts/{MOUNT}", {"type": "kv", "options": {"version": "2"}})
        print(f"kv-v2 enabled at {MOUNT}/")
    elif existing.get("type") != "kv" or (existing.get("options") or {}).get("version") != "2":
        raise BootstrapError(f"{MOUNT}/ exists but is not a KV v2 mount")

    audits = call("GET", "sys/audit")
    audits = audits.get("data", audits)
    if AUDIT_PATH not in audits:
        raise BootstrapError(f"declarative audit device {AUDIT_PATH} is missing (openbao.hcl)")

    auths = call("GET", "sys/auth")
    auths = auths.get("data", auths)
    if "approle/" not in auths:
        call("POST", "sys/auth/approle", {"type": "approle"})
        print("approle auth enabled")

    for name, policy in POLICIES.items():
        call("PUT", f"sys/policies/acl/{name}", {"policy": policy.strip() + "\n"})
    print(f"policies written: {', '.join(POLICIES)}")

    for role, policy in ROLES.items():
        call("POST", f"auth/approle/role/{role}", {**ROLE_SETTINGS, "token_policies": [policy]})
        role_id = call("GET", f"auth/approle/role/{role}/role-id")["data"]["role_id"]
        secret_id = call("POST", f"auth/approle/role/{role}/secret-id", {})["data"]["secret_id"]
        target = runtime_env / f"openbao-{role}.env"
        write_private(target, f"OPENBAO_ROLE_ID={role_id}\nOPENBAO_SECRET_ID={secret_id}\n")
        print(f"approle {role}: credentials written to {target}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p_prepare = sub.add_parser("prepare")
    p_prepare.add_argument("--runtime-env", type=Path, required=True)
    p_prepare.add_argument("--data-path", type=Path, default=Path("/srv/agentium-data/openbao"))
    p_prepare.add_argument("--uid", type=int, default=100)
    p_prepare.add_argument("--gid", type=int, default=1000)
    for name in ("init", "configure"):
        p = sub.add_parser(name)
        p.add_argument("--addr", required=True, help="e.g. http://<container-ip>:8200")
        p.add_argument("--runtime-env", type=Path, required=True)
    args = parser.parse_args(argv)
    os.umask(0o077)
    try:
        if args.command == "prepare":
            prepare(args.runtime_env, args.data_path, args.uid, args.gid)
            return 0
        if not args.runtime_env.is_dir():
            raise BootstrapError(f"{args.runtime_env} is not a directory")

        def request(method, path, **kwargs):
            return http_request(args.addr, method, path, **kwargs)

        if args.command == "init":
            token = init(request, args.runtime_env)
        else:
            token = os.environ.get("BAO_TOKEN", "").strip()
            if not token:
                raise BootstrapError("BAO_TOKEN (regenerated root token) is required")
        configure(request, token, args.runtime_env)
    except BootstrapError as exc:
        print(f"openbao bootstrap failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
