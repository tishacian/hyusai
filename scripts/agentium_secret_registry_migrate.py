#!/usr/bin/env python3
"""Move connector secrets from legacy envelopes into the secret registry.

Each legacy envelope in ``workspaces.settings`` (and the platform Hub token in
``hf_platform_config``) is decrypted with its service's old key, stored as a
registry secret with a derived name, and replaced by ``{"ref": "secret://..."}``.
Fields already holding a reference are skipped, so the script is idempotent.

Order: catalog connectors (Hub token included), MCP, RPA, HANA, LLM portal,
Client360 SMTP, platform Hub token.

Before writing, ``workspaces.settings`` and the platform Hub connection are
saved to a 0600 JSON backup. ``--dry-run`` writes nothing (no backup either)
and only checks that every envelope decrypts. Output names fields and secret
names, never values.

Needs the old per-service keys and ``SECRET_REGISTRY_FERNET_KEY`` (or the
OpenBao backend settings) in the environment, plus ``DATABASE_URL``.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BACKEND = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

ACTOR = "system:secret-registry-migrate"


@dataclass
class Target:
    label: str
    container: dict[str, Any]
    key: str
    decrypt: Callable[[str], str | None]
    name: str
    kind: str
    scope: str = "workspace"


def _dict(value: Any) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


def workspace_targets(settings: dict[str, Any]) -> list[Target]:
    """Secret fields of one (mutable) settings copy, in migration order."""
    from app.services.client360_pdr import _decrypt_smtp_password
    from app.services.connectors.generic import service as generic
    from app.services.connectors.hana import service as hana
    from app.services.connectors.mcp import service as mcp
    from app.services.connectors.rpa import service as rpa
    from app.services.huggingface.connection import decrypt_token
    from app.services.model_plane import workspace_config
    from app.services.secrets.compat import kind_for, secret_name

    targets: list[Target] = []

    entries = _dict(settings.get(generic.SETTINGS_KEY)) or {}
    for connector_id, entry in entries.items():
        secrets = _dict((entry or {}).get("secrets")) if isinstance(entry, dict) else None
        for key in list(secrets or {}):
            targets.append(
                Target(
                    f"{generic.SETTINGS_KEY}.{connector_id}.secrets.{key}",
                    secrets,
                    key,
                    decrypt_token if connector_id == "huggingface" else generic._decrypt_secret,
                    secret_name(connector_id, key),
                    kind_for(key),
                )
            )

    connectors = _dict(settings.get("connectors")) or {}
    blob = _dict(connectors.get(mcp.CONNECTOR_KEY)) or {}
    for item in blob.get("servers") or []:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        for key, field in (
            ("token_encrypted", "token"),
            ("oauth_client_secret_encrypted", "oauth_client_secret"),
        ):
            targets.append(
                Target(
                    f"connectors.{mcp.CONNECTOR_KEY}.servers[{item['id']}].{key}",
                    item,
                    key,
                    mcp._decrypt_secret,
                    secret_name("mcp", item["id"], field),
                    kind_for(field),
                )
            )
    shared = _dict(blob.get("shared_auth"))
    if shared is not None:
        targets.append(
            Target(
                f"connectors.{mcp.CONNECTOR_KEY}.shared_auth.oauth_client_secret_encrypted",
                shared,
                "oauth_client_secret_encrypted",
                mcp._decrypt_secret,
                secret_name("mcp", "shared", "oauth_client_secret"),
                "oauth_client",
            )
        )

    rpa_row = _dict(connectors.get(rpa.CONNECTOR_KEY))
    if rpa_row is not None:
        targets.append(
            Target(
                f"connectors.{rpa.CONNECTOR_KEY}.auth_token_encrypted",
                rpa_row,
                "auth_token_encrypted",
                rpa._decrypt_secret,
                "rpa-bridge-auth-token",
                "token",
            )
        )
    hana_row = _dict(connectors.get(hana.CONNECTOR_KEY))
    if hana_row is not None:
        targets.append(
            Target(
                f"connectors.{hana.CONNECTOR_KEY}.password_encrypted",
                hana_row,
                "password_encrypted",
                hana._decrypt_secret,
                "sap-hana-password",
                "password",
            )
        )

    portal = _dict(settings.get(workspace_config.SETTINGS_KEY)) or {}
    creds = _dict(portal.get("cloud_credentials")) or {}
    for provider, entry in creds.items():
        if isinstance(entry, dict):
            targets.append(
                Target(
                    f"{workspace_config.SETTINGS_KEY}.cloud_credentials.{provider}.api_key_encrypted",
                    entry,
                    "api_key_encrypted",
                    workspace_config.decrypt_secret,
                    secret_name("llm", provider, "api-key"),
                    "api_key",
                )
            )
    for item in portal.get("serving_nodes") or []:
        name = str(item.get("name") or "").strip() if isinstance(item, dict) else ""
        if name:
            targets.append(
                Target(
                    f"{workspace_config.SETTINGS_KEY}.serving_nodes[{name}].token_encrypted",
                    item,
                    "token_encrypted",
                    workspace_config.decrypt_secret,
                    secret_name("nodes", name, "token"),
                    "token",
                )
            )

    mail = _dict(settings.get("client360_pdr_mail")) or {}
    smtp = _dict(mail.get("smtp"))
    if smtp is not None:
        if smtp.get("password") and not smtp.get("password_encrypted"):
            # A leftover clear password migrates like an envelope holding it.
            smtp["password_encrypted"] = smtp.pop("password")
        targets.append(
            Target(
                "client360_pdr_mail.smtp.password_encrypted",
                smtp,
                "password_encrypted",
                _decrypt_smtp_password,
                "client360-smtp-password",
                "password",
            )
        )
    return targets


def platform_targets(connection: dict[str, Any]) -> list[Target]:
    from app.services.huggingface.connection import decrypt_token

    return [
        Target(
            "hf_platform_config.connection.token_encrypted",
            connection,
            "token_encrypted",
            decrypt_token,
            "huggingface-token",
            "token",
            scope="platform",
        )
    ]


def _migrate_targets(
    db, targets: list[Target], *, workspace_id: str | None, dry_run: bool, report: list[dict]
) -> bool:
    from app.services.secrets.compat import is_ref, write_secret_field

    changed = False
    for target in targets:
        stored = target.container.get(target.key)
        row = {"workspace_id": workspace_id, "field": target.label, "secret": target.name}
        if not stored:
            continue
        if is_ref(stored):
            report.append({**row, "action": "already_ref"})
            continue
        try:
            value = target.decrypt(stored if isinstance(stored, str) else json.dumps(stored))
        except Exception as exc:  # noqa: BLE001 - name the failure, never the value
            report.append({**row, "action": "error", "error": type(exc).__name__})
            continue
        if not value:
            report.append({**row, "action": "empty"})
            continue
        if dry_run:
            report.append({**row, "action": "would_migrate"})
            continue
        target.container[target.key] = write_secret_field(
            db,
            value,
            scope=target.scope,
            name=target.name,
            legacy=None,
            actor=ACTOR,
            kind=target.kind,
            workspace_id=workspace_id,
            description=f"Migrated from {target.label}",
        )
        report.append({**row, "action": "migrated"})
        changed = True
    return changed


def write_backup(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True, default=str)
    os.chmod(path, 0o600)


def migrate(db, *, dry_run: bool, backup_path: Path | None) -> dict[str, Any]:
    from sqlalchemy.orm.attributes import flag_modified

    from app.models.huggingface import HFPlatformConfig
    from app.models.workspace import Workspace

    workspaces = db.query(Workspace).order_by(Workspace.id).all()
    platform = db.query(HFPlatformConfig).filter(HFPlatformConfig.id == "default").first()

    if not dry_run:
        if backup_path is None:
            raise ValueError("a backup path is required outside --dry-run")
        write_backup(
            backup_path,
            {
                "created_at": datetime.now(timezone.utc).isoformat(),
                "workspaces": {w.id: w.settings for w in workspaces},
                "hf_platform_connection": (platform.connection if platform else None),
            },
        )

    report: list[dict] = []
    for workspace in workspaces:
        raw = workspace.settings
        settings = copy.deepcopy(dict(raw)) if isinstance(raw, Mapping) else {}
        targets = workspace_targets(settings)
        if _migrate_targets(
            db, targets, workspace_id=workspace.id, dry_run=dry_run, report=report
        ):
            workspace.settings = settings
            flag_modified(workspace, "settings")
            db.add(workspace)
            db.commit()

    if platform is not None and isinstance(platform.connection, Mapping):
        connection = copy.deepcopy(dict(platform.connection))
        if _migrate_targets(
            db, platform_targets(connection), workspace_id=None, dry_run=dry_run, report=report
        ):
            platform.connection = connection
            flag_modified(platform, "connection")
            db.add(platform)
            db.commit()

    counts: dict[str, int] = {}
    for row in report:
        counts[row["action"]] = counts.get(row["action"], 0) + 1
    return {
        "dry_run": dry_run,
        "backup": str(backup_path) if backup_path and not dry_run else None,
        "counts": counts,
        "fields": report,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="report only, write nothing")
    parser.add_argument(
        "--backup",
        type=Path,
        help="backup file (default: ./secret-registry-backup-<UTC timestamp>.json)",
    )
    args = parser.parse_args(argv)
    backup = args.backup or Path(
        f"secret-registry-backup-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json"
    )

    from app.db.base import SessionLocal

    with SessionLocal() as db:
        result = migrate(db, dry_run=args.dry_run, backup_path=None if args.dry_run else backup)
    print(json.dumps(result, indent=2))
    return 1 if result["counts"].get("error") else 0


if __name__ == "__main__":
    raise SystemExit(main())
