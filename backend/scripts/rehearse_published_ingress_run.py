"""Drive one published-ingress Run to a terminal state and report where it died.

``measure_flow_dispatch_readiness`` answers whether an adapter would be *served*.
It cannot answer whether the Run that adapter accepts then *completes*, and the
legacy graphs whose ingresses now compile are legacy well past their entry
points. This creates a real Run through ``flow_ingress.create_published_ingress_run``
and executes it through ``run_engine.schedule_run`` — the same two calls the
manual dispatch endpoint makes — then reports the terminal status, the failing
node and every checkpoint the walker left behind.

It executes Skills for real. Point it at a rehearsal copy, never at production::

    python -m scripts.rehearse_published_ingress_run \
        --system-id <uuid> --kind manual --report run.json
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
from app.models.run import Run, SkillInvocation  # noqa: E402
from app.models.system import System  # noqa: E402
from app.models.workspace import Workspace  # noqa: E402
from app.services.run_engine import schedule_run  # noqa: E402
from app.services.systems import flow_ingress  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--system-id", required=True)
    parser.add_argument("--kind", default="manual")
    parser.add_argument("--ingress-id", default=None)
    parser.add_argument("--payload", default="{}", help="JSON ingress payload")
    parser.add_argument("--report", type=Path)
    return parser.parse_args()


def _invocations(db: Any, run_id: str) -> list[dict[str, Any]]:
    rows = (
        db.query(SkillInvocation)
        .filter(SkillInvocation.run_id == run_id)
        .order_by(SkillInvocation.started_at.asc())
        .all()
    )
    return [
        {
            "skill_slug": row.skill_slug,
            "status": row.status,
            "error": row.error,
            "latency_ms": row.latency_ms,
            "node_id": (row.trace or {}).get("node_id") if isinstance(row.trace, dict) else None,
        }
        for row in rows
    ]


def main() -> int:
    args = parse_args()
    db = SessionLocal()
    report: dict[str, Any] = {"system_id": args.system_id, "kind": args.kind}
    try:
        system = db.query(System).filter(System.id == args.system_id).one_or_none()
        if system is None:
            report["error"] = "system_not_found"
            print(json.dumps(report, indent=2, sort_keys=True))
            return 1
        workspace = db.query(Workspace).filter(Workspace.id == system.workspace_id).one()
        report["system_name"] = system.name
        report["workspace"] = workspace.slug

        published = flow_ingress.assert_dispatchable(
            db, system_id=system.id, workspace=workspace
        )
        contract = published["execution_contract"]
        report["runtime_mode"] = contract.get("runtime_mode")
        report["contract"] = {
            "ingresses": [
                {"ingress_id": row.get("ingress_id"), "kind": row.get("kind")}
                for row in contract.get("ingresses") or []
            ],
            "node_ids": sorted(contract.get("nodes") or {}),
            "output_node_ids": [row.get("node_id") for row in contract.get("outputs") or []],
        }

        try:
            run = flow_ingress.create_published_ingress_run(
                db,
                system_id=system.id,
                workspace=workspace,
                ingress_id=args.ingress_id,
                kind=args.kind,
                payload=json.loads(args.payload),
                expected_published_version_id=published["published_flow_version_id"],
                expected_flow_sha256=published["flow_sha256"],
                adapter_evidence={"surface": "rehearsal_harness"},
            )
        except flow_ingress.FlowIngressError as exc:
            db.rollback()
            report["accepted"] = False
            report["refused"] = {"code": exc.code, "message": exc.message, "details": exc.details}
            print(json.dumps(report, indent=2, sort_keys=True))
            return 1
        db.commit()
        run_id = run.id
        report["accepted"] = True
        report["run_id"] = run_id
    finally:
        db.close()

    # The same call the manual dispatch endpoint hands to BackgroundTasks: it
    # picks the sequential or DAG walker from the Run's own snapshot.
    schedule_run(run_id)

    db = SessionLocal()
    try:
        run = db.query(Run).filter(Run.id == run_id).one()
        report["terminal_status"] = run.status
        report["error"] = run.error
        report["checkpoints"] = run.checkpoints
        report["output_ref"] = run.output_ref
        report["invocations"] = _invocations(db, run_id)
    finally:
        db.close()

    payload = json.dumps(report, indent=2, sort_keys=True, default=str)
    if args.report:
        args.report.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    return 0 if report.get("terminal_status") == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
