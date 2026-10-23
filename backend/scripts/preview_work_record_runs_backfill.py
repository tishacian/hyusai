#!/usr/bin/env python3
"""Link historical Work Runs to their record's attempts: preview, apply, revert.

Preview (the default) reads Runs and releases and prints a JSON report; it
never writes. A Run qualifies when it was started by a Work application whose
released binding declares a record identity (or whose business reader
supplies one) and its input carries the record reference. Selection is
explicit by immutable workspace id.

``--apply`` links the qualifying Runs, in one transaction:

- it only inserts into ``work_record_runs``; no Run, release or binding is
  modified;
- it is idempotent: a Run already linked (by its start or an earlier batch)
  is skipped;
- each row keeps the Run's start time, so attempts stay in their real order,
  and is stamped with the batch id;
- every linked row is logged, and ``--expect N`` refuses to write when the
  number of Runs to link differs from the preview the operator approved.

``--revert BATCH`` removes exactly the rows that batch created, nothing else.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

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


class BackfillRefused(RuntimeError):
    """The apply did not write anything; the message says why."""


def _classify(db: DBSession, *, workspace_id: str) -> tuple[Counter, list[dict[str, Any]]]:
    """Every Work Run of the workspace, with the reason it can or cannot be linked."""
    workspace = db.get(Workspace, workspace_id)
    linked = {
        run_id
        for (run_id,) in db.query(WorkRecordRun.run_id).filter(WorkRecordRun.workspace_id == workspace_id)
    }
    releases: dict[str, Any] = {}
    reasons: Counter[str] = Counter()
    candidates: list[dict[str, Any]] = []
    query = db.query(Run).filter(Run.workspace_id == workspace_id).order_by(Run.started_at, Run.id)
    for run in query.yield_per(500):
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
        candidates.append(
            {
                "run_id": run.id,
                "namespace": identity.get("namespace"),
                "record_ref": record_ref,
                "binding_key": adapter.get("binding_key"),
                "experience_id": adapter.get("experience_id") or release.experience_id,
                "initiated_by_user_id": run.initiated_by_user_id,
                "started_at": run.started_at,
            }
        )
    return reasons, candidates


def _public(candidate: dict[str, Any]) -> dict[str, Any]:
    keys = ("run_id", "namespace", "record_ref", "binding_key", "initiated_by_user_id")
    return {key: candidate[key] for key in keys}


def preview(db: DBSession, *, workspace_id: str, sample: int = 20) -> dict[str, Any]:
    """Classify the workspace's Work Runs without writing anything."""
    reasons, candidates = _classify(db, workspace_id=workspace_id)
    return {
        "mode": "preview",
        "writes": 0,
        "workspace_id": workspace_id,
        "counts": dict(sorted(reasons.items())),
        "sample": [_public(item) for item in candidates[: max(0, sample)]],
    }


def apply(
    db: DBSession,
    *,
    workspace_id: str,
    expect: Optional[int] = None,
    batch_id: Optional[str] = None,
    log=None,
) -> dict[str, Any]:
    """Link every qualifying Run, in one transaction. Commits on success."""
    if db.get(Workspace, workspace_id) is None:
        raise BackfillRefused(f"Unknown workspace {workspace_id}.")
    reasons, candidates = _classify(db, workspace_id=workspace_id)
    if expect is not None and len(candidates) != expect:
        raise BackfillRefused(
            f"{len(candidates)} Runs would be linked, not the {expect} expected. "
            "Nothing was written; preview again."
        )
    batch = batch_id or str(uuid4())
    rows = []
    for candidate in candidates:
        # Re-checked inside the transaction: a Run linked meanwhile is skipped.
        if db.query(WorkRecordRun.id).filter(WorkRecordRun.run_id == candidate["run_id"]).first():
            reasons["already_linked"] += 1
            continue
        row = WorkRecordRun(
            id=str(uuid4()),
            workspace_id=workspace_id,
            experience_id=str(candidate["experience_id"] or ""),
            binding_key=str(candidate["binding_key"] or ""),
            record_namespace=str(candidate["namespace"]),
            record_ref=candidate["record_ref"],
            run_id=candidate["run_id"],
            initiated_by_user_id=candidate["initiated_by_user_id"],
            # The attempt's real time, so the history keeps its order.
            created_at=candidate["started_at"],
            backfill_batch_id=batch,
        )
        db.add(row)
        rows.append(row)
        if log is not None:
            log(json.dumps({"batch_id": batch, "row_id": row.id, **_public(candidate)}, sort_keys=True))
    db.flush()
    db.commit()
    reasons.pop("would_link", None)
    return {
        "mode": "apply",
        "workspace_id": workspace_id,
        "batch_id": batch,
        "writes": len(rows),
        "linked": [{"row_id": row.id, "run_id": row.run_id, "record_ref": row.record_ref} for row in rows],
        "not_linked": dict(sorted(reasons.items())),
    }


def revert(db: DBSession, *, workspace_id: str, batch_id: str, log=None) -> dict[str, Any]:
    """Remove the rows one batch created, and only those. Commits."""
    rows = (
        db.query(WorkRecordRun)
        .filter(WorkRecordRun.workspace_id == workspace_id, WorkRecordRun.backfill_batch_id == batch_id)
        .all()
    )
    for row in rows:
        if log is not None:
            log(json.dumps({"batch_id": batch_id, "removed_row_id": row.id, "run_id": row.run_id}, sort_keys=True))
        db.delete(row)
    db.commit()
    return {"mode": "revert", "workspace_id": workspace_id, "batch_id": batch_id, "removed": len(rows)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--workspace-id", required=True)
    parser.add_argument("--sample", type=int, default=20, help="preview only: Runs listed")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="link the qualifying Runs (writes)")
    mode.add_argument("--revert", metavar="BATCH_ID", help="remove the rows of one batch (writes)")
    parser.add_argument("--expect", type=int, help="apply only: refuse unless exactly this many Runs qualify")
    args = parser.parse_args(argv)
    if args.expect is not None and not args.apply:
        parser.error("--expect is only meaningful with --apply")

    def log(line: str) -> None:
        print(line, file=sys.stderr, flush=True)

    db = SessionLocal()
    try:
        if args.apply:
            report = apply(db, workspace_id=args.workspace_id, expect=args.expect, log=log)
        elif args.revert:
            report = revert(db, workspace_id=args.workspace_id, batch_id=args.revert, log=log)
        else:
            report = preview(db, workspace_id=args.workspace_id, sample=max(0, args.sample))
    except BackfillRefused as exc:
        db.rollback()
        print(json.dumps({"mode": "apply", "writes": 0, "refused": str(exc)}, indent=2), flush=True)
        return 2
    except Exception:
        db.rollback()
        raise
    finally:
        if not (args.apply or args.revert):
            db.rollback()
        db.close()
    print(json.dumps(report, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
