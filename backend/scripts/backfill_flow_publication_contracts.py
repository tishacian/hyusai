"""Pin an execution contract on every published Flow that lacks one.

Examples::

    python -m scripts.backfill_flow_publication_contracts
    python -m scripts.backfill_flow_publication_contracts --workspace-id <uuid>
    python -m scripts.backfill_flow_publication_contracts --apply \
        --actor operator@example.net --report contracts.json

Migrations 077 and 081 give every System a published pointer, but they leave
``execution_contract`` NULL: a contract is compiled from workspace Skills, which
Alembic must not reach. A published version without one is valid history and
hydrates fine, yet refuses to run with ``PUBLISHED_EXECUTION_CONTRACT_MISSING``.
The remedy the service already implements is one explicit Publish, which appends
a version carrying the frozen contract even when the graph bytes are unchanged.
This script performs that Publish for the whole estate.

Run it after ``081_flow_publication_default_posture`` and before traffic resumes.
A System whose draft has moved ahead of its published version is skipped, never
published: promoting unreviewed editor work is exactly the destructive behaviour
draft/publish separation exists to prevent.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db.base import SessionLocal  # noqa: E402
from app.models.system import System  # noqa: E402
from app.models.system_flow_draft import SystemFlowDraft  # noqa: E402
from app.models.system_version import SystemVersion  # noqa: E402
from app.models.workspace import Workspace  # noqa: E402
from app.services import flow_contracts  # noqa: E402
from app.services.systems import flow_publication  # noqa: E402

MESSAGE = "Pin execution contract for the migration publication baseline"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-id", action="append", default=[])
    parser.add_argument("--system-id", action="append", default=[])
    parser.add_argument("--apply", action="store_true", help="Persist the publications")
    parser.add_argument("--actor", default="system:flow-contract-backfill")
    parser.add_argument("--report", type=Path, help="Write the JSON report to this path")
    return parser.parse_args()


def _contract_pinned(version: SystemVersion | None) -> bool:
    if version is None:
        return False
    try:
        flow_contracts.validate_execution_contract(version.execution_contract)
    except flow_contracts.FlowContractError:
        return False
    return bool(version.flow_sha256)


def _plan(db: Any, system: System) -> dict[str, Any]:
    """Classify a System without mutating it. ``action`` drives the apply pass."""

    item: dict[str, Any] = {"system_id": system.id, "status": system.status}
    if not system.published_flow_version_id:
        item["action"] = "skipped"
        item["reason"] = "no published pointer; run migration 081 first"
        return item

    version = (
        db.query(SystemVersion)
        .filter(
            SystemVersion.id == system.published_flow_version_id,
            SystemVersion.system_id == system.id,
        )
        .one_or_none()
    )
    if _contract_pinned(version):
        item["action"] = "already_pinned"
        return item

    draft = (
        db.query(SystemFlowDraft).filter(SystemFlowDraft.system_id == system.id).one_or_none()
    )
    if draft is None:
        item["action"] = "skipped"
        item["reason"] = "no server draft; run migration 081 first"
        return item
    if version is not None and draft.flow_sha256 != version.flow_sha256:
        item["action"] = "skipped"
        item["reason"] = "draft differs from the published version; publish it by hand"
        item["draft_revision"] = draft.revision
        return item

    item["action"] = "publish"
    item["draft_revision"] = draft.revision
    item["published_flow_version_id"] = system.published_flow_version_id
    return item


def main() -> int:
    args = parse_args()
    db = SessionLocal()
    report: dict[str, Any] = {
        "schema_version": 1,
        "mode": "apply" if args.apply else "dry_run",
        "workspaces": [],
        "summary": {
            "systems": 0,
            "already_pinned": 0,
            "publish": 0,
            "published": 0,
            "skipped": 0,
            "failed": 0,
        },
    }
    summary = report["summary"]
    try:
        workspace_query = db.query(Workspace).filter(Workspace.deleted_at.is_(None))
        if args.workspace_id:
            workspace_query = workspace_query.filter(
                Workspace.id.in_(sorted(set(args.workspace_id)))
            )
        for workspace in workspace_query.order_by(Workspace.id.asc()).all():
            workspace_report: dict[str, Any] = {
                "workspace_id": workspace.id,
                "publication_enabled": flow_publication.flow_publication_enabled(workspace),
                "systems": [],
            }
            report["workspaces"].append(workspace_report)
            if not workspace_report["publication_enabled"]:
                workspace_report["skipped"] = "flow_publication_v1 is off for this workspace"
                continue

            systems_query = db.query(System).filter(System.workspace_id == workspace.id)
            if args.system_id:
                systems_query = systems_query.filter(System.id.in_(sorted(set(args.system_id))))
            for system in systems_query.order_by(System.id.asc()).all():
                item = _plan(db, system)
                summary["systems"] += 1
                if item["action"] != "publish":
                    summary["already_pinned" if item["action"] == "already_pinned" else "skipped"] += 1
                    workspace_report["systems"].append(item)
                    continue

                summary["publish"] += 1
                if args.apply:
                    try:
                        version, _draft, no_op = flow_publication.publish_draft(
                            db,
                            system_id=system.id,
                            workspace=workspace,
                            expected_draft_revision=int(item["draft_revision"]),
                            expected_published_version_id=item["published_flow_version_id"],
                            message=MESSAGE,
                            # The graph is unchanged, so any breaking finding
                            # comes from materializing the absent contract.
                            breaking_change_intent="acknowledged",
                            actor=args.actor,
                        )
                    except flow_publication.FlowPublicationError as exc:
                        db.rollback()
                        item["action"] = "failed"
                        item["error"] = {"code": exc.code, "message": exc.message}
                        summary["failed"] += 1
                        workspace_report["systems"].append(item)
                        continue
                    db.commit()
                    item["action"] = "no_op" if no_op else "published"
                    item["new_published_version_id"] = version.id
                    summary["published"] += 1
                workspace_report["systems"].append(item)
    finally:
        db.rollback()
        db.close()

    payload = json.dumps(report, indent=2, sort_keys=True)
    if args.report:
        args.report.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    return 1 if summary["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
