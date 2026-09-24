"""Idempotency and reconciliation for SAP purchase-order creates.

A PO create is claimed on a ``SapWriteIntent`` row keyed on the PR item before
it calls SAP, and settled from the envelope after. The row decides whether a
second approval of the same item may call SAP again:

- ``committed``: never. The PO exists; the refusal names it.
- ``pending``: never while the first call is in flight. A claim older than
  ``STALE_PENDING`` belongs to a process that died, and is treated as unknown.
- ``unknown``: never, until someone or a read of SAP resolves it.
- ``failed``: yes. SAP refused or the create was rolled back.

With the workspace flag ``sap_po_reconciliation`` (off by default, strict
boolean like ``sap_write_unsealed``) the create also reads SAP first: the PR
item is read by key and its ``PurchasingDocument`` says whether a PO already
references it. A PO found is recorded and refused, an unreadable SAP refuses
the write, and an unknown intent SAP shows no PO for becomes a failure that
may be retried. The create then carries a reference in ``POHEADER.COLLECT_NO``
so the PO can be found from the intent.
"""

from __future__ import annotations

import copy
import hashlib
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.exc import IntegrityError

from app.models.sap_write_intent import (
    COMMITTED,
    FAILED,
    PENDING,
    UNKNOWN,
    SapWriteIntent,
)

logger = logging.getLogger(__name__)

RECONCILIATION_FLAG = "sap_po_reconciliation"
READ_SERVER_ID = "sap"
STALE_PENDING = timedelta(minutes=15)

ALREADY_ORDERED = "already_ordered"
WRITE_IN_PROGRESS = "write_in_progress"
NEEDS_RECONCILIATION = "needs_reconciliation"
RECONCILIATION_UNAVAILABLE = "reconciliation_unavailable"


@dataclass
class IntentClaim:
    intent: SapWriteIntent | None = None
    refusal: dict[str, Any] | None = None


def reconciliation_enabled(workspace: Any) -> bool:
    settings = getattr(workspace, "settings", None)
    features = settings.get("features") if isinstance(settings, Mapping) else None
    return isinstance(features, Mapping) and features.get(RECONCILIATION_FLAG) is True


def normalize_item(pr_item: Any) -> str:
    """``10``, ``010`` and ``00010`` are one PR item."""
    text = str(pr_item or "").strip()
    return str(int(text)) if text.isdigit() else text


def reference_for(run_id: str | None, decision_id: str | None) -> str:
    """A 10-character handle SAP keeps on the PO header (``COLLECT_NO``)."""
    digest = hashlib.sha256(f"{run_id or ''}:{decision_id or ''}".encode()).hexdigest()
    return f"AG{digest[:8].upper()}"


def with_reference(arguments: Mapping[str, Any], reference: str) -> dict[str, Any]:
    """The BAPI_PO_CREATE1 body with the reference on the header, marked for update."""
    body = copy.deepcopy(dict(arguments))
    imported = body.setdefault("import", {})
    header = imported.setdefault("POHEADER", {})
    header_x = imported.setdefault("POHEADERX", {})
    header["COLLECT_NO"] = reference
    header_x["COLLECT_NO"] = "X"
    return body


def pr_item_key_arguments(pr_id: str, pr_item: str) -> dict[str, str]:
    return {
        "PurchaseRequisition": str(pr_id or "").strip(),
        "PurchaseRequisitionItem": normalize_item(pr_item),
    }


def _keyed_item(raw: Any, pr_id: str) -> Mapping[str, Any] | None:
    """The PR item a keyed read returned, whatever envelope the gateway used."""

    candidates: list[Mapping[str, Any]] = []
    if isinstance(raw, Mapping):
        candidates.append(raw)
        for key in ("d", "data", "result"):
            inner = raw.get(key)
            if isinstance(inner, Mapping):
                candidates.append(inner)
                results = inner.get("results")
                if isinstance(results, list) and len(results) == 1:
                    candidates.extend(row for row in results if isinstance(row, Mapping))
    for row in candidates:
        if str(row.get("PurchaseRequisition") or "").strip() == pr_id:
            return row
    return None


def find_existing_po(workspace: Any, pr_id: str, pr_item: str) -> tuple[str | None, str | None]:
    """(PO number or None, error or None) from the PR item SAP holds.

    SAP stamps ``PurchasingDocument`` on a requisition item once a PO references
    it, and the approved-PR list already filters on that field. The item is read
    by key on the server that lists the requisitions, so a create that did commit
    is seen on the system it committed to. A reply without the item, or without
    the field, is an error: no PO is believed only when SAP says so.
    """
    from app.services.connectors.mcp import read as mcp_read
    from app.services.connectors.mcp import service as mcp_service

    pr = str(pr_id or "").strip()
    item = normalize_item(pr_item)
    try:
        server = mcp_service.resolve_server(workspace, READ_SERVER_ID)
        out = mcp_read.read_rows(
            server,
            tool=mcp_read.LIVE_PR_ITEM_BY_KEY,
            arguments=pr_item_key_arguments(pr, item),
        )
    except Exception as exc:  # noqa: BLE001 - an unreadable SAP refuses the write
        return None, f"{type(exc).__name__}: {exc}"
    row = _keyed_item(out.get("result"), pr)
    if row is None:
        return None, f"SAP did not return PR item {pr}/{item}"
    fields = {str(key).lower(): value for key, value in row.items()}
    returned_item = fields.get("purchaserequisitionitem")
    if returned_item not in (None, "") and normalize_item(returned_item) != item:
        return None, f"SAP returned PR item {returned_item} for {pr}/{item}"
    if "purchasingdocument" not in fields:
        return None, f"SAP did not return PurchasingDocument for PR item {pr}/{item}"
    number = str(fields["purchasingdocument"] or "").strip()
    return (number or None), None


def _refusal(
    reason: str, detail: str, *, intent: SapWriteIntent | None = None, po_number: str = ""
) -> IntentClaim:
    return IntentClaim(
        refusal={
            "reason": reason,
            "detail": detail,
            "po_number": po_number or (intent.po_number if intent is not None else "") or "",
            "intent_id": intent.id if intent is not None else None,
        }
    )


def _row(db: Any, workspace_id: str, pr_id: str, pr_item: str) -> SapWriteIntent | None:
    return (
        db.query(SapWriteIntent)
        .filter(
            SapWriteIntent.workspace_id == workspace_id,
            SapWriteIntent.pr_id == pr_id,
            SapWriteIntent.pr_item == pr_item,
        )
        .first()
    )


def begin_create(
    db: Any,
    workspace: Any,
    *,
    pr_id: str,
    pr_item: str,
    run_id: str | None,
    decision_id: str | None,
    decided_by: str | None,
    server_id: str,
    tool: str,
    now: datetime | None = None,
) -> IntentClaim:
    """Claim the PR item for one create, or say why it must not call SAP."""

    now = now or datetime.utcnow()
    pr = str(pr_id or "").strip()
    item = normalize_item(pr_item)
    existing = _row(db, workspace.id, pr, item)
    if (
        existing is not None
        and existing.status == PENDING
        and existing.updated_at < now - STALE_PENDING
    ):
        existing.status = UNKNOWN
        existing.error = {"reason": "stale_pending", "since": existing.updated_at.isoformat()}
        existing.updated_at = now
        db.commit()

    if reconciliation_enabled(workspace):
        po_number, error = find_existing_po(workspace, pr, item)
        if error:
            return _refusal(
                RECONCILIATION_UNAVAILABLE,
                f"SAP could not be read before the write: {error}",
                intent=existing,
            )
        if po_number:
            if existing is None:
                existing = SapWriteIntent(
                    workspace_id=workspace.id,
                    pr_id=pr,
                    pr_item=item,
                    status=COMMITTED,
                    server_id=server_id,
                    tool=tool,
                    run_id=run_id,
                    decision_id=decision_id,
                    decided_by=decided_by,
                    created_at=now,
                    updated_at=now,
                )
                db.add(existing)
            existing.status = COMMITTED
            existing.po_number = po_number
            existing.resolved_by = "sap_read"
            existing.updated_at = now
            db.commit()
            return _refusal(
                ALREADY_ORDERED, f"SAP already has PO {po_number} for this PR item", intent=existing
            )
        if existing is not None and existing.status == UNKNOWN:
            # SAP shows no PO for the item: the unknown call did not commit.
            existing.status = FAILED
            existing.resolved_by = "sap_read"
            existing.updated_at = now
            db.commit()

    if existing is not None:
        if existing.status == COMMITTED:
            return _refusal(
                ALREADY_ORDERED,
                f"PO {existing.po_number or '?'} was already created for this PR item",
                intent=existing,
            )
        if existing.status == PENDING:
            return _refusal(
                WRITE_IN_PROGRESS,
                "Another approval of this PR item is calling SAP",
                intent=existing,
            )
        if existing.status == UNKNOWN:
            return _refusal(
                NEEDS_RECONCILIATION,
                "An earlier create of this PR item has an unknown outcome; check SAP and resolve the intent first",
                intent=existing,
            )
        claimed = (
            db.query(SapWriteIntent)
            .filter(SapWriteIntent.id == existing.id, SapWriteIntent.status == FAILED)
            .update(
                {
                    SapWriteIntent.status: PENDING,
                    SapWriteIntent.attempts: SapWriteIntent.attempts + 1,
                    SapWriteIntent.run_id: run_id,
                    SapWriteIntent.decision_id: decision_id,
                    SapWriteIntent.decided_by: decided_by,
                    SapWriteIntent.server_id: server_id,
                    SapWriteIntent.tool: tool,
                    SapWriteIntent.reference: reference_for(run_id, decision_id),
                    SapWriteIntent.error: None,
                    SapWriteIntent.resolved_by: None,
                    SapWriteIntent.updated_at: now,
                },
                synchronize_session=False,
            )
        )
        db.commit()
        if claimed != 1:
            return _refusal(
                WRITE_IN_PROGRESS,
                "Another approval of this PR item claimed it first",
                intent=existing,
            )
        db.refresh(existing)
        return IntentClaim(intent=existing)

    intent = SapWriteIntent(
        workspace_id=workspace.id,
        pr_id=pr,
        pr_item=item,
        status=PENDING,
        server_id=server_id,
        tool=tool,
        run_id=run_id,
        decision_id=decision_id,
        decided_by=decided_by,
        reference=reference_for(run_id, decision_id),
        attempts=1,
        created_at=now,
        updated_at=now,
    )
    try:
        with db.begin_nested():
            db.add(intent)
            db.flush()
    except IntegrityError:
        return _refusal(WRITE_IN_PROGRESS, "Another approval of this PR item claimed it first")
    db.commit()
    return IntentClaim(intent=intent)


def settle(
    db: Any, intent: SapWriteIntent, out: Mapping[str, Any], *, now: datetime | None = None
) -> None:
    """Record what the create's envelope says happened."""

    now = now or datetime.utcnow()
    committed = bool(out.get("committed")) if "committed" in out else bool(out.get("sap_ok"))
    if out.get("needs_reconciliation") or out.get("outcome") == "unknown":
        intent.status = UNKNOWN
        intent.error = out.get("error") or {"messages": out.get("messages")}
    elif out.get("called") and out.get("sap_ok") and committed:
        intent.status = COMMITTED
        intent.error = None
    else:
        intent.status = FAILED
        intent.error = {"reason": out.get("reason"), "messages": out.get("messages")}
    number = str(out.get("po_number") or "").strip()
    if number:
        intent.po_number = number
    intent.updated_at = now
    db.commit()


def fail(
    db: Any, intent: SapWriteIntent, error: BaseException, *, now: datetime | None = None
) -> None:
    """The write raised before anything reached SAP: a known failure."""

    intent.status = FAILED
    intent.error = {"reason": "raised_before_call", "message": f"{type(error).__name__}: {error}"}
    intent.updated_at = now or datetime.utcnow()
    db.commit()


def resolve(
    db: Any,
    intent: SapWriteIntent,
    *,
    status: str,
    actor: str,
    po_number: str | None = None,
    now: datetime | None = None,
) -> SapWriteIntent:
    """An operator's verdict on an unknown or stuck intent, after checking SAP."""

    if status not in {COMMITTED, FAILED}:
        raise ValueError("an intent resolves to committed or failed")
    if status == COMMITTED and not str(po_number or "").strip():
        raise ValueError("a committed intent needs the PO number SAP shows")
    intent.status = status
    if po_number:
        intent.po_number = str(po_number).strip()
    intent.resolved_by = actor
    intent.updated_at = now or datetime.utcnow()
    db.commit()
    return intent
