"""List SAP write intents and resolve the ones SAP left unknown.

Examples::

    python -m scripts.sap_write_intents list --status unknown
    python -m scripts.sap_write_intents list --workspace-id <uuid>
    python -m scripts.sap_write_intents resolve --intent-id <uuid> \
        --as committed --po-number 4500999001 --actor operator@example.net
    python -m scripts.sap_write_intents resolve --intent-id <uuid> \
        --as failed --actor operator@example.net

A PO create claims one ``sap_write_intents`` row per PR item before it calls
SAP. When the call leaves and no answer comes back, the row says ``unknown``
and every later approval of that item is refused: SAP may hold the PO. Check
SAP (ME23N, or the PO items of the requisition), then record what it shows:
``committed`` with the PO number, or ``failed`` so a new approval may try again.
With the workspace flag ``sap_po_reconciliation`` on, the create reads SAP
itself and this step is only needed when SAP could not be read.
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
from app.models.sap_write_intent import INTENT_STATUSES, SapWriteIntent  # noqa: E402
from app.services.connectors.mcp import intents  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    listing = sub.add_parser("list", help="Show intents")
    listing.add_argument("--status", choices=INTENT_STATUSES)
    listing.add_argument("--workspace-id")
    resolving = sub.add_parser("resolve", help="Record what SAP shows for one intent")
    resolving.add_argument("--intent-id", required=True)
    resolving.add_argument("--as", dest="status", required=True, choices=("committed", "failed"))
    resolving.add_argument("--po-number")
    resolving.add_argument("--actor", required=True)
    return parser.parse_args(argv)


def _row(intent: SapWriteIntent) -> dict[str, Any]:
    return {
        "id": intent.id,
        "workspace_id": intent.workspace_id,
        "pr_id": intent.pr_id,
        "pr_item": intent.pr_item,
        "status": intent.status,
        "po_number": intent.po_number,
        "reference": intent.reference,
        "run_id": intent.run_id,
        "decision_id": intent.decision_id,
        "decided_by": intent.decided_by,
        "attempts": intent.attempts,
        "resolved_by": intent.resolved_by,
        "error": intent.error,
        "updated_at": intent.updated_at.isoformat() if intent.updated_at else None,
    }


def run(db: Any, args: argparse.Namespace) -> dict[str, Any]:
    if args.command == "list":
        query = db.query(SapWriteIntent)
        if args.status:
            query = query.filter(SapWriteIntent.status == args.status)
        if args.workspace_id:
            query = query.filter(SapWriteIntent.workspace_id == args.workspace_id)
        return {"intents": [_row(row) for row in query.order_by(SapWriteIntent.updated_at.desc()).all()]}
    intent = db.query(SapWriteIntent).filter(SapWriteIntent.id == args.intent_id).first()
    if intent is None:
        raise SystemExit(f"no intent {args.intent_id}")
    before = intent.status
    intents.resolve(db, intent, status=args.status, actor=args.actor, po_number=args.po_number)
    from app.services.audit_logger import emit_audit_event

    emit_audit_event(
        workspace_id=intent.workspace_id,
        event_type="mcp.write.intent_resolved",
        actor=args.actor,
        details={"intent_id": intent.id, "from": before, "to": intent.status, "po_number": intent.po_number},
    )
    return {"resolved": _row(intent), "from": before}


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    db = SessionLocal()
    try:
        print(json.dumps(run(db, args), indent=2, ensure_ascii=False, default=str))
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
