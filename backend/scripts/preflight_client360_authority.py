#!/usr/bin/env python3
"""Read-only preflight for the Client360 action-authorization authority.

Selection never depends on a workspace slug or display name. The production
cohort is the union of:

* active workspaces with the configured workspace family;
* active workspaces with at least one explicit Client360 app entitlement;
* optional exact workspace ids supplied by an operator.

The resolver is the same function used by every Client360 endpoint. A failed
row therefore predicts a runtime 503 before code is deployed or a workspace is
promoted to authorization shadow/enforce. This command never seeds, repairs,
locks, audits or commits data.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session as DBSession

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.config import settings  # noqa: E402
from app.db.base import SessionLocal  # noqa: E402
from app.models.workspace import (  # noqa: E402
    Workspace,
    WorkspaceIAMConfig,
    WorkspaceMember,
    WorkspaceMemberAppEntitlement,
)
from app.services.client360_contract import (  # noqa: E402
    CLIENT360_SYSTEM_VARIANT,
)
from app.services.client360_pdr import resolve_client360_authority  # noqa: E402
from app.services.iam.app_entitlements import CLIENT360_APP  # noqa: E402
from app.services.iam.decision_plane import candidate_config_sha256  # noqa: E402

SCHEMA_VERSION = 1
GIT_SHA_RE = re.compile(r"[0-9a-f]{40}")
CLIENT360_ACTION_SET = (
    "action.execute",
    "decision.approve",
    "mail_draft.mail.send",
    "system.admin",
    "system.engine.run",
    "system.read",
)


def _record(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _family(workspace: Workspace) -> str:
    return str(_record(workspace.settings).get("family") or "").strip().lower()


def _declares_client360_surface(workspace: Workspace) -> bool:
    profile = _record(_record(workspace.settings).get("navigation_profile"))
    surfaces = profile.get("primary_surfaces")
    return isinstance(surfaces, list) and CLIENT360_APP in surfaces


def _canonical_sha(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        dict(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _grant_counts(db: DBSession) -> dict[str, int]:
    rows = (
        db.query(WorkspaceMember.workspace_id, WorkspaceMemberAppEntitlement.id)
        .join(
            WorkspaceMemberAppEntitlement,
            WorkspaceMemberAppEntitlement.workspace_member_id == WorkspaceMember.id,
        )
        .filter(WorkspaceMemberAppEntitlement.app_key == CLIENT360_APP)
        .all()
    )
    counts: dict[str, int] = {}
    for workspace_id, _grant_id in rows:
        counts[str(workspace_id)] = counts.get(str(workspace_id), 0) + 1
    return counts


def _member_counts(db: DBSession) -> dict[str, int]:
    counts: dict[str, int] = {}
    for (workspace_id,) in db.query(WorkspaceMember.workspace_id).all():
        counts[str(workspace_id)] = counts.get(str(workspace_id), 0) + 1
    return counts


def select_workspaces(
    db: DBSession,
    *,
    family: str | None,
    workspace_ids: Iterable[str] = (),
) -> tuple[list[Workspace], list[str]]:
    """Return the active cohort and exact requested ids that were not found."""

    requested = {str(item).strip() for item in workspace_ids if str(item).strip()}
    grants = _grant_counts(db)
    normalized_family = str(family or "").strip().lower()
    active = (
        db.query(Workspace)
        .filter(Workspace.is_active.is_(True), Workspace.deleted_at.is_(None))
        .all()
    )
    selected = [
        workspace
        for workspace in active
        if workspace.id in requested
        or grants.get(workspace.id, 0) > 0
        or _declares_client360_surface(workspace)
        or (normalized_family and _family(workspace) == normalized_family)
    ]
    found = {workspace.id for workspace in selected}
    return sorted(selected, key=lambda row: row.id), sorted(requested - found)


def build_preflight(
    db: DBSession,
    *,
    family: str | None = "andritz",
    workspace_ids: Iterable[str] = (),
    runtime_revision: str | None = None,
    require_runtime_revision: bool = True,
) -> dict[str, Any]:
    revision = str(
        runtime_revision
        if runtime_revision is not None
        else settings.agentium_image_revision or ""
    ).strip().lower()
    workspaces, missing_ids = select_workspaces(
        db,
        family=family,
        workspace_ids=workspace_ids,
    )
    grants = _grant_counts(db)
    members = _member_counts(db)
    rows: list[dict[str, Any]] = []
    runtime_blocker = (
        {
            "code": "runtime_revision_not_exact",
            "message": "runtime revision must be the exact 40-character Git SHA being deployed",
        }
        if require_runtime_revision and GIT_SHA_RE.fullmatch(revision) is None
        else None
    )
    for workspace in workspaces:
        blockers = [runtime_blocker] if runtime_blocker else []
        row: dict[str, Any] = {
            "workspace_id": workspace.id,
            "family": _family(workspace),
            "member_count": members.get(workspace.id, 0),
            "client360_grant_count": grants.get(workspace.id, 0),
            "system_id": None,
            "capability_id": None,
            "iam_config_version": None,
            "candidate_config_sha256": None,
            "authority_sha256": None,
            "ready": False,
            "blockers": blockers,
        }
        try:
            system, capability = resolve_client360_authority(db, workspace)
        except LookupError as exc:
            blockers.append(
                {"code": "client360_authority_invalid", "message": str(exc)}
            )
        else:
            config = (
                db.query(WorkspaceIAMConfig)
                .filter(WorkspaceIAMConfig.workspace_id == workspace.id)
                .one_or_none()
            )
            flow = _record(system.flow_definition)
            system_settings = _record(system.settings)
            authority = {
                "schema_version": SCHEMA_VERSION,
                "workspace_id": workspace.id,
                "system_id": system.id,
                "system_status": system.status,
                "system_variant": flow.get("variant"),
                "system_type": system_settings.get("system_type"),
                "capability_id": capability.id,
                "capability_workspace_id": capability.workspace_id,
                "capability_slug": capability.slug,
                "action_set": list(CLIENT360_ACTION_SET),
                "iam_config_version": int(config.version) if config is not None else None,
                "candidate_config_sha256": candidate_config_sha256(config),
                "runtime_revision": revision,
            }
            row.update(
                {
                    "system_id": system.id,
                    "capability_id": capability.id,
                    "iam_config_version": authority["iam_config_version"],
                    "candidate_config_sha256": authority["candidate_config_sha256"],
                    "authority_sha256": _canonical_sha(authority),
                }
            )
            if (
                flow.get("variant") != CLIENT360_SYSTEM_VARIANT
                and system_settings.get("system_type") != CLIENT360_SYSTEM_VARIANT
            ):
                blockers.append(
                    {
                        "code": "client360_structural_marker_missing",
                        "message": "Client360 System structural marker is missing",
                    }
                )
        row["ready"] = not blockers
        rows.append(row)
    for workspace_id in missing_ids:
        rows.append(
            {
                "workspace_id": workspace_id,
                "family": None,
                "member_count": 0,
                "client360_grant_count": 0,
                "system_id": None,
                "capability_id": None,
                "iam_config_version": None,
                "candidate_config_sha256": None,
                "authority_sha256": None,
                "ready": False,
                "blockers": [
                    {
                        "code": "requested_workspace_not_active",
                        "message": "requested workspace does not exist or is not active",
                    }
                ],
            }
        )
    rows.sort(key=lambda row: str(row["workspace_id"]))
    global_blockers = (
        [
            {
                "code": "no_workspace_selected",
                "message": "no active Client360 installation matched the structural selectors",
            }
        ]
        if not rows
        else []
    )
    ready = sum(bool(row["ready"]) for row in rows)
    blocked = len(rows) - ready + len(global_blockers)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "runtime_revision": revision,
        "selector": {
            "family": str(family or "").strip().lower() or None,
            "workspace_ids": sorted(
                {str(item).strip() for item in workspace_ids if str(item).strip()}
            ),
            "includes_explicit_client360_grants": True,
            "includes_declared_client360_surfaces": True,
        },
        "action_set": list(CLIENT360_ACTION_SET),
        "blockers": global_blockers,
        "summary": {
            "workspace_count": len(rows),
            "ready": ready,
            "blocked": blocked,
        },
        "workspaces": rows,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--runtime-revision",
        help="Exact 40-character Git SHA being preflighted (for example CI_COMMIT_SHA).",
    )
    parser.add_argument(
        "--family",
        default="andritz",
        help="Configured workspace family to include (default: andritz).",
    )
    parser.add_argument(
        "--workspace-id",
        action="append",
        default=[],
        help="Exact workspace id to include; repeatable. Slugs and names are not accepted.",
    )
    parser.add_argument(
        "--allow-unbound-runtime",
        action="store_true",
        help="Local-only inspection; do not require an exact deployed Git SHA.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not args.allow_unbound_runtime and not str(args.runtime_revision or "").strip():
        print(
            json.dumps(
                {
                    "error": {
                        "code": "target_runtime_revision_required",
                        "message": "--runtime-revision must name the exact Git SHA being deployed",
                    }
                },
                sort_keys=True,
            )
        )
        return 2
    db = SessionLocal()
    try:
        result = build_preflight(
            db,
            family=args.family,
            workspace_ids=args.workspace_id,
            runtime_revision=args.runtime_revision,
            require_runtime_revision=not args.allow_unbound_runtime,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["summary"]["blocked"] == 0 else 2
    finally:
        db.rollback()
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
