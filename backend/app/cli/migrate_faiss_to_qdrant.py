"""Migrate workspace FAISS vector collections to Qdrant."""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from app.services.vector_db.factory import VectorDBFactory
from app.services.vector_db.faiss_to_qdrant import (
    MigrationReport,
    migrate_faiss_collection_to_qdrant,
    run_migration,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Copy workspace-scoped FAISS vectors into Qdrant with parity validation."
    )
    parser.add_argument("--workspace", required=True, help="Workspace slug, e.g. andritz")
    parser.add_argument(
        "--collection",
        action="append",
        help="Logical collection slug. Repeat for multiple. Defaults to all FAISS collections in workspace.",
    )
    parser.add_argument("--batch-size", type=int, default=512)
    parser.add_argument(
        "--dry-run",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Inspect source/target parity without writing to Qdrant. Default: true.",
    )
    parser.add_argument(
        "--replace-target",
        action="store_true",
        help="Delete the target Qdrant collection before writing. FAISS source is never modified.",
    )
    parser.add_argument(
        "--switch-preset",
        action="store_true",
        help="After strict validation, set the workspace default RAG preset to qdrant.",
    )
    parser.add_argument(
        "--allow-extra-target-ids",
        action="store_true",
        help="Allow Qdrant to contain IDs that are not in FAISS. Not recommended for cutover.",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    return parser


def _workspace(db: Any, slug: str) -> Any:
    from app.models.workspace import Workspace

    row = db.query(Workspace).filter(Workspace.slug == slug).first()
    if not row:
        raise SystemExit(f"Workspace {slug!r} not found")
    return row


def _collections(workspace: Any, requested: list[str] | None) -> list[str]:
    if requested:
        return requested
    names = VectorDBFactory.list_collections_for_workspace(
        db_type="faiss",
        workspace_slug=workspace.slug,
    )
    if not names:
        raise SystemExit(f"No FAISS collections found for workspace {workspace.slug!r}")
    return names


def _qdrant_client():
    from app.core.config import settings
    from qdrant_client import QdrantClient

    return QdrantClient(
        host=settings.qdrant_host,
        port=settings.qdrant_port,
        api_key=settings.qdrant_api_key or None,
        https=settings.qdrant_https,
    )


def _patch_workspace_preset_to_qdrant(db: Any, workspace: Any) -> dict[str, Any]:
    from app.models.rag_preset import RagPreset
    from app.services.rag_preset_service import RagPresetService

    preset = (
        db.query(RagPreset)
        .filter(
            RagPreset.scope == "workspace",
            RagPreset.scope_id == workspace.id,
            RagPreset.is_default.is_(True),
        )
        .first()
    )
    if preset:
        config = dict(preset.config or {})
        previous = config.get("ragVectorDBType")
        config["ragVectorDBType"] = "qdrant"
        preset.config = config
        db.commit()
        db.refresh(preset)
        return {
            "action": "updated",
            "preset_id": preset.id,
            "previous_ragVectorDBType": previous,
            "ragVectorDBType": "qdrant",
        }

    config = RagPresetService.resolve_for(db, workspace_id=workspace.id)
    previous = config.get("ragVectorDBType")
    config["ragVectorDBType"] = "qdrant"
    created = RagPresetService.create_preset(
        db,
        name="Workspace Default",
        scope="workspace",
        scope_id=workspace.id,
        workspace_id=workspace.id,
        config=config,
        is_default=True,
    )
    return {
        "action": "created",
        "preset_id": created["id"],
        "previous_ragVectorDBType": previous,
        "ragVectorDBType": "qdrant",
    }


def _print(payload: dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    for report in payload["reports"]:
        status = "OK" if report["strict_match"] else "CHECK"
        print(
            f"[{status}] {report['workspace_slug']}/{report['logical_collection']} "
            f"source={report['source_count']} target_before={report['target_count_before']} "
            f"target_after={report['target_count_after']} dry_run={report['dry_run']}"
        )
        if report["missing_target_ids"]:
            print(f"  missing_target_ids={len(report['missing_target_ids'])}")
        if report["extra_target_ids"]:
            print(f"  extra_target_ids={len(report['extra_target_ids'])}")
    if payload.get("preset_switch"):
        print(f"preset_switch={payload['preset_switch']}")


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    from app.db.base import SessionLocal

    db = SessionLocal()
    try:
        workspace = _workspace(db, args.workspace)
        collections = _collections(workspace, args.collection)
        qdrant_client = _qdrant_client()

        reports: list[MigrationReport] = []
        for collection in collections:
            report = run_migration(
                migrate_faiss_collection_to_qdrant(
                    workspace=workspace,
                    collection=collection,
                    qdrant_client=qdrant_client,
                    batch_size=args.batch_size,
                    dry_run=args.dry_run,
                    replace_target=args.replace_target,
                )
            )
            reports.append(report)

        report_payloads = [report.as_dict() for report in reports]
        blocking = []
        for report in reports:
            has_extra = bool(report.extra_target_ids)
            if report.missing_target_ids or (has_extra and not args.allow_extra_target_ids):
                blocking.append(report.logical_collection)
            if report.target_count_after != report.source_count and not (
                has_extra and args.allow_extra_target_ids
            ):
                if report.logical_collection not in blocking:
                    blocking.append(report.logical_collection)

        preset_switch = None
        if args.switch_preset:
            if args.dry_run:
                raise SystemExit("--switch-preset requires --no-dry-run")
            if blocking:
                raise SystemExit(
                    "Strict validation failed; refusing preset switch for: "
                    + ", ".join(sorted(blocking))
                )
            preset_switch = _patch_workspace_preset_to_qdrant(db, workspace)

        payload = {
            "workspace": workspace.slug,
            "dry_run": args.dry_run,
            "replace_target": args.replace_target,
            "reports": report_payloads,
            "preset_switch": preset_switch,
        }
        _print(payload, as_json=args.json)
        return 1 if blocking and not args.dry_run else 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
