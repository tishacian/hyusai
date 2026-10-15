#!/usr/bin/env python3
"""Explicit operator tools for the activity/control rollout (no service restart)."""

import argparse
import hashlib
import json
from pathlib import Path
from uuid import UUID

import app.models  # noqa: F401 - register models and transactional observers
from app.db.base import SessionLocal
from app.models.execution_control import ExecutionReservation
from app.services.activity_observability.projection import KINDS, backfill
from app.services.execution.admission import settle, snapshot


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    commands.add_parser("status", help="Read resource reservations; never infers worker liveness")
    fill = commands.add_parser(
        "backfill", help="Snapshot one page; persist returned after_id for resumption"
    )
    fill.add_argument("kind", choices=KINDS)
    fill.add_argument("--after-id")
    fill.add_argument("--limit", type=int, default=200, choices=range(1, 501), metavar="1..500")
    reconcile = commands.add_parser(
        "reconcile-stopped",
        help="Release a lost allocation after an operator verifies physical process stop",
    )
    reconcile.add_argument("reservation_id", type=UUID)
    reconcile.add_argument(
        "--evidence",
        type=Path,
        required=True,
        help="Local non-secret operational evidence, hashed into the record",
    )
    reconcile.add_argument("--operator", required=True, help="Accountable operator identifier")
    reconcile.add_argument("--confirm-process-stopped", action="store_true", required=True)
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    with SessionLocal() as db:
        if args.command == "status":
            result = snapshot(db)
        elif args.command == "backfill":
            result = backfill(db, kind=args.kind, after_id=args.after_id, limit=args.limit)
            db.commit()
        else:
            if not args.operator.strip() or len(args.operator) > 128:
                raise SystemExit("Operator must contain 1..128 characters")
            if not args.evidence.is_file() or not 0 < args.evidence.stat().st_size <= 1048576:
                raise SystemExit("Evidence must be a nonempty file <= 1 MiB")
            digest = hashlib.sha256(args.evidence.read_bytes()).hexdigest()
            row = (
                db.query(ExecutionReservation)
                .filter_by(id=str(args.reservation_id))
                .with_for_update()
                .one_or_none()
            )
            if row is None or row.outcome != "reconciliation_required" or row.released_at:
                raise SystemExit("Reservation must be unreconciled and not already released")
            row = settle(
                db,
                entity_kind=row.entity_kind,
                entity_id=row.entity_id,
                token=row.lease_token,
                outcome="operator_confirmed_stopped",
                process_stopped=True,
            )
            row.policy = {
                **row.policy,
                "reconciliation": {
                    "operator": args.operator,
                    "evidence_sha256": digest,
                    "physical_stop_asserted": True,
                },
            }
            db.commit()
            result = {
                "id": row.id,
                "released_at": row.released_at.isoformat(),
                "outcome": row.outcome,
                "evidence_sha256": digest,
                "cpu_seconds": None,
                "note": "Physical stop attested by operator; CPU usage remains unknown",
            }
        print(json.dumps(result, default=str, sort_keys=True))


if __name__ == "__main__":
    main()
