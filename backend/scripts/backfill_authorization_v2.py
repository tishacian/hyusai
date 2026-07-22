#!/usr/bin/env python3
"""Dry-run/apply the granular authorization-v2 shadow configuration.

Selection is explicit by immutable workspace id or canonical stamped family;
the script never guesses a business workspace from its mutable slug/name.
The default is dry-run and prints a machine-readable JSON report.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session as DBSession

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db.base import SessionLocal  # noqa: E402
from app.models.workspace import Workspace, WorkspaceIAMConfig  # noqa: E402
from app.services.audit_logger import emit_audit_event  # noqa: E402
from app.services.iam.config_service import load_iam_config  # noqa: E402
from app.services.iam.decision_plane import merge_authorization_v2_backfill  # noqa: E402
from app.services.workspace_features import workspace_family  # noqa: E402


def _has_stamped_family(workspace: Workspace, family: str) -> bool:
    settings = workspace.settings if isinstance(workspace.settings, Mapping) else {}
    return str(settings.get("family") or "").strip().lower() == family


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace-id", action="append", default=[])
    parser.add_argument("--family", choices=("andritz", "industrial", "sentinel_ci", "generic"))
    # Enforcement is a separate, evidence-gated promotion.  This command is
    # deliberately incapable of jumping directly from compat to enforce.
    parser.add_argument("--mode", choices=("shadow",), default="shadow")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--actor")
    return parser


def run(
    *,
    workspace_ids: list[str],
    family: str | None,
    mode: str,
    apply: bool,
    actor: str = "",
    db: DBSession | None = None,
) -> dict[str, Any]:
    if not workspace_ids and not family:
        raise ValueError("Select at least one --workspace-id or a canonical --family")
    if mode != "shadow":
        raise ValueError(
            "authorization backfill only supports shadow; use the evidence-gated "
            "promotion command for enforce"
        )
    actor_value = str(actor or "").strip()
    if apply and not actor_value:
        raise ValueError("--apply requires a non-empty --actor")
    owns_session = db is None
    db = db or SessionLocal()
    try:
        query = db.query(Workspace).filter(
            Workspace.is_active.is_(True),
            Workspace.deleted_at.is_(None),
        )
        candidates = query.order_by(Workspace.id.asc()).all()
        selected = [
            item
            for item in candidates
            if item.id in set(workspace_ids)
            or (family and _has_stamped_family(item, family))
        ]
        missing_ids = sorted(set(workspace_ids) - {item.id for item in selected})
        if missing_ids:
            raise ValueError(f"Unknown active workspace ids: {', '.join(missing_ids)}")
        if not selected:
            raise ValueError("No active workspace matched the requested selection")
        rows = []
        for workspace in selected:
            if apply:
                locked_workspace = (
                    db.query(Workspace)
                    .filter(
                        Workspace.id == workspace.id,
                        Workspace.is_active.is_(True),
                        Workspace.deleted_at.is_(None),
                    )
                    .with_for_update(of=Workspace)
                    .one_or_none()
                )
                if locked_workspace is None or (
                    family
                    and not _has_stamped_family(locked_workspace, family)
                    and locked_workspace.id not in set(workspace_ids)
                ):
                    raise ValueError(
                        f"Workspace selection drifted while acquiring lock: {workspace.id}"
                    )
                workspace = locked_workspace
                config = (
                    db.query(WorkspaceIAMConfig)
                    .filter(WorkspaceIAMConfig.workspace_id == workspace.id)
                    .with_for_update(of=WorkspaceIAMConfig)
                    .one_or_none()
                )
                if config is None:
                    # The workspace row lock serializes first-time creation
                    # with IAM PATCH, Blueprint and other backfill workflows.
                    config = load_iam_config(db, workspace.id, create=True)
            else:
                config = load_iam_config(db, workspace.id, create=False)
            current = config.capability_overrides if config else {}
            merged, changed = merge_authorization_v2_backfill(current, mode=mode)
            rows.append({
                "workspace_id": workspace.id,
                "family": workspace_family(workspace),
                "changed": changed,
                "mode": mode,
                "action": "updated" if apply and changed else ("unchanged" if not changed else "would_update"),
            })
            if apply and changed:
                assert config is not None
                config.capability_overrides = merged
                config.version = int(config.version or 0) + 1
                audit_id = emit_audit_event(
                    db=db,
                    workspace_id=workspace.id,
                    event_type="lot7.authorization.shadow_configured",
                    actor=actor_value,
                    details={
                        "policy_version": 2,
                        "mode": "shadow",
                        "actions": sorted(
                            merged["authorization_v2"]["modes"]
                        ),
                    },
                )
                if audit_id is None:
                    raise ValueError("authorization shadow audit could not be persisted")
        if apply:
            db.commit()
        else:
            db.rollback()
        return {
            "schema_version": 1,
            "operation": "apply" if apply else "dry-run",
            "policy_mode": mode,
            "selected_count": len(rows),
            "changed_count": sum(1 for item in rows if item["changed"]),
            "workspaces": rows,
        }
    except Exception:
        db.rollback()
        raise
    finally:
        if owns_session:
            db.close()


def main() -> int:
    args = _parser().parse_args()
    try:
        report = run(
            workspace_ids=args.workspace_id,
            family=args.family,
            mode=args.mode,
            apply=args.apply,
            actor=args.actor or "",
        )
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
