"""Refresh every workspace's always-on chat System to the current template.

This promotes the generalized (domain-neutral) chat orchestration into every
existing workspace's ``chat_transverse_v1`` System and re-converges the
expert-correction ``source_policy`` keys, mirroring how the startup hook would
seed a fresh deployment. It is idempotent: re-running it only rewrites the
System rows in place.

Usage:
    cd backend
    python -m scripts.refresh_workspace_chat_systems

The Andritz chat System is a zero-drift regression gate: the script prints the
Andritz chat System ``settings.source_policy`` and the effective
``resolve_workspace_chat_source_policy`` result BEFORE and AFTER the refresh so
an operator can confirm the industrial/project layer is unchanged.

This is the SCRIPT-only propagation path; no alembic migration is created here.
"""
from __future__ import annotations

import argparse
import json
from typing import Any, Dict, Optional

from app.db.base import SessionLocal
from app.models.system import System
from app.models.workspace import Workspace
from app.services.systems.bootstrap import (
    ensure_workspace_chat_system_for_all_workspaces,
    resolve_workspace_chat_source_policy,
    sync_chat_system_expert_correction_policy,
    workspace_chat_system_id,
)
from app.services.workspace_features import workspace_family


def _active_workspaces(db) -> list[Workspace]:
    return (
        db.query(Workspace)
        .filter(Workspace.is_active.is_(True), Workspace.deleted_at.is_(None))
        .all()
    )


def _andritz_workspace(db) -> Optional[Workspace]:
    """Return the Andritz workspace (family == 'andritz'), or ``None``."""
    for workspace in (
        db.query(Workspace).filter(Workspace.deleted_at.is_(None)).all()
    ):
        if workspace_family(workspace) == "andritz":
            return workspace
    return None


def andritz_chat_system_snapshot(db, workspace: Optional[Workspace] = None) -> Optional[Dict[str, Any]]:
    """Snapshot the Andritz chat System policy for before/after drift checks.

    Captures the chat System ``settings.source_policy`` and the effective
    ``resolve_workspace_chat_source_policy`` result (the System layered over the
    workspace), so an operator can diff the industrial/project layer.
    """
    workspace = workspace or _andritz_workspace(db)
    if workspace is None:
        return None
    system_id = workspace_chat_system_id(db, workspace.id)
    system = (
        db.query(System).filter(System.id == system_id).first() if system_id else None
    )
    system_source_policy: Dict[str, Any] = {}
    if system is not None and isinstance(system.settings, dict):
        system_source_policy = dict(system.settings.get("source_policy") or {})
    return {
        "workspace_slug": workspace.slug,
        "workspace_id": workspace.id,
        "system_id": system_id,
        "system_name": getattr(system, "name", None),
        "system_source_policy": system_source_policy,
        "effective_source_policy": resolve_workspace_chat_source_policy(
            db, workspace, system=system
        ),
    }


def _print_snapshot(label: str, snapshot: Optional[Dict[str, Any]]) -> None:
    if snapshot is None:
        print(f"[andritz {label}] no Andritz workspace found (nothing to gate)")
        return
    print(f"[andritz {label}] workspace={snapshot['workspace_slug']} system={snapshot['system_name']!r}")
    print(f"[andritz {label}] system.settings.source_policy = {json.dumps(snapshot['system_source_policy'], sort_keys=True, ensure_ascii=False)}")
    print(f"[andritz {label}] effective source_policy       = {json.dumps(snapshot['effective_source_policy'], sort_keys=True, ensure_ascii=False)}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--no-sync",
        action="store_true",
        help="Skip the post-refresh expert-correction policy re-convergence",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        before = andritz_chat_system_snapshot(db)
        _print_snapshot("before", before)

        report = ensure_workspace_chat_system_for_all_workspaces(db)
        print(
            "chat-system refresh: "
            f"created={report['created']} already={report['already']} skipped={report['skipped']}"
        )

        synced = 0
        if not args.no_sync:
            for workspace in _active_workspaces(db):
                if sync_chat_system_expert_correction_policy(db, workspace) is not None:
                    synced += 1
            print(f"expert-correction policy re-converged for {synced} workspace chat System(s)")

        after = andritz_chat_system_snapshot(db)
        _print_snapshot("after", after)

        if before is not None and after is not None:
            drift = before["effective_source_policy"] != after["effective_source_policy"]
            print(
                "[andritz gate] effective source_policy "
                + ("CHANGED — INVESTIGATE" if drift else "unchanged (zero drift)")
            )
    finally:
        db.close()


if __name__ == "__main__":
    main()
