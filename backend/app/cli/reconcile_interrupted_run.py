"""Preview or close an interrupted inline Run after explicit process-stop proof.

No execution or approval is repeated. Run inside the operator's backend image;
the CLI's deployment credentials confer authority, not a client-supplied actor.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from uuid import UUID

import app.models  # noqa: F401 - register transactional observers and models
from app.db.base import SessionLocal
from app.services.run_engine.interrupted_run import InterruptedRunError, preview, reconcile


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    for name in ("workspace-id", "run-id", "decision-id", "invocation-id"):
        result.add_argument(f"--{name}", type=UUID, required=True)
    result.add_argument("--apply", action="store_true", help="Default is a read-only preview")
    result.add_argument(
        "--expected-state-sha256", help="Exact token returned by the reviewed preview"
    )
    result.add_argument("--operator", help="Accountable operator identifier")
    result.add_argument(
        "--evidence", type=Path, help="Non-secret process-stop evidence file, at most 1 MiB"
    )
    result.add_argument("--confirm-process-stopped", action="store_true")
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    identity = {
        name: str(getattr(args, name))
        for name in ("workspace_id", "run_id", "decision_id", "invocation_id")
    }
    attestation = {}
    if args.apply:
        if not args.confirm_process_stopped or not args.operator or not args.expected_state_sha256:
            raise SystemExit(
                "Apply requires operator, reviewed state token and explicit process-stop confirmation"
            )
        if args.evidence is None or not args.evidence.is_file():
            raise SystemExit("Apply requires a local process-stop evidence file")
        if not 0 < args.evidence.stat().st_size <= 1_048_576:
            raise SystemExit("Evidence must be nonempty and at most 1 MiB")
        attestation = {
            "expected_state_sha256": args.expected_state_sha256,
            "operator": args.operator,
            "evidence_sha256": hashlib.sha256(args.evidence.read_bytes()).hexdigest(),
            "evidence_ref": args.evidence.name,
            "confirm_process_stopped": True,
        }
    try:
        with SessionLocal() as db:
            result = (
                reconcile(db, **identity, **attestation) if args.apply else preview(db, **identity)
            )
            if args.apply:
                db.commit()
    except InterruptedRunError as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps(result, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
