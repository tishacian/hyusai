"""Deterministic PR→PO helpers used by python_recipe nodes and tests.

The walker has a ``loop`` kind, but it only invokes one skill per item — it
cannot nest budget → decision → HITL. v1 therefore processes **one PR per
scheduled tick**: list, then select the pinned or first remaining approved PR.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta
from typing import Any, Mapping

ZNPR_PO_TYPE = "ZLPO"


def _row_pr_id(row: Mapping[str, Any]) -> str:
    return str(row.get("pr_id") or row.get("PurchaseRequisition") or "").strip()


def _row_material_group(row: Mapping[str, Any]) -> str:
    return str(row.get("MaterialGroup") or row.get("pr_type") or row.get("type") or "").strip()


def _row_supplier(row: Mapping[str, Any]) -> str:
    return str(row.get("supplier") or row.get("Supplier") or "").strip()


def _row_format(row: Mapping[str, Any]) -> str:
    return str(
        row.get("format") or row.get("PurchaseOrderType") or row.get("PaymentTerms") or ""
    ).strip()


def _row_pr_type(payload: Mapping[str, Any], pr: Mapping[str, Any] | None = None) -> str:
    row = pr if isinstance(pr, Mapping) else {}
    return str(
        payload.get("pr_type")
        or row.get("pr_type")
        or row.get("type")
        or row.get("PurchaseRequisitionType")
        or ""
    ).strip().upper()


def _qty_remaining(row: Mapping[str, Any]) -> bool:
    if "OrderedQuantity" not in row and "RequestedQuantity" not in row:
        return True
    try:
        ordered = float(row.get("OrderedQuantity") or 0)
        requested = float(row.get("RequestedQuantity") or 0)
    except (TypeError, ValueError):
        return True
    if requested <= 0:
        return True
    return ordered < requested


def pad_sap_item(item: str) -> str:
    digits = "".join(ch for ch in str(item or "") if ch.isdigit()) or "10"
    return digits.zfill(5)


def parse_sap_date(raw: str, today: date | None = None) -> date | None:
    text = str(raw or "").strip()
    if not text:
        return None
    if text.startswith("/Date(") and text.endswith(")/"):
        inner = text[6:-2]
        try:
            ms = int(inner.split(")")[0])
            return datetime.utcfromtimestamp(ms / 1000.0).date()
        except (TypeError, ValueError, OSError):
            return today
    compact = text.replace("-", "")
    if len(compact) >= 8 and compact[:8].isdigit():
        try:
            return date(int(compact[0:4]), int(compact[4:6]), int(compact[6:8]))
        except ValueError:
            return today
    return today


def override_delivery_date(raw: str, today: date | None = None) -> str:
    today = today or date.today()
    floor = today + timedelta(days=14)
    parsed = parse_sap_date(raw, today)
    chosen = parsed if parsed and parsed > floor else floor
    while chosen.weekday() >= 5:
        chosen += timedelta(days=1)
    return chosen.strftime("%Y%m%d")


def build_bapi_po_payload(
    *,
    pr_id: str,
    pr_item: str = "10",
    supplier: str,
    plant: str = "1000",
    currency: str = "QAR",
    net_price: str = "0.00",
    delivery_date: str = "",
    purch_group: str = "013",
    payment_terms: str = "ZAPS",
    incoterms: str = "DDP",
    today: date | None = None,
) -> dict[str, Any]:
    """Sealed BAPI_PO_CREATE1 body. No TESTRUN. No POACCOUNT. Dates YYYYMMDD.

    The live tool schema (bapi_po ``tools/list``, verified 2026-09-01) puts the
    header structures under ``import`` — ``import.POHEADER`` is the only
    required property — while the row tables stay under ``tables``.
    """
    plant_code = str(plant or "1000").strip() or "1000"
    po_item = "00010"
    preq_item = pad_sap_item(pr_item)
    inco = str(incoterms or "DDP").strip() or "DDP"
    delivery = override_delivery_date(delivery_date, today)
    return {
        "import": {
            "POHEADER": {
                "VENDOR": str(supplier or "").strip(),
                "COMP_CODE": plant_code,
                "DOC_TYPE": ZNPR_PO_TYPE,
                "PURCH_ORG": plant_code,
                "PUR_GROUP": str(purch_group or "013").strip() or "013",
                "CURRENCY": str(currency or "QAR").strip() or "QAR",
                "PMNTTRMS": str(payment_terms or "ZAPS").strip() or "ZAPS",
                "INCOTERMS1": inco,
                "INCOTERMS2": "Doha",
                "INCOTERMS2L": "Doha",
            },
            "POHEADERX": {
                "VENDOR": "X",
                "COMP_CODE": "X",
                "DOC_TYPE": "X",
                "PURCH_ORG": "X",
                "PUR_GROUP": "X",
                "CURRENCY": "X",
                "PMNTTRMS": "X",
                "INCOTERMS1": "X",
                "INCOTERMS2": "X",
                "INCOTERMS2L": "X",
            },
        },
        "tables": {
            "POITEM": [
                {
                    "PO_ITEM": po_item,
                    "PREQ_NO": str(pr_id or "").strip(),
                    "PREQ_ITEM": preq_item,
                    "NET_PRICE": str(net_price or "0.00"),
                    "PRICE_UNIT": "1",
                }
            ],
            "POITEMX": [
                {
                    "PO_ITEM": po_item,
                    "PO_ITEMX": "X",
                    "PREQ_NO": "X",
                    "PREQ_ITEM": "X",
                    "NET_PRICE": "X",
                    "PRICE_UNIT": "X",
                }
            ],
            "POSCHEDULE": [
                {"PO_ITEM": po_item, "SCHED_LINE": "0001", "DELIVERY_DATE": delivery}
            ],
            "POSCHEDULEX": [
                {
                    "PO_ITEM": po_item,
                    "SCHED_LINE": "0001",
                    "PO_ITEMX": "X",
                    "SCHED_LINEX": "X",
                    "DELIVERY_DATE": "X",
                }
            ],
        },
    }


CANDIDATE_CAP = 3


def _has_price(row: Mapping[str, Any]) -> bool:
    """SAP refuses a create at 0.00 (06/215 "Please enter net price")."""
    try:
        return float(row.get("PurchaseRequisitionPrice") or row.get("net_price") or 0) > 0
    except (TypeError, ValueError):
        return False


def candidate_rows(rows: list[dict[str, Any]], cap: int = CANDIDATE_CAP) -> list[dict[str, Any]]:
    """Distinct open requisitions, one row per PR, priced ones first.

    The first open item row of a PR wins. A zero-price PR only fills a slot
    no priced PR could take, so the gate proposes what SAP will accept.
    """
    seen: set[str] = set()
    priced: list[dict[str, Any]] = []
    unpriced: list[dict[str, Any]] = []
    for row in rows:
        if len(priced) >= cap:
            break
        if not _qty_remaining(row):
            continue
        pr_id = _row_pr_id(row)
        if not pr_id or pr_id in seen:
            continue
        seen.add(pr_id)
        (priced if _has_price(row) else unpriced).append(row)
    return (priced + unpriced)[:cap]


def select_next_pr(payload: Mapping[str, Any]) -> dict[str, Any]:
    prs = payload.get("prs")
    rows = [dict(item) for item in prs if isinstance(item, Mapping)] if isinstance(prs, list) else []
    pin = str(payload.get("pr_id") or "").strip()
    candidates = candidate_rows(rows)
    chosen = None
    if pin:
        chosen = next(
            (row for row in rows if _row_pr_id(row) == pin and _qty_remaining(row)),
            None,
        )
    if chosen is None:
        chosen = candidates[0] if candidates else None
    base = {
        "candidates": [_row_pr_id(row) for row in candidates],
        "total_open": len(rows),
        "prs": rows,
    }
    if not isinstance(chosen, dict):
        return {
            **base,
            "pr_id": "",
            "pr": None,
            "pr_type": "",
            "MaterialGroup": "",
            "Plant": "",
            "PurchaseRequisitionItem": "",
            "price_missing": False,
            "empty": True,
        }
    pr_id = _row_pr_id(chosen)
    material_group = _row_material_group(chosen)
    return {
        **base,
        "pr_id": pr_id,
        "pr": chosen,
        "pr_type": str(chosen.get("pr_type") or chosen.get("type") or chosen.get("PurchaseRequisitionType") or ""),
        "MaterialGroup": material_group,
        "Plant": str(chosen.get("Plant") or ""),
        "PurchaseRequisitionItem": str(chosen.get("PurchaseRequisitionItem") or "10"),
        "price_missing": not _has_price(chosen),
        "empty": False,
    }


def majority_supplier_format(payload: Mapping[str, Any]) -> dict[str, Any]:
    pos = payload.get("pos")
    rows = [dict(item) for item in pos] if isinstance(pos, list) else []
    pr = payload.get("pr") if isinstance(payload.get("pr"), Mapping) else {}
    if not rows:
        return {
            "supplier": "",
            "format": "",
            "vote_count": 0,
            "pos": rows,
            "proposed_po": {},
        }
    pr_type = _row_pr_type(payload, pr)
    purch_group = ""
    payment_terms = ""
    incoterms = ""
    if pr_type == "ZNPR":
        first = rows[0]
        supplier = _row_supplier(first)
        shared_format = ZNPR_PO_TYPE
        purch_group = str(first.get("PurchasingGroup") or first.get("purch_group") or "").strip()
        payment_terms = str(first.get("PaymentTerms") or first.get("payment_terms") or "").strip()
        incoterms = (
            str(first.get("IncotermsClassification") or first.get("incoterms") or "DDP").strip()
            or "DDP"
        )
        currency = str(pr.get("PurReqnItemCurrency") or pr.get("currency") or "QAR")
        vote_count = sum(1 for row in rows if _row_supplier(row) == supplier)
    else:
        suppliers = Counter(_row_supplier(row) for row in rows if _row_supplier(row))
        supplier = suppliers.most_common(1)[0][0] if suppliers else ""
        formats = Counter(
            _row_format(row)
            for row in rows
            if _row_supplier(row) == supplier and _row_format(row)
        )
        shared_format = formats.most_common(1)[0][0] if formats else ""
        currency = str(pr.get("currency") or "QAR")
        vote_count = suppliers.get(supplier, 0)
    pr_id = str(payload.get("pr_id") or pr.get("pr_id") or pr.get("PurchaseRequisition") or "")
    proposed = {
        "pr_id": pr_id,
        "supplier": supplier,
        "format": shared_format,
        "amount": pr.get("amount"),
        "currency": currency,
        "pr_type": str(payload.get("pr_type") or pr.get("pr_type") or pr.get("type") or pr_type),
        "purch_group": purch_group,
        "payment_terms": payment_terms,
        "incoterms": incoterms,
        "plant": str(pr.get("Plant") or payload.get("Plant") or ""),
    }
    justification = str(payload.get("justification") or "")
    summary_prompt = (
        "Summarise this purchase-requisition justification in two short sentences. "
        "Do not decide to reject or approve. Do not invent a supplier.\n\n"
        f"{justification}"
    )
    return {
        "supplier": supplier,
        "format": shared_format,
        "vote_count": vote_count,
        "pos": rows,
        "proposed_po": proposed,
        "summary_prompt": summary_prompt,
        "pr_id": pr_id,
        "pr": dict(pr) if pr else {},
        "justification": justification,
        "purch_group": purch_group,
        "payment_terms": payment_terms,
        "incoterms": incoterms,
    }


FORMAT_REQUIREMENTS = "tabulate>=0.9.0"

FORMAT_TEST_INPUT = (
    '{"pr":{"pr_id":"PR-4402","title":"Laptop replacements","amount":12000,'
    '"currency":"QAR"},"pr_id":"PR-4402","supplier":"ACME","format":"XML",'
    '"vote_count":2,"proposed_po":{"pr_id":"PR-4402","supplier":"ACME",'
    '"format":"XML"},"summary_prompt":"Summarise this purchase-requisition '
    'justification in two short sentences.","justification":"Finance laptops '
    'are past refresh."}'
)


def format_dossier(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Mirror of FORMAT_CODE for in-process walker tests.

    The live node imports ``tabulate`` from the managed venv. This helper
    keeps the same keys so the DAG can walk without that package in pytest.
    """

    pr = payload.get("pr") if isinstance(payload.get("pr"), Mapping) else {}
    supplier = str(payload.get("supplier") or "")
    order_format = str(payload.get("format") or "")
    vote_count = payload.get("vote_count") or 0
    pr_id = str(payload.get("pr_id") or pr.get("pr_id") or "")
    rows = [
        ("PR", pr_id),
        ("Title", str(pr.get("title") or pr.get("PurReqnDescription") or pr.get("PurchaseRequisitionItemText") or "")),
        ("Supplier", supplier),
        ("Order type", order_format),
        ("Votes", vote_count),
        ("Amount", pr.get("amount") or pr.get("TotalNetAmount") or ""),
        ("Currency", pr.get("currency") or "QAR"),
    ]
    version = ""
    try:
        from tabulate import tabulate as _tabulate
        import tabulate as tabulate_mod

        table = _tabulate(rows, headers=["Field", "Value"], tablefmt="github")
        version = str(getattr(tabulate_mod, "__version__", "") or "")
    except ImportError:
        table = "| Field | Value |\n| --- | --- |\n" + "\n".join(
            f"| {field} | {value} |" for field, value in rows
        )
    return {
        "formatted": table,
        "recipe_package": "tabulate",
        "recipe_package_version": version,
        "supplier": supplier,
        "format": order_format,
        "vote_count": vote_count,
        "pr_id": pr_id,
        "pr": dict(pr) if pr else {},
        "proposed_po": (
            dict(payload.get("proposed_po"))
            if isinstance(payload.get("proposed_po"), Mapping)
            else {}
        ),
        "summary_prompt": str(payload.get("summary_prompt") or ""),
        "justification": str(payload.get("justification") or ""),
    }


SELECT_PR_CODE = '''"""Pick the next approved PR for this scheduled tick."""

def _pr_id(row):
    return str((row or {}).get("pr_id") or (row or {}).get("PurchaseRequisition") or "").strip()

def _qty_remaining(row):
    if "OrderedQuantity" not in row and "RequestedQuantity" not in row:
        return True
    try:
        ordered = float(row.get("OrderedQuantity") or 0)
        requested = float(row.get("RequestedQuantity") or 0)
    except (TypeError, ValueError):
        return True
    if requested <= 0:
        return True
    return ordered < requested

def _has_price(row):
    # SAP refuses a create at 0.00 (06/215 "Please enter net price").
    try:
        return float(row.get("PurchaseRequisitionPrice") or row.get("net_price") or 0) > 0
    except (TypeError, ValueError):
        return False

def _candidates(rows, cap=3):
    # Distinct open PRs, first item row wins, priced before unpriced.
    seen, priced, unpriced = set(), [], []
    for row in rows:
        if len(priced) >= cap:
            break
        if not _qty_remaining(row):
            continue
        pr_id = _pr_id(row)
        if not pr_id or pr_id in seen:
            continue
        seen.add(pr_id)
        (priced if _has_price(row) else unpriced).append(row)
    return (priced + unpriced)[:cap]

def main(inputs):
    prs = [row for row in (inputs.get("prs") or []) if isinstance(row, dict)]
    pin = str(inputs.get("pr_id") or "").strip()
    candidates = _candidates(prs)
    chosen = None
    if pin:
        for row in prs:
            if _pr_id(row) == pin and _qty_remaining(row):
                chosen = row
                break
    if chosen is None and candidates:
        chosen = candidates[0]
    base = {"candidates": [_pr_id(row) for row in candidates], "total_open": len(prs), "prs": prs}
    if not isinstance(chosen, dict):
        base.update({"pr_id": "", "pr": None, "pr_type": "", "MaterialGroup": "", "Plant": "", "PurchaseRequisitionItem": "", "price_missing": False, "empty": True})
        return base
    base.update({
        "pr_id": _pr_id(chosen),
        "pr": chosen,
        "pr_type": str(chosen.get("pr_type") or chosen.get("type") or chosen.get("PurchaseRequisitionType") or ""),
        "MaterialGroup": str(chosen.get("MaterialGroup") or chosen.get("pr_type") or chosen.get("type") or ""),
        "Plant": str(chosen.get("Plant") or ""),
        "PurchaseRequisitionItem": str(chosen.get("PurchaseRequisitionItem") or "10"),
        "price_missing": not _has_price(chosen),
        "empty": False,
    })
    return base
'''

MAJORITY_CODE = '''"""Supplier and format from plant POs (ZNPR→ZLPO) or majority vote (fixtures)."""

from collections import Counter

def main(inputs):
    pos = [row for row in (inputs.get("pos") or []) if isinstance(row, dict)]
    pr = inputs.get("pr") if isinstance(inputs.get("pr"), dict) else {}
    if not pos:
        return {
            "supplier": "",
            "format": "",
            "vote_count": 0,
            "pos": pos,
            "proposed_po": {},
            "summary_prompt": "",
            "pr_id": str(inputs.get("pr_id") or ""),
            "pr": pr,
            "justification": str(inputs.get("justification") or ""),
        }
    def _supplier(row):
        return str(row.get("supplier") or row.get("Supplier") or "").strip()
    def _fmt(row):
        return str(row.get("format") or row.get("PurchaseOrderType") or row.get("PaymentTerms") or "").strip()
    pr_type = str(
        inputs.get("pr_type") or pr.get("pr_type") or pr.get("type") or pr.get("PurchaseRequisitionType") or ""
    ).strip().upper()
    purch_group = ""
    payment_terms = ""
    incoterms = ""
    if pr_type == "ZNPR":
        first = pos[0]
        supplier = _supplier(first)
        shared = "ZLPO"
        purch_group = str(first.get("PurchasingGroup") or first.get("purch_group") or "").strip()
        payment_terms = str(first.get("PaymentTerms") or first.get("payment_terms") or "").strip()
        incoterms = str(first.get("IncotermsClassification") or first.get("incoterms") or "DDP").strip() or "DDP"
        currency = str(pr.get("PurReqnItemCurrency") or pr.get("currency") or "QAR")
        vote_count = sum(1 for row in pos if _supplier(row) == supplier)
    else:
        suppliers = Counter(_supplier(row) for row in pos if _supplier(row))
        supplier = suppliers.most_common(1)[0][0] if suppliers else ""
        formats = Counter(_fmt(row) for row in pos if _supplier(row) == supplier and _fmt(row))
        shared = formats.most_common(1)[0][0] if formats else ""
        currency = str(pr.get("currency") or "QAR")
        vote_count = suppliers.get(supplier, 0)
    pr_id = str(inputs.get("pr_id") or pr.get("pr_id") or pr.get("PurchaseRequisition") or "")
    justification = str(inputs.get("justification") or "")
    return {
        "supplier": supplier,
        "format": shared,
        "vote_count": vote_count,
        "pos": pos,
        "proposed_po": {
            "pr_id": pr_id,
            "supplier": supplier,
            "format": shared,
            "amount": pr.get("amount"),
            "currency": currency,
            "pr_type": str(inputs.get("pr_type") or pr.get("pr_type") or pr.get("type") or pr_type),
            "purch_group": purch_group,
            "payment_terms": payment_terms,
            "incoterms": incoterms,
            "plant": str(pr.get("Plant") or inputs.get("Plant") or ""),
        },
        "summary_prompt": (
            "Summarise this purchase-requisition justification in two short sentences. "
            "Do not decide to reject or approve. Do not invent a supplier.\\n\\n"
            + justification
        ),
        "pr_id": pr_id,
        "pr": pr,
        "justification": justification,
        "purch_group": purch_group,
        "payment_terms": payment_terms,
        "incoterms": incoterms,
    }
'''

FORMAT_CODE = '''"""Format the compiled PR-to-PO dossier. Requires tabulate in the managed env."""

import tabulate
from tabulate import tabulate as render_table


def main(inputs):
    pr = inputs.get("pr") if isinstance(inputs.get("pr"), dict) else {}
    supplier = str(inputs.get("supplier") or "")
    order_format = str(inputs.get("format") or "")
    vote_count = inputs.get("vote_count") or 0
    pr_id = str(inputs.get("pr_id") or pr.get("pr_id") or "")
    rows = [
        ["PR", pr_id],
        ["Title", str(pr.get("title") or pr.get("PurReqnDescription") or pr.get("PurchaseRequisitionItemText") or "")],
        ["Supplier", supplier],
        ["Order type", order_format],
        ["Votes", vote_count],
        ["Amount", pr.get("amount") or pr.get("TotalNetAmount") or ""],
        ["Currency", pr.get("currency") or "QAR"],
    ]
    return {
        "formatted": render_table(rows, headers=["Field", "Value"], tablefmt="github"),
        "recipe_package": "tabulate",
        "recipe_package_version": str(getattr(tabulate, "__version__", "") or ""),
        "supplier": supplier,
        "format": order_format,
        "vote_count": vote_count,
        "pr_id": pr_id,
        "pr": pr,
        "proposed_po": inputs.get("proposed_po") if isinstance(inputs.get("proposed_po"), dict) else {},
        "summary_prompt": str(inputs.get("summary_prompt") or ""),
        "justification": str(inputs.get("justification") or ""),
    }
'''
