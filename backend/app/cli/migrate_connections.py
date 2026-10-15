"""Idempotent, explicit migration of legacy PG/HANA configurations.

Usage: python -m app.cli.migrate_connections --dry-run|--apply [--workspace-id ID]
Dry-run never decrypts credentials or writes to the registry/database. Apply
preserves legacy settings for the compatibility release. Each workspace is
locked and committed independently, with its secrets and mandatory audit rows.
"""

from __future__ import annotations

import argparse
import json

from sqlalchemy.orm import Session

from app.db.base import SessionLocal
from app.models.connector_connection import ConnectorConnection
from app.models.workspace import Workspace
from app.schemas.connection import ConnectionCreate
from app.services import secrets as registry
from app.services.connectors.connections import (
    ConnectionError,
    audit,
    create_connection,
    require_registry,
)
from app.services.connectors.profiles import ProfileError, get_profile

SOURCES = {"postgresql": "generic_connectors.postgresql", "sap_hana": "connectors.sap_hana"}


def _legacy(workspace, profile_key, *, decrypt=False):
    if profile_key == "postgresql":
        from app.services.connectors.generic.service import get_config

        config = get_config(workspace, profile_key, include_secrets=decrypt)
        values = config["values"]
        if values.get("port"):
            values["port"] = int(values["port"])
        password = (config.get("secrets") or {}).get("password")
        return values, config["secrets_set"].get("password", False), password
    from app.services.connectors.hana.service import get_config

    config = get_config(workspace, include_secrets=decrypt)
    values = {
        k: v for k, v in config.items() if k not in {"configured", "password_set", "password"}
    }
    return values, config["password_set"], config.get("password")


def migrate_workspace(db: Session, workspace_id: str, *, apply: bool = False) -> list[dict]:
    workspace = db.query(Workspace).filter_by(id=workspace_id).with_for_update().one()
    result = []
    raw = workspace.settings or {}
    for profile_key, source in SOURCES.items():
        parent, key = source.split(".")
        if not isinstance(raw.get(parent), dict) or not raw[parent].get(key):
            continue
        existing = (
            db.query(ConnectorConnection)
            .filter_by(workspace_id=workspace.id, legacy_source=source)
            .one_or_none()
        )
        if existing:
            result.append(
                {
                    "workspace_id": workspace.id,
                    "profile_key": profile_key,
                    "action": "already_migrated",
                    "connection_id": existing.id,
                }
            )
            continue
        values, password_set, _ = _legacy(workspace, profile_key)
        refs = (
            {"password": "secret://workspace/legacy-" + profile_key.replace("_", "-") + "-password"}
            if password_set
            else {}
        )
        profile = get_profile(profile_key)
        values = profile.validate_values(values, refs)
        if profile_key == "sap_hana" and (
            not values["encrypt"] or not values["ssl_validate_certificate"]
        ):
            raise ConnectionError("CONNECTOR_TLS_REQUIRED")
        row = {
            "workspace_id": workspace.id,
            "profile_key": profile_key,
            "action": "would_migrate",
            "credentials": "registry" if password_set else "none",
        }
        if apply:
            require_registry()
            _, _, password = _legacy(workspace, profile_key, decrypt=True)
            if password_set:
                if not password:
                    raise ConnectionError("CONNECTOR_LEGACY_SECRET_UNREADABLE")
                meta = registry.create(
                    db,
                    scope="workspace",
                    workspace_id=workspace.id,
                    name="legacy-" + profile_key.replace("_", "-") + "-password",
                    value=password,
                    kind="password",
                    actor="migration:connections",
                    commit=False,
                )
                refs = {"password": meta["ref"]}
            connection = create_connection(
                db,
                workspace_id=workspace.id,
                actor="migration:connections",
                data=ConnectionCreate(
                    name="Migrated " + profile_key,
                    profile_key=profile_key,
                    values=values,
                    secret_refs=refs,
                ),
                legacy_source=source,
            )
            audit(
                db,
                connection,
                "connection.legacy.migrated",
                "migration:connections",
                legacy_source=source,
            )
            row.update(action="migrated", connection_id=connection.id)
        result.append(row)
    if apply:
        db.commit()
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--workspace-id")
    args = parser.parse_args(argv)
    # Register mappings for SQLAlchemy relationships; no network, schema mutation or seeding.
    import app.models  # noqa: F401

    failed = False
    with SessionLocal() as db:
        query = db.query(Workspace.id).filter(Workspace.deleted_at.is_(None))
        if args.workspace_id:
            query = query.filter_by(id=args.workspace_id)
        for (workspace_id,) in query.order_by(Workspace.id).all():
            try:
                for row in migrate_workspace(db, workspace_id, apply=args.apply):
                    print(json.dumps(row, sort_keys=True))
            except (ConnectionError, ProfileError, registry.SecretRegistryError, ValueError) as exc:
                db.rollback()
                failed = True
                print(
                    json.dumps(
                        {
                            "workspace_id": workspace_id,
                            "action": "blocked",
                            "code": getattr(exc, "code", "CONNECTOR_LEGACY_INVALID"),
                        }
                    )
                )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
