#!/usr/bin/env python3
"""Backfill chat Run outcomes for Observability/Hypervisor demos.

Default mode is dry-run. Use ``--apply`` to mutate eligible Run rows.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.db.base import SessionLocal  # noqa: E402
from app.models.run import Run  # noqa: E402
from app.models.workspace import Workspace  # noqa: E402
from app.services.chat_run_ledger import enrich_chat_run_ledger  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill completed chat Run outcomes.")
    parser.add_argument("--workspace-slug", default="andritz", help="Workspace slug to target.")
    parser.add_argument("--limit", type=int, default=500, help="Maximum eligible runs to inspect.")
    parser.add_argument("--apply", action="store_true", help="Apply changes. Omit for dry-run.")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        workspace = db.query(Workspace).filter(Workspace.slug == args.workspace_slug).first()
        if not workspace:
            print(json.dumps({"status": "workspace_not_found", "workspace_slug": args.workspace_slug}, indent=2))
            return 2

        rows = (
            db.query(Run)
            .filter(Run.workspace_id == workspace.id, Run.status == "completed")
            .order_by(Run.started_at.desc())
            .limit(max(1, args.limit))
            .all()
        )
        eligible = [run for run in rows if _is_target(run)]
        changed: list[dict[str, Any]] = []
        for run in eligible:
            output = run.output_ref or {}
            item = {
                "run_id": run.id,
                "system_id": run.system_id,
                "had_capability": bool(run.capability_id),
                "had_outcome": not _missing_outcome(run),
                "started_at": run.started_at.isoformat() if run.started_at else None,
            }
            if args.apply:
                result = enrich_chat_run_ledger(
                    db,
                    run,
                    sources=output.get("sources"),
                    reasoning_trace=output.get("reasoning_trace"),
                    extra_output=output,
                    create_invocations_if_missing=True,
                )
                item["result"] = result
            changed.append(item)

        if args.apply:
            db.commit()
        else:
            db.rollback()

        print(
            json.dumps(
                {
                    "status": "applied" if args.apply else "dry_run",
                    "workspace": {"id": workspace.id, "slug": workspace.slug, "name": workspace.name},
                    "scanned": len(rows),
                    "eligible": len(eligible),
                    "items": changed[:50],
                    "truncated": len(changed) > 50,
                },
                indent=2,
                default=str,
            )
        )
        return 0
    finally:
        db.close()


def _is_target(run: Run) -> bool:
    if (run.trigger or "") not in {"chat", "trivial_bypass"}:
        return False
    output = run.output_ref or {}
    if not str(output.get("response") or "").strip():
        return False
    return not run.capability_id or _missing_outcome(run)


def _missing_outcome(run: Run) -> bool:
    return any(
        value is None
        for value in (
            run.decision,
            run.cost_internal,
            run.value_estimated,
            run.value_source,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
