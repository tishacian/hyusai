#!/usr/bin/env python3
"""Backfill authoritative Workspace App installation records explicitly.

The migration is deliberately application-owned rather than Alembic-owned:

* callers must enumerate immutable workspace ids (there is no ``--all``);
* workspace selection uses canonical settings markers, never slug or name;
* dry-run is the default and produces a content-addressed analysis;
* apply must acknowledge that exact SHA-256 and is atomic across the batch;
* legacy settings and member entitlements are read-only inputs.

An already installed but different app version/configuration is a blocker.  It
must go through the normal Workspace App upgrade/rollback lifecycle instead of
being silently rewritten by this compatibility backfill.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Mapping, Sequence
from copy import deepcopy
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session as DBSession

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db.base import SessionLocal  # noqa: E402
from app.models.workspace import Workspace  # noqa: E402
from app.models.workspace_app import WorkspaceAppInstallation  # noqa: E402
from app.services.workspace_app_lifecycle import (  # noqa: E402
    WorkspaceAppLifecycleError,
    apply_workspace_app_lifecycle,
    plan_workspace_app_lifecycle,
)
from app.services.workspace_app_manifests import (  # noqa: E402
    CompiledWorkspaceAppManifest,
    get_builtin_workspace_app_manifest,
    list_builtin_workspace_app_manifests,
    validate_manifest_configuration,
)
from app.services.workspace_features import workspace_family  # noqa: E402

SCHEMA_VERSION = 1
SENTINEL_PROFILE = "sentinel_government_v1"
SENTINEL_ASSISTANT = "vigie_executive"
OCTOCITY_PROFILE = "octocity_institutional_v1"
OCTOCITY_ASSISTANT = "octave_executive"
ANDRITZ_APP_IDS = (
    "andritz.chat",
    "andritz.client360-pdr",
    "andritz.knowledge-capture",
)


class WorkspaceAppBackfillError(RuntimeError):
    """Raised when an explicit Workspace App backfill is not safe to apply."""


def _normalize_workspace_ids(workspace_ids: Sequence[str]) -> list[str]:
    normalized = sorted(
        {str(item or "").strip() for item in workspace_ids if str(item or "").strip()}
    )
    if not normalized:
        raise WorkspaceAppBackfillError("at least one explicit workspace id is required")
    return normalized


def _lock_workspaces_for_apply(
    db: DBSession,
    *,
    workspace_ids: Sequence[str],
) -> list[Workspace]:
    """Acquire the batch mutexes in deterministic order before re-analysis.

    The caller deliberately keeps the returned ORM objects alive until commit.
    More importantly, the surrounding transaction keeps every ``FOR UPDATE``
    lock until the whole batch has either committed or rolled back.  This closes
    the gap where workspace settings could change after the acknowledged dry-run
    had been revalidated but before the first lifecycle operation acquired its
    per-workspace lock.
    """

    normalized_ids = _normalize_workspace_ids(workspace_ids)
    return (
        db.query(Workspace)
        .filter(Workspace.id.in_(normalized_ids))
        .order_by(Workspace.id.asc())
        .with_for_update(of=Workspace)
        .all()
    )


def _record(value: Any) -> dict[str, Any]:
    return deepcopy(dict(value)) if isinstance(value, Mapping) else {}


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
        default=str,
    )


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _manifest(app_id: str, version: str = "1.0.0") -> CompiledWorkspaceAppManifest:
    candidates = [
        item for item in list_builtin_workspace_app_manifests(app_id) if item.version == version
    ]
    if len(candidates) != 1:
        raise WorkspaceAppBackfillError(f"expected one compiled manifest for {app_id}@{version}")
    candidate = candidates[0]
    return get_builtin_workspace_app_manifest(
        candidate.app_id,
        candidate.version,
        expected_digest=candidate.digest,
    )


def _desired_apps(workspace: Workspace) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    settings = _record(workspace.settings)
    desired: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []

    if workspace_family(workspace) == "andritz":
        for app_id in ANDRITZ_APP_IDS:
            manifest = _manifest(app_id)
            desired.append(
                {
                    "app_id": manifest.app_id,
                    "version": manifest.version,
                    "manifest_digest": manifest.digest,
                    "configuration": validate_manifest_configuration(manifest, None),
                    "source": "workspace.settings.family",
                }
            )

    mission_room = _record(settings.get("mission_room"))
    if mission_room.get("enabled") is True:
        profile = str(mission_room.get("profile") or "").strip()
        assistant = str(settings.get("assistant_profile_default") or "").strip()
        known_profile = profile in {SENTINEL_PROFILE, OCTOCITY_PROFILE}
        expected_assistant = {
            SENTINEL_PROFILE: SENTINEL_ASSISTANT,
            OCTOCITY_PROFILE: OCTOCITY_ASSISTANT,
        }.get(profile)
        if known_profile and assistant != expected_assistant:
            blockers.append(
                {
                    "code": "mission_room_profile_assistant_mismatch",
                    "workspace_id": workspace.id,
                    "profile": profile,
                    "expected_assistant_profile": expected_assistant,
                    "actual_assistant_profile": assistant or None,
                }
            )
        elif not profile or not assistant:
            blockers.append(
                {
                    "code": "mission_room_identity_incomplete",
                    "workspace_id": workspace.id,
                    "profile_present": bool(profile),
                    "assistant_profile_present": bool(assistant),
                }
            )
        else:
            if profile == SENTINEL_PROFILE:
                manifest = _manifest("sentinel.mission-room")
                configuration = validate_manifest_configuration(manifest, None)
            elif profile == OCTOCITY_PROFILE:
                manifest = _manifest("octocity.mission-room")
                configuration = validate_manifest_configuration(manifest, None)
            else:
                # New legacy adoptions target the first provider-capable
                # immutable contract. Existing 1.0/1.1 installations are not
                # rewritten here and must use the normal explicit lifecycle.
                manifest = _manifest("mission-room.extension", "1.2.0")
                configuration = validate_manifest_configuration(
                    manifest,
                    {
                        "profile": profile,
                        "assistant_profile": assistant,
                        "decision_surfaces": True,
                    },
                )
            desired.append(
                {
                    "app_id": manifest.app_id,
                    "version": manifest.version,
                    "manifest_digest": manifest.digest,
                    "configuration": configuration,
                    "source": "workspace.settings.mission_room.enabled",
                }
            )

    desired.sort(key=lambda item: item["app_id"])
    return desired, blockers


def _installation_state(row: WorkspaceAppInstallation | None) -> dict[str, Any]:
    if row is None:
        return {
            "state": "absent",
            "version": None,
            "manifest_digest": None,
            "configuration": {},
            "revision": 0,
        }
    return {
        "state": row.state,
        "version": row.version,
        "manifest_digest": row.manifest_digest,
        "configuration": _record(row.configuration),
        "revision": int(row.revision or 0),
    }


def analyze(
    db: DBSession,
    *,
    workspace_ids: Sequence[str],
) -> dict[str, Any]:
    """Build a deterministic, read-only backfill report for explicit ids."""

    normalized_ids = _normalize_workspace_ids(workspace_ids)

    rows = db.query(Workspace).filter(Workspace.id.in_(normalized_ids)).all()
    by_id = {row.id: row for row in rows}
    blockers: list[dict[str, Any]] = []
    workspaces: list[dict[str, Any]] = []
    changes: list[dict[str, Any]] = []

    missing = sorted(set(normalized_ids) - set(by_id))
    blockers.extend(
        {"code": "workspace_not_found", "workspace_id": workspace_id} for workspace_id in missing
    )

    for workspace_id in normalized_ids:
        workspace = by_id.get(workspace_id)
        if workspace is None:
            continue
        desired, workspace_blockers = _desired_apps(workspace)
        blockers.extend(workspace_blockers)
        workspace_entry = {
            "workspace_id": workspace.id,
            "family": workspace_family(workspace),
            "mission_room_enabled": (
                _record(_record(workspace.settings).get("mission_room")).get("enabled") is True
            ),
            "desired_app_ids": [item["app_id"] for item in desired],
        }
        workspaces.append(workspace_entry)

        for target in desired:
            installation = (
                db.query(WorkspaceAppInstallation)
                .filter(
                    WorkspaceAppInstallation.workspace_id == workspace.id,
                    WorkspaceAppInstallation.app_id == target["app_id"],
                )
                .first()
            )
            before = _installation_state(installation)
            exact = (
                before["state"] == "installed"
                and before["version"] == target["version"]
                and before["manifest_digest"] == target["manifest_digest"]
                and before["configuration"] == target["configuration"]
            )
            if exact:
                changes.append(
                    {
                        "workspace_id": workspace.id,
                        **target,
                        "operation": "none",
                        "reason": "already_exact",
                        "before": before,
                        "plan_sha256": None,
                    }
                )
                continue
            if before["state"] == "installed":
                blockers.append(
                    {
                        "code": "installed_app_requires_lifecycle_transition",
                        "workspace_id": workspace.id,
                        "app_id": target["app_id"],
                        "installed_version": before["version"],
                        "installed_manifest_digest": before["manifest_digest"],
                    }
                )
                continue
            try:
                plan = plan_workspace_app_lifecycle(
                    db,
                    workspace_id=workspace.id,
                    operation="install",
                    app_id=target["app_id"],
                    target_version=target["version"],
                    expected_manifest_digest=target["manifest_digest"],
                    configuration=target["configuration"],
                    lifecycle_phase="legacy_adoption",
                )
            except WorkspaceAppLifecycleError as exc:
                blockers.append(
                    {
                        "code": "lifecycle_plan_failed",
                        "workspace_id": workspace.id,
                        "app_id": target["app_id"],
                        "reason": exc.code,
                    }
                )
                continue
            changes.append(
                {
                    "workspace_id": workspace.id,
                    **target,
                    "operation": "install",
                    "reason": "legacy_contract_detected",
                    "before": before,
                    "plan_sha256": plan.plan_sha256,
                }
            )

    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "selection": "explicit_workspace_ids",
        "requested_workspace_ids": normalized_ids,
        "workspace_count": len(workspaces),
        "workspaces": sorted(workspaces, key=lambda item: item["workspace_id"]),
        "changes": sorted(changes, key=lambda item: (item["workspace_id"], item["app_id"])),
        "blockers": sorted(
            blockers,
            key=lambda item: (
                str(item.get("workspace_id") or ""),
                str(item.get("app_id") or ""),
                item["code"],
            ),
        ),
    }
    report["ready"] = not report["blockers"]
    report["analysis_sha256"] = _sha256(report)
    return report


def apply(
    db: DBSession,
    *,
    workspace_ids: Sequence[str],
    expected_analysis_sha256: str,
    actor: str,
) -> dict[str, Any]:
    """Apply one exact dry-run analysis as a single database transaction."""

    expected = str(expected_analysis_sha256 or "").strip().lower()
    if len(expected) != 64 or any(char not in "0123456789abcdef" for char in expected):
        raise WorkspaceAppBackfillError("expected analysis SHA-256 is required for apply")
    actor_key = str(actor or "").strip()
    if not actor_key:
        raise WorkspaceAppBackfillError("actor is required for apply")

    try:
        normalized_ids = _normalize_workspace_ids(workspace_ids)
        locked_workspaces = _lock_workspaces_for_apply(
            db,
            workspace_ids=normalized_ids,
        )
        report = analyze(db, workspace_ids=normalized_ids)
        if report["analysis_sha256"] != expected:
            raise WorkspaceAppBackfillError("backfill analysis changed before apply")
        if not report["ready"]:
            raise WorkspaceAppBackfillError("backfill has blockers")

        # Keep explicit references until commit so the lock-owning rows cannot
        # leave the session identity map while lifecycle operations are applied.
        _ = locked_workspaces
        applied: list[dict[str, Any]] = []
        for change in report["changes"]:
            if change["operation"] != "install":
                continue
            result = apply_workspace_app_lifecycle(
                db,
                workspace_id=change["workspace_id"],
                operation="install",
                app_id=change["app_id"],
                target_version=change["version"],
                expected_manifest_digest=change["manifest_digest"],
                expected_plan_sha256=change["plan_sha256"],
                actor=actor_key,
                idempotency_key=(f"lot9-backfill:{expected[:20]}:{change['app_id']}"),
                configuration=change["configuration"],
                lifecycle_phase="legacy_adoption",
                prerequisite_evidence={
                    f"{change['app_id']}.legacy_installation.v1": report,
                },
                commit=False,
            )
            applied.append(
                {
                    "workspace_id": change["workspace_id"],
                    "app_id": change["app_id"],
                    "operation_id": result.operation.id,
                    "revision": result.installation.revision,
                    "idempotent_replay": result.idempotent_replay,
                }
            )
        db.commit()
    except Exception:
        db.rollback()
        raise

    return {
        "schema_version": SCHEMA_VERSION,
        "mode": "apply",
        "analysis_sha256": expected,
        "applied_count": len(applied),
        "applied": applied,
        "legacy_settings_mutated": False,
        "member_entitlements_mutated": False,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workspace-id",
        action="append",
        required=True,
        dest="workspace_ids",
        help="Immutable workspace id; repeat for an explicitly reviewed batch.",
    )
    parser.add_argument("--apply", action="store_true", help="Apply the acknowledged dry-run.")
    parser.add_argument("--expected-analysis-sha256")
    parser.add_argument("--actor", default="workspace-app-backfill-cli")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    db = SessionLocal()
    try:
        if args.apply:
            result = apply(
                db,
                workspace_ids=args.workspace_ids,
                expected_analysis_sha256=args.expected_analysis_sha256,
                actor=args.actor,
            )
        else:
            result = {
                **analyze(db, workspace_ids=args.workspace_ids),
                "mode": "dry-run",
                "database_mutated": False,
            }
        print(json.dumps(result, indent=2, sort_keys=True, default=str))
        return 0 if result.get("ready", True) else 2
    except (WorkspaceAppBackfillError, WorkspaceAppLifecycleError) as exc:
        db.rollback()
        print(json.dumps({"error": type(exc).__name__, "detail": str(exc)}, sort_keys=True))
        return 2
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
