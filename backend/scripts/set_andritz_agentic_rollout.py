"""Set the migration-059 Andritz Agentic chat rollout percentage safely.

Examples (from ``backend/``)::

    python -m scripts.set_andritz_agentic_rollout --percentage 5 --actor release-operator --dry-run
    python -m scripts.set_andritz_agentic_rollout --percentage 5 --actor release-operator

Every non-dry-run update and its ``chat.execution.rollout.updated`` audit row
are committed in the same database transaction.  Any invariant drift exits
non-zero and rolls the whole operation back.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from app.db.base import SessionLocal
from app.services.andritz_agentic_rollout import (
    RolloutInvariantError,
    normalize_percentage,
    set_andritz_agentic_rollout,
)


def _percentage(value: str) -> int | float:
    try:
        return normalize_percentage(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--percentage",
        type=_percentage,
        required=True,
        help="Stable rollout percentage between 0 and 100.",
    )
    parser.add_argument(
        "--actor",
        required=True,
        help="Named human or service identity recorded in the audit event.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Lock and validate every invariant, but do not write settings or audit rows.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    db = SessionLocal()
    try:
        try:
            result = set_andritz_agentic_rollout(
                db,
                percentage=args.percentage,
                actor=args.actor,
                dry_run=args.dry_run,
            )
            if args.dry_run:
                # No writes are staged, but explicitly rollback so a dry-run
                # can never become mutating if the service evolves later.
                db.rollback()
            else:
                db.commit()
        except (RolloutInvariantError, ValueError) as exc:
            db.rollback()
            print(f"andritz_agentic_rollout refused: {exc}", file=sys.stderr)
            return 2
        except Exception as exc:  # noqa: BLE001 - command must rollback/fail closed
            db.rollback()
            print(f"andritz_agentic_rollout failed: {exc}", file=sys.stderr)
            return 1
    finally:
        db.close()

    print(json.dumps(result.as_dict(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
