"""Count, per adapter kind, how many Systems a published contract would serve.

The backfill report says whether a Publish succeeded. It does not say whether
the contract that Publish froze can actually accept a Run, which is the
question a deployment window needs answered: a System can publish cleanly and
still refuse every adapter because its compiled ``ingresses`` array is empty.

This replays the two gates the dispatch path applies — ``assert_dispatchable``
for the publication state, then ``resolve_published_ingress_id`` per adapter
kind — over every System in the database. It creates no Run and mutates
nothing.

Point it at a rehearsal copy, never at production::

    python -m scripts.measure_flow_dispatch_readiness --report readiness.json
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

from app.db.base import SessionLocal  # noqa: E402
from app.models.system import System  # noqa: E402
from app.models.workspace import Workspace  # noqa: E402
from app.services.systems import flow_ingress, flow_publication  # noqa: E402

ADAPTER_KINDS = ("manual", "chat", "http", "schedule", "event")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, help="Write the JSON report to this path")
    return parser.parse_args()


def _system_readiness(db: Any, system: System, workspace: Any) -> dict[str, Any]:
    item: dict[str, Any] = {
        "system_id": system.id,
        "system_name": system.name,
        "workspace": getattr(workspace, "name", None),
        "status": system.status,
    }
    try:
        published = flow_ingress.assert_dispatchable(
            db,
            system_id=system.id,
            workspace=workspace,
        )
    except flow_ingress.FlowIngressError as exc:
        item["dispatchable"] = False
        item["blocked"] = {"code": exc.code, "message": exc.message}
        item["serves"] = []
        return item

    contract = published["execution_contract"]
    ingresses = contract.get("ingresses")
    item["dispatchable"] = True
    item["ingress_count"] = len(ingresses) if isinstance(ingresses, list) else 0
    item["ingresses"] = [
        {"ingress_id": row.get("ingress_id"), "kind": row.get("kind")}
        for row in (ingresses if isinstance(ingresses, list) else [])
    ]
    serves: list[str] = []
    refused: dict[str, str] = {}
    for kind in ADAPTER_KINDS:
        try:
            flow_ingress.resolve_published_ingress_id(
                contract,
                kind=kind,
                requested_ingress_id=None,
            )
        except flow_ingress.FlowIngressError as exc:
            refused[kind] = exc.code
        else:
            serves.append(kind)
    item["serves"] = serves
    item["refused"] = refused
    return item


def main() -> int:
    args = parse_args()
    db = SessionLocal()
    report: dict[str, Any] = {"systems": [], "summary": {}}
    per_kind: Counter[str] = Counter()
    blocked: Counter[str] = Counter()
    totals = Counter()
    try:
        workspaces = (
            db.query(Workspace)
            .filter(Workspace.deleted_at.is_(None))
            .order_by(Workspace.id.asc())
            .all()
        )
        for workspace in workspaces:
            if not flow_publication.flow_publication_enabled(workspace):
                continue
            systems = (
                db.query(System)
                .filter(System.workspace_id == workspace.id)
                .order_by(System.id.asc())
                .all()
            )
            for system in systems:
                item = _system_readiness(db, system, workspace)
                totals["systems"] += 1
                if item["dispatchable"]:
                    totals["dispatchable"] += 1
                    if item["ingress_count"]:
                        totals["with_ingress"] += 1
                    else:
                        totals["vacuous_contract"] += 1
                    for kind in item["serves"]:
                        per_kind[kind] += 1
                else:
                    blocked[item["blocked"]["code"]] += 1
                report["systems"].append(item)
    finally:
        db.rollback()
        db.close()

    report["summary"] = {
        "systems": totals["systems"],
        "dispatchable": totals["dispatchable"],
        "with_non_empty_ingresses": totals["with_ingress"],
        "published_but_vacuous": totals["vacuous_contract"],
        "would_accept_a_run_by_kind": dict(sorted(per_kind.items())),
        "blocked_by_code": dict(sorted(blocked.items())),
    }
    payload = json.dumps(report, indent=2, sort_keys=True)
    if args.report:
        args.report.write_text(payload + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
