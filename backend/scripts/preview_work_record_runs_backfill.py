#!/usr/bin/env python3
"""Preview which historical Work Runs could join their record's attempts.

Preview only: this script reads Runs and releases and prints a JSON report.
It has no apply mode and never writes. A Run qualifies when it was started by
a Work application whose released binding declares a record identity and its
input carries the record reference. Selection is explicit by immutable
workspace id.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy.orm import Session as DBSession  # noqa: E402

from app.db.base import SessionLocal  # noqa: E402
from app.models.experience import ExperienceRelease  # noqa: E402
from app.models.run import Run  # noqa: E402
from app.models.work_record_run import WorkRecordRun  # noqa: E402
from app.models.workspace import Workspace  # noqa: E402
from app.services.experience.bindings import record_ref_from_payload  # noqa: E402
from app.services.experience.record_identity import resolve_record_identity  # noqa: E402


def preview(db: DBSession, *, workspace_id: str, sample: int = 20) -> dict[str, Any]:
    """Classify the workspace's Work Runs without writing anything."""
    workspace = db.get(Workspace, workspace_id)
    linked = {
        run_id
        for (run_id,) in db.query(WorkRecordRun.run_id).filter(WorkRecordRun.workspace_id == workspace_id)
    }
    releases: dict[str, Any] = {}
    reasons: Counter[str] = Counter()
    candidates: list[dict[str, Any]] = []
    for run in db.query(Run).filter(Run.workspace_id == workspace_id).yield_per(500):
        ingress = (run.input_ref or {}).get("_ingress") if isinstance(run.input_ref, dict) else None
        adapter = ingress.get("adapter") if isinstance(ingress, dict) else None
        if not isinstance(adapter, dict) or adapter.get("surface") != "experience":
            continue
        if run.id in linked:
            reasons["already_linked"] += 1
            continue
        release_id = adapter.get("experience_release_id")
        if release_id not in releases:
            releases[release_id] = db.get(ExperienceRelease, release_id) if release_id else None
        release = releases[release_id]
        if release is None:
            reasons["release_missing"] += 1
            continue
        binding = next(
            (
                item
                for item in release.bindings_snapshot or []
                if isinstance(item, dict) and item.get("binding_key") == adapter.get("binding_key")
            ),
            None,
        )
        identity = resolve_record_identity(
            binding, workspace=workspace, experience_slug=adapter.get("experience_slug")
        )
        if not identity:
            reasons["binding_without_record_identity"] += 1
            continue
        record_ref = record_ref_from_payload(identity, run.input_ref)
        if record_ref is None:
            reasons["record_reference_missing"] += 1
            continue
        reasons["would_link"] += 1
        if len(candidates) < sample:
            candidates.append(
                {
                    "run_id": run.id,
                    "namespace": identity.get("namespace"),
                    "record_ref": record_ref,
                    "binding_key": adapter.get("binding_key"),
                    "initiated_by_user_id": run.initiated_by_user_id,
                }
            )
    return {
        "mode": "preview",
        "writes": 0,
        "workspace_id": workspace_id,
        "counts": dict(sorted(reasons.items())),
        "sample": candidates,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-id", required=True)
    parser.add_argument("--sample", type=int, default=20)
    args = parser.parse_args(argv)
    db = SessionLocal()
    try:
        report = preview(db, workspace_id=args.workspace_id, sample=max(0, args.sample))
    finally:
        db.rollback()
        db.close()
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
