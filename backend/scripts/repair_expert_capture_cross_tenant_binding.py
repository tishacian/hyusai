#!/usr/bin/env python3
"""Audited plan/apply repair for one cross-tenant ExpertCaptureSession binding.

The Release A tenant gate refuses any ``ExpertCaptureSession -> System`` link
crossing workspaces.  This tool removes exactly the two invalid bindings
(``system_id`` and ``capability_id``) of one explicitly designated session and
never touches the session row itself, its Run, its Context, its events or its
proposals.  Every precondition is bound to the exact identity of the drifting
row: a mismatch refuses the operation without mutating anything.

``plan`` is the default and read-only.  ``apply`` additionally requires the
session id to be repeated through ``--confirm`` and re-counts the global
cross-tenant mismatches after the update before committing.  The emitted
receipt is content-free: identifiers, slugs, statuses and counters only.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from sqlalchemy import func

from app.db.base import SessionLocal
from app.models.expert_capture import (
    ExpertCaptureEvent,
    ExpertCaptureSession,
    KnowledgeUpdateProposal,
)
from app.models.system import System
from app.models.workspace import Workspace


class RepairRefused(RuntimeError):
    """The designated row does not match the audited drift exactly."""


def _cross_tenant_mismatch_count(db) -> int:
    return int(
        db.query(ExpertCaptureSession)
        .join(System, ExpertCaptureSession.system_id == System.id)
        .filter(ExpertCaptureSession.workspace_id != System.workspace_id)
        .count()
    )


def repair_cross_tenant_binding(
    db,
    *,
    session_id: str,
    expected_workspace_slug: str,
    expected_system_id: str,
    expected_capability_id: str,
    apply: bool,
) -> dict[str, Any]:
    """Validate the exact drifting row, then plan or apply the bounded repair."""

    session = (
        db.query(ExpertCaptureSession)
        .filter(ExpertCaptureSession.id == session_id)
        .first()
    )
    if session is None:
        raise RepairRefused("session is missing")

    workspace = (
        db.query(Workspace).filter(Workspace.id == session.workspace_id).first()
    )
    if workspace is None or str(workspace.slug) != expected_workspace_slug:
        raise RepairRefused("session workspace differs from the audited drift")

    if session.system_id != expected_system_id:
        raise RepairRefused("session system binding differs from the audited drift")
    system = db.query(System).filter(System.id == session.system_id).first()
    if system is None:
        raise RepairRefused("bound system is missing")
    if system.workspace_id == session.workspace_id:
        raise RepairRefused("binding is not cross-tenant; nothing to repair")

    if session.capability_id != expected_capability_id:
        raise RepairRefused(
            "session capability binding differs from the audited drift"
        )

    event_count = int(
        db.query(func.count(ExpertCaptureEvent.id))
        .filter(ExpertCaptureEvent.session_id == session.id)
        .scalar()
        or 0
    )
    proposal_count = int(
        db.query(func.count(KnowledgeUpdateProposal.id))
        .filter(KnowledgeUpdateProposal.session_id == session.id)
        .scalar()
        or 0
    )
    mismatches_before = _cross_tenant_mismatch_count(db)

    receipt: dict[str, Any] = {
        "schema_version": 1,
        "kind": "expert_capture_cross_tenant_binding_repair",
        "mode": "apply" if apply else "plan",
        "session_id": session.id,
        "session_workspace_id": session.workspace_id,
        "session_workspace_slug": str(workspace.slug),
        "session_status": session.status,
        "run_bound": bool(session.run_id),
        "context_bound": bool(session.context_id),
        "event_count": event_count,
        "proposal_count": proposal_count,
        "bindings_before": {
            "system_id": session.system_id,
            "system_workspace_id": system.workspace_id,
            "capability_id": session.capability_id,
        },
        "cross_tenant_mismatch_count_before": mismatches_before,
    }

    if not apply:
        receipt["result"] = "planned"
        db.rollback()
        return receipt

    session.system_id = None
    session.capability_id = None
    db.flush()

    reloaded = (
        db.query(ExpertCaptureSession)
        .filter(ExpertCaptureSession.id == session_id)
        .one()
    )
    mismatches_after = _cross_tenant_mismatch_count(db)
    if (
        reloaded.system_id is not None
        or reloaded.capability_id is not None
        or mismatches_after != mismatches_before - 1
    ):
        db.rollback()
        raise RepairRefused("post-update verification failed; rolled back")

    db.commit()
    receipt["result"] = "applied"
    receipt["bindings_after"] = {"system_id": None, "capability_id": None}
    receipt["cross_tenant_mismatch_count_after"] = mismatches_after
    return receipt


def _write_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--expected-workspace-slug", required=True)
    parser.add_argument("--expected-system-id", required=True)
    parser.add_argument("--expected-capability-id", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--confirm",
        help="required with --apply; must repeat the exact session id",
    )
    parser.add_argument("--output", type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.apply and args.confirm != args.session_id:
        print(
            "Repair refused: --apply requires --confirm with the exact session id",
            file=sys.stderr,
        )
        return 1
    with SessionLocal() as db:
        try:
            receipt = repair_cross_tenant_binding(
                db,
                session_id=args.session_id,
                expected_workspace_slug=args.expected_workspace_slug,
                expected_system_id=args.expected_system_id,
                expected_capability_id=args.expected_capability_id,
                apply=args.apply,
            )
        except RepairRefused as exc:
            db.rollback()
            print(f"Repair refused: {exc}", file=sys.stderr)
            return 1
    if args.output:
        _write_atomic(args.output, receipt)
    else:
        print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
