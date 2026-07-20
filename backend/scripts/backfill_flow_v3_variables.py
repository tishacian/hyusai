"""Create canonical v3 variable snapshots; dry-run by default.

Examples::

    python -m scripts.backfill_flow_v3_variables --cohort showcase
    python -m scripts.backfill_flow_v3_variables --cohort showcase --apply --report report.json
    python -m scripts.backfill_flow_v3_variables --cohort internal --workspace-id <uuid> --apply
    python -m scripts.backfill_flow_v3_variables --cohort andritz --workspace-id <uuid> \
        --confirm-andritz-validated --apply

The selector cohort is data-driven. Showcase uses its seed marker, Andritz its
canonical workspace family, and internal workspaces must be named explicitly.
No mutable slug or System name participates in selection.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from app.db.base import SessionLocal
from app.models.system import System
from app.models.workspace import Workspace
from app.services.chains.variable_backfill import plan_variable_backfill
from app.services.chains.version_service import record_new_version
from app.services.workspace_features import workspace_family


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohort", required=True, choices=("showcase", "internal", "andritz"))
    parser.add_argument("--workspace-id", action="append", default=[])
    parser.add_argument(
        "--system-id",
        action="append",
        default=[],
        help="Restrict conversion to explicit Systems discovered by a trusted caller",
    )
    parser.add_argument("--apply", action="store_true", help="Persist new System snapshots")
    parser.add_argument("--report", type=Path, help="Write the JSON report to this path")
    parser.add_argument(
        "--confirm-andritz-validated",
        action="store_true",
        help="Required for an Andritz apply after its separate validation gate",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.cohort == "internal" and not args.workspace_id:
        raise SystemExit("internal cohort requires at least one explicit --workspace-id")
    if args.cohort == "andritz" and args.apply and not args.confirm_andritz_validated:
        raise SystemExit("Andritz apply requires --confirm-andritz-validated")

    db = SessionLocal()
    report: dict[str, Any] = {
        "schema_version": 1,
        "mode": "apply" if args.apply else "dry_run",
        "cohort": args.cohort,
        "workspaces": [],
        "summary": {"systems": 0, "changed": 0, "ambiguous": 0, "conversions": 0},
    }
    try:
        workspaces = _select_workspaces(db, cohort=args.cohort, ids=set(args.workspace_id))
        requested_system_ids = set(args.system_id)
        seen_system_ids: set[str] = set()
        for workspace in workspaces:
            workspace_report = {
                "workspace_id": workspace.id,
                "family": workspace_family(workspace),
                "systems": [],
            }
            systems_query = db.query(System).filter(System.workspace_id == workspace.id)
            if requested_system_ids:
                systems_query = systems_query.filter(System.id.in_(sorted(requested_system_ids)))
            systems = systems_query.order_by(System.id.asc()).all()
            for system in systems:
                seen_system_ids.add(system.id)
                plan = plan_variable_backfill(system.flow_definition or {})
                item: dict[str, Any] = {
                    "system_id": system.id,
                    "status": plan.status,
                    "changed": plan.changed,
                    "conversions": plan.conversions,
                    "unresolved": plan.unresolved,
                }
                report["summary"]["systems"] += 1
                report["summary"]["conversions"] += plan.conversions
                if plan.status == "ambiguous_overlay":
                    report["summary"]["ambiguous"] += 1
                if plan.changed:
                    report["summary"]["changed"] += 1
                    if args.apply:
                        version = record_new_version(
                            db=db,
                            system=system,
                            flow_definition=plan.flow,
                            created_by="system:flow-v3-variable-backfill",
                            audit_actor="system:flow-v3-variable-backfill",
                            message=f"Canonical v3 variable refs ({plan.conversions} conversions; {plan.status})",
                            purge=False,
                        )
                        system.flow_definition = plan.flow
                        db.flush()
                        item["new_version_id"] = version.id if version is not None else None
                workspace_report["systems"].append(item)
            report["workspaces"].append(workspace_report)

        missing_system_ids = requested_system_ids - seen_system_ids
        if missing_system_ids:
            raise ValueError(
                "requested Systems are absent from the selected workspace cohort: "
                + ", ".join(sorted(missing_system_ids))
            )

        if args.apply:
            db.commit()
        else:
            db.rollback()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    payload = json.dumps(report, indent=2, sort_keys=True)
    if args.report:
        args.report.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    return 0


def _select_workspaces(db, *, cohort: str, ids: set[str]) -> list[Workspace]:
    query = db.query(Workspace).filter(Workspace.deleted_at.is_(None))
    if ids:
        query = query.filter(Workspace.id.in_(sorted(ids)))
    candidates = query.order_by(Workspace.id.asc()).all()
    if cohort == "showcase":
        return [
            workspace
            for workspace in candidates
            if isinstance(workspace.settings, dict) and workspace.settings.get("showcase_seed") is True
        ]
    if cohort == "andritz":
        return [workspace for workspace in candidates if workspace_family(workspace) == "andritz"]
    return candidates


if __name__ == "__main__":
    raise SystemExit(main())
